from __future__ import annotations

from dataclasses import dataclass
import math

from nc_time_twin.core.ir.blocks import (
    ArcMoveBlock,
    BaseBlock,
    CoolantEventBlock,
    DwellBlock,
    LinearMoveBlock,
    OptionalStopBlock,
    Position,
    RapidMoveBlock,
    ReferenceReturnBlock,
    SmoothingEventBlock,
    SpindleEventBlock,
    ToolChangeBlock,
)
from nc_time_twin.core.machine.profile import MachineProfile
from nc_time_twin.core.parser.modal_state import unit_factor

LOW_G94_FEED_THRESHOLD = 100.0
AUTO_M_PER_MIN_MIN_COUNT = 20
AUTO_M_PER_MIN_MIN_RATIO = 0.05


@dataclass
class FeedEstimationStats:
    configured_feed_unit: str
    effective_feed_unit: str
    feed_move_count: int = 0
    raw_feed_count: int = 0
    low_g94_feed_count: int = 0
    capped_count: int = 0
    min_raw_feed: float | None = None
    max_raw_feed: float | None = None
    min_effective_feed_mm_min: float | None = None
    max_effective_feed_mm_min: float | None = None

    def record_raw_feed(self, feedrate: float | None, block: LinearMoveBlock | ArcMoveBlock) -> None:
        if feedrate is None:
            return
        self.raw_feed_count += 1
        self.min_raw_feed = feedrate if self.min_raw_feed is None else min(self.min_raw_feed, feedrate)
        self.max_raw_feed = feedrate if self.max_raw_feed is None else max(self.max_raw_feed, feedrate)
        if block.feed_mode == "G94" and block.unit == "mm" and 0 < feedrate < LOW_G94_FEED_THRESHOLD:
            self.low_g94_feed_count += 1

    def record_effective_feed(self, feed_mm_min: float | None, capped: bool) -> None:
        self.feed_move_count += 1
        if feed_mm_min is not None:
            self.min_effective_feed_mm_min = (
                feed_mm_min
                if self.min_effective_feed_mm_min is None
                else min(self.min_effective_feed_mm_min, feed_mm_min)
            )
            self.max_effective_feed_mm_min = (
                feed_mm_min
                if self.max_effective_feed_mm_min is None
                else max(self.max_effective_feed_mm_min, feed_mm_min)
            )
        if capped:
            self.capped_count += 1

    def to_dict(self) -> dict[str, float | int | str | None]:
        return {
            "feed_unit_configured": self.configured_feed_unit,
            "feed_unit_effective": self.effective_feed_unit,
            "feed_move_count": self.feed_move_count,
            "feed_raw_count": self.raw_feed_count,
            "feed_min_raw": self.min_raw_feed,
            "feed_max_raw": self.max_raw_feed,
            "feed_low_g94_count": self.low_g94_feed_count,
            "feed_capped_count": self.capped_count,
            "feed_min_effective_mm_min": self.min_effective_feed_mm_min,
            "feed_max_effective_mm_min": self.max_effective_feed_mm_min,
        }


def estimate_program_time(program: list[BaseBlock], machine_profile: MachineProfile) -> None:
    effective_feed_unit = resolve_program_feed_unit(program, machine_profile)
    stats = FeedEstimationStats(
        configured_feed_unit=machine_profile.feed_unit,
        effective_feed_unit=effective_feed_unit,
    )
    for block in program:
        estimate_block_time(block, machine_profile, effective_feed_unit=effective_feed_unit, stats=stats)
    _attach_feed_diagnostics(program, machine_profile, stats)


