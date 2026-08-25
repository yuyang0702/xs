from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tools.canary import skill_v2_pair1_corrected_b_binding_closure as closure


REPO = Path(__file__).resolve().parents[2]


def _packet() -> dict:
    return closure.build_successor_packet(REPO, approval_parent_head="a" * 40)[0]


def test_corrected_b_closed_world_entry_exists() -> None:
    resolved = closure.resolve_execution_entry_point(
        pair_case_id="restored-character-heavy-v2",
        arm_role="B_ARM",
        skill_arm="RESTORED_SKILL_V2",
        entry_point_id=closure.ENTRY_POINT_ID,
    )
    assert resolved is closure.execute_authorized_once_v3
    for changed in (
        {"pair_case_id": "restored-world-heavy-v1"},
        {"arm_role": "A_ARM"},
        {"skill_arm": "CURRENT_RUNTIME_SKILL"},
        {"entry_point_id": "arbitrary:execute"},
    ):
        values = {
            "pair_case_id": closure.PAIR_CASE_ID,
            "arm_role": closure.ARM_ROLE,
            "skill_arm": closure.SKILL_ARM,
            "entry_point_id": closure.ENTRY_POINT_ID,
            **changed,
        }
        with pytest.raises(closure.CorrectedBBindingError, match="entry_point_not_registered"):
            closure.resolve_execution_entry_point(**values)


def test_sealed_a_control_is_sequence_only_and_exact() -> None:
    control = closure.sealed_a_control_binding(REPO)
    assert control["a_status"] == "PASS_SEALED"
    assert control["a_control_sample_valid"] is True
    assert control["a_artifact_sha256"] == closure.A_ARTIFACT_SHA256
    assert control["a_nonce_status"] == "CONSUMED"
    assert control["a_artifact_content_visible_to_b_model"] is False
    assert control["a_artifact_hash_in_b_prompt"] is False
    assert control["a_result_used_only_as_sequence_control_evidence"] is True


def test_forward_audits_merge_full_gap_lists() -> None:
    audit = closure.merge_forward_audits(REPO)
    assert audit["corrected_b_approval_binding_complete_before_fix"] is False
    assert audit["corrected_b_execution_entry_point_present_before_fix"] is False
    assert "approval_parent_head" in audit["corrected_b_missing_approval_bindings"]
    assert "execution_entry_point_id" in audit["corrected_b_missing_execution_bindings"]
    assert audit["known_gap_count"] == 29
    assert audit["full_gap_list_closed_by_successor"] is True


def test_restored_skill_and_b_model_input_are_exact() -> None:
    binding = closure.restored_skill_binding(REPO)
    assert binding["profile_sha256"] == closure.RESTORED_PROFILE_SHA256
    assert binding["context_sha256"] == closure.RESTORED_CONTEXT_SHA256
    assert binding["context_char_count"] == 2742
    assert binding["restoration_items_present"] == "8/8"
    model, system, user, _authority = closure._corrected_b_model_input(REPO, REPO / "data/app.db")
    packet = _packet()
    assert hashlib.sha256(system.encode("utf-8")).hexdigest() == packet["system_sha256"]
    assert hashlib.sha256(user.encode("utf-8")).hexdigest() == packet["user_sha256"]
    assert model["skill_context_sha256"] == closure.RESTORED_CONTEXT_SHA256
    assert closure.A_ARTIFACT_SHA256 not in system
    assert closure.A_ARTIFACT_SHA256 not in user


def test_successor_packet_is_disabled_and_preserves_b_v2_semantics() -> None:
    packet = _packet()
    old = json.loads((REPO / closure.B_V2_PATH).read_text(encoding="utf-8"))
    assert closure.validate_packet_v3(REPO, packet) == "PASS"
    assert packet["execution_entry_point_present"] is True
    assert packet["arm_role"] == "B_ARM"
    assert packet["skill_arm"] == "RESTORED_SKILL_V2"
    assert packet["execution_authorized"] is False
    assert packet["signed_approval"] == "ABSENT"
    assert packet["single_use_nonce"] is None
    assert packet["usage_status"] == "unused"
    assert packet["reservation_status"] == "unreserved"
    assert packet["a_artifact_injected_into_b_model_input"] is False
    for field in closure.PARITY_FIELDS:
        assert packet[field] == old[field]


def test_approval_parent_policy_is_explicit_and_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(closure, "_git", lambda _repo, *args: "" if args[0] == "merge-base" else "")
    monkeypatch.setattr(closure, "_changed", lambda _repo, _older, _newer: (closure.SOURCE_PATH, closure.TEST_PATH))
    receipt = closure.validate_approval_parent_source_policy(REPO, "a" * 40)
    assert receipt["approval_parent_head_explicit"] is True
    assert receipt["approval_parent_head_validation"] == "PASS"
    monkeypatch.setattr(closure, "_changed", lambda _repo, _older, _newer: (closure.SOURCE_PATH, "src/novel_flywheel/workflows.py"))
    with pytest.raises(closure.CorrectedBBindingError, match="approval_parent_scope_mismatch"):
        closure.validate_approval_parent_source_policy(REPO, "a" * 40)


