from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


NUMBER_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
WORD_RE = re.compile(rf"([A-Z])({NUMBER_RE})")


@dataclass
class TokenizedLine:
    raw: str
    words: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def g_codes(self) -> list[int]:
        return list(self.words.get("G", []))

    def m_codes(self) -> list[int]:
        return list(self.words.get("M", []))

    def contains_g(self, code: int) -> bool:
        return code in self.g_codes()

    def contains_m(self, code: int) -> bool:
        return code in self.m_codes()

    def get_float(self, letter: str, default: float | None = None) -> float | None:
        value = self.words.get(letter.upper(), default)
        if isinstance(value, list):
            return default
        return value

    def has_any_axis(self) -> bool:
        return any(letter in self.words for letter in ("X", "Y", "Z"))


def tokenize(line: str) -> TokenizedLine:
    compact = re.sub(r"\s+", "", line.upper())
    tokens = TokenizedLine(raw=line)
    spans: list[tuple[int, int]] = []

    for match in WORD_RE.finditer(compact):
        letter = match.group(1)
        value = float(match.group(2))
        spans.append(match.span())
        if letter in {"G", "M"}:
            tokens.words.setdefault(letter, []).append(int(value))
        else:
            tokens.words[letter] = value

    unparsed = _find_unparsed(compact, spans)
    if unparsed:
        tokens.warnings.append(f"Unparsed content: {unparsed}")
    return tokens


def _find_unparsed(text: str, spans: list[tuple[int, int]]) -> str:
    if not text:
        return ""
    covered = [False] * len(text)
    for start, end in spans:
        for index in range(start, end):
            covered[index] = True
    parts: list[str] = []
    current = []
    for char, is_covered in zip(text, covered, strict=True):
        if not is_covered:
            current.append(char)
        elif current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    return " ".join(part for part in parts if part.strip())
