from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CleanLine:
    line_no: int
    raw: str
    clean: str


PAREN_COMMENT_RE = re.compile(r"\([^)]*\)")
SEQUENCE_RE = re.compile(r"^N\d+\s*", re.IGNORECASE)
PROGRAM_RE = re.compile(r"^O\d+$", re.IGNORECASE)


def preprocess_nc_lines(raw_lines: list[str]) -> list[CleanLine]:
    clean_lines: list[CleanLine] = []
    for index, original in enumerate(raw_lines, start=1):
        raw = original.rstrip("\r\n")
        line = raw.strip()
        if not line or line == "%":
            continue
        line = PAREN_COMMENT_RE.sub("", line)
        line = line.split(";", 1)[0]
        line = SEQUENCE_RE.sub("", line.strip())
        line = line.upper()
        line = re.sub(r"\s+", " ", line).strip()
        if not line or line == "%" or PROGRAM_RE.match(line):
            continue
        clean_lines.append(CleanLine(line_no=index, raw=raw, clean=line))
    return clean_lines
