import asyncio
import uuid
from collections.abc import Awaitable, Callable

from novel_flywheel.db import Database
from novel_flywheel.errors import describe_error


RunOperation = Callable[[str], Awaitable[object]]


class RunTaskManager:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.tasks: dict[str, asyncio.Task] = {}

    def start(self, project_id: str, workflow: str, operation: RunOperation) -> dict:
        run_id = uuid.uuid4().hex
        self.db.create_run(run_id, project_id, workflow, status="queued")
        self.db.add_run_event(run_id, "info", "queued", "任务已排队", stage="queue")
        task = asyncio.create_task(self._execute(run_id, operation), name=f"novel-run-{run_id}")
        self.tasks[run_id] = task
        task.add_done_callback(lambda finished, rid=run_id: self._task_done(rid, finished))
        return self.db.get_run(run_id) or {"id": run_id, "status": "queued"}

    def resume(
        self, run_id: str, operation: RunOperation,
        *, allow_interrupted: bool = False,
    ) -> dict:
        run = self.db.get_run(run_id)
        if run is None:
            raise LookupError("Run not found")
        allowed = {"failed", "cancelled"}
        if allow_interrupted:
            allowed.add("interrupted")
        if run["status"] not in allowed:
            raise ValueError("Only a failed or cancelled run can be resumed")
        if run_id in self.tasks:
            raise ValueError("Run is already active")
        self.db.update_run(run_id, "queued")
        self.db.add_run_event(run_id, "info", "resumed", "继续上次失败任务", stage="queue")
        task = asyncio.create_task(self._execute(run_id, operation), name=f"novel-run-{run_id}")
        self.tasks[run_id] = task
        task.add_done_callback(lambda finished, rid=run_id: self._task_done(rid, finished))
        return self.db.get_run(run_id) or {"id": run_id, "status": "queued"}

    def _task_done(self, run_id: str, task: asyncio.Task) -> None:
        run = self.db.get_run(run_id)
        if run and run["status"] == "cancelling":
            self.db.update_run(run_id, "cancelled", error="Cancelled by user")
            self.db.add_run_event(run_id, "warning", "cancelled", "任务已终止")
        self.tasks.pop(run_id, None)

    async def _execute(self, run_id: str, operation: RunOperation) -> None:
        self.db.update_run(run_id, "running", "starting")
        self.db.add_run_event(run_id, "info", "started", "任务开始执行", stage="starting")
        try:
            await operation(run_id)
        except asyncio.CancelledError:
            if (self.db.get_run(run_id) or {}).get("status") != "cancelling":
                self.db.update_run(run_id, "cancelled", error="Cancelled by user")
                self.db.add_run_event(run_id, "warning", "cancelled", "任务已由用户终止")
            raise
        except Exception as exc:
            run = self.db.get_run(run_id) or {}
            is_revision = run.get("workflow") == "short-revision"
            error = (
                "定向返修未完成，已保留可恢复进度。"
                if is_revision else describe_error(exc)
            )
            self.db.update_run(run_id, "failed", error=error)
            self.db.add_run_event(
                run_id, "error",
                "short_revision_failed" if is_revision else "failed", error,
            )
        else:
            run = self.db.get_run(run_id)
            if run and run["status"] in {"queued", "running"}:
                self.db.update_run(run_id, "completed", "archive")
                run = self.db.get_run(run_id)
            if not run or run["status"] != "completed":
                return
            self.db.add_run_event(run_id, "success", "completed", "任务执行完成", stage="archive")

    def cancel(self, run_id: str) -> dict:
        run = self.db.get_run(run_id)
        if run is None:
            raise LookupError("Run not found")
        if run["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            return run
        task = self.tasks.get(run_id)
        if task is not None:
            self.db.update_run(run_id, "cancelling", run.get("current_stage"))
            self.db.add_run_event(run_id, "warning", "cancellation_requested", "正在终止当前任务")
            task.cancel()
        return self.db.get_run(run_id) or run

    async def wait(self, run_id: str) -> dict:
        task = self.tasks.get(run_id)
        if task is not None:
            await task
        run = self.db.get_run(run_id)
        if run is None:
            raise LookupError("Run not found")
        return run
