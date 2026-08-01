import json
import hashlib
from types import SimpleNamespace

import pytest

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.skill_runtime import (
    SkillContract, SkillRuntimeService, SkillRuntimeToolbox, StoryCli,
    expected_initialization_characters, initialization_stage_issues,
    initialization_answers, initialization_context_hash,
)


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
    with pytest.raises(ValueError, match="file proposal"):
        toolbox.execute("complete_skill", {"summary": "done"})


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


def test_story_init_cannot_create_a_second_title_directory(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "story-init", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("story-init"),
        StoryCli(project, lambda command: "ok"), bootstrap=True,
    )

    with pytest.raises(ValueError, match="not allowed"):
        toolbox.execute("update_registry_proposal", {
            "relative_path": "book/characters/_index.md",
            "content": "---\ntype: character-registry\n---\n# Characters\n",
        })


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


def test_runtime_normalizes_character_role_and_empty_aliases(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "character-management", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("character-management"),
        StoryCli(project, lambda command: "ok"),
    )

    toolbox.execute("create_file_proposal", {
        "relative_path": "characters/pei-yan-xing.md",
        "content": (
            "---\nname: 裴砚行\nrole: counterpart\naliases:\n"
            "  - \"\"\n  - \"裴公子\"\n  - 裴公子\n---\n# 裴砚行\n"
        ),
    })
    toolbox.execute("update_registry_proposal", {
        "relative_path": "characters/_index.md",
        "content": (
            "---\ntype: character-registry\n---\n# Characters\n\n"
            "| Name | Role | Status | File |\n|---|---|---|---|\n"
            "| 裴砚行 | counterpart | alive | pei-yan-xing.md |\n"
        ),
    })

    proposals = {item["relative_path"]: item["content"]
                 for item in db.list_file_proposals("run")}
    profile = proposals["characters/pei-yan-xing.md"]
    assert "role: deuteragonist" in profile
    assert 'aliases:\n  - "裴公子"\n' in profile
    assert '  - ""' not in profile
    assert "| 裴砚行 | deuteragonist |" in proposals["characters/_index.md"]


def test_runtime_removes_aliases_field_when_every_alias_is_empty(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "character-management", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("character-management"),
        StoryCli(project, lambda command: "ok"),
    )

    toolbox.execute("create_file_proposal", {
        "relative_path": "characters/shen-da-xiaojie.md",
        "content": (
            "---\nname: 沈大小姐\nrole: supporting\naliases:\n"
            "  - \"\"\n  - '   '\ntags:\n  - 闺秀\n---\n# 沈大小姐\n"
        ),
    })

    content = db.list_file_proposals("run")[0]["content"]
    assert "aliases:" not in content
    assert "tags:\n  - 闺秀" in content


def test_character_initialization_prompt_uses_story_role_values() -> None:
    instruction = SkillRuntimeService._initialization_instruction(
        "character-management", {},
    )

    assert "deuteragonist" in instruction
    assert "Omit aliases" in instruction
    assert "one relationship entry per target character" in instruction
    assert "future location references" in instruction


def test_initialization_answers_normalizes_cached_outline_manifest(tmp_path) -> None:
    _db, project = make_project(tmp_path)
    outline = "# 大纲\n\n### 第一幕：错入高门（约3000字）\n"
    cache = project.path / "memory" / "outline-manifest.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({
        "outline_hash": hashlib.sha256(outline.encode("utf-8")).hexdigest(),
        "manifest": {
            "plot_arcs": [
                {"name": "第一幕：错入高门（约3000字）", "evidence": "同一幕"},
                {"name": "第一幕：错入高门", "evidence": "同一幕"},
            ],
            "questions": [
                {"name": "花穗被人带回沈府并错认成三小姐", "evidence": "同一问题"},
                {"name": "花穗为何被错认？", "evidence": "同一问题"},
            ],
        },
    }, ensure_ascii=False), encoding="utf-8")

    answers = initialization_answers(project, {
        "content": outline, "outline_version": 1, "events": [],
    })

    assert [item["name"] for item in answers["outline_manifest"]["plot_arcs"]] == [
        "第一幕：错入高门",
    ]
    assert [item["name"] for item in answers["outline_manifest"]["questions"]] == [
        "花穗为何被错认？",
    ]


