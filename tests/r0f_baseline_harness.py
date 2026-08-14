"""Test-only baseline helpers for R0F runtime fingerprint instrumentation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROTECTED_SOURCE_PATHS = (
    "src/novel_flywheel/completion_supervisor.py",
    "src/novel_flywheel/contract_runtime.py",
    "src/novel_flywheel/generated_artifacts.py",
    "src/novel_flywheel/long_workflow.py",
    "src/novel_flywheel/models.py",
    "src/novel_flywheel/prompts.py",
    "src/novel_flywheel/providers/registry.py",
    "src/novel_flywheel/workflows.py",
)

DIAGNOSTIC_EVENT_TYPES = frozenset({
    "runtime_fingerprint_binding_v1",
    "runtime_fingerprint_unavailable_v1",
})


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_source_manifest(repository: Path) -> list[dict[str, Any]]:
    return [
        {"path": relative, "sha256": sha256_file(repository / relative)}
        for relative in PROTECTED_SOURCE_PATHS
    ]


def business_run_projection(run: dict[str, Any], events: list[dict[str, Any]]) -> dict:
    """Remove observation-only fields while preserving existing run semantics."""

    return {
        "status": run["status"],
        "current_stage": run["current_stage"],
        "error": run["error"],
        "events": [
            {
                "severity": event["severity"],
                "event_type": event["event_type"],
                "stage": event["stage"],
                "message": event["message"],
                "metadata": event["metadata"],
            }
            for event in events
            if event["event_type"] not in DIAGNOSTIC_EVENT_TYPES
        ],
    }


def load_baseline(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
