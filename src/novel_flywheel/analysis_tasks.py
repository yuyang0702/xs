from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable


ProgressCallback = Callable[[dict], None]
AnalysisOperation = Callable[[ProgressCallback], Awaitable[dict]]


class ReferenceAnalysisTaskManager:
    def __init__(self) -> None:
        self._states: dict[str, dict] = {}
        self._latest_by_source: dict[str, str] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def start(self, source_id: str, operation: AnalysisOperation) -> dict:
        current = self.get_for_source(source_id)
        if current and current["status"] in {"queued", "running"}:
            return current
        task_id = uuid.uuid4().hex
        state = {
            "id": task_id, "source_id": source_id, "status": "queued", "phase": "queued",
            "completed_windows": 0, "total_windows": 0, "result": None, "error": None,
            "reused_windows": 0, "current_window": None,
            "started_at": self._now(), "finished_at": None,
        }
        self._states[task_id] = state
        self._latest_by_source[source_id] = task_id
        self._tasks[task_id] = asyncio.create_task(self._run(task_id, operation))
        return dict(state)

    def get_for_source(self, source_id: str) -> dict | None:
        task_id = self._latest_by_source.get(source_id)
        return dict(self._states[task_id]) if task_id else None

    def cancel(self, task_id: str) -> dict:
        if task_id not in self._states:
            raise LookupError("analysis_task_not_found")
        task = self._tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            self._states[task_id].update(
                status="cancelled", phase="cancelled", finished_at=self._now(),
            )
        return dict(self._states[task_id])

    async def _run(self, task_id: str, operation: AnalysisOperation) -> None:
        state = self._states[task_id]
        state.update(status="running", phase="starting")

        def progress(update: dict) -> None:
            state.update({key: value for key, value in update.items() if key in {
                "phase", "completed_windows", "total_windows", "reused_windows", "current_window",
            }})

        try:
            result = await operation(progress)
            state.update(status="completed", phase="completed", result=result, finished_at=self._now())
        except asyncio.CancelledError:
            state.update(status="cancelled", phase="cancelled", finished_at=self._now())
        except Exception as exc:  # The UI needs the provider error after the request has detached.
            state.update(status="failed", phase="failed", error=str(exc), finished_at=self._now())

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