def test_initialization_answers_rebuilds_legacy_outline_event_cache(tmp_path) -> None:
    _db, project = make_project(tmp_path)
    outline = (
        "# 大纲\n\n**真实事件**：主角发现线索。\n"
        "<!-- **模板事件**：只是示例。 -->\n"
    )

    answers = initialization_answers(project, {
        "content": outline,
        "outline_version": 1,
        "events": [{
            "id": "EV-DEADBEEF", "order": 99,
            "label": "模板事件", "section": "",
        }],
    })

    events = answers["confirmed_outline"]["events"]
    assert [item["label"] for item in events] == ["真实事件"]
    assert all(item["id"] != "EV-DEADBEEF" for item in events)


def test_bootstrap_character_preflight_rejects_ambiguous_relationships(tmp_path) -> None:
    _db, project = make_project(tmp_path)
    answers = {"outline_manifest": {"characters": [
        {"name": "花穗", "role": "protagonist"},
        {"name": "裴砚行", "role": "deuteragonist"},
    ]}}
    proposals = [
        {
            "relative_path": "characters/hua-sui.md",
            "content": (
                "---\nname: 花穗\nrole: protagonist\nrelationships:\n"
                "  - character: pei-yan-xing\n    type: rival\n"
                "  - character: pei-yan-xing\n    type: love-interest\n"
                "locations:\n  - shen-fu\n---\n# 花穗\n"
            ),
            "status": "pending",
        },
        {
            "relative_path": "characters/pei-yan-xing.md",
            "content": (
                "---\nname: 裴砚行\nrole: deuteragonist\nrelationships:\n"
                "  - character: hua-sui\n    type: rival\n"
                "---\n# 裴砚行\n"
            ),
            "status": "pending",
        },
        {
            "relative_path": "characters/_index.md",
            "content": (
                "---\ntype: character-registry\n---\n# Characters\n\n"
                "## Relationship Map\n\n花穗与裴砚行：欢喜冤家。\n"
            ),
            "status": "pending",
        },
    ]

    issues = initialization_stage_issues(
        project, "character-management", answers, proposals,
    )

    assert any("同一对象只能登记一种关系" in issue for issue in issues)
    assert not any("shen-fu" in issue for issue in issues)


def test_bootstrap_character_preflight_rejects_wrong_inverse_relationship(tmp_path) -> None:
    _db, project = make_project(tmp_path)
    answers = {"outline_manifest": {"characters": [
        {"name": "花穗", "role": "protagonist"},
        {"name": "裴砚行", "role": "deuteragonist"},
    ]}}
    proposals = [
        {
            "relative_path": "characters/hua-sui.md",
            "content": (
                "---\nname: 花穗\nrole: protagonist\nrelationships:\n"
                "  - character: pei-yan-xing\n    type: love-interest\n"
                "---\n# 花穗\n"
            ),
            "status": "pending",
        },
        {
            "relative_path": "characters/pei-yan-xing.md",
            "content": (
                "---\nname: 裴砚行\nrole: deuteragonist\nrelationships:\n"
                "  - character: hua-sui\n    type: rival\n"
                "---\n# 裴砚行\n"
            ),
            "status": "pending",
        },
        {
            "relative_path": "characters/_index.md",
            "content": (
                "---\ntype: character-registry\n---\n# Characters\n\n"
                "## Relationship Map\n\n花穗与裴砚行：欢喜冤家。\n"
            ),
            "status": "pending",
        },
    ]

    issues = initialization_stage_issues(
        project, "character-management", answers, proposals,
    )

    assert any("反向关系类型不一致" in issue for issue in issues)


def test_bootstrap_character_apply_defers_forward_location_links(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "character-management", "hash")
    commands = []

    def runner(command):
        commands.append(command[0])
        if command[0] == "links":
            raise RuntimeError("forward location does not exist yet")
        return "ok"

    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("character-management"),
        StoryCli(project, runner), bootstrap=True,
        answers={"outline_manifest": {"characters": [
            {"name": "花穗", "role": "protagonist"},
            {"name": "裴砚行", "role": "deuteragonist"},
        ]}},
    )
    toolbox.execute("create_file_proposal", {
        "relative_path": "characters/hua-sui.md",
        "content": (
            "---\nname: 花穗\nrole: protagonist\nrelationships:\n"
            "  - character: pei-yan-xing\n    type: love-interest\n"
            "locations:\n  - shen-fu\n---\n# 花穗\n"
        ),
    })
    toolbox.execute("create_file_proposal", {
        "relative_path": "characters/pei-yan-xing.md",
        "content": (
            "---\nname: 裴砚行\nrole: deuteragonist\nrelationships:\n"
            "  - character: hua-sui\n    type: love-interest\n"
            "locations:\n  - shen-fu\n---\n# 裴砚行\n"
        ),
    })
    toolbox.execute("update_registry_proposal", {
        "relative_path": "characters/_index.md",
        "content": (
            "---\ntype: character-registry\n---\n# Characters\n\n"
            "[花穗](hua-sui.md)\n[裴砚行](pei-yan-xing.md)\n\n"
            "## Relationship Map\n\n花穗与裴砚行：爱慕。\n"
        ),
    })

    toolbox.apply()

    assert commands == ["reindex", "validate"]


