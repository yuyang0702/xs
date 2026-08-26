from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tools.canary import skill_v2_pair1_demand_aware_b_revalidation as readiness


REPO = Path(__file__).resolve().parents[2]


def _packet() -> dict:
    return readiness.build_approval_readiness_packet(
        REPO, approval_parent_head="a" * 40, require_parent=False,
    )[0]


def test_parent_candidate_manifest_and_logical_identities_are_exact() -> None:
    binding = readiness.candidate_binding_v1(REPO)
    assert binding["candidate_sha256"] == readiness.CANDIDATE_SHA256
    assert binding["profile_sha256"] == readiness.PROFILE_SHA256
    assert binding["context_sha256"] == readiness.CONTEXT_SHA256
    assert binding["context_characters"] == 2925
    assert binding["successor_ab_lock_sha256"] == readiness.AB_LOCK_SHA256
    assert binding["manifest_status"] == "EXACT"
    assert binding["execution_authorized"] is False
    assert binding["signed_approval"] == "ABSENT"
    assert binding["nonce_reserved"] is False


def test_a_control_reuse_policy_is_revalidated_mechanically() -> None:
    binding = readiness.a_control_reuse_binding_v1(REPO)
    assert binding["a_control_reuse_binding"] == "PASS"
    assert binding["a_control_status"] == "PASS_SEALED"
    assert binding["a_control_packet_sha256"] == readiness.A_PACKET_SHA256
    assert binding["a_control_artifact_sha256"] == readiness.A_ARTIFACT_SHA256
    assert binding["shared_binding_count"] == 19
    assert binding["shared_binding_mismatch_count"] == 0
    assert binding["primary_changed_variable"] == "SKILL_CONTEXT"
    assert binding["a_artifact_content_injected_into_new_b_model_input"] is False
    assert binding["a_result_used_only_as_sealed_control_evidence"] is True


def test_historical_failed_b_is_isolated_from_new_treatment() -> None:
    binding = readiness.historical_b_isolation_v1(REPO)
    assert binding["historical_b_artifact_sha256"] == readiness.HISTORICAL_B_ARTIFACT_SHA256
    assert binding["historical_b_artifact_used_as_new_treatment"] is False
    assert binding["historical_b_result_injected_into_new_b_model_input"] is False
    assert binding["historical_b_result_used_only_as_root_cause_sequence_evidence"] is True
    assert binding["fresh_treatment_artifact_required"] is True


def test_demand_aware_profile_and_request_binding_are_exact() -> None:
    skill = readiness.demand_aware_skill_binding_v1(REPO)
    assert skill["skill_arm"] == "RESTORED_SKILL_V2_CHARACTER_CORE_V2"
    assert skill["profile_sha256"] == readiness.PROFILE_SHA256
    assert skill["context_sha256"] == readiness.CONTEXT_SHA256
    assert skill["context_characters"] == 2925
    assert skill["truncation"] == "NONE"
    model, system, user, _authority = readiness._demand_aware_b_model_input(
        REPO, REPO / "data/app.db",
    )
    assert model["skill_profile_sha256"] == readiness.PROFILE_SHA256
    assert model["skill_context_sha256"] == readiness.CONTEXT_SHA256
    assert hashlib.sha256(system.encode("utf-8")).hexdigest() == model["system_sha256"]
    assert hashlib.sha256(user.encode("utf-8")).hexdigest() == model["user_sha256"]
    assert readiness.A_ARTIFACT_SHA256 not in system + user
    assert readiness.HISTORICAL_B_ARTIFACT_SHA256 not in system + user


def test_disabled_packet_has_complete_execution_and_launcher_bindings() -> None:
    packet = _packet()
    assert readiness.validate_approval_readiness_packet(REPO, packet) == "PASS"
    assert packet["candidate_sha256"] == readiness.CANDIDATE_SHA256
    assert packet["pair_case_id"] == readiness.PAIR_CASE_ID
    assert packet["arm_role"] == "B_ARM"
    assert packet["skill_arm"] == readiness.SKILL_ARM
    assert packet["skill_profile_sha256"] == readiness.PROFILE_SHA256
    assert packet["skill_context_sha256"] == readiness.CONTEXT_SHA256
    assert packet["pair_lock_sha256"] == readiness.AB_LOCK_SHA256
    assert packet["execution_entry_point_present"] is True
    assert packet["execution_authorized"] is False
    assert packet["signed_approval"] == "ABSENT"
    assert packet["single_use_nonce"] is None
    assert packet["usage_status"] == "unused"
    assert packet["reservation_status"] == "unreserved"
    assert packet["hard_max_model_calls"] == 1
    assert packet["hard_max_real_provider_request_attempts"] == 1
    assert packet["hard_max_http_post_attempts"] == 1
    assert packet["hard_max_network_request_attempts"] == 1
    assert packet["retry_allowed"] is False
    assert packet["fallback_allowed"] is False
    assert packet["route_switch_allowed"] is False
    assert packet["resume_allowed"] is False
    assert packet["second_dispatch_allowed"] is False


