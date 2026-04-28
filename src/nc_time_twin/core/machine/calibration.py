from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nc_time_twin.core.machine.profile import MachineProfile, load_machine_profile


@dataclass(frozen=True)
class CalibrationCase:
    case_id: str
    nc_file: Path
    actual_total_time_sec: float


def calibrate_machine_profile_from_csv(
    dataset_path: str | Path,
    base_profile_path: str | Path,
    *,
    nc_base_dir: str | Path | None = None,
) -> tuple[MachineProfile, dict[str, Any]]:
    dataset = load_calibration_dataset(dataset_path, nc_base_dir=nc_base_dir)
    base_profile = load_machine_profile(base_profile_path)
    base_profile = _profile_with_time_model(base_profile, "phase2")
    before = _evaluate_profile(base_profile, dataset)
    current_profile = base_profile
    best_error = before["mape"]
    best_params = {
        "acc_scale": 1.0,
        "jerk_scale": 1.0,
        "junction_tolerance_scale": 1.0,
        "rapid_scale": 1.0,
        "event_scale": 1.0,
    }

    candidates = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
    for _ in range(2):
        improved = False
        for param_name in list(best_params):
            local_best_profile = current_profile
            local_best_error = best_error
            local_best_value = best_params[param_name]
            for scale in candidates:
                params = dict(best_params)
                params[param_name] = scale
                candidate_profile = update_profile_with_params(base_profile, params)
                score = _evaluate_profile(candidate_profile, dataset)["mape"]
                if score < local_best_error:
                    local_best_error = score
                    local_best_profile = candidate_profile
                    local_best_value = scale
            if local_best_error < best_error:
                current_profile = local_best_profile
                best_error = local_best_error
                best_params[param_name] = local_best_value
                improved = True
        if not improved:
            break

    after = _evaluate_profile(current_profile, dataset)
    return current_profile, {
        "case_count": len(dataset),
        "before_mape": before["mape"],
        "after_mape": after["mape"],
        "before_details": before["details"],
        "after_details": after["details"],
        "best_params": best_params,
    }


def load_calibration_dataset(
    dataset_path: str | Path,
    *,
    nc_base_dir: str | Path | None = None,
) -> list[CalibrationCase]:
    path = Path(dataset_path)
    base_dir = Path(nc_base_dir) if nc_base_dir is not None else path.parent
    cases: list[CalibrationCase] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            actual = row.get("actual_total_time_sec") or row.get("actual_total_time") or row.get("actual_time_sec")
            nc_file = row.get("nc_file")
            if not actual or not nc_file:
                raise ValueError("calibration CSV requires nc_file and actual_total_time_sec columns")
            nc_path = Path(nc_file)
            if not nc_path.is_absolute():
                nc_path = base_dir / nc_path
            cases.append(
                CalibrationCase(
                    case_id=row.get("case_id") or nc_path.stem,
                    nc_file=nc_path,
                    actual_total_time_sec=float(actual),
                )
            )
    if not cases:
        raise ValueError("calibration CSV contains no cases")
    return cases


def update_profile_with_params(base_profile: MachineProfile, params: dict[str, float]) -> MachineProfile:
    data = base_profile.model_dump()
    data.setdefault("time_model", {})["mode"] = "phase2"
    acc_scale = params.get("acc_scale", 1.0)
    jerk_scale = params.get("jerk_scale", 1.0)
    rapid_scale = params.get("rapid_scale", 1.0)
    event_scale = params.get("event_scale", 1.0)
    for axis in data["axes"].values():
        axis["max_acc_mm_s2"] *= acc_scale
        axis["max_jerk_mm_s3"] *= jerk_scale
        axis["rapid_velocity_mm_min"] *= rapid_scale
    data["rapid_feed_mm_min"] *= rapid_scale
    data["default_cut_acc_mm_s2"] *= acc_scale
    data["default_cut_jerk_mm_s3"] *= jerk_scale
    data["controller"]["junction_tolerance_mm"] *= params.get("junction_tolerance_scale", 1.0)
    for key in ("tool_change_sec", "spindle_start_sec", "spindle_stop_sec", "coolant_on_sec", "coolant_off_sec"):
        data["event_time"][key] *= event_scale
    return MachineProfile.model_validate(data)


def _profile_with_time_model(profile: MachineProfile, mode: str) -> MachineProfile:
    data = profile.model_dump()
    data.setdefault("time_model", {})["mode"] = mode
    return MachineProfile.model_validate(data)


def _evaluate_profile(profile: MachineProfile, dataset: list[CalibrationCase]) -> dict[str, Any]:
    from nc_time_twin.api import estimate_nc_time

    errors: list[float] = []
    details: list[dict[str, Any]] = []
    profile_path = _profile_temp_path(profile)
    try:
        for case in dataset:
            result = estimate_nc_time(case.nc_file, profile_path, time_model="phase2")
            predicted = result.total_time_sec
            actual = case.actual_total_time_sec
            abs_error = abs(predicted - actual)
            percentage_error = (abs_error / actual * 100.0) if actual > 0 else 0.0
            errors.append(percentage_error)
            details.append(
                {
                    "case_id": case.case_id,
                    "predicted_time_sec": predicted,
                    "actual_time_sec": actual,
                    "abs_error_sec": abs_error,
                    "percentage_error": percentage_error,
                }
            )
    finally:
        try:
            profile_path.unlink()
        except FileNotFoundError:
            pass
    mape = sum(errors) / len(errors) if errors else 0.0
    return {"mape": mape, "details": details}


def _profile_temp_path(profile: MachineProfile) -> Path:
    import tempfile
    import yaml

    handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", encoding="utf-8", delete=False)
    with handle:
        yaml.safe_dump(profile.model_dump(mode="json"), handle, allow_unicode=True, sort_keys=False)
    return Path(handle.name)
