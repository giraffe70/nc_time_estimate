from __future__ import annotations

import csv
from pathlib import Path

from nc_time_twin.core.report.comparison import comparison_segment_report_rows
from nc_time_twin.core.report.exporter_common import flattened_rows
from nc_time_twin.core.report.result_model import EstimateResult


def export_csv(result: EstimateResult, path: str | Path) -> None:
    comparison_rows = comparison_segment_report_rows(result.comparison) if result.comparison else []
    rows = flattened_rows(comparison_rows or result.block_table)
    if not rows:
        Path(path).write_text("", encoding="utf-8")
        return
    with Path(path).open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
