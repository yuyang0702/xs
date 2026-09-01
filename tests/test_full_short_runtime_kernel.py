from __future__ import annotations

import json
import importlib
from pathlib import Path

import pytest

from novel_flywheel.full_short_runtime_kernel import (
    DEFAULT_FAULT_INJECTION_REGISTRY_V1,
    DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
    DeterministicFaultInjectorV1,
    DurableExecutionJournalV1,
    PredispatchReadinessV1,
    ExecutionState,
    FailureClassification,
    FullShortBoundaryFailureV1,
    FullShortExecutionKernel,
    RecoveryDecisionInputV1,
    RecoveryDecisionKind,
    RecoveryDecisionEngineV1,
    RestartDecisionKind,
    RestartPolicyRegistryV1,
    RegisteredBoundaryFailureV1,
    fault_case_keys_v1,
)


def _journal(tmp_path: Path, name: str = "journal.json") -> DurableExecutionJournalV1:
    return DurableExecutionJournalV1.create(
        tmp_path / name,
        execution_id="offline-execution",
        initial_state=ExecutionState.TEMPLATE_READY,
    )


def test_registry_is_closed_and_fault_coverage_is_mechanical() -> None:
    registry = DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1
    expected = {
        (boundary.boundary_id, failure_id)
        for boundary in registry.boundaries
        for failure_id in boundary.allowed_typed_failures
    } | {
        (boundary.boundary_id, "__unexpected__")
        for boundary in registry.boundaries
    }

    assert set(fault_case_keys_v1(registry)) == expected
    assert registry.boundary_without_unexpected_handler_count == 0
    assert registry.registered_failure_without_executable_test_count == 0
    assert registry.boundary_without_unexpected_exception_test_count == 0
    assert {
        case.case_key for case in DEFAULT_FAULT_INJECTION_REGISTRY_V1.cases
    } == {
        f"{boundary_id}|{failure_id}"
        for boundary_id, failure_id in expected
    }


