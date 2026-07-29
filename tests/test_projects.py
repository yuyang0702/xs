import json

import pytest

import novel_flywheel.projects as projects_module
from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.outlines import OutlineService
from novel_flywheel.storage import ProjectSnapshot
from novel_flywheel.story_state import StoryStateStore


def _register_existing_project(
    db, workspace, project_id, mode, extra_metadata=None,
):
    path = workspace / project_id
    (path / "memory").mkdir(parents=True)
    (path / "manuscript").mkdir()
    payload = {
        "id": project_id,
        "title": project_id,
        "mode": mode,
        "genre": "suspense",
        "premise": "legacy project",
        "target_words": 8_000,
        **(extra_metadata or {}),
    }
    original = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    project_json = path / "project.json"
    project_json.write_bytes(original)
    db.save_project(project_id, project_id, mode, path)
    return path, project_json, original


def test_create_short_project_writes_durable_structure(tmp_path) -> None:
    constraint = tmp_path / "global-rules.md"
    constraint.write_text("Never use canned AI prose.", encoding="utf-8")
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace", [constraint])

    project = store.create(ProjectCreate(
        title="The Last Train", mode="short", genre="suspense", premise="A missing passenger returns.",
        target_words=8000, pov="first", tone="restrained", must_include="a brass ticket",
        must_avoid="dream ending",
    ))

    assert project.path.parent == tmp_path / "workspace"
    metadata = json.loads((project.path / "project.json").read_text(encoding="utf-8"))
    assert metadata["mode"] == "short"
    assert metadata["optimized_local_review_enabled"] is True
    assert metadata["root_constraints"] == [str(constraint.resolve())]
    assert (project.path / "constraints.md").is_file()
    assert json.loads((project.path / "memory" / "canon.json").read_text(encoding="utf-8")) == {"facts": []}
    assert (project.path / "manuscript").is_dir()
    assert (project.path / "story.md").is_file()
    assert (project.path / "chapters" / "_index.md").is_file()
    assert f"story: {project.id}" in (project.path / "chapters" / "_index.md").read_text(encoding="utf-8")
    assert f"story: {project.id}" in (project.path / "plot" / "timeline.md").read_text(encoding="utf-8")
    assert f"story: {project.id}" in (project.path / "continuity" / "state.md").read_text(encoding="utf-8")
    assert (project.path / "continuity" / "state.md").is_file()
    assert store.load_constraints(project.id).startswith("Never use canned AI prose.")
    state = StoryStateStore(db).get(project.id)
    assert state is not None
    assert state.revision == 1
    assert state.data["manuscript_revision"] == 0


def test_long_project_has_chapter_and_volume_folders(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Long Book", mode="long", genre="fantasy", premise="An oath survives dynasties.",
        target_words=1_000_000,
    ))
    assert (project.path / "chapters").is_dir()
    assert (project.path / "volumes").is_dir()
    assert "optimized_local_review_enabled" not in project.metadata


