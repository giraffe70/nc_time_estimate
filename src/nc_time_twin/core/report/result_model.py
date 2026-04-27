from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nc_time_twin.core.ir.blocks import (
    ArcMoveBlock,
    BaseBlock,
    CoolantEventBlock,
    LinearMoveBlock,
    SpindleEventBlock,
    ToolChangeBlock,
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
    else:
        row["feedrate"] = None
        row["feed_mode"] = None
        row["spindle_speed"] = None
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
    else:
        row["event"] = None
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
    auxiliary_time_sec: float = 0.0
    total_length_mm: float = 0.0
    tool_change_count: int = 0
    spindle_event_count: int = 0
    coolant_event_count: int = 0
    warning_list: list[str] = field(default_factory=list)
    block_table: list[dict[str, Any]] = field(default_factory=list)
    ir_program: list[BaseBlock] = field(default_factory=list)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "total_time_sec": self.total_time_sec,
            "total_time_text": self.total_time_text,
            "rapid_time_sec": self.rapid_time_sec,
            "cutting_time_sec": self.cutting_time_sec,
            "arc_time_sec": self.arc_time_sec,
            "dwell_time_sec": self.dwell_time_sec,
            "tool_change_time_sec": self.tool_change_time_sec,
            "spindle_time_sec": self.spindle_time_sec,
            "coolant_time_sec": self.coolant_time_sec,
            "auxiliary_time_sec": self.auxiliary_time_sec,
            "total_length_mm": self.total_length_mm,
            "tool_change_count": self.tool_change_count,
            "spindle_event_count": self.spindle_event_count,
            "coolant_event_count": self.coolant_event_count,
            "warning_count": len(self.warning_list),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary_dict(),
            "warnings": self.warning_list,
            "blocks": self.block_table,
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

        for warning in block.warnings:
            result.warning_list.append(f"Line {block.line_no}: {warning}")

    result.auxiliary_time_sec = (
        result.tool_change_time_sec
        + result.spindle_time_sec
        + result.coolant_time_sec
        + result.dwell_time_sec
    )
    result.total_time_text = format_seconds(result.total_time_sec)
    result.block_table = [block_to_row(block) for block in ir_program]
    return result
