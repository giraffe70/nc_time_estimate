from __future__ import annotations

from html import escape
from pathlib import Path
import zipfile

from nc_time_twin.core.report.exporter_common import flattened_rows
from nc_time_twin.core.report.result_model import EstimateResult


def export_excel(result: EstimateResult, path: str | Path) -> None:
    try:
        import pandas as pd

        summary_df = pd.DataFrame(_summary_rows(result))
        blocks_df = pd.DataFrame(flattened_rows(result.block_table))
        diagnostics_df = pd.DataFrame(flattened_rows(_diagnostic_rows(result)))
        phase2_dynamic_df = pd.DataFrame(flattened_rows(result.phase2_dynamic_samples))
        with pd.ExcelWriter(Path(path), engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="summary", index=False)
            blocks_df.to_excel(writer, sheet_name="blocks", index=False)
            diagnostics_df.to_excel(writer, sheet_name="diagnostics", index=False)
            if not phase2_dynamic_df.empty:
                phase2_dynamic_df.to_excel(writer, sheet_name="phase2_dynamic", index=False)
            _add_matplotlib_chart_images(writer.book, result)
    except ModuleNotFoundError:
        _export_minimal_xlsx(result, Path(path))


def _toolpath_points(toolpath: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for segment in toolpath:
        start = segment.get("start")
        end = segment.get("end")
        if not isinstance(start, tuple) or not isinstance(end, tuple):
            continue
        rows.append({"x": start[0], "y": start[1], "line_no": segment.get("line_no")})
        rows.append({"x": end[0], "y": end[1], "line_no": segment.get("line_no")})
        rows.append({"x": None, "y": None, "line_no": None})
    return rows


def _add_matplotlib_chart_images(workbook, result: EstimateResult) -> bool:
    try:
        from io import BytesIO

        from matplotlib.figure import Figure
        from openpyxl.drawing.image import Image
    except Exception:
        return False

    chart_sheet = workbook.create_sheet("charts")
    has_phase2 = bool(result.phase2_dynamic_samples)
    figure = Figure(figsize=(10.8, 7.0 if has_phase2 else 5.2), dpi=120)
    if has_phase2:
        path_ax = figure.add_subplot(311)
        time_ax = figure.add_subplot(312)
        velocity_ax = figure.add_subplot(313)
    else:
        path_ax = figure.add_subplot(211)
        time_ax = figure.add_subplot(212)

    xs: list[float | None] = []
    ys: list[float | None] = []
    times: list[float] = []
    for block in result.ir_program:
        if block.start is not None and block.end is not None:
            xs.extend([block.start.x, block.end.x, None])
            ys.extend([block.start.y, block.end.y, None])
        times.append(block.estimated_time)

    path_ax.plot(xs, ys, linewidth=1.0)
    path_ax.set_title("XY Toolpath")
    path_ax.set_aspect("equal", adjustable="datalim")
    path_ax.grid(True, linewidth=0.3)

    time_ax.bar(range(len(times)), times)
    time_ax.set_title("Block Time")
    time_ax.set_xlabel("Block index")
    time_ax.set_ylabel("sec")
    time_ax.grid(True, axis="y", linewidth=0.3)
    if has_phase2:
        velocity_ax.plot(
            [sample["time_sec"] for sample in result.phase2_dynamic_samples],
            [sample["velocity_mm_s"] for sample in result.phase2_dynamic_samples],
            linewidth=0.8,
        )
        velocity_ax.set_title("Phase 2 Velocity")
        velocity_ax.set_xlabel("sec")
        velocity_ax.set_ylabel("mm/s")
        velocity_ax.grid(True, linewidth=0.3)
    figure.tight_layout()

    image_buffer = BytesIO()
    figure.savefig(image_buffer, format="png")
    image_buffer.seek(0)
    image = Image(image_buffer)
    chart_sheet.add_image(image, "A1")
    return True


def _export_minimal_xlsx(result: EstimateResult, path: Path) -> None:
    summary = _dict_rows_to_matrix(_summary_rows(result))
    blocks = _dict_rows_to_matrix(flattened_rows(result.block_table))
    diagnostics = _dict_rows_to_matrix(flattened_rows(_diagnostic_rows(result)))
    phase2_dynamic = _dict_rows_to_matrix(flattened_rows(result.phase2_dynamic_samples))
    sheets = [
        ("summary", summary),
        ("blocks", blocks),
        ("diagnostics", diagnostics),
    ]
    if result.phase2_dynamic_samples:
        sheets.append(("phase2_dynamic", phase2_dynamic))

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types_xml(len(sheets)))
        zf.writestr("_rels/.rels", _root_rels_xml())
        zf.writestr("xl/workbook.xml", _workbook_xml([name for name, _ in sheets]))
        zf.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(len(sheets)))
        for index, (_, rows) in enumerate(sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(rows))


