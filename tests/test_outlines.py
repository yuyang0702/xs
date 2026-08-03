import json
from pathlib import Path

import pytest

from novel_flywheel.db import Database
from novel_flywheel.learning import LearningSystem
from novel_flywheel.outlines import (
    OutlineService, extract_outline_characters, local_outline_manifest,
    narrative_outline_event_contracts, narrative_outline_events,
    normalize_outline_manifest, outline_event_kind, outline_events,
)
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.reference_library import ReferenceLibrary


def setup_outline_service(tmp_path) -> tuple[Database, ProjectStore, object, OutlineService]:
    db = Database(tmp_path / "app.db")
    db.migrate()
    projects = ProjectStore(db, tmp_path / "projects")
    project = projects.create(ProjectCreate(
        title="大纲版本测试", mode="short", genre="悬疑",
        premise="主角寻找失踪的朋友", target_words=10_000,
    ))
    return db, projects, project, OutlineService(db, projects)


def test_current_outline_uses_latest_completed_run_without_migrating_it(tmp_path) -> None:
    db, _projects, project, service = setup_outline_service(tmp_path)
    for run_id, content in (("older", "# 旧大纲\n"), ("latest", "# 最近大纲\n")):
        db.create_run(run_id, project.id, "short-story", status="completed")
        output = project.path / "runs" / run_id / "outputs"
        output.mkdir(parents=True)
        (output / "planning.md").write_text(content, encoding="utf-8")

    current = service.current(project.id)

    assert current["content"] == "# 最近大纲\n"
    assert current["source"] == "legacy_run"
    assert current["outline_version"] == 0
    assert current["stage"] == "outline_only"


def test_candidate_can_be_listed_read_and_edited_instead_of_hidden_on_disk(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)
    candidate = service.create_candidate(
        project.id, "# 初稿\n\n主角出发。\n", title="第一次调整",
    )

    listed = service.list_candidates(project.id)
    edited = service.update_candidate(
        project.id, candidate["id"], "# 初稿\n\n主角带着证据出发。\n", title="补充证据",
    )

    assert listed[0]["content"] == "# 初稿\n\n主角出发。\n"
    assert edited["title"] == "补充证据"
    assert service.get_candidate(project.id, candidate["id"])["content"] == "# 初稿\n\n主角带着证据出发。\n"


def test_local_comparison_reports_story_blocks_and_does_not_need_a_model(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)
    first = service.create_candidate(
        project.id,
        "# 大纲\n\n## 开头\n主角收到求救信。\n\n## 结尾\n主角救回朋友。\n",
    )
    service.apply_candidate(project.id, first["id"])
    second = service.create_candidate(
        project.id,
        "# 大纲\n\n## 开头\n主角收到带血的求救信。\n\n## 中段\n第一次营救失败。\n\n## 结尾\n主角救回朋友，但失去记忆。\n",
    )

    report = service.compare_candidate(project.id, second["id"])

    assert report["summary"]["added"] == 1
    assert report["summary"]["changed"] >= 2
    assert {item["label"] for item in report["changes"]} >= {"开头", "中段", "结尾"}
    assert report["model_called"] is False
    assert report["can_apply"] is True


