import asyncio

import pytest

from novel_flywheel.db import Database
from novel_flywheel.tasks import RunTaskManager


def make_manager(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("book", "Book", "long", tmp_path / "book")
    return db, RunTaskManager(db)


@pytest.mark.asyncio
async def test_task_manager_returns_immediately_and_records_completion(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    release = asyncio.Event()

    async def operation(run_id):
        await release.wait()
        return {"id": run_id}

    run = manager.start("book", "long-chapter", operation)
    assert run["status"] in {"queued", "running"}
    release.set()
    await manager.wait(run["id"])

    assert db.get_run(run["id"])["status"] == "completed"
    assert [item["event_type"] for item in db.list_run_events(run["id"])] == [
        "queued", "started", "completed",
    ]


@pytest.mark.asyncio
async def test_task_manager_cancels_active_task_idempotently(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    started = asyncio.Event()

    async def operation(run_id):
        started.set()
        await asyncio.Event().wait()

    run = manager.start("book", "short-story", operation)
    await started.wait()
    cancelled = manager.cancel(run["id"])
    assert cancelled["status"] == "cancelling"
    with pytest.raises(asyncio.CancelledError):
        await manager.wait(run["id"])

    assert manager.cancel(run["id"])["status"] == "cancelled"
    assert db.get_run(run["id"])["status"] == "cancelled"


@pytest.mark.asyncio
async def test_task_manager_cancels_before_operation_starts(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    called = False

    async def operation(run_id):
        nonlocal called
        called = True

    run = manager.start("book", "short-story", operation)
    assert manager.cancel(run["id"])["status"] == "cancelling"
    with pytest.raises(asyncio.CancelledError):
        await manager.wait(run["id"])
    await asyncio.sleep(0)

    assert called is False
    assert db.get_run(run["id"])["status"] == "cancelled"


@pytest.mark.asyncio
async def test_task_manager_records_failure_without_raising_to_caller(tmp_path) -> None:
    db, manager = make_manager(tmp_path)

    async def operation(run_id):
        raise RuntimeError("model unavailable")

    run = manager.start("book", "short-story", operation)
    await manager.wait(run["id"])

    stored = db.get_run(run["id"])
    assert stored["status"] == "failed"
    assert stored["error"] == "model unavailable"
    assert db.list_run_events(run["id"])[-1]["severity"] == "error"


@pytest.mark.asyncio
async def test_task_manager_records_a_useful_error_when_exception_message_is_empty(tmp_path) -> None:
    db, manager = make_manager(tmp_path)

    async def operation(run_id):
        raise TimeoutError()

    run = manager.start("book", "short-story", operation)
    await manager.wait(run["id"])

    stored = db.get_run(run["id"])
    assert stored["error"] == "TimeoutError (provider returned no error detail)"
    assert db.list_run_events(run["id"])[-1]["message"] == stored["error"]


@pytest.mark.asyncio
async def test_task_manager_resumes_failed_run_with_same_id(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    db.create_run("failed-run", "book", "short-story", status="failed")

    async def operation(run_id):
        assert run_id == "failed-run"

    resumed = manager.resume("failed-run", operation)
    await manager.wait("failed-run")

    assert resumed["id"] == "failed-run"
    assert db.get_run("failed-run")["status"] == "completed"
    assert any(event["event_type"] == "resumed"
               for event in db.list_run_events("failed-run"))


@pytest.mark.asyncio
async def test_task_manager_resumes_cancelled_run_with_same_id(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    db.create_run("cancelled-run", "book", "short-story", status="cancelled")

    async def operation(run_id):
        assert run_id == "cancelled-run"

    resumed = manager.resume("cancelled-run", operation)
    await manager.wait("cancelled-run")

    assert resumed["id"] == "cancelled-run"
    assert db.get_run("cancelled-run")["status"] == "completed"


def test_task_manager_rejects_resuming_completed_run(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    db.create_run("completed-run", "book", "short-story", status="completed")

    with pytest.raises(ValueError, match="failed or cancelled run"):
        manager.resume("completed-run", lambda run_id: None)
