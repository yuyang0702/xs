from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tools.canary import skill_v2_bounded_repeated_ab_pair1_a as pair1_a


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def built() -> tuple[dict[str, bytes], dict[str, object]]:
    return pair1_a.build_closure_documents(
        REPO_ROOT,
        materialization_parent_head=pair1_a.BASELINE_HEAD,
        validation_evidence={"focused": "TEST", "related": "TEST", "full_suite": "TEST", "strict_l3": "TEST"},
    )


def _json(documents: dict[str, bytes], name: str) -> dict[str, object]:
    return json.loads(documents[f"{pair1_a.CLOSURE_ROOT}/{name}"].decode("utf-8"))


def test_source_bindings_are_explicit_and_canonical(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, _ = built
    launcher = _json(documents, "launcher-source-binding-v1.json")
    preflight = _json(documents, "signed-preflight-validator-binding-v1.json")
    head = _json(documents, "head-successor-validator-binding-v1.json")
    stop = _json(documents, "campaign-stop-state-authority-v1.json")

    assert launcher["launcher_source_path"] == pair1_a.LAUNCHER_SOURCE_PATH
    assert launcher["launcher_source_sha256"] == pair1_a._sha_file(
        REPO_ROOT / pair1_a.LAUNCHER_SOURCE_PATH
    )
    assert launcher["launcher_source_binding_explicit"] is True
    assert launcher["launcher_source_binding_unambiguous"] is True
    assert preflight["signed_preflight_validator_binding_explicit"] is True
    assert head["head_successor_validator_binding_explicit"] is True
    assert stop["stop_state_authority_explicit"] is True
    assert stop["campaign_stop_state"] == "CONTINUE_ALLOWED"


def test_successor_packet_is_disabled_exact_and_approval_ready(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, result = built
    successor = _json(documents, "pair1-a-successor-packet-v2.json")
    dry_run = _json(documents, "approval-readiness-dry-run-v1.json")

    assert result["approval_dry_run_result"] == "READY"
    assert successor["execution_authorized"] is False
    assert successor["named_approver"] is None
    assert successor["signed_approval"] == "ABSENT"
    assert successor["single_use_nonce"] is None
    assert successor["usage_status"] == "unused"
    assert successor["reservation_status"] == "unreserved"
    assert successor["successor_primary_semantic_diff"] == "APPROVAL_AUTHORITY_BINDING_CLOSURE_ONLY"
    assert dry_run["approval_dry_run_result"] == "READY"
    assert all(value == "PASS" for key, value in dry_run.items() if key.endswith("_binding") or key in {"pair_1_a_ab_lock", "pair_1_a_sequence"})


def test_pair_lock_and_original_v1_semantics_remain_exact(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, _ = built
    lock = _json(documents, "pair1-a-successor-ab-lock-v1.json")
    original = json.loads((REPO_ROOT / pair1_a.ORIGINAL_PACKET_PATH).read_text(encoding="utf-8"))
    successor = _json(documents, "pair1-a-successor-packet-v2.json")

    assert lock["a_b_experimental_lock_unchanged"] is True
    assert lock["primary_changed_variable"] == "SKILL_CONTEXT"
    for field in pair1_a.ORIGINAL_SEMANTIC_FIELDS:
        assert successor[field] == original[field]


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("missing_launcher_source", "launcher_source_sha256_missing"),
        ("wrong_launcher_source", "launcher_source_sha256_mismatch"),
        ("launcher_identity_source_mismatch", "launcher_identity_source_mismatch"),
        ("missing_preflight_validator", "signed_preflight_validator_sha256_missing"),
        ("wrong_preflight_validator", "signed_preflight_validator_sha256_mismatch"),
        ("missing_head_validator", "head_successor_validator_sha256_missing"),
        ("wrong_head_validator", "head_successor_validator_sha256_mismatch"),
        ("missing_stop_receipt", "campaign_stop_state_receipt_sha256_missing"),
        ("stale_stop_receipt", "campaign_stop_state_receipt_stale"),
        ("forged_continue_allowed", "campaign_stop_state_receipt_hash_mismatch"),
        ("stop_evaluator_source_mismatch", "campaign_stop_state_evaluator_sha256_mismatch"),
        ("wrong_pair", "pair_case_id_mismatch"),
        ("wrong_arm", "arm_role_mismatch"),
        ("wrong_scope", "scope_mismatch"),
        ("wrong_cohort", "cohort_mismatch"),
        ("wrong_original_packet", "original_packet_sha256_mismatch"),
        ("wrong_current_context", "current_skill_context_sha256_mismatch"),
        ("wrong_ab_lock", "pair_lock_sha256_mismatch"),
        ("arbitrary_historical_root", "historical_root_not_allowed"),
        ("precreated_approval", "signed_approval_must_be_absent"),
        ("precreated_nonce", "single_use_nonce_must_be_absent"),
    ],
)
def test_negative_matrix_fails_closed_before_external_action(
    built: tuple[dict[str, bytes], dict[str, object]], case: str, expected_reason: str,
) -> None:
    documents, _ = built
    packet = _json(documents, "pair1-a-successor-packet-v2.json")
    stop = _json(documents, "campaign-stop-state-authority-v1.json")
    mutated_packet, mutated_stop, historical_root = pair1_a.mutate_negative_case(
        packet, stop, case
    )
    with pytest.raises(pair1_a.Pair1AClosureError, match=expected_reason):
        pair1_a.validate_successor_packet(
            REPO_ROOT,
            mutated_packet,
            stop_receipt=mutated_stop,
            historical_root=historical_root,
        )
    assert set(pair1_a.ZERO_COUNTERS.values()) == {0}


def test_historical_roots_are_closed_world() -> None:
    policy = pair1_a.historical_root_policy()
    assert policy["historical_root_policy"] == "CLOSED_WORLD"
    assert pair1_a.CAMPAIGN_ROOT in policy["accepted_roots"]
    assert pair1_a.CLOSURE_ROOT in policy["accepted_roots"]
    assert pair1_a.APPROVAL_ROOT in policy["accepted_roots"]
    assert pair1_a.validate_historical_root(pair1_a.CAMPAIGN_ROOT) == "PASS"
    with pytest.raises(pair1_a.Pair1AClosureError, match="historical_root_not_allowed"):
        pair1_a.validate_historical_root("docs/superpowers/reports/arbitrary-root")


def test_cross_platform_documents_and_manifest_are_reproducible() -> None:
    first, _ = pair1_a.build_closure_documents(
        REPO_ROOT, materialization_parent_head=pair1_a.BASELINE_HEAD,
    )
    second, _ = pair1_a.build_closure_documents(
        REPO_ROOT, materialization_parent_head=pair1_a.BASELINE_HEAD,
    )
    assert first == second
    assert first[f"{pair1_a.CLOSURE_ROOT}/.gitattributes"] == b"* text eol=lf\n"
    manifest = _json(first, "sha256-manifest-v1.json")
    assert manifest["overall_status"] == "exact"
    assert manifest["entry_count"] == len(first) - 1
    for entry in manifest["files"]:
        data = first[entry["path"]]
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]


def test_privacy_and_external_actions_are_zero(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, result = built
    privacy = _json(documents, "privacy-scan-v1.json")
    assert privacy["overall_status"] == "exact"
    assert privacy["privacy_match_count"] == 0
    assert result["execution_authorized"] is False
    assert result["signed_approval"] == "ABSENT"
    assert result["single_use_nonce"] is None
    assert set(result["external_actions"].values()) == {0}
