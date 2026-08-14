from __future__ import annotations

from pathlib import Path

from novel_flywheel.db import Database
from novel_flywheel.runtime_fingerprint import (
    RuntimeFingerprintRecorderV1,
    collect_build_fingerprint,
)
from r0f_baseline_harness import business_run_projection


def make_database(root: Path, name: str) -> Database:
    db = Database(root / f"{name}.db")
    db.migrate()
    db.save_project("book", "Book", "long", root / name / "book")
    return db


def execute(db: Database, run_id: str) -> dict:
    assert db.activate_supervised_run(
        run_id=run_id, project_id="book", workflow="long-chapter",
        resume_payload={"chapter_goal": "deterministic fixture"},
        retry_budgets={
            "protocol_retry": 1, "fallback_route": 1,
            "semantic_repair": 1, "quality_repair": 1,
        },
    )
    assert db.enter_supervised_run_running(run_id)
    assert db.commit_supervised_completion(run_id)
    return business_run_projection(
        db.get_run(run_id) or {}, db.list_run_events(run_id),
    )


def test_r0f_instrumentation_preserves_run_event_business_projection(
    tmp_path: Path,
) -> None:
    before_db = make_database(tmp_path, "before")
    before = execute(before_db, "before-run")

    after_db = make_database(tmp_path, "after")
    build, children = collect_build_fingerprint()
    recorder = RuntimeFingerprintRecorderV1(
        after_db, tmp_path / "after-data",
        process_build=build, build_children=children,
    )
    after_db.set_run_lifecycle_observer(recorder)
    after = execute(after_db, "after-run")

    assert after == before
    assert after["status"] == "completed"
    assert [item["event_type"] for item in after["events"]] == [
        "queued", "started", "completed",
    ]
