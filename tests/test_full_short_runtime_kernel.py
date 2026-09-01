from __future__ import annotations

import json
import importlib
import inspect
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
    FullShortRestartReconcilerV1,
    RecoveryDecisionInputV1,
    RecoveryDecisionKind,
    RecoveryDecisionEngineV1,
    RestartDecisionKind,
    RestartPolicyRegistryV1,
    RegisteredBoundaryFailureV1,
    activate_full_short_kernel_v1,
    fault_case_keys_v1,
)
from novel_flywheel.project_transactions import (
    write_full_short_formal_artifacts_v1,
)
from novel_flywheel.models import (
    ReasoningOnlyFinalArtifactUnavailableError,
)
from novel_flywheel.completion_supervisor import classify_completion_failure
from novel_flywheel.execution_failure_architecture import (
    build_durable_failure_evidence,
)
from novel_flywheel.recovery_engine import FailureClass


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
    boundary = DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.boundary(
        fault_case.boundary_id
    )
    module_name, qualname = boundary.entry_function.split(":", 1)
    production_entry = importlib.import_module(module_name)
    for part in qualname.split("."):
        production_entry = getattr(production_entry, part)
    assert getattr(production_entry, "__full_short_boundary_id__", None) == (
        fault_case.boundary_id
    )

    with pytest.raises(FullShortBoundaryFailureV1) as caught:
        with activate_full_short_kernel_v1(kernel):
            if inspect.iscoroutinefunction(production_entry):
                await production_entry()
            else:
                production_entry()

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
    journal = DurableExecutionJournalV1.create(
        tmp_path / (boundary_id.replace(".", "-") + ".json"),
        execution_id="offline-execution",
        initial_state=(
            ExecutionState.STAGE_ACCEPTED
            if boundary_id in {
                "FS.AUTHORITY.PROMOTE", "FS.TERMINAL.VERIFY_COMMIT",
            }
            else ExecutionState.TEMPLATE_READY
        ),
    )
    if boundary_id == "FS.AUTHORITY.PROMOTE":
        for stage_boundary in (
            "FS.STAGE.PLANNING", "FS.STAGE.DRAFT", "FS.STAGE.REVIEW",
            "FS.STAGE.READER_REVIEW", "FS.STAGE.POLISH",
            "FS.STAGE.FINAL_REVIEW", "FS.STAGE.MAINTENANCE",
        ):
            journal.append_audit(
                receipt_kind="boundary_success",
                boundary_id=stage_boundary,
                payload={"accepted": True},
            )
    elif boundary_id == "FS.TERMINAL.VERIFY_COMMIT":
        journal.append_audit(
            receipt_kind="authority_gate_ready",
            boundary_id="FS.AUTHORITY.PROMOTE",
            payload={"accepted": True},
        )
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
async def test_dispatch_reasoning_only_is_known_durable_recoverable(
    tmp_path: Path,
) -> None:
    journal = DurableExecutionJournalV1.create(
        tmp_path / "reasoning-only.json",
        execution_id="offline-execution",
        initial_state=ExecutionState.RESPONSE_CAPTURED,
    )
    kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=journal,
    )
    source = ReasoningOnlyFinalArtifactUnavailableError(receipt={
        "failure_code": "reasoning_only_final_artifact_unavailable",
        "provider_call_executed": True,
    })

    async def fail() -> None:
        raise source

    with pytest.raises(FullShortBoundaryFailureV1) as caught:
        await kernel.execute_boundary("FS.DISPATCH.MODEL", fail)

    assert caught.value.envelope.classification == FailureClassification.KNOWN
    assert caught.value.envelope.failure_code == (
        "planning.reasoning_only_no_final"
    )
    assert caught.value.envelope.source_exception_class == (
        "ReasoningOnlyFinalArtifactUnavailableError"
    )
    assert caught.value.source_exception is source
    assert caught.value.failure_code == (
        "reasoning_only_final_artifact_unavailable"
    )
    assert caught.value.receipt["provider_call_executed"] is True
    reopened = DurableExecutionJournalV1.open(journal.path)
    assert reopened.state == ExecutionState.STAGE_REJECTED_RECOVERABLE
    assert len(reopened.failure_receipts) == 1
    assert reopened.failure_receipts[0].failure_envelope == (
        caught.value.envelope
    )
    restarted_kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=reopened,
    )
    assert restarted_kernel.recoverable_failure_already_recorded(
        boundary_id="FS.DISPATCH.MODEL",
        failure_code="planning.reasoning_only_no_final",
    )
    assert classify_completion_failure(caught.value) == (
        FailureClass.OUTPUT_TRUNCATION
    )
    evidence = build_durable_failure_evidence(
        caught.value,
        boundary="full_short.kernel",
    )
    assert evidence.root.code == (
        "reasoning_only_final_artifact_unavailable"
    )
    assert evidence.root.children[0].code == (
        "reasoning_only_final_artifact_unavailable"
    )
    assert evidence.root.children[0].source_exception_class == (
        "ReasoningOnlyFinalArtifactUnavailableError"
    )


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
    journal = DurableExecutionJournalV1.create(
        tmp_path / (
            (boundary_id + "-" + failure_id).replace(".", "-") + ".json"
        ),
        execution_id="offline-execution",
        initial_state=(
            ExecutionState.STAGE_ACCEPTED
            if boundary_id in {
                "FS.AUTHORITY.PROMOTE", "FS.TERMINAL.VERIFY_COMMIT",
            }
            else ExecutionState.TEMPLATE_READY
        ),
    )
    if boundary_id == "FS.AUTHORITY.PROMOTE":
        for stage_boundary in (
            "FS.STAGE.PLANNING", "FS.STAGE.DRAFT", "FS.STAGE.REVIEW",
            "FS.STAGE.READER_REVIEW", "FS.STAGE.POLISH",
            "FS.STAGE.FINAL_REVIEW", "FS.STAGE.MAINTENANCE",
        ):
            journal.append_audit(
                receipt_kind="boundary_success",
                boundary_id=stage_boundary,
                payload={"accepted": True},
            )
    elif boundary_id == "FS.TERMINAL.VERIFY_COMMIT":
        journal.append_audit(
            receipt_kind="authority_gate_ready",
            boundary_id="FS.AUTHORITY.PROMOTE",
            payload={"accepted": True},
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
        physical_attempt_id="physical-1",
        request_bytes_sha256="a" * 64,
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
            physical_attempt_id="physical-1",
            request_bytes_sha256="a" * 64,
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
            physical_attempt_id="physical-1",
            request_bytes_sha256="a" * 64,
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


def _accepted_kernel_with_stage_audits(
    tmp_path: Path,
) -> FullShortExecutionKernel:
    journal = DurableExecutionJournalV1.create(
        tmp_path / "authority-journal.json",
        execution_id="authority-test",
        initial_state=ExecutionState.STAGE_ACCEPTED,
    )
    for boundary_id in (
        "FS.STAGE.PLANNING",
        "FS.STAGE.DRAFT",
        "FS.STAGE.REVIEW",
        "FS.STAGE.READER_REVIEW",
        "FS.STAGE.POLISH",
        "FS.STAGE.FINAL_REVIEW",
        "FS.STAGE.MAINTENANCE",
    ):
        journal.append_audit(
            receipt_kind="boundary_success",
            boundary_id=boundary_id,
            payload={"accepted": True},
        )
    return FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=journal,
    )