def test_bootstrap_runtime_preserves_character_relationships_and_locations(tmp_path) -> None:
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
    assert "relationships:\n  - character: rival\n    type: enemy" in content
    assert "locations:\n  - missing-place" in content
    assert "tags:\n  - lead" in content


def test_bootstrap_runtime_preserves_artifact_relationships(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "worldbuilding", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("worldbuilding"),
        StoryCli(project, lambda command: "ok"), bootstrap=True,
    )

    toolbox.execute("create_file_proposal", {
        "relative_path": "worldbuilding/artifacts/converter.md",
        "content": (
            "---\nname: Converter\ntype: technology\nstatus: active\n"
            "owner: missing-owner\nlocation: office\ntags:\n  - device\n"
            "---\n# Converter\n"
        ),
    })

    content = db.list_file_proposals("run")[0]["content"]
    assert "owner: missing-owner" in content
    assert "location: office" in content
    assert "tags:\n  - device" in content


def test_bootstrap_runtime_removes_future_chapter_links_from_promises(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "plot-structure", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("plot-structure"),
        StoryCli(project, lambda command: "ok"), bootstrap=True,
    )

    toolbox.execute("create_file_proposal", {
        "relative_path": "continuity/promises/oath.md",
        "content": (
            "---\ntitle: Oath\nstatus: planned\nplanted: chapter-05\n"
            "payoff: chapter-16\ncharacters:\n  - hero\n---\n"
            "\n# Oath\n\n第5章埋下承诺，第16章兑现。\n"
        ),
    })

    content = db.list_file_proposals("run")[0]["content"]
    assert "planted:" not in content
    assert "payoff:" not in content
    assert "characters:\n  - hero" in content
    assert "第5章埋下承诺，第16章兑现。" in content


def test_bootstrap_runtime_removes_all_future_chapter_references(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "plot-structure", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("plot-structure"),
        StoryCli(project, lambda command: "ok"), bootstrap=True,
    )

    toolbox.execute("create_file_proposal", {
        "relative_path": "continuity/questions/source.md",
        "content": (
            "---\ntitle: 匿名信来源\nstatus: open\nintroduced: chapter-05\n"
            "resolved: chapter-08\ncharacters:\n  - hero\n---\n\n"
            "# 匿名信来源\n\n计划在[第5章](../../chapters/chapter-05.md)提出。\n"
        ),
    })

    content = db.list_file_proposals("run")[0]["content"]
    assert "introduced:" not in content
    assert "resolved:" not in content
    assert "characters:\n  - hero" in content
    assert "chapters/chapter-05.md" not in content
    assert "计划在第5章提出。" in content


def test_bootstrap_runtime_keeps_markdown_links_to_existing_chapters(tmp_path) -> None:
    db, project = make_project(tmp_path)
    chapter = project.path / "chapters" / "chapter-01.md"
    chapter.write_text("---\ntitle: 第一章\n---\n# 第一章\n", encoding="utf-8")
    db.create_skill_execution("run", project.id, "plot-structure", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("plot-structure"),
        StoryCli(project, lambda command: "ok"), bootstrap=True,
    )

    toolbox.execute("create_file_proposal", {
        "relative_path": "continuity/questions/source.md",
        "content": (
            "---\ntitle: 已出现的问题\nstatus: open\n---\n\n"
            "# 已出现的问题\n\n在[第一章](../../chapters/chapter-01.md)提出。\n"
        ),
    })

    assert "../../chapters/chapter-01.md" in db.list_file_proposals("run")[0]["content"]


