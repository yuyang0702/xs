from __future__ import annotations

import hashlib
import inspect
import json
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar


_T = TypeVar("_T")
_UNEXPECTED_FAILURE_ID = "internal.unexpected_at_boundary"
_AUTHORITY_REQUIRED_STAGE_BOUNDARIES = frozenset({
    "FS.STAGE.PLANNING",
    "FS.STAGE.DRAFT",
    "FS.STAGE.REVIEW",
    "FS.STAGE.READER_REVIEW",
    "FS.STAGE.POLISH",
    "FS.STAGE.FINAL_REVIEW",
    "FS.STAGE.MAINTENANCE",
})


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _canonical_json_bytes(value: object) -> bytes:
    def default(item: object) -> object:
        if is_dataclass(item) and not isinstance(item, type):
            return asdict(item)
        if isinstance(item, Path):
            return str(item)
        raise TypeError(f"not_canonical_json_serializable:{type(item).__name__}")

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=default,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


class ExecutionState(StrEnum):
    TEMPLATE_READY = "TEMPLATE_READY"
    AUTHORIZED = "AUTHORIZED"
    APPROVED = "APPROVED"
    PREDISPATCH_READY = "PREDISPATCH_READY"
    DISPATCH_TOKEN_RESERVED = "DISPATCH_TOKEN_RESERVED"
    DISPATCHING = "DISPATCHING"
    RESPONSE_CAPTURED = "RESPONSE_CAPTURED"
    VALIDATING = "VALIDATING"
    STAGE_REJECTED_RECOVERABLE = "STAGE_REJECTED_RECOVERABLE"
    STAGE_ACCEPTED = "STAGE_ACCEPTED"
    PAUSED_RECONCILIATION = "PAUSED_RECONCILIATION"
    TERMINAL_FAILED = "TERMINAL_FAILED"
    COMPLETED = "COMPLETED"


class FailureClassification(StrEnum):
    KNOWN = "KNOWN"
    UNEXPECTED = "UNEXPECTED"


class RecoveryDecisionKind(StrEnum):
    LOCAL_REPLAY = "LOCAL_REPLAY"
    ONE_TYPED_REATTEMPT = "ONE_TYPED_REATTEMPT"
    LOCAL_REPAIR = "LOCAL_REPAIR"
    FAIL_CLOSED = "FAIL_CLOSED"
    PAUSE_RECONCILIATION = "PAUSE_RECONCILIATION"


class RestartDecisionKind(StrEnum):
    START_FROM_TEMPLATE = "START_FROM_TEMPLATE"
    REVALIDATE_AUTHORIZATION = "REVALIDATE_AUTHORIZATION"
    REVALIDATE_APPROVAL = "REVALIDATE_APPROVAL"
    RESUME_PREDISPATCH = "RESUME_PREDISPATCH"
    PAUSE_RECONCILIATION = "PAUSE_RECONCILIATION"
    LOCAL_REPLAY_ONLY = "LOCAL_REPLAY_ONLY"
    RESUME_VALIDATION = "RESUME_VALIDATION"
    APPLY_CENTRAL_RECOVERY = "APPLY_CENTRAL_RECOVERY"
    RESUME_NEXT_STAGE = "RESUME_NEXT_STAGE"
    RETURN_TERMINAL_FAILURE = "RETURN_TERMINAL_FAILURE"
    RETURN_COMPLETED = "RETURN_COMPLETED"


@dataclass(frozen=True)
class PredispatchReadinessV1:
    route_configured: bool
    provider_configured: bool
    model_configured: bool
    endpoint_configured: bool
    capability_sealed: bool
    credential_source_configured: bool
    authorized_credential_readiness: bool
    network_free_request_constructable: bool
    reasoning_policy_projected: bool
    request_bytes_sha256: str
    route_policy_sha256: str

    def validate(self) -> None:
        checks = (
            self.route_configured,
            self.provider_configured,
            self.model_configured,
            self.endpoint_configured,
            self.capability_sealed,
            self.credential_source_configured,
            self.authorized_credential_readiness,
            self.network_free_request_constructable,
            self.reasoning_policy_projected,
        )
        if not all(checks):
            raise ValueError("predispatch_readiness_incomplete")
        if any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in (self.request_bytes_sha256, self.route_policy_sha256)
        ):
            raise ValueError("predispatch_identity_invalid")


@dataclass(frozen=True)
class RestartPolicyV1:
    state: ExecutionState
    decision: RestartDecisionKind
    provider_redispatch_allowed: bool


@dataclass(frozen=True)
class RestartPolicyRegistryV1:
    policies: dict[ExecutionState, RestartPolicyV1]

    @classmethod
    def default(cls) -> RestartPolicyRegistryV1:
        decisions = {
            ExecutionState.TEMPLATE_READY: RestartDecisionKind.START_FROM_TEMPLATE,
            ExecutionState.AUTHORIZED: RestartDecisionKind.REVALIDATE_AUTHORIZATION,
            ExecutionState.APPROVED: RestartDecisionKind.REVALIDATE_APPROVAL,
            ExecutionState.PREDISPATCH_READY: RestartDecisionKind.RESUME_PREDISPATCH,
            ExecutionState.DISPATCH_TOKEN_RESERVED: RestartDecisionKind.PAUSE_RECONCILIATION,
            ExecutionState.DISPATCHING: RestartDecisionKind.PAUSE_RECONCILIATION,
            ExecutionState.RESPONSE_CAPTURED: RestartDecisionKind.LOCAL_REPLAY_ONLY,
            ExecutionState.VALIDATING: RestartDecisionKind.RESUME_VALIDATION,
            ExecutionState.STAGE_REJECTED_RECOVERABLE: RestartDecisionKind.APPLY_CENTRAL_RECOVERY,
            ExecutionState.STAGE_ACCEPTED: RestartDecisionKind.RESUME_NEXT_STAGE,
            ExecutionState.PAUSED_RECONCILIATION: RestartDecisionKind.PAUSE_RECONCILIATION,
            ExecutionState.TERMINAL_FAILED: RestartDecisionKind.RETURN_TERMINAL_FAILURE,
            ExecutionState.COMPLETED: RestartDecisionKind.RETURN_COMPLETED,
        }
        policies = {
            state: RestartPolicyV1(
                state=state,
                decision=decision,
                provider_redispatch_allowed=(
                    state == ExecutionState.PREDISPATCH_READY
                ),
            )
            for state, decision in decisions.items()
        }
        return cls(policies)

    @property
    def state_without_explicit_policy_count(self) -> int:
        return len(set(ExecutionState) - set(self.policies))


@dataclass(frozen=True)
class RestartReconciliationResultV1:
    state_before: ExecutionState
    state_after: ExecutionState
    decision: RestartDecisionKind
    provider_redispatch_allowed: bool
    authority_mutation_allowed: bool
    journal_head_sha256: str