def test_execution_entry_is_closed_world() -> None:
    resolved = readiness.resolve_execution_entry_point(
        pair_case_id=readiness.PAIR_CASE_ID,
        arm_role=readiness.ARM_ROLE,
        skill_arm=readiness.SKILL_ARM,
        entry_point_id=readiness.ENTRY_POINT_ID,
    )
    assert resolved is readiness.execute_authorized_once_v1
    for changed in (
        {"pair_case_id": "restored-world-heavy-v1"},
        {"arm_role": "A_ARM"},
        {"skill_arm": "RESTORED_SKILL_V2"},
        {"entry_point_id": "arbitrary:execute"},
    ):
        values = {
            "pair_case_id": readiness.PAIR_CASE_ID,
            "arm_role": readiness.ARM_ROLE,
            "skill_arm": readiness.SKILL_ARM,
            "entry_point_id": readiness.ENTRY_POINT_ID,
            **changed,
        }
        with pytest.raises(readiness.DemandAwareBReadinessError, match="entry_point_not_registered"):
            readiness.resolve_execution_entry_point(**values)


def test_approval_parent_source_policy_is_narrow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness, "_git", lambda _repo, *args: "")
    monkeypatch.setattr(
        readiness, "_changed", lambda _repo, _older, _newer: (readiness.SOURCE_PATH, readiness.TEST_PATH),
    )
    receipt = readiness.validate_approval_parent_source_policy(REPO, "a" * 40)
    assert receipt["approval_parent_head_validation"] == "PASS"
    monkeypatch.setattr(
        readiness, "_changed", lambda _repo, _older, _newer: (readiness.SOURCE_PATH, "src/novel_flywheel/workflows.py"),
    )
    with pytest.raises(readiness.DemandAwareBReadinessError, match="approval_parent_scope_mismatch"):
        readiness.validate_approval_parent_source_policy(REPO, "a" * 40)


def test_phase_a_is_real_and_phase_b_remains_unmaterialized() -> None:
    phase_a = readiness.phase_a_preapproval_readiness_v1(REPO, _packet())
    assert phase_a["phase"] == "PRE_APPROVAL_READINESS"
    assert phase_a["status"] == "PASS"
    assert phase_a["signed_approval_present"] is False
    assert phase_a["execution_authorized"] is False
    assert phase_a["nonce_id"] == "NOT_YET_CREATED_BY_DESIGN"
    assert phase_a["semantic_stop_state"] == "CONTINUE_ALLOWED_FOR_LATER_APPROVAL_CREATION_ONLY"
    assert set(phase_a["external_actions"].values()) == {0}


def test_synthetic_phase_b_preflight_proves_future_sequence_only() -> None:
    packet = _packet()
    signed = readiness.synthetic_signed_approval_v1(packet)
    phase_b = readiness.phase_b_receipt_v1(REPO, signed, synthetic=True)
    permission = readiness.synthetic_permission_receipt_v1(packet, signed)
    gate = readiness.validate_precredential_gate_v1(
        REPO,
        packet=packet,
        signed_approval=signed,
        phase_b_receipt=phase_b,
        permission_receipt=permission,
        allow_synthetic=True,
    )
    assert gate["status"] == "exact"
    assert gate["nonce_state"] == "unreserved_unconsumed"


@pytest.mark.parametrize("case", readiness.PRECREDENTIAL_NEGATIVE_CASES)
def test_precredential_negative_matrix(case: str) -> None:
    result = readiness.run_precredential_negative_case_v1(REPO, _packet(), case)
    assert result["status"] == "REJECTED_BEFORE_CREDENTIAL_LOOKUP"
    assert result["real_boundary_reached"] is False
    assert set(result["external_actions"].values()) == {0}


