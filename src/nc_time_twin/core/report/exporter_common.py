from __future__ import annotations

from typing import Any


def flatten_row(row: dict[str, Any]) -> dict[str, Any]:
    flattened = dict(row)
    for field in ("start", "end"):
        value = flattened.get(field)
        if isinstance(value, tuple):
            flattened[field] = ", ".join(f"{part:.6g}" for part in value)
    return flattened


def flattened_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [flatten_row(row) for row in rows]
