import json
from types import SimpleNamespace

import pytest

from novel_flywheel.db import Database
from novel_flywheel.learning import LearningSystem
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.reference_library import ReferenceLibrary


def setup_system(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    library = ReferenceLibrary(db, tmp_path / "references")
    projects = ProjectStore(db, tmp_path / "projects")
    return db, library, projects, LearningSystem(db, library, projects)


def test_analysis_creates_evidenced_mechanisms_and_reuses_windows(tmp_path) -> None:
    _db, library, _projects, system = setup_system(tmp_path)
    source = library.import_text(
        title="样本", source_type="paste",
        text="她以为门外无人，推门后却看见失踪多年的兄长。\n\n先前那封无名信，此刻终于有了答案。",
    )
    first = system.analyze_reference(source["id"])
    second = system.analyze_reference(source["id"])
    assert first["mechanisms"]
    assert first["mechanisms"][0]["evidence"]
    assert second["cached_windows"] == second["window_count"]


def test_reference_windows_cover_single_line_text_without_splitting_sentences(tmp_path) -> None:
    _db, library, _projects, system = setup_system(tmp_path)
    sentences = [f"第{index}次尝试后，他决定继续追查真相。" for index in range(520)]
    text = "".join(sentences)
    source = library.import_text(title="单行长文", source_type="paste", text=text)

    result = system.analyze_reference(source["id"])
    windows = system._windows(text)

    assert result["window_count"] > 1
    assert result["analyzed_windows"] == result["window_count"]
    assert result["coverage_percent"] == 100.0
    for window in windows[:-1]:
        assert window["text"].endswith(("。", "！", "？", "!", "?"))
        assert 3000 <= len(window["text"]) <= 5000


def test_local_extraction_folds_repeated_mechanism_and_preserves_all_evidence(tmp_path) -> None:
    _db, library, _projects, system = setup_system(tmp_path)
    text = "\n\n".join([
        "他决定进入废弃医院，寻找失踪的朋友。",
        "调查受阻后，他决定更换身份继续追查。",
        "知道真相以后，他决定拒绝复活仪式。",
    ])
    source = library.import_text(title="多处选择", source_type="paste", text=text)

    result = system.analyze_reference(source["id"])
    matching = [item for item in result["mechanisms"] if "状态变化" in item["data"]["name"]]

    assert len(matching) == 1
    assert len(matching[0]["evidence"]) == 3
    assert matching[0]["data"]["occurrence_count"] == 3
    assert matching[0]["data"]["positions"] == sorted(matching[0]["data"]["positions"])


def test_only_rejected_unadopted_mechanisms_can_be_deleted(tmp_path) -> None:
    _db, library, projects, system = setup_system(tmp_path)
    source = library.import_text(title="删除候选", source_type="paste", text="他决定推门寻找真相。")
    node = system.analyze_reference(source["id"])["mechanisms"][0]

    with __import__("pytest").raises(ValueError, match="仅能删除已拒绝"):
        system.delete_rejected_nodes([node["id"]])

    system.revise_node(node["id"], "reject", {})
    deleted = system.delete_rejected_nodes([node["id"]])
    assert deleted == {"deleted_ids": [node["id"]], "skipped": []}
    with __import__("pytest").raises(LookupError):
        system.get_node(node["id"])

    project = projects.create(ProjectCreate(
        title="已采纳保护", mode="short", genre="悬疑", premise="测试", target_words=10_000,
    ))
    protected = system._save_node("mechanism", {
        "key": "protected", "name": "保护机制", "confidence": 0.9,
    }, source_id=source["id"], status="confirmed")
    system.adopt(project.id, protected["id"])
    system.revise_node(protected["id"], "reject", {})

    blocked = system.delete_rejected_nodes([protected["id"]])
    assert blocked["deleted_ids"] == []
    assert blocked["skipped"] == [{"id": protected["id"], "reason": "已被作品采纳"}]


def test_adoption_requires_confirmation_and_never_overwrites_outline(tmp_path) -> None:
    _db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="测试书", mode="short", genre="悬疑", premise="秘密推动关系变化",
        target_words=20_000,
    ))
    source = library.import_text(title="样本", source_type="paste", text="谜底揭晓后，旧盟友突然成为阻碍。")
    mechanism = system.analyze_reference(source["id"])["mechanisms"][0]
    outline = project.path / "outline.md"
    outline.write_text("# 原大纲\n", encoding="utf-8")
    recommendation = system.recommend(project.id, mechanism["id"])
    assert recommendation["status"] == "proposed"
    assert not system.list_adoptions(project.id)
    system.revise_node(mechanism["id"], "confirm", {})
    adopted = system.adopt(project.id, mechanism["id"], {"position": "中段"})
    assert adopted["status"] == "adopted"
    assert outline.read_text(encoding="utf-8") == "# 原大纲\n"
    assert system.get_artifact(project.id, "creative_blueprint")["data"]["mechanisms"]


