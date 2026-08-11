from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from novel_flywheel.completion_supervisor import (
    CompletionState,
    CompletionSupervisor,
    RetryBudgets,
)
from novel_flywheel.db import Database, WORKFLOW_SUPERVISION_CONTRACT_VERSION
from novel_flywheel.production_incidents import classify_production_failure


RunOperation = Callable[[str], Awaitable[object]]
RunOperationResolver = Callable[[dict[str, Any], dict[str, Any]], RunOperation | None]


class ProjectRunActiveError(RuntimeError):
    """Raised when a second writer is started for the same project."""


class RunTaskManager:
    def __init__(
        self, db: Database, *, supervisor: CompletionSupervisor | None = None,
        operation_resolver: RunOperationResolver | None = None,
    ) -> None:
        self.db = db
        self.supervisor = supervisor or CompletionSupervisor(db)
        self.operation_resolver = operation_resolver
        self.tasks: dict[str, asyncio.Task] = {}
        self._operations: dict[str, RunOperation] = {}

    def start(
        self, project_id: str, workflow: str, operation: RunOperation, *,
        resume_payload: dict[str, Any] | None = None,
    ) -> dict:
        resume_payload = self.db.validate_workflow_resume_payload(
            workflow, resume_payload,
        )
        asyncio.get_running_loop()
        run_id = uuid.uuid4().hex
        if not self.db.activate_supervised_run(
            run_id=run_id, project_id=project_id, workflow=workflow,
            resume_payload=resume_payload,
            retry_budgets=RetryBudgets().model_dump(),
        ):
            raise ProjectRunActiveError(
                "This project already has an active run. Wait for it to finish before starting another."
            )
        self._launch_activated_run(run_id, operation)
        return self.db.get_run(run_id) or {"id": run_id, "status": "queued"}

    def resume(
        self, run_id: str, operation: RunOperation, *,
        allow_interrupted: bool = False,
        resume_payload: dict[str, Any] | None = None,
    ) -> dict:
        run = self.db.get_run(run_id)
        if run is None:
            raise LookupError("Run not found")
        if resume_payload is None:
            supervision = self.db.get_workflow_supervision(run_id)
            if supervision is not None:
                resume_payload = supervision["resume_payload"]
        resume_payload = self.db.validate_workflow_resume_payload(
            str(run["workflow"]), resume_payload,
        )
        allowed = {"failed", "cancelled", "waiting_provider"}
        if allow_interrupted:
            allowed.add("interrupted")
        if run["status"] not in allowed:
            raise ValueError("Only a failed or cancelled run can be resumed")
        if run_id in self.tasks:
            raise ValueError("Run is already active")
        asyncio.get_running_loop()
        if not self.db.activate_supervised_run(
            run_id=run_id, project_id=str(run["project_id"]),
            workflow=str(run["workflow"]), resume_payload=resume_payload,
            retry_budgets=RetryBudgets().model_dump(),
            expected_statuses=allowed,
        ):
            raise ProjectRunActiveError(
                "This project already has an active run. Wait for it to finish before resuming."
            )
        self._launch_activated_run(run_id, operation)
        return self.db.get_run(run_id) or {"id": run_id, "status": "queued"}

    def _launch_activated_run(
        self, run_id: str, operation: RunOperation,
    ) -> asyncio.Task:
        self._operations[run_id] = operation
        try:
            return self._launch(run_id, operation)
        except Exception as exc:
            self._operations.pop(run_id, None)
            evidence = f"{type(exc).__name__}:{str(exc)}"
            self.db.interrupt_supervised_run_launch_failure(
                run_id,
                failure_sha256=hashlib.sha256(
                    evidence.encode("utf-8"),
                ).hexdigest(),
            )
            raise

    def _launch(self, run_id: str, operation: RunOperation) -> asyncio.Task:
        task = asyncio.create_task(
            self._execute(run_id, operation), name=f"novel-run-{run_id}",
        )
        self.tasks[run_id] = task
        task.add_done_callback(
            lambda finished, rid=run_id: self._task_done(rid, finished),
        )
        return task

    def _task_done(self, run_id: str, task: asyncio.Task) -> None:
        run = self.db.get_run(run_id)
        if run and run["status"] == "cancelling":
            self._commit_worker_outcome(
                run_id, "cancelled_by_user", "cancelled",
                lambda: self.db.commit_supervised_cancellation(run_id),
                lambda failure_sha256: self.db.commit_supervised_cancellation(
                    run_id, degraded_failure_sha256=failure_sha256,
                ),
            )
        # A failed attempt may already have installed a delayed replacement.
        # Its callback must never remove that newer task.
        if self.tasks.get(run_id) is task:
            self.tasks.pop(run_id, None)
        terminal = self.db.get_run(run_id) or {}
        if terminal.get("status") in {
            "completed", "failed", "cancelled", "interrupted", "waiting_user",
        }:
            self._operations.pop(run_id, None)

    def _commit_worker_outcome(
        self, run_id: str, action: str, intended_outcome: str,
        commit: Callable[[], bool],
        commit_degraded: Callable[[str], bool], *,
        intended_transition: dict[str, Any] | None = None,
    ) -> bool:
        """Bounded retry, then preserve the intended outcome with safe audit."""

        last_error: BaseException | None = None
        for _attempt in range(2):
            try:
                if commit():
                    return True
                last_error = RuntimeError(
                    f"worker outcome authority changed before {action}"
                )
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        evidence = f"{type(last_error).__name__}:{str(last_error)}:{action}"
        failure_sha256 = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        try:
            if commit_degraded(failure_sha256):
                return True
        except Exception as exc:
            last_error = exc
            evidence = f"{type(exc).__name__}:{str(exc)}:{action}:degraded"
            failure_sha256 = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        recovered = self.db.interrupt_supervised_run_outcome_failure(
            run_id,
            failure_sha256=failure_sha256,
            intended_outcome=intended_outcome,
            intended_transition=intended_transition,
            summary=(
                "The worker outcome could not be committed; validated progress "
                "was preserved for restart recovery."
            ),
        )
        if not recovered:
            raise RuntimeError("worker outcome compensation lost state authority") \
                from last_error
        return False

    async def _execute(self, run_id: str, operation: RunOperation) -> None:
        try:
            entered = self.db.enter_supervised_run_running(run_id)
        except Exception as exc:
            evidence = f"{type(exc).__name__}:{str(exc)}"
            self.db.interrupt_supervised_run_launch_failure(
                run_id,
                failure_sha256=hashlib.sha256(
                    evidence.encode("utf-8"),
                ).hexdigest(),
                failure_code="runtime.worker_enter_running_failed",
                action="worker_enter_running_failed",
                summary=(
                    "The workflow worker could not enter running state; "
                    "validated progress was preserved for restart recovery."
                ),
            )
            raise
        if not entered:
            return
        try:
            await operation(run_id)
        except asyncio.CancelledError:
            self._commit_worker_outcome(
                run_id, "cancelled_by_user", "cancelled",
                lambda: self.db.commit_supervised_cancellation(run_id),
                lambda failure_sha256: self.db.commit_supervised_cancellation(
                    run_id, degraded_failure_sha256=failure_sha256,
                ),
            )
            raise
        except Exception as exc:
            run = self.db.get_run(run_id) or {}
            plan = self.supervisor.plan_failure(run_id, exc)
            disposition = plan.disposition
            if disposition.automatic:
                stage = str(run.get("current_stage") or "provider_wait")
                summary, incident = self._safe_failure_record(
                    exc, disposition.failure_class.value,
                    workflow=str(run.get("workflow") or ""),
                    stage=stage, revision=False,
                )
                if plan.next_retry_at is None:
                    raise RuntimeError("provider wait transition lacks retry authority")
                committed = self._commit_worker_outcome(
                    run_id, plan.attempt_action, "waiting_provider",
                    lambda: self.db.commit_supervised_provider_wait(
                        run_id=run_id, stage=stage, error_summary=summary,
                        used_budgets=plan.used_budgets,
                        next_retry_at=plan.next_retry_at,
                        failure_class=disposition.failure_class.value,
                        failure_sha256=plan.failure_sha256,
                        attempt_action=plan.attempt_action,
                        retry_metadata=plan.attempt_metadata,
                        event_metadata={
                            **incident,
                            "retry_after_seconds": disposition.retry_after_seconds,
                        },
                    ),
                    lambda degraded_sha256: self.db.commit_supervised_provider_wait(
                        run_id=run_id, stage=stage, error_summary=summary,
                        used_budgets=plan.used_budgets,
                        next_retry_at=plan.next_retry_at or "",
                        failure_class=disposition.failure_class.value,
                        failure_sha256=plan.failure_sha256,
                        attempt_action=plan.attempt_action,
                        retry_metadata=plan.attempt_metadata,
                        event_metadata={
                            **incident,
                            "retry_after_seconds": disposition.retry_after_seconds,
                        },
                        degraded_failure_sha256=degraded_sha256,
                    ),
                    intended_transition={
                        "used_budgets": plan.used_budgets,
                        "next_retry_at": plan.next_retry_at,
                        "failure_class": disposition.failure_class.value,
                        "failure_sha256": plan.failure_sha256,
                        "error_summary": summary,
                    },
                )
                if not committed:
                    return
                self._schedule_retry(
                    run_id, operation, float(disposition.retry_after_seconds or 0),
                )
                return
            is_revision = run.get("workflow") == "short-revision"
            error, incident = self._safe_failure_record(
                exc, disposition.failure_class.value,
                workflow=str(run.get("workflow") or ""),
                stage=str(run.get("current_stage") or "failed"),
                revision=is_revision,
            )
            stage = str(run.get("current_stage") or "failed")
            event_type = "short_revision_failed" if is_revision else "failed"
            def commit_terminal() -> bool:
                try:
                    return self.db.commit_supervised_terminal_failure(
                        run_id=run_id, supervision_state=disposition.state.value,
                        stage=stage, error_summary=error,
                        used_budgets=plan.used_budgets,
                        failure_class=disposition.failure_class.value,
                        failure_sha256=plan.failure_sha256,
                        attempt_action=plan.attempt_action,
                        attempt_metadata=plan.attempt_metadata,
                        event_type=event_type, incident=incident,
                    )
                except Exception:
                    # Incident aggregation is diagnostic.  If that sub-ledger
                    # is unavailable, retry the same atomic outcome with a
                    # typed, hash-only degraded event.
                    return self.db.commit_supervised_terminal_failure(
                        run_id=run_id, supervision_state=disposition.state.value,
                        stage=stage, error_summary=error,
                        used_budgets=plan.used_budgets,
                        failure_class=disposition.failure_class.value,
                        failure_sha256=plan.failure_sha256,
                        attempt_action=plan.attempt_action,
                        attempt_metadata=plan.attempt_metadata,
                        event_type=event_type, incident=None,
                        event_metadata={
                            **incident, "incident_recording_degraded": True,
                        },
                    )

            committed = self._commit_worker_outcome(
                run_id, plan.attempt_action,
                (
                    "waiting_user"
                    if disposition.state == CompletionState.WAITING_USER else "failed"
                ),
                commit_terminal,
                lambda degraded_sha256: self.db.commit_supervised_terminal_failure(
                    run_id=run_id, supervision_state=disposition.state.value,
                    stage=stage, error_summary=error,
                    used_budgets=plan.used_budgets,
                    failure_class=disposition.failure_class.value,
                    failure_sha256=plan.failure_sha256,
                    attempt_action=plan.attempt_action,
                    attempt_metadata=plan.attempt_metadata,
                    event_type=event_type, incident=None,
                    event_metadata=incident,
                    degraded_failure_sha256=degraded_sha256,
                ),
                intended_transition={
                    "used_budgets": plan.used_budgets,
                    "failure_class": disposition.failure_class.value,
                    "failure_sha256": plan.failure_sha256,
                    "error_summary": error,
                    "stage": stage,
                },
            )
            if not committed:
                return
        else:
            run = self.db.get_run(run_id)
            if not run or run["status"] not in {"running", "completed"}:
                return
            self._commit_worker_outcome(
                run_id, "all_gates_completed", "completed",
                lambda: self.db.commit_supervised_completion(run_id),
                lambda failure_sha256: self.db.commit_supervised_completion(
                    run_id, degraded_failure_sha256=failure_sha256,
                ),
            )

    @staticmethod
    def _safe_failure_record(
        exc: BaseException, failure_class: str, *, workflow: str,
        stage: str, revision: bool,
    ) -> tuple[str, dict[str, str]]:
        """Classify raw evidence in memory and return persistence-safe fields."""

        reliability = getattr(exc, "reliability_failure", None)
        raw_code = str(getattr(reliability, "code", "") or "")
        raw_evidence = f"{type(exc).__name__}:{str(exc)}:{raw_code}"
        failure_sha256 = hashlib.sha256(raw_evidence.encode("utf-8")).hexdigest()
        classified = classify_production_failure(
            str(exc), workflow=workflow, stage=stage, failure=reliability,
        )
        code = f"task.{classified['incident_family']}"
        summaries = {
            "transport": "Provider transport is temporarily unavailable; validated progress was preserved.",
            "credential": "Provider credentials are unavailable to this runtime; validated progress was preserved.",
            "capability": "The configured provider route cannot satisfy this operation; validated progress was preserved.",
            "context_capacity": "The operation exceeded the verified context capacity; validated progress was preserved.",
            "output_truncation": "The provider output was incomplete; validated progress was preserved.",
            "syntax_protocol": "A generated artifact failed its protocol contract; validated progress was preserved.",
            "ownership_evidence": "Generated evidence did not prove the required ownership; validated progress was preserved.",
            "semantic_invariant": "A candidate failed a narrative invariant; the last validated version was preserved.",
            "quality_regression": "A candidate failed a quality gate; the last validated version was preserved.",
            "stale_authority": "The operation used stale authority; the current validated authority was preserved.",
            "unknown": "The workflow could not complete; validated progress was preserved for diagnosis and resume.",
        }
        summary = (
            "定向返修未完成，已保留可恢复进度。"
            if revision else summaries.get(failure_class, summaries["unknown"])
        )
        incident = {
            key: str(classified[key])
            for key in (
                "incident_key", "incident_family", "incident_title", "known_resolution",
            )
        }
        incident.update({
            "failure_code": code,
            "failure_class": failure_class,
            "failure_sha256": failure_sha256,
            "error_summary": summary,
        })
        return summary, incident

    def _schedule_retry(
        self, run_id: str, operation: RunOperation, delay_seconds: float,
    ) -> None:
        async def delayed() -> None:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            run = self.db.get_run(run_id)
            if run is None or run["status"] != "waiting_provider":
                return
            supervision = self.db.get_workflow_supervision(run_id)
            if supervision is None:
                return
            if not self.db.activate_supervised_run(
                run_id=run_id, project_id=str(run["project_id"]),
                workflow=str(run["workflow"]),
                resume_payload=supervision["resume_payload"],
                retry_budgets=supervision["retry_budgets"],
                expected_statuses={"waiting_provider"},
                attempt_action="resume_validated_checkpoint",
            ):
                return
            await self._execute(run_id, operation)

        replacement = asyncio.create_task(
            delayed(), name=f"novel-run-retry-{run_id}",
        )
        self.tasks[run_id] = replacement
        replacement.add_done_callback(
            lambda finished, rid=run_id: self._task_done(rid, finished),
        )

    def recover_due_runs(self) -> list[str]:
        """Schedule due durable runs after startup; never guess missing inputs."""

        if self.operation_resolver is None:
            return []
        scheduled: list[str] = []
        for supervision in self.db.list_recoverable_workflow_supervisions(
            include_future=True,
        ):
            run_id = str(supervision["run_id"])
            if run_id in self.tasks:
                continue
            run = self.db.get_run(run_id)
            if run is None:
                continue
            if (
                int(supervision.get("contract_version") or 0)
                != WORKFLOW_SUPERVISION_CONTRACT_VERSION
            ):
                self.db.update_run(
                    run_id, "waiting_user", run.get("current_stage"),
                    error="The run uses an unsupported resume contract version",
                )
                self.db.add_run_event(
                    run_id, "warning", "resume_contract_unsupported",
                    "The saved run needs an explicit compatible resume migration.",
                    stage=str(run.get("current_stage") or "startup_recovery"),
                    metadata={"contract_version": supervision.get("contract_version")},
                )
                continue
            operation = self.operation_resolver(run, supervision["resume_payload"])
            if operation is None:
                self.db.update_run(
                    run_id, "waiting_user", run.get("current_stage"),
                    error="The run requires missing resume inputs",
                )
                self.supervisor.transition(
                    run_id, CompletionState.WAITING_USER,
                    action="resume_payload_missing",
                )
                continue
            if run["status"] == "waiting_provider":
                retry_at = supervision.get("next_retry_at")
                delay = 0.0
                if retry_at:
                    try:
                        due = datetime.fromisoformat(str(retry_at))
                        if due.tzinfo is None:
                            due = due.replace(tzinfo=timezone.utc)
                        delay = max(
                            0.0, (due - datetime.now(timezone.utc)).total_seconds(),
                        )
                    except ValueError:
                        delay = 0.0
                self._operations[run_id] = operation
                self._schedule_retry(run_id, operation, delay)
                scheduled.append(run_id)
                continue
            if not self.db.activate_supervised_run(
                run_id=run_id, project_id=str(run["project_id"]),
                workflow=str(run["workflow"]),
                resume_payload=supervision["resume_payload"],
                retry_budgets=supervision["retry_budgets"],
                expected_statuses={"waiting_provider", "interrupted"},
                attempt_action="resume_validated_checkpoint",
            ):
                continue
            try:
                self._launch_activated_run(run_id, operation)
            except Exception:
                continue
            scheduled.append(run_id)
        return scheduled

    def cancel(self, run_id: str) -> dict:
        run = self.db.get_run(run_id)
        if run is None:
            raise LookupError("Run not found")
        if run["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            return run
        task = self.tasks.get(run_id)
        if task is not None:
            self.db.update_run(run_id, "cancelling", run.get("current_stage"))
            self.db.add_run_event(
                run_id, "warning", "cancellation_requested", "Cancelling current run",
            )
            task.cancel()
        elif run["status"] in {"waiting_provider", "waiting_user"}:
            self._commit_worker_outcome(
                run_id, "cancelled_by_user", "cancelled",
                lambda: self.db.commit_supervised_cancellation(run_id),
                lambda failure_sha256: self.db.commit_supervised_cancellation(
                    run_id, degraded_failure_sha256=failure_sha256,
                ),
            )
        return self.db.get_run(run_id) or run

    async def wait(self, run_id: str) -> dict:
        task = self.tasks.get(run_id)
        if task is not None:
            await task
        run = self.db.get_run(run_id)
        if run is None:
            raise LookupError("Run not found")
        return run
