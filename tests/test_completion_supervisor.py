from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event

import pytest

from novel_flywheel.completion_supervisor import (
    CompletionState,
    CompletionSupervisor,
    RetryBudgets,
)
from novel_flywheel.db import Database
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.tasks import RunTaskManager


def prepared_db(tmp_path) -> Database:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("book", "Book", "short", tmp_path / "book")
    return db


def test_r0_migration_is_idempotent_and_exposes_durable_tables(tmp_path) -> None:
    db = prepared_db(tmp_path)
    db.migrate()

    assert {
        "workflow_supervision", "workflow_attempts", "feature_flags",
        "sealed_generation_units", "reference_distillation_regions",
        "originality_findings",
    } <= db.table_names()
    with db.connect() as connection:
        assert connection.execute("SELECT version FROM schema_version").fetchone()[0] == 3


def test_supervisor_persists_resume_inputs_without_provider_secrets(tmp_path) -> None:
    db = prepared_db(tmp_path)
    db.create_run("run", "book", "long-chapter", status="queued")
    supervisor = CompletionSupervisor(db)

    envelope = supervisor.create(
        "run", resume_payload={"chapter_goal": "Find the missing witness"},
        retry_budgets=RetryBudgets(provider_wait=2),
    )

    assert envelope.resume_payload == {"chapter_goal": "Find the missing witness"}
    assert envelope.retry_budgets.provider_wait == 2
    stored = str(db.get_workflow_supervision("run")).casefold()
    assert "api_key" not in stored
    assert "credential" not in stored

    db.create_run("secret-run", "book", "short-story", status="queued")
    with pytest.raises(ValueError, match="forbidden secret-bearing field"):
        supervisor.create(
            "secret-run", resume_payload={"nested": {"api_key": "must-not-persist"}},
        )


@pytest.mark.parametrize(
    "secret_field", [
        "auth", "provider_token", "providerToken", "accessToken", "提供商令牌",
    ],
)
def test_initialize_resume_contract_rejects_nested_secret_fields(
    tmp_path, secret_field,
) -> None:
    db = prepared_db(tmp_path)
    run_id = f"initialize-{secret_field}"
    db.create_run(run_id, "book", "initialize-skills", status="queued")

    with pytest.raises(ValueError, match="forbidden secret-bearing field"):
        CompletionSupervisor(db).create(run_id, resume_payload={
            "version": 1,
            "outline_sha256": "a" * 64,
            "answers": {"nested": {secret_field: "must-not-persist"}},
            "learning_snapshot": {
                "versions": {}, "summary": {}, "stages": {},
                "skipped_conflicts": [],
            },
        })

    assert db.get_workflow_supervision(run_id) is None


def test_workflow_attempt_numbers_are_serialized_under_concurrency(tmp_path) -> None:
    db = prepared_db(tmp_path)
    db.create_run("run", "book", "short-story", status="queued")
    CompletionSupervisor(db).create("run", resume_payload={})

    def record(index: int) -> int:
        return db.record_workflow_attempt(
            run_id="run", state="running", action=f"parallel-{index}",
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        attempts = list(pool.map(record, range(12)))

    assert sorted(attempts) == list(range(2, 14))
    assert [item["attempt"] for item in db.list_workflow_attempts("run")] == list(
        range(1, 14)
    )


def test_validated_reference_region_is_immutable_under_concurrency(tmp_path) -> None:
    db = prepared_db(tmp_path)
    library = ReferenceLibrary(db, tmp_path / "references")
    source = library.import_text(
        title="Immutable cache", source_type="paste", text="reference content",
    )
    version_id = source["latest_version"]["id"]

    def save(marker: str) -> str:
        payload = {"marker": marker}
        db.save_reference_distillation_region(
            version_id=version_id, level=0, region_index=0,
            source_start=0, source_end=10, input_sha256="a" * 64,
            output_sha256=marker * 64, payload=payload,
        )
        return marker

    successes = []
    failures = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, marker) for marker in ("b", "c")]
        for future in futures:
            try:
                successes.append(future.result())
            except ValueError as exc:
                failures.append(str(exc))

    assert len(successes) == 1
    assert failures == ["validated reference distillation region conflict"]
    stored = db.get_reference_distillation_region(
        version_id=version_id, level=0, region_index=0,
        input_sha256="a" * 64,
    )
    assert stored is not None
    assert stored["payload"] == {"marker": successes[0]}
    assert stored["output_sha256"] == successes[0] * 64

    with pytest.raises(ValueError, match="validated reference distillation region conflict"):
        db.save_reference_distillation_region(
            version_id=version_id, level=0, region_index=0,
            source_start=0, source_end=10, input_sha256="a" * 64,
            output_sha256=successes[0] * 64,
            payload={"marker": successes[0]}, status="failed",
        )
    assert db.get_reference_distillation_region(
        version_id=version_id, level=0, region_index=0,
        input_sha256="a" * 64,
    )["status"] == "validated"


