from __future__ import annotations

import csv
from pathlib import Path

from nc_time_twin.core.report.exporter_common import flattened_rows
from nc_time_twin.core.report.result_model import EstimateResult


def export_csv(result: EstimateResult, path: str | Path) -> None:
    rows = flattened_rows(result.block_table)
    if not rows:
        Path(path).write_text("", encoding="utf-8")
        return
    with Path(path).open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
