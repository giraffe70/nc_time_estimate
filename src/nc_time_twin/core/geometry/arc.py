from __future__ import annotations

import math

from nc_time_twin.core.geometry.line import compute_line_length
from nc_time_twin.core.ir.blocks import ArcMoveBlock, Position
from nc_time_twin.core.machine.profile import MachineProfile


def compute_arc_length(block: ArcMoveBlock, machine_profile: MachineProfile) -> float:
    if block.r is not None:
        block.warnings.append("R arc length is approximate in Phase 1")
        return compute_arc_length_r(block)
    return compute_arc_length_ijk(block, machine_profile.arc_tolerance_mm)


def compute_arc_length_ijk(block: ArcMoveBlock, tolerance: float) -> float:
    if block.start is None or block.end is None:
        return 0.0
    projected = _project_arc(block)
    if projected is None:
        block.warnings.append("Missing IJK values for active arc plane")
        return compute_line_length(block.start, block.end)

    s1, s2, e1, e2, c1, c2, out_delta = projected
    r_start = math.hypot(s1 - c1, s2 - c2)
    r_end = math.hypot(e1 - c1, e2 - c2)
    if r_start <= 0 or r_end <= 0:
        block.warnings.append("Invalid arc radius")
        return compute_line_length(block.start, block.end)
    if abs(r_start - r_end) > tolerance:
        block.warnings.append("Arc radius mismatch")

    radius = (r_start + r_end) / 2.0
    theta_start = math.atan2(s2 - c2, s1 - c1)
    theta_end = math.atan2(e2 - c2, e1 - c1)

    if block.direction == "G03":
        delta_theta = theta_end - theta_start
        if delta_theta <= 0:
            delta_theta += 2 * math.pi
    else:
        delta_theta = theta_start - theta_end
        if delta_theta <= 0:
            delta_theta += 2 * math.pi

    arc_length = radius * delta_theta
    if abs(out_delta) > 0:
        arc_length = math.sqrt(arc_length * arc_length + out_delta * out_delta)
    return arc_length


def compute_arc_length_r(block: ArcMoveBlock) -> float:
    if block.start is None or block.end is None or block.r is None:
        return 0.0
    start_2d, end_2d, out_delta = _project_points(block.start, block.end, block.plane)
    chord = math.dist(start_2d, end_2d)
    radius = abs(block.r)
    if radius <= 0:
        block.warnings.append("Invalid arc R radius")
        return compute_line_length(block.start, block.end)
    if chord > 2 * radius:
        block.warnings.append("Invalid arc R: chord larger than diameter")
        return compute_line_length(block.start, block.end)
    if chord == 0:
        block.warnings.append("Full circle R arc is ambiguous")
        return compute_line_length(block.start, block.end)
    ratio = min(1.0, max(-1.0, chord / (2 * radius)))
    angle = 2 * math.asin(ratio)
    if block.r < 0:
        angle = 2 * math.pi - angle
    arc_length = radius * angle
    if abs(out_delta) > 0:
        arc_length = math.sqrt(arc_length * arc_length + out_delta * out_delta)
    return arc_length


def _project_arc(block: ArcMoveBlock) -> tuple[float, float, float, float, float, float, float] | None:
    start = block.start
    end = block.end
    if start is None or end is None:
        return None
    i, j, k = block.ijk
    if block.plane == "G17":
        if i is None or j is None:
            return None
        return start.x, start.y, end.x, end.y, start.x + i, start.y + j, end.z - start.z
    if block.plane == "G18":
        if i is None or k is None:
            return None
        return start.x, start.z, end.x, end.z, start.x + i, start.z + k, end.y - start.y
    if block.plane == "G19":
        if j is None or k is None:
            return None
        return start.y, start.z, end.y, end.z, start.y + j, start.z + k, end.x - start.x
    block.warnings.append("Unknown arc plane")
    return None


def _project_points(
    start: Position,
    end: Position,
    plane: str,
) -> tuple[tuple[float, float], tuple[float, float], float]:
    if plane == "G18":
        return (start.x, start.z), (end.x, end.z), end.y - start.y
    if plane == "G19":
        return (start.y, start.z), (end.y, end.z), end.x - start.x
    return (start.x, start.y), (end.x, end.y), end.z - start.z
