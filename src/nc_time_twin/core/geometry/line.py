from __future__ import annotations

import math

from nc_time_twin.core.ir.blocks import Position


def compute_line_length(start: Position, end: Position) -> float:
    dx = end.x - start.x
    dy = end.y - start.y
    dz = end.z - start.z
    return math.sqrt(dx * dx + dy * dy + dz * dz)
