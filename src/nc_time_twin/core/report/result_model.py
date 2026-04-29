from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nc_time_twin.core.ir.blocks import (
    ArcMoveBlock,
    BaseBlock,
    CoolantEventBlock,
    LinearMoveBlock,
    OptionalStopBlock,
    ReferenceReturnBlock,
    SmoothingEventBlock,
    SpindleEventBlock,
    ToolChangeBlock,
)


FEED_HISTOGRAM_BANDS: tuple[tuple[str, float | None, float | None], ...] = (
    ("<1000", None, 1000.0),
    ("1000-2999", 1000.0, 3000.0),
    ("3000-4499", 3000.0, 4500.0),
    ("4500-5999", 4500.0, 6000.0),
    (">=6000", 6000.0, None),
)


def format_seconds(seconds: float) -> str:
    rounded = int(round(seconds))
    hours, rem = divmod(rounded, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def block_to_row(block: BaseBlock) -> dict[str, Any]:
    row: dict[str, Any] = {
        "line_no": block.line_no,
        "raw": block.raw,
        "type": block.display_type,
        "start": block.start_tuple(),
        "end": block.end_tuple(),
        "length_mm": block.length,
        "estimated_time_sec": block.estimated_time,
        "warnings": "; ".join(block.warnings),
    }
    if isinstance(block, (LinearMoveBlock, ArcMoveBlock)):
        row["feedrate"] = block.feedrate
        row["feed_mode"] = block.feed_mode
        row["spindle_speed"] = block.spindle_speed
        row["feed_unit"] = block.feed_unit
        row["effective_feed_mm_min"] = block.effective_feed_mm_min
        row["feed_capped"] = block.feed_capped
    else:
        row["feedrate"] = None
        row["feed_mode"] = None
        row["spindle_speed"] = None
        row["feed_unit"] = None
        row["effective_feed_mm_min"] = None
        row["feed_capped"] = None
    if isinstance(block, ArcMoveBlock):
        row["plane"] = block.plane
        row["direction"] = block.direction
    else:
        row["plane"] = None
        row["direction"] = None
    if isinstance(block, ToolChangeBlock):
        row["tool_id"] = block.tool_id
    else:
        row["tool_id"] = None
    if isinstance(block, (SpindleEventBlock, CoolantEventBlock)):
        row["event"] = block.event
    elif isinstance(block, OptionalStopBlock):
        row["event"] = "optional_stop"
    elif isinstance(block, SmoothingEventBlock):
        row["event"] = "smoothing"
    else:
        row["event"] = None
    if isinstance(block, ReferenceReturnBlock):
        row["reference_code"] = block.code
        row["reference_axes"] = ",".join(block.axes)
    else:
        row["reference_code"] = None
        row["reference_axes"] = None
    row["phase2_entry_velocity_mm_s"] = block.phase2_entry_velocity_mm_s
    row["phase2_exit_velocity_mm_s"] = block.phase2_exit_velocity_mm_s
    row["phase2_peak_velocity_mm_s"] = block.phase2_peak_velocity_mm_s
    row["phase2_v_cap_mm_s"] = block.phase2_v_cap_mm_s
    row["phase2_a_cap_mm_s2"] = block.phase2_a_cap_mm_s2
    row["phase2_j_cap_mm_s3"] = block.phase2_j_cap_mm_s3
    row["phase2_profile_type"] = block.phase2_profile_type
    row["phase2_slowdown_ratio"] = block.phase2_slowdown_ratio
    row["phase2_bottleneck_reason"] = block.phase2_bottleneck_reason
    row["phase2_segment_count"] = block.phase2_segment_count
    return row


@dataclass
class EstimateResult:
    total_time_sec: float = 0.0
    total_time_text: str = "00:00:00"
    rapid_time_sec: float = 0.0
    cutting_time_sec: float = 0.0
    arc_time_sec: float = 0.0
    dwell_time_sec: float = 0.0
    tool_change_time_sec: float = 0.0
    spindle_time_sec: float = 0.0
    coolant_time_sec: float = 0.0
    optional_stop_time_sec: float = 0.0
    reference_return_time_sec: float = 0.0
    auxiliary_time_sec: float = 0.0
    total_length_mm: float = 0.0
    tool_change_count: int = 0
    spindle_event_count: int = 0
    coolant_event_count: int = 0
    optional_stop_count: int = 0
    reference_return_count: int = 0
    smoothing_event_count: int = 0
    warning_list: list[str] = field(default_factory=list)
    block_table: list[dict[str, Any]] = field(default_factory=list)
    ir_program: list[BaseBlock] = field(default_factory=list)
    feed_summary: dict[str, Any] = field(default_factory=dict)
    feed_histogram: list[dict[str, Any]] = field(default_factory=list)
    top_slow_blocks: list[dict[str, Any]] = field(default_factory=list)
    feed_sanity_summary: dict[str, Any] = field(default_factory=dict)
    feed_sanity_issues: list[dict[str, Any]] = field(default_factory=list)
    normalized_feed_recommendation: str = ""
    comparison: dict[str, Any] = field(default_factory=dict)
    phase2_summary: dict[str, Any] = field(default_factory=dict)
    phase2_junctions: list[dict[str, Any]] = field(default_factory=list)
    phase2_bottlenecks: list[dict[str, Any]] = field(default_factory=list)
    phase2_dynamic_samples: list[dict[str, Any]] = field(default_factory=list)

    def summary_dict(self) -> dict[str, Any]:
        summary = {
            "total_time_sec": self.total_time_sec,
            "total_time_text": self.total_time_text,
            "rapid_time_sec": self.rapid_time_sec,
            "cutting_time_sec": self.cutting_time_sec,
            "arc_time_sec": self.arc_time_sec,
            "dwell_time_sec": self.dwell_time_sec,
            "tool_change_time_sec": self.tool_change_time_sec,
            "spindle_time_sec": self.spindle_time_sec,
            "coolant_time_sec": self.coolant_time_sec,
            "optional_stop_time_sec": self.optional_stop_time_sec,
            "reference_return_time_sec": self.reference_return_time_sec,
            "auxiliary_time_sec": self.auxiliary_time_sec,
            "total_length_mm": self.total_length_mm,
            "tool_change_count": self.tool_change_count,
            "spindle_event_count": self.spindle_event_count,
            "coolant_event_count": self.coolant_event_count,
            "optional_stop_count": self.optional_stop_count,
            "reference_return_count": self.reference_return_count,
            "smoothing_event_count": self.smoothing_event_count,
        }
        summary.update(self.feed_summary)
        summary.update(self.feed_sanity_summary)
        summary.update(self.phase2_summary)
        summary["warning_count"] = len(self.warning_list)
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary_dict(),
            "warnings": self.warning_list,
            "blocks": self.block_table,
            "feed_histogram": self.feed_histogram,
            "top_slow_blocks": self.top_slow_blocks,
            "feed_sanity_summary": self.feed_sanity_summary,
            "feed_sanity_issues": self.feed_sanity_issues,
            "normalized_feed_recommendation": self.normalized_feed_recommendation,
            "comparison": self.comparison,
            "phase2_junctions": self.phase2_junctions,
            "phase2_bottlenecks": self.phase2_bottlenecks,
            "charts": self.chart_data(),
        }

    def chart_data(self) -> dict[str, Any]:
        toolpath: list[dict[str, Any]] = []
        block_times: list[dict[str, Any]] = []
        for index, block in enumerate(self.ir_program):
            if block.start is not None and block.end is not None:
                toolpath.append(
                    {
                        "line_no": block.line_no,
                        "type": block.display_type,
                        "start": block.start_tuple(),
                        "end": block.end_tuple(),
                    }
                )
            block_times.append(
                {
                    "block_index": index,
                    "line_no": block.line_no,
                    "type": block.display_type,
                    "estimated_time_sec": block.estimated_time,
                }
            )
        return {
            "xy_toolpath": toolpath,
            "block_times": block_times,
            "phase2_dynamic_samples": self.phase2_dynamic_samples,
            "phase2_junctions": self.phase2_junctions,
        }


