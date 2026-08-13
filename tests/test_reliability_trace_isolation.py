from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_flywheel.api.projects import _material_documents
from novel_flywheel.db import Database
from novel_flywheel.memory import StoryMemory
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.reliability_trace import emit_observation, trace_file_for_project
from novel_flywheel.storage import ProjectSnapshot
from novel_flywheel.story_state import StoryStateStore
from phase0_baseline_harness import artifact_manifest


def test_trace_is_physically_excluded_from_memory_material_candidate_saga_snapshot_and_artifacts(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "data" / "app.db")
    db.migrate()
    projects = ProjectStore(db, tmp_path / "data" / "projects")
    project = projects.create(ProjectCreate(
        title="Isolation", mode="long", genre="mystery",
        premise="A deterministic isolation fixture.", target_words=100_000,
    ))
    before = artifact_manifest(project.path)
    sentinel = "TRACE_ONLY_SENTINEL"
    assert emit_observation(
        project.path,
        event_type="authority_read",
        source_component="test.isolation",
        source_writer="test",
        observation_status="confirmed",
        payload={"authority_type": "StoryState", "reader": sentinel},
        semantic_domain="occurred_current",
    )
    trace_path = trace_file_for_project(project.path)
    assert not trace_path.resolve().is_relative_to(project.path.resolve())
    assert sentinel in trace_path.read_text(encoding="utf-8")

    # Memory and FTS are DB projections; no trace file is indexed or returned.
    memory = StoryMemory(db).context(project.id, sentinel)
    assert sentinel not in json.dumps(memory, ensure_ascii=False)
    with db.connect() as connection:
        indexed = connection.execute(
            "SELECT COUNT(*) AS n FROM chapter_search WHERE project_id=?",
            (project.id,),
        ).fetchone()["n"]
    assert indexed == 0

    # The project material scanner is an explicit Markdown allowlist beneath
    # the project root. The physically separate JSONL cannot be discovered.
    materials = _material_documents(project)
    assert sentinel not in json.dumps(materials, ensure_ascii=False)
    assert trace_path not in list(project.path.rglob("*"))

    # Candidate and Saga state live in SQLite/project run artifacts and remain
    # empty; trace append creates neither.
    state_store = StoryStateStore(db)
    assert state_store.list_candidates(project.id) == []
    assert not list((project.path / "runs").glob("*/outputs/project-mutation-journal.json"))

    # Snapshot requires an explicit in-project file list and rejects the trace.
    snapshot = ProjectSnapshot.create(
        project.path, project.path / "snapshots" / "isolation",
        [project.path / "project.json"],
    )
    manifest = json.loads(
        (snapshot.snapshot_root / "manifest.json").read_text(encoding="utf-8")
    )
    assert [item["path"] for item in manifest] == ["project.json"]
    snapshot.discard()
    with pytest.raises(ValueError):
        ProjectSnapshot.create(
            project.path, project.path / "snapshots" / "reject-trace",
            [trace_path],
        )

    # Formal/business artifact collection is byte-for-byte identical with the
    # operational stream enabled because the stream is outside the project.
    assert artifact_manifest(project.path) == before


def test_trace_filename_is_not_reachable_from_import_migration_or_export_scanners() -> None:
    source_root = Path(__file__).parents[1] / "src" / "novel_flywheel"
    scanned = [
        source_root / "memory.py",
        source_root / "reference_library.py",
        source_root / "publication.py",
        source_root / "projects.py",
        source_root / "storage.py",
        source_root / "api" / "projects.py",
    ]
    for path in scanned:
        assert "_reliability-trace-v1.jsonl" not in path.read_text(encoding="utf-8")