def test_line_edit_is_candidate_only_and_preserves_locked_facts(tmp_path) -> None:
    _db, _library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="精修书", mode="short", genre="都市", premise="测试", target_words=10_000,
    ))
    result = system.create_line_edit_candidate(
        project.id, "林知晚必须留下。她很确定。", "林知晚必须留下。她从门锁上的新痕判断，对方刚离开。",
        issues=["overprecise_cognition"], locked_facts=["林知晚必须留下"],
    )
    assert result["status"] == "pending"
    assert not (project.path / "manuscript" / "story.md").exists()
    assert "林知晚必须留下" in result["candidate"]


def test_material_change_marks_derived_artifacts_stale(tmp_path) -> None:
    _db, _library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="影响书", mode="short", genre="古风", premise="测试", target_words=10_000,
    ))
    system.save_artifact(project.id, "voice_profiles", {"人物甲": {"habit": "记笔记"}})
    impact = system.mark_material_change(project.id, "characters/a.md", ["人物甲不再记笔记"])
    assert impact["affected"]
    assert system.get_artifact(project.id, "voice_profiles")["status"] == "stale"
    assert "Character Voice Profiles" not in projects.load_constraints(project.id)


def test_deleting_source_keeps_adoption_as_reviewable_tombstone(tmp_path) -> None:
    db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="墓碑", mode="short", genre="悬疑", premise="测试", target_words=10_000,
    ))
    source = library.import_text(title="样本", source_type="paste", text="他推门后却发现真相。")
    node = system.analyze_reference(source["id"])["mechanisms"][0]
    system.revise_node(node["id"], "confirm", {})
    system.adopt(project.id, node["id"])
    library.delete(source["id"])
    with db.connect() as connection:
        status = connection.execute("SELECT status FROM project_adoptions WHERE project_id=?", (project.id,)).fetchone()[0]
    assert status == "review_source_deleted"


def test_reference_metadata_change_marks_adoptions_and_artifacts_for_review(tmp_path) -> None:
    db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="复核作品", mode="short", genre="悬疑", premise="测试", target_words=10_000,
    ))
    source = library.import_text(
        title="样本", source_type="paste", text="他推门后却发现真相。",
        platform="知乎", content_type="reference_work",
    )
    node = system.analyze_reference(source["id"])["mechanisms"][0]
    system.revise_node(node["id"], "confirm", {})
    system.adopt(project.id, node["id"])

    library.update_metadata(
        source["id"], platform="番茄", content_type="popular_sample", project_id=project.id,
    )

    with db.connect() as connection:
        adoption = connection.execute(
            "SELECT status FROM project_adoptions WHERE project_id=? AND node_id=?",
            (project.id, node["id"]),
        ).fetchone()
    assert adoption["status"] == "review_source_metadata_changed"
    assert system.get_artifact(project.id, "creative_blueprint")["status"] == "stale"
    assert system.list_adoption_reviews(project.id)[0]["node_id"] == node["id"]


