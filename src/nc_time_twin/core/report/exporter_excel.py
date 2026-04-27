from __future__ import annotations

from html import escape
from pathlib import Path
import zipfile

from nc_time_twin.core.report.exporter_common import flattened_rows
from nc_time_twin.core.report.result_model import EstimateResult


def export_excel(result: EstimateResult, path: str | Path) -> None:
    try:
        import pandas as pd

        summary_df = pd.DataFrame([result.summary_dict()])
        blocks_df = pd.DataFrame(flattened_rows(result.block_table))
        warnings_df = pd.DataFrame({"warning": result.warning_list})
        with pd.ExcelWriter(Path(path), engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="summary", index=False)
            blocks_df.to_excel(writer, sheet_name="blocks", index=False)
            warnings_df.to_excel(writer, sheet_name="warnings", index=False)
    except ModuleNotFoundError:
        _export_minimal_xlsx(result, Path(path))


def _export_minimal_xlsx(result: EstimateResult, path: Path) -> None:
    summary = [list(result.summary_dict().keys()), list(result.summary_dict().values())]
    blocks = _dict_rows_to_matrix(flattened_rows(result.block_table))
    warnings = [["warning"], *[[warning] for warning in result.warning_list]]

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types_xml())
        zf.writestr("_rels/.rels", _root_rels_xml())
        zf.writestr("xl/workbook.xml", _workbook_xml())
        zf.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml())
        zf.writestr("xl/worksheets/sheet1.xml", _sheet_xml(summary))
        zf.writestr("xl/worksheets/sheet2.xml", _sheet_xml(blocks))
        zf.writestr("xl/worksheets/sheet3.xml", _sheet_xml(warnings))


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


def _content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""


def _root_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _workbook_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="summary" sheetId="1" r:id="rId1"/>
    <sheet name="blocks" sheetId="2" r:id="rId2"/>
    <sheet name="warnings" sheetId="3" r:id="rId3"/>
  </sheets>
</workbook>"""


def _workbook_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>
</Relationships>"""
