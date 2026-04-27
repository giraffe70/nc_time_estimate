from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nc_time_twin.core.report.result_model import EstimateResult


def export_json(result: EstimateResult, path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, ensure_ascii=False, indent=2, default=_json_default)


def _json_default(value: Any) -> Any:
    if hasattr(value, "as_tuple"):
        return value.as_tuple()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
