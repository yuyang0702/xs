import json

import pytest

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore


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
    assert store.load_constraints(project.id).startswith("Never use canned AI prose.")


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


def test_project_slug_cannot_escape_workspace(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    with pytest.raises(ValueError):
        store.create(ProjectCreate(title="..", mode="short", genre="test", premise="test", target_words=1000))
