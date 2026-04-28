from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable

from nc_time_twin.core.ir.blocks import (
    ArcMoveBlock,
    BaseBlock,
    LinearMoveBlock,
    Position,
    RapidMoveBlock,
)
from nc_time_twin.core.machine.profile import MachineProfile


EPSILON = 1e-9


@dataclass
class MotionSegment:
    segment_id: int
    block_index: int
    block: RapidMoveBlock | LinearMoveBlock | ArcMoveBlock
    motion_type: str
    start_pos: Position
    end_pos: Position
    length: float
    direction: tuple[float, float, float]
    commanded_feed_mm_s: float
    v_cap: float = 0.0
    a_cap: float = 0.0
    j_cap: float = 0.0
    axis_delta: dict[str, float] = field(default_factory=dict)
    entry_velocity: float = 0.0
    exit_velocity: float = 0.0
    peak_velocity: float = 0.0
    estimated_time: float = 0.0
    profile_type: str = ""
    dynamic_profile: list[dict[str, float | int | str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bottleneck_reasons: list[str] = field(default_factory=list)


@dataclass
class Junction:
    index: int
    prev_segment_id: int
    next_segment_id: int
    angle_rad: float
    tolerance: float
    v_junction_limit: float
    reason: str

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "index": self.index,
            "prev_segment_id": self.prev_segment_id,
            "next_segment_id": self.next_segment_id,
            "angle_deg": math.degrees(self.angle_rad),
            "tolerance_mm": self.tolerance,
            "v_junction_limit_mm_s": self.v_junction_limit,
            "reason": self.reason,
        }


@dataclass
class TransitionResult:
    time: float
    distance: float
    t_j: float = 0.0
    t_a: float = 0.0
    profile_type: str = "no_change"


@dataclass
class SegmentProfile:
    total_time: float
    peak_velocity: float
    profile_type: str
    samples: list[dict[str, float | int | str]]


def estimate_program_time_phase2(
    program: list[BaseBlock],
    machine_profile: MachineProfile,
    *,
    effective_feed_unit: str,
    stats,
) -> None:
    current_time = 0.0
    pending_motion: list[tuple[int, RapidMoveBlock | LinearMoveBlock | ArcMoveBlock]] = []
    phase2_junctions: list[dict[str, float | int | str]] = []
    phase2_bottlenecks: list[dict[str, float | int | str]] = []
    phase2_samples: list[dict[str, float | int | str]] = []
    segment_count = 0

    _reset_phase2_fields(program)

    def flush_motion_group() -> None:
        nonlocal current_time, segment_count
        if not pending_motion:
            return
        motion_time, group_metadata = _estimate_motion_group(
            pending_motion,
            machine_profile,
            effective_feed_unit=effective_feed_unit,
            stats=stats,
            start_time=current_time,
            segment_id_start=segment_count,
        )
        current_time += motion_time
        segment_count += int(group_metadata["segment_count"])
        phase2_junctions.extend(group_metadata["junctions"])
        phase2_bottlenecks.extend(group_metadata["bottlenecks"])
        phase2_samples.extend(group_metadata["dynamic_samples"])
        pending_motion.clear()

    for block_index, block in enumerate(program):
        if isinstance(block, (RapidMoveBlock, LinearMoveBlock, ArcMoveBlock)):
            pending_motion.append((block_index, block))
            continue

        flush_motion_group()
        from nc_time_twin.core.simulation.time_estimator import estimate_block_time

        estimate_block_time(block, machine_profile, effective_feed_unit=effective_feed_unit, stats=stats)
        current_time += block.estimated_time

    flush_motion_group()

    if hasattr(program, "metadata"):
        program.metadata["phase2"] = {
            "enabled": True,
            "summary": {
                "phase2_segment_count": segment_count,
                "phase2_junction_count": len(phase2_junctions),
                "phase2_bottleneck_count": len(phase2_bottlenecks),
                "phase2_dynamic_sample_count": len(phase2_samples),
            },
            "junctions": phase2_junctions,
            "bottlenecks": phase2_bottlenecks,
            "dynamic_samples": phase2_samples,
        }


def s_curve_transition(v0: float, v1: float, a_max: float, j_max: float) -> TransitionResult:
    dv = abs(v1 - v0)
    if dv <= EPSILON:
        return TransitionResult(time=0.0, distance=0.0)
    if a_max <= EPSILON or j_max <= EPSILON:
        time = dv / max(a_max, EPSILON)
        return TransitionResult(time=time, distance=((v0 + v1) / 2.0) * time, profile_type="linear_acc_fallback")

    dv_threshold = a_max * a_max / j_max
    if dv <= dv_threshold:
        t_j = math.sqrt(dv / j_max)
        total_time = 2.0 * t_j
        return TransitionResult(
            time=total_time,
            distance=((v0 + v1) / 2.0) * total_time,
            t_j=t_j,
            t_a=0.0,
            profile_type="triangular_s_curve",
        )

    t_j = a_max / j_max
    t_a = (dv - dv_threshold) / a_max
    total_time = 2.0 * t_j + t_a
    return TransitionResult(
        time=total_time,
        distance=((v0 + v1) / 2.0) * total_time,
        t_j=t_j,
        t_a=t_a,
        profile_type="full_s_curve",
    )


def compute_s_curve_segment_profile(segment: MotionSegment, machine_profile: MachineProfile) -> SegmentProfile:
    s = segment.length
    v_cap = max(0.0, segment.v_cap)
    v0 = min(max(0.0, segment.entry_velocity), v_cap)
    v1 = min(max(0.0, segment.exit_velocity), v_cap)
    a = segment.a_cap
    j = segment.j_cap

    if s <= EPSILON or v_cap <= EPSILON:
        return SegmentProfile(total_time=0.0, peak_velocity=0.0, profile_type="zero_motion", samples=[])

    acc = s_curve_transition(v0, v_cap, a, j)
    dec = s_curve_transition(v_cap, v1, a, j)
    distance_need = acc.distance + dec.distance

    if distance_need <= s:
        cruise_distance = s - distance_need
        cruise_time = cruise_distance / v_cap if v_cap > EPSILON else 0.0
        samples = build_dynamic_profile(v0, v_cap, v1, acc, dec, cruise_time, segment, machine_profile)
        return SegmentProfile(
            total_time=acc.time + cruise_time + dec.time,
            peak_velocity=v_cap,
            profile_type="full_s_curve_with_cruise",
            samples=samples,
        )

    v_peak = solve_reachable_peak_velocity(s, v0, v1, v_cap, a, j)
    acc = s_curve_transition(v0, v_peak, a, j)
    dec = s_curve_transition(v_peak, v1, a, j)
    samples = build_dynamic_profile(v0, v_peak, v1, acc, dec, 0.0, segment, machine_profile)
    return SegmentProfile(
        total_time=acc.time + dec.time,
        peak_velocity=v_peak,
        profile_type="degraded_s_curve_no_cruise",
        samples=samples,
    )


def solve_reachable_peak_velocity(
    distance: float,
    v0: float,
    v1: float,
    v_cap: float,
    a_max: float,
    j_max: float,
    *,
    iterations: int = 60,
) -> float:
    low = min(v_cap, max(v0, v1))
    high = max(low, v_cap)
    for _ in range(iterations):
        mid = (low + high) / 2.0
        required = s_curve_transition(v0, mid, a_max, j_max).distance + s_curve_transition(
            mid, v1, a_max, j_max
        ).distance
        if required <= distance:
            low = mid
        else:
            high = mid
    return low


def build_dynamic_profile(
    v0: float,
    v_peak: float,
    v1: float,
    acc_transition: TransitionResult,
    dec_transition: TransitionResult,
    cruise_time: float,
    segment: MotionSegment,
    machine_profile: MachineProfile,
) -> list[dict[str, float | int | str]]:
    phases = [
        *_transition_phases(v0, v_peak, acc_transition, segment.j_cap),
        (max(0.0, cruise_time), 0.0),
        *_transition_phases(v_peak, v1, dec_transition, segment.j_cap),
    ]
    total_time = sum(duration for duration, _ in phases)
    if total_time <= EPSILON:
        return []

    dt = machine_profile.controller.interpolation_period_ms / 1000.0
    max_samples = machine_profile.controller.phase2_max_samples_per_block
    if total_time / dt > max_samples:
        dt = total_time / max_samples

    samples: list[dict[str, float | int | str]] = []
    elapsed_total = 0.0
    s_accum = 0.0
    current_v = v0
    current_a = 0.0
    for duration, jerk in phases:
        phase_elapsed = 0.0
        while phase_elapsed < duration - EPSILON:
            step = min(dt, duration - phase_elapsed)
            v_before = current_v
            a_before = current_a
            s_accum += v_before * step + 0.5 * a_before * step * step + (jerk * step**3) / 6.0
            current_v = max(0.0, v_before + a_before * step + 0.5 * jerk * step * step)
            current_a = a_before + jerk * step
            elapsed_total += step
            phase_elapsed += step
            samples.append(
                {
                    "time_sec": elapsed_total,
                    "position_s_mm": max(0.0, min(segment.length, s_accum)),
                    "velocity_mm_s": current_v,
                    "acceleration_mm_s2": current_a,
                    "jerk_mm_s3": jerk,
                    "segment_id": segment.segment_id,
                    "block_index": segment.block_index,
                    "line_no": segment.block.line_no,
                    "motion_type": segment.motion_type,
                }
            )
        if abs(jerk) <= EPSILON:
            current_a = 0.0
    return samples


def _estimate_motion_group(
    motion_blocks: list[tuple[int, RapidMoveBlock | LinearMoveBlock | ArcMoveBlock]],
    machine_profile: MachineProfile,
    *,
    effective_feed_unit: str,
    stats,
    start_time: float,
    segment_id_start: int,
) -> tuple[float, dict[str, object]]:
    segments = build_motion_segments(
        motion_blocks,
        machine_profile,
        effective_feed_unit=effective_feed_unit,
        stats=stats,
        segment_id_start=segment_id_start,
    )
    if not segments:
        return 0.0, {"segment_count": 0, "junctions": [], "bottlenecks": [], "dynamic_samples": []}

    for segment in segments:
        apply_kinematic_mapping(segment, machine_profile)
        compute_segment_limits(segment, machine_profile)

    junctions = compute_all_junction_limits(segments, machine_profile)
    node_velocities = initialize_node_velocities(segments, junctions)
    node_velocities = bidirectional_lookahead(segments, node_velocities, machine_profile)
    assign_entry_exit_velocity(segments, node_velocities)

    dynamic_samples: list[dict[str, float | int | str]] = []
    motion_elapsed = 0.0
    for segment in segments:
        profile = compute_s_curve_segment_profile(segment, machine_profile)
        segment.estimated_time = profile.total_time
        segment.peak_velocity = profile.peak_velocity
        segment.profile_type = profile.profile_type
        segment.dynamic_profile = profile.samples
        segment.block.estimated_time += segment.estimated_time
        _merge_segment_diagnostics_into_block(segment)
        for sample in segment.dynamic_profile:
            global_sample = dict(sample)
            global_sample["time_sec"] = float(global_sample["time_sec"]) + start_time + motion_elapsed
            dynamic_samples.append(global_sample)
            segment.block.phase2_dynamic_samples.append(global_sample)
        motion_elapsed += segment.estimated_time

    bottlenecks = detect_bottlenecks(segments)
    _merge_bottlenecks_into_blocks(segments)
    return motion_elapsed, {
        "segment_count": len(segments),
        "junctions": [junction.to_dict() for junction in junctions],
        "bottlenecks": bottlenecks,
        "dynamic_samples": dynamic_samples,
    }


def build_motion_segments(
    motion_blocks: Iterable[tuple[int, RapidMoveBlock | LinearMoveBlock | ArcMoveBlock]],
    machine_profile: MachineProfile,
    *,
    effective_feed_unit: str,
    stats,
    segment_id_start: int = 0,
) -> list[MotionSegment]:
    segments: list[MotionSegment] = []
    segment_id = segment_id_start
    for block_index, block in motion_blocks:
        if isinstance(block, RapidMoveBlock):
            block.estimated_time = 0.0
            if block.start is None or block.end is None:
                continue
            segment = _create_segment(
                segment_id,
                block_index,
                block,
                "rapid",
                block.start,
                block.end,
                machine_profile.rapid_feed_mm_min / 60.0,
            )
            segment_id += 1
            if segment.length > EPSILON:
                segments.append(segment)
            continue

        from nc_time_twin.core.simulation.time_estimator import compute_feed_move_time

        compute_feed_move_time(block, machine_profile, effective_feed_unit, stats)
        block.estimated_time = 0.0
        feed_mm_s = (block.effective_feed_mm_min or machine_profile.default_cut_feed_mm_min) / 60.0
        if isinstance(block, LinearMoveBlock):
            if block.start is None or block.end is None:
                continue
            segment = _create_segment(segment_id, block_index, block, "linear", block.start, block.end, feed_mm_s)
            segment_id += 1
            if segment.length > EPSILON:
                segments.append(segment)
        elif isinstance(block, ArcMoveBlock):
            arc_segments = discretize_arc_block(block, machine_profile, block_index, segment_id, feed_mm_s)
            segment_id += len(arc_segments)
            segments.extend(arc_segments)
    return segments


def discretize_arc_block(
    block: ArcMoveBlock,
    machine_profile: MachineProfile,
    block_index: int,
    segment_id_start: int,
    feed_mm_s: float,
) -> list[MotionSegment]:
    arc = _arc_definition(block)
    if arc is None:
        if block.start is None or block.end is None:
            return []
        block.warnings.append("Phase 2 arc discretization fell back to chord segment")
        return [_create_segment(segment_id_start, block_index, block, "arc_discretized", block.start, block.end, feed_mm_s)]

    center_1, center_2, radius, start_angle, sweep, out_delta = arc
    if radius <= EPSILON or abs(sweep) <= EPSILON:
        return []

    tolerance = machine_profile.arc_chord_tolerance_mm
    ratio = max(-1.0, min(1.0, 1.0 - tolerance / radius))
    max_delta = 2.0 * math.acos(ratio)
    if max_delta <= EPSILON:
        max_delta = abs(sweep)
    segment_count = max(1, math.ceil(abs(sweep) / max_delta))

    segments: list[MotionSegment] = []
    previous = block.start
    if previous is None:
        return []
    for index in range(1, segment_count + 1):
        fraction = index / segment_count
        theta = start_angle + sweep * fraction
        next_pos = _arc_point(block, center_1, center_2, radius, theta, out_delta * fraction)
        segment = _create_segment(
            segment_id_start + index - 1,
            block_index,
            block,
            "arc_discretized",
            previous,
            next_pos,
            feed_mm_s,
        )
        if segment.length > EPSILON:
            segments.append(segment)
        previous = next_pos
    return segments


def apply_kinematic_mapping(segment: MotionSegment, machine_profile: MachineProfile) -> None:
    if machine_profile.kinematic_type != "3_axis":
        raise ValueError("phase 2 MVP supports only 3_axis kinematics")
    segment.axis_delta = {
        "X": segment.end_pos.x - segment.start_pos.x,
        "Y": segment.end_pos.y - segment.start_pos.y,
        "Z": segment.end_pos.z - segment.start_pos.z,
    }


def compute_segment_limits(segment: MotionSegment, machine_profile: MachineProfile) -> None:
    axis_length = math.sqrt(sum(delta * delta for delta in segment.axis_delta.values()))
    if axis_length <= EPSILON:
        segment.v_cap = segment.a_cap = segment.j_cap = 0.0
        segment.warnings.append("Zero axis movement")
        return

    v_limits: list[float] = []
    a_limits: list[float] = []
    j_limits: list[float] = []
    for axis, delta in segment.axis_delta.items():
        unit = delta / axis_length
        if abs(unit) <= EPSILON:
            continue
        axis_profile = machine_profile.axis(axis)
        if segment.motion_type == "rapid":
            v_limits.append((axis_profile.rapid_velocity_mm_min / 60.0) / abs(unit))
        else:
            v_limits.append((axis_profile.max_velocity_mm_min / 60.0) / abs(unit))
        a_limits.append(axis_profile.max_acc_mm_s2 / abs(unit))
        j_limits.append(axis_profile.max_jerk_mm_s3 / abs(unit))

    axis_v_cap = min(v_limits) if v_limits else 0.0
    axis_a_cap = min(a_limits) if a_limits else 0.0
    axis_j_cap = min(j_limits) if j_limits else 0.0
    if segment.motion_type == "rapid":
        segment.v_cap = min(segment.commanded_feed_mm_s, axis_v_cap, machine_profile.rapid_feed_mm_min / 60.0)
        segment.a_cap = axis_a_cap
        segment.j_cap = axis_j_cap
    else:
        segment.v_cap = min(segment.commanded_feed_mm_s, axis_v_cap, machine_profile.max_cut_feed_mm_min / 60.0)
        segment.a_cap = min(axis_a_cap, machine_profile.default_cut_acc_mm_s2)
        segment.j_cap = min(axis_j_cap, machine_profile.default_cut_jerk_mm_s3)


def compute_junction_velocity(
    prev_segment: MotionSegment,
    next_segment: MotionSegment,
    machine_profile: MachineProfile,
) -> tuple[float, str, float]:
    if prev_segment.length <= EPSILON or next_segment.length <= EPSILON:
        return 0.0, "zero length segment", 0.0

    dot_value = max(-1.0, min(1.0, _dot(prev_segment.direction, next_segment.direction)))
    phi = math.acos(dot_value)
    same_threshold = math.radians(machine_profile.controller.same_direction_angle_threshold_deg)
    reverse_threshold = math.radians(machine_profile.controller.reverse_angle_threshold_deg)
    if phi < same_threshold:
        return min(prev_segment.v_cap, next_segment.v_cap), "almost straight", phi
    if abs(math.pi - phi) < reverse_threshold:
        return 0.0, "reverse direction", phi

    a = min(prev_segment.a_cap, next_segment.a_cap)
    j = min(prev_segment.j_cap, next_segment.j_cap)
    epsilon_corner = machine_profile.controller.junction_tolerance_mm
    alpha = math.acos(max(-1.0, min(1.0, -dot_value)))
    sin_half = math.sin(alpha / 2.0)
    if sin_half <= EPSILON or 1.0 - sin_half <= EPSILON:
        return 0.0, "sharp corner", phi

    r_blend = epsilon_corner * sin_half / (1.0 - sin_half)
    v_acc_limit = math.sqrt(max(0.0, a * r_blend))
    v_jerk_limit = (max(0.0, j * r_blend * r_blend)) ** (1.0 / 3.0)
    return min(prev_segment.v_cap, next_segment.v_cap, v_acc_limit, v_jerk_limit), "corner limit", phi


def compute_all_junction_limits(segments: list[MotionSegment], machine_profile: MachineProfile) -> list[Junction]:
    junctions: list[Junction] = []
    for index in range(1, len(segments)):
        prev_segment = segments[index - 1]
        next_segment = segments[index]
        v_limit, reason, angle = compute_junction_velocity(prev_segment, next_segment, machine_profile)
        junctions.append(
            Junction(
                index=index,
                prev_segment_id=prev_segment.segment_id,
                next_segment_id=next_segment.segment_id,
                angle_rad=angle,
                tolerance=machine_profile.controller.junction_tolerance_mm,
                v_junction_limit=v_limit,
                reason=reason,
            )
        )
    return junctions


def initialize_node_velocities(segments: list[MotionSegment], junctions: list[Junction]) -> list[float]:
    node_velocities = [0.0] * (len(segments) + 1)
    for junction in junctions:
        prev_cap = segments[junction.index - 1].v_cap
        next_cap = segments[junction.index].v_cap
        node_velocities[junction.index] = min(junction.v_junction_limit, prev_cap, next_cap)
    return node_velocities


def backward_pass(segments: list[MotionSegment], node_velocities: list[float]) -> list[float]:
    for index in range(len(segments) - 1, -1, -1):
        segment = segments[index]
        v_end = node_velocities[index + 1]
        max_v_start = max_start_velocity_given_end_velocity(
            segment.length,
            v_end,
            segment.v_cap,
            segment.a_cap,
            segment.j_cap,
        )
        node_velocities[index] = min(node_velocities[index], max_v_start, segment.v_cap)
    return node_velocities


def forward_pass(segments: list[MotionSegment], node_velocities: list[float]) -> list[float]:
    for index, segment in enumerate(segments):
        v_start = node_velocities[index]
        max_v_end = max_end_velocity_given_start_velocity(
            segment.length,
            v_start,
            segment.v_cap,
            segment.a_cap,
            segment.j_cap,
        )
        node_velocities[index + 1] = min(node_velocities[index + 1], max_v_end, segment.v_cap)
    return node_velocities


def bidirectional_lookahead(
    segments: list[MotionSegment],
    node_velocities: list[float],
    machine_profile: MachineProfile,
) -> list[float]:
    if machine_profile.controller.lookahead_blocks == 0:
        return node_velocities
    for _ in range(machine_profile.controller.lookahead_max_iterations):
        old = list(node_velocities)
        node_velocities = backward_pass(segments, node_velocities)
        node_velocities = forward_pass(segments, node_velocities)
        if max(abs(left - right) for left, right in zip(old, node_velocities, strict=True)) < (
            machine_profile.controller.velocity_tolerance_mm_s
        ):
            break
    return node_velocities


def max_start_velocity_given_end_velocity(
    distance: float,
    v_end: float,
    v_cap: float,
    a_max: float,
    j_max: float,
) -> float:
    low = min(v_end, v_cap)
    high = v_cap
    for _ in range(50):
        mid = (low + high) / 2.0
        if s_curve_transition(mid, v_end, a_max, j_max).distance <= distance:
            low = mid
        else:
            high = mid
    return low


def max_end_velocity_given_start_velocity(
    distance: float,
    v_start: float,
    v_cap: float,
    a_max: float,
    j_max: float,
) -> float:
    low = min(v_start, v_cap)
    high = v_cap
    for _ in range(50):
        mid = (low + high) / 2.0
        if s_curve_transition(v_start, mid, a_max, j_max).distance <= distance:
            low = mid
        else:
            high = mid
    return low


def assign_entry_exit_velocity(segments: list[MotionSegment], node_velocities: list[float]) -> None:
    for index, segment in enumerate(segments):
        segment.entry_velocity = node_velocities[index]
        segment.exit_velocity = node_velocities[index + 1]


def detect_bottlenecks(segments: list[MotionSegment]) -> list[dict[str, float | int | str]]:
    bottlenecks: list[dict[str, float | int | str]] = []
    for segment in segments:
        ideal_time = segment.length / segment.commanded_feed_mm_s if segment.commanded_feed_mm_s > EPSILON else 0.0
        if ideal_time <= EPSILON:
            continue
        slowdown_ratio = segment.estimated_time / ideal_time if ideal_time > EPSILON else 0.0
        reasons: list[str] = []
        if segment.peak_velocity < 0.8 * segment.commanded_feed_mm_s:
            reasons.append("short segment speed degradation")
        if segment.v_cap < 0.999 * segment.commanded_feed_mm_s:
            reasons.append("axis velocity limit")
        if segment.estimated_time > ideal_time * 1.2:
            reasons.append("acceleration or jerk limited")
        if segment.v_cap > EPSILON and segment.entry_velocity < 0.5 * segment.v_cap:
            reasons.append("low entry velocity due to previous junction")
        if segment.v_cap > EPSILON and segment.exit_velocity < 0.5 * segment.v_cap:
            reasons.append("low exit velocity due to next junction")
        segment.bottleneck_reasons = reasons
        if slowdown_ratio > 1.2:
            bottlenecks.append(
                {
                    "line_no": segment.block.line_no,
                    "segment_id": segment.segment_id,
                    "raw": segment.block.raw,
                    "ideal_time_sec": ideal_time,
                    "actual_time_sec": segment.estimated_time,
                    "slowdown_ratio": slowdown_ratio,
                    "reason": "; ".join(reasons),
                }
            )
    return bottlenecks


def _reset_phase2_fields(program: list[BaseBlock]) -> None:
    for block in program:
        block.estimated_time = 0.0
        block.phase2_entry_velocity_mm_s = None
        block.phase2_exit_velocity_mm_s = None
        block.phase2_peak_velocity_mm_s = None
        block.phase2_v_cap_mm_s = None
        block.phase2_a_cap_mm_s2 = None
        block.phase2_j_cap_mm_s3 = None
        block.phase2_profile_type = None
        block.phase2_slowdown_ratio = None
        block.phase2_bottleneck_reason = None
        block.phase2_segment_count = 0
        block.phase2_dynamic_samples.clear()


def _merge_segment_diagnostics_into_block(segment: MotionSegment) -> None:
    block = segment.block
    if block.phase2_entry_velocity_mm_s is None:
        block.phase2_entry_velocity_mm_s = segment.entry_velocity
    block.phase2_exit_velocity_mm_s = segment.exit_velocity
    block.phase2_peak_velocity_mm_s = max(block.phase2_peak_velocity_mm_s or 0.0, segment.peak_velocity)
    block.phase2_v_cap_mm_s = (
        segment.v_cap if block.phase2_v_cap_mm_s is None else min(block.phase2_v_cap_mm_s, segment.v_cap)
    )
    block.phase2_a_cap_mm_s2 = (
        segment.a_cap if block.phase2_a_cap_mm_s2 is None else min(block.phase2_a_cap_mm_s2, segment.a_cap)
    )
    block.phase2_j_cap_mm_s3 = (
        segment.j_cap if block.phase2_j_cap_mm_s3 is None else min(block.phase2_j_cap_mm_s3, segment.j_cap)
    )
    block.phase2_profile_type = _combine_profile_type(block.phase2_profile_type, segment.profile_type)
    block.phase2_segment_count += 1
    ideal_time = segment.length / segment.commanded_feed_mm_s if segment.commanded_feed_mm_s > EPSILON else None
    if ideal_time and ideal_time > EPSILON:
        ratio = segment.estimated_time / ideal_time
        block.phase2_slowdown_ratio = max(block.phase2_slowdown_ratio or 0.0, ratio)
    for warning in segment.warnings:
        block.warnings.append(warning)


def _merge_bottlenecks_into_blocks(segments: list[MotionSegment]) -> None:
    for segment in segments:
        if not segment.bottleneck_reasons:
            continue
        existing = set((segment.block.phase2_bottleneck_reason or "").split("; "))
        existing.discard("")
        existing.update(segment.bottleneck_reasons)
        segment.block.phase2_bottleneck_reason = "; ".join(sorted(existing))


def _combine_profile_type(left: str | None, right: str) -> str:
    if not left:
        return right
    if left == right:
        return left
    if "degraded" in {left, right} or "degraded" in left or "degraded" in right:
        return "mixed_degraded"
    return "mixed"


def _create_segment(
    segment_id: int,
    block_index: int,
    block: RapidMoveBlock | LinearMoveBlock | ArcMoveBlock,
    motion_type: str,
    start: Position,
    end: Position,
    commanded_feed_mm_s: float,
) -> MotionSegment:
    length = _distance(start, end)
    direction = _direction(start, end, length)
    return MotionSegment(
        segment_id=segment_id,
        block_index=block_index,
        block=block,
        motion_type=motion_type,
        start_pos=start,
        end_pos=end,
        length=length,
        direction=direction,
        commanded_feed_mm_s=max(0.0, commanded_feed_mm_s),
    )


def _transition_phases(
    v_start: float,
    v_end: float,
    transition: TransitionResult,
    j_max: float,
) -> list[tuple[float, float]]:
    if transition.time <= EPSILON:
        return []
    sign = 1.0 if v_end >= v_start else -1.0
    jerk = j_max * sign
    if transition.profile_type == "triangular_s_curve":
        peak_jerk = (abs(v_end - v_start) / (transition.t_j * transition.t_j)) * sign
        return [(transition.t_j, peak_jerk), (transition.t_j, -peak_jerk)]
    return [(transition.t_j, jerk), (transition.t_a, 0.0), (transition.t_j, -jerk)]


def _arc_definition(block: ArcMoveBlock) -> tuple[float, float, float, float, float, float] | None:
    if block.start is None or block.end is None:
        return None
    start_2d, end_2d, out_delta = _project_points(block.start, block.end, block.plane)
    if block.r is not None:
        center = _arc_center_from_r(start_2d, end_2d, block.r, block.direction)
        if center is None:
            return None
    else:
        center = _arc_center_from_ijk(block)
        if center is None:
            return None
    c1, c2 = center
    radius = math.dist(start_2d, center)
    if radius <= EPSILON:
        return None
    start_angle = math.atan2(start_2d[1] - c2, start_2d[0] - c1)
    end_angle = math.atan2(end_2d[1] - c2, end_2d[0] - c1)
    sweep = _arc_sweep(block.direction, start_angle, end_angle)
    return c1, c2, radius, start_angle, sweep, out_delta


def _arc_center_from_ijk(block: ArcMoveBlock) -> tuple[float, float] | None:
    if block.start is None:
        return None
    i, j, k = block.ijk
    if block.plane == "G18":
        if i is None or k is None:
            return None
        return block.start.x + i, block.start.z + k
    if block.plane == "G19":
        if j is None or k is None:
            return None
        return block.start.y + j, block.start.z + k
    if i is None or j is None:
        return None
    return block.start.x + i, block.start.y + j


def _arc_center_from_r(
    start: tuple[float, float],
    end: tuple[float, float],
    radius_word: float,
    direction: str,
) -> tuple[float, float] | None:
    chord = math.dist(start, end)
    radius = abs(radius_word)
    if chord <= EPSILON or radius <= EPSILON or chord > 2.0 * radius:
        return None
    mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    half = chord / 2.0
    height = math.sqrt(max(0.0, radius * radius - half * half))
    ux = (end[0] - start[0]) / chord
    uy = (end[1] - start[1]) / chord
    candidates = [
        (mid[0] - uy * height, mid[1] + ux * height),
        (mid[0] + uy * height, mid[1] - ux * height),
    ]
    want_large = radius_word < 0
    best = candidates[0]
    best_score = float("inf")
    for candidate in candidates:
        start_angle = math.atan2(start[1] - candidate[1], start[0] - candidate[0])
        end_angle = math.atan2(end[1] - candidate[1], end[0] - candidate[0])
        sweep = abs(_arc_sweep(direction, start_angle, end_angle))
        large = sweep > math.pi
        score = 0.0 if large == want_large else 1.0
        if score < best_score:
            best = candidate
            best_score = score
    return best


def _arc_sweep(direction: str, start_angle: float, end_angle: float) -> float:
    if direction == "G03":
        delta = end_angle - start_angle
        if delta <= 0:
            delta += 2.0 * math.pi
        return delta
    delta = end_angle - start_angle
    if delta >= 0:
        delta -= 2.0 * math.pi
    return delta


def _arc_point(
    block: ArcMoveBlock,
    center_1: float,
    center_2: float,
    radius: float,
    theta: float,
    out_delta: float,
) -> Position:
    p1 = center_1 + radius * math.cos(theta)
    p2 = center_2 + radius * math.sin(theta)
    start = block.start or Position()
    if block.plane == "G18":
        return Position(x=p1, y=start.y + out_delta, z=p2)
    if block.plane == "G19":
        return Position(x=start.x + out_delta, y=p1, z=p2)
    return Position(x=p1, y=p2, z=start.z + out_delta)


def _project_points(start: Position, end: Position, plane: str) -> tuple[tuple[float, float], tuple[float, float], float]:
    if plane == "G18":
        return (start.x, start.z), (end.x, end.z), end.y - start.y
    if plane == "G19":
        return (start.y, start.z), (end.y, end.z), end.x - start.x
    return (start.x, start.y), (end.x, end.y), end.z - start.z


def _distance(start: Position, end: Position) -> float:
    return math.sqrt((end.x - start.x) ** 2 + (end.y - start.y) ** 2 + (end.z - start.z) ** 2)


def _direction(start: Position, end: Position, length: float) -> tuple[float, float, float]:
    if length <= EPSILON:
        return (0.0, 0.0, 0.0)
    return ((end.x - start.x) / length, (end.y - start.y) / length, (end.z - start.z) / length)


def _dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]
