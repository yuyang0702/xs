from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from tools.canary import skill_v3_character_heavy_pilot as pilot


ROOT = Path(__file__).resolve().parents[2]


def test_sealed_inputs_and_reconstruction_are_exact() -> None:
    sealed = pilot.load_sealed_pilot(ROOT)
    assert sealed["status"] == "EXACT"
    assert [row["sample_slot"] for row in sealed["locks"]] == list(pilot.SEQUENCE)
    reconstructed = [pilot.reconstruct_sample_input(ROOT, row["sample_id"]) for row in sealed["locks"]]
    assert len({item.non_skill_snapshot_sha256 for item in reconstructed}) == 1
    assert len({item.non_skill_prefix_sha256 for item in reconstructed}) == 1
    assert {item.arm for item in reconstructed} == {"A", "B"}
    assert all(not item.advisory_truncation_occurred for item in reconstructed)
    assert all(not item.advisory_shedding_occurred for item in reconstructed)


def test_caller_cannot_override_frozen_input_or_policy() -> None:
    signature = pilot.execution_entry_contract(ROOT)
    assert signature["caller_override_fields"] == []
    assert all(signature["protections"].values())


@pytest.mark.parametrize("case", pilot.NEGATIVE_EXECUTION_CASES)
def test_negative_execution_boundary_matrix(case: str, tmp_path: Path) -> None:
    result = pilot.run_negative_case(ROOT, case, tmp_path)
    assert result["status"] == "REJECTED"
    assert result["reason_code"] == case
    assert result["real_boundary_reached"] == 0


def test_fake_success_executes_each_sample_independently(tmp_path: Path) -> None:
    rows = pilot.run_six_sample_fake_execution(ROOT, tmp_path)
    assert [row["sample_slot"] for row in rows] == list(pilot.SEQUENCE)
    assert all(row["status"] == "SEALED_VALID" for row in rows)
    assert all(row["attempts"] == {
        "logical_model_call_count": 1,
        "provider_dispatch_attempt_count": 1,
        "http_post_attempt_count": 1,
        "network_request_attempt_count": 1,
    } for row in rows)
    assert sum(row["real_boundary_reached"] for row in rows) == 0


def test_failure_after_dispatch_never_retries(tmp_path: Path) -> None:
    ledger = pilot.FakePilotLedger()
    sample = pilot.load_sealed_pilot(ROOT)["locks"][0]
    dispatcher = pilot.FakeDispatcher("TRANSPORT_ERROR_BEFORE_RESPONSE")
    with pytest.raises(pilot.PilotBoundaryError) as caught:
        asyncio.run(pilot.launch_one_sealed_sample(
            repo_root=ROOT,
            pilot_id=pilot.PILOT_ID,
            sample_id=sample["sample_id"],
            expected_sample_lock_sha256=sample["sample_lock_sha256"],
            expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
            permission=pilot.fake_permission(sample),
            signed_approval=pilot.fake_signed_approval(sample),
            nonce_store=pilot.FakeNonceStore(),
            ledger=ledger,
            dispatcher=dispatcher,
            output_root=tmp_path / "one",
            offline_fake=True,
        ))
    assert caught.value.reason_code == "PROVIDER_BOUNDARY_FAILED"
    assert dispatcher.attempts == 1
    assert ledger.sample_states[sample["sample_id"]] == "PROVIDER_BOUNDARY_FAILED"


def test_ordinary_runtime_does_not_reference_pilot_entry() -> None:
    pilot_source = "skill_v3_character_heavy_pilot"
    for relative in ("src/novel_flywheel/workflows.py", "src/novel_flywheel/api.py"):
        path = ROOT / relative
        if path.is_file():
            assert pilot_source not in path.read_text(encoding="utf-8")


def test_single_dispatch_policy_is_pilot_scoped() -> None:
    binding = pilot.single_dispatch_guard_binding(ROOT)
    assert binding["status"] == "PASS"
    assert binding["implicit_gateway_transport_retry_disabled_for_pilot"] is True
    assert binding["ordinary_runtime_generic_retry_behavior_changed"] is False
    assert binding["hard_caps"] == {
        "logical_model_calls": 1,
        "provider_dispatch_attempts": 1,
        "http_post_attempts": 1,
        "network_request_attempts": 1,
    }


def test_stale_sample_lock_fails_before_nonce(tmp_path: Path) -> None:
    sample = deepcopy(pilot.load_sealed_pilot(ROOT)["locks"][0])
    nonce = pilot.FakeNonceStore()
    with pytest.raises(pilot.PilotBoundaryError) as caught:
        asyncio.run(pilot.launch_one_sealed_sample(
            repo_root=ROOT,
            pilot_id=pilot.PILOT_ID,
            sample_id=sample["sample_id"],
            expected_sample_lock_sha256="0" * 64,
            expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
            permission=pilot.fake_permission(sample),
            signed_approval=pilot.fake_signed_approval(sample),
            nonce_store=nonce,
            ledger=pilot.FakePilotLedger(),
            dispatcher=pilot.FakeDispatcher("SUCCESS"),
            output_root=tmp_path / "stale",
            offline_fake=True,
        ))
    assert caught.value.reason_code == "STALE_SAMPLE_LOCK"
    assert nonce.reservation_count == 0
