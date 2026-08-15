"""Scoped C0A environment; raw values never enter evidence."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path


@contextmanager
def c0a_environment(data_root: Path, *, feature_flags: dict[str, bool] | None = None):
    values = {
        "NOVEL_FLYWHEEL_DATA_DIR": str(data_root),
        "CREWAI_STORAGE_DIR": str(data_root / "crewai" / "storage"),
        "OTEL_SDK_DISABLED": "true",
        "NOVEL_SHORT_CANONICAL_V2": "0",
        "NOVEL_CANONICAL_SHADOW_V1": "0",
        "NOVEL_RELIABILITY_TRACE": "1",
    }
    for name, enabled in (feature_flags or {}).items():
        if name.startswith("NOVEL_"):
            values[name] = "1" if enabled else "0"
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, old in previous.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