def estimate_block_time(
    block: BaseBlock,
    machine_profile: MachineProfile,
    *,
    effective_feed_unit: str | None = None,
    stats: FeedEstimationStats | None = None,
) -> None:
    if isinstance(block, RapidMoveBlock):
        block.estimated_time = compute_rapid_time(block, machine_profile)
    elif isinstance(block, (LinearMoveBlock, ArcMoveBlock)):
        block.estimated_time = compute_feed_move_time(block, machine_profile, effective_feed_unit, stats)
    elif isinstance(block, DwellBlock):
        block.estimated_time = block.dwell_time_sec
    elif isinstance(block, ToolChangeBlock):
        block.estimated_time = machine_profile.event_time.tool_change_sec
    elif isinstance(block, SpindleEventBlock):
        if block.event == "spindle_stop":
            block.estimated_time = machine_profile.event_time.spindle_stop_sec
        else:
            block.estimated_time = machine_profile.event_time.spindle_start_sec
    elif isinstance(block, CoolantEventBlock):
        if block.event == "coolant_off":
            block.estimated_time = machine_profile.event_time.coolant_off_sec
        else:
            block.estimated_time = machine_profile.event_time.coolant_on_sec
    elif isinstance(block, OptionalStopBlock):
        block.estimated_time = machine_profile.event_time.optional_stop_sec
    elif isinstance(block, ReferenceReturnBlock):
        block.estimated_time = compute_reference_return_time(block, machine_profile)
    elif isinstance(block, SmoothingEventBlock):
        block.estimated_time = 0.0
    else:
        block.estimated_time = 0.0


def resolve_program_feed_unit(program: list[BaseBlock], machine_profile: MachineProfile) -> str:
    if machine_profile.feed_unit != "auto":
        return machine_profile.feed_unit

    feed_blocks = [
        block
        for block in program
        if isinstance(block, (LinearMoveBlock, ArcMoveBlock)) and block.feedrate is not None
    ]
    if not feed_blocks:
        return "mm_per_min"

    low_g94_blocks = [
        block
        for block in feed_blocks
        if block.feed_mode == "G94"
        and block.unit == "mm"
        and block.feedrate is not None
        and 0 < block.feedrate < LOW_G94_FEED_THRESHOLD
    ]
    low_ratio = len(low_g94_blocks) / len(feed_blocks)
    if len(low_g94_blocks) >= AUTO_M_PER_MIN_MIN_COUNT and low_ratio >= AUTO_M_PER_MIN_MIN_RATIO:
        return "auto_m_per_min"
    return "mm_per_min"


def compute_rapid_time(block: RapidMoveBlock, machine_profile: MachineProfile) -> float:
    if block.start is None or block.end is None:
        return 0.0
    dx = abs(block.end.x - block.start.x)
    dy = abs(block.end.y - block.start.y)
    dz = abs(block.end.z - block.start.z)
    vx = machine_profile.axis("X").rapid_velocity_mm_min / 60.0
    vy = machine_profile.axis("Y").rapid_velocity_mm_min / 60.0
    vz = machine_profile.axis("Z").rapid_velocity_mm_min / 60.0
    tx = dx / vx if vx > 0 else 0.0
    ty = dy / vy if vy > 0 else 0.0
    tz = dz / vz if vz > 0 else 0.0
    return max(tx, ty, tz)


def compute_reference_return_time(block: ReferenceReturnBlock, machine_profile: MachineProfile) -> float:
    reference = machine_profile.reference_return
    if reference.mode == "fixed":
        block.end = _reference_end_position(block, machine_profile)
        return reference.fixed_time_sec
    if reference.mode == "rapid":
        return _compute_reference_return_rapid_time(block, machine_profile)

    block.warnings.append(f"{block.code} reference return time is not estimated")
    return 0.0


def _compute_reference_return_rapid_time(block: ReferenceReturnBlock, machine_profile: MachineProfile) -> float:
    if block.start is None:
        return 0.0
    block.end = _reference_end_position(block, machine_profile)
    dx = abs((block.end.x if "X" in block.axes else block.start.x) - block.start.x)
    dy = abs((block.end.y if "Y" in block.axes else block.start.y) - block.start.y)
    dz = abs((block.end.z if "Z" in block.axes else block.start.z) - block.start.z)
    vx = machine_profile.axis("X").rapid_velocity_mm_min / 60.0
    vy = machine_profile.axis("Y").rapid_velocity_mm_min / 60.0
    vz = machine_profile.axis("Z").rapid_velocity_mm_min / 60.0
    tx = dx / vx if vx > 0 else 0.0
    ty = dy / vy if vy > 0 else 0.0
    tz = dz / vz if vz > 0 else 0.0
    return max(tx, ty, tz)


def _reference_end_position(block: ReferenceReturnBlock, machine_profile: MachineProfile) -> Position | None:
    if block.start is None:
        return None
    reference = machine_profile.reference_return
    return Position(
        x=reference.axis_position("X") if "X" in block.axes else block.start.x,
        y=reference.axis_position("Y") if "Y" in block.axes else block.start.y,
        z=reference.axis_position("Z") if "Z" in block.axes else block.start.z,
    )


