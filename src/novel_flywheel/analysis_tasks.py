from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Awaitable, Callable

from novel_flywheel.db import Database
from novel_flywheel.production_incidents import classify_production_failure


ProgressCallback = Callable[[dict], None]
AnalysisOperation = Callable[[ProgressCallback], Awaitable[dict]]
AnalysisOperationResolver = Callable[[str], AnalysisOperation | None]


class ReferenceAnalysisTaskManager:
    """Durable supervisor for reference-analysis resource tasks.

    Window and distillation checkpoints remain owned by ``LearningSystem``.
    This manager persists only lifecycle/progress and a secret-free resume
    identity, so a process restart can re-enter the same operation and reuse
    the already validated windows instead of losing task state.
    """

    RESOURCE_TYPE = "reference_source"
    OPERATION = "model_analysis"
    CONTRACT_VERSION = 1

    def __init__(
        self, db: Database, *,
        operation_resolver: AnalysisOperationResolver | None = None,
    ) -> None:
        self.db = db
        self.operation_resolver = operation_resolver
        self._tasks: dict[str, asyncio.Task] = {}

    def start(self, source_id: str, operation: AnalysisOperation) -> dict:
        asyncio.get_running_loop()
        state, created = self.db.create_resource_task(
            task_id=uuid.uuid4().hex,
            resource_type=self.RESOURCE_TYPE,
            resource_id=source_id,
            operation=self.OPERATION,
            resume_payload={"source_id": source_id},
            contract_version=self.CONTRACT_VERSION,
        )
        task_id = str(state["id"])
        if (
            state["status"] == "queued"
            and task_id not in self._tasks
            and (created or operation is not None)
        ):
            self._launch(task_id, operation)
        return self._public(state)

    def get_for_source(self, source_id: str) -> dict | None:
        state = self.db.get_latest_resource_task(
            resource_type=self.RESOURCE_TYPE,
            resource_id=source_id,
            operation=self.OPERATION,
        )
        return self._public(state) if state is not None else None

    def cancel(self, task_id: str) -> dict:
        state = self.db.get_resource_task(task_id)
        if state is None or state.get("resource_type") != self.RESOURCE_TYPE:
            raise LookupError("analysis_task_not_found")
        self.db.cancel_resource_task(task_id)
        task = self._tasks.get(task_id)
        if task is not None and not task.done():
            task.cancel()
        current = self.db.get_resource_task(task_id)
        assert current is not None
        return self._public(current)

    def recover_pending(self) -> list[str]:
        """Re-enter interrupted work from source identity and cached windows."""

        if self.operation_resolver is None:
            return []
        asyncio.get_running_loop()
        scheduled: list[str] = []
        for state in self.db.requeue_active_resource_tasks(
            resource_type=self.RESOURCE_TYPE,
            operation=self.OPERATION,
        ):
            task_id = str(state["id"])
            if task_id in self._tasks:
                continue
            source_id = str(state["resource_id"])
            operation = self.operation_resolver(source_id)
            if operation is None:
                self.db.fail_resource_task(
                    task_id,
                    error_code="reference_analysis.resume_source_unavailable",
                    failure_sha256=hashlib.sha256(
                        source_id.encode("utf-8")
                    ).hexdigest(),
                    safe_message=(
                        "Analysis could not resume because its source is no "
                        "longer available; validated windows were preserved."
                    ),
                )
                continue
            self._launch(task_id, operation)
            scheduled.append(task_id)
        return scheduled

    def _launch(
        self, task_id: str, operation: AnalysisOperation,
    ) -> asyncio.Task:
        task = asyncio.create_task(
            self._run(task_id, operation),
            name=f"reference-analysis-{task_id}",
        )
        self._tasks[task_id] = task
        task.add_done_callback(
            lambda finished, tid=task_id: self._task_done(tid, finished),
        )
        return task

    def _task_done(self, task_id: str, task: asyncio.Task) -> None:
        if self._tasks.get(task_id) is task:
            self._tasks.pop(task_id, None)

    async def _run(
        self, task_id: str, operation: AnalysisOperation,
    ) -> None:
        if not self.db.claim_resource_task(task_id):
            return

        def progress(update: dict) -> None:
            current = self.db.get_resource_task(task_id) or {}
            self.db.update_resource_task_progress(
                task_id,
                phase=str(update.get("phase") or current.get("phase") or "running"),
                completed_units=int(
                    update.get("completed_windows", current.get("completed_units") or 0)
                ),
                total_units=int(
                    update.get("total_windows", current.get("total_units") or 0)
                ),
                reused_units=int(
                    update.get("reused_windows", current.get("reused_units") or 0)
                ),
                current_unit=(
                    int(update["current_window"])
                    if update.get("current_window") is not None else None
                ),
            )

        try:
            result = await operation(progress)
            if not isinstance(result, dict):
                raise TypeError("reference analysis result must be an object")
            if not self.db.complete_resource_task(task_id, result):
                current = self.db.get_resource_task(task_id) or {}
                if current.get("status") != "cancelled":
                    raise RuntimeError("reference analysis completion authority changed")
        except asyncio.CancelledError:
            self.db.cancel_resource_task(task_id)
            raise
        except Exception as exc:
            evidence = f"{type(exc).__name__}:{str(exc)}"
            failure_sha256 = hashlib.sha256(
                evidence.encode("utf-8", errors="replace")
            ).hexdigest()
            classified = classify_production_failure(
                str(exc), workflow="reference-analysis", stage="model_analysis",
                failure=getattr(exc, "reliability_failure", None),
            )
            self.db.fail_resource_task(
                task_id,
                error_code=(
                    "reference_analysis."
                    + str(classified.get("incident_family") or "unknown")
                ),
                failure_sha256=failure_sha256,
                safe_message=(
                    "Analysis did not complete; validated windows and regional "
                    "checkpoints were preserved for the next run."
                ),
            )

    @staticmethod
    def _public(state: dict) -> dict:
        return {
            "id": state["id"],
            "source_id": state["resource_id"],
            "status": state["status"],
            "phase": state["phase"],
            "completed_windows": int(state.get("completed_units") or 0),
            "total_windows": int(state.get("total_units") or 0),
            "reused_windows": int(state.get("reused_units") or 0),
            "current_window": state.get("current_unit"),
            "result": state.get("result"),
            "error": state.get("safe_message"),
            "error_code": state.get("error_code"),
            "failure_sha256": state.get("failure_sha256"),
            "started_at": state.get("created_at"),
            "finished_at": state.get("finished_at"),
        }
