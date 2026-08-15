from __future__ import annotations

import os
from pathlib import Path

from novel_flywheel.db import Database
from r0f_baseline_harness import (
    business_run_projection,
    load_baseline,
    protected_source_manifest,
)


REPOSITORY = Path(__file__).resolve().parents[1]
BASELINE = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f" / "r0f-baseline-v1.json"
)
R1_PA1_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-pa1-authorized-protected-source-successor-v1.json"
)


def make_database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("book", "Book", "long", tmp_path / "book")
    return db


def test_r0f_baseline_is_bound_to_clean_r0e_head_and_full_suite() -> None:
    baseline = load_baseline(BASELINE)

    assert baseline["schema"] == "R0FBaselineV1"
    assert baseline["baseline_head"] == (
        "dc15a525f656344c510f973630adaf7cbc3fecf2"
    )
    assert baseline["full_suite"] == {
        "passed": 2409,
        "skipped": 1,
        "strict_xfailed": 5,
        "failed": 0,
    }
    successor = load_baseline(R1_PA1_SUCCESSOR)
    original = {item["path"]: item["sha256"] for item in baseline["protected_sources"]}
    authorized = {
        item["path"]: (item["before_sha256"], item["after_sha256"])
        for item in successor["authorized_source_deltas"]
    }
    current = protected_source_manifest(REPOSITORY)
    for item in current:
        path = item["path"]
        if path in authorized:
            assert authorized[path] == (original[path], item["sha256"])
        else:
            assert item["sha256"] == original[path]
    assert successor["parent_baseline_head"] == baseline["baseline_head"]
    assert successor["phase"] == "R1-PA1"
    assert successor["business_behavior_changed"] is False
    assert successor["protected_deltas"] == baseline["protected_deltas"]
    assert baseline["protected_deltas"] == {
        "model_calls": 0,
        "prompt": 0,
        "retry_fallback_sequence": 0,
        "business_artifacts": 0,
    }


def test_r0f_baseline_characterizes_supervised_run_business_projection(
    tmp_path: Path,
) -> None:
    db = make_database(tmp_path)

    assert db.activate_supervised_run(
        run_id="run-new",
        project_id="book",
        workflow="long-chapter",
        resume_payload={"chapter_goal": "deterministic fixture"},
        retry_budgets={
            "protocol_retry": 1,
            "fallback_route": 1,
            "semantic_repair": 1,
            "quality_repair": 1,
        },
    )
    assert db.enter_supervised_run_running("run-new")
    assert db.commit_supervised_completion("run-new")

    projection = business_run_projection(
        db.get_run("run-new") or {}, db.list_run_events("run-new"),
    )
    assert projection == load_baseline(BASELINE)["supervised_run_projection"]


def test_r0f_baseline_keeps_phase1b_cutover_closed(tmp_path: Path) -> None:
    db = make_database(tmp_path)

    assert os.getenv("NOVEL_SHORT_CANONICAL_V2", "0") == "0"
    assert db.feature_flag(
        "short_canonical_v2", project_id="book", default=False,
    )["enabled"] is False