def summarize_result(ir_program: list[BaseBlock]) -> EstimateResult:
    result = EstimateResult(ir_program=ir_program)
    for block in ir_program:
        result.total_time_sec += block.estimated_time
        result.total_length_mm += block.length

        if block.display_type == "rapid":
            result.rapid_time_sec += block.estimated_time
        elif block.display_type == "linear":
            result.cutting_time_sec += block.estimated_time
        elif block.display_type == "arc":
            result.arc_time_sec += block.estimated_time
            result.cutting_time_sec += block.estimated_time
        elif block.display_type == "dwell":
            result.dwell_time_sec += block.estimated_time
        elif block.display_type == "tool_change":
            result.tool_change_time_sec += block.estimated_time
            result.tool_change_count += 1
        elif block.display_type == "spindle_event":
            result.spindle_time_sec += block.estimated_time
            result.spindle_event_count += 1
        elif block.display_type == "coolant_event":
            result.coolant_time_sec += block.estimated_time
            result.coolant_event_count += 1
        elif block.display_type == "optional_stop":
            result.optional_stop_time_sec += block.estimated_time
            result.optional_stop_count += 1
        elif block.display_type == "reference_return":
            result.reference_return_time_sec += block.estimated_time
            result.reference_return_count += 1
        elif block.display_type == "smoothing_event":
            result.smoothing_event_count += 1

        for warning in block.warnings:
            result.warning_list.append(f"Line {block.line_no}: {warning}")

    result.auxiliary_time_sec = (
        result.tool_change_time_sec
        + result.spindle_time_sec
        + result.coolant_time_sec
        + result.optional_stop_time_sec
        + result.reference_return_time_sec
        + result.dwell_time_sec
    )
    result.feed_summary = _feed_summary(ir_program)
    _attach_phase2_metadata(result, ir_program)
    result.total_time_text = format_seconds(result.total_time_sec)
    result.block_table = [block_to_row(block) for block in ir_program]
    result.feed_histogram = _feed_histogram(ir_program)
    result.top_slow_blocks = _top_slow_blocks(ir_program)
    return result