class FullShortRestartReconcilerV1:
    """Execute the closed restart policy without dispatch or authority writes."""

    def __init__(
        self,
        policies: RestartPolicyRegistryV1 | None = None,
    ) -> None:
        self.policies = policies or RestartPolicyRegistryV1.default()

    def reconcile(
        self,
        journal_path: Path,
        *,
        paused_resolution: str | None = None,
    ) -> RestartReconciliationResultV1:
        journal = DurableExecutionJournalV1.open(journal_path)
        before = journal.state
        policy = self.policies.policies[before]
        if before in {
            ExecutionState.DISPATCH_TOKEN_RESERVED,
            ExecutionState.DISPATCHING,
        }:
            journal.transition(
                ExecutionState.PAUSED_RECONCILIATION,
                transition_id="restart-ambiguous-dispatch-pause",
                boundary_id="FS.RECOVERY.DECIDE",
            )
        elif before == ExecutionState.PAUSED_RECONCILIATION:
            if paused_resolution == "captured":
                journal.transition(
                    ExecutionState.RESPONSE_CAPTURED,
                    transition_id="reconciliation-capture-proven",
                    boundary_id="FS.RECOVERY.DECIDE",
                )
            elif paused_resolution == "terminal_failed":
                journal.transition(
                    ExecutionState.TERMINAL_FAILED,
                    transition_id="reconciliation-terminal-failure",
                    boundary_id="FS.RECOVERY.DECIDE",
                )
            elif paused_resolution is not None:
                raise ValueError("restart_resolution_invalid")
        reopened = DurableExecutionJournalV1.open(journal_path)
        return RestartReconciliationResultV1(
            state_before=before,
            state_after=reopened.state,
            decision=policy.decision,
            provider_redispatch_allowed=policy.provider_redispatch_allowed,
            authority_mutation_allowed=False,
            journal_head_sha256=reopened.head_sha256,
        )


@dataclass(frozen=True)
class FailureSpecV1:
    failure_id: str
    failure_code: str
    failure_family: str
    recovery_decision: RecoveryDecisionKind
    restart_policy_id: str
    authority_effect: str = "preserve_last_accepted"


@dataclass(frozen=True)
class BoundarySpecV1:
    boundary_id: str
    owner_layer: str
    entry_function: str
    allowed_success_outcome: str
    allowed_typed_failures: tuple[str, ...]
    unexpected_exception_policy: str = _UNEXPECTED_FAILURE_ID
    durable_receipt_type: str = "FailureEnvelopeV1"
    recovery_policy_id: str = "central.recovery.v1"
    restart_policy_id: str = "journal.reconcile.v1"
    authority_effect: str = "none_until_accepted_receipt"
    fault_injection_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class FailureBoundaryRegistryV1:
    boundaries: tuple[BoundarySpecV1, ...]
    failures: tuple[FailureSpecV1, ...]
    schema_version: str = "FailureBoundaryRegistryV1"
    _boundary_by_id: dict[str, BoundarySpecV1] = field(init=False, repr=False)
    _failure_by_id: dict[str, FailureSpecV1] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        boundary_by_id = {item.boundary_id: item for item in self.boundaries}
        failure_by_id = {item.failure_id: item for item in self.failures}
        if len(boundary_by_id) != len(self.boundaries):
            raise ValueError("duplicate_boundary_id")
        if len(failure_by_id) != len(self.failures):
            raise ValueError("duplicate_failure_id")
        if _UNEXPECTED_FAILURE_ID in failure_by_id:
            raise ValueError("unexpected_failure_must_not_be_registered_as_known")
        for boundary in self.boundaries:
            if boundary.unexpected_exception_policy != _UNEXPECTED_FAILURE_ID:
                raise ValueError("boundary_without_unexpected_handler")
            if not boundary.fault_injection_ids:
                raise ValueError("boundary_without_fault_injection")
            if len(set(boundary.fault_injection_ids)) != len(
                boundary.fault_injection_ids
            ):
                raise ValueError("duplicate_fault_injection_id")
            unknown = set(boundary.allowed_typed_failures) - set(failure_by_id)
            if unknown:
                raise ValueError("boundary_references_unknown_failure")
            expected_injections = {
                f"{boundary.boundary_id}:{failure_id}"
                for failure_id in boundary.allowed_typed_failures
            } | {f"{boundary.boundary_id}:__unexpected__"}
            if set(boundary.fault_injection_ids) != expected_injections:
                raise ValueError("fault_injection_registry_not_mechanical")
        object.__setattr__(self, "_boundary_by_id", boundary_by_id)
        object.__setattr__(self, "_failure_by_id", failure_by_id)

    def boundary(self, boundary_id: str) -> BoundarySpecV1:
        try:
            return self._boundary_by_id[boundary_id]
        except KeyError as exc:
            raise ValueError("unregistered_boundary") from exc

    def failure(self, failure_id: str) -> FailureSpecV1:
        try:
            return self._failure_by_id[failure_id]
        except KeyError as exc:
            raise ValueError("unregistered_failure") from exc

    @property
    def boundary_without_unexpected_handler_count(self) -> int:
        return sum(
            item.unexpected_exception_policy != _UNEXPECTED_FAILURE_ID
            for item in self.boundaries
        )

    @property
    def registered_failure_without_executable_test_count(self) -> int:
        covered = {
            failure_id
            for boundary in self.boundaries
            for failure_id in boundary.allowed_typed_failures
            if f"{boundary.boundary_id}:{failure_id}"
            in boundary.fault_injection_ids
        }
        return len(set(self._failure_by_id) - covered)

    @property
    def boundary_without_unexpected_exception_test_count(self) -> int:
        return sum(
            f"{item.boundary_id}:__unexpected__" not in item.fault_injection_ids
            for item in self.boundaries
        )

    @property
    def identity_sha256(self) -> str:
        return _sha256({
            "schema_version": self.schema_version,
            "boundaries": [asdict(item) for item in self.boundaries],
            "failures": [asdict(item) for item in self.failures],
        })


def _fault_ids(boundary_id: str, failures: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        [f"{boundary_id}:{failure_id}" for failure_id in failures]
        + [f"{boundary_id}:__unexpected__"]
    )


def _boundary(
    boundary_id: str,
    owner_layer: str,
    entry_function: str,
    success: str,
    *failures: str,
) -> BoundarySpecV1:
    failure_tuple = tuple(failures)
    return BoundarySpecV1(
        boundary_id=boundary_id,
        owner_layer=owner_layer,
        entry_function=entry_function,
        allowed_success_outcome=success,
        allowed_typed_failures=failure_tuple,
        fault_injection_ids=_fault_ids(boundary_id, failure_tuple),
    )


