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
@pytest.mark.parametrize("status", ["waiting_confirmation", "waiting_local_fix"])
async def test_task_manager_preserves_revision_waiting_status_without_completed_event(
    tmp_path, status,
) -> None:
    db, manager = make_manager(tmp_path)

    async def operation(run_id):
        db.update_run(run_id, status, "repair_gate")

    run = manager.start("book", "short-revision", operation)
    await manager.wait(run["id"])

    assert db.get_run(run["id"])["status"] == status
    assert "completed" not in {
        item["event_type"] for item in db.list_run_events(run["id"])
    }


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
async def test_task_manager_aggregates_recurring_production_incidents(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    failures = iter((
        "Link check failed: missing location backlink in C:\\projects\\hua-sui.md; 9 errors",
        "Link check failed: missing location backlinks in D:\\books\\pei-yanxing.md; 5 errors",
    ))

    async def failing_operation(_run_id):
        raise RuntimeError(next(failures))

    first = manager.start("book", "initialize-skills", failing_operation)
    await manager.wait(first["id"])
    second = manager.start("book", "initialize-skills", failing_operation)
    await manager.wait(second["id"])

    events = db.list_run_events(second["id"])
    recognized = next(item for item in events if item["event_type"] == "production_incident_recognized")
    failure = next(item for item in events if item["event_type"] == "failed")
    assert "历史同类问题" in recognized["message"]
    assert failure["metadata"]["incident_family"] == "initialization.location_backlink_missing"
    assert failure["metadata"]["occurrence_count"] == 2
    assert "确定性双向闭合" in failure["metadata"]["known_resolution"]


@pytest.mark.asyncio
async def test_task_manager_keeps_unrelated_incidents_separate(tmp_path) -> None:
    db, manager = make_manager(tmp_path)

    async def location_failure(_run_id):
        raise RuntimeError("missing location backlink for hua-sui")

    async def connection_failure(_run_id):
        raise RuntimeError("ConnectError: all connection attempts failed")

    first = manager.start("book", "initialize-skills", location_failure)
    await manager.wait(first["id"])
    second = manager.start("book", "initialize-skills", connection_failure)
    await manager.wait(second["id"])

    families = {item["incident_family"] for item in db.list_production_incidents("book")}
    assert families == {
        "initialization.location_backlink_missing", "provider.connection_failed",
    }


def test_database_reclassifies_legacy_terminal_failure_events(tmp_path) -> None:
    db, _manager = make_manager(tmp_path)
    db.create_run("legacy-run", "book", "initialize-skills", status="failed")
    db.add_run_event(
        "legacy-run", "error", "failed",
        "Controlled runtime ended without required tool output",
        stage="worldbuilding",
    )

    incidents = db.list_production_incidents("book")
    assert incidents[0]["incident_family"] == "runtime.required_tool_output_missing"
    assert incidents[0]["occurrence_count"] == 1


def test_database_refines_legacy_generic_capacity_metadata_from_terminal_evidence(
    tmp_path,
) -> None:
    db, _manager = make_manager(tmp_path)
    db.create_run("legacy-capacity", "book", "short-story", status="failed")
    message = (
        "input context overflow preflight: topology=compact；"
        "规划第 1 段单个事件不可再拆分，已保留完整事件权威"
    )
    db.add_run_event(
        "legacy-capacity", "error", "failed", message,
        stage="review", metadata={
            "incident_key": (
                "short-story:review:model.context_capacity_preflight"
            ),
            "incident_family": "model.context_capacity_preflight",
            "incident_title": "旧通用容量分类",
            "known_resolution": "旧处置",
        },
    )

    incidents = db.list_production_incidents("book")

    assert incidents[0]["incident_family"] \
        == "model.context_capacity_indivisible_scope"
    assert "重叠证据窗口" in incidents[0]["known_resolution"]


def test_database_includes_legacy_failed_runs_without_terminal_failure_event(
    tmp_path,
) -> None:
    db, _manager = make_manager(tmp_path)
    db.create_run("legacy-direct", "book", "short-revision", status="failed")
    db.update_run(
        "legacy-direct", "failed", "final_review",
        error="终审暂时不可用，可以稍后重试。",
    )
    db.add_run_event(
        "legacy-direct", "error", "short_revision_review_unavailable",
        "终审暂时不可用，已保留所有修改决定，可以稍后重试。",
        stage="final_review",
    )

    incidents = db.list_production_incidents("book")

    assert incidents[0]["incident_family"] == "review.final_review_unavailable"
    assert incidents[0]["latest_run_id"] == "legacy-direct"
    assert incidents[0]["occurrence_count"] == 1


@pytest.mark.asyncio
async def test_recurring_incident_counts_legacy_failed_run_without_terminal_event(
    tmp_path,
) -> None:
    db, manager = make_manager(tmp_path)
    db.create_run("legacy-direct", "book", "initialize-skills", status="failed")
    db.update_run(
        "legacy-direct", "failed", "worldbuilding",
        error="missing location backlink for old-character",
    )

    async def operation(_run_id):
        db.update_run(_run_id, "running", "worldbuilding")
        raise RuntimeError("missing location backlinks for new-character")

    run = manager.start("book", "initialize-skills", operation)
    await manager.wait(run["id"])

    failure = db.list_run_events(run["id"])[-1]
    assert failure["metadata"]["occurrence_count"] == 2
    assert failure["metadata"]["family_occurrence_count"] == 2


@pytest.mark.asyncio
async def test_incident_aggregation_failure_does_not_hide_terminal_run_failure(
    tmp_path, monkeypatch,
) -> None:
    db, manager = make_manager(tmp_path)

    def broken_recorder(*_args, **_kwargs):
        raise RuntimeError("incident store unavailable")

    monkeypatch.setattr(db, "record_run_failure", broken_recorder)

    async def operation(_run_id):
        raise RuntimeError("ConnectError")

    run = manager.start("book", "short-story", operation)
    await manager.wait(run["id"])

    stored = db.get_run(run["id"])
    failure = db.list_run_events(run["id"])[-1]
    assert stored["status"] == "failed"
    assert failure["message"] == "ConnectError"
    assert failure["metadata"]["incident_recording_degraded"] is True


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


def test_task_manager_rejects_interrupted_run_without_opt_in(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    db.create_run("interrupted-run", "book", "short-story", status="interrupted")

    with pytest.raises(ValueError, match="failed or cancelled run"):
        manager.resume("interrupted-run", lambda run_id: None)


@pytest.mark.asyncio
async def test_task_manager_resumes_interrupted_run_with_opt_in(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    db.create_run("interrupted-run", "book", "short-revision", status="interrupted")

    resumed = manager.resume(
        "interrupted-run", lambda run_id: asyncio.sleep(0),
        allow_interrupted=True,
    )
    await manager.wait("interrupted-run")

    assert resumed["id"] == "interrupted-run"
    assert db.get_run("interrupted-run")["status"] == "completed"
