import ast
import hashlib
from pathlib import Path
import json

import pytest
from pydantic import ValidationError

from novel_flywheel.project_transactions import (
    ProjectMutationPostCommitGateV1,
    ProjectMutationCanonFactV1,
    ProjectMutationChapterIndexV1,
    ProjectMutationChapterStateV1,
    ProjectMutationJournalV1,
    ProjectMutationStoryStateV1,
    canonical_json_sha256,
    project_mutation_artifacts_match,
    restore_project_mutation_targets,
    stage_project_mutation_targets,
)
from novel_flywheel.learning_artifacts import LearningArtifactInvalidationV1
from novel_flywheel.learning_artifacts import (
    plan_learning_artifact_invalidations,
    write_learning_artifact_sidecar_targets,
)
from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.project_transactions import (
    complete_project_mutation,
    commit_project_mutation_authority,
    finalize_project_mutation,
    record_project_mutation_gate_result,
    project_mutation_journal_path,
    write_project_mutation_journal,
)
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.storage import ProjectSnapshot


def test_mixed_file_story_state_writer_inventory_cannot_grow() -> None:
    """All mixed project-file plus StoryState writers use the shared Saga."""

    source_root = Path(__file__).parents[1] / "src" / "novel_flywheel"
    discovered = set()
    for source_path in source_root.rglob("*.py"):
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path),
        )
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            call_names = set()
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                if isinstance(call.func, ast.Name):
                    call_names.add(call.func.id)
                elif isinstance(call.func, ast.Attribute):
                    call_names.add(call.func.attr)
            if {"atomic_write", "commit"} <= call_names:
                discovered.add((
                    source_path.relative_to(source_root).as_posix(), node.name,
                ))

    assert discovered == set()


def test_mixed_file_story_memory_writer_inventory_cannot_grow() -> None:
    """All file plus StoryMemory writers must use the shared Saga."""

    source_root = Path(__file__).parents[1] / "src" / "novel_flywheel"
    discovered = set()
    for source_path in source_root.rglob("*.py"):
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path),
        )
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = set()
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                if isinstance(call.func, ast.Name):
                    calls.add(call.func.id)
                elif isinstance(call.func, ast.Attribute):
                    calls.add(call.func.attr)
            if (
                "atomic_write" in calls
                and calls & {"add_fact", "index_chapter", "save_state"}
            ):
                discovered.add((
                    source_path.relative_to(source_root).as_posix(), node.name,
                ))

    assert discovered == set()


def test_material_impact_application_has_one_mixed_authority_commit_owner() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "novel_flywheel" / "api"
        / "projects.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "apply_material_impact"
    )
    call_names = {
        call.func.id if isinstance(call.func, ast.Name) else call.func.attr
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
        and isinstance(call.func, (ast.Name, ast.Attribute))
    }

    assert "complete_project_mutation" in call_names
    assert "commit" not in call_names


def test_outline_application_has_one_mixed_authority_commit_owner() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "novel_flywheel"
        / "outlines.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "apply_candidate"
    )
    call_names = {
        call.func.id if isinstance(call.func, ast.Name) else call.func.attr
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
        and isinstance(call.func, (ast.Name, ast.Attribute))
    }

    assert "complete_project_mutation" in call_names
    assert "commit" not in call_names


def test_material_edit_has_one_mixed_authority_commit_owner() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "novel_flywheel" / "api"
        / "projects.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "update_project_material"
    )
    call_names = {
        call.func.id if isinstance(call.func, ast.Name) else call.func.attr
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
        and isinstance(call.func, (ast.Name, ast.Attribute))
    }

    assert "complete_project_mutation" in call_names
    assert "commit" not in call_names