def test_every_registry_entry_resolves_to_matching_production_wrapper() -> None:
    for boundary in DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.boundaries:
        module_name, qualname = boundary.entry_function.split(":", 1)
        value = importlib.import_module(module_name)
        for part in qualname.split("."):
            value = getattr(value, part)
        assert getattr(value, "__full_short_boundary_id__", None) == (
            boundary.boundary_id
        ), boundary.entry_function


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault_case",
    DEFAULT_FAULT_INJECTION_REGISTRY_V1.cases,
    ids=lambda item: item.case_key,
)
async def test_registry_generated_fault_campaign_executes_kernel_path(
    tmp_path: Path,
    fault_case,
) -> None:
    journal = _journal(
        tmp_path,
        fault_case.injection_id.replace(".", "-").replace(":", "-") + ".json",
    )
    injector = DeterministicFaultInjectorV1(fault_case)
    kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=journal,
        fault_injector=injector,
    )
    operation_called = False

    async def must_not_run() -> None:
        nonlocal operation_called
        operation_called = True

    with pytest.raises(FullShortBoundaryFailureV1) as caught:
        await kernel.execute_boundary(fault_case.boundary_id, must_not_run)

    assert operation_called is False
    assert injector.trigger_count == 1
    expected_code = (
        "internal.unexpected_at_boundary"
        if fault_case.failure_id == "__unexpected__"
        else DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.failure(
            fault_case.failure_id
        ).failure_code
    )
    assert caught.value.envelope.failure_code == expected_code
    reopened = DurableExecutionJournalV1.open(journal.path)
    triggered = [
        item for item in reopened.audit_receipts
        if item.receipt_kind == "fault_injection_triggered"
    ]
    assert len(triggered) == 1
    assert triggered[0].boundary_id == fault_case.boundary_id
    assert reopened.failure_receipts[-1].failure_envelope_sha256 == (
        caught.value.envelope.failure_envelope_sha256
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary_id",
    [
        item.boundary_id
        for item in DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.boundaries
    ],
)
async def test_every_boundary_maps_unexpected_to_durable_fail_closed(
    tmp_path: Path,
    boundary_id: str,
) -> None:
    sentinel = "sk-test-secret-DO-NOT-PERSIST"
    journal = _journal(tmp_path, boundary_id.replace(".", "-") + ".json")
    kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=journal,
    )

    async def fail() -> None:
        raise RuntimeError(f"HTTP 504 credential business incomplete {sentinel}")

    with pytest.raises(FullShortBoundaryFailureV1) as caught:
        await kernel.execute_boundary(boundary_id, fail)

    envelope = caught.value.envelope
    assert envelope.boundary_id == boundary_id
    assert envelope.classification == FailureClassification.UNEXPECTED
    assert envelope.failure_code == "internal.unexpected_at_boundary"
    assert envelope.failure_family == "internal.unexpected"
    assert envelope.source_exception_class == "RuntimeError"
    assert envelope.recovery_decision == RecoveryDecisionKind.FAIL_CLOSED
    assert envelope.raw_content_persisted is False
    assert len(envelope.failure_envelope_sha256) == 64

    reopened = DurableExecutionJournalV1.open(journal.path)
    assert reopened.state == ExecutionState.TERMINAL_FAILED
    assert reopened.failure_receipts[-1].failure_envelope_sha256 == (
        envelope.failure_envelope_sha256
    )
    assert sentinel.encode("utf-8") not in journal.path.read_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("boundary_id", "failure_id"),
    [
        (boundary.boundary_id, failure_id)
        for boundary in DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.boundaries
        for failure_id in boundary.allowed_typed_failures
    ],
)
async def test_every_registered_failure_has_executable_boundary_evidence(
    tmp_path: Path,
    boundary_id: str,
    failure_id: str,
) -> None:
    journal = _journal(
        tmp_path,
        (boundary_id + "-" + failure_id).replace(".", "-") + ".json",
    )
    kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=journal,
    )

    async def fail() -> None:
        raise RegisteredBoundaryFailureV1(
            boundary_id=boundary_id,
            failure_id=failure_id,
        )

    with pytest.raises(FullShortBoundaryFailureV1) as caught:
        await kernel.execute_boundary(boundary_id, fail)

    spec = DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.failure(failure_id)
    envelope = caught.value.envelope
    assert envelope.classification == FailureClassification.KNOWN
    assert envelope.failure_code == spec.failure_code
    assert envelope.failure_family == spec.failure_family
    assert envelope.recovery_decision == spec.recovery_decision
    assert envelope.restart_policy_id == spec.restart_policy_id
    assert envelope.authority_effect == spec.authority_effect

    reopened = DurableExecutionJournalV1.open(journal.path)
    assert reopened.failure_receipts[-1].boundary_id == boundary_id
    assert reopened.failure_receipts[-1].failure_envelope_sha256 == (
        envelope.failure_envelope_sha256
    )


def test_journal_rejects_illegal_transition_and_hash_tamper(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.transition(
        ExecutionState.AUTHORIZED,
        transition_id="authorize",
        boundary_id="FS.CONTROL.PREFLIGHT",
    )
    with pytest.raises(ValueError, match="illegal_execution_transition"):
        journal.transition(
            ExecutionState.DISPATCHING,
            transition_id="skip-readiness",
            boundary_id="FS.DISPATCH.MODEL",
        )

    payload = json.loads(journal.path.read_text(encoding="utf-8"))
    payload["transitions"][0]["transition_id"] = "tampered"
    journal.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="journal_hash_chain_invalid"):
        DurableExecutionJournalV1.open(journal.path)


def test_recovery_engine_uses_one_shared_second_physical_slot() -> None:
    engine = RecoveryDecisionEngineV1(
        DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
    )
    first = engine.decide(RecoveryDecisionInputV1(
        boundary_id="FS.STAGE.PLANNING",
        failure_id="planning.business_incomplete",
        logical_stage_id="planning:1",
        physical_attempts_consumed=1,
        slot_2_owner=None,
        capture_state="complete_valid",
        exact_replay_consumed=True,
        authority_matches=True,
    ))
    assert first.decision == RecoveryDecisionKind.ONE_TYPED_REATTEMPT
    assert first.slot_2_owner == "planning.business_incomplete"

    second = engine.decide(RecoveryDecisionInputV1(
        boundary_id="FS.STAGE.PLANNING",
        failure_id="planning.reasoning_only_no_final",
        logical_stage_id="planning:1",
        physical_attempts_consumed=2,
        slot_2_owner=first.slot_2_owner,
        capture_state="complete_valid",
        exact_replay_consumed=True,
        authority_matches=True,
    ))
    assert second.decision == RecoveryDecisionKind.FAIL_CLOSED
    assert second.physical_attempt_delta == 0


