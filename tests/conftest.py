from __future__ import annotations

from pathlib import Path
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles" / "default_3axis.yaml"


@pytest.fixture
def profile_path() -> Path:
    return PROFILE


@pytest.fixture
def write_nc():
    created: list[Path] = []

    def _write(content: str) -> Path:
        path = ROOT / f".test_program_{uuid.uuid4().hex}.nc"
        path.write_text(content.strip() + "\n", encoding="utf-8")
        created.append(path)
        return path

    yield _write
    for path in created:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


@pytest.fixture
def artifact_path():
    created: list[Path] = []

    def _path(suffix: str) -> Path:
        path = ROOT / f".test_artifact_{uuid.uuid4().hex}.{suffix.lstrip('.')}"
        created.append(path)
        return path

    yield _path
    for path in created:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