_FAILURES = (
    FailureSpecV1(
        "control.binding_mismatch", "control.binding_mismatch", "control.binding",
        RecoveryDecisionKind.FAIL_CLOSED, "restart.forbidden.v1",
    ),
    FailureSpecV1(
        "workflow.invariant_rejected", "workflow.invariant_rejected",
        "workflow.invariant", RecoveryDecisionKind.FAIL_CLOSED,
        "restart.from_last_accepted.v1",
    ),
    FailureSpecV1(
        "planning.business_incomplete", "planning.business_incomplete",
        "business.incomplete", RecoveryDecisionKind.ONE_TYPED_REATTEMPT,
        "restart.same_logical_stage.v1",
    ),
    FailureSpecV1(
        "planning.reasoning_only_no_final",
        "planning.reasoning_only_no_final", "reasoning.finalization",
        RecoveryDecisionKind.ONE_TYPED_REATTEMPT,
        "restart.same_logical_stage.v1",
    ),
    FailureSpecV1(
        "stage.semantic_repair_required", "stage.semantic_repair_required",
        "business.semantic", RecoveryDecisionKind.LOCAL_REPAIR,
        "restart.same_logical_stage.v1",
    ),
    FailureSpecV1(
        "stage.artifact_rejected", "stage.artifact_rejected", "business.artifact",
        RecoveryDecisionKind.FAIL_CLOSED, "restart.from_last_accepted.v1",
    ),
    FailureSpecV1(
        "provider.configuration_invalid", "provider.configuration_invalid",
        "provider.configuration", RecoveryDecisionKind.FAIL_CLOSED,
        "restart.after_configuration_change.v1",
    ),
    FailureSpecV1(
        "provider.credential_unavailable", "provider.credential_unavailable",
        "provider.credential", RecoveryDecisionKind.FAIL_CLOSED,
        "restart.after_credential_readiness.v1",
    ),
    FailureSpecV1(
        "provider.transport_pre_dispatch", "provider.transport_pre_dispatch",
        "provider.transport", RecoveryDecisionKind.FAIL_CLOSED,
        "restart.new_dispatch_token.v1",
    ),
    FailureSpecV1(
        "provider.transport_ambiguous", "provider.transport_ambiguous",
        "provider.transport", RecoveryDecisionKind.PAUSE_RECONCILIATION,
        "restart.reconcile_dispatch.v1",
    ),
    FailureSpecV1(
        "provider.capture_replay_available", "provider.capture_replay_available",
        "provider.capture", RecoveryDecisionKind.LOCAL_REPLAY,
        "restart.local_replay.v1",
    ),
    FailureSpecV1(
        "contract.validation_rejected", "contract.validation_rejected",
        "contract.validation", RecoveryDecisionKind.LOCAL_REPAIR,
        "restart.same_logical_stage.v1",
    ),
    FailureSpecV1(
        "checkpoint.persistence_failed", "checkpoint.persistence_failed",
        "checkpoint.persistence", RecoveryDecisionKind.PAUSE_RECONCILIATION,
        "restart.reconcile_checkpoint.v1",
    ),
    FailureSpecV1(
        "authority.stale", "authority.stale", "authority.conflict",
        RecoveryDecisionKind.PAUSE_RECONCILIATION,
        "restart.reconcile_authority.v1",
    ),
    FailureSpecV1(
        "authority.promotion_rejected", "authority.promotion_rejected",
        "authority.validation", RecoveryDecisionKind.FAIL_CLOSED,
        "restart.from_last_accepted.v1",
    ),
    FailureSpecV1(
        "authority.prerequisite_missing", "authority.prerequisite_missing",
        "authority.prerequisite", RecoveryDecisionKind.FAIL_CLOSED,
        "restart.forbidden.v1",
    ),
    FailureSpecV1(
        "terminal.binding_invalid", "terminal.binding_invalid",
        "terminal.binding", RecoveryDecisionKind.FAIL_CLOSED,
        "restart.forbidden.v1",
    ),
    FailureSpecV1(
        "recovery.budget_exhausted", "recovery.budget_exhausted",
        "recovery.budget", RecoveryDecisionKind.FAIL_CLOSED,
        "restart.forbidden.v1",
    ),
)


_BOUNDARIES = (
    _boundary(
        "FS.CONTROL.PREFLIGHT", "control", "novel_flywheel.full_short_execution:FullShortDispatchLedgerObserverV1.before_http_dispatch",
        "PREDISPATCH_READY", "control.binding_mismatch",
        "provider.configuration_invalid", "provider.credential_unavailable",
    ),
    _boundary(
        "FS.WORKFLOW.SHORT", "workflow", "novel_flywheel.workflows:WorkflowService._short_pipeline",
        "COMPLETED", "workflow.invariant_rejected", "stage.artifact_rejected",
    ),
    _boundary(
        "FS.STAGE.PLANNING", "stage", "novel_flywheel.workflows:WorkflowService._plan_short_ir_first",
        "STAGE_ACCEPTED", "planning.business_incomplete",
        "planning.reasoning_only_no_final", "contract.validation_rejected",
        "recovery.budget_exhausted",
    ),
    _boundary(
        "FS.STAGE.DRAFT", "stage", "novel_flywheel.workflows:WorkflowService._draft_short_in_segments",
        "STAGE_ACCEPTED", "stage.semantic_repair_required",
        "stage.artifact_rejected", "contract.validation_rejected",
    ),
    _boundary(
        "FS.STAGE.REVIEW", "stage", "novel_flywheel.workflows:WorkflowService._accept_short_initial_review",
        "STAGE_ACCEPTED", "stage.semantic_repair_required",
        "stage.artifact_rejected", "contract.validation_rejected",
    ),
    _boundary(
        "FS.STAGE.READER_REVIEW", "stage", "novel_flywheel.workflows:WorkflowService._reader_review",
        "STAGE_ACCEPTED", "stage.semantic_repair_required",
        "stage.artifact_rejected", "contract.validation_rejected",
    ),
    _boundary(
        "FS.STAGE.POLISH", "stage", "novel_flywheel.workflows:WorkflowService._quality_polish",
        "STAGE_ACCEPTED", "stage.semantic_repair_required",
        "stage.artifact_rejected", "contract.validation_rejected",
    ),
    _boundary(
        "FS.STAGE.FINAL_REVIEW", "stage", "novel_flywheel.workflows:WorkflowService._full_manuscript_review",
        "STAGE_ACCEPTED", "stage.artifact_rejected",
        "contract.validation_rejected",
    ),
    _boundary(
        "FS.STAGE.MAINTENANCE", "stage",
        "novel_flywheel.workflows:WorkflowService._close_short_maintenance_authority", "STAGE_ACCEPTED",
        "stage.artifact_rejected", "checkpoint.persistence_failed",
    ),
    _boundary(
        "FS.DISPATCH.MODEL", "dispatch", "novel_flywheel.contract_runtime:dispatch_explicit_model_route",
        "RESPONSE_CAPTURED", "provider.configuration_invalid",
        "provider.credential_unavailable", "provider.transport_pre_dispatch",
        "provider.transport_ambiguous", "provider.capture_replay_available",
    ),
    _boundary(
        "FS.CONTRACT.VALIDATE", "contract", "novel_flywheel.workflows:WorkflowService._stage",
        "STAGE_ACCEPTED", "contract.validation_rejected",
        "stage.artifact_rejected",
    ),
    _boundary(
        "FS.RECOVERY.DECIDE", "recovery", "novel_flywheel.execution_failure_architecture:FullShortExactRecoveryControllerV1.authorize_shared_second_slot",
        "RECOVERY_DECIDED", "recovery.budget_exhausted",
        "provider.transport_ambiguous",
    ),
    _boundary(
        "FS.CHECKPOINT.TRANSITION", "checkpoint", "novel_flywheel.full_short_execution:FullShortDurableExecutionStoreV1.prepare_predispatch_ledger",
        "CHECKPOINT_COMMITTED", "checkpoint.persistence_failed",
    ),
    _boundary(
        "FS.AUTHORITY.PROMOTE", "authority", "novel_flywheel.project_transactions:write_full_short_formal_artifacts_v1",
        "AUTHORITY_COMMITTED", "authority.stale", "authority.promotion_rejected",
        "authority.prerequisite_missing", "checkpoint.persistence_failed",
    ),
    _boundary(
        "FS.TERMINAL.VERIFY_COMMIT", "completion", "novel_flywheel.full_short_execution:FullShortDurableExecutionStoreV1.commit_completion",
        "COMPLETED", "checkpoint.persistence_failed", "authority.stale",
        "terminal.binding_invalid",
    ),
)


DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1 = FailureBoundaryRegistryV1(
    boundaries=_BOUNDARIES,
    failures=_FAILURES,
)


def fault_case_keys_v1(
    registry: FailureBoundaryRegistryV1,
) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(
        [
            (boundary.boundary_id, failure_id)
            for boundary in registry.boundaries
            for failure_id in boundary.allowed_typed_failures
        ]
        + [
            (boundary.boundary_id, "__unexpected__")
            for boundary in registry.boundaries
        ]
    ))


