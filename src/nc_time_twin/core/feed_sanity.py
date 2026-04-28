from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nc_time_twin.core.ir.blocks import ArcMoveBlock, BaseBlock, LinearMoveBlock
from nc_time_twin.core.machine.profile import MachineProfile

LOW_EFFECTIVE_FEED_MM_MIN = 1000.0
VERY_LOW_EFFECTIVE_FEED_MM_MIN = 500.0
LOW_RAW_G94_FEED = 100.0
MID_RAW_G94_FEED = 1000.0
EXTREME_RAW_MULTIPLIER = 5.0


@dataclass(frozen=True)
class FeedSanityDiagnostics:
    summary: dict[str, Any]
    issues: list[dict[str, Any]]
    recommendation: str


def analyze_feed_sanity(
    ir_program: list[BaseBlock],
    machine_profile: MachineProfile,
    *,
    strict_feed: bool = False,
) -> FeedSanityDiagnostics:
    feed_blocks = [
        block
        for block in ir_program
        if isinstance(block, (LinearMoveBlock, ArcMoveBlock))
        and block.feed_mode == "G94"
        and block.unit == "mm"
        and block.feedrate is not None
    ]
    max_cut_feed = machine_profile.max_cut_feed_mm_min
    extreme_raw_threshold = max_cut_feed * EXTREME_RAW_MULTIPLIER

    low_raw_blocks = [block for block in feed_blocks if 0 < (block.feedrate or 0.0) < LOW_RAW_G94_FEED]
    mid_raw_blocks = [
        block for block in feed_blocks if LOW_RAW_G94_FEED <= (block.feedrate or 0.0) < MID_RAW_G94_FEED
    ]
    extreme_raw_blocks = [block for block in feed_blocks if (block.feedrate or 0.0) > extreme_raw_threshold]
    low_effective_blocks = [
        block
        for block in feed_blocks
        if block.effective_feed_mm_min is not None
        and 0 < block.effective_feed_mm_min < LOW_EFFECTIVE_FEED_MM_MIN
    ]

    issues: list[dict[str, Any]] = []
    if low_raw_blocks and mid_raw_blocks and extreme_raw_blocks:
        issues.append(
            _aggregate_issue(
                severity="critical",
                code="mixed_feed_scale",
                message=(
                    "G21/G94 feed values look scale-mixed: low raw F, 100-999 raw F, "
                    "and extreme raw F values appear in the same program."
                ),
                blocks=[*low_raw_blocks[:5], *mid_raw_blocks[:5], *extreme_raw_blocks[:5]],
                recommendation=(
                    "Normalize the optimizer output to explicit mm/min before estimation; "
                    "do not rely on auto feed-unit inference for this file."
                ),
            )
        )
    elif low_raw_blocks and mid_raw_blocks:
        issues.append(
            _aggregate_issue(
                severity="warning",
                code="mixed_low_feed_scale",
                message="G21/G94 feed values include both F<100 and F100-F999 values.",
                blocks=[*low_raw_blocks[:5], *mid_raw_blocks[:5]],
                recommendation="Verify whether the source NC uses m/min or mm/min, then normalize feed values.",
            )
        )

    for block in low_effective_blocks:
        effective_feed = block.effective_feed_mm_min or 0.0
        severity = "critical" if strict_feed or effective_feed < VERY_LOW_EFFECTIVE_FEED_MM_MIN else "warning"
        issues.append(
            _block_issue(
                block,
                severity=severity,
                code="low_effective_feed",
                message=(
                    f"G21/G94 effective feed {effective_feed:g} mm/min is below "
                    f"{LOW_EFFECTIVE_FEED_MM_MIN:g} mm/min."
                ),
                recommendation=(
                    "Confirm this is an intentional local slowdown; otherwise normalize feed scale "
                    "or reject the optimized NC as a time regression."
                ),
            )
        )

    for block in extreme_raw_blocks:
        issues.append(
            _block_issue(
                block,
                severity="critical" if strict_feed else "warning",
                code="extreme_raw_feed",
                message=(
                    f"G21/G94 raw feed F{block.feedrate:g} is above "
                    f"{extreme_raw_threshold:g} ({EXTREME_RAW_MULTIPLIER:g}x max_cut_feed)."
                ),
                recommendation="Check optimizer/postprocessor scaling; cap or normalize before machining.",
            )
        )

    critical_count = sum(1 for issue in issues if issue["severity"] == "critical")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    summary = {
        "feed_sanity_issue_count": len(issues),
        "feed_sanity_critical_count": critical_count,
        "feed_sanity_warning_count": warning_count,
        "feed_sanity_low_effective_count": len(low_effective_blocks),
        "feed_sanity_low_raw_g94_count": len(low_raw_blocks),
        "feed_sanity_mid_raw_g94_count": len(mid_raw_blocks),
        "feed_sanity_extreme_raw_count": len(extreme_raw_blocks),
        "feed_sanity_extreme_raw_threshold": extreme_raw_threshold,
        "feed_sanity_strict_feed": strict_feed,
    }
    recommendation = _recommendation(summary)
    return FeedSanityDiagnostics(summary=summary, issues=issues, recommendation=recommendation)


def _aggregate_issue(
    *,
    severity: str,
    code: str,
    message: str,
    blocks: list[LinearMoveBlock | ArcMoveBlock],
    recommendation: str,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "line_no": None,
        "feedrate": None,
        "effective_feed_mm_min": None,
        "estimated_time_sec": None,
        "raw": None,
        "message": message,
        "recommendation": recommendation,
        "sample_lines": ", ".join(str(block.line_no) for block in blocks),
    }


def _block_issue(
    block: LinearMoveBlock | ArcMoveBlock,
    *,
    severity: str,
    code: str,
    message: str,
    recommendation: str,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "line_no": block.line_no,
        "feedrate": block.feedrate,
        "effective_feed_mm_min": block.effective_feed_mm_min,
        "estimated_time_sec": block.estimated_time,
        "raw": block.raw,
        "message": message,
        "recommendation": recommendation,
        "sample_lines": None,
    }


def _recommendation(summary: dict[str, Any]) -> str:
    if summary["feed_sanity_extreme_raw_count"] and summary["feed_sanity_low_effective_count"]:
        return (
            "Feed scale is likely inconsistent. Use normalize-feed with an explicit input-feed-unit, "
            "then compare against the source NC with regression checks enabled."
        )
    if summary["feed_sanity_low_effective_count"]:
        return (
            "Low feed blocks dominate the risk. Verify whether each slowdown is intentional; "
            "otherwise reject or regenerate the optimized NC."
        )
    if summary["feed_sanity_extreme_raw_count"]:
        return "Extreme raw F values are being capped; inspect optimizer/postprocessor output scaling."
    return "No feed normalization action is required by the current sanity rules."