def resolve_feedrate_mm_per_min(
    block: LinearMoveBlock | ArcMoveBlock,
    machine_profile: MachineProfile,
    effective_feed_unit: str | None = None,
) -> float:
    feed_unit = effective_feed_unit or machine_profile.feed_unit
    factor = unit_factor(block.unit)
    if block.feed_mode == "G94":
        if block.feedrate is None:
            block.warnings.append("Missing feedrate F; using default_cut_feed_mm_min")
            return machine_profile.default_cut_feed_mm_min
        if _should_treat_g94_as_m_per_min(block, feed_unit):
            feed_mm_min = block.feedrate * 1000.0
        else:
            feed_mm_min = block.feedrate * factor
    elif block.feed_mode == "G95":
        if block.feedrate is None:
            block.warnings.append("Missing feedrate F in G95; using default_cut_feed_mm_min")
            return machine_profile.default_cut_feed_mm_min
        if block.spindle_speed is None:
            block.warnings.append("G95 requires spindle speed S; using default_cut_feed_mm_min")
            return machine_profile.default_cut_feed_mm_min
        feed_mm_min = block.feedrate * factor * block.spindle_speed
    elif block.feed_mode == "G93":
        if block.feedrate is None or block.feedrate <= 0:
            block.warnings.append("Invalid G93 inverse time feed; using default_cut_feed_mm_min")
            return machine_profile.default_cut_feed_mm_min
        time_sec = 60.0 / block.feedrate
        return (block.length / time_sec) * 60.0 if time_sec > 0 and block.length > 0 else 0.0
    else:
        block.warnings.append(f"Unknown feed mode {block.feed_mode}; using default_cut_feed_mm_min")
        return machine_profile.default_cut_feed_mm_min

    if feed_mm_min <= 0:
        block.warnings.append("Invalid feedrate; using default_cut_feed_mm_min")
        return machine_profile.default_cut_feed_mm_min
    if feed_mm_min > machine_profile.max_cut_feed_mm_min:
        return machine_profile.max_cut_feed_mm_min
    return feed_mm_min


def compute_feed_move_time(
    block: LinearMoveBlock | ArcMoveBlock,
    machine_profile: MachineProfile,
    effective_feed_unit: str | None = None,
    stats: FeedEstimationStats | None = None,
) -> float:
    feed_unit = effective_feed_unit or machine_profile.feed_unit
    block.feed_unit = _block_feed_unit(block, feed_unit)
    if stats is not None:
        stats.record_raw_feed(block.feedrate, block)

    if feed_unit == "inverse_time" or block.feed_mode == "G93":
        if block.feedrate is None or block.feedrate <= 0:
            block.warnings.append("Invalid inverse time feed; using default_cut_feed_mm_min")
            feed_mm_min = machine_profile.default_cut_feed_mm_min
            capped = False
            block.effective_feed_mm_min = feed_mm_min
            block.feed_capped = capped
            if stats is not None:
                stats.record_effective_feed(feed_mm_min, capped)
            return compute_feed_move_time_with_model(block.length, feed_mm_min, machine_profile)
        time_sec = 60.0 / block.feedrate
        feed_mm_min = (block.length / time_sec) * 60.0 if time_sec > 0 and block.length > 0 else 0.0
        block.effective_feed_mm_min = feed_mm_min
        block.feed_capped = False
        if stats is not None:
            stats.record_effective_feed(feed_mm_min, False)
        return time_sec

    uncapped_feed_mm_min = _resolve_uncapped_feedrate_mm_per_min(block, machine_profile, feed_unit)
    capped = uncapped_feed_mm_min > machine_profile.max_cut_feed_mm_min
    feed_mm_min = min(uncapped_feed_mm_min, machine_profile.max_cut_feed_mm_min)
    block.effective_feed_mm_min = feed_mm_min
    block.feed_capped = capped
    if stats is not None:
        stats.record_effective_feed(feed_mm_min, capped)
    return compute_feed_move_time_with_model(block.length, feed_mm_min, machine_profile)


