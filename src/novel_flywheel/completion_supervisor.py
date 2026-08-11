from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_flywheel.db import Database, WORKFLOW_SUPERVISION_CONTRACT_VERSION
from novel_flywheel.models import (
    CapabilityRoutesExhaustedError,
    ModelRoutesExhaustedError,
    TransportInterruptedError,
)
from novel_flywheel.recovery_engine import FailureClass
from novel_flywheel.structured_artifacts import StructuredOutputCapabilityError


class CompletionState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_PROVIDER = "waiting_provider"
    RECOVERING_PROTOCOL = "recovering_protocol"
    RECOVERING_SEMANTIC = "recovering_semantic"
    WAITING_USER = "waiting_user"
    QUALITY_REPAIR = "quality_repair"
    COMPLETED = "completed"
    IRRECOVERABLE = "irrecoverable"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class RetryBudgets(BaseModel):
    """Independent bounded budgets; one failure class cannot consume another."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    transport: int = Field(default=3, ge=0, le=20)
    protocol: int = Field(default=3, ge=0, le=20)
    semantic: int = Field(default=3, ge=0, le=20)
    quality: int = Field(default=2, ge=0, le=20)
    provider_wait: int = Field(default=6, ge=0, le=50)


class SupervisorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = WORKFLOW_SUPERVISION_CONTRACT_VERSION
    run_id: str = Field(min_length=1)
    state: CompletionState
    resume_payload: dict[str, Any] = Field(default_factory=dict)
    retry_budgets: RetryBudgets = Field(default_factory=RetryBudgets)
    used_budgets: dict[str, int] = Field(default_factory=dict)
    next_retry_at: str | None = None
    last_failure_class: FailureClass | None = None
    last_failure_sha256: str | None = None


@dataclass(frozen=True)
class FailureDisposition:
    state: CompletionState
    failure_class: FailureClass
    retry_after_seconds: float | None = None
    exhausted: bool = False

    @property
    def automatic(self) -> bool:
        return self.state == CompletionState.WAITING_PROVIDER


@dataclass(frozen=True)
class FailureTransitionPlan:
    """A persistence-free failure decision consumed by one DB transaction."""

    disposition: FailureDisposition
    used_budgets: dict[str, int]
    next_retry_at: str | None
    failure_sha256: str
    last_error_summary: str
    attempt_action: str
    attempt_metadata: dict[str, Any]


def classify_completion_failure(exc: BaseException) -> FailureClass:
    """Classify a terminal workflow exception without provider-name branches."""

    reliability = getattr(exc, "reliability_failure", None)
    raw_class = getattr(reliability, "failure_class", None)
    if raw_class:
        try:
            return FailureClass(raw_class)
        except ValueError:
            pass
    if isinstance(exc, TransportInterruptedError):
        return FailureClass.TRANSPORT
    if isinstance(exc, StructuredOutputCapabilityError):
        return FailureClass.CAPABILITY
    if isinstance(exc, CapabilityRoutesExhaustedError):
        children = [item[2] for item in exc.route_errors]
        return _strongest_failure_class(children) or FailureClass.CAPABILITY
    if isinstance(exc, ModelRoutesExhaustedError):
        return _strongest_failure_class(
            [exc.primary_error, exc.fallback_error],
        ) or FailureClass.TRANSPORT
    if isinstance(exc, ConnectionError):
        return FailureClass.TRANSPORT
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    if any(token in name for token in (
        "connecterror", "readtimeout", "connecttimeout", "remoteprotocolerror",
    )):
        return FailureClass.TRANSPORT
    if any(token in message for token in (
        "credential", "api key", "unauthorized", "forbidden", "authentication",
    )):
        return FailureClass.CREDENTIAL
    return FailureClass.UNKNOWN


def _strongest_failure_class(errors: list[BaseException]) -> FailureClass | None:
    classes = [classify_completion_failure(item) for item in errors]
    for candidate in (
        FailureClass.CREDENTIAL,
        FailureClass.CAPABILITY,
        FailureClass.TRANSPORT,
    ):
        if candidate in classes:
            return candidate
    return next((item for item in classes if item != FailureClass.UNKNOWN), None)


class CompletionSupervisor:
    """Durable run-level recovery policy layered above node checkpoints.

    This class does not execute workflow nodes and never replaces the existing
    RecoveryController.  It only decides whether a process-level terminal
    failure should wait for the configured provider and resume from the
    workflow's already validated checkpoints.
    """

    BACKOFF_SECONDS = (5.0, 20.0, 60.0, 180.0, 600.0, 1800.0)

    def __init__(self, db: Database, *, clock=None) -> None:
        self.db = db
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def create(
        self, run_id: str, *, resume_payload: dict[str, Any] | None = None,
        retry_budgets: RetryBudgets | None = None,
    ) -> SupervisorEnvelope:
        budgets = retry_budgets or RetryBudgets()
        self.db.save_workflow_supervision(
            run_id=run_id, state=CompletionState.QUEUED.value,
            resume_payload=resume_payload or {},
            retry_budgets=budgets.model_dump(), used_budgets={},
        )
        self.db.record_workflow_attempt(
            run_id=run_id, state=CompletionState.QUEUED.value, action="created",
        )
        return self.load(run_id)

    def load(self, run_id: str) -> SupervisorEnvelope:
        row = self.db.get_workflow_supervision(run_id)
        if row is None:
            raise LookupError("workflow supervision not found")
        return SupervisorEnvelope.model_validate({
            "version": row["contract_version"],
            "run_id": run_id,
            "state": row["state"],
            "resume_payload": row["resume_payload"],
            "retry_budgets": row["retry_budgets"] or RetryBudgets().model_dump(),
            "used_budgets": row["used_budgets"],
            "next_retry_at": row.get("next_retry_at"),
            "last_failure_class": row.get("last_failure_class"),
            "last_failure_sha256": row.get("last_failure_sha256"),
        })

    def transition(self, run_id: str, state: CompletionState, *, action: str) -> SupervisorEnvelope:
        current = self.load(run_id)
        self.db.save_workflow_supervision(
            run_id=run_id, state=state.value,
            next_retry_at=None if state != CompletionState.WAITING_PROVIDER else current.next_retry_at,
        )
        self.db.record_workflow_attempt(
            run_id=run_id, state=state.value, action=action,
        )
        return self.load(run_id)

    def plan_failure(self, run_id: str, exc: BaseException) -> FailureTransitionPlan:
        """Classify and budget a failure without changing durable state.

        Worker orchestration uses this method so the run row, supervision
        envelope, attempt and public event can be committed in one database
        transaction.  ``handle_failure`` remains as the compatibility boundary
        for callers that only own the supervisor ledger.
        """

        current = self.load(run_id)
        failure_class = classify_completion_failure(exc)
        raw_evidence = f"{type(exc).__name__}:{str(exc)}"
        failure_sha = hashlib.sha256(raw_evidence.encode("utf-8")).hexdigest()
        used = dict(current.used_budgets)

        if failure_class == FailureClass.TRANSPORT:
            bucket = "provider_wait"
            count = int(used.get(bucket, 0)) + 1
            used[bucket] = count
            limit = current.retry_budgets.provider_wait
            if count <= limit:
                delay = self.BACKOFF_SECONDS[min(count - 1, len(self.BACKOFF_SECONDS) - 1)]
                next_retry = (self._clock() + timedelta(seconds=delay)).isoformat()
                disposition = FailureDisposition(
                    CompletionState.WAITING_PROVIDER, failure_class, delay, False,
                )
                return FailureTransitionPlan(
                    disposition=disposition,
                    used_budgets=used,
                    next_retry_at=next_retry,
                    failure_sha256=failure_sha,
                    last_error_summary=(
                        f"{type(exc).__name__}: provider transport unavailable"
                    ),
                    attempt_action="schedule_checkpoint_resume",
                    attempt_metadata={
                        "retry_index": count,
                        "retry_after_seconds": delay,
                    },
                )

        state = (
            CompletionState.WAITING_USER
            if failure_class in {FailureClass.CREDENTIAL, FailureClass.CAPABILITY}
            else CompletionState.IRRECOVERABLE
        )
        disposition = FailureDisposition(state, failure_class, None, True)
        return FailureTransitionPlan(
            disposition=disposition,
            used_budgets=used,
            next_retry_at=None,
            failure_sha256=failure_sha,
            last_error_summary=f"{type(exc).__name__}: {failure_class.value}",
            attempt_action="automatic_recovery_exhausted",
            attempt_metadata={},
        )

    def handle_failure(self, run_id: str, exc: BaseException) -> FailureDisposition:
        plan = self.plan_failure(run_id, exc)
        disposition = plan.disposition
        self.db.save_workflow_supervision(
            run_id=run_id, state=disposition.state.value,
            used_budgets=plan.used_budgets,
            next_retry_at=plan.next_retry_at,
            last_failure_class=disposition.failure_class.value,
            last_failure_sha256=plan.failure_sha256,
            last_error_summary=plan.last_error_summary,
        )
        self.db.record_workflow_attempt(
            run_id=run_id, state=disposition.state.value,
            action=plan.attempt_action,
            failure_class=disposition.failure_class.value,
            failure_sha256=plan.failure_sha256,
            metadata=plan.attempt_metadata,
        )
        return disposition

    def resume_due(self, run_id: str) -> SupervisorEnvelope:
        current = self.load(run_id)
        if current.state not in {
            CompletionState.WAITING_PROVIDER, CompletionState.INTERRUPTED,
        }:
            raise ValueError("run is not awaiting automatic recovery")
        self.db.save_workflow_supervision(
            run_id=run_id, state=CompletionState.QUEUED.value, next_retry_at=None,
        )
        self.db.record_workflow_attempt(
            run_id=run_id, state=CompletionState.QUEUED.value,
            action="resume_validated_checkpoint",
        )
        return self.load(run_id)
