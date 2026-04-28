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
    feed_histogram_rows = "\n".join(_table_row(row) for row in flattened_rows(result.feed_histogram))
    top_slow_rows = "\n".join(_table_row(row) for row in flattened_rows(result.top_slow_blocks))
    feed_sanity_summary = [result.feed_sanity_summary] if result.feed_sanity_summary else []
    feed_sanity_summary_rows = "\n".join(_table_row(row) for row in flattened_rows(feed_sanity_summary))
    feed_sanity_issue_rows = "\n".join(_table_row(row) for row in flattened_rows(result.feed_sanity_issues))
    phase2_summary = [result.phase2_summary] if result.phase2_summary else []
    phase2_summary_rows = "\n".join(_table_row(row) for row in flattened_rows(phase2_summary))
    phase2_junction_rows = "\n".join(_table_row(row) for row in flattened_rows(result.phase2_junctions))
    phase2_bottleneck_rows = "\n".join(_table_row(row) for row in flattened_rows(result.phase2_bottlenecks))
    phase2_dynamic_rows = "\n".join(_table_row(row) for row in flattened_rows(result.phase2_dynamic_samples))
    comparison_html = _comparison_html(result)
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
  <h2>Feed Histogram</h2>
  <table>
    <thead>{_header_row(flattened_rows(result.feed_histogram))}</thead>
    <tbody>{feed_histogram_rows}</tbody>
  </table>
  <h2>Top Slow Feed Blocks</h2>
  <table>
    <thead>{_header_row(flattened_rows(result.top_slow_blocks))}</thead>
    <tbody>{top_slow_rows}</tbody>
  </table>
  <h2>Feed Sanity Summary</h2>
  <table>
    <thead>{_header_row(flattened_rows(feed_sanity_summary))}</thead>
    <tbody>{feed_sanity_summary_rows}</tbody>
  </table>
  <h2>Feed Sanity Issues</h2>
  <p>{escape(result.normalized_feed_recommendation)}</p>
  <table>
    <thead>{_header_row(flattened_rows(result.feed_sanity_issues))}</thead>
    <tbody>{feed_sanity_issue_rows}</tbody>
  </table>
  <h2>Phase 2 Summary</h2>
  <table>
    <thead>{_header_row(flattened_rows(phase2_summary))}</thead>
    <tbody>{phase2_summary_rows}</tbody>
  </table>
  <h2>Phase 2 Junctions</h2>
  <table>
    <thead>{_header_row(flattened_rows(result.phase2_junctions))}</thead>
    <tbody>{phase2_junction_rows}</tbody>
  </table>
  <h2>Phase 2 Bottlenecks</h2>
  <table>
    <thead>{_header_row(flattened_rows(result.phase2_bottlenecks))}</thead>
    <tbody>{phase2_bottleneck_rows}</tbody>
  </table>
  <h2>Phase 2 Dynamic Samples</h2>
  <table>
    <thead>{_header_row(flattened_rows(result.phase2_dynamic_samples))}</thead>
    <tbody>{phase2_dynamic_rows}</tbody>
  </table>
  {comparison_html}
  <h2>Blocks</h2>
  <table>
    <thead>{_header_row(flattened_rows(result.block_table))}</thead>
    <tbody>{block_rows}</tbody>
  </table>
</body>
</html>
"""
    Path(path).write_text(html, encoding="utf-8")


def _comparison_html(result: EstimateResult) -> str:
    comparison = result.comparison
    if not comparison:
        return ""
    summary_keys = [
        "source_label",
        "candidate_label",
        "block_count_match",
        "geometry_match",
        "is_regression",
        "max_regression_ratio",
        "regression_ratio",
        "total_time_delta_sec",
        "cutting_time_delta_sec",
    ]
    summary = [{key: comparison.get(key) for key in summary_keys}]
    band_rows = flattened_rows(comparison.get("feed_band_deltas", []))
    block_rows = flattened_rows(comparison.get("top_time_regression_blocks", []))
    return f"""
  <h2>Comparison</h2>
  <table>
    <thead>{_header_row(summary)}</thead>
    <tbody>{"".join(_table_row(row) for row in summary)}</tbody>
  </table>
  <h2>Comparison Feed Band Deltas</h2>
  <table>
    <thead>{_header_row(band_rows)}</thead>
    <tbody>{"".join(_table_row(row) for row in band_rows)}</tbody>
  </table>
  <h2>Top Time Regression Blocks</h2>
  <table>
    <thead>{_header_row(block_rows)}</thead>
    <tbody>{"".join(_table_row(row) for row in block_rows)}</tbody>
  </table>
"""


def _header_row(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    return "<tr>" + "".join(f"<th>{escape(str(key))}</th>" for key in rows[0].keys()) + "</tr>"


def _table_row(row: dict[str, object]) -> str:
    return "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row.values()) + "</tr>"
