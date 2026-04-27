from __future__ import annotations

import json
import math

from nc_time_twin import estimate_nc_time
from nc_time_twin.cli import main
from nc_time_twin.core.report.exporters import export_result


def test_event_times_and_dwell(write_nc, profile_path) -> None:
    nc = write_nc(
        """
        G21 G90
        T1 M06
        S1000 M03
        M08
        G04 P1000
        M09
        M05
        """
    )
    result = estimate_nc_time(nc, profile_path)
    assert math.isclose(result.tool_change_time_sec, 8.0, rel_tol=1e-9)
    assert math.isclose(result.spindle_time_sec, 3.0, rel_tol=1e-9)
    assert math.isclose(result.coolant_time_sec, 1.0, rel_tol=1e-9)
    assert math.isclose(result.dwell_time_sec, 1.0, rel_tol=1e-9)


def test_g81_g82_g83_cycles_expand(write_nc, profile_path) -> None:
    nc = write_nc(
        """
        G21 G90 G17
        G81 X20 Y0 Z-5 R2 F300
        G82 X30 Y0 Z-4 R2 P500 F300
        G83 X40 Y0 Z-9 R2 Q3 F300
        G80
        """
    )
    result = estimate_nc_time(nc, profile_path)
    types = [block.display_type for block in result.ir_program]
    assert types[:4] == ["rapid", "rapid", "linear", "rapid"]
    assert "dwell" in types
    assert types.count("linear") >= 5
    assert result.ir_program[-1].end.as_tuple() == (40.0, 0.0, 2.0)


def test_json_csv_excel_html_exports(write_nc, profile_path, artifact_path) -> None:
    nc = write_nc("G21 G90\nG01 X100 F1000")
    result = estimate_nc_time(nc, profile_path)
    for suffix in ("json", "csv", "xlsx", "html"):
        out = artifact_path(suffix)
        export_result(result, out)
        assert out.exists()
        assert out.stat().st_size > 0


def test_cli_estimate_json(write_nc, profile_path, artifact_path) -> None:
    nc = write_nc("G21 G90\nG01 X100 F1000")
    out = artifact_path("json")
    exit_code = main(["estimate", "--nc", str(nc), "--profile", str(profile_path), "--out", str(out)])
    assert exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["total_time_sec"] == 6.0
