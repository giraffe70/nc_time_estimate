from __future__ import annotations

import math
from pathlib import Path

from nc_time_twin import estimate_nc_time, estimate_nc_time_with_comparison


def test_basic_linear_time_case(write_nc, profile_path) -> None:
    nc = write_nc(
        """
        G21 G90 G17
        G01 X100 Y0 F1000
        """
    )
    result = estimate_nc_time(nc, profile_path)
    assert math.isclose(result.total_length_mm, 100.0, rel_tol=1e-9)
    assert math.isclose(result.cutting_time_sec, 6.0, rel_tol=1e-9)


def test_g95_feedrate_uses_spindle_speed(write_nc, profile_path) -> None:
    nc = write_nc(
        """
        G21 G90
        S1000 M03
        G95
        G01 X100 F0.2
        """
    )
    result = estimate_nc_time(nc, profile_path)
    assert math.isclose(result.cutting_time_sec, 30.0, rel_tol=1e-9)


def test_g93_inverse_time_feed(write_nc, profile_path) -> None:
    nc = write_nc(
        """
        G21 G90
        G93
        G01 X100 F2
        """
    )
    result = estimate_nc_time(nc, profile_path)
    block = next(block for block in result.ir_program if block.display_type == "linear")
    assert math.isclose(result.cutting_time_sec, 30.0, rel_tol=1e-9)
    assert block.feed_unit == "inverse_time"


def test_g00_axis_synchronous_time(write_nc, profile_path) -> None:
    nc = write_nc("G21 G90\nG00 X100 Y50 Z10")
    result = estimate_nc_time(nc, profile_path)
    assert math.isclose(result.rapid_time_sec, 0.6, rel_tol=1e-9)


def test_ijk_arc_length(write_nc, profile_path) -> None:
    nc = write_nc(
        """
        G21 G90 G17
        G02 X10 Y0 I5 J0 F600
        """
    )
    result = estimate_nc_time(nc, profile_path)
    arc = next(block for block in result.ir_program if block.display_type == "arc")
    assert math.isclose(arc.length, math.pi * 5, rel_tol=1e-9)
    assert math.isclose(result.arc_time_sec, math.pi * 5 / 10.0, rel_tol=1e-9)


def test_r_arc_is_supported_with_warning(write_nc, profile_path) -> None:
    nc = write_nc(
        """
        G21 G90 G17
        G03 X10 Y0 R5 F600
        """
    )
    result = estimate_nc_time(nc, profile_path)
    arc = next(block for block in result.ir_program if block.display_type == "arc")
    assert math.isclose(arc.length, math.pi * 5, rel_tol=1e-9)
    assert any("R arc length is approximate" in warning for warning in result.warning_list)


def test_g18_arc_plane(write_nc, profile_path) -> None:
    nc = write_nc(
        """
        G21 G90 G18
        G02 X10 Z0 I5 K0 F600
        """
    )
    result = estimate_nc_time(nc, profile_path)
    arc = next(block for block in result.ir_program if block.display_type == "arc")
    assert math.isclose(arc.length, math.pi * 5, rel_tol=1e-9)


def test_m_per_min_feed_unit_converts_metric_g94_feed(write_nc, profile_path, tmp_path) -> None:
    profile = _profile_with_feed_unit(profile_path, tmp_path, "m_per_min")
    nc = write_nc(
        """
        G21 G90
        G01 X100 F6
        """
    )
    result = estimate_nc_time(nc, profile)
    block = next(block for block in result.ir_program if block.display_type == "linear")
    assert math.isclose(result.cutting_time_sec, 1.0, rel_tol=1e-9)
    assert block.feed_unit == "m_per_min"
    assert math.isclose(block.effective_feed_mm_min or 0.0, 6000.0, rel_tol=1e-9)


def test_low_g94_feed_warns_when_profile_does_not_enable_auto(write_nc, profile_path, tmp_path) -> None:
    profile = _profile_without_feed_unit(profile_path, tmp_path)
    nc = write_nc(
        """
        G21 G90
        G01 X100 F6
        """
    )
    result = estimate_nc_time(nc, profile)
    assert math.isclose(result.cutting_time_sec, 1000.0, rel_tol=1e-9)
    assert any("Suspicious low G94 metric feedrates" in warning for warning in result.warning_list)


def test_feed_cap_is_reported_once_in_summary_warning(write_nc, profile_path) -> None:
    nc = write_nc(
        """
        G21 G90
        G01 X100 F12000
        X200
        """
    )
    result = estimate_nc_time(nc, profile_path)
    cap_warnings = [warning for warning in result.warning_list if "Feedrate capped by max_cut_feed" in warning]
    repeated_block_warnings = [
        warning for warning in result.warning_list if warning.endswith("Feedrate exceeds max_cut_feed_mm_min; capped")
    ]
    assert len(cap_warnings) == 1
    assert not repeated_block_warnings
    assert result.summary_dict()["feed_capped_count"] == 2
    assert all(row["effective_feed_mm_min"] == 10000.0 for row in result.block_table if row["type"] == "linear")