def _feed_summary(ir_program: list[BaseBlock]) -> dict[str, Any]:
    metadata = getattr(ir_program, "metadata", {})
    feed_metadata = metadata.get("feed") if isinstance(metadata, dict) else None
    if isinstance(feed_metadata, dict):
        return feed_metadata

    feed_blocks = [
        block
        for block in ir_program
        if isinstance(block, (LinearMoveBlock, ArcMoveBlock)) and block.feedrate is not None
    ]
    if not feed_blocks:
        return {}

    raw_feeds = [block.feedrate for block in feed_blocks if block.feedrate is not None]
    effective_feeds = [
        block.effective_feed_mm_min for block in feed_blocks if block.effective_feed_mm_min is not None
    ]
    feed_units = sorted({block.feed_unit for block in feed_blocks if block.feed_unit})
    return {
        "feed_unit_effective": ",".join(feed_units),
        "feed_move_count": len(feed_blocks),
        "feed_raw_count": len(raw_feeds),
        "feed_min_raw": min(raw_feeds) if raw_feeds else None,
        "feed_max_raw": max(raw_feeds) if raw_feeds else None,
        "feed_low_g94_count": sum(
            1
            for block in feed_blocks
            if block.feed_mode == "G94"
            and block.unit == "mm"
            and block.feedrate is not None
            and 0 < block.feedrate < 100
        ),
        "feed_capped_count": sum(1 for block in feed_blocks if block.feed_capped),
        "feed_min_effective_mm_min": min(effective_feeds) if effective_feeds else None,
        "feed_max_effective_mm_min": max(effective_feeds) if effective_feeds else None,
    }


def _attach_phase2_metadata(result: EstimateResult, ir_program: list[BaseBlock]) -> None:
    metadata = getattr(ir_program, "metadata", {})
    phase2 = metadata.get("phase2") if isinstance(metadata, dict) else None
    if not isinstance(phase2, dict) or not phase2.get("enabled"):
        return
    summary = phase2.get("summary")
    if isinstance(summary, dict):
        result.phase2_summary = summary
    junctions = phase2.get("junctions")
    if isinstance(junctions, list):
        result.phase2_junctions = junctions
    bottlenecks = phase2.get("bottlenecks")
    if isinstance(bottlenecks, list):
        result.phase2_bottlenecks = bottlenecks
    dynamic_samples = phase2.get("dynamic_samples")
    if isinstance(dynamic_samples, list):
        result.phase2_dynamic_samples = dynamic_samples