def _diagnostic_rows(result: EstimateResult) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, warning in enumerate(result.warning_list, start=1):
        rows.append(
            {
                "section": "warnings",
                "item": index,
                "line_no": None,
                "severity": None,
                "code": None,
                "metric": "warning",
                "value": warning,
                "message": warning,
                "recommendation": None,
                "raw": None,
            }
        )
    for row in result.feed_histogram:
        rows.append(
            {
                "section": "feed_histogram",
                "item": row.get("effective_feed_band_mm_min"),
                "line_no": None,
                "severity": None,
                "code": None,
                "metric": "time_sec",
                "value": row.get("time_sec"),
                "message": (
                    f"band={row.get('effective_feed_band_mm_min')}, "
                    f"count={row.get('block_count')}, length_mm={row.get('length_mm')}"
                ),
                "recommendation": None,
                "raw": None,
            }
        )
    for row in result.top_slow_blocks:
        rows.append(
            {
                "section": "top_slow_blocks",
                "item": row.get("type"),
                "line_no": row.get("line_no"),
                "severity": None,
                "code": None,
                "metric": "estimated_time_sec",
                "value": row.get("estimated_time_sec"),
                "message": (
                    f"feed={row.get('feedrate')}, effective_feed_mm_min="
                    f"{row.get('effective_feed_mm_min')}, length_mm={row.get('length_mm')}"
                ),
                "recommendation": None,
                "raw": row.get("raw"),
            }
        )
    for key, value in result.feed_sanity_summary.items():
        rows.append(
            {
                "section": "feed_sanity_summary",
                "item": key,
                "line_no": None,
                "severity": None,
                "code": None,
                "metric": key,
                "value": value,
                "message": None,
                "recommendation": None,
                "raw": None,
            }
        )
    if result.normalized_feed_recommendation:
        rows.append(
            {
                "section": "feed_recommendation",
                "item": "normalized_feed_recommendation",
                "line_no": None,
                "severity": None,
                "code": None,
                "metric": "recommendation",
                "value": result.normalized_feed_recommendation,
                "message": result.normalized_feed_recommendation,
                "recommendation": result.normalized_feed_recommendation,
                "raw": None,
            }
        )
    for row in result.feed_sanity_issues:
        rows.append(
            {
                "section": "feed_sanity_issues",
                "item": row.get("sample_lines") or row.get("line_no"),
                "line_no": row.get("line_no"),
                "severity": row.get("severity"),
                "code": row.get("code"),
                "metric": "effective_feed_mm_min",
                "value": row.get("effective_feed_mm_min"),
                "message": row.get("message"),
                "recommendation": row.get("recommendation"),
                "raw": row.get("raw"),
            }
        )
    for key, value in result.phase2_summary.items():
        rows.append(
            {
                "section": "phase2_summary",
                "item": key,
                "line_no": None,
                "severity": None,
                "code": None,
                "metric": key,
                "value": value,
                "message": None,
                "recommendation": None,
                "raw": None,
            }
        )
    for row in result.phase2_junctions:
        rows.append(
            {
                "section": "phase2_junctions",
                "item": row.get("index"),
                "line_no": None,
                "severity": None,
                "code": row.get("reason"),
                "metric": "v_junction_limit_mm_s",
                "value": row.get("v_junction_limit_mm_s"),
                "message": f"angle_deg={row.get('angle_deg')}, tolerance_mm={row.get('tolerance_mm')}",
                "recommendation": None,
                "raw": None,
            }
        )
    for row in result.phase2_bottlenecks:
        rows.append(
            {
                "section": "phase2_bottlenecks",
                "item": row.get("segment_id"),
                "line_no": row.get("line_no"),
                "severity": "warning",
                "code": "phase2_bottleneck",
                "metric": "slowdown_ratio",
                "value": row.get("slowdown_ratio"),
                "message": row.get("reason"),
                "recommendation": None,
                "raw": row.get("raw"),
            }
        )
    rows.extend(_comparison_diagnostic_rows(result))
    return rows