def test_outline_comparison_uses_market_opening_signals_as_non_blocking_advice(tmp_path) -> None:
    db, projects, project, service = setup_outline_service(tmp_path)
    learning = LearningSystem(
        db, ReferenceLibrary(db, tmp_path / "references"), projects,
    )
    learning.save_artifact(project.id, "market_baseline", {
        "sample_count": 12, "confidence_level": "advisory",
        "opening": {"question_percent": 75, "anomaly_percent": 66.7},
        "mechanisms": [{"name": "开场目标受阻", "work_count": 8, "position_median": 5}],
        "boundary": "只描述本地已确认样本，不代表质量标准。",
    })
    projects.set_market_baseline_selection(
        project.id, enabled=True,
        key={"platform": "知乎", "ranking_name": "盐选热榜", "category": "悬疑", "length_type": "short"},
    )
    candidate = service.create_candidate(
        project.id,
        "# 候选大纲\n\n## 开头\n主角整理朋友留下的旧照片。\n\n## 结尾\n主角找到朋友。\n",
    )

    report = service.compare_candidate(project.id, candidate["id"])

    assert report["market_check"]["status"] == "advisory"
    assert {item["signal"] for item in report["market_check"]["signals"]} == {
        "opening_question", "opening_anomaly",
    }
    assert all(item["detected"] is False for item in report["market_check"]["signals"])
    assert report["market_check"]["advisory_only"] is True
    assert report["can_apply"] is True
    assert not any("市场" in item for item in report["risks"])
    assert report["model_called"] is False
    learning.save_artifact(project.id, "market_baseline", {
        "sample_count": 3, "confidence_level": "insufficient",
        "opening": {"question_percent": 100, "anomaly_percent": 100},
        "mechanisms": [{"name": "样本不足的机制", "work_count": 3}],
    })
    insufficient = service.compare_candidate(project.id, candidate["id"])["market_check"]
    assert insufficient["status"] == "insufficient"
    assert insufficient["signals"] == []
    assert insufficient["mechanisms"] == []
    assert "数量不足" in insufficient["message"]


def test_semantic_outline_decisions_accept_wrappers_and_reject_ambiguity() -> None:
    decision = {
        "decisions": [{
            "id": "change-1", "type": "changed",
            "explanation": "补足动机", "impact": "因果更清楚",
        }],
    }

    assert OutlineService._semantic_decisions(
        f"说明如下：\n```JSON\n{json.dumps(decision, ensure_ascii=False)}\n```",
        {"change-1"},
    )[0]["id"] == "change-1"
    with pytest.raises(ValueError, match="重新尝试"):
        OutlineService._semantic_decisions(
            f"{json.dumps(decision)}\n{json.dumps(decision)}", {"change-1"},
        )


def test_semantic_outline_decisions_normalize_aliases_and_degrade_unknown_labels() -> None:
    decisions = OutlineService._semantic_decisions(json.dumps({
        "decisions": [
            {"id": "change-1", "type": "顺序变化", "explanation": "位置后移"},
            {"id": "change-2", "type": "局部重组", "explanation": "需要人工复核"},
        ],
    }, ensure_ascii=False), {"change-1", "change-2"})

    assert decisions[0]["type"] == "reordered"
    assert decisions[0]["raw_type"] == "顺序变化"
    assert decisions[1]["type"] == "uncertain"
    assert decisions[1]["raw_type"] == "局部重组"


def test_canon_conflicts_require_a_choice_and_can_keep_project_facts(tmp_path) -> None:
    _db, projects, project, service = setup_outline_service(tmp_path)
    metadata_path = project.path / "project.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["story_requirements"] = {
        "protagonist.name": "苏荞", "world.locations": "容府、东市",
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    candidate = service.create_candidate(
        project.id,
        "# 新大纲\n\n**方小满（冒牌千金）**住进沈府。\n\n沈府众人开始试探她。\n",
    )

    report = service.compare_candidate(project.id, candidate["id"])

    assert {item["key"] for item in report["canon_conflicts"]} >= {
        "protagonist", "primary_location",
    }
    assert report["can_apply"] is False
    with pytest.raises(ValueError, match="设定冲突"):
        service.apply_candidate(project.id, candidate["id"])
    applied = service.apply_candidate(
        project.id, candidate["id"], canon_choices={
            item["id"]: "keep_current" for item in report["canon_conflicts"]
        },
    )
    assert "苏荞" in applied["content"]
    assert "容府" in applied["content"]
    assert service.writing_readiness(project.id)["ready"] is True


def test_conflicting_candidate_can_create_independent_project(tmp_path) -> None:
    _db, projects, project, service = setup_outline_service(tmp_path)
    candidate = service.create_candidate(
        project.id,
        "# 错认鸾枝\n\n**方小满（冒牌千金）**进入沈府，决定查清错认真相。\n",
    )

    created = service.create_project_from_candidate(project.id, candidate["id"])

    assert created["id"] != project.id
    assert created["materials_need_generation"] is True
    assert service.current(created["id"])["content"].startswith("# 错认鸾枝")
    assert service.get_candidate(project.id, candidate["id"])["status"] == "pending"
    assert projects.get(project.id).path.is_dir()
    new_project = projects.get(created["id"])
    story = (new_project.path / "story.md").read_text(encoding="utf-8")
    assert "## Confirmed Story Requirements" in story
    assert new_project.metadata["initialization_skills"] == [
        "story-init", "character-management", "worldbuilding", "plot-structure",
    ]
    assert new_project.title == "错认鸾枝（新大纲）"