def test_two_phase_stop_state_and_signed_preflight_are_exact() -> None:
    packet = _packet()
    phase_a = closure.phase_receipt_v3(REPO, "PHASE_A")
    assert phase_a["current_state"]["pair1_b_approval_exists"] is False
    signed = closure.synthetic_signed_approval_v3(packet)
    phase_b = closure.phase_receipt_v3(REPO, "PHASE_B", signed, synthetic=True)
    permission = closure.synthetic_permission_receipt_v1(packet, signed)
    gate = closure.validate_precredential_gate_v3(
        REPO, packet=packet, signed_approval=signed, phase_b_receipt=phase_b,
        permission_receipt=permission, allow_synthetic=True,
    )
    assert gate["status"] == "exact"
    assert gate["nonce_state"] == "unreserved_unconsumed"


@pytest.mark.parametrize("case", closure.PRECREDENTIAL_NEGATIVE_CASES)
def test_precredential_negative_matrix(case: str) -> None:
    result = closure.run_precredential_negative_case_v1(REPO, _packet(), case)
    assert result["status"] == "REJECTED_BEFORE_CREDENTIAL_LOOKUP"
    assert set(result["external_actions"].values()) == {0}


@pytest.mark.parametrize("case", closure.POSTDISPATCH_FAILURE_CASES)
def test_postdispatch_matrix_is_single_attempt(case: str) -> None:
    result = closure.run_postdispatch_case_v1(case)
    assert result["fake_provider_requests"] == 1
    assert result["fake_http_posts"] == 1
    assert result["fake_network_attempts"] == 1
    assert result["retry_attempts"] == 0
    assert result["fallback_attempts"] == 0
    assert result["second_dispatch_attempts"] == 0
    assert result["resume_second_request"] == 0
    assert set(result["real_external_actions"].values()) == {0}


def test_full_fake_execution_entry_crosses_local_success_tail(tmp_path: Path) -> None:
    receipt = closure.offline_execution_entry_dry_run_v1(REPO, _packet(), tmp_path)
    assert receipt["b_execution_entry_point_resolution"] == "PASS"
    assert receipt["a_control_sequence_binding"] == "PASS"
    assert receipt["fake_provider_dispatch_count"] == 1
    assert receipt["fake_http_post_attempts"] == 1
    assert receipt["fake_network_attempts"] == 1
    assert receipt["fake_model_calls"] == 1
    assert receipt["local_validation"] == "PASS"
    assert receipt["artifact_freeze"] == "PASS"
    assert receipt["audit_serialization"] == "PASS"
    assert receipt["output_isolation"] == "PASS"
    assert receipt["persistence"] == "PASS"
    assert set(receipt["real_external_actions"].values()) == {0}
    safe = json.loads((tmp_path / "execution/dry-run-receipt.json").read_text(encoding="utf-8"))
    assert "narrative" not in json.dumps(safe)


def test_approval_readiness_dry_run_is_inert(tmp_path: Path) -> None:
    receipt = closure.approval_readiness_dry_run_v1(REPO, _packet(), tmp_path)
    assert receipt["b_approval_dry_run_result"] == "READY"
    assert receipt["b_execution_entry_dry_run"] == "PASS"
    assert receipt["signed_approval"] == "ABSENT"
    assert receipt["single_use_nonce"] == "ABSENT"
    assert set(receipt["external_actions"].values()) == {0}


def test_historical_roots_are_closed_world_and_pair2_remains_blocked() -> None:
    policy = closure.historical_root_policy_v1()
    for root in policy["accepted_roots"]:
        assert closure.validate_historical_root_v1(root) == "PASS"
    with pytest.raises(closure.CorrectedBBindingError, match="historical_root_not_allowed"):
        closure.validate_historical_root_v1("docs/superpowers/reports/arbitrary")
    packet = _packet()
    assert packet["pair2_or_later_authorized"] is False
    assert packet["pair2_to_5_execution_allowed"] is False


def test_packet_tamper_fails_closed() -> None:
    for field, value in (
        ("packet_sha256", "0" * 64),
        ("arm_role", "A_ARM"),
        ("skill_arm", "CURRENT_RUNTIME_SKILL"),
        ("pair_lock_sha256", "0" * 64),
        ("execution_entry_point_present", False),
        ("execution_entry_point_source_sha256", "0" * 64),
        ("a_control_binding_sha256", "0" * 64),
    ):
        packet = deepcopy(_packet())
        packet[field] = value
        with pytest.raises(closure.CorrectedBBindingError):
            closure.validate_packet_v3(REPO, packet)


def test_packet_manifest_privacy_and_forward_risk_are_exact() -> None:
    manifest = closure.packet_manifest_binding(REPO)
    privacy = closure.packet_privacy_binding(REPO)
    risk = closure.forward_risk_report_v2()
    assert manifest["coverage"] == "exact"
    assert privacy["privacy_match_count"] == 0
    assert risk["model_output_boundary_changed"] is False
    assert risk["resolution_status"] == "case_fixed"


def test_real_entry_is_dormant_without_sealed_approval(tmp_path: Path) -> None:
    packet = _packet()
    signed = closure.synthetic_signed_approval_v3(packet)
    with pytest.raises(closure.CorrectedBBindingError):
        asyncio.run(closure.execute_authorized_once_v3(
            repo_root=REPO, packet=packet, signed_approval=signed,
            permission_receipt=None, route_database=tmp_path / "never-read.db",
            run_root=tmp_path / "never-created",
            phase_b_receipt=closure.phase_receipt_v3(REPO, "PHASE_B", signed, synthetic=True),
        ))
    assert not (tmp_path / "never-created").exists()
