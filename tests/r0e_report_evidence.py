"""R0E report integrity, fingerprint availability, and live parity helpers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from novel_flywheel.db import Database


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    ).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def runtime_fingerprint_availability(root: Path) -> dict[str, Any]:
    source_root = root / "src" / "novel_flywheel"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(source_root.rglob("*.py"))
    )
    db = Database(root / "data" / "app.db")
    projects = db.list_projects()
    project_id = str(projects[0]["id"]) if projects else None
    return {
        "schema": "R0ERuntimeFingerprintAvailabilityV1",
        "fingerprint_instrumentation": "IMPLEMENTED_R0F",
        "real_provider_canary": "BLOCKED_BY_APPROVAL_AND_EXACT_BINDING",
        "paid_llm_calls": 0,
        "fields": {
            "control_plane_git_commit": "available_outside_run",
            "run_bound_git_commit": "available_via_stored_provenance_child",
            "build_id": "RuntimeBuildFingerprintV1",
            "contract_runtime_version": "available_via_contract_registry_child",
            "contract_registration_versions": "stored_and_run_bound",
            "recovery_policy_version": "stored_and_run_bound",
            "incident_catalog_version": "stored_and_run_bound",
            "feature_flags": "stored_per_execution_config_binding",
        },
        "source_characterization": {
            "RuntimeBuildFingerprintV1_present": (
                "RuntimeBuildFingerprintV1" in source
            ),
            "run_runtime_fingerprint_field_present": any(
                token in source for token in (
                    '"runtime_build_fingerprint"',
                    '"runtime_execution_fingerprint"',
                    '"source_fingerprint"',
                    '"runtime_commit"',
                )
            ),
        },
        "phase1b_flags": {
            "environment_raw": os.getenv("NOVEL_SHORT_CANONICAL_V2"),
            "environment_effective": os.getenv(
                "NOVEL_SHORT_CANONICAL_V2", "0",
            ) in {"1", "true", "TRUE", "yes", "on"},
            "project_id_hash": (
                hashlib.sha256(project_id.encode("utf-8")).hexdigest()
                if project_id else None
            ),
            "project_effective": (
                bool(db.feature_flag(
                    "short_canonical_v2", project_id=project_id, default=False,
                )["enabled"]) if project_id else False
            ),
        },
    }


def zero_failure_upper_bound(sample_size: int, alpha: float = 0.05) -> float:
    if sample_size < 1:
        raise ValueError("sample size must be positive")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    return 1 - alpha ** (1 / sample_size)


def exposure_sample_plan() -> dict[str, Any]:
    average_calls = 379 / 26
    targets = (59, 99, 299)
    return {
        "schema": "R0EControlledExposureSamplePlanV1",
        "confidence": 0.95,
        "method": "one_sided_zero_failure_exact_binomial",
        "formula": "1 - 0.05 ** (1 / N)",
        "r0_deterministic_calls": 379,
        "r0_recovered_workflows": 26,
        "estimated_calls_per_run": average_calls,
        "rows": [{
            "runs": count,
            "zero_failure_upper_bound": zero_failure_upper_bound(count),
            "estimated_model_calls": math.ceil(count * average_calls),
            "hard_cap_calls_at_20_per_run": count * 20,
        } for count in targets],
        "claim_boundary": (
            "canary-mixture terminal-rate bound unless workload weights are "
            "proved representative of production"
        ),
    }


def _manifest(root: Path, paths: Iterable[Path]) -> dict[str, Any]:
    rows = [{
        "path": path.relative_to(root).as_posix(),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    } for path in sorted(set(paths)) if path.is_file()]
    return {"count": len(rows), "sha256": canonical_sha256(rows), "rows": rows}


def live_parity_snapshot(root: Path) -> dict[str, Any]:
    database_path = root / "data" / "app.db"
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    project = dict(connection.execute(
        "SELECT * FROM projects ORDER BY created_at DESC LIMIT 1"
    ).fetchone())
    project_root = Path(str(project["path"]))
    if not project_root.is_absolute():
        project_root = database_path.parent / "projects" / project_root
    categories = {
        "formal": [
            project_root / "manuscript" / "story.md",
            project_root / "story.md",
            project_root / "chapters" / "chapter-01.md",
        ],
        "canon": [project_root / "memory" / "canon.json"],
        "candidate": list(project_root.glob("runs/*/outputs/best-candidate.md")),
        "checkpoint": list(project_root.glob("runs/**/*checkpoint*.json")),
        "saga": [
            path for path in project_root.rglob("*")
            if path.is_file() and "saga" in path.name.casefold()
        ],
    }
    table_counts = {}
    for table in (
        "story_states", "story_candidates", "workflow_node_checkpoints",
    ):
        table_counts[table] = int(connection.execute(
            f"SELECT COUNT(*) FROM {table}"  # closed internal table list
        ).fetchone()[0])
    connection.close()
    return {
        "schema": "R0ELiveParitySnapshotV1",
        "database_sha256": file_sha256(database_path),
        "project_id_hash": hashlib.sha256(
            str(project["id"]).encode("utf-8")
        ).hexdigest(),
        "artifact_manifests": {
            name: _manifest(project_root, paths)
            for name, paths in categories.items()
        },
        "table_counts": table_counts,
    }