def test_authority_gate_rejects_before_any_formal_write(
    tmp_path: Path,
) -> None:
    journal = DurableExecutionJournalV1.create(
        tmp_path / "missing-stage-journal.json",
        execution_id="missing-stage-authority",
        initial_state=ExecutionState.STAGE_ACCEPTED,
    )
    kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=journal,
    )
    target = tmp_path / "formal.md"

    with activate_full_short_kernel_v1(kernel):
        with pytest.raises(FullShortBoundaryFailureV1) as rejected:
            write_full_short_formal_artifacts_v1(((target, "never-write"),))

    assert rejected.value.envelope.failure_code == (
        "authority.prerequisite_missing"
    )
    assert target.exists() is False
    assert journal.state == ExecutionState.TERMINAL_FAILED


def test_authority_gate_receipt_precedes_exact_formal_artifact_set(
    tmp_path: Path,
) -> None:
    kernel = _accepted_kernel_with_stage_audits(tmp_path)
    targets = (
        (tmp_path / "formal.md", "formal\ntext"),
        (tmp_path / "chapter.md", "chapter\ntext"),
        (tmp_path / "canon.json", '{"facts":[]}'),
    )

    with activate_full_short_kernel_v1(kernel):
        write_full_short_formal_artifacts_v1(targets)

    assert [path.read_text(encoding="utf-8") for path, _ in targets] == [
        content for _path, content in targets
    ]
    ready = [
        item for item in kernel.journal.audit_receipts
        if item.receipt_kind == "authority_gate_ready"
    ]
    success = [
        item for item in kernel.journal.audit_receipts
        if item.receipt_kind == "boundary_success"
        and item.boundary_id == "FS.AUTHORITY.PROMOTE"
    ]
    assert len(ready) == len(success) == 1
    assert ready[0].sequence < success[0].sequence


