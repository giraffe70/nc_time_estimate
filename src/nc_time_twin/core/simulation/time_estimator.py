from __future__ import annotations

import math

from nc_time_twin.core.ir.blocks import (
    ArcMoveBlock,
    BaseBlock,
    CoolantEventBlock,
    DwellBlock,
    LinearMoveBlock,
    RapidMoveBlock,
    SpindleEventBlock,
    ToolChangeBlock,
)
from nc_time_twin.core.machine.profile import MachineProfile
from nc_time_twin.core.parser.modal_state import unit_factor


def estimate_program_time(program: list[BaseBlock], machine_profile: MachineProfile) -> None:
    for block in program:
        estimate_block_time(block, machine_profile)


def estimate_block_time(block: BaseBlock, machine_profile: MachineProfile) -> None:
    if isinstance(block, RapidMoveBlock):
        block.estimated_time = compute_rapid_time(block, machine_profile)
    elif isinstance(block, (LinearMoveBlock, ArcMoveBlock)):
        feed_mm_min = resolve_feedrate_mm_per_min(block, machine_profile)
        block.estimated_time = compute_feed_move_time_with_model(block.length, feed_mm_min, machine_profile)
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
    else:
        block.estimated_time = 0.0


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


def resolve_feedrate_mm_per_min(
    block: LinearMoveBlock | ArcMoveBlock,
    machine_profile: MachineProfile,
) -> float:
    factor = unit_factor(block.unit)
    if block.feed_mode == "G94":
        if block.feedrate is None:
            block.warnings.append("Missing feedrate F; using default_cut_feed_mm_min")
            return machine_profile.default_cut_feed_mm_min
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
        block.warnings.append("G93 inverse time feed is not fully supported in Phase 1")
        return machine_profile.default_cut_feed_mm_min
    else:
        block.warnings.append(f"Unknown feed mode {block.feed_mode}; using default_cut_feed_mm_min")
        return machine_profile.default_cut_feed_mm_min

    if feed_mm_min <= 0:
        block.warnings.append("Invalid feedrate; using default_cut_feed_mm_min")
        return machine_profile.default_cut_feed_mm_min
    if feed_mm_min > machine_profile.max_cut_feed_mm_min:
        block.warnings.append("Feedrate exceeds max_cut_feed_mm_min; capped")
        return machine_profile.max_cut_feed_mm_min
    return feed_mm_min


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
