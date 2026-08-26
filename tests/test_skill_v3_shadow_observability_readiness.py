from __future__ import annotations

import json
from pathlib import Path

from tools.diagnostics.recheck_skill_v3_shadow_observability import (
    materialize,
    verify_manifest,
)


def load(root: Path, name: str) -> dict:
    return json.loads((root / name).read_text(encoding="utf-8"))


def test_readiness_recheck_only_closes_observability_and_materializes_disabled_plan(
    tmp_path: Path,
) -> None:
    result = materialize(tmp_path, {
        "focused_tests": "TEST",
        "adjacent_tests": "TEST",
        "full_suite": "TEST",
        "strict_l3": "PASS",
    })
    matrix = load(tmp_path, "pilot-readiness-matrix-recheck-v1.json")
    assert result["readiness_delta"] == ["SHADOW_FAIL_OPEN"]
    assert matrix["all_readiness_dimensions"] == "PASS"
    assert matrix["new_failure_dimension_count"] == 0
    assert all(value == "PASS" for value in matrix["matrix"].values())

    plan = load(tmp_path, "real-pilot-plan-v1.json")
    assert plan["materialized"] is True
    assert plan["pilot_plan_disabled"] is True
    assert plan["execution_authorized"] is False
    assert plan["signed_approval_present"] is False
    assert plan["real_execution_nonce_created"] is False
    assert plan["real_execution_nonce_reserved"] is False
    assert plan["real_execution_enabled"] is False
    assert plan["samples_per_a"] == plan["samples_per_b"] == 3
    assert plan["maximum_total_real_requests"] == 6

    packet = load(tmp_path, "pilot-packet-template-v1.json")
    assert packet["materialized"] is True
    assert packet["execution_authorized"] is False
    assert packet["signed_approval_present"] is False
    assert packet["nonce_reserved"] is False
    assert verify_manifest(tmp_path)["status"] == "EXACT"


def test_materialized_evidence_is_privacy_safe_and_has_required_coverage(
    tmp_path: Path,
) -> None:
    materialize(tmp_path, {
        "focused_tests": "TEST",
        "adjacent_tests": "TEST",
        "full_suite": "TEST",
        "strict_l3": "PASS",
    })
    privacy = load(tmp_path, "privacy-scan-v1.json")
    assert privacy["status"] == "PASS"
    assert privacy["privacy_match_count"] == 0
    required = {
        "README.md",
        "prior-readiness-binding-v1.json",
        "silent-swallow-source-audit-v1.json",
        "observability-contract-reuse-v1.json",
        "failure-event-schema-v1.json",
        "failure-counter-contract-v1.json",
        "failure-receipt-mode-v1.json",
        "full-suite-classification-v1.json",
        "observer-fail-open-contract-v1.json",
        "negative-failure-injection-matrix-v1.json",
        "production-input-identity-v1.json",
        "shadow-success-output-parity-v1.json",
        "shadow-fail-open-recheck-v1.json",
        "pilot-readiness-matrix-recheck-v1.json",
        "multi-sample-policy-binding-v1.json",
        "real-pilot-plan-v1.json",
        "pilot-packet-template-v1.json",
        "privacy-scan-v1.json",
        "test-receipt-v1.json",
        "strict-l3-receipt-v1.json",
        "final-report-v1.md",
        "sha256-manifest-v1.json",
    }
    assert {path.name for path in tmp_path.iterdir()} == required
