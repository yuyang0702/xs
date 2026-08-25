from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tools.canary import skill_v2_pair1_corrected_a_launcher_binding as launcher


REPO = Path(__file__).resolve().parents[2]


def _packet() -> dict:
    return launcher.build_v4_packet_body(REPO, approval_parent_head="a" * 40)[0]


def _signed(packet: dict) -> dict:
    return launcher.synthetic_signed_approval_v4(packet)


def test_registry_resolves_only_exact_corrected_a_entry() -> None:
    resolved = launcher.resolve_execution_entry_point(
        pair_case_id=launcher.PAIR_CASE_ID,
        arm_role=launcher.ARM_ROLE,
        skill_arm=launcher.SKILL_ARM,
        entry_point_id=launcher.ENTRY_POINT_ID,
    )
    assert resolved is launcher.execute_authorized_once_v4
    for changed in (
        {"pair_case_id": "restored-character-heavy-v1"},
        {"arm_role": "B_ARM"},
        {"skill_arm": "RESTORED_SKILL_V2"},
        {"entry_point_id": "arbitrary:execute"},
    ):
        values = {
            "pair_case_id": launcher.PAIR_CASE_ID,
            "arm_role": launcher.ARM_ROLE,
            "skill_arm": launcher.SKILL_ARM,
            "entry_point_id": launcher.ENTRY_POINT_ID,
            **changed,
        }
        with pytest.raises(launcher.LauncherBindingError, match="entry_point_not_registered"):
            launcher.resolve_execution_entry_point(**values)


def test_v4_packet_is_disabled_and_preserves_frozen_authority() -> None:
    packet = _packet()
    assert launcher.validate_v4_packet(REPO, packet) == "PASS"
    assert packet["execution_entry_point_present"] is True
    assert packet["execution_entry_point_id"] == launcher.ENTRY_POINT_ID
    assert packet["corrected_formal_event_id"] == "EV-3D3AE01E"
    assert packet["authority_input_sha256"] == launcher.AUTHORITY_SHA256
    assert packet["story_slice_sha256"] == launcher.STORY_SHA256
    assert packet["pair_lock_sha256"] == launcher.LOCK_SHA256
    assert packet["execution_authorized"] is False
    assert packet["signed_approval"] == "ABSENT"
    assert packet["single_use_nonce"] is None
    assert set(packet["external_actions"].values()) == {0}


def test_precredential_gate_and_execution_order_contract() -> None:
    packet = _packet()
    signed = _signed(packet)
    phase_b = launcher.synthetic_phase_b_receipt_v4(packet, signed)
    permission = launcher.synthetic_permission_receipt_v1(packet, signed)
    gate = launcher.validate_precredential_gate_v4(
        REPO,
        packet=packet,
        signed_approval=signed,
        phase_b_receipt=phase_b,
        permission_receipt=permission,
        allow_synthetic=True,
    )
    assert gate["status"] == "exact"
    assert gate["nonce_state"] == "unreserved_unconsumed"
    assert launcher.execution_order_contract_v1()["permission_before_nonce_reservation"] is True


@pytest.mark.parametrize("case", launcher.PRECREDENTIAL_NEGATIVE_CASES)
def test_precredential_negative_matrix_case(case: str) -> None:
    packet = _packet()
    result = launcher.run_precredential_negative_case_v1(REPO, packet, case)
    assert result["status"] == "REJECTED_BEFORE_CREDENTIAL_LOOKUP"
    assert set(result["external_actions"].values()) == {0}


@pytest.mark.parametrize("case", launcher.POSTDISPATCH_FAILURE_CASES)
def test_postdispatch_failure_is_single_attempt(case: str, tmp_path: Path) -> None:
    result = launcher.run_fake_dispatch_case_v1(REPO, _packet(), case, tmp_path / case)
    assert result["fake_provider_requests"] <= 1
    assert result["fake_http_posts"] <= 1
    assert result["fake_network_attempts"] <= 1
    assert result["retry"] == 0
    assert result["fallback"] == 0
    assert result["second_dispatch"] == 0
    assert set(result["real_external_actions"].values()) == {0}


