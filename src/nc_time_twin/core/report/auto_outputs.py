from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from nc_time_twin.core.report.exporters import export_result
from nc_time_twin.core.report.result_model import EstimateResult


@dataclass(frozen=True)
class AutoOutputPaths:
    report_path: Path
    log_path: Path


def write_auto_outputs(
    result: EstimateResult,
    nc_file_path: str | Path,
    *,
    base_dir: str | Path = ".",
    now: datetime | None = None,
    report_format: str = "xlsx",
) -> AutoOutputPaths:
    root = Path(base_dir)
    output_dir = root / "output"
    log_dir = root / "logs"
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = now or datetime.now()
    filename = _output_filename(nc_file_path, timestamp)
    report_path = output_dir / f"Report_{filename}.{_report_suffix(report_format)}"
    log_path = log_dir / f"{filename}.log"

    export_result(result, report_path, report_format)
    _write_log(result, nc_file_path, log_path)
    return AutoOutputPaths(report_path=report_path, log_path=log_path)


def write_auto_log(
    result: EstimateResult,
    nc_file_path: str | Path,
    *,
    base_dir: str | Path = ".",
    now: datetime | None = None,
) -> Path:
    root = Path(base_dir)
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    filename = _output_filename(nc_file_path, now or datetime.now())
    log_path = log_dir / f"{filename}.log"
    _write_log(result, nc_file_path, log_path)
    return log_path


def manual_export_path(
    nc_file_path: str | Path,
    export_format: str,
    *,
    base_dir: str | Path = ".",
    now: datetime | None = None,
) -> Path:
    output_dir = Path(base_dir) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = _output_filename(nc_file_path, now or datetime.now())
    return output_dir / f"{filename}.{_report_suffix(export_format)}"


def manual_export_path_in_dir(
    nc_file_path: str | Path,
    export_format: str,
    output_dir: str | Path,
    *,
    now: datetime | None = None,
) -> Path:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = _output_filename(nc_file_path, now or datetime.now())
    return target_dir / f"{filename}.{_report_suffix(export_format)}"


def _output_filename(nc_file_path: str | Path, timestamp: datetime) -> str:
    stem = Path(nc_file_path).stem or "nc_code"
    safe_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).strip()
    safe_stem = safe_stem.rstrip(" ._") or "nc_code"
    return f"{safe_stem}_{timestamp:%Y%m%d_%H%M}"


def _report_suffix(report_format: str) -> str:
    normalized = report_format.lower()
    if normalized == "excel":
        return "xlsx"
    return normalized


def _write_log(result: EstimateResult, nc_file_path: str | Path, log_path: Path) -> None:
    lines = [
        "NC-Time-Twin Estimate Log",
        f"NC-Code: {Path(nc_file_path).resolve()}",
        f"Generated at: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "Summary:",
    ]
    lines.extend(f"  {key}: {value}" for key, value in result.summary_dict().items())
    lines.extend(["", "Warnings:"])
    if result.warning_list:
        lines.extend(f"  - {warning}" for warning in result.warning_list)
    else:
        lines.append("  None")
    lines.extend(["", "Feed Histogram:"])
    if result.feed_histogram:
        for row in result.feed_histogram:
            lines.append(
                "  - "
                f"{row['effective_feed_band_mm_min']}: "
                f"count={row['block_count']}, "
                f"time_sec={row['time_sec']:.6g}, "
                f"length_mm={row['length_mm']:.6g}"
            )
    else:
        lines.append("  None")
    lines.extend(["", "Top Slow Feed Blocks:"])
    if result.top_slow_blocks:
        for row in result.top_slow_blocks[:20]:
            lines.append(
                "  - "
                f"Line {row['line_no']}: "
                f"time_sec={row['estimated_time_sec']:.6g}, "
                f"length_mm={row['length_mm']:.6g}, "
                f"raw_F={row['feedrate']}, "
                f"effective_feed_mm_min={row['effective_feed_mm_min']}, "
                f"raw={row['raw']}"
            )
    else:
        lines.append("  None")
    lines.extend(["", "Feed Sanity Summary:"])
    if result.feed_sanity_summary:
        lines.extend(f"  {key}: {value}" for key, value in result.feed_sanity_summary.items())
        lines.append(f"  normalized_feed_recommendation: {result.normalized_feed_recommendation}")
    else:
        lines.append("  None")
    lines.extend(["", "Feed Sanity Issues:"])
    if result.feed_sanity_issues:
        for row in result.feed_sanity_issues[:50]:
            location = f"Line {row['line_no']}" if row.get("line_no") is not None else "Program"
            lines.append(
                "  - "
                f"{location}: "
                f"{row['severity']} {row['code']}: "
                f"{row['message']} "
                f"recommendation={row['recommendation']}"
            )
    else:
        lines.append("  None")
    if result.comparison:
        comparison = result.comparison
        lines.extend(["", "Comparison:"])
        lines.append(f"  source: {comparison['source_label']}")
        lines.append(f"  candidate: {comparison['candidate_label']}")
        lines.append(f"  geometry_match: {comparison['geometry_match']}")
        lines.append(f"  total_time_delta_sec: {comparison['total_time_delta_sec']}")
        lines.append(f"  cutting_time_delta_sec: {comparison['cutting_time_delta_sec']}")
        lines.append(f"  regression_ratio: {comparison['regression_ratio']}")
        lines.append(f"  max_regression_ratio: {comparison['max_regression_ratio']}")
        lines.append(f"  is_regression: {comparison['is_regression']}")
        lines.extend(["", "Comparison Feed Band Deltas:"])
        for row in comparison.get("feed_band_deltas", []):
            lines.append(
                "  - "
                f"{row['candidate_effective_feed_band_mm_min']}: "
                f"count={row['block_count']}, "
                f"delta_time_sec={row['delta_time_sec']:.6g}"
            )
        lines.extend(["", "Top Time Regression Blocks:"])
        for row in comparison.get("top_time_regression_blocks", [])[:20]:
            lines.append(
                "  - "
                f"Candidate line {row['candidate_line_no']}: "
                f"delta_time_sec={row['delta_time_sec']:.6g}, "
                f"source_F={row['source_feedrate']}, "
                f"candidate_F={row['candidate_feedrate']}, "
                f"candidate_effective_feed_mm_min={row['candidate_effective_feed_mm_min']}, "
                f"raw={row['candidate_raw']}"
            )
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