def test_confirmed_outline_creates_stable_event_ids() -> None:
    content = (
        "# 《归途》小说大纲\n\n## 开头\n收到死者来信。\n\n"
        "## 中段\n**第一次营救：失败**\n\n## 结尾\n付出代价后救回朋友。\n"
    )

    before = outline_events(content)
    after = outline_events(content.replace("收到死者来信。", "深夜收到死者来信。"))

    assert [item["label"] for item in before] == ["开头", "中段", "第一次营救：失败", "结尾"]
    assert [item["id"] for item in before] == [item["id"] for item in after]


def test_outline_events_separate_story_beats_from_structure_and_directives() -> None:
    content = """# 大纲

## 一、故事核心设定
**总字数**：一万字

## 三、章节大纲
### 第一幕：误入高门
**开篇钩子**：花穗被错抬进府。
### 第1章·身份露馅
**冲突升级**：众人开始怀疑她。

## 四、主题与情感线
**核心母题**：出身不决定价值。

## 五、写作要点
**保持第一人称**：只写花穗所见。
"""

    events = outline_events(content)

    assert {
        item["label"]: outline_event_kind(item["section"], item["label"])
        for item in events
    } == {
        "总字数": "directive",
        "第一幕：误入高门": "structure",
        "开篇钩子": "narrative",
        "第1章·身份露馅": "narrative",
        "冲突升级": "narrative",
        "四、主题与情感线": "theme",
        "核心母题": "theme",
        "五、写作要点": "directive",
        "保持第一人称": "directive",
    }
    assert [item["label"] for item in narrative_outline_events(events)] == [
        "开篇钩子", "冲突升级",
    ]

    assert all("kind" not in item for item in events)


def test_narrative_outline_events_falls_back_to_sparse_chapter_headings() -> None:
    events = outline_events("# 大纲\n\n## 第一章\n\n## 第二章\n")

    assert [outline_event_kind(item["section"], item["label"]) for item in events] == [
        "structure", "structure",
    ]
    assert narrative_outline_events(events) == events


def test_narrative_outline_events_treats_titled_chapter_with_children_as_container() -> None:
    events = outline_events(
        "# 大纲\n\n## 第一章：误入\n**开篇钩子**：被错抬进府。\n\n"
        "## 第二章：真相揭晓\n"
    )

    assert [item["label"] for item in narrative_outline_events(events)] == [
        "开篇钩子", "第二章：真相揭晓",
    ]


def test_narrative_outline_events_falls_back_per_sparse_chapter() -> None:
    events = outline_events(
        "# 大纲\n\n## 第一章\n花穗被错抬进府。\n\n"
        "## 第二章：身份揭晓\n"
    )

    assert [item["label"] for item in narrative_outline_events(events)] == [
        "第一章", "第二章：身份揭晓",
    ]


def test_narrative_outline_events_falls_back_per_nested_sparse_chapter() -> None:
    events = outline_events(
        "# 大纲\n\n## 章节规划\n### 第一章\n花穗被错抬进府。\n\n"
        "### 第二章：身份揭晓\n"
    )

    assert [item["label"] for item in narrative_outline_events(events)] == [
        "第一章", "第二章：身份揭晓",
    ]


def test_narrative_outline_events_does_not_require_act_before_titled_chapter() -> None:
    events = outline_events(
        "# 大纲\n\n## 章节规划\n"
        "### 第一幕：错入高门\n### 第1章·一顶轿子抬错了人\n"
        "### 第二幕：真相浮现\n### 第2章·账册露出破绽\n"
    )

    assert [item["label"] for item in narrative_outline_events(events)] == [
        "第1章·一顶轿子抬错了人", "第2章·账册露出破绽",
    ]


