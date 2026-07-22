import json
from types import SimpleNamespace

import pytest

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.skill_runtime import SkillContract, SkillRuntimeService, SkillRuntimeToolbox, StoryCli


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


def test_entity_schema_guides_model_and_plural_aliases_work(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "story-init", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("story-init"),
        StoryCli(project, lambda command: "ok"),
    )
    definition = next(item for item in toolbox.definitions() if item.name == "list_story_entities")

    assert definition.input_schema["properties"]["entity_type"]["enum"] == [
        "character", "location", "system", "arc", "chapter", "scene", "faction", "artifact",
    ]
    assert toolbox.execute("list_story_entities", {"entity_type": "characters"}) == {"items": []}
    assert toolbox.execute("list_story_entities", {"entity_type": "chapters"}) == {"items": []}


def test_runtime_applies_allowed_proposals_and_story_validation(tmp_path) -> None:
    db, project = make_project(tmp_path)
    commands = []
    historical_index = project.path / "snapshots" / "old" / "files" / "plot" / "_index.md"
    historical_index.parent.mkdir(parents=True)
    historical_index.write_text("historical", encoding="utf-8")
    db.create_skill_execution("run", project.id, "character-management", "hash")
    toolbox = SkillRuntimeToolbox(db, project, "run", SkillContract.for_skill("character-management"), StoryCli(project, lambda command: commands.append(command) or "ok"))
    content = "---\nname: Lin\nrole: protagonist\n---\n\n# Lin\n"
    toolbox.execute("create_file_proposal", {"relative_path": "characters/lin.md", "content": content, "facts": {"protagonist.name": "Lin"}})

    toolbox.apply()

    assert (project.path / "characters" / "lin.md").read_text(encoding="utf-8") == content
    assert [item[0] for item in commands] == ["reindex", "links", "validate"]
    assert db.list_file_proposals("run")[0]["status"] == "applied"
    manifest = json.loads((project.path / "snapshots" / "skill-run" / "manifest.json").read_text(encoding="utf-8"))
    assert not any(item["path"].startswith("snapshots/") for item in manifest)


def test_runtime_applies_latest_duplicate_proposal_without_shifting_other_files(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "plot-structure", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("plot-structure"),
        StoryCli(project, lambda command: "ok"),
    )
    toolbox.execute("create_file_proposal", {
        "relative_path": "plot/arcs/main.md",
        "content": "---\nname: First\ntype: main\n---\n# First\n",
    })
    toolbox.execute("update_file_proposal", {
        "relative_path": "plot/arcs/main.md",
        "content": "---\nname: Final\ntype: main\n---\n# Final\n",
    })
    toolbox.execute("update_file_proposal", {
        "relative_path": "plot/timeline.md",
        "content": "---\ntype: wrong\nstory: wrong\n---\n# Final Timeline\n",
    })

    toolbox.apply()

    assert "# Final\n" in (project.path / "plot" / "arcs" / "main.md").read_text(encoding="utf-8")
    timeline = (project.path / "plot" / "timeline.md").read_text(encoding="utf-8")
    assert "type: timeline" in timeline
    assert "# Final Timeline\n" in timeline
    proposals = db.list_file_proposals("run")
    assert [item["status"] for item in proposals] == ["superseded", "applied", "applied"]


def test_runtime_canonicalizes_story_id_in_proposals(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "story-init", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("story-init"),
        StoryCli(project, lambda command: "ok"),
    )

    toolbox.execute("update_file_proposal", {
        "relative_path": "plot/timeline.md",
        "content": "---\ntype: wrong\nstory: wrong\n---\n# Timeline\n",
    })

    proposal = db.list_file_proposals("run")[0]
    assert f"story: {project.id}" in proposal["content"]
    assert "story: wrong" not in proposal["content"]
    assert "type: timeline" in proposal["content"]
    assert "type: wrong" not in proposal["content"]


def test_runtime_rejects_frontmatter_the_story_cli_cannot_parse(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "character-management", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("character-management"),
        StoryCli(project, lambda command: "ok"),
    )

    with pytest.raises(ValueError, match="Unsupported frontmatter line"):
        toolbox.execute("create_file_proposal", {
            "relative_path": "characters/hero.md",
            "content": "---\nname: Hero\nappearance:\n  height: 186cm\n---\n# Hero\n",
        })


def test_bootstrap_runtime_removes_cross_file_references_until_all_skills_exist(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "character-management", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("character-management"),
        StoryCli(project, lambda command: "ok"), bootstrap=True,
    )
    toolbox.execute("create_file_proposal", {
        "relative_path": "characters/hero.md",
        "content": (
            "---\nname: Hero\nrole: protagonist\nstatus: alive\n"
            "relationships:\n  - character: rival\n    type: enemy\n"
            "locations:\n  - missing-place\ntags:\n  - lead\n---\n# Hero\n"
        ),
    })

    content = db.list_file_proposals("run")[0]["content"]
    assert "relationships:" not in content
    assert "locations:" not in content
    assert "tags:\n  - lead" in content


def test_bootstrap_runtime_does_not_offer_interactive_question_tool(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "story-init", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("story-init"),
        StoryCli(project, lambda command: "ok"), bootstrap=True,
    )

    assert "request_user_input" not in {tool.name for tool in toolbox.definitions()}


def test_runtime_loads_bounded_skill_reference_markdown(tmp_path) -> None:
    skill_path = tmp_path / "character-management"
    references = skill_path / "references"
    references.mkdir(parents=True)
    (references / "template.md").write_text("# Character Template", encoding="utf-8")
    (references / "notes.txt").write_text("ignore", encoding="utf-8")
    skill = SimpleNamespace(path=skill_path)

    context = SkillRuntimeService._reference_context(skill)

    assert "REFERENCE: references/template.md" in context
    assert "# Character Template" in context
    assert "notes.txt" not in context


def test_story_cli_uses_ascii_project_id_without_changing_display_title(tmp_path) -> None:
    db, project = make_project(tmp_path)
    original = (project.path / "story.md").read_text(encoding="utf-8")

    class Skills:
        def skills(self, project_root):
            return {"story-maintenance": SimpleNamespace(executable=True)}

        def run_required(self, stage, required, commands, cwd, project_root):
            during = (project.path / "story.md").read_text(encoding="utf-8")
            assert f"title: {project.id}" in during
            return SimpleNamespace(receipts=[SimpleNamespace(output="ok")])

    service = SkillRuntimeService(db, None, None, Skills())

    assert service._run_story_cli(project, ["validate", "."]) == "ok"
    assert (project.path / "story.md").read_text(encoding="utf-8") == original


def test_runtime_only_auto_finalizes_when_proposals_exist(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "story-init", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("story-init"),
        StoryCli(project, lambda command: "ok"),
    )

    assert toolbox.finalize_on_tool_limit() is None
    toolbox.execute("update_file_proposal", {
        "relative_path": "story.md", "content": "---\ntitle: Book\n---\n# Book\n",
    })

    assert toolbox.finalize_on_tool_limit() == "Generated proposals are ready for local validation"


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
    original_plot = (project.path / "plot" / "_index.md").read_text(encoding="utf-8")
    db.create_skill_execution("run", project.id, "character-management", "hash")
    def runner(command):
        if command[0] == "reindex":
            (project.path / "plot" / "_index.md").write_text("changed by reindex", encoding="utf-8")
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
    assert (project.path / "plot" / "_index.md").read_text(encoding="utf-8") == original_plot
