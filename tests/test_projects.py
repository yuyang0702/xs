import json

import pytest

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.outlines import OutlineService
from novel_flywheel.story_state import StoryStateStore


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
