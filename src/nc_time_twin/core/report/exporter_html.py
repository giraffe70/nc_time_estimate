from __future__ import annotations

from html import escape
from pathlib import Path

from nc_time_twin.core.report.exporter_common import flattened_rows
from nc_time_twin.core.report.result_model import EstimateResult


def export_html(result: EstimateResult, path: str | Path) -> None:
    summary_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in result.summary_dict().items()
    )
    block_rows = "\n".join(_table_row(row) for row in flattened_rows(result.block_table))
    warning_items = "\n".join(f"<li>{escape(warning)}</li>" for warning in result.warning_list)
    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <title>NC-Code 加工時間估測報告</title>
  <style>
    body {{ font-family: Arial, "Microsoft JhengHei", sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 13px; }}
    th, td {{ border: 1px solid #c8d1dc; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #eef3f8; }}
    h1, h2 {{ margin-bottom: 8px; }}
  </style>
</head>
<body>
  <h1>NC-Code 加工時間估測報告</h1>
  <h2>Summary</h2>
  <table>{summary_rows}</table>
  <h2>Warnings</h2>
  <ul>{warning_items}</ul>
  <h2>Blocks</h2>
  <table>
    <thead>{_header_row(flattened_rows(result.block_table))}</thead>
    <tbody>{block_rows}</tbody>
  </table>
</body>
</html>
"""
    Path(path).write_text(html, encoding="utf-8")


def _header_row(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    return "<tr>" + "".join(f"<th>{escape(str(key))}</th>" for key in rows[0].keys()) + "</tr>"


def _table_row(row: dict[str, object]) -> str:
    return "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row.values()) + "</tr>"
