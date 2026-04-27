from __future__ import annotations

from pathlib import Path

from nc_time_twin.core.geometry.processor import compute_program_geometry
from nc_time_twin.core.machine.profile import load_machine_profile
from nc_time_twin.core.parser.nc_parser import parse_nc_file
from nc_time_twin.core.report.result_model import EstimateResult, summarize_result
from nc_time_twin.core.simulation.time_estimator import estimate_program_time


def estimate_nc_time(nc_file_path: str | Path, machine_profile_path: str | Path) -> EstimateResult:
    machine_profile = load_machine_profile(machine_profile_path)
    ir_program = parse_nc_file(nc_file_path, machine_profile)
    compute_program_geometry(ir_program, machine_profile)
    estimate_program_time(ir_program, machine_profile)
    ir_program.link_neighbors()
    return summarize_result(ir_program)