def test_narrative_outline_event_contracts_exclude_eight_production_style_chapters() -> None:
    counts = [4, 4, 4, 4, 4, 3, 3, 3]
    blocks = ["# 短篇正式大纲", "", "## 章节规划"]
    event_labels = []
    for chapter, count in enumerate(counts, 1):
        blocks.append(f"### 第{chapter}章·章节标题{chapter}")
        for event in range(1, count + 1):
            label = f"事件{chapter}-{event}"
            event_labels.append(label)
            blocks.append(f"**{label}**：人物执行本事件并产生可核对结果。")
        blocks.append("")
    content = "\n".join(blocks)

    all_events = outline_events(content)
    contracts = narrative_outline_event_contracts(content)
    original_ids = {item["label"]: item["id"] for item in all_events}

    assert len(contracts) == 29
    assert [item["label"] for item in contracts] == event_labels
    assert all(not item["label"].startswith("第") for item in contracts)
    assert [item["id"] for item in contracts] == [
        original_ids[label] for label in event_labels
    ]
    changed = narrative_outline_event_contracts(
        content.replace("产生可核对结果", "产生更具体且可核对的结果"),
    )
    assert [item["id"] for item in changed] == [item["id"] for item in contracts]


@pytest.mark.parametrize(
    ("content", "labels"),
    [
        (
            "# Outline\n\n## Act I\n### Chapter 1: Arrival\n"
            "**Inciting event**: The envoy lands.\n",
            ["Inciting event"],
        ),
        (
            "# Outline\n\n## Act I\n### Chapter 1: Arrival\n"
            "### Chapter 2: Discovery\n",
            ["Chapter 1: Arrival", "Chapter 2: Discovery"],
        ),
    ],
)
def test_narrative_outline_events_support_english_nested_and_sparse_structure(
    content: str, labels: list[str],
) -> None:
    assert [
        item["label"] for item in narrative_outline_event_contracts(content)
    ] == labels


@pytest.mark.parametrize("section", ["世界崩塌", "背景真相揭晓", "情感线索浮现"])
def test_outline_event_kind_defaults_unknown_story_sections_to_narrative(section) -> None:
    assert outline_event_kind(section, "危机升级") == "narrative"


def test_outline_semantic_scans_ignore_html_comments_and_fenced_examples() -> None:
    content = """# 大纲

## 开头
<!--
**隐藏冲突**：这只是模板提示。
### 女主（假千金）
-->
```markdown
**示例事件**：这只是格式示例。
### 女主（示例人物）
```
**真实事件**：花穗被错抬进府。

## 人物设定
### 女主（花穗）
"""

    assert [item["label"] for item in outline_events(content)] == [
        "开头", "真实事件",
    ]
    assert [item["name"] for item in extract_outline_characters(content)] == ["花穗"]


@pytest.mark.parametrize("section", ["写作要求：", "写作要求/", "写作要求:"])
def test_outline_event_kind_accepts_trailing_section_punctuation(section) -> None:
    assert outline_event_kind(section, "保持第一人称") == "directive"


@pytest.mark.parametrize("section", ["（一）写作要求", "(1) 写作要求", "一）写作要求"])
def test_outline_event_kind_accepts_bracketed_section_numbers(section) -> None:
    assert outline_event_kind(section, "保持第一人称") == "directive"


def test_outline_events_accept_tab_headings_and_normalize_identity_width() -> None:
    tabbed = outline_events(
        "# 大纲\n\n##\t写作要求\n###\t保持第一人称\n\n##\t第１章：开端\n",
    )
    ascii_width = outline_events("# 大纲\n\n## 第1章：开端\n")

    assert outline_event_kind(tabbed[0]["section"], tabbed[0]["label"]) == "directive"
    assert outline_event_kind(tabbed[1]["section"], tabbed[1]["label"]) == "directive"
    assert tabbed[-1]["id"] == ascii_width[-1]["id"]


def test_outline_structure_container_accepts_trailing_punctuation() -> None:
    events = outline_events("# 大纲\n\n## 章节规划：\n### 第一章\n")

    assert [item["label"] for item in narrative_outline_events(events)] == ["第一章"]


