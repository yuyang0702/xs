from __future__ import annotations

from pathlib import Path

from novel_flywheel.db import Database
from novel_flywheel.runtime_fingerprint import (
    RuntimeFingerprintRecorderV1,
    canonical_runtime_bindings,
    collect_build_fingerprint,
)


def make_database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("book", "Book", "long", tmp_path / "book")
    db.save_project("book-2", "Book 2", "long", tmp_path / "book-2")
    return db


def install_recorder(db: Database, tmp_path: Path) -> RuntimeFingerprintRecorderV1:
    build, children = collect_build_fingerprint()
    recorder = RuntimeFingerprintRecorderV1(
        db, tmp_path / "data", process_build=build, build_children=children,
    )
    db.set_run_lifecycle_observer(recorder)
    return recorder


def activate_new(db: Database, run_id: str = "new-run") -> None:
    assert db.activate_supervised_run(
        run_id=run_id, project_id="book", workflow="long-chapter",
        resume_payload={"chapter_goal": "deterministic fixture"},
        retry_budgets={
            "protocol_retry": 1, "fallback_route": 1,
            "semantic_repair": 1, "quality_repair": 1,
        },
    )


def test_new_run_has_one_immutable_origin_and_executor_binding(tmp_path: Path) -> None:
    db = make_database(tmp_path)
    recorder = install_recorder(db, tmp_path)
    activate_new(db)
    assert db.enter_supervised_run_running("new-run")

    bindings = canonical_runtime_bindings(db, "new-run")
    assert bindings["binding_status"] == "exact"
    assert bindings["origin_count"] == 1
    assert [item["binding_kind"] for item in bindings["bindings"]] == [
        "executor", "origin",
    ]

    origin_event = {
        "run_id": "new-run", "project_id": "book",
        "workflow": "long-chapter", "binding_kind": "origin",
        "execution_epoch": "origin:1",
    }
    recorder(origin_event)
    recorder(origin_event)
    deduplicated = canonical_runtime_bindings(db, "new-run")
    assert deduplicated["origin_count"] == 1
    assert deduplicated["logical_binding_count"] == 2


def test_legacy_resume_adds_executor_but_never_backfills_origin(tmp_path: Path) -> None:
    db = make_database(tmp_path)
    db.create_run("legacy", "book", "short-revision", status="failed")
    install_recorder(db, tmp_path)

    assert db.activate_supervised_run(
        run_id="legacy", project_id="book", workflow="short-revision",
        resume_payload={"issue_ids": []}, retry_budgets={
            "protocol_retry": 1, "fallback_route": 1,
            "semantic_repair": 1, "quality_repair": 1,
        }, expected_statuses={"failed"},
    )

    bindings = canonical_runtime_bindings(db, "legacy")
    assert bindings["origin_count"] == 0
    assert bindings["origin_runtime_execution_fingerprint"] is None
    assert bindings["binding_status"] == "unverifiable_legacy"
    assert [item["binding_kind"] for item in bindings["bindings"]] == ["executor"]
    assert bindings["bindings"][0]["binding_status"] == "unverifiable_legacy"


def test_direct_and_idle_run_creators_emit_origin_after_commit(tmp_path: Path) -> None:
    db = make_database(tmp_path)
    observed_visible_runs: list[str] = []

    def observer(item: dict) -> None:
        assert db.get_run(item["run_id"]) is not None
        observed_visible_runs.append(f"{item['run_id']}:{item['binding_kind']}")

    db.set_run_lifecycle_observer(observer)
    db.create_run("direct", "book", "material-edit", status="running")
    assert db.create_run_if_idle(
        "idle", "book-2", "candidate-publish", status="queued",
    )

    assert observed_visible_runs == [
        "direct:origin", "direct:executor", "idle:origin",
    ]


def test_observer_failure_never_changes_business_transaction(tmp_path: Path) -> None:
    db = make_database(tmp_path)

    def fail(_item: dict) -> None:
        raise RuntimeError("diagnostic sink unavailable")

    db.set_run_lifecycle_observer(fail)
    db.create_run("business", "book", "material-edit", status="running")

    assert db.get_run("business")["status"] == "running"
    assert db.list_run_events("business") == []


def test_binding_reader_reports_same_epoch_contradiction_not_last_write_wins(
    tmp_path: Path,
) -> None:
    db = make_database(tmp_path)
    db.create_run("conflict", "book", "material-edit", status="running")
    for marker, fingerprint in (("a", "1" * 64), ("b", "2" * 64)):
        db.add_run_event(
            "conflict", "info", "runtime_fingerprint_binding_v1",
            "Runtime identity observed", stage="runtime_identity", metadata={
                "binding_definition_sha256": marker * 64,
                "binding_kind": "executor",
                "execution_epoch": "execution:1",
                "runtime_execution_fingerprint": fingerprint,
            },
        )

    result = canonical_runtime_bindings(db, "conflict")

    assert result["binding_status"] == "conflict"
    assert result["logical_binding_count"] == 2
    assert result["conflicts"] == [{
        "binding_kind": "executor",
        "execution_epoch": "execution:1",
        "runtime_execution_fingerprints": ["1" * 64, "2" * 64],
    }]
