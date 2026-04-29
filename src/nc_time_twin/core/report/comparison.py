from __future__ import annotations

from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from nc_time_twin.core.feed_sanity import (
    EXTREME_RAW_MULTIPLIER,
    LOW_EFFECTIVE_FEED_MM_MIN,
    LOW_RAW_G94_FEED,
)

if TYPE_CHECKING:
    from nc_time_twin.core.report.result_model import EstimateResult


FEED_HISTOGRAM_BANDS: tuple[tuple[str, float | None, float | None], ...] = (
    ("<1000", None, 1000.0),
    ("1000-2999", 1000.0, 3000.0),
    ("3000-4499", 3000.0, 4500.0),
    ("4500-5999", 4500.0, 6000.0),
    (">=6000", 6000.0, None),
)

COMPARISON_BLOCK_TYPES = {"rapid", "linear", "arc"}
UNIT_SUSPECT_CODES = {"mixed_feed_scale", "mixed_low_feed_scale", "extreme_raw_feed"}

COMPARISON_SEGMENT_REPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("line_no", "line_no"),
    ("original_feedrate", "原始 F"),
    ("optimized_feedrate", "優化後 F"),
    ("original_effective_feed_mm_min", "原始有效 feed"),
    ("optimized_effective_feed_mm_min", "優化後有效 feed"),
    ("original_time_sec", "原始時間"),
    ("optimized_time_sec", "優化後時間"),
    ("delta_time_sec", "時間差"),
    ("is_low_speed_anomaly", "是否低速異常"),
    ("is_unit_suspect", "是否單位疑似異常"),
    ("match_status", "match_status"),
    ("original_line_no", "original_line_no"),
    ("optimized_line_no", "optimized_line_no"),
    ("type", "type"),
    ("original_raw", "original_raw"),
    ("optimized_raw", "optimized_raw"),
)


def compare_estimate_results(
    source: EstimateResult,
    candidate: EstimateResult,
    *,
    source_label: str = "source",
    candidate_label: str = "candidate",
    max_regression_ratio: float = 0.0,
    limit: int = 20,
) -> dict[str, Any]:
    block_count_match = len(source.block_table) == len(candidate.block_table)
    geometry_match = _geometry_matches(source.block_table, candidate.block_table) if block_count_match else False
    segment_rows = _comparison_segment_rows(source, candidate)
    top_delta_rows = sorted(segment_rows, key=lambda row: row["delta_time_sec"], reverse=True)[:limit]
    band_rows = _comparison_band_rows(segment_rows)
    total_delta = candidate.total_time_sec - source.total_time_sec
    cutting_delta = candidate.cutting_time_sec - source.cutting_time_sec
    regression_ratio = total_delta / source.total_time_sec if source.total_time_sec > 0 else 0.0
    is_regression = geometry_match and regression_ratio > max_regression_ratio
    return {
        "source_label": source_label,
        "candidate_label": candidate_label,
        "block_count_match": block_count_match,
        "geometry_match": geometry_match,
        "is_regression": is_regression,
        "max_regression_ratio": max_regression_ratio,
        "regression_ratio": regression_ratio,
        "total_time_delta_sec": total_delta,
        "cutting_time_delta_sec": cutting_delta,
        "source_total_time_sec": source.total_time_sec,
        "candidate_total_time_sec": candidate.total_time_sec,
        "source_total_time_text": source.total_time_text,
        "candidate_total_time_text": candidate.total_time_text,
        "feed_band_deltas": band_rows,
        "top_time_regression_blocks": top_delta_rows,
        "segment_differences": segment_rows,
    }


def comparison_segment_report_rows(comparison: dict[str, Any]) -> list[dict[str, Any]]:
    rows = comparison.get("segment_differences", [])
    if not isinstance(rows, list):
        return []
    report_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        report_rows.append({label: row.get(key) for key, label in COMPARISON_SEGMENT_REPORT_COLUMNS})
    return report_rows