def test_saving_unchanged_reference_metadata_keeps_adoption_active(tmp_path) -> None:
    _db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="稳定作品", mode="short", genre="悬疑", premise="测试", target_words=10_000,
    ))
    source = library.import_text(
        title="样本", source_type="paste", text="他推门后却发现真相。",
        platform="知乎", content_type="reference_work",
    )
    node = system.analyze_reference(source["id"])["mechanisms"][0]
    system.revise_node(node["id"], "confirm", {})
    system.adopt(project.id, node["id"])

    library.update_metadata(
        source["id"], platform="知乎", content_type="reference_work", project_id=None,
    )

    assert system.list_adoptions(project.id)[0]["node_id"] == node["id"]
    assert system.get_artifact(project.id, "creative_blueprint")["status"] == "active"


def test_active_learning_artifacts_join_existing_constraint_path(tmp_path) -> None:
    _db, _library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="上下文", mode="short", genre="都市", premise="测试", target_words=10_000,
    ))
    system.build_prose_baseline(project.id, {"dialogue": "每次回应都改变关系或信息"})
    constraints = projects.load_constraints(project.id)
    assert "Executable Prose Baseline" in constraints
    assert "每次回应都改变关系或信息" in constraints


def test_active_market_baseline_is_advisory_planning_context(tmp_path) -> None:
    _db, _library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="市场参考", mode="short", genre="悬疑", premise="测试", target_words=10_000,
    ))
    system.save_artifact(project.id, "market_baseline", {
        "sample_count": 12, "confidence_level": "advisory",
        "boundary": "只提供建议，不是质量门槛",
    })

    constraints = projects.load_constraints(project.id)

    assert "Advisory Market Baseline" in constraints
    assert "只提供建议，不是质量门槛" in constraints


def test_short_causal_chain_is_project_artifact_and_constraint(tmp_path) -> None:
    _db, _library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="因果短篇", mode="short", genre="悬疑", premise="复活朋友", target_words=6000,
    ))
    artifact = system.build_short_causal_chain(project.id, {
        "core_goal": {"content": "复活死去的朋友"},
        "cycles": [
            {"obstacle": "缺少灵魂媒介", "effort": "调查死亡现场", "result": "找到残缺记忆", "state_change": "确认灵魂仍在"},
            {"obstacle": "仪式需要交换生命", "effort": "寻找规则漏洞", "result": "朋友暂时复活", "state_change": "目标表面达成"},
        ],
        "reversal": {"content": "朋友主动死亡是为了封印", "prior_evidence": ["死亡记录被销毁"]},
        "ending": {"surface_goal": "无法永久复活", "inner_goal": "主角放下愧疚"},
    })

    assert artifact["artifact_type"] == "short_causal_chain"
    assert artifact["data"]["diagnostics"]["status"] == "valid"
    constraints = projects.load_constraints(project.id)
    assert "Short Story Causal Chain" in constraints
    assert "复活死去的朋友" in constraints


def test_adopted_causal_structure_mechanism_enters_blueprint_bucket(tmp_path) -> None:
    _db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="结构借鉴", mode="short", genre="悬疑", premise="复活朋友", target_words=6000,
    ))
    source = library.import_text(title="结构样本", source_type="paste", text="她救的人其实一直在逃离她。")
    mechanism = system._save_node("mechanism", {
        "key": "causal-structure-1",
        "name": "目标对象主动抗拒被拯救",
        "mechanism_type": "causal_structure",
        "transfer_guidance": "只复用目标被重新解释的结构，不复用具体人物和死因",
        "confidence": 0.9,
    }, source_id=source["id"], status="confirmed")

    system.adopt(project.id, mechanism["id"])

    blueprint = system.get_artifact(project.id, "creative_blueprint")["data"]
    assert blueprint["causal_structure"][0]["name"] == "目标对象主动抗拒被拯救"
    assert blueprint["rules"]


