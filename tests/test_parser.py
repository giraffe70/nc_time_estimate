from __future__ import annotations

import math

from nc_time_twin import estimate_nc_time
from nc_time_twin.core.parser.macro import expand_macro_variables, update_macro_table
from nc_time_twin.core.parser.preprocess import preprocess_nc_lines
from nc_time_twin.core.parser.tokenizer import tokenize


def test_preprocess_removes_comments_sequence_and_normalizes_case() -> None:
    lines = preprocess_nc_lines(["%", "n100 g01 x10 (tool) y20 ; comment", "O1234"])
    assert len(lines) == 1
    assert lines[0].line_no == 2
    assert lines[0].clean == "G01 X10 Y20"


def test_tokenizer_normalizes_multiple_g_and_m_codes() -> None:
    tokens = tokenize("G001 G90 M03 X-10.5 Y.25 F800.")
    assert tokens.g_codes() == [1, 90]
    assert tokens.m_codes() == [3]
    assert tokens.get_float("X") == -10.5
    assert tokens.get_float("Y") == 0.25
    assert tokens.get_float("F") == 800.0


def test_simple_macro_replacement() -> None:
    table: dict[str, float] = {}
    update_macro_table("#101=930.5", table)
    expanded, warnings = expand_macro_variables("G01 X100 F#101", table)
    assert expanded == "G01 X100 F930.5"
    assert warnings == []


def test_modal_continuation_and_partial_axis_updates(write_nc, profile_path) -> None:
    nc = write_nc(
        """
        G21 G90 G17
        G01 X100 F1000
        Y100
        X0
        """
    )
    result = estimate_nc_time(nc, profile_path)
    linear_blocks = [block for block in result.ir_program if block.display_type == "linear"]
    assert len(linear_blocks) == 3
    assert [block.end.as_tuple() for block in linear_blocks] == [
        (100.0, 0.0, 0.0),
        (100.0, 100.0, 0.0),
        (0.0, 100.0, 0.0),
    ]
    assert math.isclose(result.cutting_time_sec, 18.0, rel_tol=1e-9)


def test_relative_coordinates(write_nc, profile_path) -> None:
    nc = write_nc(
        """
        G21 G91
        G01 X10 F600
        X10
        X10
        """
    )
    result = estimate_nc_time(nc, profile_path)
    linear_blocks = [block for block in result.ir_program if block.display_type == "linear"]
    assert linear_blocks[-1].end.as_tuple() == (30.0, 0.0, 0.0)
    assert math.isclose(sum(block.length for block in linear_blocks), 30.0, rel_tol=1e-9)