def test_bootstrap_runtime_removes_future_death_chapter_from_characters(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "character-management", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("character-management"),
        StoryCli(project, lambda command: "ok"), bootstrap=True,
    )

    toolbox.execute("create_file_proposal", {
        "relative_path": "characters/hero.md",
        "content": "---\nname: 主角\nrole: protagonist\nstatus: alive\ndied-in: chapter-09\n---\n# 主角\n",
    })

    assert "died-in:" not in db.list_file_proposals("run")[0]["content"]


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


@pytest.mark.asyncio
async def test_runtime_prompt_names_project_relative_writable_paths(tmp_path) -> None:
    db, project = make_project(tmp_path)

    class Skills:
        def skills(self, project_root):
            return {
                "character-management": SimpleNamespace(
                    name="character-management", content_hash="hash",
                    instructions="Create the confirmed characters.", path=tmp_path,
                ),
                "story-maintenance": SimpleNamespace(executable=True),
            }

        def run_required(self, stage, required, commands, cwd, project_root):
            return SimpleNamespace(receipts=[SimpleNamespace(output="ok")])

    class Gateway:
        async def complete_with_tools(self, role, system, user, toolbox, **kwargs):
            assert "characters/*.md" in system
            assert "Never prefix a path with the project title" in system
            assert "must never override the confirmed outline" in system
            assert "never create or update plot/outline.md" in system
            toolbox.execute("create_file_proposal", {
                "relative_path": "characters/hero.md",
                "content": "---\nname: Hero\n---\n# Hero\n",
            })
            toolbox.execute("update_registry_proposal", {
                "relative_path": "characters/_index.md",
                "content": (
                    "---\ntype: character-registry\n---\n# Characters\n\n"
                    "| Name | Role | Status | File |\n|---|---|---|---|\n"
                    "| Hero | protagonist | active | [hero.md](hero.md) |\n"
                ),
            })
            return SimpleNamespace(text="done", receipt={"execution_mode": "native_tools"})

    service = SkillRuntimeService(db, ProjectStore(db, tmp_path / "workspace"), Gateway(), Skills())

    result = await service.run(project.id, "character-management", {}, bootstrap=True)

    assert result["status"] == "completed"
    assert (project.path / "characters" / "hero.md").is_file()


def test_bootstrap_character_completion_covers_confirmed_outline_cast(tmp_path) -> None:
    db, project = make_project(tmp_path)
    outline = """# 大纲

## 主要人物

**苏小满（主角）**：冒牌千金。

- **李慕远**：男主。
- **老夫人**：关键配角。
"""
    answers = {"confirmed_outline": {"content": outline}}
    assert expected_initialization_characters(answers) == ["苏小满", "李慕远", "老夫人"]
    db.create_skill_execution("run", project.id, "character-management", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("character-management"),
        StoryCli(project, lambda command: "ok"), bootstrap=True, answers=answers,
    )
    toolbox.execute("create_file_proposal", {
        "relative_path": "characters/su-xiaoman.md",
        "content": "---\nname: 苏小满\nrole: protagonist\n---\n# 苏小满\n",
    })

    with pytest.raises(ValueError, match="李慕远.*老夫人"):
        toolbox.execute("complete_skill", {"summary": "完成"})

    issues = initialization_stage_issues(
        project, "character-management", answers, db.list_file_proposals("run"),
    )
    assert any("人物档案只有 1 份，需要覆盖 3 位主要人物" in issue for issue in issues)


def test_bootstrap_character_completion_does_not_guess_that_two_names_are_aliases(tmp_path) -> None:
    _db, project = make_project(tmp_path)
    (project.path / "characters" / "old-name.md").write_text(
        "---\nname: 柳春杏\nrole: protagonist\naliases:\n  - 花穗\n---\n# 柳春杏\n",
        encoding="utf-8",
    )
    (project.path / "characters" / "_index.md").write_text(
        "---\ntype: character-registry\n---\n# Characters\n\n"
        "| Name | Role | Status | File |\n|---|---|---|---|\n"
        "| 柳春杏 | protagonist | alive | [old-name](old-name.md) |\n",
        encoding="utf-8",
    )
    answers = {
        "confirmed_outline": {"content": "# 大纲\n\n## 人物设定\n\n### 女主（花穗）\n"},
        "outline_manifest": {"characters": [{"name": "花穗", "role": "protagonist"}]},
    }

    issues = initialization_stage_issues(project, "character-management", answers)

    assert any("花穗" in issue and "独立档案" in issue for issue in issues)
    assert any("柳春杏" in issue and "正式大纲为花穗" in issue for issue in issues)


