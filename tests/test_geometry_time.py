from __future__ import annotations

import math

from nc_time_twin import estimate_nc_time


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