def test_current_outline_rebuilds_legacy_cached_events_from_visible_content(tmp_path) -> None:
    db, _projects, project, service = setup_outline_service(tmp_path)
    candidate = service.create_candidate(
        project.id,
        "# 大纲\n\n**真实事件**：主角发现线索。\n"
        "<!-- **模板事件**：只是示例。 -->\n",
    )
    service.apply_candidate(project.id, candidate["id"])
    state = service.states.get(project.id)
    assert state is not None
    state.data["outline"]["events"].append({
        "id": "EV-DEADBEEF", "order": 99, "label": "模板事件", "section": "",
    })
    with db.connect() as connection:
        connection.execute(
            "UPDATE story_states SET state_json=? WHERE project_id=?",
            (json.dumps(state.data, ensure_ascii=False), project.id),
        )

    current = service.current(project.id)

    assert [item["label"] for item in current["events"]] == ["真实事件"]
    assert all(item["id"] != "EV-DEADBEEF" for item in current["events"])


def test_outline_character_manifest_reads_only_explicit_named_roles() -> None:
    content = """# 大纲

## 人物设定

### 女主（花穗）
- 性情泼辣直爽，目标是离开深宅。

### 男主（裴砚行）
- 身份是沈家故交之子。

### 重要配角
- **沈老夫人**：沈家主母。
- **沈大小姐**：名门闺秀。
"""

    characters = extract_outline_characters(content)

    assert [item["name"] for item in characters] == [
        "花穗", "裴砚行", "沈老夫人", "沈大小姐",
    ]
    assert not {"性情", "目标", "身份"} & {item["name"] for item in characters}


def test_outline_manifest_collapses_model_labels_for_the_same_evidence() -> None:
    manifest = normalize_outline_manifest({
        "plot_arcs": [
            {"name": "第一幕：错入高门（约3000字）", "evidence": "### 第一幕：错入高门（约3000字）"},
            {"name": "第一幕：错入高门", "evidence": "### 第一幕：错入高门（约3000字）"},
        ],
        "questions": [
            {"name": "花穗被人塞进轿子，带回沈府冒充三小姐", "evidence": "- **开篇钩子**：花穗被错认。"},
            {"name": "花穗为何被错认？", "evidence": "- **开篇钩子**：花穗被错认。"},
        ],
    })

    assert [item["name"] for item in manifest["plot_arcs"]] == ["第一幕：错入高门"]
    assert [item["name"] for item in manifest["questions"]] == ["花穗为何被错认？"]


@pytest.mark.asyncio
async def test_material_manifest_rejects_invented_entities_and_reuses_outline_cache(tmp_path) -> None:
    db, projects, project, _service = setup_outline_service(tmp_path)

    class Gateway:
        calls = 0

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls += 1
            return type("Result", (), {
                "text": json.dumps({
                    "characters": [
                        {"name": "花穗", "role": "protagonist", "evidence": "### 女主（花穗）"},
                        {"name": "张三", "role": "supporting", "evidence": "### 女主（花穗）"},
                    ],
                    "world": [],
                    "locations": [
                        {"name": "沈府", "evidence": "- **地点**：沈府"},
                        {"name": "京城", "evidence": "- **地点**：沈府"},
                    ],
                    "plot_arcs": [], "timeline": [], "promises": [],
                    "questions": [], "constraints": [],
                }, ensure_ascii=False),
                "receipt": {"model_name": "test-planner"},
            })()

    gateway = Gateway()
    service = OutlineService(db, projects, gateway)
    first = service.create_candidate(project.id, """# 大纲

## 人物设定
### 女主（花穗）

## 章节大纲
### 第一幕：入府
#### 第1章·错认

- **地点**：沈府
""")
    service.apply_candidate(project.id, first["id"])

    manifest = await service.material_manifest(project.id)
    cached = await service.material_manifest(project.id)

    assert gateway.calls == 1
    assert cached == manifest
    assert [item["name"] for item in manifest["characters"]] == ["花穗"]
    assert [item["name"] for item in manifest["locations"]] == ["沈府"]
    assert manifest["_review"]["status"] == "model_confirmed"

    changed = service.create_candidate(project.id, service.current(project.id)["content"] + "\n#### 第2章·查账\n")
    service.apply_candidate(project.id, changed["id"])
    await service.material_manifest(project.id)
    assert gateway.calls == 2