def test_toolpathsource_opti_auto_feed_unit_regression(profile_path) -> None:
    root = Path(__file__).resolve().parents[1]
    original = estimate_nc_time(root / "examples" / "ToolPathSource.nc", profile_path)
    optimized = estimate_nc_time(root / "examples" / "ToolPathSource.opti.nc", profile_path)
    compared = estimate_nc_time_with_comparison(
        root / "examples" / "ToolPathSource.opti.nc",
        root / "examples" / "ToolPathSource.nc",
        profile_path,
    )

    assert math.isclose(original.total_length_mm, optimized.total_length_mm, rel_tol=1e-9)
    assert optimized.total_time_sec < original.total_time_sec * 10
    assert optimized.total_time_sec < 600.0
    assert optimized.summary_dict()["feed_unit_effective"] == "auto_m_per_min"
    assert any("Auto feed unit selected" in warning for warning in optimized.warning_list)
    assert original.total_time_text == "00:05:43"
    assert optimized.total_time_text == "00:06:39"
    assert compared.comparison["geometry_match"] is True
    assert compared.comparison["is_regression"] is True
    assert compared.comparison["regression_ratio"] > 0.16
    assert compared.comparison["top_time_regression_blocks"][0]["candidate_line_no"] == 870
    assert next(
        row for row in optimized.feed_histogram if row["effective_feed_band_mm_min"] == "<1000"
    )["block_count"] == 22
    assert optimized.feed_sanity_summary["feed_sanity_low_effective_count"] == 22
    assert optimized.feed_sanity_summary["feed_sanity_extreme_raw_count"] > 0


def test_comparison_segment_differences_pinpoint_slower_line(write_nc, profile_path, tmp_path) -> None:
    profile = _profile_with_feed_unit(profile_path, tmp_path, "mm_per_min")
    source = write_nc("G21 G90\nG01 X100 F6000\nX200 F6000")
    candidate = write_nc("G21 G90\nG01 X100 F6000\nX200 F100")

    compared = estimate_nc_time_with_comparison(candidate, source, profile)
    segments = compared.comparison["segment_differences"]
    top = compared.comparison["top_time_regression_blocks"][0]

    assert {"line_no", "original_feedrate", "optimized_feedrate", "delta_time_sec"}.issubset(segments[0])
    assert top["line_no"] == 3
    assert top["candidate_line_no"] == 3
    assert top["original_feedrate"] == 6000.0
    assert top["optimized_feedrate"] == 100.0
    assert top["delta_time_sec"] > 50.0


def test_comparison_marks_inserted_and_removed_geometry_segments(write_nc, profile_path) -> None:
    source = write_nc("G21 G90\nG01 X100 F1000\nX200 F1000")
    candidate = write_nc("G21 G90\nG01 X50 F1000\nX100 F1000\nX200 F1000")

    compared = estimate_nc_time_with_comparison(candidate, source, profile_path)
    statuses = {row["match_status"] for row in compared.comparison["segment_differences"]}

    assert compared.comparison["geometry_match"] is False
    assert {"matched", "original_only", "optimized_only"}.issubset(statuses)


def test_comparison_flags_low_speed_and_unit_suspect_segments(write_nc, profile_path, tmp_path) -> None:
    profile = _profile_with_feed_unit(profile_path, tmp_path, "mm_per_min")
    source = write_nc("G21 G90 G94\nG01 X100 F6000")
    candidate = write_nc("G21 G90 G94\nG01 X100 F6")

    compared = estimate_nc_time_with_comparison(candidate, source, profile, strict_feed=True)
    segment = compared.comparison["segment_differences"][0]

    assert segment["line_no"] == 2
    assert segment["optimized_effective_feed_mm_min"] == 6.0
    assert segment["is_low_speed_anomaly"] is True
    assert segment["is_unit_suspect"] is True


def _profile_with_feed_unit(profile_path: Path, tmp_path: Path, feed_unit: str) -> Path:
    text = _strip_feed_unit(profile_path.read_text(encoding="utf-8"))
    text = text.replace('units: "mm"\n', f'units: "mm"\nfeed_unit: "{feed_unit}"\n', 1)
    path = tmp_path / f"profile_{feed_unit}.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _profile_without_feed_unit(profile_path: Path, tmp_path: Path) -> Path:
    path = tmp_path / "profile_without_feed_unit.yaml"
    path.write_text(_strip_feed_unit(profile_path.read_text(encoding="utf-8")), encoding="utf-8")
    return path


def _strip_feed_unit(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("feed_unit:")) + "\n"