def test_project_mutation_target_replay_is_exact_and_idempotent(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = project / "characters" / "hero.md"
    target.parent.mkdir()
    target.write_bytes(b"old\r\nauthority")
    snapshot = ProjectSnapshot.create(
        project, project / "snapshots" / "mutation", [target],
    )
    target.write_bytes(b"new\nauthority")
    artifacts = stage_project_mutation_targets(project, snapshot, [target])
    snapshot.restore()

    restore_project_mutation_targets(project, snapshot, artifacts)
    restore_project_mutation_targets(project, snapshot, artifacts)

    assert target.read_bytes() == b"new\nauthority"
    assert project_mutation_artifacts_match(project, artifacts) is True


def test_project_mutation_target_replay_refuses_unknown_concurrent_bytes(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = project / "plot" / "outline.md"
    target.parent.mkdir()
    target.write_text("old", encoding="utf-8")
    snapshot = ProjectSnapshot.create(
        project, project / "snapshots" / "mutation", [target],
    )
    target.write_text("new", encoding="utf-8")
    artifacts = stage_project_mutation_targets(project, snapshot, [target])
    target.write_text("third-party", encoding="utf-8")

    with pytest.raises(ValueError, match="unknown concurrent edit"):
        restore_project_mutation_targets(project, snapshot, artifacts)

    assert target.read_text(encoding="utf-8") == "third-party"


def test_project_mutation_target_replay_validates_all_paths_before_any_write(
    tmp_path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    first = project / "a.md"
    second = project / "z.md"
    first.write_text("old-a", encoding="utf-8")
    second.write_text("old-z", encoding="utf-8")
    snapshot = ProjectSnapshot.create(
        project, project / "snapshots" / "mutation", [first, second],
    )
    first.write_text("new-a", encoding="utf-8")
    second.write_text("new-z", encoding="utf-8")
    artifacts = stage_project_mutation_targets(
        project, snapshot, [first, second],
    )
    snapshot.restore()
    second.write_text("third-party-z", encoding="utf-8")

    with pytest.raises(ValueError, match="unknown concurrent edit"):
        restore_project_mutation_targets(project, snapshot, artifacts)

    assert first.read_text(encoding="utf-8") == "old-a"
    assert second.read_text(encoding="utf-8") == "third-party-z"


def test_project_mutation_target_replay_rejects_corrupt_staged_copy(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = project / "canon.json"
    target.write_text("old", encoding="utf-8")
    snapshot = ProjectSnapshot.create(
        project, project / "snapshots" / "mutation", [target],
    )
    target.write_text("new", encoding="utf-8")
    artifacts = stage_project_mutation_targets(project, snapshot, [target])
    staged = snapshot.snapshot_root / "targets" / "canon.json"
    staged.write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="staged target is corrupt"):
        restore_project_mutation_targets(project, snapshot, artifacts)


def test_project_mutation_journal_binds_full_artifact_and_story_state_authority() -> None:
    data = {"story_state_schema": 3, "confirmed_facts": []}
    state = ProjectMutationStoryStateV1(
        candidate_id="candidate-1",
        expected_revision=4,
        target_revision=5,
        state_sha256=canonical_json_sha256(data),
        data=data,
    )
    artifact_sha = hashlib.sha256(b"target").hexdigest()
    journal = ProjectMutationJournalV1(
        status="artifacts_committed",
        operation="material-edit",
        run_id="run-1",
        project_id="project-1",
        snapshot_path="snapshots/run-1",
        source_authority_sha256=hashlib.sha256(b"source").hexdigest(),
        expected_story_state_revision=4,
        managed_paths=("characters/hero.md",),
        artifacts=({
            "path": "characters/hero.md", "sha256": artifact_sha,
        },),
        story_state=state,
    )
    assert journal.story_state is not None

    with pytest.raises(ValidationError, match="artifact coverage is incomplete"):
        ProjectMutationJournalV1.model_validate({
            **journal.model_dump(mode="python"),
            "managed_paths": ("characters/hero.md", "canon.json"),
        })
    with pytest.raises(ValidationError, match="StoryState hash is stale"):
        ProjectMutationStoryStateV1.model_validate({
            **state.model_dump(mode="python"),
            "data": {"story_state_schema": 3, "confirmed_facts": ["changed"]},
        })


def test_project_mutation_defers_terminal_state_to_hash_bound_business_gate(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    projects = ProjectStore(db, tmp_path / "projects")
    project = projects.create(ProjectCreate(
        title="Deferred gate", mode="long", genre="fantasy",
        premise="Chapter authority commits before the volume gate.",
        target_words=100_000,
    ))
    state = StoryStateStore(db).ensure(project.id, project.path)
    chapter = project.path / "chapters" / "chapter-01.md"
    run_id = "deferred-gate"
    db.create_run(run_id, project.id, "long-chapter", status="running")
    snapshot = ProjectSnapshot.create(
        project.path, project.path / "snapshots" / run_id, [chapter],
    )
    chapter.write_text("accepted chapter", encoding="utf-8")
    artifacts = stage_project_mutation_targets(
        project.path, snapshot, [chapter],
    )
    snapshot.restore()
    gate_payload = {"chapter_number": 1, "volume_number": 1}
    journal = ProjectMutationJournalV1(
        status="artifacts_committed", operation="long-chapter",
        run_id=run_id, project_id=project.id,
        snapshot_path=f"snapshots/{run_id}",
        source_authority_sha256="d" * 64,
        expected_story_state_revision=state.revision,
        managed_paths=("chapters/chapter-01.md",),
        artifacts=artifacts,
        post_commit_gate=ProjectMutationPostCommitGateV1(
            name="volume_audit",
            payload=gate_payload,
            payload_sha256=canonical_json_sha256(gate_payload),
        ),
    )
    write_project_mutation_journal(
        project_mutation_journal_path(project.path, run_id), journal,
    )

    committed = commit_project_mutation_authority(projects, run_id)

    assert committed.status == "committed"
    assert chapter.read_text(encoding="utf-8") == "accepted chapter"
    assert db.get_run(run_id)["status"] == "running"
    assert (project.path / "snapshots" / run_id).is_dir()
    with pytest.raises(RuntimeError, match="business post-commit gate"):
        complete_project_mutation(projects, run_id)
    with pytest.raises(RuntimeError, match="has not passed"):
        finalize_project_mutation(projects, run_id)

    receipt = project.path / "memory" / "audits" / "volume-01.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
    record_project_mutation_gate_result(
        projects, run_id, status="passed", receipt_path=receipt,
    )
    receipt.write_text('{"status":"tampered"}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="receipt is stale"):
        finalize_project_mutation(projects, run_id)
    receipt.write_text('{"status":"passed"}\n', encoding="utf-8")

    finalized = finalize_project_mutation(projects, run_id)

    assert finalized.status == "committed"
    assert db.get_run(run_id)["status"] == "completed"
    assert not (project.path / "snapshots" / run_id).exists()


def test_project_mutation_journal_requires_sidecar_for_learning_effect() -> None:
    effect = LearningArtifactInvalidationV1(
        artifact_id="artifact-1",
        artifact_type="scene_briefs",
        artifact_version=2,
        source_hash="a" * 64,
    )
    with pytest.raises(ValidationError, match="lacks its sidecar"):
        ProjectMutationJournalV1(
            status="prepared",
            operation="outline-apply",
            run_id="run-1",
            project_id="project-1",
            snapshot_path="snapshots/run-1",
            source_authority_sha256="b" * 64,
            expected_story_state_revision=4,
            managed_paths=("plot/outline.md",),
            learning_artifact_invalidations=(effect,),
        )


def test_project_mutation_replays_story_state_files_and_learning_effects(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    projects = ProjectStore(db, tmp_path / "projects")
    project = projects.create(ProjectCreate(
        title="完整事务", mode="short", genre="现实",
        premise="验证业务权威整体恢复。", target_words=13_000,
    ))
    state_store = StoryStateStore(db)
    state = state_store.ensure(project.id, project.path)
    artifact_data = {"briefs": [{"id": "scene-01"}]}
    serialized = json.dumps(
        artifact_data, ensure_ascii=False, sort_keys=True,
    )
    artifact_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO project_learning_artifacts VALUES "
            "(?,?,?,?,?,?,?,datetime('now'))",
            ("artifact-1", project.id, "scene_briefs", 1, "active",
             serialized, artifact_hash),
        )
    outline = project.path / "plot" / "outline.md"
    sidecar = project.path / "learning" / "scene_briefs.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text("{}\n", encoding="utf-8")
    run_id = "outline-saga"
    db.create_run(run_id, project.id, "outline-apply", status="running")
    snapshot = ProjectSnapshot.create(
        project.path, project.path / "snapshots" / run_id,
        [outline, sidecar],
    )
    plan = plan_learning_artifact_invalidations(
        db, project.id, artifact_types=("scene_briefs",), latest_only=True,
    )
    outline.write_text("# 新大纲\n", encoding="utf-8")
    write_learning_artifact_sidecar_targets(project.path, plan)
    artifacts = stage_project_mutation_targets(
        project.path, snapshot, [outline, sidecar],
    )
    snapshot.restore()
    next_data = {**state.data, "outline": {"content": "# 新大纲\n"}}
    candidate = state_store.create_candidate(
        project.id, run_id, state.revision, "outline",
        hashlib.sha256(b"# new outline").hexdigest(),
    )
    target_state = ProjectMutationStoryStateV1(
        candidate_id=candidate.id,
        expected_revision=state.revision,
        target_revision=state.revision + 1,
        state_sha256=canonical_json_sha256(next_data),
        data=next_data,
    )
    journal = ProjectMutationJournalV1(
        status="artifacts_committed",
        operation="outline-apply",
        run_id=run_id,
        project_id=project.id,
        snapshot_path=f"snapshots/{run_id}",
        source_authority_sha256="c" * 64,
        expected_story_state_revision=state.revision,
        managed_paths=("plot/outline.md", "learning/scene_briefs.json"),
        artifacts=artifacts,
        story_state=target_state,
        learning_artifact_invalidations=plan.effects,
    )
    write_project_mutation_journal(
        project_mutation_journal_path(project.path, run_id), journal,
    )

    completed = complete_project_mutation(projects, run_id)
    completed_again = complete_project_mutation(projects, run_id)

    assert completed.status == completed_again.status == "committed"
    assert outline.read_text(encoding="utf-8") == "# 新大纲\n"
    assert state_store.get(project.id).revision == state.revision + 1
    with db.connect() as connection:
        status = connection.execute(
            "SELECT status FROM project_learning_artifacts WHERE id='artifact-1'",
        ).fetchone()["status"]
    assert status == "stale"
    assert json.loads(sidecar.read_text(encoding="utf-8"))["status"] == "stale"
    assert db.get_run(run_id)["status"] == "completed"


def test_project_mutation_replays_memory_effects_idempotently(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    projects = ProjectStore(db, tmp_path / "projects")
    project = projects.create(ProjectCreate(
        title="章节记忆事务", mode="long", genre="现实",
        premise="文件与章节记忆必须来自同一提交。", target_words=100_000,
    ))
    state = StoryStateStore(db).ensure(project.id, project.path)
    chapter = project.path / "chapters" / "chapter-01.md"
    run_id = "chapter-memory-saga"
    db.create_run(run_id, project.id, "long-chapter", status="running")
    snapshot = ProjectSnapshot.create(
        project.path, project.path / "snapshots" / run_id, [chapter],
    )
    prose = "第一章正文。"
    chapter.write_text(prose, encoding="utf-8")
    artifacts = stage_project_mutation_targets(
        project.path, snapshot, [chapter],
    )
    snapshot.restore()
    chapter_state = {"hero": {"knowledge": "已发现线索"}}
    effects = (
        ProjectMutationCanonFactV1(
            fact_key="chapter.1.clue", value="线索已出现",
            source="chapter-01", confirmed=True,
        ),
        ProjectMutationChapterIndexV1(
            chapter_id="chapter-01", chapter_number=1,
            content=prose,
            content_sha256=hashlib.sha256(prose.encode("utf-8")).hexdigest(),
            summary="主角发现线索",
        ),
        ProjectMutationChapterStateV1(
            chapter_id="chapter-01",
            state_sha256=canonical_json_sha256(chapter_state),
            state=chapter_state,
        ),
    )
    journal = ProjectMutationJournalV1(
        status="artifacts_committed",
        operation="long-chapter",
        run_id=run_id,
        project_id=project.id,
        snapshot_path=f"snapshots/{run_id}",
        source_authority_sha256="d" * 64,
        expected_story_state_revision=state.revision,
        managed_paths=("chapters/chapter-01.md",),
        artifacts=artifacts,
        memory_effects=effects,
    )
    write_project_mutation_journal(
        project_mutation_journal_path(project.path, run_id), journal,
    )

    complete_project_mutation(projects, run_id)
    complete_project_mutation(projects, run_id)

    assert chapter.read_text(encoding="utf-8") == prose
    with db.connect() as connection:
        fact = connection.execute(
            "SELECT value, source FROM canon_facts WHERE project_id=? "
            "AND fact_key='chapter.1.clue' AND confirmed=1",
            (project.id,),
        ).fetchone()
        indexed = connection.execute(
            "SELECT content, summary FROM chapter_search WHERE project_id=? "
            "AND chapter_id='chapter-01'",
            (project.id,),
        ).fetchall()
        saved_state = connection.execute(
            "SELECT state_json FROM chapter_states WHERE project_id=? "
            "AND chapter_id='chapter-01'",
            (project.id,),
        ).fetchone()
    assert dict(fact) == {"value": "线索已出现", "source": "chapter-01"}
    assert len(indexed) == 1
    assert dict(indexed[0]) == {"content": prose, "summary": "主角发现线索"}
    assert json.loads(saved_state["state_json"]) == chapter_state