def _feed_histogram(ir_program: list[BaseBlock]) -> list[dict[str, Any]]:
    feed_blocks = _feed_blocks(ir_program)
    rows: list[dict[str, Any]] = []
    for label, low, high in FEED_HISTOGRAM_BANDS:
        blocks = [
            block
            for block in feed_blocks
            if block.effective_feed_mm_min is not None
            and _value_in_band(block.effective_feed_mm_min, low, high)
        ]
        effective_feeds = [
            block.effective_feed_mm_min for block in blocks if block.effective_feed_mm_min is not None
        ]
        raw_feeds = [block.feedrate for block in blocks if block.feedrate is not None]
        rows.append(
            {
                "effective_feed_band_mm_min": label,
                "block_count": len(blocks),
                "length_mm": sum(block.length for block in blocks),
                "time_sec": sum(block.estimated_time for block in blocks),
                "raw_feed_min": min(raw_feeds) if raw_feeds else None,
                "raw_feed_max": max(raw_feeds) if raw_feeds else None,
                "effective_feed_min": min(effective_feeds) if effective_feeds else None,
                "effective_feed_max": max(effective_feeds) if effective_feeds else None,
            }
        )
    return rows


def _top_slow_blocks(ir_program: list[BaseBlock], limit: int = 20) -> list[dict[str, Any]]:
    feed_blocks = [
        block
        for block in _feed_blocks(ir_program)
        if block.effective_feed_mm_min is not None and block.effective_feed_mm_min < 1000.0
    ]
    if not feed_blocks:
        feed_blocks = _feed_blocks(ir_program)
    sorted_blocks = sorted(feed_blocks, key=lambda block: block.estimated_time, reverse=True)
    return [_feed_block_diagnostic_row(block) for block in sorted_blocks[:limit]]


def compare_estimate_results(
    source: EstimateResult,
    candidate: EstimateResult,
    *,
    source_label: str = "source",
    candidate_label: str = "candidate",
    max_regression_ratio: float = 0.0,
    limit: int = 20,
) -> dict[str, Any]:
    from nc_time_twin.core.report.comparison import compare_estimate_results as _compare_estimate_results

    return _compare_estimate_results(
        source,
        candidate,
        source_label=source_label,
        candidate_label=candidate_label,
        max_regression_ratio=max_regression_ratio,
        limit=limit,
    )


def _feed_blocks(ir_program: list[BaseBlock]) -> list[LinearMoveBlock | ArcMoveBlock]:
    return [
        block
        for block in ir_program
        if isinstance(block, (LinearMoveBlock, ArcMoveBlock)) and block.feedrate is not None
    ]


def _feed_block_diagnostic_row(block: LinearMoveBlock | ArcMoveBlock) -> dict[str, Any]:
    return {
        "line_no": block.line_no,
        "type": block.display_type,
        "length_mm": block.length,
        "estimated_time_sec": block.estimated_time,
        "feedrate": block.feedrate,
        "feed_unit": block.feed_unit,
        "effective_feed_mm_min": block.effective_feed_mm_min,
        "feed_capped": block.feed_capped,
        "raw": block.raw,
    }


def _value_in_band(value: float, low: float | None, high: float | None) -> bool:
    if low is not None and value < low:
        return False
    if high is not None and value >= high:
        return False
    return True


def _geometry_matches(source_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> bool:
    for source_row, candidate_row in zip(source_rows, candidate_rows, strict=False):
        if source_row.get("type") != candidate_row.get("type"):
            return False
        if not _nearly_equal(source_row.get("length_mm"), candidate_row.get("length_mm")):
            return False
        if source_row.get("start") != candidate_row.get("start"):
            return False
        if source_row.get("end") != candidate_row.get("end"):
            return False
    return True


def _nearly_equal(left: object, right: object, tolerance: float = 1e-6) -> bool:
    if left is None and right is None:
        return True
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return left == right
    return abs(float(left) - float(right)) <= tolerance
