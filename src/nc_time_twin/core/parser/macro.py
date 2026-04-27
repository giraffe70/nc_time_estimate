from __future__ import annotations

import re


MACRO_ASSIGN_RE = re.compile(r"^#(\d+)\s*=\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))$")
MACRO_REF_RE = re.compile(r"#(\d+)")
COMPLEX_MACRO_RE = re.compile(r"\b(IF|WHILE|GOTO|END|DO)\b", re.IGNORECASE)


def is_macro_assignment(line: str) -> bool:
    return MACRO_ASSIGN_RE.match(line.strip()) is not None


def update_macro_table(line: str, macro_table: dict[str, float]) -> None:
    match = MACRO_ASSIGN_RE.match(line.strip())
    if not match:
        return
    macro_table[match.group(1)] = float(match.group(2))


def expand_macro_variables(line: str, macro_table: dict[str, float]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if COMPLEX_MACRO_RE.search(line):
        warnings.append("Complex macro control flow is not supported in Phase 1")

    def replace(match: re.Match[str]) -> str:
        macro_id = match.group(1)
        if macro_id not in macro_table:
            warnings.append(f"Unknown macro variable: #{macro_id}")
            return "0"
        value = macro_table[macro_id]
        return str(int(value)) if value.is_integer() else str(value)

    return MACRO_REF_RE.sub(replace, line), warnings