def _summary_rows(result: EstimateResult) -> list[dict[str, object]]:
    return [{"metric": key, "value": value} for key, value in result.summary_dict().items()]


def _comparison_diagnostic_rows(result: EstimateResult) -> list[dict[str, object]]:
    comparison = result.comparison
    if not comparison:
        return []
    rows: list[dict[str, object]] = []
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
        "source_total_time_text",
        "candidate_total_time_text",
    ]
    for key in summary_keys:
        rows.append(
            {
                "section": "comparison_summary",
                "item": key,
                "line_no": None,
                "severity": "critical" if key == "is_regression" and comparison.get(key) else None,
                "code": "time_regression" if key == "is_regression" and comparison.get(key) else None,
                "metric": key,
                "value": comparison.get(key),
                "message": None,
                "recommendation": None,
                "raw": None,
            }
        )
    for row in comparison.get("feed_band_deltas", []):
        rows.append(
            {
                "section": "comparison_feed_band_deltas",
                "item": row.get("candidate_effective_feed_band_mm_min"),
                "line_no": None,
                "severity": None,
                "code": None,
                "metric": "delta_time_sec",
                "value": row.get("delta_time_sec"),
                "message": (
                    f"count={row.get('block_count')}, source_time_sec={row.get('source_time_sec')}, "
                    f"candidate_time_sec={row.get('candidate_time_sec')}"
                ),
                "recommendation": None,
                "raw": None,
            }
        )
    for row in comparison.get("top_time_regression_blocks", []):
        rows.append(
            {
                "section": "top_time_regression_blocks",
                "item": row.get("type"),
                "line_no": row.get("candidate_line_no"),
                "severity": "warning" if (row.get("delta_time_sec") or 0) > 0 else None,
                "code": "time_delta",
                "metric": "delta_time_sec",
                "value": row.get("delta_time_sec"),
                "message": (
                    f"source_F={row.get('source_feedrate')}, candidate_F={row.get('candidate_feedrate')}, "
                    f"candidate_effective_feed_mm_min={row.get('candidate_effective_feed_mm_min')}"
                ),
                "recommendation": None,
                "raw": row.get("candidate_raw"),
            }
        )
    return rows


def _dict_rows_to_matrix(rows: list[dict[str, object]]) -> list[list[object]]:
    if not rows:
        return [[]]
    headers = list(rows[0].keys())
    return [headers, *[[row.get(header, "") for header in headers] for row in rows]]


def _sheet_xml(rows: list[list[object]]) -> str:
    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{_column_name(col_index)}{row_index}"
            cells.append(_cell_xml(ref, value))
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        "</worksheet>"
    )


def _cell_xml(ref: str, value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _content_types_xml(sheet_count: int) -> str:
    sheet_overrides = "\n".join(
        f'  <Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
{sheet_overrides}
</Types>"""


def _root_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _workbook_xml(sheet_names: list[str]) -> str:
    sheet_xml = "\n".join(
        f'    <sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
{sheet_xml}
  </sheets>
</workbook>"""


def _workbook_rels_xml(sheet_count: int) -> str:
    rels_xml = "\n".join(
        f'  <Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{rels_xml}
</Relationships>"""