@dataclass(frozen=True)
class FailureCauseV1:
    ordinal: int
    relation: str
    source_exception_class: str
    safe_class_id: str
    parent_ordinal: int | None
    cause_sha256: str


def _safe_exception_class(exc: BaseException) -> str:
    cls = type(exc)
    if cls.__module__ in {"builtins", __name__}:
        return cls.__name__
    return "ExternalException"


def _cause_chain(exc: BaseException) -> tuple[FailureCauseV1, ...]:
    chain: list[FailureCauseV1] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    relation = "root"
    parent: int | None = None
    while current is not None and id(current) not in seen and len(chain) < 16:
        seen.add(id(current))
        ordinal = len(chain)
        source_class = _safe_exception_class(current)
        safe_class_id = (
            source_class
            if source_class != "ExternalException"
            else "external:" + hashlib.sha256(
                type(current).__name__.encode("utf-8", errors="replace")
            ).hexdigest()
        )
        node_without_sha = {
            "ordinal": ordinal,
            "relation": relation,
            "source_exception_class": source_class,
            "safe_class_id": safe_class_id,
            "parent_ordinal": parent,
        }
        chain.append(FailureCauseV1(
            **node_without_sha,
            cause_sha256=_sha256(node_without_sha),
        ))
        child = current.__cause__
        if child is not None:
            relation = "cause"
        else:
            child = current.__context__
            relation = "context"
        parent = ordinal
        current = child
    return tuple(chain)


@dataclass(frozen=True)
class FailureEnvelopeV1:
    boundary_id: str
    classification: FailureClassification
    failure_code: str
    failure_family: str
    source_exception_class: str
    ordered_causes: tuple[FailureCauseV1, ...]
    recovery_decision: RecoveryDecisionKind
    restart_policy_id: str
    authority_effect: str
    logical_stage_id: str | None
    physical_attempt: int
    capture_reference_sha256: str | None
    current_state: ExecutionState
    allowed_next_states: tuple[ExecutionState, ...]
    raw_content_persisted: bool
    failure_envelope_sha256: str


class RegisteredBoundaryFailureV1(Exception):
    def __init__(self, *, boundary_id: str, failure_id: str) -> None:
        super().__init__(failure_id)
        self.boundary_id = boundary_id
        self.failure_id = failure_id


class FullShortBoundaryFailureV1(Exception):
    def __init__(self, envelope: FailureEnvelopeV1) -> None:
        super().__init__(
            f"full_short_boundary_failure:{envelope.boundary_id}:"
            f"{envelope.failure_code}"
        )
        self.envelope = envelope


@dataclass(frozen=True)
class ExecutionTransitionV1:
    sequence: int
    transition_id: str
    boundary_id: str
    from_state: ExecutionState
    to_state: ExecutionState
    previous_record_sha256: str
    record_sha256: str


@dataclass(frozen=True)
class DurableFailureReceiptV1:
    sequence: int
    boundary_id: str
    failure_code: str
    failure_envelope_sha256: str
    previous_record_sha256: str
    record_sha256: str


@dataclass(frozen=True)
class DurableAuditReceiptV1:
    sequence: int
    receipt_kind: str
    boundary_id: str
    payload_sha256: str
    previous_record_sha256: str
    record_sha256: str


@dataclass(frozen=True)
class DispatchTokenReceiptV1:
    sequence: int
    logical_stage_id_sha256: str
    physical_attempt: int
    physical_attempt_id_sha256: str
    request_bytes_sha256: str
    dispatch_token_sha256: str
    previous_record_sha256: str
    record_sha256: str


@dataclass(frozen=True)
class DispatchTokenV1:
    token: str
    token_sha256: str
    logical_stage_id_sha256: str
    physical_attempt: int
    physical_attempt_id_sha256: str
    request_bytes_sha256: str
    raw_token_persisted: bool = False


_NORMAL_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.TEMPLATE_READY: frozenset({ExecutionState.AUTHORIZED}),
    ExecutionState.AUTHORIZED: frozenset({ExecutionState.APPROVED}),
    ExecutionState.APPROVED: frozenset({ExecutionState.PREDISPATCH_READY}),
    ExecutionState.PREDISPATCH_READY: frozenset({
        ExecutionState.DISPATCH_TOKEN_RESERVED,
    }),
    ExecutionState.DISPATCH_TOKEN_RESERVED: frozenset({ExecutionState.DISPATCHING}),
    ExecutionState.DISPATCHING: frozenset({ExecutionState.RESPONSE_CAPTURED}),
    ExecutionState.RESPONSE_CAPTURED: frozenset({ExecutionState.VALIDATING}),
    ExecutionState.VALIDATING: frozenset({
        ExecutionState.STAGE_REJECTED_RECOVERABLE,
        ExecutionState.STAGE_ACCEPTED,
    }),
    ExecutionState.STAGE_REJECTED_RECOVERABLE: frozenset({
        ExecutionState.PREDISPATCH_READY,
        ExecutionState.VALIDATING,
    }),
    ExecutionState.STAGE_ACCEPTED: frozenset({
        ExecutionState.PREDISPATCH_READY,
        ExecutionState.COMPLETED,
    }),
    ExecutionState.PAUSED_RECONCILIATION: frozenset({
        ExecutionState.RESPONSE_CAPTURED,
        ExecutionState.TERMINAL_FAILED,
    }),
    ExecutionState.TERMINAL_FAILED: frozenset(),
    ExecutionState.COMPLETED: frozenset(),
}