@pytest.mark.asyncio
async def test_material_manifest_uses_strict_local_result_when_planning_model_is_unavailable(
    tmp_path,
) -> None:
    db, projects, project, _service = setup_outline_service(tmp_path)

    class Gateway:
        available = False

        async def complete(self, *args, **kwargs):
            if not self.available:
                raise LookupError("planning role is not configured")
            return type("Result", (), {
                "text": json.dumps({key: [] for key in (
                    "characters", "world", "locations", "plot_arcs", "timeline",
                    "promises", "questions", "constraints",
                )}),
                "receipt": {"model_name": "planner"},
            })()

    gateway = Gateway()
    service = OutlineService(db, projects, gateway)
    candidate = service.create_candidate(project.id, "# 正式大纲\n\n## 开头\n门被推开。\n")
    service.apply_candidate(project.id, candidate["id"])

    manifest = await service.material_manifest(project.id)

    assert manifest["_review"]["status"] == "local_only"
    assert manifest["characters"] == []
    assert local_outline_manifest("普通描述，不是人物清单。")["characters"] == []

    gateway.available = True
    reviewed = await service.material_manifest(project.id)
    assert reviewed["_review"]["status"] == "model_confirmed"


def test_conflicting_current_outline_can_create_clean_project_without_changing_source(
    tmp_path,
) -> None:
    db, projects, project, service = setup_outline_service(tmp_path)
    candidate = service.create_candidate(
        project.id,
        "# 错认鸾枝\n\n**方小满（冒牌千金）**进入沈府，决定查清错认真相。\n",
    )
    service.apply_candidate(project.id, candidate["id"])
    db.create_run("source-run", project.id, "short-story", status="completed")
    metadata_path = project.path / "project.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update({
        "must_include": "旧人物苏荞必须出现",
        "must_avoid": "不得离开容府",
        "story_requirements": {
            "protagonist.name": "苏荞", "world.locations": "容府、东市",
        },
    })
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    source_outline = service.current(project.id)["content"]

    assert service.writing_readiness(project.id)["ready"] is False
    created = service.create_project_from_current(project.id)

    assert created["id"] != project.id
    assert created["materials_need_generation"] is True
    assert service.current(created["id"])["content"] == source_outline
    assert service.current(project.id)["content"] == source_outline
    assert db.get_run("source-run")["project_id"] == project.id
    new_metadata = projects.get(created["id"]).metadata
    assert new_metadata["must_include"] == ""
    assert new_metadata["must_avoid"] == ""
    assert "protagonist.name" not in new_metadata["story_requirements"]


def test_selected_changes_create_new_outline_version_and_preserve_unselected_blocks(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)
    initial = service.create_candidate(
        project.id,
        "# 大纲\n\n## 开头\n旧开头。\n\n## 中段\n旧中段。\n\n## 结尾\n旧结尾。\n",
    )
    service.apply_candidate(project.id, initial["id"])
    candidate = service.create_candidate(
        project.id,
        "# 大纲\n\n## 开头\n新开头。\n\n## 中段\n新中段。\n\n## 结尾\n新结尾。\n",
    )
    report = service.compare_candidate(project.id, candidate["id"])
    middle = next(item for item in report["changes"] if item["label"] == "中段")

    applied = service.apply_candidate(
        project.id, candidate["id"], change_ids=[middle["id"]],
        expected_revision=report["state_revision"],
    )

    assert "旧开头" in applied["content"]
    assert "新中段" in applied["content"]
    assert "旧结尾" in applied["content"]
    assert applied["outline_version"] == 2
    assert (project.path / "plot" / "outline.md").read_text(encoding="utf-8") == applied["content"]