def _comparison_segment_rows(source: EstimateResult, candidate: EstimateResult) -> list[dict[str, Any]]:
    source_rows = _comparison_rows(source.block_table)
    candidate_rows = _comparison_rows(candidate.block_table)
    source_signatures = [_geometry_signature(row) for row in source_rows]
    candidate_signatures = [_geometry_signature(row) for row in candidate_rows]
    issue_codes_by_line = _issue_codes_by_line(candidate.feed_sanity_issues)
    rows: list[dict[str, Any]] = []

    if source_signatures == candidate_signatures:
        for source_row, candidate_row in zip(source_rows, candidate_rows, strict=False):
            rows.append(_segment_row(source_row, candidate_row, "matched", issue_codes_by_line, candidate))
        return rows

    matcher = SequenceMatcher(None, source_signatures, candidate_signatures, autojunk=False)
    for tag, source_start, source_end, candidate_start, candidate_end in matcher.get_opcodes():
        if tag == "equal":
            for source_row, candidate_row in zip(
                source_rows[source_start:source_end],
                candidate_rows[candidate_start:candidate_end],
                strict=False,
            ):
                rows.append(_segment_row(source_row, candidate_row, "matched", issue_codes_by_line, candidate))
            continue
        for source_row in source_rows[source_start:source_end]:
            rows.append(_segment_row(source_row, None, "original_only", issue_codes_by_line, candidate))
        for candidate_row in candidate_rows[candidate_start:candidate_end]:
            rows.append(_segment_row(None, candidate_row, "optimized_only", issue_codes_by_line, candidate))
    return rows


def _comparison_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("type") in COMPARISON_BLOCK_TYPES]


def _segment_row(
    source_row: dict[str, Any] | None,
    candidate_row: dict[str, Any] | None,
    match_status: str,
    issue_codes_by_line: dict[int, set[str]],
    candidate: EstimateResult,
) -> dict[str, Any]:
    original_time = _float_value(source_row, "estimated_time_sec")
    optimized_time = _float_value(candidate_row, "estimated_time_sec")
    optimized_line = _line_no(candidate_row)
    original_line = _line_no(source_row)
    optimized_feed = _value(candidate_row, "feedrate")
    optimized_effective_feed = _value(candidate_row, "effective_feed_mm_min")
    issue_codes = issue_codes_by_line.get(optimized_line or -1, set())
    return {
        "line_no": optimized_line,
        "original_line_no": original_line,
        "optimized_line_no": optimized_line,
        "source_line_no": original_line,
        "candidate_line_no": optimized_line,
        "type": _value(candidate_row, "type") or _value(source_row, "type"),
        "match_status": match_status,
        "length_mm": _value(candidate_row, "length_mm") or _value(source_row, "length_mm"),
        "original_length_mm": _value(source_row, "length_mm"),
        "optimized_length_mm": _value(candidate_row, "length_mm"),
        "source_time_sec": original_time,
        "candidate_time_sec": optimized_time,
        "original_time_sec": original_time,
        "optimized_time_sec": optimized_time,
        "delta_time_sec": optimized_time - original_time,
        "source_feedrate": _value(source_row, "feedrate"),
        "candidate_feedrate": optimized_feed,
        "original_feedrate": _value(source_row, "feedrate"),
        "optimized_feedrate": optimized_feed,
        "source_effective_feed_mm_min": _value(source_row, "effective_feed_mm_min"),
        "candidate_effective_feed_mm_min": optimized_effective_feed,
        "original_effective_feed_mm_min": _value(source_row, "effective_feed_mm_min"),
        "optimized_effective_feed_mm_min": optimized_effective_feed,
        "original_feed_unit": _value(source_row, "feed_unit"),
        "optimized_feed_unit": _value(candidate_row, "feed_unit"),
        "candidate_feed_unit": _value(candidate_row, "feed_unit"),
        "original_feed_mode": _value(source_row, "feed_mode"),
        "optimized_feed_mode": _value(candidate_row, "feed_mode"),
        "is_low_speed_anomaly": _is_low_speed_anomaly(optimized_effective_feed, issue_codes),
        "is_unit_suspect": _is_unit_suspect(candidate_row, issue_codes, candidate),
        "original_raw": _value(source_row, "raw"),
        "optimized_raw": _value(candidate_row, "raw"),
        "candidate_raw": _value(candidate_row, "raw"),
    }