class DurableExecutionJournalV1:
    schema_version = "DurableExecutionJournalV1"

    def __init__(
        self,
        path: Path,
        *,
        execution_id: str,
        initial_state: ExecutionState,
        state: ExecutionState,
        transitions: list[ExecutionTransitionV1],
        failure_receipts: list[DurableFailureReceiptV1],
        audit_receipts: list[DurableAuditReceiptV1],
        dispatch_token_receipts: list[DispatchTokenReceiptV1],
    ) -> None:
        self.path = path
        self.execution_id = execution_id
        self.initial_state = initial_state
        self.state = state
        self.transitions = transitions
        self.failure_receipts = failure_receipts
        self.audit_receipts = audit_receipts
        self.dispatch_token_receipts = dispatch_token_receipts

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        execution_id: str,
        initial_state: ExecutionState,
    ) -> DurableExecutionJournalV1:
        if path.exists():
            raise FileExistsError("execution_journal_already_exists")
        journal = cls(
            path,
            execution_id=execution_id,
            initial_state=initial_state,
            state=initial_state,
            transitions=[],
            failure_receipts=[],
            audit_receipts=[],
            dispatch_token_receipts=[],
        )
        journal._persist()
        return journal

    @classmethod
    def open(cls, path: Path) -> DurableExecutionJournalV1:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != cls.schema_version:
            raise ValueError("journal_schema_invalid")
        journal = cls(
            path,
            execution_id=str(payload["execution_id"]),
            initial_state=ExecutionState(payload["initial_state"]),
            state=ExecutionState(payload["state"]),
            transitions=[
                ExecutionTransitionV1(
                    sequence=int(item["sequence"]),
                    transition_id=str(item["transition_id"]),
                    boundary_id=str(item["boundary_id"]),
                    from_state=ExecutionState(item["from_state"]),
                    to_state=ExecutionState(item["to_state"]),
                    previous_record_sha256=str(item["previous_record_sha256"]),
                    record_sha256=str(item["record_sha256"]),
                )
                for item in payload.get("transitions", [])
            ],
            failure_receipts=[
                DurableFailureReceiptV1(
                    sequence=int(item["sequence"]),
                    boundary_id=str(item["boundary_id"]),
                    failure_code=str(item["failure_code"]),
                    failure_envelope_sha256=str(item["failure_envelope_sha256"]),
                    previous_record_sha256=str(item["previous_record_sha256"]),
                    record_sha256=str(item["record_sha256"]),
                )
                for item in payload.get("failure_receipts", [])
            ],
            audit_receipts=[
                DurableAuditReceiptV1(
                    sequence=int(item["sequence"]),
                    receipt_kind=str(item["receipt_kind"]),
                    boundary_id=str(item["boundary_id"]),
                    payload_sha256=str(item["payload_sha256"]),
                    previous_record_sha256=str(item["previous_record_sha256"]),
                    record_sha256=str(item["record_sha256"]),
                )
                for item in payload.get("audit_receipts", [])
            ],
            dispatch_token_receipts=[
                DispatchTokenReceiptV1(
                    sequence=int(item["sequence"]),
                    logical_stage_id_sha256=str(
                        item["logical_stage_id_sha256"]
                    ),
                    physical_attempt=int(item["physical_attempt"]),
                    physical_attempt_id_sha256=str(
                        item["physical_attempt_id_sha256"]
                    ),
                    request_bytes_sha256=str(item["request_bytes_sha256"]),
                    dispatch_token_sha256=str(item["dispatch_token_sha256"]),
                    previous_record_sha256=str(item["previous_record_sha256"]),
                    record_sha256=str(item["record_sha256"]),
                )
                for item in payload.get("dispatch_token_receipts", [])
            ],
        )
        journal._verify()
        return journal

    def _genesis_hash(self) -> str:
        return _sha256({
            "schema_version": self.schema_version,
            "execution_id": self.execution_id,
            "initial_state": self.initial_state,
        })

    def _records(
        self,
    ) -> list[
        ExecutionTransitionV1 | DurableFailureReceiptV1 | DurableAuditReceiptV1
        | DispatchTokenReceiptV1
    ]:
        return sorted(
            [
                *self.transitions,
                *self.failure_receipts,
                *self.audit_receipts,
                *self.dispatch_token_receipts,
            ],
            key=lambda item: item.sequence,
        )

    def _last_hash(self) -> str:
        records = self._records()
        return records[-1].record_sha256 if records else self._genesis_hash()

    @property
    def head_sha256(self) -> str:
        return self._last_hash()

    def _next_sequence(self) -> int:
        return (
            len(self.transitions) + len(self.failure_receipts)
            + len(self.audit_receipts) + len(self.dispatch_token_receipts) + 1
        )

    def _verify(self) -> None:
        previous = self._genesis_hash()
        expected_sequence = 1
        derived_state = self.initial_state
        for record in self._records():
            if record.sequence != expected_sequence:
                raise ValueError("journal_hash_chain_invalid")
            data = asdict(record)
            actual_hash = data.pop("record_sha256")
            if data["previous_record_sha256"] != previous:
                raise ValueError("journal_hash_chain_invalid")
            if _sha256(data) != actual_hash:
                raise ValueError("journal_hash_chain_invalid")
            if isinstance(record, ExecutionTransitionV1):
                if record.from_state != derived_state:
                    raise ValueError("journal_state_projection_invalid")
                if not self._transition_allowed(record.from_state, record.to_state):
                    raise ValueError("journal_state_projection_invalid")
                derived_state = record.to_state
            previous = actual_hash
            expected_sequence += 1
        if derived_state != self.state:
            raise ValueError("journal_state_projection_invalid")

    @staticmethod
    def _transition_allowed(
        from_state: ExecutionState,
        to_state: ExecutionState,
    ) -> bool:
        if to_state in {
            ExecutionState.TERMINAL_FAILED,
            ExecutionState.PAUSED_RECONCILIATION,
            ExecutionState.STAGE_REJECTED_RECOVERABLE,
        } and from_state not in {
            ExecutionState.TERMINAL_FAILED,
            ExecutionState.COMPLETED,
        }:
            return True
        return to_state in _NORMAL_TRANSITIONS[from_state]

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "execution_id": self.execution_id,
            "initial_state": self.initial_state,
            "state": self.state,
            "transitions": [asdict(item) for item in self.transitions],
            "failure_receipts": [asdict(item) for item in self.failure_receipts],
            "audit_receipts": [asdict(item) for item in self.audit_receipts],
            "dispatch_token_receipts": [
                asdict(item) for item in self.dispatch_token_receipts
            ],
        }
        temp_path = self.path.with_name(self.path.name + ".tmp")
        with temp_path.open("wb") as handle:
            handle.write(_canonical_json_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, self.path)

    def transition(
        self,
        to_state: ExecutionState,
        *,
        transition_id: str,
        boundary_id: str,
        _persist_now: bool = True,
    ) -> ExecutionTransitionV1:
        if not self._transition_allowed(self.state, to_state):
            raise ValueError("illegal_execution_transition")
        data: dict[str, Any] = {
            "sequence": self._next_sequence(),
            "transition_id": transition_id,
            "boundary_id": boundary_id,
            "from_state": self.state,
            "to_state": to_state,
            "previous_record_sha256": self._last_hash(),
        }
        transition = ExecutionTransitionV1(
            **data,
            record_sha256=_sha256(data),
        )
        self.transitions.append(transition)
        self.state = to_state
        if _persist_now:
            self._persist()
        return transition

    def append_failure(
        self,
        envelope: FailureEnvelopeV1,
        *,
        _persist_now: bool = True,
    ) -> DurableFailureReceiptV1:
        data = {
            "sequence": self._next_sequence(),
            "boundary_id": envelope.boundary_id,
            "failure_code": envelope.failure_code,
            "failure_envelope_sha256": envelope.failure_envelope_sha256,
            "previous_record_sha256": self._last_hash(),
        }
        receipt = DurableFailureReceiptV1(
            **data,
            record_sha256=_sha256(data),
        )
        self.failure_receipts.append(receipt)
        if _persist_now:
            self._persist()
        return receipt

    def append_audit(
        self,
        *,
        receipt_kind: str,
        boundary_id: str,
        payload: object,
        _persist_now: bool = True,
    ) -> DurableAuditReceiptV1:
        data = {
            "sequence": self._next_sequence(),
            "receipt_kind": receipt_kind,
            "boundary_id": boundary_id,
            "payload_sha256": _sha256(payload),
            "previous_record_sha256": self._last_hash(),
        }
        receipt = DurableAuditReceiptV1(
            **data,
            record_sha256=_sha256(data),
        )
        self.audit_receipts.append(receipt)
        if _persist_now:
            self._persist()
        return receipt

    def reserve_dispatch_token(
        self,
        *,
        logical_stage_id: str,
        physical_attempt: int,
        physical_attempt_id: str,
        request_bytes_sha256: str,
    ) -> DispatchTokenV1:
        if physical_attempt not in {1, 2}:
            raise ValueError("physical_attempt_out_of_bounds")
        logical_stage_id_sha256 = hashlib.sha256(
            logical_stage_id.encode("utf-8", errors="replace")
        ).hexdigest()
        physical_attempt_id_sha256 = hashlib.sha256(
            physical_attempt_id.encode("utf-8", errors="replace")
        ).hexdigest()
        if not _is_sha256(request_bytes_sha256):
            raise ValueError("dispatch_request_bytes_sha256_invalid")
        if any(
            item.logical_stage_id_sha256 == logical_stage_id_sha256
            and item.physical_attempt == physical_attempt
            for item in self.dispatch_token_receipts
        ):
            raise ValueError("dispatch_token_attempt_already_reserved")
        if self.state != ExecutionState.PREDISPATCH_READY:
            raise ValueError("predispatch_readiness_required")
        token = hashlib.sha256(_canonical_json_bytes({
            "execution_id": self.execution_id,
            "logical_stage_id_sha256": logical_stage_id_sha256,
            "physical_attempt": physical_attempt,
            "physical_attempt_id_sha256": physical_attempt_id_sha256,
            "request_bytes_sha256": request_bytes_sha256,
            "previous_record_sha256": self._last_hash(),
            "unique_material": uuid.uuid4().hex,
        })).hexdigest()
        token_sha256 = hashlib.sha256(token.encode("ascii")).hexdigest()
        data = {
            "sequence": self._next_sequence(),
            "logical_stage_id_sha256": logical_stage_id_sha256,
            "physical_attempt": physical_attempt,
            "physical_attempt_id_sha256": physical_attempt_id_sha256,
            "request_bytes_sha256": request_bytes_sha256,
            "dispatch_token_sha256": token_sha256,
            "previous_record_sha256": self._last_hash(),
        }
        receipt = DispatchTokenReceiptV1(
            **data,
            record_sha256=_sha256(data),
        )
        self.dispatch_token_receipts.append(receipt)
        return DispatchTokenV1(
            token=token,
            token_sha256=token_sha256,
            logical_stage_id_sha256=logical_stage_id_sha256,
            physical_attempt=physical_attempt,
            physical_attempt_id_sha256=physical_attempt_id_sha256,
            request_bytes_sha256=request_bytes_sha256,
        )