def test_existing_short_missing_optimized_review_flag_migrates_once(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    workspace = tmp_path / "workspace"
    path, project_json, original = _register_existing_project(
        db, workspace, "missing-flag", "short",
        {"custom": {"kept": ["原值", 7]}},
    )

    store = ProjectStore(db, workspace)

    snapshot_root = path / "snapshots" / "optimized-review-default"
    snapshot_json = snapshot_root / "files" / "project.json"
    migrated = json.loads(project_json.read_text(encoding="utf-8"))
    assert store.get("missing-flag").metadata == migrated
    assert migrated["optimized_local_review_enabled"] is True
    assert migrated["custom"] == {"kept": ["原值", 7]}
    assert snapshot_json.read_bytes() == original
    assert (snapshot_root / "manifest.json").is_file()
    first_project = project_json.read_bytes()
    first_snapshot = snapshot_json.read_bytes()
    first_project_mtime = project_json.stat().st_mtime_ns
    first_snapshot_mtime = snapshot_json.stat().st_mtime_ns

    ProjectStore(db, workspace)

    assert project_json.read_bytes() == first_project
    assert snapshot_json.read_bytes() == first_snapshot
    assert project_json.stat().st_mtime_ns == first_project_mtime
    assert snapshot_json.stat().st_mtime_ns == first_snapshot_mtime


@pytest.mark.parametrize(
    ("mode", "stored_flag"),
    [("short", False), ("short", True), ("long", None)],
)
def test_optimized_review_migration_preserves_explicit_and_long_values(
    tmp_path, mode, stored_flag,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    workspace = tmp_path / "workspace"
    extra = {"other": "preserved"}
    if stored_flag is not None:
        extra["optimized_local_review_enabled"] = stored_flag
    path, project_json, original = _register_existing_project(
        db, workspace, f"{mode}-{stored_flag}", mode, extra,
    )
    before_mtime = project_json.stat().st_mtime_ns

    store = ProjectStore(db, workspace)

    assert project_json.read_bytes() == original
    assert project_json.stat().st_mtime_ns == before_mtime
    assert not (
        path / "snapshots" / "optimized-review-default"
    ).exists()
    metadata = store.get(f"{mode}-{stored_flag}").metadata
    assert metadata["other"] == "preserved"
    if stored_flag is None:
        assert "optimized_local_review_enabled" not in metadata
    else:
        assert metadata["optimized_local_review_enabled"] is stored_flag


def test_optimized_review_migration_resumes_after_atomic_write_interruption(
    tmp_path, monkeypatch,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    workspace = tmp_path / "workspace"
    path, project_json, original = _register_existing_project(
        db, workspace, "interrupted", "short",
    )
    snapshot_json = (
        path / "snapshots" / "optimized-review-default"
        / "files" / "project.json"
    )
    real_atomic_write = projects_module.atomic_write

    def interrupt_write(target, content):
        assert target == project_json
        assert snapshot_json.read_bytes() == original
        raise OSError("simulated migration interruption")

    monkeypatch.setattr(projects_module, "atomic_write", interrupt_write)
    with pytest.raises(OSError, match="simulated migration interruption"):
        ProjectStore(db, workspace)

    assert project_json.read_bytes() == original
    snapshot_before = snapshot_json.read_bytes()
    snapshot_mtime = snapshot_json.stat().st_mtime_ns
    monkeypatch.setattr(projects_module, "atomic_write", real_atomic_write)

    recovered = ProjectStore(db, workspace)

    assert recovered.get("interrupted").metadata[
        "optimized_local_review_enabled"
    ] is True
    assert snapshot_json.read_bytes() == snapshot_before
    assert snapshot_json.stat().st_mtime_ns == snapshot_mtime


@pytest.mark.parametrize("damage", ["snapshot", "target"])
def test_optimized_review_migration_refuses_damaged_interrupted_state(
    tmp_path, damage,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    workspace = tmp_path / "workspace"
    path, project_json, _original = _register_existing_project(
        db, workspace, f"damaged-{damage}", "short",
    )
    snapshot_root = path / "snapshots" / "optimized-review-default"
    ProjectSnapshot.create(path, snapshot_root, [project_json])
    snapshot_json = snapshot_root / "files" / "project.json"
    if damage == "snapshot":
        snapshot_json.write_text("{broken", encoding="utf-8")
    else:
        changed = json.loads(project_json.read_text(encoding="utf-8"))
        changed["edited_after_snapshot"] = True
        project_json.write_text(
            json.dumps(changed, ensure_ascii=False), encoding="utf-8",
        )
    project_before = project_json.read_bytes()
    snapshot_before = snapshot_json.read_bytes()

    with pytest.raises(ValueError, match="snapshot"):
        ProjectStore(db, workspace)

    assert project_json.read_bytes() == project_before
    assert snapshot_json.read_bytes() == snapshot_before


def test_project_store_rejects_registered_path_outside_workspace_before_migration(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path, project_json, original = _register_existing_project(
        db, tmp_path / "outside", "outside-short", "short",
    )
    before_mtime = project_json.stat().st_mtime_ns

    with pytest.raises(ValueError, match="项目路径不在工作区内") as error:
        ProjectStore(db, workspace)

    assert str(path.resolve()) not in str(error.value)
    assert project_json.read_bytes() == original
    assert project_json.stat().st_mtime_ns == before_mtime
    assert not (
        path / "snapshots" / "optimized-review-default"
    ).exists()
    assert StoryStateStore(db).get("outside-short") is None


@pytest.mark.parametrize(
    ("project_id", "metadata_override"),
    [
        pytest.param(
            "wrong-id",
            {
                "id": "another-project",
                "optimized_local_review_enabled": False,
            },
            id="explicit-flag-with-wrong-id",
        ),
        pytest.param(
            "wrong-mode",
            {"mode": "long"},
            id="database-short-with-json-long",
        ),
    ],
)
def test_project_store_rejects_mismatched_metadata_before_migration(
    tmp_path, project_id, metadata_override,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    workspace = tmp_path / "workspace"
    path, project_json, original = _register_existing_project(
        db, workspace, project_id, "short", metadata_override,
    )
    before_mtime = project_json.stat().st_mtime_ns

    with pytest.raises(
        ValueError, match="项目元数据与登记信息不一致",
    ) as error:
        ProjectStore(db, workspace)

    assert str(path.resolve()) not in str(error.value)
    assert project_json.read_bytes() == original
    assert project_json.stat().st_mtime_ns == before_mtime
    assert not (
        path / "snapshots" / "optimized-review-default"
    ).exists()
    assert StoryStateStore(db).get(project_id) is None


def test_project_store_imports_story_state_for_existing_projects(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    path = tmp_path / "workspace" / "legacy"
    (path / "memory").mkdir(parents=True)
    (path / "manuscript").mkdir()
    (path / "memory" / "canon.json").write_text('{"facts": []}', encoding="utf-8")
    db.save_project("legacy", "Legacy", "short", path)

    ProjectStore(db, tmp_path / "workspace")

    assert StoryStateStore(db).get("legacy") is not None


def test_project_slug_cannot_escape_workspace(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    with pytest.raises(ValueError):
        store.create(ProjectCreate(title="..", mode="short", genre="test", premise="test", target_words=1000))


def test_project_trash_restore_and_permanent_delete(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Keep Me", mode="long", genre="fantasy", premise="An oath.", target_words=100000,
    ))
    original = project.path
    (original / "chapters" / "chapter-01.md").write_text("chapter", encoding="utf-8")

    trashed = store.trash(project.id)
    assert store.list() == []
    assert trashed["path"].parent == tmp_path / "trash"
    assert (trashed["path"] / "chapters" / "chapter-01.md").is_file()

    restored = store.restore(project.id)
    assert restored.path == original
    assert (restored.path / "chapters" / "chapter-01.md").is_file()

    store.trash(project.id)
    store.delete_permanently(project.id)
    assert store.list_trash() == []
    assert not (tmp_path / "trash" / project.id).exists()


def test_cancelled_run_does_not_hide_project_and_trash_rejects_outside_path(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Continue", mode="long", genre="fantasy", premise="An oath.", target_words=100000,
    ))
    db.create_run("run", project.id, "long-chapter", status="cancelled")
    assert store.list()[0].id == project.id

    outside = tmp_path / "outside"
    outside.mkdir()
    db.update_project_path(project.id, outside)
    with pytest.raises(ValueError, match="outside"):
        store.trash(project.id)


def test_project_with_active_run_cannot_be_trashed(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Running", mode="long", genre="fantasy", premise="An oath.", target_words=100000,
    ))
    db.create_run("run", project.id, "long-chapter", status="running")

    with pytest.raises(ValueError, match="active run"):
        store.trash(project.id)


def test_current_confirmed_outline_is_loaded_as_a_creation_constraint(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Follow Outline", mode="short", genre="suspense",
        premise="A friend returns.", target_words=8_000,
    ))
    outlines = OutlineService(db, store)
    candidate = outlines.create_candidate(
        project.id, "# 正式大纲\n\n## 开头\n主角收到死者来信。\n",
    )
    outlines.apply_candidate(project.id, candidate["id"])

    constraints = store.load_constraints(project.id)

    assert "# Current Confirmed Outline" in constraints
    assert "主角收到死者来信" in constraints