@pytest.mark.parametrize("case", readiness.POSTDISPATCH_FAILURE_CASES)
def test_single_dispatch_terminal_matrix_never_retries(case: str) -> None:
    result = readiness.run_postdispatch_case_v1(case)
    assert result["fake_provider_requests"] == 1
    assert result["fake_http_posts"] == 1
    assert result["fake_network_attempts"] == 1
    assert result["retry_attempts"] == 0
    assert result["fallback_attempts"] == 0
    assert result["route_switch_attempts"] == 0
    assert result["resume_attempts"] == 0
    assert result["second_dispatch_attempts"] == 0
    assert set(result["real_external_actions"].values()) == {0}


def test_offline_dry_run_blocks_real_boundary_and_completes_local_tail(tmp_path: Path) -> None:
    receipt = readiness.offline_execution_dry_run_v1(REPO, _packet(), tmp_path)
    assert receipt["candidate_load"] == "PASS"
    assert receipt["sealed_a_control_binding"] == "PASS_EVIDENCE_ONLY"
    assert receipt["new_profile_context_load"] == "PASS"
    assert receipt["single_dispatch_guard_armed"] is True
    assert receipt["approval_missing_real_boundary_blocked"] is True
    assert receipt["real_boundary_reached"] is False
    assert receipt["local_fake_success_tail"] == "PASS"
    assert receipt["story_state_mutations"] == 0
    assert receipt["canon_mutations"] == 0
    assert receipt["ready_mutations"] == 0
    assert set(receipt["external_actions"].values()) == {0}
    safe = json.loads((tmp_path / "dry-run-receipt-v1.json").read_text(encoding="utf-8"))
    assert "narrative" not in json.dumps(safe)


def test_future_egress_scope_excludes_control_and_historical_prose() -> None:
    scope = readiness.future_data_egress_scope_v1(REPO)
    assert scope["a_control_artifact_prose_egress"] is False
    assert scope["historical_failed_b_artifact_prose_egress"] is False
    assert scope["private_blind_review_evidence_egress"] is False
    assert scope["only_new_b_packet_required_data_egress"] is True


def test_packet_tamper_fails_closed() -> None:
    for field, value in (
        ("approval_readiness_packet_sha256", "0" * 64),
        ("candidate_sha256", "0" * 64),
        ("skill_profile_sha256", "0" * 64),
        ("skill_context_sha256", "0" * 64),
        ("pair_lock_sha256", "0" * 64),
        ("route_model_client_sha256", "0" * 64),
        ("output_cap", 4625),
        ("execution_entry_point_present", False),
        ("launcher_source_sha256", "0" * 64),
        ("pair2_to_5_execution_allowed", True),
        ("skill_v2_production_cutover_authorized", True),
    ):
        packet = deepcopy(_packet())
        packet[field] = value
        with pytest.raises(readiness.DemandAwareBReadinessError):
            readiness.validate_approval_readiness_packet(REPO, packet)


def test_packet_documents_privacy_and_forward_risk_are_exact(tmp_path: Path) -> None:
    documents, result = readiness.build_documents_v1(
        REPO,
        approval_parent_head="a" * 40,
        validation={"focused": "PENDING", "adjacent": "PENDING", "full_suite": "PENDING", "strict_l3": "PENDING"},
        temp_root=tmp_path,
        require_parent=False,
    )
    expected = {
        "README.md", "candidate-binding-v1.json", "a-control-reuse-binding-v1.json",
        "historical-b-isolation-v1.json", "execution-entry-binding-v1.json",
        "launcher-binding-v1.json", "single-dispatch-contract-v1.json",
        "terminal-local-pipeline-contract-v1.json", "approval-readiness-packet-v1.json",
        "phase-a-preapproval-readiness-v1.json", "future-permission-before-nonce-v1.json",
        "future-data-egress-scope-v1.json", "nonce-readiness-v1.json",
        "negative-test-matrix-v1.json", "offline-dry-run-v1.json", "test-receipt-v1.json",
        "privacy-scan-v1.json", "final-report-v1.md", "sha256-manifest-v1.json",
    }
    assert expected <= {Path(path).name for path in documents}
    assert result["privacy_match_count"] == 0
    assert result["manifest_coverage"] == "exact"
    assert result["approval_readiness_packet_sha256"] == _packet()["approval_readiness_packet_sha256"]


def test_real_entry_is_dormant_without_sealed_approval(tmp_path: Path) -> None:
    packet = _packet()
    with pytest.raises(readiness.DemandAwareBReadinessError):
        asyncio.run(
            readiness.execute_authorized_once_v1(
                repo_root=REPO,
                packet=packet,
                signed_approval={},
                permission_receipt=None,
                route_database=tmp_path / "never-read.db",
                run_root=tmp_path / "never-created",
                phase_b_receipt={},
            )
        )
    assert not (tmp_path / "never-created").exists()
