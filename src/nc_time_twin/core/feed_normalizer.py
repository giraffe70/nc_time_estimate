from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Callable

from nc_time_twin.core.machine.profile import load_machine_profile
from nc_time_twin.core.parser.tokenizer import NUMBER_RE

WORD_RE = re.compile(rf"([A-Za-z])({NUMBER_RE})")
NUMBER_AT_RE = re.compile(NUMBER_RE)


@dataclass
class FeedNormalizationSummary:
    input_path: str
    output_path: str
    input_feed_unit: str
    output_feed_unit: str = "mm_per_min"
    rewritten_feed_count: int = 0
    capped_feed_count: int = 0
    skipped_feed_count: int = 0
    max_cut_feed_mm_min: float = 0.0
    changed_lines: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "input_path": self.input_path,
            "output_path": self.output_path,
            "input_feed_unit": self.input_feed_unit,
            "output_feed_unit": self.output_feed_unit,
            "rewritten_feed_count": self.rewritten_feed_count,
            "capped_feed_count": self.capped_feed_count,
            "skipped_feed_count": self.skipped_feed_count,
            "max_cut_feed_mm_min": self.max_cut_feed_mm_min,
            "changed_lines": self.changed_lines,
        }


def normalize_feed_file(
    nc_file_path: str | Path,
    machine_profile_path: str | Path,
    output_path: str | Path,
    *,
    input_feed_unit: str,
) -> FeedNormalizationSummary:
    if input_feed_unit not in {"mm_per_min", "m_per_min"}:
        raise ValueError("input_feed_unit must be 'mm_per_min' or 'm_per_min'")

    profile = load_machine_profile(machine_profile_path)
    input_path = Path(nc_file_path)
    target_path = Path(output_path)
    if input_path.resolve() == target_path.resolve():
        raise ValueError("normalize-feed requires a distinct --out path; it will not overwrite the input NC")

    unit = profile.units
    feed_mode = "G94"
    summary = FeedNormalizationSummary(
        input_path=str(input_path),
        output_path=str(target_path),
        input_feed_unit=input_feed_unit,
        max_cut_feed_mm_min=profile.max_cut_feed_mm_min,
    )
    converted_lines: list[str] = []
    for line_no, raw_line in enumerate(input_path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        modal_words = _modal_words(raw_line)
        unit, feed_mode = _update_modal(unit, feed_mode, modal_words)
        if unit == "mm" and feed_mode == "G94":
            converted, changed, rewritten, capped = _rewrite_feed_words(
                raw_line,
                lambda feed: _convert_feed(feed, input_feed_unit, profile.max_cut_feed_mm_min),
            )
            converted_lines.append(converted)
            summary.rewritten_feed_count += rewritten
            summary.capped_feed_count += capped
            if changed:
                summary.changed_lines.append(line_no)
        else:
            converted_lines.append(raw_line)
            if _line_has_feed(raw_line):
                summary.skipped_feed_count += 1

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("\n".join(converted_lines) + "\n", encoding="utf-8")
    return summary


def _update_modal(unit: str, feed_mode: str, words: list[tuple[str, float]]) -> tuple[str, str]:
    for letter, value in words:
        if letter != "G":
            continue
        code = int(value)
        if code == 20:
            unit = "inch"
        elif code == 21:
            unit = "mm"
        elif code == 93:
            feed_mode = "G93"
        elif code == 94:
            feed_mode = "G94"
        elif code == 95:
            feed_mode = "G95"
    return unit, feed_mode


def _modal_words(line: str) -> list[tuple[str, float]]:
    code = _strip_comments(line)
    return [(match.group(1).upper(), float(match.group(2))) for match in WORD_RE.finditer(code)]


def _strip_comments(line: str) -> str:
    result: list[str] = []
    in_paren = False
    for char in line:
        if char == ";" and not in_paren:
            break
        if char == "(" and not in_paren:
            in_paren = True
            continue
        if char == ")" and in_paren:
            in_paren = False
            continue
        if not in_paren:
            result.append(char)
    return "".join(result)


def _rewrite_feed_words(
    line: str,
    convert: Callable[[float], tuple[float, bool]],
) -> tuple[str, bool, int, int]:
    parts: list[str] = []
    in_paren = False
    changed = False
    rewritten = 0
    capped = 0
    index = 0
    while index < len(line):
        char = line[index]
        if char == ";" and not in_paren:
            parts.append(line[index:])
            break
        if char == "(" and not in_paren:
            in_paren = True
            parts.append(char)
            index += 1
            continue
        if char == ")" and in_paren:
            in_paren = False
            parts.append(char)
            index += 1
            continue
        if not in_paren and char.upper() == "F":
            match = NUMBER_AT_RE.match(line, index + 1)
            if match:
                value = float(match.group(0))
                converted, was_capped = convert(value)
                parts.append(char)
                parts.append(_format_feed(converted))
                index = match.end()
                changed = True
                rewritten += 1
                capped += 1 if was_capped else 0
                continue
        parts.append(char)
        index += 1
    return "".join(parts), changed, rewritten, capped


def _convert_feed(feed: float, input_feed_unit: str, max_cut_feed_mm_min: float) -> tuple[float, bool]:
    converted = feed * 1000.0 if input_feed_unit == "m_per_min" else feed
    capped = converted > max_cut_feed_mm_min
    return min(converted, max_cut_feed_mm_min), capped


def _format_feed(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _line_has_feed(line: str) -> bool:
    return any(letter == "F" for letter, _ in _modal_words(line))