def _comparison_band_rows(delta_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, low, high in FEED_HISTOGRAM_BANDS:
        band = [
            row
            for row in delta_rows
            if row.get("optimized_effective_feed_mm_min") is not None
            and _value_in_band(float(row["optimized_effective_feed_mm_min"]), low, high)
        ]
        rows.append(
            {
                "candidate_effective_feed_band_mm_min": label,
                "block_count": len(band),
                "length_mm": sum(float(row.get("optimized_length_mm") or row.get("length_mm") or 0.0) for row in band),
                "source_time_sec": sum(float(row.get("original_time_sec") or 0.0) for row in band),
                "candidate_time_sec": sum(float(row.get("optimized_time_sec") or 0.0) for row in band),
                "delta_time_sec": sum(float(row.get("delta_time_sec") or 0.0) for row in band),
            }
        )
    return rows


def _issue_codes_by_line(issues: list[dict[str, Any]]) -> dict[int, set[str]]:
    codes_by_line: dict[int, set[str]] = {}
    for issue in issues:
        code = str(issue.get("code") or "")
        line_no = issue.get("line_no")
        if isinstance(line_no, int):
            codes_by_line.setdefault(line_no, set()).add(code)
        sample_lines = issue.get("sample_lines")
        if isinstance(sample_lines, str):
            for part in sample_lines.split(","):
                stripped = part.strip()
                if stripped.isdigit():
                    codes_by_line.setdefault(int(stripped), set()).add(code)
    return codes_by_line


def _is_low_speed_anomaly(effective_feed: object, issue_codes: set[str]) -> bool:
    if "low_effective_feed" in issue_codes:
        return True
    if isinstance(effective_feed, (int, float)) and 0 < float(effective_feed) < LOW_EFFECTIVE_FEED_MM_MIN:
        return True
    return False


def _is_unit_suspect(
    candidate_row: dict[str, Any] | None,
    issue_codes: set[str],
    candidate: EstimateResult,
) -> bool:
    if issue_codes.intersection(UNIT_SUSPECT_CODES):
        return True
    if candidate_row is None:
        return False
    feedrate = candidate_row.get("feedrate")
    if not isinstance(feedrate, (int, float)) or feedrate <= 0:
        return False
    if candidate_row.get("type") not in {"linear", "arc"}:
        return False
    if candidate_row.get("feed_mode") != "G94":
        return False
    if 0 < float(feedrate) < LOW_RAW_G94_FEED:
        return True
    threshold = candidate.feed_sanity_summary.get("feed_sanity_extreme_raw_threshold")
    if not isinstance(threshold, (int, float)):
        max_raw = candidate.summary_dict().get("feed_max_raw")
        threshold = float(max_raw) * EXTREME_RAW_MULTIPLIER if isinstance(max_raw, (int, float)) else None
    return isinstance(threshold, (int, float)) and float(feedrate) > float(threshold)


def _geometry_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("type"),
        _rounded_tuple(row.get("start")),
        _rounded_tuple(row.get("end")),
        _rounded_number(row.get("length_mm")),
    )


def _geometry_matches(source_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> bool:
    for source_row, candidate_row in zip(source_rows, candidate_rows, strict=False):
        if source_row.get("type") != candidate_row.get("type"):
            return False
        if not _nearly_equal(source_row.get("length_mm"), candidate_row.get("length_mm")):
            return False
        if _rounded_tuple(source_row.get("start")) != _rounded_tuple(candidate_row.get("start")):
            return False
        if _rounded_tuple(source_row.get("end")) != _rounded_tuple(candidate_row.get("end")):
            return False
    return True


def _value(row: dict[str, Any] | None, key: str) -> Any:
    return row.get(key) if row is not None else None


def _float_value(row: dict[str, Any] | None, key: str) -> float:
    value = _value(row, key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _line_no(row: dict[str, Any] | None) -> int | None:
    value = _value(row, "line_no")
    return int(value) if isinstance(value, int) else None


def _rounded_tuple(value: object, digits: int = 6) -> tuple[float, ...] | None:
    if not isinstance(value, tuple):
        return None
    return tuple(round(float(part), digits) for part in value)


def _rounded_number(value: object, digits: int = 6) -> float | None:
    return round(float(value), digits) if isinstance(value, (int, float)) else None


def _value_in_band(value: float, low: float | None, high: float | None) -> bool:
    if low is not None and value < low:
        return False
    if high is not None and value >= high:
        return False
    return True


def _nearly_equal(left: object, right: object, tolerance: float = 1e-6) -> bool:
    if left is None and right is None:
        return True
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return left == right
    return abs(float(left) - float(right)) <= tolerance