def test_story_init_accepts_confirmed_fields_under_natural_chinese_headings(tmp_path) -> None:
    _db, project = make_project(tmp_path)
    answers = {
        "title": "Book", "genre": "fantasy", "premise": "An oath.",
        "target_words": 100000, "pov": "first", "tone": "幽默风趣",
    }
    story = """---
title: Book
genre: fantasy
pov: first-person
---

## 核心设定
An oath.

## 目标篇幅
100000 字

## 文风
幽默风趣
"""

    issues = initialization_stage_issues(
        project, "story-init", answers,
        [{"relative_path": "story.md", "content": story, "status": "pending"}],
    )

    assert issues == []


def test_story_init_accepts_a_faithful_premise_rewrite(tmp_path) -> None:
    _db, project = make_project(tmp_path)
    answers = {
        "title": "Book", "genre": "fantasy",
        "premise": "一块祖传玉佩让乡野姑娘被错认成豪门失散多年的女儿，真正的千金早已不在人世。",
        "target_words": 100000, "pov": "first", "tone": "幽默风趣",
    }
    story = """---
title: Book
genre: fantasy
pov: first
---

## 故事梗概
乡野姑娘苏小满因为一块祖传玉佩，被容府误认成失散多年的女儿；真正的千金其实早已不在人世。

## 目标篇幅
100000 字

## 文风
幽默风趣
"""

    issues = initialization_stage_issues(
        project, "story-init", answers,
        [{"relative_path": "story.md", "content": story, "status": "pending"}],
    )

    assert issues == []


def test_story_init_reports_the_actual_missing_confirmed_fields(tmp_path) -> None:
    _db, project = make_project(tmp_path)
    answers = {
        "title": "Book", "genre": "fantasy", "premise": "An oath.",
        "target_words": 100000, "pov": "first", "tone": "幽默风趣",
    }
    story = """---
title: Wrong Book
genre: fantasy
pov: first
---

## 核心设定
An oath.

## 文风
幽默风趣
"""

    issues = initialization_stage_issues(
        project, "story-init", answers,
        [{"relative_path": "story.md", "content": story, "status": "pending"}],
    )

    assert any("标题、目标字数" in issue for issue in issues)


def test_bootstrap_world_completion_allows_supporting_locations(tmp_path) -> None:
    _db, project = make_project(tmp_path)
    location = project.path / "worldbuilding" / "locations" / "supporting.md"
    location.write_text("---\nname: 沈府\ntype: building\n---\n# 沈府\n", encoding="utf-8")
    (project.path / "worldbuilding" / "_index.md").write_text(
        "---\ntype: world-registry\n---\n# World\n[supporting](locations/supporting.md)\n",
        encoding="utf-8",
    )

    issues = initialization_stage_issues(project, "worldbuilding", {
        "confirmed_outline": {"content": "# 大纲\n\n故事发生在容府。\n"},
    })

    assert issues == []


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


def test_bootstrap_plot_runtime_cannot_replace_confirmed_outline(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "plot-structure", "hash")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("plot-structure"),
        StoryCli(project, lambda command: "ok"), bootstrap=True,
    )

    with pytest.raises(ValueError, match="正式大纲"):
        toolbox.execute("update_file_proposal", {
            "relative_path": "plot/outline.md",
            "content": "---\ntype: outline\n---\n# 被替换的大纲\n",
        })

    assert db.list_file_proposals("run") == []


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
    assert db.get_skill_execution("run")["status"] == "recoverable"
    assert db.file_proposal_summary("run")["recoverable_count"] == 1


def test_runtime_recovers_complete_bootstrap_proposals_without_complete_tool(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "worldbuilding", "hash", "running")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("worldbuilding"),
        StoryCli(project, lambda command: "ok"), bootstrap=True,
    )
    toolbox.execute("create_file_proposal", {
        "relative_path": "worldbuilding/locations/shen-jia.md",
        "content": "---\nname: 沈家\ntype: family\n---\n# 沈家\n",
    })
    toolbox.execute("update_registry_proposal", {
        "relative_path": "worldbuilding/_index.md",
        "content": (
            "---\ntype: world-registry\n---\n# World\n\n"
            "[沈家](locations/shen-jia.md)\n"
        ),
    })

    assert toolbox.finalize_after_route_error() == (
        "Generated proposals are ready for local validation"
    )
    assert db.get_skill_execution("run")["status"] == "validating"