def _resolve_uncapped_feedrate_mm_per_min(
    block: LinearMoveBlock | ArcMoveBlock,
    machine_profile: MachineProfile,
    feed_unit: str,
) -> float:
    factor = unit_factor(block.unit)
    if block.feed_mode == "G94":
        if block.feedrate is None:
            block.warnings.append("Missing feedrate F; using default_cut_feed_mm_min")
            return machine_profile.default_cut_feed_mm_min
        if _should_treat_g94_as_m_per_min(block, feed_unit):
            return block.feedrate * 1000.0
        return block.feedrate * factor
    if block.feed_mode == "G95":
        if block.feedrate is None:
            block.warnings.append("Missing feedrate F in G95; using default_cut_feed_mm_min")
            return machine_profile.default_cut_feed_mm_min
        if block.spindle_speed is None:
            block.warnings.append("G95 requires spindle speed S; using default_cut_feed_mm_min")
            return machine_profile.default_cut_feed_mm_min
        return block.feedrate * factor * block.spindle_speed

    block.warnings.append(f"Unknown feed mode {block.feed_mode}; using default_cut_feed_mm_min")
    return machine_profile.default_cut_feed_mm_min


def _block_feed_unit(block: LinearMoveBlock | ArcMoveBlock, effective_feed_unit: str) -> str:
    if effective_feed_unit == "inverse_time" or block.feed_mode == "G93":
        return "inverse_time"
    if block.feed_mode == "G95":
        return "mm_per_rev" if block.unit == "mm" else "inch_per_rev"
    if _should_treat_g94_as_m_per_min(block, effective_feed_unit):
        return "m_per_min"
    return "mm_per_min" if block.unit == "mm" else "inch_per_min"


def _attach_feed_diagnostics(
    program: list[BaseBlock],
    machine_profile: MachineProfile,
    stats: FeedEstimationStats,
) -> None:
    if hasattr(program, "metadata"):
        program.metadata["feed"] = stats.to_dict()

    if stats.configured_feed_unit == "auto" and stats.effective_feed_unit == "auto_m_per_min":
        _append_program_warning(
            program,
            (
                f"Auto feed unit selected mixed mm/min plus m/min: {stats.low_g94_feed_count} G94 metric "
                f"move blocks had F below {LOW_G94_FEED_THRESHOLD:g}; small F values were converted "
                "from m/min to mm/min"
            ),
        )
    elif stats.configured_feed_unit == "mm_per_min" and stats.low_g94_feed_count:
        _append_program_warning(
            program,
            (
                f"Suspicious low G94 metric feedrates: {stats.low_g94_feed_count} move blocks had F below "
                f"{LOW_G94_FEED_THRESHOLD:g}; verify whether the NC-Code uses m/min instead of mm/min"
            ),
        )

    if stats.capped_count:
        _append_program_warning(
            program,
            (
                f"Feedrate capped by max_cut_feed_mm_min on {stats.capped_count} move blocks "
                f"(limit {machine_profile.max_cut_feed_mm_min:g} mm/min)"
            ),
        )


def _append_program_warning(program: list[BaseBlock], warning: str) -> None:
    if program:
        program[0].warnings.append(warning)


def _should_treat_g94_as_m_per_min(block: LinearMoveBlock | ArcMoveBlock, feed_unit: str) -> bool:
    if block.feed_mode != "G94" or block.unit != "mm" or block.feedrate is None:
        return False
    if feed_unit == "m_per_min":
        return True
    return feed_unit == "auto_m_per_min" and 0 < block.feedrate < LOW_G94_FEED_THRESHOLD


def compute_feed_move_time_with_model(
    length_mm: float,
    feed_mm_min: float,
    machine_profile: MachineProfile,
) -> float:
    if feed_mm_min <= 0 or length_mm <= 0:
        return 0.0
    target_velocity = feed_mm_min / 60.0
    if machine_profile.time_model.mode == "trapezoid":
        return compute_trapezoid_time(length_mm, target_velocity, machine_profile.default_cut_acc_mm_s2)
    return length_mm / target_velocity


def compute_trapezoid_time(distance: float, target_velocity: float, max_acc: float) -> float:
    if distance <= 0 or target_velocity <= 0 or max_acc <= 0:
        return 0.0
    t_acc = target_velocity / max_acc
    d_acc = 0.5 * max_acc * t_acc * t_acc
    d_acc_dec = 2 * d_acc
    if distance >= d_acc_dec:
        d_const = distance - d_acc_dec
        return t_acc + (d_const / target_velocity) + t_acc
    t_peak = math.sqrt(distance / max_acc)
    return 2 * t_peak
