from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from tools.canary import skill_v2_bounded_repeated_ab_pair1_a as pair1a


REPO = Path(__file__).resolve().parents[2]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _packet() -> dict:
    return pair1a.build_fresh_stop_state_successor_packet_v3(
        REPO, materialization_parent_head=pair1a.FRESH_STOP_FIX_BASELINE_HEAD,
    )


def _identity(packet: dict) -> dict:
    return {
        "schema": "SkillV2Pair1AUnsignedApprovalIdentityV1",
        "version": 1,
        "approval_id": "synthetic-pair1-a-approval-v3",
        "pair_case_id": pair1a.PAIR_CASE_ID,
        "arm_role": pair1a.ARM_ROLE,
        "scope": pair1a.SCOPE,
        "cohort_id": pair1a.COHORT,
        "approval_parent_head": pair1a.FRESH_STOP_FIX_BASELINE_HEAD,
        "successor_packet_sha256": packet["successor_packet_sha256"],
        "approval_evidence_root": pair1a.FRESH_APPROVAL_ROOT,
    }


def _signals() -> dict:
    return pair1a.build_campaign_stop_signals_v1()


def _write_transaction(root: Path, packet: dict) -> tuple[dict, dict]:
    approval = root / pair1a.FRESH_APPROVAL_ROOT
    approval.mkdir(parents=True)
    identity = _identity(packet)
    (approval / "approval-identity-v1.json").write_text(
        json.dumps(identity, sort_keys=True), encoding="utf-8",
    )
    signals = _signals()
    (approval / "campaign-stop-signals-v1.json").write_text(
        json.dumps(signals, sort_keys=True), encoding="utf-8",
    )
    return identity, signals


def _receipt(root: Path, packet: dict, identity: dict) -> dict:
    return pair1a.build_approval_time_stop_state_receipt_v1(
        REPO, packet=packet, approval_identity=identity,
        evidence_repo_root=root,
    )


def _signed(packet: dict, identity: dict, receipt: dict) -> dict:
    return {
        "schema": "SkillV2BoundedRepeatedABPair1ASignedApprovalV2",
        "version": 2,
        "execution_authorized": True,
        "named_approver": "USER_PROJECT_OWNER",
        "approval_scope": pair1a.SCOPE,
        "cohort_id": pair1a.COHORT,
        "approval_id": identity["approval_id"],
        "approval_parent_head": identity["approval_parent_head"],
        "successor_packet_sha256": packet["successor_packet_sha256"],
        "campaign_stop_state_receipt_path": pair1a.FRESH_RECEIPT_PATH,
        "campaign_stop_state_receipt_sha256": receipt["campaign_stop_state_receipt_sha256"],
        "single_use_nonce": "synthetic-test-only-nonce",
        "nonce_reserved": False,
        "nonce_consumed": False,
        "execution_window": {
            "not_before": "2026-08-25T00:00:00Z",
            "not_after": "2026-08-26T00:00:00Z",
        },
        "pair_1_b_arm_authorized": False,
        "pair_2_or_later_authorized": False,
        "skill_v2_production_cutover_authorized": False,
        "planning_v2_cutover_authorized": False,
        "draft_authorized": False,
        "full_short_authorized": False,
        "story_state_mutation_allowed": False,
        "canon_mutation_allowed": False,
        "ready_mutation_allowed": False,
    }


def test_phase_a_and_phase_b_transition_is_semantically_allowed(tmp_path: Path) -> None:
    packet = _packet()
    phase_a = pair1a.build_pre_approval_readiness_stop_state_v3(REPO, packet=packet)
    assert phase_a["receipt_type"] == "PRE_APPROVAL_READINESS_STOP_STATE"
    assert phase_a["current_arm_approval_exists"] is False
    assert phase_a["campaign_stop_state"] == "CONTINUE_ALLOWED"
    identity, _ = _write_transaction(tmp_path, packet)
    phase_b = _receipt(tmp_path, packet, identity)
    assert phase_b["receipt_type"] == "APPROVAL_TIME_SIGNED_PREFLIGHT_STOP_STATE"
    assert phase_b["current_arm_approval_exists"] is True
    assert phase_b["current_arm_approval_count"] == 1
    assert phase_b["campaign_stop_state"] == "CONTINUE_ALLOWED"
    assert pair1a.validate_approval_time_stop_state_receipt_v1(
        REPO, packet=packet, signed_approval=_signed(packet, identity, phase_b),
        receipt=phase_b, evidence_repo_root=tmp_path,
    )["status"] == "exact"


def test_receipt_serialization_is_deterministic(tmp_path: Path) -> None:
    packet = _packet()
    identity, _ = _write_transaction(tmp_path, packet)
    assert _receipt(tmp_path, packet, identity) == _receipt(tmp_path, packet, identity)


NEGATIVE_CASES = (
    "old_phase_a_receipt", "missing_fresh_receipt", "wrong_receipt_sha",
    "forged_continue", "wrong_evaluator", "wrong_pair", "wrong_arm",
    "wrong_approval_id", "wrong_approval_parent", "wrong_successor",
    "stale_state_set", "two_current_approvals", "pair1_b_approval",
    "later_approval", "pair1_a_result", "execution_root_exists",
    "critical_quality_stop", "engineering_stop", "ab_lock_stop",
    "arbitrary_receipt_root", "noncanonical_authority", "malformed_receipt",
    "missing_campaign_plan", "wrong_decision_rule", "after_nonce_reservation",
)


