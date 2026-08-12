import asyncio

from novel_flywheel.analysis_tasks import ReferenceAnalysisTaskManager
from novel_flywheel.db import Database


def manager_for(tmp_path, *, resolver=None):
    db = Database(tmp_path / "app.db")
    db.migrate()
    return db, ReferenceAnalysisTaskManager(
        db, operation_resolver=resolver,
    )


async def test_reference_analysis_task_records_redacted_failure(tmp_path) -> None:
    _db, manager = manager_for(tmp_path)

    async def fail(_progress):
        raise RuntimeError("provider timeout SECRET-SENTINEL C:\\private\\route.log")

    manager.start("source-1", fail)
    await asyncio.sleep(0.05)

    state = manager.get_for_source("source-1")
    assert state["status"] == "failed"
    assert state["error_code"].startswith("reference_analysis.")
    assert state["error"] == (
        "Analysis did not complete; validated windows and regional checkpoints "
        "were preserved for the next run."
    )
    serialized = repr(state)
    assert "SECRET-SENTINEL" not in serialized
    assert "private" not in serialized
    assert len(state["failure_sha256"]) == 64
    assert state["finished_at"]


async def test_reference_analysis_task_names_empty_error_without_leaking_it(tmp_path) -> None:
    _db, manager = manager_for(tmp_path)

    async def fail(_progress):
        raise TimeoutError()

    manager.start("source-1", fail)
    await asyncio.sleep(0.05)

    state = manager.get_for_source("source-1")
    assert state["status"] == "failed"
    assert state["error_code"].startswith("reference_analysis.")
    assert len(state["failure_sha256"]) == 64


async def test_reference_analysis_task_can_be_cancelled(tmp_path) -> None:
    _db, manager = manager_for(tmp_path)
    blocker = asyncio.Event()

    async def wait(_progress):
        await blocker.wait()

    started = manager.start("source-1", wait)
    await asyncio.sleep(0)
    cancelled = manager.cancel(started["id"])
    await asyncio.sleep(0)

    assert cancelled["status"] == "cancelled"
    assert manager.get_for_source("source-1")["phase"] == "cancelled"


async def test_reference_analysis_task_exposes_persisted_resume_progress(tmp_path) -> None:
    _db, manager = manager_for(tmp_path)
    blocker = asyncio.Event()

    async def resume(progress):
        progress({
            "phase": "analyzing_windows", "completed_windows": 9,
            "total_windows": 15, "reused_windows": 9,
            "current_window": 10,
        })
        await blocker.wait()

    manager.start("source-1", resume)
    await asyncio.sleep(0.05)

    state = manager.get_for_source("source-1")
    assert state["reused_windows"] == 9
    assert state["current_window"] == 10

    blocker.set()
    await asyncio.sleep(0.05)


async def test_reference_analysis_restart_reuses_durable_task_identity(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    state, created = db.create_resource_task(
        task_id="task-1",
        resource_type=ReferenceAnalysisTaskManager.RESOURCE_TYPE,
        resource_id="source-1",
        operation=ReferenceAnalysisTaskManager.OPERATION,
        resume_payload={"source_id": "source-1"},
    )
    assert created is True
    assert db.claim_resource_task(state["id"]) is True
    assert db.update_resource_task_progress(
        state["id"], phase="analyzing_windows", completed_units=5,
        total_units=5, reused_units=5, current_unit=5,
    ) is True
    calls = []

    async def recovered(progress):
        calls.append("resumed")
        progress({
            "phase": "distilling", "completed_windows": 5,
            "total_windows": 5, "reused_windows": 5,
            "current_window": None,
        })
        return {"status": "validated"}

    manager = ReferenceAnalysisTaskManager(
        db,
        operation_resolver=lambda source_id: (
            recovered if source_id == "source-1" else None
        ),
    )
    assert manager.recover_pending() == ["task-1"]
    await asyncio.sleep(0.05)

    current = manager.get_for_source("source-1")
    assert calls == ["resumed"]
    assert current["id"] == "task-1"
    assert current["status"] == "completed"
    assert current["reused_windows"] == 5
    assert current["result"] == {"status": "validated"}


async def test_reference_analysis_start_is_idempotent_per_source(tmp_path) -> None:
    _db, manager = manager_for(tmp_path)
    blocker = asyncio.Event()

    async def wait(_progress):
        await blocker.wait()

    first = manager.start("source-1", wait)
    second = manager.start("source-1", wait)
    assert second["id"] == first["id"]

    blocker.set()
    await asyncio.sleep(0.05)