@pytest.mark.asyncio
async def test_transport_failure_waits_then_automatically_resumes(tmp_path) -> None:
    db = prepared_db(tmp_path)
    supervisor = CompletionSupervisor(db)
    supervisor.BACKOFF_SECONDS = (0.0,)
    manager = RunTaskManager(db, supervisor=supervisor)
    calls = 0

    async def operation(_run_id: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("provider unavailable")

    run = manager.start("book", "short-story", operation)
    for _ in range(20):
        await asyncio.sleep(0)
        if (db.get_run(run["id"]) or {}).get("status") == "completed":
            break

    assert calls == 2
    assert db.get_run(run["id"])["status"] == "completed"
    assert [item["action"] for item in db.list_workflow_attempts(run["id"])] == [
        "created", "execute_from_checkpoint", "schedule_checkpoint_resume",
        "resume_validated_checkpoint", "execute_from_checkpoint", "all_gates_completed",
    ]


@pytest.mark.asyncio
async def test_startup_recovers_interrupted_run_from_persisted_payload(tmp_path) -> None:
    db = prepared_db(tmp_path)
    db.create_run("run", "book", "long-chapter", status="interrupted")
    supervisor = CompletionSupervisor(db)
    supervisor.create("run", resume_payload={"chapter_goal": "Reach the harbor"})
    db.save_workflow_supervision(
        run_id="run", state=CompletionState.INTERRUPTED.value,
    )
    observed = []

    def resolver(run, payload):
        assert run["workflow"] == "long-chapter"
        assert payload == {"chapter_goal": "Reach the harbor"}

        async def operation(run_id):
            observed.append(run_id)

        return operation

    manager = RunTaskManager(
        db, supervisor=supervisor, operation_resolver=resolver,
    )
    assert manager.recover_due_runs() == ["run"]
    await manager.wait("run")

    assert observed == ["run"]
    assert db.get_run("run")["status"] == "completed"


@pytest.mark.asyncio
async def test_startup_recovery_launch_failure_uses_same_safe_compensation(
    tmp_path, monkeypatch,
) -> None:
    db = prepared_db(tmp_path)
    db.create_run("run", "book", "short-story", status="interrupted")
    supervisor = CompletionSupervisor(db)
    supervisor.create("run", resume_payload={})
    db.save_workflow_supervision(
        run_id="run", state=CompletionState.INTERRUPTED.value,
    )

    async def operation(_run_id):
        raise AssertionError("operation must not start")

    manager = RunTaskManager(
        db, supervisor=supervisor,
        operation_resolver=lambda _run, _payload: operation,
    )

    def fail_launch(*_args, **_kwargs):
        raise RuntimeError("PRIVATE-RECOVERY-LAUNCH-SENTINEL")

    monkeypatch.setattr(manager, "_launch", fail_launch)
    assert manager.recover_due_runs() == []

    assert db.get_run("run")["status"] == "interrupted"
    assert db.get_workflow_supervision("run")["state"] == "interrupted"
    assert db.has_active_runs("book") is False
    persisted = str({
        "run": db.get_run("run"),
        "supervision": db.get_workflow_supervision("run"),
        "attempts": db.list_workflow_attempts("run"),
        "events": db.list_run_events("run"),
    })
    assert "PRIVATE-RECOVERY-LAUNCH-SENTINEL" not in persisted


def test_startup_rejects_unknown_supervision_contract_without_running_operation(
    tmp_path,
) -> None:
    db = prepared_db(tmp_path)
    db.create_run("future-run", "book", "short-story", status="interrupted")
    CompletionSupervisor(db).create("future-run", resume_payload={})
    db.save_workflow_supervision(run_id="future-run", state="interrupted")
    with db.connect() as connection:
        connection.execute(
            "UPDATE workflow_supervision SET contract_version=2 WHERE run_id=?",
            ("future-run",),
        )
    resolver_calls = []

    def resolver(_run, _payload):
        resolver_calls.append(True)
        return lambda _run_id: asyncio.sleep(0)

    manager = RunTaskManager(db, operation_resolver=resolver)

    assert manager.recover_due_runs() == []
    assert resolver_calls == []
    assert db.get_run("future-run")["status"] == "waiting_user"
    assert db.list_run_events("future-run")[-1]["event_type"] == (
        "resume_contract_unsupported"
    )


def test_sealed_units_are_idempotent_and_invalidate_by_dependency(tmp_path) -> None:
    db = prepared_db(tmp_path)
    db.create_run("run", "book", "short-story", status="running")
    values = dict(
        run_id="run", unit_type="segment", unit_id="1",
        authority_sha256="a" * 64, input_sha256="b" * 64,
        output_sha256="c" * 64, dependencies=["EV-00000001"],
    )

    first = db.seal_generation_unit(**values)
    repeated = db.seal_generation_unit(**values)

    assert first["generation"] == repeated["generation"] == 1
    assert db.invalidate_generation_scope(
        run_id="run", dependency_ids={"EV-00000002"}, reason="unrelated",
    ) == []
    assert db.invalidate_generation_scope(
        run_id="run", dependency_ids={"EV-00000001"}, reason="event changed",
    ) == ["segment:1"]
    second = db.seal_generation_unit(
        **{**values, "output_sha256": "d" * 64},
    )
    assert second["generation"] == 2


def test_feature_flags_support_project_override(tmp_path) -> None:
    db = prepared_db(tmp_path)
    db.set_feature_flag("planning_ir_first", True)
    db.set_feature_flag(
        "planning_ir_first", False, scope_type="project", scope_id="book",
        config={"reason": "controlled rollback"},
    )

    assert db.feature_flag("planning_ir_first")["enabled"] is True
    project = db.feature_flag("planning_ir_first", project_id="book")
    assert project["enabled"] is False
    assert project["config"]["reason"] == "controlled rollback"


def test_project_flag_update_serializes_with_a_concurrent_run_start(tmp_path) -> None:
    db = prepared_db(tmp_path)
    run_inserted = Event()
    release_transaction = Event()

    def insert_active_run() -> None:
        with db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, NULL, NULL, datetime('now'), datetime('now'))",
                ("concurrent-run", "book", "short-story", "queued"),
            )
            run_inserted.set()
            assert release_transaction.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        run_future = pool.submit(insert_active_run)
        assert run_inserted.wait(timeout=5)
        flag_future = pool.submit(
            db.set_project_feature_flag_if_idle,
            "book", "planning_ir_first", True,
        )
        release_transaction.set()
        run_future.result()
        changed = flag_future.result()

    assert changed is False
    assert db.feature_flag("planning_ir_first", project_id="book")["enabled"] is False


def test_restart_interrupts_worker_states_but_preserves_durable_provider_wait(
    tmp_path,
) -> None:
    db = prepared_db(tmp_path)
    for status in (
        "queued", "recovering_protocol", "recovering_semantic", "quality_repair",
        "waiting_provider",
    ):
        run_id = f"run-{status}"
        db.create_run(run_id, "book", "short-story", status=status)
        CompletionSupervisor(db).create(run_id)
        db.save_workflow_supervision(run_id=run_id, state=status)

    assert db.interrupt_active_runs() == 4
    for status in (
        "queued", "recovering_protocol", "recovering_semantic", "quality_repair",
    ):
        assert db.get_run(f"run-{status}")["status"] == "interrupted"
    assert db.get_run("run-waiting_provider")["status"] == "waiting_provider"
    assert (
        db.get_workflow_supervision("run-waiting_provider")["state"]
        == "waiting_provider"
    )