def test_recovery_engine_never_guesses_unknown_or_ambiguous_completion() -> None:
    engine = RecoveryDecisionEngineV1(
        DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
    )
    unexpected = engine.decide(RecoveryDecisionInputV1(
        boundary_id="FS.STAGE.DRAFT",
        failure_id="internal.unexpected_at_boundary",
        logical_stage_id="draft:1",
        physical_attempts_consumed=1,
        slot_2_owner=None,
        capture_state="none",
        exact_replay_consumed=False,
        authority_matches=True,
    ))
    assert unexpected.decision == RecoveryDecisionKind.FAIL_CLOSED

    ambiguous = engine.decide(RecoveryDecisionInputV1(
        boundary_id="FS.DISPATCH.MODEL",
        failure_id="provider.transport_ambiguous",
        logical_stage_id="draft:1",
        physical_attempts_consumed=1,
        slot_2_owner=None,
        capture_state="ambiguous",
        exact_replay_consumed=False,
        authority_matches=True,
    ))
    assert ambiguous.decision == RecoveryDecisionKind.PAUSE_RECONCILIATION
    assert ambiguous.physical_attempt_delta == 0


def test_predispatch_readiness_precedes_unique_attempt_token(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.transition(
        ExecutionState.AUTHORIZED,
        transition_id="authorized",
        boundary_id="FS.CONTROL.PREFLIGHT",
    )
    journal.transition(
        ExecutionState.APPROVED,
        transition_id="approved",
        boundary_id="FS.CONTROL.PREFLIGHT",
    )
    readiness = PredispatchReadinessV1(
        route_configured=True,
        provider_configured=True,
        model_configured=True,
        endpoint_configured=True,
        capability_sealed=True,
        credential_source_configured=True,
        authorized_credential_readiness=True,
        network_free_request_constructable=True,
        reasoning_policy_projected=True,
        request_bytes_sha256="a" * 64,
        route_policy_sha256="b" * 64,
    )
    kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=journal,
    )

    kernel.mark_predispatch_ready(readiness)
    token = kernel.reserve_dispatch_token(
        logical_stage_id="planning:1",
        physical_attempt=1,
    )

    assert journal.state == ExecutionState.DISPATCH_TOKEN_RESERVED
    assert len(token.token_sha256) == 64
    assert token.raw_token_persisted is False
    reopened = DurableExecutionJournalV1.open(journal.path)
    assert len(reopened.dispatch_token_receipts) == 1
    assert reopened.dispatch_token_receipts[0].dispatch_token_sha256 == (
        token.token_sha256
    )
    with pytest.raises(ValueError, match="dispatch_token_attempt_already_reserved"):
        # Durable receipt, not process memory, owns uniqueness.
        FullShortExecutionKernel(
            registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
            journal=reopened,
        ).reserve_dispatch_token(
            logical_stage_id="planning:1",
            physical_attempt=1,
        )


def test_nonce_cannot_be_reserved_before_predispatch_ready(tmp_path: Path) -> None:
    kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=_journal(tmp_path),
    )
    with pytest.raises(ValueError, match="predispatch_readiness_required"):
        kernel.reserve_dispatch_token(
            logical_stage_id="planning:1",
            physical_attempt=1,
        )
    assert kernel.journal.dispatch_token_receipts == []


def test_restart_policy_is_explicit_for_every_durable_state() -> None:
    registry = RestartPolicyRegistryV1.default()
    assert set(registry.policies) == set(ExecutionState)
    assert registry.state_without_explicit_policy_count == 0
    assert registry.policies[ExecutionState.DISPATCHING].decision == (
        RestartDecisionKind.PAUSE_RECONCILIATION
    )
    assert registry.policies[ExecutionState.RESPONSE_CAPTURED].decision == (
        RestartDecisionKind.LOCAL_REPLAY_ONLY
    )
    assert registry.policies[ExecutionState.COMPLETED].decision == (
        RestartDecisionKind.RETURN_COMPLETED
    )
