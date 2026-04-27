from __future__ import annotations

from pathlib import Path

from nc_time_twin.core.report.exporter_csv import export_csv
from nc_time_twin.core.report.exporter_excel import export_excel
from nc_time_twin.core.report.exporter_html import export_html
from nc_time_twin.core.report.exporter_json import export_json
from nc_time_twin.core.report.result_model import EstimateResult


def export_result(result: EstimateResult, path: str | Path, fmt: str | None = None) -> None:
    target = Path(path)
    export_format = (fmt or target.suffix.lstrip(".")).lower()
    if export_format == "csv":
        export_csv(result, target)
    elif export_format == "json":
        export_json(result, target)
    elif export_format in {"xlsx", "excel"}:
        export_excel(result, target)
    elif export_format == "html":
        export_html(result, target)
    else:
        raise ValueError(f"Unsupported export format: {export_format}")