@dataclass(frozen=True)
class RecoveryDecisionInputV1:
    boundary_id: str
    failure_id: str
    logical_stage_id: str
    physical_attempts_consumed: int
    slot_2_owner: str | None
    capture_state: str
    exact_replay_consumed: bool
    authority_matches: bool


@dataclass(frozen=True)
class RecoveryDecisionV1:
    decision: RecoveryDecisionKind
    physical_attempt_delta: int
    slot_2_owner: str | None
    policy_id: str


class RecoveryDecisionEngineV1:
    def __init__(self, registry: FailureBoundaryRegistryV1) -> None:
        self.registry = registry

    def decide(self, value: RecoveryDecisionInputV1) -> RecoveryDecisionV1:
        boundary = self.registry.boundary(value.boundary_id)
        if not value.authority_matches:
            return RecoveryDecisionV1(
                RecoveryDecisionKind.PAUSE_RECONCILIATION, 0,
                value.slot_2_owner, "authority.reconcile.v1",
            )
        if value.capture_state == "ambiguous":
            return RecoveryDecisionV1(
                RecoveryDecisionKind.PAUSE_RECONCILIATION, 0,
                value.slot_2_owner, "capture.reconcile.v1",
            )
        if value.failure_id == _UNEXPECTED_FAILURE_ID:
            return RecoveryDecisionV1(
                RecoveryDecisionKind.FAIL_CLOSED, 0,
                value.slot_2_owner, "unexpected.fail_closed.v1",
            )
        if value.failure_id not in boundary.allowed_typed_failures:
            return RecoveryDecisionV1(
                RecoveryDecisionKind.FAIL_CLOSED, 0,
                value.slot_2_owner, "unregistered.fail_closed.v1",
            )
        spec = self.registry.failure(value.failure_id)
        if spec.recovery_decision == RecoveryDecisionKind.LOCAL_REPLAY:
            if value.capture_state != "complete_valid" or value.exact_replay_consumed:
                return RecoveryDecisionV1(
                    RecoveryDecisionKind.FAIL_CLOSED, 0,
                    value.slot_2_owner, "local_replay.exhausted.v1",
                )
            return RecoveryDecisionV1(
                RecoveryDecisionKind.LOCAL_REPLAY, 0,
                value.slot_2_owner, "exact_local_replay.v1",
            )
        if spec.recovery_decision == RecoveryDecisionKind.ONE_TYPED_REATTEMPT:
            if value.physical_attempts_consumed != 1 or value.slot_2_owner is not None:
                return RecoveryDecisionV1(
                    RecoveryDecisionKind.FAIL_CLOSED, 0,
                    value.slot_2_owner, "physical_attempt_budget_exhausted.v1",
                )
            return RecoveryDecisionV1(
                RecoveryDecisionKind.ONE_TYPED_REATTEMPT, 1,
                value.failure_id, "shared_slot_2.v1",
            )
        if spec.recovery_decision == RecoveryDecisionKind.LOCAL_REPAIR:
            return RecoveryDecisionV1(
                RecoveryDecisionKind.LOCAL_REPAIR, 0,
                value.slot_2_owner, "local_repair.v1",
            )
        return RecoveryDecisionV1(
            spec.recovery_decision, 0, value.slot_2_owner,
            "registry." + spec.recovery_decision.value.lower() + ".v1",
        )


@dataclass(frozen=True)
class FaultInjectionCaseV1:
    case_key: str
    boundary_id: str
    failure_id: str
    injection_id: str


@dataclass(frozen=True)
class FaultInjectionRegistryV1:
    cases: tuple[FaultInjectionCaseV1, ...]
    source_registry_sha256: str
    schema_version: str = "FaultInjectionRegistryV1"

    @classmethod
    def from_boundary_registry(
        cls,
        registry: FailureBoundaryRegistryV1,
    ) -> FaultInjectionRegistryV1:
        cases = tuple(
            FaultInjectionCaseV1(
                case_key=f"{boundary_id}|{failure_id}",
                boundary_id=boundary_id,
                failure_id=failure_id,
                injection_id=f"{boundary_id}:{failure_id}",
            )
            for boundary_id, failure_id in fault_case_keys_v1(registry)
        )
        instance = cls(cases, registry.identity_sha256)
        if len({item.case_key for item in cases}) != len(cases):
            raise ValueError("duplicate_fault_case_key")
        declared = {
            injection_id
            for boundary in registry.boundaries
            for injection_id in boundary.fault_injection_ids
        }
        if {item.injection_id for item in cases} != declared:
            raise ValueError("fault_injection_registry_coverage_incomplete")
        return instance

    @property
    def identity_sha256(self) -> str:
        return _sha256({
            "schema_version": self.schema_version,
            "source_registry_sha256": self.source_registry_sha256,
            "cases": [asdict(item) for item in self.cases],
        })


DEFAULT_FAULT_INJECTION_REGISTRY_V1 = (
    FaultInjectionRegistryV1.from_boundary_registry(
        DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
    )
)


class DeterministicFaultInjectorV1:
    def __init__(self, case: FaultInjectionCaseV1 | None = None) -> None:
        self.case = case
        self.trigger_count = 0

    def exception_for(self, boundary_id: str) -> BaseException | None:
        if self.case is None or self.case.boundary_id != boundary_id:
            return None
        if self.trigger_count:
            raise RuntimeError("fault_injection_case_triggered_more_than_once")
        self.trigger_count += 1
        if self.case.failure_id == "__unexpected__":
            return RuntimeError("deterministic unexpected boundary fault")
        return RegisteredBoundaryFailureV1(
            boundary_id=boundary_id,
            failure_id=self.case.failure_id,
        )