@pytest.mark.parametrize("case", NEGATIVE_CASES)
def test_mandatory_negative_matrix_fails_closed(tmp_path: Path, case: str) -> None:
    packet = _packet()
    identity, _ = _write_transaction(tmp_path, packet)
    receipt = _receipt(tmp_path, packet, identity)
    signed = _signed(packet, identity, receipt)
    candidate = pair1a.mutate_fresh_stop_state_negative_case(
        case, packet=packet, signed_approval=signed, receipt=receipt,
        evidence_repo_root=tmp_path,
    )
    with pytest.raises(pair1a.Pair1AClosureError):
        pair1a.validate_approval_time_stop_state_receipt_v1(
            REPO, packet=candidate["packet"],
            signed_approval=candidate["signed_approval"],
            receipt=candidate["receipt"],
            evidence_repo_root=candidate["evidence_repo_root"],
            nonce_reservation_attempted=candidate["nonce_reservation_attempted"],
        )


def test_v3_packet_is_disabled_and_preserves_ab_fields() -> None:
    packet = _packet()
    original = _read(REPO / pair1a.ORIGINAL_PACKET_PATH)
    assert packet["execution_authorized"] is False
    assert packet["signed_approval"] == "ABSENT"
    assert packet["single_use_nonce"] is None
    assert packet["successor_primary_semantic_diff"] == "SIGNED_PREFLIGHT_FRESH_STOP_STATE_BINDING_FIX_ONLY"
    assert packet["packet_manifest_path"] == f"{pair1a.FRESH_STOP_FIX_ROOT}/sha256-manifest-v1.json"
    assert packet["privacy_receipt_path"] == f"{pair1a.FRESH_STOP_FIX_ROOT}/privacy-scan-v1.json"
    assert packet["packet_manifest_definition_sha256"] == pair1a.fresh_manifest_definition_v1()["manifest_definition_sha256"]
    assert packet["privacy_receipt_definition_sha256"] == pair1a.fresh_privacy_definition_v1()["privacy_definition_sha256"]
    for field in pair1a.ORIGINAL_SEMANTIC_FIELDS:
        assert packet[field] == original[field]


def test_old_phase_a_receipt_is_not_a_signed_preflight_receipt() -> None:
    packet = _packet()
    phase_a = pair1a.build_pre_approval_readiness_stop_state_v3(REPO, packet=packet)
    assert phase_a["receipt_type"] != "APPROVAL_TIME_SIGNED_PREFLIGHT_STOP_STATE"


def test_post_seal_head_successor_uses_only_canonical_approval_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    pair1a.init_synthetic_head_successor_repo(repo)
    result = pair1a.simulate_post_seal_head_successor(repo)
    assert result["status"] == "PASS"
    assert result["post_seal_signed_preflight_with_fresh_receipt"] == "PASS"


def test_positive_synthetic_signed_preflight_transaction(tmp_path: Path) -> None:
    repo = tmp_path / "transaction"
    repo.mkdir()
    result = pair1a.run_positive_synthetic_transaction_v1(REPO, repo)
    assert result["pre_seal_signed_preflight"] == "PASS"
    assert result["post_seal_signed_preflight_with_fresh_receipt"] == "PASS"
    assert result["approval_exists_transition"] == "false_to_true"
    assert result["campaign_decision_after"] == "CONTINUE_ALLOWED"
    assert result["nonce_reservation_attempted"] is False
    assert result["external_actions"] == pair1a.ZERO_COUNTERS


def test_fresh_evidence_is_deterministic_complete_and_private() -> None:
    first, first_result = pair1a.build_fresh_stop_state_fix_documents(
        REPO, implementation_parent_head=pair1a.FRESH_STOP_FIX_BASELINE_HEAD,
        validation_evidence={"focused": "31 passed", "related": "PASS", "strict_l3": "PASS"},
    )
    second, second_result = pair1a.build_fresh_stop_state_fix_documents(
        REPO, implementation_parent_head=pair1a.FRESH_STOP_FIX_BASELINE_HEAD,
        validation_evidence={"focused": "31 passed", "related": "PASS", "strict_l3": "PASS"},
    )
    assert first == second
    assert first_result == second_result
    assert len(first) == 21
    privacy = json.loads(first[f"{pair1a.FRESH_STOP_FIX_ROOT}/privacy-scan-v1.json"])
    manifest = json.loads(first[f"{pair1a.FRESH_STOP_FIX_ROOT}/sha256-manifest-v1.json"])
    assert privacy["overall_status"] == "exact"
    assert privacy["privacy_match_count"] == 0
    assert manifest["entry_count"] == 20
    assert first[f"{pair1a.FRESH_STOP_FIX_ROOT}/.gitattributes"] == b"* text eol=lf\n"
    assert first_result["approval_ready_v3"] is True
    assert first_result["execution_authorized"] is False
