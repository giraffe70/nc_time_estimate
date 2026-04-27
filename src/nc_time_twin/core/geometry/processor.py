from __future__ import annotations

from nc_time_twin.core.geometry.arc import compute_arc_length
from nc_time_twin.core.geometry.line import compute_line_length
from nc_time_twin.core.ir.blocks import ArcMoveBlock, BaseBlock
from nc_time_twin.core.machine.profile import MachineProfile


def compute_geometry(block: BaseBlock, machine_profile: MachineProfile) -> None:
    if block.start is None or block.end is None:
        block.length = 0.0
        return
    if isinstance(block, ArcMoveBlock):
        block.length = compute_arc_length(block, machine_profile)
    else:
        block.length = compute_line_length(block.start, block.end)


def compute_program_geometry(program: list[BaseBlock], machine_profile: MachineProfile) -> None:
    for block in program:
        compute_geometry(block, machine_profile)
