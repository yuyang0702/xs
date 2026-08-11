import asyncio
import json
from types import SimpleNamespace

import pytest

from novel_flywheel.db import Database
from novel_flywheel.recovery_engine import FailureClass
from novel_flywheel.tasks import RunTaskManager


def make_manager(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("book", "Book", "long", tmp_path / "book")
    return db, RunTaskManager(db)


def initialization_resume_payload() -> dict:
    return {
        "version": 1,
        "outline_sha256": "a" * 64,
        "answers": {},
        "learning_snapshot": {
            "versions": {}, "summary": {}, "stages": {},
            "skipped_conflicts": [],
        },
    }


def test_task_manager_validates_resume_contract_before_creating_or_claiming_run(
    tmp_path,
) -> None:
    db, manager = make_manager(tmp_path)

    with pytest.raises(ValueError, match="resume_payload"):
        manager.start("book", "long-chapter", lambda _run_id: None)
    assert db.list_runs("book") == []

    db.create_run("interrupted", "book", "short-revision", status="interrupted")
    with pytest.raises(ValueError, match="resume_payload"):
        manager.resume(
            "interrupted", lambda _run_id: None, allow_interrupted=True,
        )
    assert db.get_run("interrupted")["status"] == "interrupted"


@pytest.mark.asyncio
async def test_task_manager_returns_immediately_and_records_completion(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    release = asyncio.Event()

    async def operation(run_id):
        await release.wait()
        return {"id": run_id}

    run = manager.start(
        "book", "long-chapter", operation,
        resume_payload={"chapter_goal": "Complete this chapter"},
    )
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

    run = manager.start(
        "book", "short-revision", operation, resume_payload={"issue_ids": []},
    )
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
    assert stored["error"] == (
        "The workflow could not complete; validated progress was preserved "
        "for diagnosis and resume."
    )
    assert db.list_run_events(run["id"])[-1]["severity"] == "error"


@pytest.mark.asyncio
async def test_task_manager_records_a_useful_error_when_exception_message_is_empty(tmp_path) -> None:
    db, manager = make_manager(tmp_path)

    async def operation(run_id):
        raise TimeoutError()

    run = manager.start("book", "short-story", operation)
    await manager.wait(run["id"])

    stored = db.get_run(run["id"])
    assert stored["error"] == (
        "The workflow could not complete; validated progress was preserved "
        "for diagnosis and resume."
    )
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

    first = manager.start(
        "book", "initialize-skills", failing_operation,
        resume_payload=initialization_resume_payload(),
    )
    await manager.wait(first["id"])
    second = manager.start(
        "book", "initialize-skills", failing_operation,
        resume_payload=initialization_resume_payload(),
    )
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

    first = manager.start(
        "book", "initialize-skills", location_failure,
        resume_payload=initialization_resume_payload(),
    )
    await manager.wait(first["id"])
    second = manager.start(
        "book", "initialize-skills", connection_failure,
        resume_payload=initialization_resume_payload(),
    )
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

    run = manager.start(
        "book", "initialize-skills", operation,
        resume_payload=initialization_resume_payload(),
    )
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
    assert failure["message"] == stored["error"]
    assert failure["metadata"]["incident_recording_degraded"] is True


@pytest.mark.asyncio
async def test_task_failure_persists_only_typed_hash_and_safe_summary(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    sentinel = "PRIVATE-STORY-SENTINEL C:\\formal\\canon-secret.md"
    secret_code = "secretlikealphanumericcredential987654321"

    async def operation(_run_id):
        error = RuntimeError(sentinel)
        error.reliability_failure = SimpleNamespace(
            code=secret_code,
            failure_class=FailureClass.UNKNOWN,
            boundary="private-boundary",
            unit_id="private-unit",
        )
        raise error

    run = manager.start("book", "short-story", operation)
    await manager.wait(run["id"])

    persisted = json.dumps({
        "run": db.get_run(run["id"]),
        "events": db.list_run_events(run["id"]),
        "supervision": db.get_workflow_supervision(run["id"]),
        "attempts": db.list_workflow_attempts(run["id"]),
    }, ensure_ascii=False, sort_keys=True)
    assert sentinel not in persisted
    assert secret_code not in persisted
    failure = db.list_run_events(run["id"])[-1]
    assert failure["metadata"]["failure_class"] == "unknown"
    assert failure["metadata"]["failure_code"].startswith("task.")
    assert len(failure["metadata"]["failure_sha256"]) == 64
    assert failure["metadata"]["error_summary"] == failure["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("resume", [False, True])
async def test_synchronous_worker_launch_failure_leaves_no_active_run(
    tmp_path, monkeypatch, resume,
) -> None:
    db, manager = make_manager(tmp_path)
    sentinel = "PRIVATE-LAUNCH-SENTINEL"
    if resume:
        db.create_run("resume-run", "book", "short-story", status="failed")

    def fail_launch(*_args, **_kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(manager, "_launch", fail_launch)
    with pytest.raises(RuntimeError, match=sentinel):
        if resume:
            manager.resume("resume-run", lambda _run_id: None)
        else:
            manager.start("book", "short-story", lambda _run_id: None)

    run = db.list_runs("book")[0]
    assert run["status"] == "interrupted"
    assert db.has_active_runs("book") is False
    assert db.get_workflow_supervision(run["id"])["state"] == "interrupted"
    persisted = json.dumps({
        "run": run,
        "events": db.list_run_events(run["id"]),
        "attempts": db.list_workflow_attempts(run["id"]),
        "supervision": db.get_workflow_supervision(run["id"]),
    }, ensure_ascii=False, sort_keys=True)
    assert sentinel not in persisted
    failure = db.list_run_events(run["id"])[-1]
    assert failure["metadata"]["failure_code"] == "runtime.worker_launch_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger_sql", [
    (
        "CREATE TRIGGER reject_running_supervision BEFORE UPDATE ON workflow_supervision "
        "WHEN NEW.state='running' BEGIN SELECT RAISE(ABORT, "
        "'injected enter-running supervision failure'); END"
    ),
    (
        "CREATE TRIGGER reject_running_attempt BEFORE INSERT ON workflow_attempts "
        "WHEN NEW.action='execute_from_checkpoint' BEGIN SELECT RAISE(ABORT, "
        "'injected enter-running attempt failure'); END"
    ),
    (
        "CREATE TRIGGER reject_started_event BEFORE INSERT ON run_events "
        "WHEN NEW.event_type='started' BEGIN SELECT RAISE(ABORT, "
        "'injected enter-running event failure'); END"
    ),
])
async def test_enter_running_transaction_failure_never_leaves_active_state(
    tmp_path, trigger_sql,
) -> None:
    db, manager = make_manager(tmp_path)
    with db.connect() as connection:
        connection.execute(trigger_sql)
    operation_called = False

    async def operation(_run_id):
        nonlocal operation_called
        operation_called = True

    run = manager.start("book", "short-story", operation)
    with pytest.raises(Exception, match="injected enter-running"):
        await manager.wait(run["id"])
    await asyncio.sleep(0)

    stored = db.get_run(run["id"])
    supervision = db.get_workflow_supervision(run["id"])
    attempts = db.list_workflow_attempts(run["id"])
    events = db.list_run_events(run["id"])
    assert operation_called is False
    assert stored["status"] == "interrupted"
    assert supervision["state"] == "interrupted"
    assert db.has_active_runs("book") is False
    assert run["id"] not in manager.tasks
    assert [item["action"] for item in attempts] == [
        "created", "worker_enter_running_failed",
    ]
    assert [item["event_type"] for item in events] == [
        "queued", "worker_enter_running_failed",
    ]
    persisted = json.dumps({
        "run": stored, "supervision": supervision,
        "attempts": attempts, "events": events,
    }, ensure_ascii=False, sort_keys=True)
    assert "injected enter-running" not in persisted


@pytest.mark.asyncio
async def test_start_rolls_back_run_when_supervision_insert_fails(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    with db.connect() as connection:
        connection.execute(
            "CREATE TRIGGER reject_supervision BEFORE INSERT ON workflow_supervision "
            "BEGIN SELECT RAISE(ABORT, 'injected supervision failure'); END",
        )

    with pytest.raises(Exception, match="injected supervision failure"):
        manager.start("book", "short-story", lambda _run_id: None)

    assert db.list_runs("book") == []
    assert db.has_active_runs("book") is False


@pytest.mark.asyncio
async def test_resume_rolls_back_claim_when_supervision_insert_fails(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    db.create_run("failed-run", "book", "short-story", status="failed")
    with db.connect() as connection:
        connection.execute(
            "CREATE TRIGGER reject_supervision BEFORE INSERT ON workflow_supervision "
            "BEGIN SELECT RAISE(ABORT, 'injected supervision failure'); END",
        )

    with pytest.raises(Exception, match="injected supervision failure"):
        manager.resume("failed-run", lambda _run_id: None)

    assert db.get_run("failed-run")["status"] == "failed"
    assert db.get_workflow_supervision("failed-run") is None
    assert db.has_active_runs("book") is False


@pytest.mark.asyncio
async def test_resume_rolls_back_claim_when_existing_supervision_update_fails(
    tmp_path,
) -> None:
    db, manager = make_manager(tmp_path)
    db.create_run("failed-run", "book", "short-story", status="failed")
    db.save_workflow_supervision(
        run_id="failed-run", state="irrecoverable", resume_payload={},
        retry_budgets={"transport": 3}, used_budgets={"transport": 1},
        last_failure_class="unknown", last_failure_sha256="a" * 64,
        last_error_summary="Safe prior summary",
    )
    db.record_workflow_attempt(
        run_id="failed-run", state="irrecoverable", action="prior_failure",
        failure_class="unknown", failure_sha256="a" * 64,
    )
    supervision_before = db.get_workflow_supervision("failed-run")
    attempts_before = db.list_workflow_attempts("failed-run")
    with db.connect() as connection:
        connection.execute(
            "CREATE TRIGGER reject_supervision_update BEFORE UPDATE ON workflow_supervision "
            "BEGIN SELECT RAISE(ABORT, 'injected supervision update failure'); END",
        )

    with pytest.raises(Exception, match="injected supervision update failure"):
        manager.resume("failed-run", lambda _run_id: None)

    assert db.get_run("failed-run")["status"] == "failed"
    assert db.get_workflow_supervision("failed-run") == supervision_before
    assert db.list_workflow_attempts("failed-run") == attempts_before
    assert db.has_active_runs("book") is False


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
        allow_interrupted=True, resume_payload={"issue_ids": []},
    )
    await manager.wait("interrupted-run")

    assert resumed["id"] == "interrupted-run"
    assert db.get_run("interrupted-run")["status"] == "completed"


@pytest.mark.parametrize("fault_surface", ["supervision", "attempt", "event"])
@pytest.mark.parametrize(
    ("outcome", "target_status", "target_supervision", "attempt_action", "event_type"),
    [
        ("completed", "completed", "completed", "all_gates_completed", "completed"),
        (
            "provider_wait", "waiting_provider", "waiting_provider",
            "schedule_checkpoint_resume", "waiting_provider",
        ),
        (
            "failed", "failed", "irrecoverable",
            "automatic_recovery_exhausted", "failed",
        ),
        ("cancelled", "cancelled", "cancelled", "cancelled_by_user", "cancelled"),
    ],
)
def test_supervised_worker_outcomes_commit_atomically_across_all_ledgers(
    tmp_path, fault_surface, outcome, target_status, target_supervision,
    attempt_action, event_type,
) -> None:
    db, _manager = make_manager(tmp_path)
    run_id = f"atomic-{outcome}-{fault_surface}"
    assert db.activate_supervised_run(
        run_id=run_id, project_id="book", workflow="short-story",
        resume_payload={}, retry_budgets={"provider_wait": 6},
    )
    assert db.enter_supervised_run_running(run_id)
    attempts_before = db.list_workflow_attempts(run_id)
    events_before = db.list_run_events(run_id)

    trigger_name = f"reject_{outcome}_{fault_surface}"
    if fault_surface == "supervision":
        trigger_sql = (
            f"CREATE TRIGGER {trigger_name} BEFORE UPDATE ON workflow_supervision "
            f"WHEN NEW.state='{target_supervision}' BEGIN SELECT RAISE(ABORT, "
            "'injected outcome supervision failure'); END"
        )
    elif fault_surface == "attempt":
        trigger_sql = (
            f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON workflow_attempts "
            f"WHEN NEW.action='{attempt_action}' BEGIN SELECT RAISE(ABORT, "
            "'injected outcome attempt failure'); END"
        )
    else:
        trigger_sql = (
            f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON run_events "
            f"WHEN NEW.event_type='{event_type}' BEGIN SELECT RAISE(ABORT, "
            "'injected outcome event failure'); END"
        )
    with db.connect() as connection:
        connection.execute(trigger_sql)

    incident = {
        "incident_key": "short-story:archive:unknown",
        "incident_family": "unknown",
        "incident_title": "Unknown workflow failure",
        "known_resolution": "Resume from the last validated checkpoint.",
        "failure_code": "task.unknown",
        "failure_class": "unknown",
        "failure_sha256": "f" * 64,
        "error_summary": "Safe failure summary",
    }

    def commit() -> bool:
        if outcome == "completed":
            return db.commit_supervised_completion(run_id)
        if outcome == "provider_wait":
            return db.commit_supervised_provider_wait(
                run_id=run_id, stage="draft",
                error_summary="Provider temporarily unavailable",
                used_budgets={"provider_wait": 1},
                next_retry_at="2099-01-01T00:00:00+00:00",
                failure_class="transport", failure_sha256="e" * 64,
                attempt_action=attempt_action,
                retry_metadata={"retry_index": 1},
                event_metadata={"failure_sha256": "e" * 64},
            )
        if outcome == "failed":
            return db.commit_supervised_terminal_failure(
                run_id=run_id, supervision_state="irrecoverable",
                stage="draft", error_summary="Safe failure summary",
                used_budgets={}, failure_class="unknown",
                failure_sha256="f" * 64, attempt_action=attempt_action,
                attempt_metadata={}, event_type="failed", incident=incident,
            )
        return db.commit_supervised_cancellation(run_id)

    with pytest.raises(Exception, match=f"injected outcome {fault_surface} failure"):
        commit()

    assert db.get_run(run_id)["status"] == "running"
    assert db.get_workflow_supervision(run_id)["state"] == "running"
    assert db.list_workflow_attempts(run_id) == attempts_before
    assert db.list_run_events(run_id) == events_before

    with db.connect() as connection:
        connection.execute(f"DROP TRIGGER {trigger_name}")
    assert commit() is True
    assert db.get_run(run_id)["status"] == target_status
    assert db.get_workflow_supervision(run_id)["state"] == target_supervision
    assert [item["action"] for item in db.list_workflow_attempts(run_id)][-1] \
        == attempt_action
    assert db.list_run_events(run_id)[-1]["event_type"] == event_type


def test_startup_reconciles_legacy_split_terminal_states_idempotently(tmp_path) -> None:
    db, manager = make_manager(tmp_path)
    cases = {
        "legacy-failed-active": (
            "running", "irrecoverable", "failed", "irrecoverable",
        ),
        "legacy-failed-after-old-restart": (
            "interrupted", "irrecoverable", "failed", "irrecoverable",
        ),
        "legacy-user": ("running", "waiting_user", "waiting_user", "waiting_user"),
        (
            "legacy-provider"
        ): ("waiting_provider", "running", "waiting_provider", "waiting_provider"),
        "legacy-completed": ("completed", "running", "completed", "completed"),
    }
    for index, (run_id, (run_status, supervision_state, _target_run, _target_super)) \
            in enumerate(cases.items(), 1):
        project_id = f"book-{index}"
        db.save_project(project_id, project_id, "short", tmp_path / project_id)
        db.create_run(run_id, project_id, "short-story", status=run_status)
        manager.supervisor.create(run_id)
        db.save_workflow_supervision(run_id=run_id, state=supervision_state)

    assert db.interrupt_active_runs() == 0
    for run_id, (_old_run, _old_super, target_run, target_super) in cases.items():
        assert db.get_run(run_id)["status"] == target_run
        assert db.get_workflow_supervision(run_id)["state"] == target_super
        assert db.list_run_events(run_id)[-1]["event_type"] \
            == "terminal_state_reconciled"

    attempts_after_first = {
        run_id: db.list_workflow_attempts(run_id) for run_id in cases
    }
    events_after_first = {run_id: db.list_run_events(run_id) for run_id in cases}
    assert db.interrupt_active_runs() == 0
    assert {
        run_id: db.list_workflow_attempts(run_id) for run_id in cases
    } == attempts_after_first
    assert {
        run_id: db.list_run_events(run_id) for run_id in cases
    } == events_after_first
    assert [
        item["run_id"] for item in db.list_recoverable_workflow_supervisions(
            include_future=True,
        )
    ] == ["legacy-provider"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "blocked_event"),
    [
        ("completed", "completed"),
        ("provider_wait", "waiting_provider"),
        ("failed", "failed"),
        ("cancelled", "cancelled"),
    ],
)
async def test_worker_outcome_audit_fault_preserves_intended_state_without_replay(
    tmp_path, outcome, blocked_event,
) -> None:
    db, manager = make_manager(tmp_path)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    never = asyncio.Event()
    calls = 0

    async def operation(_run_id):
        nonlocal calls
        calls += 1
        if calls > 1:
            return
        first_started.set()
        if outcome == "cancelled":
            await never.wait()
        else:
            await release_first.wait()
        if outcome == "provider_wait":
            raise ConnectionError("provider unavailable")
        if outcome == "failed":
            raise RuntimeError("generated artifact remained invalid")

    run = manager.start("book", "short-story", operation)
    await first_started.wait()
    trigger_name = f"reject_manager_{blocked_event}"
    with db.connect() as connection:
        connection.execute(
            f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON run_events "
            f"WHEN NEW.event_type='{blocked_event}' BEGIN SELECT RAISE(ABORT, "
            "'injected manager outcome event failure'); END",
        )
    if outcome == "cancelled":
        manager.cancel(run["id"])
        with pytest.raises(asyncio.CancelledError):
            await manager.wait(run["id"])
    else:
        release_first.set()
        await manager.wait(run["id"])

    expected = {
        "completed": ("completed", "completed"),
        "provider_wait": ("waiting_provider", "waiting_provider"),
        "failed": ("failed", "irrecoverable"),
        "cancelled": ("cancelled", "cancelled"),
    }[outcome]
    assert db.get_run(run["id"])["status"] == expected[0]
    assert db.get_workflow_supervision(run["id"])["state"] == expected[1]
    assert db.list_run_events(run["id"])[-1]["event_type"] \
        == "worker_outcome_commit_degraded"
    assert db.list_run_events(run["id"])[-1]["metadata"]["intended_outcome"] \
        == expected[0]

    with db.connect() as connection:
        connection.execute(f"DROP TRIGGER {trigger_name}")
    if outcome == "provider_wait":
        supervision = db.get_workflow_supervision(run["id"])
        assert supervision["next_retry_at"]
        assert supervision["used_budgets"]["provider_wait"] == 1
        assert run["id"] in manager.tasks
        manager.cancel(run["id"])
        with pytest.raises(asyncio.CancelledError):
            await manager.wait(run["id"])
        assert db.get_run(run["id"])["status"] == "cancelled"
    else:
        assert run["id"] not in manager.tasks
        assert db.has_active_runs("book") is False
        assert db.list_recoverable_workflow_supervisions(
            include_future=True,
        ) == []
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "blocked_state", "target_status", "target_supervision"),
    [
        ("completed", "completed", "completed", "completed"),
        (
            "provider_wait", "waiting_provider",
            "waiting_provider", "waiting_provider",
        ),
        ("failed", "irrecoverable", "failed", "irrecoverable"),
        ("cancelled", "cancelled", "cancelled", "cancelled"),
    ],
)
async def test_startup_reconciles_intended_outcome_after_state_write_fault(
    tmp_path, outcome, blocked_state, target_status, target_supervision,
) -> None:
    db, manager = make_manager(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()
    never = asyncio.Event()

    async def operation(_run_id):
        started.set()
        if outcome == "cancelled":
            await never.wait()
        else:
            await release.wait()
        if outcome == "provider_wait":
            raise ConnectionError("provider unavailable")
        if outcome == "failed":
            raise RuntimeError("generated artifact remained invalid")

    run = manager.start("book", "short-story", operation)
    await started.wait()
    trigger_name = f"reject_manager_state_{blocked_state}"
    with db.connect() as connection:
        connection.execute(
            f"CREATE TRIGGER {trigger_name} BEFORE UPDATE ON workflow_supervision "
            f"WHEN NEW.state='{blocked_state}' BEGIN SELECT RAISE(ABORT, "
            "'injected manager outcome state failure'); END",
        )
    if outcome == "cancelled":
        manager.cancel(run["id"])
        with pytest.raises(asyncio.CancelledError):
            await manager.wait(run["id"])
    else:
        release.set()
        await manager.wait(run["id"])

    assert db.get_run(run["id"])["status"] == "interrupted"
    assert db.get_workflow_supervision(run["id"])["state"] == "interrupted"
    attempt = db.list_workflow_attempts(run["id"])[-1]
    assert attempt["action"] == "worker_outcome_commit_failed"
    assert attempt["metadata"]["intended_outcome"] == target_status
    assert db.has_active_runs("book") is False

    with db.connect() as connection:
        connection.execute(f"DROP TRIGGER {trigger_name}")
    db.interrupt_active_runs()

    assert db.get_run(run["id"])["status"] == target_status
    supervision = db.get_workflow_supervision(run["id"])
    assert supervision["state"] == target_supervision
    assert db.list_run_events(run["id"])[-1]["event_type"] \
        == "outcome_intent_reconciled"
    if outcome == "provider_wait":
        assert supervision["next_retry_at"]
        assert supervision["used_budgets"]["provider_wait"] == 1
    else:
        assert db.list_recoverable_workflow_supervisions(
            include_future=True,
        ) == []
