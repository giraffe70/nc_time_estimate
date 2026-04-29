from __future__ import annotations

from pathlib import Path

from nc_time_twin.core.feed_sanity import analyze_feed_sanity
from nc_time_twin.core.geometry.processor import compute_program_geometry
from nc_time_twin.core.machine.profile import MachineProfile, load_machine_profile
from nc_time_twin.core.parser.nc_parser import parse_nc_file
from nc_time_twin.core.report.comparison import compare_estimate_results
from nc_time_twin.core.report.result_model import EstimateResult, summarize_result
from nc_time_twin.core.simulation.time_estimator import estimate_program_time


def estimate_nc_time(
    nc_file_path: str | Path,
    machine_profile_path: str | Path,
    *,
    feed_unit: str | None = None,
    time_model: str | None = None,
    strict_feed: bool = False,
) -> EstimateResult:
    machine_profile = load_machine_profile(machine_profile_path)
    if strict_feed and feed_unit is None:
        feed_unit = "mm_per_min"
    if feed_unit is not None or time_model is not None:
        machine_profile = _profile_with_overrides(machine_profile, feed_unit=feed_unit, time_model=time_model)
    ir_program = parse_nc_file(nc_file_path, machine_profile)
    compute_program_geometry(ir_program, machine_profile)
    estimate_program_time(ir_program, machine_profile)
    ir_program.link_neighbors()
    result = summarize_result(ir_program)
    _attach_feed_sanity(result, ir_program, machine_profile, strict_feed=strict_feed)
    return result


def estimate_nc_time_with_comparison(
    nc_file_path: str | Path,
    source_nc_file_path: str | Path,
    machine_profile_path: str | Path,
    *,
    feed_unit: str | None = None,
    time_model: str | None = None,
    strict_feed: bool = False,
    max_regression_ratio: float = 0.0,
) -> EstimateResult:
    source = estimate_nc_time(
        source_nc_file_path,
        machine_profile_path,
        feed_unit=feed_unit,
        time_model=time_model,
        strict_feed=strict_feed,
    )
    candidate = estimate_nc_time(
        nc_file_path,
        machine_profile_path,
        feed_unit=feed_unit,
        time_model=time_model,
        strict_feed=strict_feed,
    )
    candidate.comparison = compare_estimate_results(
        source,
        candidate,
        source_label=str(Path(source_nc_file_path)),
        candidate_label=str(Path(nc_file_path)),
        max_regression_ratio=max_regression_ratio,
    )
    return candidate


def _profile_with_overrides(
    machine_profile: MachineProfile,
    *,
    feed_unit: str | None = None,
    time_model: str | None = None,
) -> MachineProfile:
    data = machine_profile.model_dump()
    if feed_unit is not None:
        data["feed_unit"] = feed_unit
    if time_model is not None:
        data.setdefault("time_model", {})["mode"] = time_model
    return MachineProfile.model_validate(data)


def _attach_feed_sanity(
    result: EstimateResult,
    ir_program,
    machine_profile: MachineProfile,
    *,
    strict_feed: bool,
) -> None:
    diagnostics = analyze_feed_sanity(ir_program, machine_profile, strict_feed=strict_feed)
    result.feed_sanity_summary = diagnostics.summary
    result.feed_sanity_issues = diagnostics.issues
    result.normalized_feed_recommendation = diagnostics.recommendation
    critical_count = diagnostics.summary.get("feed_sanity_critical_count", 0)
    if critical_count:
        result.warning_list.append(f"Feed sanity check found {critical_count} critical issue(s)")
