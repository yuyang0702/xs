import json

import pytest

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.skill_runtime import SkillContract, SkillRuntimeToolbox, StoryCli


def make_project(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="Book", mode="long", genre="fantasy", premise="An oath.", target_words=100000,
    ))
    return db, project


def test_runtime_rejects_unknown_tools_paths_and_commands(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "character-management", "hash")
    toolbox = SkillRuntimeToolbox(db, project, "run", SkillContract.for_skill("character-management"), StoryCli(project, lambda command: "ok"))

    with pytest.raises(ValueError, match="Unknown runtime tool"):
        toolbox.execute("shell", {"command": "dir"})
    with pytest.raises(ValueError, match="not allowed"):
        toolbox.execute("create_file_proposal", {"relative_path": "../outside.md", "content": "x"})
    with pytest.raises(ValueError, match="not allowed"):
        toolbox.execute("create_file_proposal", {"relative_path": "worldbuilding/x.md", "content": "x"})
    with pytest.raises(ValueError, match="Story command"):
        toolbox.execute("run_story_command", {"command": "exec", "arguments": []})


def test_story_command_schema_lists_runtime_subcommands(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "story-init", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("story-init"),
        StoryCli(project, lambda command: "ok"),
    )

    definition = next(item for item in toolbox.definitions() if item.name == "run_story_command")

    assert definition.input_schema["properties"]["command"]["enum"] == [
        "reindex", "links", "validate", "wordcount",
    ]


def test_runtime_applies_allowed_proposals_and_story_validation(tmp_path) -> None:
    db, project = make_project(tmp_path)
    commands = []
    db.create_skill_execution("run", project.id, "character-management", "hash")
    toolbox = SkillRuntimeToolbox(db, project, "run", SkillContract.for_skill("character-management"), StoryCli(project, lambda command: commands.append(command) or "ok"))
    content = "---\nname: Lin\nrole: protagonist\n---\n\n# Lin\n"
    toolbox.execute("create_file_proposal", {"relative_path": "characters/lin.md", "content": content, "facts": {"protagonist.name": "Lin"}})

    toolbox.apply()

    assert (project.path / "characters" / "lin.md").read_text(encoding="utf-8") == content
    assert [item[0] for item in commands] == ["reindex", "links", "validate"]
    assert db.list_file_proposals("run")[0]["status"] == "applied"


def test_runtime_lock_conflict_creates_change_request(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.save_lock(project.id, "protagonist.name", "Lin", "wizard")
    db.create_skill_execution("run", project.id, "character-management", "hash")
    toolbox = SkillRuntimeToolbox(db, project, "run", SkillContract.for_skill("character-management"), StoryCli(project, lambda command: "ok"))

    with pytest.raises(PermissionError, match="locked"):
        toolbox.execute("create_file_proposal", {
            "relative_path": "characters/hero.md", "content": "---\nname: Chen\n---\n",
            "facts": {"protagonist.name": "Chen"},
        })

    assert db.list_change_requests(project.id)[0]["proposed"] == "Chen"


def test_runtime_rolls_back_when_validation_fails(tmp_path) -> None:
    db, project = make_project(tmp_path)
    original = (project.path / "characters" / "_index.md").read_text(encoding="utf-8")
    db.create_skill_execution("run", project.id, "character-management", "hash")
    def runner(command):
        if command[0] == "validate":
            raise RuntimeError("invalid links")
        return "ok"
    toolbox = SkillRuntimeToolbox(db, project, "run", SkillContract.for_skill("character-management"), StoryCli(project, runner))
    toolbox.execute("create_file_proposal", {
        "relative_path": "characters/_index.md", "content": "---\ntype: character-registry\n---\nchanged",
    })

    with pytest.raises(RuntimeError, match="invalid links"):
        toolbox.apply()

    assert (project.path / "characters" / "_index.md").read_text(encoding="utf-8") == original