@pytest.mark.parametrize("state", tuple(ExecutionState))
def test_restart_reconciler_executes_policy_for_every_durable_state(
    tmp_path: Path,
    state: ExecutionState,
) -> None:
    journal = DurableExecutionJournalV1.create(
        tmp_path / f"restart-{state.value}.json",
        execution_id=f"restart-{state.value}",
        initial_state=state,
    )
    before = DurableExecutionJournalV1.open(journal.path)
    result = FullShortRestartReconcilerV1().reconcile(journal.path)
    reopened = DurableExecutionJournalV1.open(journal.path)

    assert result.state_before == state
    assert len(result.journal_head_sha256) == 64
    assert result.authority_mutation_allowed is False
    assert reopened.dispatch_token_receipts == before.dispatch_token_receipts
    assert reopened.audit_receipts == before.audit_receipts
    assert sum(
        item.to_state == ExecutionState.STAGE_ACCEPTED
        for item in reopened.transitions
    ) == 0
    assert sum(
        item.boundary_id == "FS.AUTHORITY.PROMOTE"
        for item in reopened.audit_receipts
    ) == 0
    if state in {
        ExecutionState.DISPATCH_TOKEN_RESERVED,
        ExecutionState.DISPATCHING,
    }:
        assert result.state_after == ExecutionState.PAUSED_RECONCILIATION
        assert result.provider_redispatch_allowed is False
    else:
        assert result.state_after == state
    assert result.provider_redispatch_allowed is (
        state == ExecutionState.PREDISPATCH_READY
    )

    stable_head = reopened.head_sha256
    repeated = FullShortRestartReconcilerV1().reconcile(journal.path)
    assert repeated.state_after == reopened.state
    assert repeated.journal_head_sha256 == stable_head
    assert DurableExecutionJournalV1.open(journal.path).head_sha256 == stable_head


def test_paused_reconciliation_requires_typed_resolution_without_dispatch(
    tmp_path: Path,
) -> None:
    journal = DurableExecutionJournalV1.create(
        tmp_path / "paused.json",
        execution_id="paused",
        initial_state=ExecutionState.PAUSED_RECONCILIATION,
    )
    unchanged = FullShortRestartReconcilerV1().reconcile(journal.path)
    assert unchanged.state_after == ExecutionState.PAUSED_RECONCILIATION
    captured = FullShortRestartReconcilerV1().reconcile(
        journal.path, paused_resolution="captured",
    )
    assert captured.state_after == ExecutionState.RESPONSE_CAPTURED
    assert captured.provider_redispatch_allowed is False


def test_validating_split_store_projection_is_reconciled_without_business_run(
    tmp_path: Path,
) -> None:
    journal = DurableExecutionJournalV1.create(
        tmp_path / "validating.json",
        execution_id="validating",
        initial_state=ExecutionState.VALIDATING,
    )
    kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=journal,
    )
    kernel.reconcile_validating_stage_projection(
        projected_attempt_state="LOCAL_STAGE_COMPLETE",
        receipt_sha256="a" * 64,
    )
    assert DurableExecutionJournalV1.open(journal.path).state == (
        ExecutionState.STAGE_ACCEPTED
    )


@pytest.mark.asyncio
async def test_failure_receipt_and_state_use_one_atomic_persist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal(tmp_path)
    kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=journal,
    )
    original = journal._persist
    calls = 0

    def counted() -> None:
        nonlocal calls
        calls += 1
        original()

    monkeypatch.setattr(journal, "_persist", counted)

    async def fail() -> None:
        raise RuntimeError("offline deterministic fault")

    with pytest.raises(FullShortBoundaryFailureV1):
        await kernel.execute_boundary("FS.STAGE.DRAFT", fail)
    assert calls == 1
    reopened = DurableExecutionJournalV1.open(journal.path)
    assert len(reopened.failure_receipts) == 1
    assert reopened.state == ExecutionState.TERMINAL_FAILED


@pytest.mark.asyncio
async def test_nested_boundaries_propagate_first_durable_root_failure_once(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    kernel = FullShortExecutionKernel(
        registry=DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
        journal=journal,
    )

    async def inner() -> None:
        raise RuntimeError("offline root fault")

    async def outer() -> None:
        await kernel.execute_boundary("FS.CONTRACT.VALIDATE", inner)

    with pytest.raises(FullShortBoundaryFailureV1) as caught:
        await kernel.execute_boundary("FS.STAGE.PLANNING", outer)

    assert caught.value.envelope.boundary_id == "FS.CONTRACT.VALIDATE"
    reopened = DurableExecutionJournalV1.open(journal.path)
    assert len(reopened.failure_receipts) == 1
    assert reopened.failure_receipts[0].failure_envelope_sha256 == (
        caught.value.envelope.failure_envelope_sha256
    )