def test_legacy_style_sample_migrates_once_without_deleting_old_files(tmp_path) -> None:
    _db, _library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="旧笔感", mode="short", genre="都市", premise="测试", target_words=10_000,
    ))
    folder = project.path / "style-samples"
    folder.mkdir()
    profile = {
        "summary": "克制近距离叙事", "sentence_rhythm": ["动作段短，观察段稍长"],
        "dialogue": ["回应改变信息"], "narrative_distance": ["限知视角"],
        "characterization": ["用选择表现性格"], "diction": ["具体名词"],
        "avoid": ["避免直接总结情绪"],
    }
    (folder / "profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    (project.path / "style-profile.md").write_text("# 旧风格档案\n", encoding="utf-8")

    first = system.migrate_legacy_style(project.id)
    second = system.migrate_legacy_style(project.id)

    assert first["migrated"] is True
    assert second["migrated"] is False
    assert system.get_artifact(project.id, "prose_baseline")["data"]["dialogue"] == ["回应改变信息"]
    assert (folder / "profile.json").is_file()
    assert (project.path / "style-profile.md").is_file()


class FakeGateway:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.roles = []

    async def complete(self, role, system, user, **kwargs):
        self.roles.append(role)
        return SimpleNamespace(text=next(self.outputs), receipt={"model_id": "fake"})


async def test_model_analysis_uses_explicit_roles_and_keeps_claims_proposed(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    gateway = FakeGateway([
        '{"events":[{"start":0,"end":3,"fact":"发现线索","interpretation":"信息变化","confidence":0.8}]}',
        '{"mechanisms":[{"name":"延迟揭示","supporting_windows":[1],"trigger_conditions":["线索"],'
        '"structural_position":"中段","state_change":"获得信息","emotional_effect":"意外",'
        '"required_preparation":["伏笔"],"downstream_consequence":"改变选择",'
        '"transfer_guidance":"替换内容包装","incompatible_conditions":[],"confidence":0.8}]}',
    ])
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(title="模型样本", source_type="paste", text="他忽然发现了线索。")
    progress = []
    result = await system.model_analyze_reference(source["id"], progress.append)
    assert gateway.roles == ["reference_analysis", "reference_synthesis"]
    assert result["mechanisms"][0]["status"] == "proposed"
    assert progress[0]["phase"] == "analyzing_windows"
    assert progress[0]["completed_windows"] == 0
    assert progress[-1]["phase"] == "synthesizing"
    assert progress[-1]["completed_windows"] == progress[-1]["total_windows"] == 1


def test_reference_model_json_accepts_fenced_or_explained_object() -> None:
    assert LearningSystem._json_object('```json\n{"events": []}\n```') == {"events": []}
    assert LearningSystem._json_object('分析如下：\n```json\n{"events": []}\n```\n请确认。') == {"events": []}


async def test_model_analysis_explains_empty_window_response(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    system = LearningSystem(db, library, projects, FakeGateway([""]))
    source = library.import_text(title="empty-model", source_type="paste", text="一段需要分析的正文。")

    with pytest.raises(ValueError, match="第 1 个文本窗口.*空内容"):
        await system.model_analyze_reference(source["id"])


async def test_model_analysis_uses_configured_fallback_for_invalid_json(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)

    class GatewayWithFallback(FakeGateway):
        def __init__(self):
            super().__init__([
                "",
                '{"mechanisms": []}',
            ])
            self.fallback_roles = []

        async def complete_configured_fallback(self, role, system, user, **kwargs):
            self.fallback_roles.append(role)
            return SimpleNamespace(text='{"events": []}', receipt={"model_id": "fallback"})

    gateway = GatewayWithFallback()
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(title="fallback-model", source_type="paste", text="一段需要分析的正文。")
    progress = []

    result = await system.model_analyze_reference(source["id"], progress.append)

    assert result["claims"] == 1
    assert gateway.fallback_roles == ["reference_analysis"]
    assert any(item["phase"] == "fallback_window" for item in progress)


async def test_model_line_edit_routes_to_line_edit_and_remains_candidate(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    gateway = FakeGateway(["事实甲。她从门缝的光判断，屋里还有人。"])
    system = LearningSystem(db, library, projects, gateway)
    project = projects.create(ProjectCreate(
        title="模型精修", mode="short", genre="都市", premise="测试", target_words=10_000,
    ))
    result = await system.model_line_edit(
        project.id, "事实甲。她很确定屋里有人。", issues=["unsupported_certainty"], locked_facts=["事实甲"],
    )
    assert gateway.roles == ["line_edit"]
    assert result["status"] == "pending"