def test_bootstrap_world_candidates_use_local_reindex_before_final_validation(tmp_path) -> None:
    db, project = make_project(tmp_path)
    (project.path / "worldbuilding" / "_index.md").write_text("", encoding="utf-8")
    db.create_skill_execution("run", project.id, "worldbuilding", "hash", "running")

    def runner(command):
        if command[0] == "reindex":
            (project.path / "worldbuilding" / "_index.md").write_text(
                "---\ntype: world-registry\n---\n# World\n"
                "[沈家](locations/shen-jia.md)\n",
                encoding="utf-8",
            )
        return "ok"

    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("worldbuilding"),
        StoryCli(project, runner), bootstrap=True,
    )
    toolbox.execute("create_file_proposal", {
        "relative_path": "worldbuilding/locations/shen-jia.md",
        "content": "---\nname: 沈家\ntype: family\n---\n# 沈家\n",
    })

    assert toolbox.finalize_after_route_error() == (
        "Generated proposals are ready for local validation"
    )
    toolbox.apply()

    assert db.get_skill_execution("run")["status"] == "completed"
    assert db.list_file_proposals("run")[0]["status"] == "applied"


def test_bootstrap_local_reindex_does_not_guess_character_relationships(tmp_path) -> None:
    _db, project = make_project(tmp_path)
    answers = {
        "outline_manifest": {"characters": [
            {"name": "沈明珠", "role": "protagonist"},
            {"name": "裴砚行", "role": "deuteragonist"},
        ]},
    }
    proposals = [
        {
            "relative_path": "characters/shen-mingzhu.md",
            "content": "---\nname: 沈明珠\nrole: protagonist\n---\n# 沈明珠\n",
            "status": "pending",
        },
        {
            "relative_path": "characters/pei-yanxing.md",
            "content": "---\nname: 裴砚行\nrole: deuteragonist\n---\n# 裴砚行\n",
            "status": "pending",
        },
    ]

    issues = initialization_stage_issues(
        project, "character-management", answers, proposals,
    )

    assert "人物关系图还是空的" in issues
    assert not any("人物列表还没有登记完整" in issue for issue in issues)


@pytest.mark.asyncio
async def test_runtime_failure_exposes_recoverable_candidate_summary(tmp_path) -> None:
    db, project = make_project(tmp_path)

    class Skills:
        def skills(self, project_root):
            return {
                "worldbuilding": SimpleNamespace(
                    name="worldbuilding", content_hash="hash",
                    instructions="Create confirmed world files.", path=tmp_path,
                ),
                "story-maintenance": SimpleNamespace(executable=True),
            }

    class Gateway:
        async def complete_with_tools(self, role, system, user, toolbox, **kwargs):
            toolbox.execute("create_file_proposal", {
                "relative_path": "worldbuilding/locations/shen-jia.md",
                "content": "---\nname: 沈家\ntype: family\n---\n# 沈家\n主模型版本。\n",
            })
            toolbox.prepare_fallback(RuntimeError("主模型中断"))
            toolbox.execute("create_file_proposal", {
                "relative_path": "worldbuilding/locations/shen-family.md",
                "content": "---\nname: 沈家\ntype: family\n---\n# 沈家\n待修复版本。\n",
            })
            raise RuntimeError("备用模型中断")

    service = SkillRuntimeService(
        db, ProjectStore(db, tmp_path / "workspace"), Gateway(), Skills(),
    )
    answers = {"outline_manifest": {"locations": [
        {"name": "沈家"}, {"name": "镇子集市"},
    ]}}

    with pytest.raises(RuntimeError, match="备用模型中断") as caught:
        await service.run(project.id, "worldbuilding", answers, bootstrap=True)

    summary = caught.value.proposal_summary
    assert caught.value.execution_id == summary["execution_id"]
    assert summary["retainable_count"] == 1
    assert summary["repair_count"] == 1
    assert summary["duplicate_count"] == 1
    assert summary["missing_count"] == 1
    assert summary["missing_items"] == ["这些故事地点还没有资料：镇子集市"]
    assert summary["formal_unchanged"] is True
    assert not (project.path / "worldbuilding" / "locations" / "shen-jia.md").exists()


