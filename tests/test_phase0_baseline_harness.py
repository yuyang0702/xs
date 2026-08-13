from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from phase0_baseline_harness import (
    CANONICALIZATION_VERSION,
    TRACE_BASENAME,
    artifact_manifest,
    canonical_hash,
    capture,
    compare,
)


def test_phase0_canonical_hash_is_stable_across_order_paths_and_volatile_fields(
    tmp_path: Path,
) -> None:
    left = {
        "b": True, "a": None, "count": 3,
        "project_path": str(tmp_path / "project"),
        "created_at": "2026-08-13T00:00:00Z", "run_id": "random-a",
    }
    right = {
        "run_id": "random-b", "created_at": "later",
        "project_path": str(tmp_path / "project"),
        "count": 3, "a": None, "b": True,
    }

    assert CANONICALIZATION_VERSION == "phase0-canonical-json-v1"
    assert canonical_hash(left, root=tmp_path) == canonical_hash(right, root=tmp_path)


def test_phase0_artifact_manifest_excludes_trace_and_run_internals(tmp_path: Path) -> None:
    (tmp_path / "manuscript").mkdir()
    (tmp_path / "manuscript" / "story.md").write_text("formal", encoding="utf-8")
    outputs = tmp_path / "runs" / "run-a" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "candidate.json").write_text("{}", encoding="utf-8")
    (tmp_path / "runs" / TRACE_BASENAME).write_text("secret trace", encoding="utf-8")
    (tmp_path / "runs" / "run-a" / "request.json").write_text("{}", encoding="utf-8")

    paths = {item["path"] for item in artifact_manifest(tmp_path)}

    assert paths == {"manuscript/story.md", "runs/run-a/outputs/candidate.json"}


def test_phase0_capture_is_hash_only_and_compares_artifacts_state_and_calls(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "canon.json").write_text(
        json.dumps({"facts": ["sensitive prose"]}), encoding="utf-8",
    )
    database = tmp_path / "app.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE story_states (project_id TEXT PRIMARY KEY, revision INTEGER, "
        "state_json TEXT, created_at TEXT, updated_at TEXT)"
    )
    connection.execute(
        "INSERT INTO story_states VALUES (?, ?, ?, ?, ?)",
        ("project-secret", 2, json.dumps({"confirmed_facts": ["secret"]}), "a", "b"),
    )
    connection.commit()
    connection.close()
    calls = [{
        "role": "draft", "route": "primary", "system": "secret system",
        "user": "secret prose", "input_tokens": 10, "output_tokens": 4,
        "max_output_tokens": 100,
    }]

    before = capture(workspace, database=database, model_calls=calls)
    after = capture(workspace, database=database, model_calls=calls)

    assert compare(before, after).equal
    serialized = json.dumps(before, ensure_ascii=False)
    assert "secret system" not in serialized
    assert "secret prose" not in serialized
    assert "project-secret" not in serialized
    assert before["story_states"][0]["revision"] == 2
    assert before["model_calls"][0]["max_output_tokens"] == 100