class FullShortExecutionKernel:
    def __init__(
        self,
        *,
        registry: FailureBoundaryRegistryV1,
        journal: DurableExecutionJournalV1,
        fault_injector: DeterministicFaultInjectorV1 | None = None,
    ) -> None:
        self.registry = registry
        self.journal = journal
        self.fault_injector = fault_injector or DeterministicFaultInjectorV1()
        self._last_failure_envelope: FailureEnvelopeV1 | None = None

    def _successful_boundaries(self) -> set[str]:
        return {
            item.boundary_id for item in self.journal.audit_receipts
            if item.receipt_kind == "boundary_success"
        }

    def _enforce_entry_prerequisites(self, boundary_id: str) -> None:
        if boundary_id == "FS.AUTHORITY.PROMOTE":
            if self.journal.state != ExecutionState.STAGE_ACCEPTED:
                raise RegisteredBoundaryFailureV1(
                    boundary_id=boundary_id,
                    failure_id="authority.prerequisite_missing",
                )
            if not _AUTHORITY_REQUIRED_STAGE_BOUNDARIES.issubset(
                self._successful_boundaries()
            ):
                raise RegisteredBoundaryFailureV1(
                    boundary_id=boundary_id,
                    failure_id="authority.prerequisite_missing",
                )
        elif boundary_id == "FS.TERMINAL.VERIFY_COMMIT":
            if "FS.AUTHORITY.PROMOTE" not in self._successful_boundaries():
                raise RegisteredBoundaryFailureV1(
                    boundary_id=boundary_id,
                    failure_id="terminal.binding_invalid",
                )

    def authorize_authority_mutation(
        self,
        *,
        artifact_sha256s: tuple[str, ...],
    ) -> DurableAuditReceiptV1:
        """Create the single durable gate receipt immediately before writes."""

        self._enforce_entry_prerequisites("FS.AUTHORITY.PROMOTE")
        if not artifact_sha256s or any(
            not _is_sha256(value) for value in artifact_sha256s
        ):
            raise ValueError("authority_artifact_identity_invalid")
        if any(
            item.receipt_kind == "authority_gate_ready"
            for item in self.journal.audit_receipts
        ):
            raise ValueError("authority_gate_already_consumed")
        return self.journal.append_audit(
            receipt_kind="authority_gate_ready",
            boundary_id="FS.AUTHORITY.PROMOTE",
            payload={
                "state": self.journal.state,
                "required_stage_boundaries": sorted(
                    _AUTHORITY_REQUIRED_STAGE_BOUNDARIES
                ),
                "artifact_sha256s": artifact_sha256s,
                "authority_effect": "formal_artifact_set_once",
            },
        )

    def reconcile_validating_stage_projection(
        self,
        *,
        projected_attempt_state: str,
        receipt_sha256: str,
    ) -> ExecutionTransitionV1:
        """Finish a split-store stage close without executing business code."""

        if self.journal.state != ExecutionState.VALIDATING:
            raise ValueError("validating_state_required")
        if not _is_sha256(receipt_sha256):
            raise ValueError("stage_projection_receipt_invalid")
        target = {
            "LOCAL_STAGE_COMPLETE": ExecutionState.STAGE_ACCEPTED,
            "LOCAL_ATTEMPT_REJECTED": (
                ExecutionState.STAGE_REJECTED_RECOVERABLE
            ),
        }.get(projected_attempt_state)
        if target is None:
            raise ValueError("stage_projection_unresolved")
        return self.journal.transition(
            target,
            transition_id="stage-projection-reconciled:" + receipt_sha256,
            boundary_id="FS.RECOVERY.DECIDE",
        )

    def mark_completed(self, *, completion_receipt_sha256: str) -> None:
        if not _is_sha256(completion_receipt_sha256):
            raise ValueError("completion_receipt_identity_invalid")
        self._enforce_entry_prerequisites("FS.TERMINAL.VERIFY_COMMIT")
        if self.journal.state == ExecutionState.COMPLETED:
            return
        if self.journal.state != ExecutionState.STAGE_ACCEPTED:
            raise ValueError("terminal_stage_acceptance_required")
        self.journal.transition(
            ExecutionState.COMPLETED,
            transition_id="completion-committed:" + completion_receipt_sha256,
            boundary_id="FS.TERMINAL.VERIFY_COMMIT",
        )

    def mark_predispatch_ready(
        self,
        readiness: PredispatchReadinessV1,
    ) -> ExecutionTransitionV1:
        readiness.validate()
        if not self.journal._transition_allowed(
            self.journal.state, ExecutionState.PREDISPATCH_READY
        ):
            raise ValueError("illegal_execution_transition")
        self.journal.append_audit(
            receipt_kind="predispatch_readiness",
            boundary_id="FS.CONTROL.PREFLIGHT",
            payload=asdict(readiness),
            _persist_now=False,
        )
        return self.journal.transition(
            ExecutionState.PREDISPATCH_READY,
            transition_id="predispatch-ready:" + _sha256(asdict(readiness)),
            boundary_id="FS.CONTROL.PREFLIGHT",
        )

    def reserve_dispatch_token(
        self,
        *,
        logical_stage_id: str,
        physical_attempt: int,
        physical_attempt_id: str,
        request_bytes_sha256: str,
    ) -> DispatchTokenV1:
        token = self.journal.reserve_dispatch_token(
            logical_stage_id=logical_stage_id,
            physical_attempt=physical_attempt,
            physical_attempt_id=physical_attempt_id,
            request_bytes_sha256=request_bytes_sha256,
        )
        self.journal.transition(
            ExecutionState.DISPATCH_TOKEN_RESERVED,
            transition_id="dispatch-token-reserved:" + token.token_sha256,
            boundary_id="FS.DISPATCH.MODEL",
        )
        return token

    def _injected_exception(self, boundary_id: str) -> BaseException | None:
        injected = self.fault_injector.exception_for(boundary_id)
        if injected is not None:
            self.journal.append_audit(
                receipt_kind="fault_injection_triggered",
                boundary_id=boundary_id,
                payload={
                    "boundary_id": boundary_id,
                    "source_exception_class": _safe_exception_class(injected),
                },
            )
        return injected

    def _record_success(
        self,
        boundary: BoundarySpecV1,
        *,
        logical_stage_id: str | None,
        physical_attempt: int,
    ) -> None:
        self.journal.append_audit(
            receipt_kind="boundary_success",
            boundary_id=boundary.boundary_id,
            payload={
                "logical_stage_id": logical_stage_id,
                "physical_attempt": physical_attempt,
                "allowed_success_outcome": boundary.allowed_success_outcome,
            },
        )

    def _raise_failure(
        self,
        boundary: BoundarySpecV1,
        exc: BaseException,
        *,
        logical_stage_id: str | None,
        physical_attempt: int,
        capture_reference_sha256: str | None,
    ) -> None:
        if (
            self.journal.state in {
                ExecutionState.TERMINAL_FAILED,
                ExecutionState.PAUSED_RECONCILIATION,
            }
            and self._last_failure_envelope is not None
        ):
            # Nested registered wrappers must propagate the first durable root
            # failure; they may not overwrite it or attempt a second terminal
            # transition while unwinding the same call stack.
            raise FullShortBoundaryFailureV1(
                self._last_failure_envelope
            ) from None
        boundary_id = boundary.boundary_id
        is_registered = (
            isinstance(exc, RegisteredBoundaryFailureV1)
            and exc.boundary_id == boundary_id
            and exc.failure_id in boundary.allowed_typed_failures
        )
        if is_registered:
            spec = self.registry.failure(exc.failure_id)
            classification = FailureClassification.KNOWN
            failure_code = spec.failure_code
            failure_family = spec.failure_family
            recovery_decision = spec.recovery_decision
            restart_policy_id = spec.restart_policy_id
            authority_effect = spec.authority_effect
        else:
            classification = FailureClassification.UNEXPECTED
            failure_code = _UNEXPECTED_FAILURE_ID
            failure_family = "internal.unexpected"
            recovery_decision = RecoveryDecisionKind.FAIL_CLOSED
            restart_policy_id = "restart.forbidden.v1"
            authority_effect = "preserve_last_accepted"
        causes = _cause_chain(exc)
        next_state = {
            RecoveryDecisionKind.PAUSE_RECONCILIATION:
                ExecutionState.PAUSED_RECONCILIATION,
            RecoveryDecisionKind.LOCAL_REPLAY:
                ExecutionState.STAGE_REJECTED_RECOVERABLE,
            RecoveryDecisionKind.ONE_TYPED_REATTEMPT:
                ExecutionState.STAGE_REJECTED_RECOVERABLE,
            RecoveryDecisionKind.LOCAL_REPAIR:
                ExecutionState.STAGE_REJECTED_RECOVERABLE,
            RecoveryDecisionKind.FAIL_CLOSED:
                ExecutionState.TERMINAL_FAILED,
        }[recovery_decision]
        envelope_without_sha = {
            "boundary_id": boundary_id,
            "classification": classification,
            "failure_code": failure_code,
            "failure_family": failure_family,
            "source_exception_class": _safe_exception_class(exc),
            "ordered_causes": causes,
            "recovery_decision": recovery_decision,
            "restart_policy_id": restart_policy_id,
            "authority_effect": authority_effect,
            "logical_stage_id": logical_stage_id,
            "physical_attempt": physical_attempt,
            "capture_reference_sha256": capture_reference_sha256,
            "current_state": self.journal.state,
            "allowed_next_states": (next_state,),
            "raw_content_persisted": False,
        }
        envelope = FailureEnvelopeV1(
            **envelope_without_sha,
            failure_envelope_sha256=_sha256(envelope_without_sha),
        )
        self._last_failure_envelope = envelope
        # Failure receipt and state are one durable journal replacement.  A
        # crash cannot expose a receipt without its owned recovery/stop state.
        self.journal.append_failure(envelope, _persist_now=False)
        self.journal.transition(
            next_state,
            transition_id=f"failure:{envelope.failure_envelope_sha256}",
            boundary_id=boundary_id,
        )
        raise FullShortBoundaryFailureV1(envelope) from None

    def execute_boundary_sync(
        self,
        boundary_id: str,
        operation: Callable[[], _T],
        *,
        logical_stage_id: str | None = None,
        physical_attempt: int = 1,
        capture_reference_sha256: str | None = None,
    ) -> _T:
        boundary = self.registry.boundary(boundary_id)
        try:
            injected = self._injected_exception(boundary_id)
            if injected is not None:
                raise injected
            self._enforce_entry_prerequisites(boundary_id)
            result = operation()
            if inspect.isawaitable(result):
                raise TypeError("sync_boundary_returned_awaitable")
            self._record_success(
                boundary,
                logical_stage_id=logical_stage_id,
                physical_attempt=physical_attempt,
            )
            return result
        except FullShortBoundaryFailureV1:
            raise
        except BaseException as exc:
            self._raise_failure(
                boundary,
                exc,
                logical_stage_id=logical_stage_id,
                physical_attempt=physical_attempt,
                capture_reference_sha256=capture_reference_sha256,
            )

    async def execute_boundary(
        self,
        boundary_id: str,
        operation: Callable[[], Awaitable[_T] | _T],
        *,
        logical_stage_id: str | None = None,
        physical_attempt: int = 1,
        capture_reference_sha256: str | None = None,
    ) -> _T:
        boundary = self.registry.boundary(boundary_id)
        try:
            injected = self._injected_exception(boundary_id)
            if injected is not None:
                raise injected
            self._enforce_entry_prerequisites(boundary_id)
            result = operation()
            if inspect.isawaitable(result):
                result = await result
            self._record_success(
                boundary,
                logical_stage_id=logical_stage_id,
                physical_attempt=physical_attempt,
            )
            return result
        except FullShortBoundaryFailureV1:
            raise
        except BaseException as exc:
            self._raise_failure(
                boundary,
                exc,
                logical_stage_id=logical_stage_id,
                physical_attempt=physical_attempt,
                capture_reference_sha256=capture_reference_sha256,
            )


