from __future__ import annotations

import json
from pathlib import Path

from tools.diagnostics import skill_v2_demand_aware_creative_core as evidence


REPO = Path(__file__).resolve().parents[1]
VALIDATION = {
    "focused": "TEST",
    "adjacent": "TEST",
    "historical_matrix": "TEST",
    "known_fixed_head_failure_count": 8,
    "historical_classifications": [
        {
            "classification": "HISTORICAL_TERMINAL_STATE_EXPECTATION",
            "count": 8,
            "owning_source_regression": False,
        }
    ],
    "full_suite": "TEST",
    "strict_l3": "PASS",
    "strict_l3_warnings": 0,
    "strict_l3_blockers": 0,
}


def _documents():
    return evidence.build_documents(
        REPO,
        validation_head=evidence.IMPLEMENTATION_HEAD,
        validation=VALIDATION,
    )


def _json(documents: dict[str, bytes], name: str):
    return json.loads(documents[f"{evidence.EVIDENCE_ROOT}/{name}"].decode("utf-8"))


def test_evidence_set_is_complete_exact_and_hash_bound():
    documents, result = _documents()
    required = {
        "README.md",
        "change-contract-v1.json",
        "root-cause-binding-v1.json",
        "sealed-restoration-set-binding-v1.json",
        "demand-aware-strategy-binding-v1.json",
        "source-diff-scope-v1.json",
        "restoration-implementation-matrix-v1.json",
        "old-vs-new-context-semantic-diff-v1.json",
        "character-heavy-semantic-coverage-v1.json",
        "relationship-setup-payoff-preservation-v1.json",
        "anti-template-validation-v1.json",
        "context-size-receipt-v1.json",
        "profile-identity-v1.json",
        "offline-quality-validation-v1.json",
        "test-receipt-v1.json",
        "historical-matrix-classification-v1.json",
        "a-control-reuse-decision-v1.json",
        "revalidation-ab-lock-v1.json",
        "revalidation-candidate-v1.json",
        "privacy-scan-v1.json",
        "final-report-v1.md",
        "sha256-manifest-v1.json",
    }
    actual = {path.removeprefix(f"{evidence.EVIDENCE_ROOT}/") for path in documents}
    assert required <= actual
    assert result["overall_status"] == "exact"
    assert result["new_context_characters"] == 2925
    assert result["privacy_match_count"] == 0

    manifest = _json(documents, "sha256-manifest-v1.json")
    assert manifest["entry_count"] == result["manifest_entry_count"]
    for entry in manifest["files"]:
        data = documents[entry["path"]]
        assert len(data) == entry["bytes"]
        assert evidence._sha_bytes(data) == entry["sha256"]
    assert evidence._sha_bytes(documents[f"{evidence.EVIDENCE_ROOT}/sha256-manifest-v1.json"]) == result["manifest_file_sha256"]


def test_restoration_diff_and_demand_mapping_are_closed_world():
    documents, _ = _documents()
    matrix = _json(documents, "restoration-implementation-matrix-v1.json")
    diff = _json(documents, "old-vs-new-context-semantic-diff-v1.json")
    strategy = _json(documents, "demand-aware-strategy-binding-v1.json")
    context = _json(documents, "context-size-receipt-v1.json")

    assert matrix["sealed_item_count"] == 4
    assert matrix["implemented_item_count"] == 4
    assert [row["restoration_id"] for row in matrix["rows"]] == list(evidence.RESTORATION_IDS)
    assert diff["changed_semantic_unit_count"] == 4
    assert diff["unchanged_rule_count"] == 16
    assert diff["unrelated_semantic_diff_count"] == 0
    assert diff["operational_rule_leak_count"] == 0
    assert strategy["resolver"] == "DETERMINISTIC_LOCAL"
    assert strategy["unknown_demand_behavior"] == "FAIL_CLOSED_NO_PROFILE_SUBSTITUTION"
    assert context["new_character_heavy_context_characters"] == 2925
    assert context["delta_characters"] == 183
    assert context["within_cap"] is True


def test_sealed_a_reuse_lock_and_candidate_are_inert():
    documents, result = _documents()
    reuse = _json(documents, "a-control-reuse-decision-v1.json")
    lock = _json(documents, "revalidation-ab-lock-v1.json")
    candidate = _json(documents, "revalidation-candidate-v1.json")

    assert reuse["can_reuse_sealed_a_control_after_b_profile_only_fix"] == "CONDITIONAL"
    assert reuse["a_control_reuse_conditions_satisfied"] == "YES"
    assert all(reuse["conditions"].values())
    assert lock["primary_changed_variable"] == "SKILL_CONTEXT"
    assert lock["unintended_ab_lock_diff_count"] == 0
    assert lock["successor_ab_lock_sha256"] == result["successor_ab_lock_sha256"]
    assert candidate["candidate_sha256"] == result["candidate_sha256"]
    assert candidate["execution_authorized"] is False
    assert candidate["real_execution_enabled"] is False
    assert candidate["usage_status"] == "unused"
    assert candidate["reservation_status"] == "unreserved"
    assert candidate["signed_approval"] == "ABSENT"
    assert candidate["single_use_nonce"] is None
    assert candidate["pair2_to_5_execution_allowed"] is False
    assert set(candidate["external_actions"].values()) == {0}
    assert not any("approval/" in path or "nonce/" in path for path in documents)


def test_repository_materialization_is_exact_when_present():
    documents, _ = _documents()
    for relative, expected in documents.items():
        path = REPO / relative
        if path.exists():
            assert path.read_bytes() == expected
