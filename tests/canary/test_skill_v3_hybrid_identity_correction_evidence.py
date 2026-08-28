from __future__ import annotations

import json
from pathlib import Path

from tools.diagnostics.materialize_skill_v3_hybrid_identity_correction_evidence import (
    NEXT_GATE,
    REQUIRED_FILES,
    build_artifacts,
    validate_artifacts,
)


ROOT = Path(__file__).resolve().parents[2]


def _artifacts() -> dict[str, bytes]:
    return build_artifacts(
        ROOT,
        strict_l3="PASS",
        clean_room_core_tree_sha256="1" * 64,
    )


def test_identity_correction_evidence_is_complete_deterministic_and_exact() -> None:
    first = _artifacts()
    second = _artifacts()
    assert first == second
    assert set(first) == set(REQUIRED_FILES)
    validate_artifacts(first)


def test_acceptance_and_external_boundaries_are_explicit() -> None:
    artifacts = _artifacts()
    report = artifacts["final-report-v1.md"].decode("utf-8")
    replay = json.loads(artifacts["planning-real-seam-4-skill-replay-v1.json"])
    negative = json.loads(artifacts["identity-negative-injections-v1.json"])
    privacy = json.loads(artifacts["privacy-scan-v1.json"])
    assert replay["REAL_PLANNING_SKILL_SEAM_PASS"] == "4/4"
    assert negative["IDENTITY_NEGATIVE_INJECTIONS_PASS"] == "YES"
    assert privacy["Privacy"] == "PASS"
    assert all(value == 0 or value == "NO" for value in privacy["external_actions"].values())
    assert "PILOT_EXECUTION_AUTHORIZED=NO" in report
    assert f"EXACT_NEXT_GATE={NEXT_GATE}" in report


def test_manifest_binds_every_non_manifest_file() -> None:
    artifacts = _artifacts()
    manifest = json.loads(artifacts["sha256-manifest-v1.json"])
    assert {row["path"] for row in manifest["entries"]} == (
        set(REQUIRED_FILES) - {"sha256-manifest-v1.json"}
    )