_ACTIVE_FULL_SHORT_KERNEL_V1: ContextVar[
    FullShortExecutionKernel | None
] = ContextVar("active_full_short_kernel_v1", default=None)


def active_full_short_kernel_v1() -> FullShortExecutionKernel | None:
    return _ACTIVE_FULL_SHORT_KERNEL_V1.get()


@contextmanager
def activate_full_short_kernel_v1(kernel: FullShortExecutionKernel):
    token = _ACTIVE_FULL_SHORT_KERNEL_V1.set(kernel)
    try:
        yield kernel
    finally:
        _ACTIVE_FULL_SHORT_KERNEL_V1.reset(token)


def full_short_boundary_entry(boundary_id: str):
    """Declare the only production wrapper allowed to enter a boundary."""

    DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.boundary(boundary_id)

    def decorate(function):
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def async_wrapper(*args, **kwargs):
                kernel = active_full_short_kernel_v1()
                if kernel is None:
                    return await function(*args, **kwargs)
                return await kernel.execute_boundary(
                    boundary_id,
                    lambda: function(*args, **kwargs),
                    logical_stage_id=str(kwargs.get("logical_stage_id") or "") or None,
                )

            async_wrapper.__full_short_boundary_id__ = boundary_id
            return async_wrapper

        @wraps(function)
        def sync_wrapper(*args, **kwargs):
            kernel = active_full_short_kernel_v1()
            if kernel is None:
                return function(*args, **kwargs)
            return kernel.execute_boundary_sync(
                boundary_id,
                lambda: function(*args, **kwargs),
                logical_stage_id=str(kwargs.get("logical_stage_id") or "") or None,
            )

        sync_wrapper.__full_short_boundary_id__ = boundary_id
        return sync_wrapper

    return decorate


__all__ = [
    "DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1",
    "DEFAULT_FAULT_INJECTION_REGISTRY_V1",
    "BoundarySpecV1",
    "DurableExecutionJournalV1",
    "DispatchTokenV1",
    "ExecutionState",
    "FaultInjectionCaseV1",
    "FaultInjectionRegistryV1",
    "FailureBoundaryRegistryV1",
    "FailureClassification",
    "FailureEnvelopeV1",
    "FullShortBoundaryFailureV1",
    "FullShortExecutionKernel",
    "FullShortRestartReconcilerV1",
    "PredispatchReadinessV1",
    "DeterministicFaultInjectorV1",
    "RecoveryDecisionEngineV1",
    "RecoveryDecisionInputV1",
    "RecoveryDecisionKind",
    "RecoveryDecisionV1",
    "RegisteredBoundaryFailureV1",
    "RestartDecisionKind",
    "RestartReconciliationResultV1",
    "RestartPolicyRegistryV1",
    "activate_full_short_kernel_v1",
    "active_full_short_kernel_v1",
    "fault_case_keys_v1",
    "full_short_boundary_entry",
]