def test_whole_outline_requires_explicit_confirmation_after_manuscript_exists(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)
    initial = service.create_candidate(project.id, "# 大纲\n\n旧剧情。\n")
    service.apply_candidate(project.id, initial["id"])
    manuscript = project.path / "manuscript" / "story.md"
    manuscript.write_text("# 正文\n\n已经写好的正文。\n", encoding="utf-8")
    candidate = service.create_candidate(project.id, "# 大纲\n\n新剧情。\n")

    with pytest.raises(ValueError, match="已有正文"):
        service.apply_candidate(project.id, candidate["id"])

    applied = service.apply_candidate(
        project.id, candidate["id"], allow_full_with_manuscript=True,
    )
    assert "新剧情" in applied["content"]
    assert manuscript.read_text(encoding="utf-8") == "# 正文\n\n已经写好的正文。\n"


def test_locked_fact_removal_blocks_outline_application(tmp_path) -> None:
    db, _projects, project, service = setup_outline_service(tmp_path)
    initial = service.create_candidate(project.id, "# 大纲\n\n林舟必须活到结局。\n")
    service.apply_candidate(project.id, initial["id"])
    with db.connect() as connection:
        row = connection.execute(
            "SELECT revision,state_json FROM story_states WHERE project_id=?", (project.id,),
        ).fetchone()
        import json
        data = json.loads(row["state_json"])
        data["locked_facts"] = [{"key": "ending", "value": "林舟必须活到结局"}]
        connection.execute(
            "UPDATE story_states SET state_json=? WHERE project_id=?",
            (json.dumps(data, ensure_ascii=False), project.id),
        )
    candidate = service.create_candidate(project.id, "# 大纲\n\n林舟在中段消失。\n")

    with pytest.raises(ValueError, match="锁定设定"):
        service.apply_candidate(project.id, candidate["id"])


def test_restoring_history_creates_a_new_version_instead_of_erasing_history(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)
    first = service.create_candidate(project.id, "# 第一版\n")
    service.apply_candidate(project.id, first["id"])
    second = service.create_candidate(project.id, "# 第二版\n")
    service.apply_candidate(project.id, second["id"])

    restored = service.restore(project.id, outline_version=1)
    history = service.history(project.id)

    assert restored["content"] == "# 第一版\n"
    assert restored["outline_version"] == 3
    assert [item["outline_version"] for item in history] == [1, 2, 3]
    assert history[-1]["source"] == "restored"


def test_candidate_reject_keeps_history_but_removes_it_from_active_list(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)
    candidate = service.create_candidate(project.id, "# 不采用\n")

    rejected = service.reject_candidate(project.id, candidate["id"], "方向不合适")

    assert rejected["status"] == "rejected"
    assert service.list_candidates(project.id) == []


def test_outline_length_is_bounded(tmp_path) -> None:
    _db, _projects, project, service = setup_outline_service(tmp_path)

    with pytest.raises(ValueError, match="100,000"):
        service.create_candidate(project.id, "大" * 100_001)


def test_applying_outline_marks_only_outline_derived_artifacts_stale(tmp_path) -> None:
    db, projects, project, service = setup_outline_service(tmp_path)
    learning = LearningSystem(
        db, ReferenceLibrary(db, tmp_path / "references"), projects, gateway=None,
    )
    learning.save_artifact(project.id, "scene_briefs", {"briefs": []})
    learning.save_artifact(project.id, "short_causal_chain", {"cycles": []})
    learning.save_artifact(project.id, "voice_profiles", {"人物甲": {"rules": "少说话"}})
    manuscript = project.path / "manuscript" / "story.md"
    manuscript.write_text("# 正文\n\n已经写好的内容。\n", encoding="utf-8")
    before = manuscript.read_bytes()
    candidate = service.create_candidate(project.id, "# 新大纲\n")

    service.apply_candidate(
        project.id, candidate["id"], allow_full_with_manuscript=True,
    )

    assert learning.get_artifact(project.id, "scene_briefs")["status"] == "stale"
    assert learning.get_artifact(project.id, "short_causal_chain")["status"] == "stale"
    assert learning.get_artifact(project.id, "voice_profiles")["status"] == "active"
    assert manuscript.read_bytes() == before
    saved = json.loads((project.path / "learning" / "scene_briefs.json").read_text(encoding="utf-8"))
    assert saved["status"] == "stale"
