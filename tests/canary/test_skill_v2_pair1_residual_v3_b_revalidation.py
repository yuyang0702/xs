from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tools.canary import skill_v2_pair1_residual_v3_b_revalidation as readiness


REPO = Path(__file__).resolve().parents[2]


def _packet() -> dict:
    packet, _ = readiness.build_approval_readiness_packet(
        REPO,
        approval_parent_head=readiness.BASELINE_HEAD,
        require_parent=False,
    )
    return packet


def test_v3_candidate_profile_context_lock_and_parent_manifest_are_exact() -> None:
    binding = readiness.candidate_binding_v1(REPO)
    skill = readiness.residual_v3_skill_binding_v1(REPO)
    assert binding["candidate_sha256"] == readiness.CANDIDATE_SHA256
    assert binding["profile_sha256"] == readiness.PROFILE_SHA256
    assert binding["context_sha256"] == readiness.CONTEXT_SHA256
    assert binding["context_characters"] == 2998
    assert binding["successor_ab_lock_sha256"] == readiness.AB_LOCK_SHA256
    assert binding["manifest_status"] == "EXACT"
    assert skill["skill_arm"] == "RESTORED_SKILL_V2_CHARACTER_CORE_V3"
    assert skill["truncation"] == "NONE"


def test_v3_a_control_reuse_and_historical_b_isolation_are_exact() -> None:
    control = readiness.a_control_reuse_binding_v1(REPO)
    historical = readiness.historical_b_isolation_v1(REPO)
    assert control["a_control_reuse_binding"] == "PASS"
    assert control["shared_binding_mismatch_count"] == 0
    assert control["a_artifact_content_injected_into_new_b_model_input"] is False
    assert historical["historical_b_artifact_used_as_new_treatment"] is False
    assert historical["historical_b_result_injected_into_new_b_model_input"] is False


def test_v3_packet_is_inert_and_has_exact_closed_world_launcher() -> None:
    packet = _packet()
    assert readiness.validate_approval_readiness_packet(REPO, packet) == "PASS"
    assert packet["pair_case_id"] == "restored-character-heavy-v2-residual-v3"
    assert packet["arm_role"] == "B_ARM"
    assert packet["skill_arm"] == "RESTORED_SKILL_V2_CHARACTER_CORE_V3"
    assert packet["execution_authorized"] is False
    assert packet["signed_approval"] == "ABSENT"
    assert packet["single_use_nonce"] is None
    assert packet["private_blind_evidence_injected_into_b_model_input"] is False
    assert packet["retry_allowed"] is False
    assert packet["fallback_allowed"] is False
    assert packet["route_switch_allowed"] is False
    assert packet["resume_allowed"] is False
    assert packet["second_dispatch_allowed"] is False
    assert set(packet["external_actions"].values()) == {0}
    assert readiness.resolve_execution_entry_point(
        pair_case_id=packet["pair_case_id"],
        arm_role=packet["arm_role"],
        skill_arm=packet["skill_arm"],
        entry_point_id=packet["execution_entry_point_id"],
    ) is readiness.execute_authorized_once_v1


@pytest.mark.parametrize("case", readiness.PRECREDENTIAL_NEGATIVE_CASES)
def test_all_v3_precredential_negative_cases_fail_closed(case: str) -> None:
    result = readiness.run_precredential_negative_case_v1(REPO, _packet(), case)
    assert result["status"] == "REJECTED_BEFORE_CREDENTIAL_LOOKUP"
    assert result["real_boundary_reached"] is False
    assert set(result["external_actions"].values()) == {0}


@pytest.mark.parametrize("case", readiness.POSTDISPATCH_FAILURE_CASES)
def test_postdispatch_failures_never_retry(case: str) -> None:
    result = readiness.run_postdispatch_case_v1(case)
    assert result["fake_provider_requests"] == 1
    assert result["retry_attempts"] == 0
    assert result["fallback_attempts"] == 0
    assert result["route_switch_attempts"] == 0
    assert result["resume_attempts"] == 0
    assert result["second_dispatch_attempts"] == 0
    assert set(result["real_external_actions"].values()) == {0}


def test_phase_a_and_offline_dry_run_stop_before_real_boundary(tmp_path: Path) -> None:
    packet = _packet()
    phase = readiness.phase_a_preapproval_readiness_v1(REPO, packet)
    dry = readiness.offline_execution_dry_run_v1(REPO, packet, tmp_path)
    assert phase["status"] == "PASS"
    assert phase["signed_approval_present"] is False
    assert phase["execution_authorized"] is False
    assert phase["nonce_reserved"] is False
    assert phase["nonce_consumed"] is False
    assert dry["candidate_load"] == "PASS"
    assert dry["new_profile_context_load"] == "PASS"
    assert dry["local_fake_success_tail"] == "PASS"
    assert dry["real_boundary_reached"] is False
    assert dry["nonce_consumed"] is False
    assert set(dry["external_actions"].values()) == {0}


def test_real_entry_is_dormant_without_approval(tmp_path: Path) -> None:
    packet = _packet()
    with pytest.raises(readiness.DemandAwareBReadinessError):
        asyncio.run(readiness.execute_authorized_once_v1(
            repo_root=REPO,
            packet=packet,
            signed_approval={},
            permission_receipt=None,
            route_database=tmp_path / "never-open.db",
            run_root=tmp_path / "never-created",
            phase_b_receipt={},
        ))
    assert not (tmp_path / "never-created").exists()


def test_materialized_documents_cover_required_v3_evidence(tmp_path: Path) -> None:
    documents, result = readiness.build_documents_v1(
        REPO,
        approval_parent_head=readiness.BASELINE_HEAD,
        validation={"focused": "TEST", "adjacent": "TEST", "full_suite": "PENDING", "strict_l3": "PENDING"},
        temp_root=tmp_path,
        require_parent=False,
    )
    names = {Path(path).name for path in documents}
    assert {
        "candidate-binding-v1.json",
        "v3-profile-context-binding-v1.json",
        "a-control-reuse-binding-v1.json",
        "historical-b-isolation-v1.json",
        "successor-v3-ab-lock-binding-v1.json",
        "execution-entry-binding-v1.json",
        "launcher-binding-v1.json",
        "single-dispatch-contract-v1.json",
        "terminal-local-pipeline-contract-v1.json",
        "approval-readiness-packet-v1.json",
        "phase-a-preapproval-readiness-v1.json",
        "future-permission-before-nonce-v1.json",
        "future-data-egress-scope-v1.json",
        "nonce-readiness-v1.json",
        "negative-test-matrix-v1.json",
        "offline-dry-run-v1.json",
        "test-receipt-v1.json",
        "privacy-scan-v1.json",
        "final-report-v1.md",
        "sha256-manifest-v1.json",
    } <= names
    assert result["privacy_match_count"] == 0
    assert result["manifest_coverage"] == "exact"
    assert result["external_actions"] == readiness.ZERO_EXTERNAL_ACTIONS