def test_fallback_proposal_reuses_primary_path_for_same_entity(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "worldbuilding", "hash", "running")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("worldbuilding"),
        StoryCli(project, lambda command: "ok"),
    )
    first = toolbox.execute("create_file_proposal", {
        "relative_path": "worldbuilding/locations/shen-jia.md",
        "content": "---\nname: 沈家\ntype: family\n---\n# 沈家\n主模型版本。\n",
    })

    context = toolbox.prepare_fallback(RuntimeError("primary stopped"))
    second = toolbox.execute("create_file_proposal", {
        "relative_path": "worldbuilding/locations/shen-family.md",
        "content": "---\nname: 沈家\ntype: family\n---\n# 沈家\n备用模型补全版本。\n",
    })

    proposals = db.list_file_proposals("run")
    assert first["relative_path"] == "worldbuilding/locations/shen-jia.md"
    assert second["relative_path"] == "worldbuilding/locations/shen-jia.md"
    assert [item["status"] for item in proposals] == ["retained", "pending"]
    assert "worldbuilding/locations/shen-jia.md" in context
    assert "只补齐" in context

    toolbox.apply()

    assert "备用模型补全版本" in (
        project.path / "worldbuilding" / "locations" / "shen-jia.md"
    ).read_text(encoding="utf-8")
    assert not (project.path / "worldbuilding" / "locations" / "shen-family.md").exists()
    assert [item["status"] for item in db.list_file_proposals("run")] == [
        "superseded", "applied",
    ]


def test_fallback_proposal_reuses_existing_formal_entity_path(tmp_path) -> None:
    db, project = make_project(tmp_path)
    formal = project.path / "worldbuilding" / "locations" / "shen-jia.md"
    formal.write_text(
        "---\nname: 沈家\ntype: family\n---\n# 沈家\n正式资料。\n",
        encoding="utf-8",
    )
    db.create_skill_execution("run", project.id, "worldbuilding", "hash", "running")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("worldbuilding"),
        StoryCli(project, lambda command: "ok"),
    )

    proposal = toolbox.execute("create_file_proposal", {
        "relative_path": "worldbuilding/locations/shen-family.md",
        "content": "---\nname: 沈家\ntype: family\n---\n# 沈家\n补充资料。\n",
    })

    assert proposal["relative_path"] == "worldbuilding/locations/shen-jia.md"


def test_validation_failure_keeps_retained_primary_proposals(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "worldbuilding", "hash", "running")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("worldbuilding"),
        StoryCli(
            project,
            lambda command: (_ for _ in ()).throw(RuntimeError("invalid links"))
            if command[0] == "validate" else "ok",
        ),
    )
    toolbox.execute("create_file_proposal", {
        "relative_path": "worldbuilding/locations/shen-jia.md",
        "content": "---\nname: 沈家\ntype: family\n---\n# 沈家\n主模型资料。\n",
    })
    toolbox.prepare_fallback(RuntimeError("primary stopped"))
    toolbox.execute("update_registry_proposal", {
        "relative_path": "worldbuilding/_index.md",
        "content": "---\ntype: world-registry\n---\n# World\n",
    })

    with pytest.raises(RuntimeError, match="invalid links"):
        toolbox.apply()

    assert [item["status"] for item in db.list_file_proposals("run")] == [
        "retained", "failed",
    ]


def test_entity_identity_keeps_same_name_in_different_types_separate(tmp_path) -> None:
    db, project = make_project(tmp_path)
    db.create_skill_execution("run", project.id, "worldbuilding", "hash", "running")
    toolbox = SkillRuntimeToolbox(
        db, project, "run", SkillContract.for_skill("worldbuilding"),
        StoryCli(project, lambda command: "ok"),
    )

    location = toolbox.execute("create_file_proposal", {
        "relative_path": "worldbuilding/locations/guiji.md",
        "content": "---\nname: 归寂\ntype: place\n---\n# 归寂\n",
    })
    faction = toolbox.execute("create_file_proposal", {
        "relative_path": "worldbuilding/factions/guiji.md",
        "content": "---\nname: 归寂\ntype: faction\n---\n# 归寂\n",
    })

    assert location["relative_path"] != faction["relative_path"]