def test_full_offline_entry_dry_run(tmp_path: Path) -> None:
    receipt = launcher.offline_execution_entry_dry_run_v1(
        REPO, _packet(), tmp_path / "isolated-run",
    )
    assert receipt["execution_entry_point_resolution"] == "PASS"
    assert receipt["fake_provider_dispatch_count"] == 1
    assert receipt["fake_http_post_attempts"] == 1
    assert receipt["fake_network_attempts"] == 1
    assert receipt["fake_model_calls"] == 1
    assert receipt["local_validation"] == "PASS"
    assert receipt["artifact_freeze"] == "PASS"
    assert receipt["audit_serialization"] == "PASS"
    assert receipt["persistence"] == "PASS"
    assert set(receipt["real_external_actions"].values()) == {0}
    persisted = json.loads(
        (tmp_path / "isolated-run" / "execution" / "receipt.json").read_text("utf-8")
    )
    assert "narrative" not in json.dumps(persisted)
    ledger = tmp_path / "isolated-run" / "execution" / "ledger" / "single-use-ledger-v1.json"
    assert json.loads(ledger.read_text("utf-8"))["usage_status"] == "reserved"


def test_v3_approval_and_nonce_cannot_authorize_v4() -> None:
    packet = _packet()
    old = json.loads((REPO / launcher.V3_SIGNED_APPROVAL_PATH).read_text("utf-8"))
    phase_b = launcher.synthetic_phase_b_receipt_v4(packet, old)
    permission = launcher.synthetic_permission_receipt_v1(packet, old)
    with pytest.raises(launcher.LauncherBindingError, match="signed_approval_schema_mismatch"):
        launcher.validate_precredential_gate_v4(
            REPO,
            packet=packet,
            signed_approval=old,
            phase_b_receipt=phase_b,
            permission_receipt=permission,
        )


def test_packet_tamper_and_old_disabled_entry_fail_closed() -> None:
    for field, value in (
        ("packet_sha256", "0" * 64),
        ("execution_entry_point_present", False),
        ("execution_entry_point_id", "wrong"),
        ("execution_entry_point_source_sha256", "0" * 64),
        ("pair_lock_sha256", "0" * 64),
    ):
        packet = deepcopy(_packet())
        packet[field] = value
        with pytest.raises(launcher.LauncherBindingError):
            launcher.validate_v4_packet(REPO, packet)


def test_corrected_b_forward_audit_is_read_only_and_incomplete() -> None:
    audit = launcher.corrected_b_forward_audit_v1(REPO)
    assert audit["corrected_b_execution_entry_point_present"] is False
    assert audit["corrected_b_launcher_binding_complete"] is False
    assert audit["corrected_b_authorized"] is False
    assert audit["corrected_b_missing_execution_bindings"]


def test_historical_root_policy_is_closed_world() -> None:
    assert launcher.validate_historical_root_v1(launcher.V3_ROOT) == "HISTORICAL_V3"
    assert launcher.validate_historical_root_v1(launcher.OUTPUT_ROOT) == "FUTURE_V4"
    with pytest.raises(launcher.LauncherBindingError, match="historical_root_not_allowed"):
        launcher.validate_historical_root_v1("docs/superpowers/reports/arbitrary")


def test_approval_readiness_is_synthetic_and_inert(tmp_path: Path) -> None:
    packet = _packet()
    receipt = launcher.approval_readiness_dry_run_v1(REPO, packet, tmp_path)
    assert receipt["approval_dry_run_result"] == "READY"
    assert receipt["execution_entry_dry_run"] == "PASS"
    assert receipt["signed_approval"] == "ABSENT"
    assert receipt["single_use_nonce"] == "ABSENT"
    assert set(receipt["external_actions"].values()) == {0}


def test_real_entry_is_dormant_without_external_permission(tmp_path: Path) -> None:
    packet = _packet()
    signed = _signed(packet)
    with pytest.raises(launcher.LauncherBindingError, match="sealed_signed_approval_missing"):
        asyncio.run(launcher.execute_authorized_once_v4(
            repo_root=REPO,
            packet=packet,
            signed_approval=signed,
            permission_receipt=None,
            route_database=tmp_path / "never-read.db",
            run_root=tmp_path / "never-created",
            phase_b_receipt=launcher.synthetic_phase_b_receipt_v4(packet, signed),
        ))
    assert not (tmp_path / "never-created").exists()
