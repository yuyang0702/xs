from __future__ import annotations

import json
from pathlib import Path

from tools.diagnostics.close_skill_v3_reference_distill_binding import (
    materialize, verify_manifest,
)


def load(root: Path, name: str) -> dict:
    return json.loads((root / name).read_text(encoding="utf-8"))


def validation() -> dict:
    return {
        "focused_tests": "TEST", "related_tests": "TEST",
        "full_suite": "TEST", "strict_l3": "PASS",
        "constraint_traceability": [],
    }


def test_closure_materializes_exact_six_sample_non_skill_lock(tmp_path: Path) -> None:
    result = materialize(tmp_path, validation())
    identity = load(tmp_path, "a-b-project-guidance-byte-identity-v1.json")
    matrix = load(tmp_path, "six-sample-model-input-component-matrix-v1.json")
    loss = load(tmp_path, "no-silent-advisory-loss-v1.json")

    assert result["a_project_guidance_sha256"] == result["b_project_guidance_sha256"]
    assert identity["non_skill_model_visible_bytes_identical_across_arms"] is True
    assert matrix["all_non_skill_components_equal_across_6"] is True
    assert matrix["primary_changed_variable"] == "SKILL_CONTEXT"
    assert len(matrix["samples"]) == 6
    assert all(not row["advisory_truncation_occurred"] for row in loss["samples"])
    assert all(not row["advisory_shedding_occurred"] for row in loss["samples"])
    partition = load(tmp_path, "pilot-advisory-partition-decision-v1.json")
    lock = load(
        Path("docs/superpowers/reports/skill-v3-selective-compiler-shadow-review-pilot-readiness-v1"),
        "real-pilot-experiment-lock-v1.json",
    )
    assert partition["arm_a"]["skill_guidance_sha256"] == lock[
        "skill_context_arms"
    ]["A"]["context_sha256"]
    assert partition["arm_b"]["skill_guidance_sha256"] == lock[
        "skill_context_arms"
    ]["B"]["context_sha256"]


def test_closure_is_private_offline_and_manifest_exact(tmp_path: Path) -> None:
    materialize(tmp_path, validation())
    privacy = load(tmp_path, "privacy-scan-v1.json")
    receipt = load(tmp_path, "test-receipt-v1.json")
    required = {
        "README.md", "runtime-truth-source-lock-revalidation-v1.json",
        "planning-reference-runtime-truth-v1.json",
        "active-reference-derived-provenance-v1.json",
        "rendered-advisory-provenance-contract-v1.json",
        "production-model-input-identity-v1.json",
        "pilot-non-skill-guidance-snapshot-v1.json",
        "a-b-project-guidance-byte-identity-v1.json",
        "pilot-advisory-partition-decision-v1.json",
        "style-system-separation-v1.json",
        "six-sample-model-input-component-matrix-v1.json",
        "no-silent-advisory-loss-v1.json",
        "deferred-full-short-style-reference-gaps-v1.json",
        "negative-binding-matrix-v1.json", "forward-risk-report-v2.json",
        "test-receipt-v1.json", "strict-l3-receipt-v1.json",
        "privacy-scan-v1.json", "final-report-v1.md", "sha256-manifest-v1.json",
    }
    assert {path.name for path in tmp_path.iterdir()} == required
    assert privacy["status"] == "PASS"
    assert privacy["privacy_match_count"] == 0
    assert all(receipt[key] == 0 for key in (
        "credential_lookup_count", "real_provider_request_attempts",
        "http_post_attempts", "network_calls", "model_calls", "paid_calls",
    ))
    assert verify_manifest(tmp_path)["status"] == "EXACT"