@pytest.mark.asyncio
async def test_bootstrap_resumes_candidates_only_for_the_same_context(tmp_path) -> None:
    db, project = make_project(tmp_path)
    answers = {
        "confirmed_outline": {"version": 1, "content": "# Outline\n\nOld house."},
        "outline_manifest": {"locations": [{"name": "Old house"}]},
    }
    db.create_skill_execution(
        "old-run", project.id, "worldbuilding", "hash", "recoverable",
        context_hash=initialization_context_hash(answers),
    )
    db.save_file_proposal(
        "old-place", "old-run", "worldbuilding/locations/old-house.md",
        "---\nname: Old house\ntype: place\n---\n# Old house\n", "retained",
    )

    class Skills:
        def skills(self, project_root):
            return {"worldbuilding": SimpleNamespace(
                name="worldbuilding", content_hash="hash",
                instructions="Complete the world files.", path=tmp_path,
            )}

    seen = []

    class Gateway:
        async def complete_with_tools(self, role, system, user, toolbox, **kwargs):
            seen.append(toolbox.execute("read_story_file", {
                "relative_path": "worldbuilding/locations/old-house.md",
            }))
            toolbox.execute("update_registry_proposal", {
                "relative_path": "worldbuilding/_index.md",
                "content": (
                    "---\ntype: world-registry\n---\n# World\n\n"
                    "[Old house](locations/old-house.md)\n"
                ),
            })
            return SimpleNamespace(text="done", receipt={"execution_mode": "native_tools"})

    service = SkillRuntimeService(
        db, ProjectStore(db, tmp_path / "workspace"), Gateway(), Skills(),
    )
    service._run_story_cli = lambda _project, _command: "ok"

    result = await service.run(project.id, "worldbuilding", answers, bootstrap=True)

    assert result["status"] == "completed"
    assert seen[0]["source"] == "retained_candidate"
    assert db.get_skill_execution("old-run")["status"] == "resumed"
    assert (project.path / "worldbuilding" / "locations" / "old-house.md").is_file()


@pytest.mark.asyncio
async def test_bootstrap_does_not_resume_candidates_after_outline_changes(tmp_path) -> None:
    db, project = make_project(tmp_path)
    old_answers = {
        "confirmed_outline": {"version": 1, "content": "# Old outline"},
        "outline_manifest": {"locations": [{"name": "Old house"}]},
    }
    new_answers = {
        "confirmed_outline": {"version": 2, "content": "# New outline"},
        "outline_manifest": {"locations": [{"name": "New house"}]},
    }
    db.create_skill_execution(
        "old-run", project.id, "worldbuilding", "hash", "recoverable",
        context_hash=initialization_context_hash(old_answers),
    )
    db.save_file_proposal(
        "old-place", "old-run", "worldbuilding/locations/old-house.md",
        "---\nname: Old house\ntype: place\n---\n# Old house\n", "retained",
    )

    class Skills:
        def skills(self, project_root):
            return {"worldbuilding": SimpleNamespace(
                name="worldbuilding", content_hash="hash",
                instructions="Complete the world files.", path=tmp_path,
            )}

    class Gateway:
        async def complete_with_tools(self, role, system, user, toolbox, **kwargs):
            with pytest.raises(ValueError, match="not found"):
                toolbox.execute("read_story_file", {
                    "relative_path": "worldbuilding/locations/old-house.md",
                })
            toolbox.execute("create_file_proposal", {
                "relative_path": "worldbuilding/locations/new-house.md",
                "content": "---\nname: New house\ntype: place\n---\n# New house\n",
            })
            toolbox.execute("update_registry_proposal", {
                "relative_path": "worldbuilding/_index.md",
                "content": (
                    "---\ntype: world-registry\n---\n# World\n\n"
                    "[New house](locations/new-house.md)\n"
                ),
            })
            return SimpleNamespace(text="done", receipt={"execution_mode": "native_tools"})

    service = SkillRuntimeService(
        db, ProjectStore(db, tmp_path / "workspace"), Gateway(), Skills(),
    )
    service._run_story_cli = lambda _project, _command: "ok"

    await service.run(project.id, "worldbuilding", new_answers, bootstrap=True)

    assert db.get_skill_execution("old-run")["status"] == "recoverable"
    assert not (project.path / "worldbuilding" / "locations" / "old-house.md").exists()
    assert (project.path / "worldbuilding" / "locations" / "new-house.md").is_file()
