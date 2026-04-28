from __future__ import annotations

import csv
import math
from pathlib import Path

import yaml

from nc_time_twin import estimate_nc_time
from nc_time_twin.cli import main
from nc_time_twin.core.ir.blocks import LinearMoveBlock, Position
from nc_time_twin.core.machine.calibration import calibrate_machine_profile_from_csv
from nc_time_twin.core.machine.profile import MachineProfile, load_machine_profile
from nc_time_twin.core.simulation.phase2 import (
    MotionSegment,
    compute_s_curve_segment_profile,
    s_curve_transition,
)


PHASE2_PROFILE = Path(__file__).resolve().parents[1] / "profiles" / "default_phase2_3axis.yaml"


def test_phase2_profile_validates_and_legacy_default_remains_constant(profile_path, write_nc) -> None:
    profile = load_machine_profile(PHASE2_PROFILE)
    assert profile.time_model.mode == "phase2"
    assert profile.kinematic_type == "3_axis"

    nc = write_nc("G21 G90\nG01 X100 F1000")
    default_result = estimate_nc_time(nc, profile_path)
    phase2_result = estimate_nc_time(nc, profile_path, time_model="phase2")

    assert math.isclose(default_result.cutting_time_sec, 6.0, rel_tol=1e-9)
    assert phase2_result.cutting_time_sec > default_result.cutting_time_sec
    assert phase2_result.phase2_summary["phase2_segment_count"] == 1


def test_s_curve_transition_and_short_segment_degradation() -> None:
    transition = s_curve_transition(0.0, 100.0, 1000.0, 10000.0)
    assert transition.time > 0
    assert transition.distance > 0

    profile = load_machine_profile(PHASE2_PROFILE)
    block = LinearMoveBlock(line_no=1, raw="G01 X1 F6000", start=Position(), end=Position(x=1.0))
    segment = MotionSegment(
        segment_id=0,
        block_index=0,
        block=block,
        motion_type="linear",
        start_pos=block.start,
        end_pos=block.end,
        length=1.0,
        direction=(1.0, 0.0, 0.0),
        commanded_feed_mm_s=100.0,
        v_cap=100.0,
        a_cap=800.0,
        j_cap=10000.0,
        entry_velocity=0.0,
        exit_velocity=0.0,
    )
    segment_profile = compute_s_curve_segment_profile(segment, profile)
    assert segment_profile.profile_type == "degraded_s_curve_no_cruise"
    assert segment_profile.peak_velocity < 100.0
    assert segment_profile.total_time > 0
    assert segment_profile.samples


def test_phase2_arc_discretization_and_chart_samples(write_nc) -> None:
    nc = write_nc(
        """
        G21 G90 G17
        G02 X10 Y0 I5 J0 F600
        """
    )
    result = estimate_nc_time(nc, PHASE2_PROFILE)
    arc = next(block for block in result.ir_program if block.display_type == "arc")

    assert arc.phase2_segment_count > 1
    assert result.phase2_summary["phase2_segment_count"] == arc.phase2_segment_count
    assert result.chart_data()["phase2_dynamic_samples"]


def test_phase2_junction_velocity_and_bottleneck(write_nc) -> None:
    nc = write_nc(
        """
        G21 G90 G17
        G01 X50 Y0 F6000
        G01 X50 Y50 F6000
        """
    )
    result = estimate_nc_time(nc, PHASE2_PROFILE)

    assert result.phase2_junctions
    junction = result.phase2_junctions[0]
    assert junction["reason"] == "corner limit"
    assert junction["v_junction_limit_mm_s"] < 100.0
    assert result.phase2_bottlenecks
    first = next(block for block in result.ir_program if block.display_type == "linear")
    assert first.phase2_exit_velocity_mm_s == junction["v_junction_limit_mm_s"]


def test_phase2_event_forces_motion_group_stop(write_nc) -> None:
    nc = write_nc(
        """
        G21 G90
        G01 X50 F3000
        G04 P1000
        G01 X100 F3000
        """
    )
    result = estimate_nc_time(nc, PHASE2_PROFILE)
    moves = [block for block in result.ir_program if block.display_type == "linear"]

    assert moves[0].phase2_exit_velocity_mm_s == 0.0
    assert moves[1].phase2_entry_velocity_mm_s == 0.0
    assert math.isclose(result.dwell_time_sec, 1.0, rel_tol=1e-9)


def test_cli_time_model_phase2_and_benchmark_generation(write_nc, profile_path, artifact_path) -> None:
    nc = write_nc("G21 G90\nG01 X100 F1000")
    out = artifact_path("json")
    exit_code = main(
        [
            "estimate",
            "--nc",
            str(nc),
            "--profile",
            str(profile_path),
            "--time-model",
            "phase2",
            "--out",
            str(out),
        ]
    )
    assert exit_code == 0
    assert "phase2_segment_count" in out.read_text(encoding="utf-8")

    benchmark = artifact_path("nc")
    exit_code = main(["generate-benchmark", "--profile", str(PHASE2_PROFILE), "--out", str(benchmark)])
    assert exit_code == 0
    text = benchmark.read_text(encoding="utf-8")
    assert "G02" in text
    assert "T2 M06" in text


def test_synthetic_calibration_reduces_mape(write_nc, tmp_path) -> None:
    nc = write_nc("G21 G90\nG01 X100 F6000\nG01 X100 Y50 F6000")
    target_profile = _scaled_profile(PHASE2_PROFILE, tmp_path / "target.yaml", acc_scale=0.5)
    actual = estimate_nc_time(nc, target_profile).total_time_sec
    dataset = tmp_path / "dataset.csv"
    with dataset.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["case_id", "nc_file", "actual_total_time_sec"])
        writer.writeheader()
        writer.writerow({"case_id": "case_1", "nc_file": str(nc), "actual_total_time_sec": actual})

    _, summary = calibrate_machine_profile_from_csv(dataset, PHASE2_PROFILE)

    assert summary["case_count"] == 1
    assert summary["after_mape"] < summary["before_mape"]


def _scaled_profile(profile_path: Path, out_path: Path, *, acc_scale: float) -> Path:
    profile = load_machine_profile(profile_path)
    data = profile.model_dump(mode="json")
    for axis in data["axes"].values():
        axis["max_acc_mm_s2"] *= acc_scale
    data["default_cut_acc_mm_s2"] *= acc_scale
    with out_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
    return out_path
