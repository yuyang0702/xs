import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from novel_flywheel.db import Database
from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.learning import LearningSystem, ReferenceSynthesisRoutePlanV1
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.reference_distillation import validate_distillation_receipt
from novel_flywheel.reference_library import ReferenceLibrary
import novel_flywheel.learning as learning_module


def setup_system(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    library = ReferenceLibrary(db, tmp_path / "references")
    projects = ProjectStore(db, tmp_path / "projects")
    return db, library, projects, LearningSystem(db, library, projects)


def route_schedule_receipt() -> str:
    """A business-shaped receipt for tests that isolate route scheduling."""

    return json.dumps({
        "version": 2,
        "covered_child_ids": ["route-schedule-fixture"],
        "child_dispositions": [{
            "child_id": "route-schedule-fixture",
            "disposition": "no_transferable_claim",
            "reason": "This fixture verifies explicit route scheduling only.",
        }],
        "child_attributions": [],
        "semantic": {"ok": True},
    })


def route_schedule_semantic(text: str) -> dict:
    return json.loads(text)["semantic"]


def test_local_attraction_context_never_truncates_partial_json() -> None:
    small = {"questions": [{"excerpt": "small"}], "turns": []}
    small_context = LearningSystem._local_attraction_prompt_context(
        small, max_tokens=512,
    )
    assert json.loads(small_context) == small

    large = {
        "questions": [
            {"excerpt": f"evidence-{index}-" + "x" * 80}
            for index in range(1_000)
        ],
        "opening": {"pressure": [], "anomaly": []},
    }
    large_context = LearningSystem._local_attraction_prompt_context(
        large, max_tokens=512,
    )
    receipt = json.loads(large_context)

    assert receipt["mode"] == "content_addressed_registry"
    assert receipt["model_comparison_available"] is False
    assert receipt["topology_counts"]["questions"] == 1_000
    assert len(receipt["catalog_sha256"]) == 64
    assert "evidence-999" not in large_context


def test_model_window_style_field_aliases_and_unknown_descriptions_are_non_blocking() -> None:
    value = LearningSystem._window_result({
        "events": [], "state_changes": [], "reader_questions": [],
        "turning_points": [], "relationship_changes": [],
        "style_evidence": [
            {
                "field": "心理描写", "start": 0, "end": 4,
                "fact": "动作先于判断", "interpretation": "情绪有证据",
            },
            {
                "field": "氛围张力", "start": 5, "end": 9,
                "fact": "环境逐步收紧", "interpretation": "形成压力",
            },
        ],
    })

    assert value["style_evidence"][0]["field"] == "psychology"
    assert value["style_evidence"][0]["raw_field"] == "心理描写"
    assert value["unrecognized_style_evidence"][0]["field"] == "氛围张力"


def test_synthesis_unknown_style_rule_is_preserved_but_not_executed() -> None:
    value = LearningSystem._synthesis_result({
        "mechanisms": [], "attraction_map": {},
        "style_profile": {
            "summary": "保留可核对的文笔规则",
            "rules": [{
                "field": "自定义氛围", "rule": "逐步增加环境压力",
                "when_to_use": "危险接近时", "avoid": "不要突然宣布危险",
                "supporting_windows": [1],
            }],
            "uncertainties": [],
        },
    })

    assert value["style_profile"]["rules"] == []
    assert value["style_profile"]["unrecognized_rules"][0]["field"] == "自定义氛围"


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


def test_local_mechanism_exposes_plain_provenance_and_source_title(tmp_path) -> None:
    _db, library, _projects, system = setup_system(tmp_path)
    source = library.import_text(
        title="本地判断样本", source_type="paste", text="她决定离开，却在门口发现了真相。",
    )

    created = system.analyze_reference(source["id"])["mechanisms"][0]
    listed = next(item for item in system.list_mechanisms() if item["id"] == created["id"])

    assert listed["data"]["analysis_origin"] == "local"
    assert listed["analysis"] == {
        "state": "local_only",
        "local": {"confidence": 0.68, "evidence_count": listed["data"]["occurrence_count"]},
        "model": None,
        "source_title": "本地判断样本",
    }


def test_legacy_mechanism_list_fields_accept_single_text_values(tmp_path) -> None:
    _db, library, _projects, system = setup_system(tmp_path)
    source = library.import_text(
        title="旧候选写法", source_type="paste", text="她决定继续追查真相。",
    )
    created = system._save_node("mechanism", {
        "name": "旧写法", "confidence": 0.9,
        "applicable_modes": "both", "applicable_stages": "开头",
        "applicable_genres": "悬疑", "incompatible_conditions": "纯日常题材不适用",
    }, source_id=source["id"], status="confirmed")

    listed = next(item for item in system.list_mechanisms() if item["id"] == created["id"])

    assert listed["data"]["applicable_modes"] == ["short", "long"]
    assert listed["data"]["applicable_stages"] == ["开头"]
    assert listed["data"]["applicable_genres"] == ["悬疑"]
    assert listed["data"]["incompatible_conditions"] == ["纯日常题材不适用"]


def test_initialization_contexts_filter_rules_by_stage_project_and_viewpoint(tmp_path) -> None:
    _db, _library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="第一人称悬疑", mode="short", genre="悬疑", premise="门后有人。",
        target_words=8000, pov="first",
    ))
    system.build_prose_baseline(project.id, {
        "dialogue": ["让每次回应改变关系或信息。"],
        "psychology": ["先写动作，再写人物判断。"],
        "sentence_rhythm": ["长短句交替。"],
        "viewpoint": ["需要时切换视角补充另一方信息。"],
    })
    system.save_artifact(project.id, "creative_blueprint", {
        "mechanisms": [
            {
                "name": "关系冲突进入对白", "transfer_guidance": "让对白改变人物关系。",
                "applicable_modes": ["short"], "applicable_stages": ["人物与关系"],
            },
            {
                "name": "地点规则制造限制", "transfer_guidance": "让地点规则限制人物行动。",
                "applicable_modes": ["short"], "applicable_stages": ["世界设定"],
            },
            {
                "name": "延迟答案", "transfer_guidance": "保留推进方式，替换人物、设定和具体情节。",
                "applicable_modes": ["short"], "applicable_stages": [],
            },
            {
                "name": "长篇专用", "transfer_guidance": "跨卷回收。",
                "applicable_modes": ["long"], "applicable_stages": [],
            },
            {
                "name": "科幻专用", "transfer_guidance": "围绕技术代价推进。",
                "applicable_modes": ["short"], "applicable_genres": ["科幻"],
            },
        ],
    })

    context = system.initialization_contexts(project.id)

    assert context["versions"] == {"prose_baseline": 1, "creative_blueprint": 1}
    assert [item["category"] for item in context["stages"]["character-management"]["prose_rules"]] == [
        "对白方式", "心理描写",
    ]
    assert context["stages"]["worldbuilding"]["prose_rules"] == []
    assert [item["name"] for item in context["stages"]["character-management"]["creative_methods"]] == [
        "关系冲突进入对白",
    ]
    assert [item["name"] for item in context["stages"]["worldbuilding"]["creative_methods"]] == [
        "地点规则制造限制",
    ]
    assert [item["name"] for item in context["stages"]["plot-structure"]["creative_methods"]] == [
        "关系冲突进入对白", "地点规则制造限制", "延迟答案",
    ]
    assert context["summary"]["creative_methods"] == 3
    assert context["summary"]["skipped_conflicts"] == 1
    assert "第一人称" in context["skipped_conflicts"][0]["reason"]


def test_cached_window_rebuilds_missing_mechanisms(tmp_path) -> None:
    db, library, _projects, system = setup_system(tmp_path)
    source = library.import_text(
        title="缓存恢复", source_type="paste", text="她推门后却发现真相，于是决定离开。",
    )
    first = system.analyze_reference(source["id"])
    assert first["mechanisms"]
    with db.connect() as connection:
        connection.execute("DELETE FROM learning_nodes WHERE node_type='mechanism' AND source_id=?", (source["id"],))

    second = system.analyze_reference(source["id"])

    assert second["cached_windows"] == 0
    assert second["mechanisms"]


def test_local_reference_analysis_returns_cross_text_attraction_candidates(tmp_path) -> None:
    _db, library, _projects, system = setup_system(tmp_path)
    source = library.import_text(
        title="无标签推进", source_type="paste",
        text="她烧掉返程票，独自走进封锁区。三天后药送到了，妹妹却不再认得她。",
    )

    result = system.analyze_reference(source["id"])

    assert result["attraction_candidates"]["coverage_percent"] == 100.0
    assert result["attraction_candidates"]["decisions"]
    assert result["attraction_candidates"]["consequences"]
    assert "候选证据" in result["attraction_candidates"]["boundary"]


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
    assert blocked["skipped"] == [{
        "id": protected["id"], "reason": "仍在作品中使用，取消应用后才能删除",
    }]


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


def test_adoption_edits_cannot_change_immutable_classification(tmp_path) -> None:
    _db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="Immutable adoption", mode="short", genre="mystery",
        premise="A choice changes the investigation", target_words=6_000,
    ))
    source = library.import_text(
        title="Style source", source_type="paste",
        text="A reply changes leverage without explaining the conflict.",
    )
    style = system._save_node("style_rule", {
        "field": "dialogue", "rule": "Let replies change leverage.",
        "confidence": 0.9,
    }, source_id=source["id"], status="confirmed")

    with pytest.raises(ValueError, match="classification authority"):
        system.adopt(project.id, style["id"], {
            "mechanism_type": "causal_structure",
            "transfer_guidance": "Alter the plot",
        })

    assert system.list_adoptions(project.id) == []


def test_legacy_adoption_markers_cannot_cross_node_type_buckets(tmp_path) -> None:
    db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="Legacy classification", mode="short", genre="mystery",
        premise="Authority must survive legacy data", target_words=6_000,
    ))
    source = library.import_text(
        title="Authority source", source_type="paste",
        text="The method and prose rule are independently attributable.",
    )
    style = system._save_node("style_rule", {
        "field": "dialogue", "rule": "Keep replies adversarial.",
        "confidence": 0.9,
    }, source_id=source["id"], status="confirmed")
    mechanism = system._save_node("mechanism", {
        "name": "Escalating choice", "transfer_guidance": "Narrow the options.",
        "confidence": 0.9,
    }, source_id=source["id"], status="confirmed")
    attraction = system._save_node("attraction_map", {
        "review_state": "confirmed", "opening": {
            "mechanism": "pressure_anomaly",
            "transfer_guidance": "Open with pressure and an anomaly.",
        },
    }, source_id=source["id"], status="confirmed")
    rows = (
        (style["id"], {
            "field": "dialogue", "rule": "Keep replies adversarial.",
            "mechanism_type": "causal_structure",
            "transfer_guidance": "STYLE_MUST_NOT_ENTER_PLOT",
        }),
        (mechanism["id"], {
            "name": "Escalating choice", "transfer_guidance": "Narrow the options.",
            "mechanism_type": "attraction_guidance",
            "opening_rule": "FORGED_ATTRACTION_RULE",
        }),
        (attraction["id"], {
            "mechanism_type": "causal_structure",
            "opening_rule": "Open with pressure and an anomaly.",
        }),
    )
    with db.connect() as connection:
        for ordinal, (node_id, data) in enumerate(rows, start=1):
            data["provenance"] = {"source_id": source["id"], "node_id": node_id}
            connection.execute(
                "INSERT INTO project_adoptions VALUES (?, ?, ?, 'adopted', ?, "
                "datetime('now'), datetime('now'))",
                (f"legacy-{ordinal}", project.id, node_id,
                 json.dumps(data, ensure_ascii=False)),
            )

    system._save_creative_blueprint(project.id)

    blueprint = system.get_artifact(project.id, "creative_blueprint")["data"]
    assert blueprint["causal_structure"] == []
    assert [item["name"] for item in blueprint["mechanisms"]] == ["Escalating choice"]
    assert [item["field"] for item in blueprint["style_rules"]] == ["dialogue"]
    assert blueprint["attraction_guidance"][0]["opening_rule"] == (
        "Open with pressure and an anomaly."
    )
    assert "STYLE_MUST_NOT_ENTER_PLOT" not in blueprint["rules"]
    assert "Narrow the options." in blueprint["rules"]

    recipe = system.get_artifact(project.id, "creative_recipe")["data"]
    assert len(recipe["mechanisms"]) == 1
    assert len(recipe["style_rules"]) == 1
    assert len(recipe["attraction_guidance"]) == 1
    context = system._outline_generation_context(project.id, project.metadata, "")
    assert context["writing_methods"] == [{
        "name": "Escalating choice", "transfer_guidance": "Narrow the options.",
    }]
    assert "FORGED_ATTRACTION_RULE" not in context["attraction_rules"]
    assert "Open with pressure and an anomaly." in context["attraction_rules"]


def test_learning_artifact_sidecar_projection_is_monotonic_across_writers(
    tmp_path, monkeypatch,
) -> None:
    db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="Monotonic projection", mode="short", genre="mystery",
        premise="Concurrent artifact updates", target_words=6_000,
    ))
    second_system = LearningSystem(db, library, projects)
    original_atomic_write = learning_module.atomic_write
    slow_projection_started = threading.Event()
    release_slow_projection = threading.Event()

    def delayed_atomic_write(path, content):
        payload = json.loads(content)
        if payload.get("data", {}).get("writer") == "slow":
            slow_projection_started.set()
            assert release_slow_projection.wait(timeout=5)
        return original_atomic_write(path, content)

    monkeypatch.setattr(learning_module, "atomic_write", delayed_atomic_write)
    with ThreadPoolExecutor(max_workers=2) as executor:
        slow = executor.submit(
            system.save_artifact, project.id, "voice_profiles", {"writer": "slow"},
        )
        assert slow_projection_started.wait(timeout=5)
        fast = executor.submit(
            second_system.save_artifact,
            project.id, "voice_profiles", {"writer": "fast"},
        )
        release_slow_projection.set()
        slow.result(timeout=10)
        fast.result(timeout=10)

    latest = system.get_artifact(project.id, "voice_profiles")
    sidecar = json.loads(
        (project.path / "learning" / "voice_profiles.json").read_text(encoding="utf-8")
    )
    assert latest is not None
    assert latest["version"] == 2
    assert latest["data"] == {"writer": "fast"}
    assert sidecar == system._artifact_sidecar_payload(latest)


def test_learning_artifact_read_repairs_a_stale_sidecar_from_db_authority(tmp_path) -> None:
    _db, _library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="Repair projection", mode="short", genre="mystery",
        premise="Repair a stale projection", target_words=6_000,
    ))
    artifact = system.save_artifact(
        project.id, "voice_profiles", {"hero": {"voice": "terse"}},
    )
    sidecar_path = project.path / "learning" / "voice_profiles.json"
    sidecar_path.write_text(json.dumps({
        "id": "stale", "version": 0, "status": "active",
        "source_hash": "0" * 64,
        "data": {"writer": "old"},
    }), encoding="utf-8")

    loaded = system.get_artifact(project.id, "voice_profiles")

    assert loaded == artifact
    assert json.loads(sidecar_path.read_text(encoding="utf-8")) == (
        system._artifact_sidecar_payload(artifact)
    )


def test_adoption_accepts_chinese_confidence_from_model_output(tmp_path) -> None:
    _db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="中文置信度", mode="short", genre="悬疑", premise="测试", target_words=10_000,
    ))
    source = library.import_text(title="样本", source_type="paste", text="她推门寻找真相。")
    high = system._save_node(
        "mechanism", {"key": "high", "name": "高置信写法", "confidence": "高"},
        source_id=source["id"], status="proposed",
    )
    medium = system._save_node(
        "mechanism", {"key": "medium", "name": "中置信写法", "confidence": "中"},
        source_id=source["id"], status="proposed",
    )

    assert system.adopt(project.id, high["id"])["data"]["confidence"] == 0.9
    with pytest.raises(ValueError, match="低置信度候选必须先确认分析"):
        system.adopt(project.id, medium["id"])


def test_duplicate_check_ignores_unrelated_names_with_shared_generic_guidance() -> None:
    guidance = "没有新增信息、状态变化或后果时不采用"
    adoptions = [
        {"node_id": str(index), "data": {"name": name, "transfer_guidance": guidance}}
        for index, name in enumerate((
            "将平台硬性要求转化为发布检查",
            "预期反转并重释既有信息",
            "延迟回答核心读者问题",
        ))
    ]

    assert LearningSystem._adoption_duplicates(adoptions) == []


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


@pytest.mark.asyncio
async def test_enabled_market_baseline_is_bounded_advice_for_outline_generation(tmp_path) -> None:
    _db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="原创悬疑", mode="short", genre="悬疑",
        premise="主角寻找失踪的朋友", target_words=10_000,
    ))
    source = library.import_text(
        title="参考样本", source_type="paste", text="她推门后发现真相。",
    )
    method = system._save_node("mechanism", {
        "name": "递进阻碍", "transfer_guidance": "每次尝试都改变下一步选择",
        "confidence": 0.9,
    }, source_id=source["id"], status="confirmed")
    system.adopt(project.id, method["id"])
    system.save_artifact(project.id, "market_baseline", {
        "key": {
            "platform": "知乎", "ranking_name": "盐选热榜",
            "category": "悬疑", "length_type": "short",
        },
        "sample_count": 12, "confidence_level": "advisory",
        "opening": {"question_percent": 75, "anomaly_percent": 66.7},
        "mechanisms": [
            {"name": f"常见机制 {index}", "work_count": 12 - index,
             "position_median": index * 10, "private_evidence": "不得发送"}
            for index in range(8)
        ],
        "samples": [{"title": "不得发送样本标题", "weight": 1}],
        "boundary": "只描述本地已确认同类样本，不代表成功原因。" * 20,
    })
    projects.set_market_baseline_selection(
        project.id, enabled=True,
        key={"platform": "知乎", "ranking_name": "盐选热榜", "category": "悬疑", "length_type": "short"},
    )

    class Gateway:
        calls = []

        async def complete(self, role, system_prompt, user, max_output_tokens=None):
            self.calls.append((role, system_prompt, json.loads(user), max_output_tokens))
            return SimpleNamespace(text="# 候选大纲\n\n## 开头\n朋友失踪。", receipt={})

    gateway = Gateway()
    system.gateway = gateway
    await system.generate_outline_candidate(project.id, "保留我的人物设定和原创结局")

    _role, prompt, context, _budget = gateway.calls[0]
    market = context["market_reference"]
    assert context["user_brief"] == "保留我的人物设定和原创结局"
    assert market["advisory_only"] is True
    assert market["sample_count"] == 12
    assert len(market["mechanisms"]) == 5
    assert len(json.dumps(market, ensure_ascii=False)) < 2_000
    assert "samples" not in market
    assert "不得发送" not in json.dumps(market, ensure_ascii=False)
    assert "不得覆盖 project_brief、user_brief、正式设定或原创选择" in prompt
    assert "不是质量门槛" in prompt

    disabled = projects.set_market_baseline_selection(project.id, enabled=False, key=None)
    context = system._outline_generation_context(project.id, disabled.metadata, "原创简报")
    assert "market_reference" not in context


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


def test_adopted_attraction_map_adds_only_abstract_guidance(tmp_path) -> None:
    _db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="吸引力迁移", mode="short", genre="悬疑", premise="原创送药故事", target_words=3000,
    ))
    source = library.import_text(
        title="河清海晏", source_type="paste", text="周海晏收下十块钱，真的保护了她十年。",
    )
    node = system._save_node("attraction_map", {
        "fit": {"level": "strong", "explanation": "承诺贯穿全文"},
        "opening": {
            "mechanism": "opening_pressure_anomaly_future_promise",
            "transfer_guidance": "先建立压力，再给反常行动和长期结果预告",
            "evidence": [{"start": 0, "end": 8, "excerpt": "周海晏收下十块钱"}],
        },
        "core_goal": {"surface": "获得保护", "emotional": "获得归属"},
        "cycles": [{
            "obstacle": "家暴", "effort": "向周海晏交十块钱", "result": "获得保护",
            "state_change": "从孤立变为拥有保护者", "transfer_guidance": "每轮结果改变人物可用选择",
            "evidence": [{"start": 0, "end": 8, "excerpt": "十块钱保护十年"}],
        }],
        "ending": {
            "surface_payoff": "保护兑现", "emotional_payoff": "确认被爱", "cost": "失去周海晏",
            "transfer_guidance": "结尾同时回答表层目标、情感目标和代价",
        },
        "review_state": "confirmed",
    }, source_id=source["id"], status="confirmed")

    system.adopt(project.id, node["id"])

    blueprint = system.get_artifact(project.id, "creative_blueprint")["data"]
    assert blueprint["attraction_guidance"][0]["opening"] == "opening_pressure_anomaly_future_promise"
    constraints = projects.load_constraints(project.id)
    assert "每轮结果改变人物可用选择" in constraints
    assert "周海晏" not in constraints
    assert "十块钱" not in constraints
    assert "excerpt" not in constraints


def test_legacy_claim_attraction_map_is_readable_without_rerunning_model(tmp_path) -> None:
    _db, library, _projects, system = setup_system(tmp_path)
    source = library.import_text(title="旧汇总", source_type="paste", text="她决定离开。" * 20)
    system._save_node("attraction_map", {
        "fit": {"level": "partial", "explanation": ""},
        "opening": {"hook": {"claim": "先给出长期结果，再隐藏实现过程", "evidence": []}},
        "core_goal": {"claim": "从摆脱威胁升级为获得稳定归属"},
        "cycles": [{"claim": "保护失效后，人物主动寻找新的支点"}],
        "accidents": [], "reversal": None,
        "ending": {"claim": "结尾同时兑现关系与公共意义"},
        "question_chain": [], "relationship_arc": [],
        "uncertainties": ["未识别出有证据支持的核心目标", "未识别出有证据支持的结局兑现"],
    }, source_id=source["id"], status="proposed")

    result = system.attraction_map(source["id"])["data"]

    assert result["opening"]["summary"] == "先给出长期结果，再隐藏实现过程"
    assert result["core_goal"]["summary"] == "从摆脱威胁升级为获得稳定归属"
    assert result["cycles"][0]["summary"] == "保护失效后，人物主动寻找新的支点"
    assert result["ending"]["summary"] == "结尾同时兑现关系与公共意义"
    assert result["uncertainties"] == []


def test_synthesis_rejects_generic_claim_shape_that_page_cannot_explain() -> None:
    value = {
        "mechanisms": [],
        "attraction_map": {
            "fit": {"level": "partial"}, "opening": {"hook": {"claim": "开头"}},
            "core_goal": {"claim": "目标"}, "cycles": [{"claim": "推进"}],
            "accidents": [], "reversal": None, "ending": {"claim": "结尾"},
            "question_chain": [], "relationship_arc": [], "uncertainties": [],
        },
    }

    with pytest.raises(ValueError, match="开头分析格式不完整"):
        LearningSystem._synthesis_result(value)


def test_artifact_restore_creates_new_version_and_effective_overview(tmp_path) -> None:
    _db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="版本恢复", mode="short", genre="悬疑", premise="寻找朋友", target_words=6000,
    ))
    source = library.import_text(title="参考样本", source_type="paste", text="他决定追查真相。")
    mechanism = system._save_node("mechanism", {
        "name": "长篇专用铺垫", "transfer_guidance": "分卷铺垫",
        "confidence": 0.9, "applicable_modes": ["long"],
        "incompatible_conditions": ["短篇篇幅不足时不要使用"],
    }, source_id=source["id"], status="confirmed")
    system.adopt(project.id, mechanism["id"])
    system.build_prose_baseline(project.id, {"dialogue": ["版本一"]})
    system.build_prose_baseline(project.id, {"dialogue": ["版本二"]})

    restored = system.restore_artifact(project.id, "prose_baseline", 1)
    overview = system.effective_rule_overview(project.id)

    assert restored["version"] == 3
    assert restored["data"]["dialogue"] == ["版本一"]
    assert len(system.artifact_history(project.id, "prose_baseline")) == 3
    assert any(item["name"] == "基础文笔规则" for item in overview["layers"])
    assert any("没有标记为适合短篇" in item["message"] for item in overview["conflicts"])
    assert overview["cautions"][0]["message"] == "短篇篇幅不足时不要使用"


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
        self.users = []
        self.requests = []

    async def complete(self, role, system, user, **kwargs):
        self.roles.append(role)
        self.users.append(user)
        self.requests.append({"role": role, "system": system, "user": user, **kwargs})
        return SimpleNamespace(
            text=_final_receipt_for_prompt(user, next(self.outputs)),
            receipt={"model_id": "fake"},
        )

    async def complete_primary(self, role, system, user, **kwargs):
        return await self.complete(role, system, user, **kwargs)


class ExactDistillationGateway:
    def __init__(self):
        self.requests = []

    async def complete(self, role, system, user, **kwargs):
        self.requests.append({"role": role, "system": system, "user": user, **kwargs})
        manifest_text = user.split("CHILD MANIFEST:\n", 1)[1].split(
            "\nCHILD PAYLOADS:\n", 1,
        )[0]
        child_ids = json.loads(manifest_text)
        receipt = {
            "version": 2,
            "covered_child_ids": child_ids,
            "child_dispositions": [
                {
                    "child_id": child_id,
                    "disposition": "no_transferable_claim",
                    "reason": "该窗口没有可安全迁移的抽象发现",
                }
                for child_id in child_ids
            ],
            "semantic": {
                "mechanisms": [], "attraction_map": {}, "style_profile": {},
            },
        }
        return SimpleNamespace(
            text=json.dumps(receipt, ensure_ascii=False),
            receipt={"model_id": "fake"},
        )

    async def complete_primary(self, role, system, user, **kwargs):
        return await self.complete(role, system, user, **kwargs)

    async def complete_configured_fallback(self, role, system, user, **kwargs):
        return await self.complete(role, system, user, **kwargs)


def hierarchical_claims(count: int, *, body_size: int = 0) -> list[dict]:
    return [{
        "data": {
            "window": index + 1,
            "window_start": index * 100,
            "window_end": index * 100 + 100,
            "result": {
                "marker": f"claim-{index}",
                "body": "甲" * body_size,
            },
        },
    } for index in range(count)]


@pytest.mark.asyncio
async def test_hierarchical_distillation_binds_purpose_focus_and_reuses_exact_cache(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    source = library.import_text(
        title="Hierarchical", source_type="paste", text="reference text",
    )
    gateway = ExactDistillationGateway()
    system = LearningSystem(db, library, projects, gateway)
    version = source["latest_version"]
    claim_set = hierarchical_claims(13)

    first = await system._hierarchical_reference_claims(
        version=version, claims=claim_set,
        content_type="reference_work", focus="extract structure",
    )
    first_calls = len(gateway.requests)
    repeated = await system._hierarchical_reference_claims(
        version=version, claims=claim_set,
        content_type="reference_work", focus="extract structure",
    )
    assert len(gateway.requests) == first_calls
    assert repeated == first

    await system._hierarchical_reference_claims(
        version=version, claims=claim_set,
        content_type="writing_tutorial", focus="extract structure",
    )
    purpose_calls = len(gateway.requests)
    assert purpose_calls > first_calls
    await system._hierarchical_reference_claims(
        version=version, claims=claim_set,
        content_type="writing_tutorial", focus="extract prose guidance",
    )
    assert len(gateway.requests) > purpose_calls
    assert first_calls == 3


@pytest.mark.asyncio
async def test_hierarchical_distillation_capacity_splits_six_large_children_losslessly(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    source = library.import_text(
        title="Capacity", source_type="paste", text="large reference text",
    )
    db.save_provider(
        provider_id="primary", name="Primary", protocol="openai",
        base_url="https://primary.invalid", auth_type="none",
        timeout_seconds=30, extra_headers={},
    )
    db.save_provider(
        provider_id="fallback", name="Fallback", protocol="openai",
        base_url="https://fallback.invalid", auth_type="none",
        timeout_seconds=30, extra_headers={},
    )
    db.save_model(
        model_id="primary-16k", provider_id="primary", display_name="Primary 16K",
        model_name="primary-16k", context_window=16_384,
        max_output_tokens=4_096,
    )
    db.save_model(
        model_id="fallback-20k", provider_id="fallback", display_name="Fallback 20K",
        model_name="fallback-20k", context_window=20_000,
        max_output_tokens=4_096,
    )
    db.save_role_binding(
        "reference_synthesis", "primary", "primary-16k",
        "fallback", "fallback-20k",
    )
    gateway = ExactDistillationGateway()
    system = LearningSystem(db, library, projects, gateway)

    reduced = await system._hierarchical_reference_claims(
        version=source["latest_version"],
        claims=hierarchical_claims(6, body_size=3_000),
        content_type="reference_work", focus="preserve every child",
    )

    assert system._reference_synthesis_input_token_limit() == 9_011
    assert system._reference_synthesis_route_plan().mode == "auto"
    assert len(gateway.requests) == 3
    all_prompts = "".join(item["user"] for item in gateway.requests)
    assert all(f"claim-{index}" in all_prompts for index in range(6))
    assert all(
        estimate_input_tokens(item["system"] + item["user"]) < 9_011
        for item in gateway.requests
    )
    assert [
        child
        for item in reduced
        for child in item["runtime_coverage"]["child_ids"]
    ] == [f"window:{index}" for index in range(1, 7)]


def test_reference_synthesis_unknown_route_uses_conservative_context_budget(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    system = LearningSystem(db, library, projects, ExactDistillationGateway())

    assert system._reference_synthesis_input_token_limit() == 9_011


@pytest.mark.asyncio
async def test_reference_synthesis_route_plan_bypasses_tiny_primary_for_fallback(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    db.save_provider(
        provider_id="tiny", name="Tiny", protocol="openai",
        base_url="https://tiny.invalid", auth_type="none",
        timeout_seconds=30, extra_headers={},
    )
    db.save_provider(
        provider_id="large", name="Large", protocol="openai",
        base_url="https://large.invalid", auth_type="none",
        timeout_seconds=30, extra_headers={},
    )
    db.save_model(
        model_id="primary-4k", provider_id="tiny", display_name="Primary 4K",
        model_name="primary-4k", context_window=4_096,
        max_output_tokens=4_096,
    )
    db.save_model(
        model_id="fallback-32k", provider_id="large", display_name="Fallback 32K",
        model_name="fallback-32k", context_window=32_768,
        max_output_tokens=4_096,
    )
    db.save_role_binding(
        "reference_synthesis", "tiny", "primary-4k",
        "large", "fallback-32k",
    )

    class RouteGateway:
        def __init__(self):
            self.routes = []

        async def complete(self, *_args, **_kwargs):
            self.routes.append("auto")
            raise AssertionError("tiny primary must not receive the request")

        async def complete_configured_fallback(self, *_args, **_kwargs):
            self.routes.append("fallback")
            return SimpleNamespace(text=route_schedule_receipt(), receipt={})

    gateway = RouteGateway()
    system = LearningSystem(db, library, projects, gateway)
    plan = system._reference_synthesis_route_plan()

    response, value = await system._execute_reference_synthesis(
        route_plan=plan, system="system", user="user",
        validator=route_schedule_semantic,
    )

    assert plan.version == 1
    assert plan.mode == "fallback"
    assert plan.input_token_limit == 22_118
    assert gateway.routes == ["fallback"]
    assert response.receipt == {}
    assert value == {"ok": True}


@pytest.mark.asyncio
async def test_reference_synthesis_auto_expands_to_explicit_route_schedule(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)

    class RouteGateway:
        def __init__(self):
            self.routes = []
            self.fallback_outputs = iter(["not-json", route_schedule_receipt()])

        async def complete(self, *_args, **_kwargs):
            raise AssertionError("auto must not use hidden gateway routing")

        async def complete_primary(self, *_args, **_kwargs):
            self.routes.append("primary")
            return SimpleNamespace(text="not-json", receipt={})

        async def complete_configured_fallback(self, *_args, **_kwargs):
            self.routes.append("fallback")
            return SimpleNamespace(text=next(self.fallback_outputs), receipt={})

    gateway = RouteGateway()
    system = LearningSystem(db, library, projects, gateway)
    plan = ReferenceSynthesisRoutePlanV1(
        version=1, mode="auto", input_token_limit=9_000,
        primary_input_token_limit=9_000,
        fallback_input_token_limit=10_000,
    )

    _response, value = await system._execute_reference_synthesis(
        route_plan=plan, system="system", user="user",
        validator=route_schedule_semantic,
    )

    assert gateway.routes == ["primary", "primary", "fallback", "fallback"]
    assert value == {"ok": True}


@pytest.mark.asyncio
async def test_reference_synthesis_route_plan_uses_primary_when_it_is_only_route(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    db.save_provider(
        provider_id="primary", name="Primary", protocol="openai",
        base_url="https://primary.invalid", auth_type="none",
        timeout_seconds=30, extra_headers={},
    )
    db.save_model(
        model_id="primary-32k", provider_id="primary", display_name="Primary 32K",
        model_name="primary-32k", context_window=32_768,
        max_output_tokens=4_096,
    )
    db.save_role_binding(
        "reference_synthesis", "primary", "primary-32k", None, None,
    )

    class RouteGateway:
        def __init__(self):
            self.routes = []

        async def complete_primary(self, *_args, **_kwargs):
            self.routes.append("primary")
            return SimpleNamespace(text=route_schedule_receipt(), receipt={})

        async def complete(self, *_args, **_kwargs):
            self.routes.append("auto")
            raise AssertionError("primary-only plan must use direct primary execution")

    gateway = RouteGateway()
    system = LearningSystem(db, library, projects, gateway)
    plan = system._reference_synthesis_route_plan()

    _response, value = await system._execute_reference_synthesis(
        route_plan=plan, system="system", user="user",
        validator=route_schedule_semantic,
    )

    assert plan.mode == "primary"
    assert gateway.routes == ["primary"]
    assert value == {"ok": True}


@pytest.mark.asyncio
async def test_reference_synthesis_primary_only_retries_one_invalid_receipt(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    db.save_provider(
        provider_id="primary", name="Primary", protocol="openai",
        base_url="https://primary.invalid", auth_type="none",
        timeout_seconds=30, extra_headers={},
    )
    db.save_model(
        model_id="primary-32k", provider_id="primary", display_name="Primary 32K",
        model_name="primary-32k", context_window=32_768,
        max_output_tokens=4_096,
    )
    db.save_role_binding(
        "reference_synthesis", "primary", "primary-32k", None, None,
    )

    class RouteGateway:
        def __init__(self):
            self.outputs = iter(["not-json", route_schedule_receipt()])
            self.routes = []

        async def complete_primary(self, *_args, **_kwargs):
            self.routes.append("primary")
            return SimpleNamespace(text=next(self.outputs), receipt={})

    gateway = RouteGateway()
    system = LearningSystem(db, library, projects, gateway)

    _response, value = await system._execute_reference_synthesis(
        route_plan=system._reference_synthesis_route_plan(),
        system="system", user="user", validator=route_schedule_semantic,
    )

    assert gateway.routes == ["primary", "primary"]
    assert value == {"ok": True}


@pytest.mark.asyncio
async def test_final_synthesis_cannot_discard_promoted_hierarchy_semantics(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    system = LearningSystem(db, library, projects)
    prior = {
        "semantic": {
            "mechanisms": [{"name": "retained-A"}],
            "attraction_map": {}, "style_profile": {},
        },
        "runtime_coverage": {
            "child_ids": ["window:1"], "child_count": 1,
            "input_sha256": "a" * 64, "source_range": [0, 10],
            "semantic_sha256": "b" * 64,
        },
    }
    region = system._final_synthesis_region([prior], max_payload_tokens=7_000)
    child_id = region.child_ids[0]
    bad = {
        "version": 2, "covered_child_ids": [child_id],
        "child_dispositions": [{
            "child_id": child_id, "disposition": "no_transferable_claim",
            "reason": "The prior semantic is incorrectly discarded here.",
        }],
        "child_attributions": [],
        "semantic": {
            "mechanisms": [], "attraction_map": {}, "style_profile": {},
        },
    }
    good = {
        "version": 2, "covered_child_ids": [child_id],
        "child_dispositions": [{
            "child_id": child_id, "disposition": "promoted",
            "reason": "The prior semantic remains in the final mechanism.",
        }],
        "child_attributions": [{
            "child_id": child_id, "relation": "claim",
            "semantic_path": "/mechanisms/0", "related_child_ids": [],
        }],
        "semantic": {
            "mechanisms": [{"name": "retained-A"}],
            "attraction_map": {}, "style_profile": {},
        },
    }

    class Gateway:
        def __init__(self):
            self.outputs = iter([bad, good])
            self.calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            return SimpleNamespace(text=json.dumps(next(self.outputs)), receipt={})

    gateway = Gateway()
    system.gateway = gateway
    _response, semantic = await system._execute_reference_synthesis(
        route_plan=system._reference_synthesis_route_plan(),
        system="system", user="user",
        validator=lambda text: validate_distillation_receipt(
            region, json.loads(text),
        ),
    )

    assert gateway.calls == 2
    assert semantic["mechanisms"] == [{"name": "retained-A"}]


@pytest.mark.asyncio
async def test_hierarchical_distillation_fails_when_semantic_payload_does_not_converge(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    source = library.import_text(
        title="Non-converging", source_type="paste", text="reference text",
    )

    class NonConvergingGateway:
        async def complete(self, role, system, user, **kwargs):
            child_ids = json.loads(user.split("CHILD MANIFEST:\n", 1)[1].split(
                "\nCHILD PAYLOADS:\n", 1,
            )[0])
            semantic = {
                "mechanisms": [{
                    "name": "保持超大语义负载",
                    "supporting_windows": [1],
                    "transfer_guidance": "甲" * 4_000,
                }],
                "attraction_map": {}, "style_profile": {},
            }
            receipt = {
                "version": 2,
                "covered_child_ids": child_ids,
                "child_dispositions": [{
                    "child_id": child_id, "disposition": "promoted",
                    "reason": "该窗口保留到聚合机制中",
                } for child_id in child_ids],
                "child_attributions": [{
                    "child_id": child_ids[0], "relation": "claim",
                    "semantic_path": "/mechanisms/0", "related_child_ids": [],
                }, *[{
                    "child_id": child_id, "relation": "merged",
                    "semantic_path": None, "related_child_ids": [child_ids[0]],
                } for child_id in child_ids[1:]]],
                "semantic": semantic,
            }
            return SimpleNamespace(
                text=json.dumps(receipt, ensure_ascii=False), receipt={},
            )

    system = LearningSystem(db, library, projects, NonConvergingGateway())

    with pytest.raises(ValueError, match="did not reduce"):
        await system._hierarchical_reference_claims(
            version=source["latest_version"],
            claims=hierarchical_claims(6, body_size=500),
            content_type="reference_work", focus="preserve semantics",
            final_payload_tokens=2_000, regional_payload_tokens=6_000,
        )


async def test_model_analysis_resumes_after_any_failed_window(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    source = library.import_text(
        title="任意窗口续跑", source_type="paste", text="甲" * 12_000,
    )

    class FailsOnThirdWindow(FakeGateway):
        async def complete(self, role, system, user, **kwargs):
            if role == "reference_analysis" and self.roles.count(role) >= 2:
                self.roles.append(role)
                raise RuntimeError("第三个窗口临时失败")
            return await super().complete(role, system, user, **kwargs)

    first_gateway = FailsOnThirdWindow([valid_window_result(), valid_window_result()])
    first_system = LearningSystem(db, library, projects, first_gateway)
    with pytest.raises(RuntimeError, match="第三个窗口临时失败"):
        await first_system.model_analyze_reference(source["id"])

    resumed_gateway = FakeGateway([
        valid_window_result(),
        valid_synthesis_result(),
    ])
    resumed_system = LearningSystem(db, library, projects, resumed_gateway)
    progress = []

    result = await resumed_system.model_analyze_reference(source["id"], progress.append)

    assert result["claims"] == 3
    assert resumed_gateway.roles == ["reference_analysis", "reference_synthesis"]
    assert progress[0] == {
        "phase": "analyzing_windows",
        "completed_windows": 2,
        "total_windows": 3,
        "reused_windows": 2,
        "current_window": 3,
    }


async def test_model_analysis_reuses_unchanged_dynamic_windows_after_new_version(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    original = "甲" * 12_000
    source = library.import_text(title="动态分窗", source_type="paste", text=original)
    first_gateway = FakeGateway([
        valid_window_result(), valid_window_result(), valid_window_result(),
        valid_synthesis_result(),
    ])
    await LearningSystem(db, library, projects, first_gateway).model_analyze_reference(source["id"])
    library.add_version(source["id"], original[:-1] + "乙")

    resumed_gateway = FakeGateway([valid_window_result(), valid_synthesis_result()])
    progress = []
    result = await LearningSystem(
        db, library, projects, resumed_gateway,
    ).model_analyze_reference(source["id"], progress.append)

    assert result["claims"] == 3
    assert resumed_gateway.roles == ["reference_analysis", "reference_synthesis"]
    assert progress[0]["reused_windows"] == 2
    assert progress[0]["current_window"] == 3


async def test_model_analysis_reuses_all_windows_after_synthesis_failure(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    source = library.import_text(title="汇总续跑", source_type="paste", text="甲" * 7_000)

    class FailsSynthesis(FakeGateway):
        async def complete(self, role, system, user, **kwargs):
            if role == "reference_synthesis":
                self.roles.append(role)
                raise RuntimeError("汇总接口临时失败")
            return await super().complete(role, system, user, **kwargs)

    first_gateway = FailsSynthesis([valid_window_result(), valid_window_result()])
    with pytest.raises(RuntimeError, match="汇总接口临时失败"):
        await LearningSystem(db, library, projects, first_gateway).model_analyze_reference(source["id"])

    resumed_gateway = FakeGateway([valid_synthesis_result()])
    progress = []
    result = await LearningSystem(
        db, library, projects, resumed_gateway,
    ).model_analyze_reference(source["id"], progress.append)

    assert result["claims"] == 2
    assert resumed_gateway.roles == ["reference_synthesis"]
    assert progress[0]["reused_windows"] == 2
    assert progress[0]["current_window"] is None


async def test_model_analysis_rechecks_v1_window_for_prose_evidence(tmp_path) -> None:
    db, library, projects, system = setup_system(tmp_path)
    source = library.import_text(
        title="旧版文笔证据", source_type="paste", text="她推开门，先看见桌上的旧信。",
    )
    window = system._windows("她推开门，先看见桌上的旧信。")[0]
    system._save_node("model_claim", {
        "window": 1, "window_start": window["start"], "window_end": window["end"],
        "analysis_version": "reference-model-window-v1", "checkpoint_key": "old",
        "result": json.loads(valid_window_result()), "review_state": "proposal",
        "model_receipt": {"model_id": "old-model"},
    }, source_id=source["id"], status="proposed")
    gateway = FakeGateway([valid_window_result(), valid_synthesis_result()])
    progress = []

    await LearningSystem(db, library, projects, gateway).model_analyze_reference(
        source["id"], progress.append,
    )

    assert gateway.roles == ["reference_analysis", "reference_synthesis"]
    assert progress[0]["reused_windows"] == 0


async def test_model_analysis_recovers_valid_legacy_claim_for_single_version_source(tmp_path) -> None:
    db, library, projects, system = setup_system(tmp_path)
    text = "甲" * 7_000
    source = library.import_text(title="旧窗口恢复", source_type="paste", text=text)
    first_window = system._windows(text)[0]
    legacy = system._save_node("model_claim", {
        "window": first_window["index"],
        "window_start": first_window["start"],
        "window_end": first_window["end"],
        "result": json.loads(valid_window_result()),
        "review_state": "proposal",
        "model_receipt": {"model_id": "legacy"},
    }, source_id=source["id"], status="proposed")
    gateway = FakeGateway([valid_window_result(), valid_synthesis_result()])
    progress = []

    result = await LearningSystem(
        db, library, projects, gateway,
    ).model_analyze_reference(source["id"], progress.append)

    migrated = system.get_node(legacy["id"])["data"]
    assert result["claims"] == 2
    assert gateway.roles == ["reference_analysis", "reference_synthesis"]
    assert progress[0]["reused_windows"] == 1
    assert migrated["analysis_version"]
    assert migrated["window_hash"]
    assert migrated["source_version_id"] == source["latest_version"]["id"]


async def test_model_analysis_uses_explicit_roles_and_keeps_claims_proposed(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    gateway = FakeGateway([
        '{"events":[{"start":0,"end":3,"fact":"发现线索","interpretation":"信息变化","confidence":0.8}],'
        '"state_changes":[],"reader_questions":[],"turning_points":[],"relationship_changes":[],"style_evidence":[]}',
        '{"mechanisms":[{"name":"延迟揭示","supporting_windows":[1],"trigger_conditions":["线索"],'
        '"structural_position":"中段","state_change":"获得信息","emotional_effect":"意外",'
        '"required_preparation":["伏笔"],"downstream_consequence":"改变选择",'
        '"transfer_guidance":"替换内容包装","incompatible_conditions":[],"confidence":0.8}],"attraction_map":{}}',
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


async def test_model_analysis_creates_evidenced_style_candidates_without_extra_call(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    gateway = FakeGateway([
        json.dumps({
            "events": [], "state_changes": [], "reader_questions": [],
            "turning_points": [], "relationship_changes": [],
            "style_evidence": [{
                "field": "psychology",
                "start": 0, "end": 9, "fact": "先写动作再写判断",
                "interpretation": "让情绪由证据自然显现", "confidence": 0.88,
            }],
        }, ensure_ascii=False),
        json.dumps({
            "mechanisms": [], "attraction_map": {},
            "style_profile": {
                "summary": "动作先于情绪判断",
                "rules": [{
                    "field": "psychology", "rule": "先给出可观察动作，再写人物的有限判断",
                    "when_to_use": "人物情绪发生变化时",
                    "avoid": "不要直接替读者总结情绪",
                    "supporting_windows": [1], "confidence": 0.86,
                }],
                "uncertainties": [],
            },
        }, ensure_ascii=False),
    ])
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(
        title="文笔样本", source_type="paste", text="她攥紧袖口，半晌才抬起眼。",
    )

    result = await system.model_analyze_reference(source["id"])
    listed = system.list_style_candidates(source["id"])

    assert gateway.roles == ["reference_analysis", "reference_synthesis"]
    assert len(result["style_candidates"]) == len(listed) == 1
    assert listed[0]["status"] == "proposed"
    assert listed[0]["data"]["field"] == "psychology"
    assert listed[0]["data"]["rule"] == "先给出可观察动作，再写人物的有限判断"
    assert listed[0]["evidence"][0]["excerpt"] == "她攥紧袖口，半晌才"
    assert '"style_profile":{}' in gateway.requests[1]["user"]


async def test_model_analysis_recovers_missing_style_window_from_same_category_evidence(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    gateway = FakeGateway([
        json.dumps({
            "events": [], "state_changes": [], "reader_questions": [],
            "turning_points": [], "relationship_changes": [],
            "style_evidence": [{
                "field": "dialogue", "start": 0, "end": 8,
                "fact": "对话回应同时改变信息",
                "interpretation": "冲突对白应让关系或信息发生变化",
                "confidence": 0.88,
            }],
        }, ensure_ascii=False),
        json.dumps({
            "mechanisms": [], "attraction_map": {},
            "style_profile": {
                "summary": "对白推动关系变化",
                "rules": [{
                    "field": "dialogue", "rule": "让每次关键回应带来新信息或关系变化",
                    "when_to_use": "人物冲突时", "avoid": "不要重复已知信息",
                    "confidence": 0.84,
                }],
                "uncertainties": [],
            },
        }, ensure_ascii=False),
    ])
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(
        title="遗漏窗口编号", source_type="paste", text="她问出真相，他却承认早已知情。",
    )

    result = await system.model_analyze_reference(source["id"])
    listed = system.list_style_candidates(source["id"])

    assert len(result["style_candidates"]) == 1
    assert result["style_candidates"][0]["data"]["supporting_windows"] == [1]
    assert listed[0]["evidence"]


async def test_model_analysis_ignores_unsupported_style_rule_without_losing_summary(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    gateway = FakeGateway([
        valid_window_result(),
        json.dumps({
            "mechanisms": [{
                "name": "延迟揭示", "supporting_windows": [1],
                "transfer_guidance": "把关键回答延后到人物采取行动之后",
            }],
            "attraction_map": {},
            "style_profile": {
                "summary": "动作先于情绪判断",
                "rules": [{
                    "field": "psychology",
                    "rule": "先给动作，再写人物判断",
                    "when_to_use": "人物情绪变化时",
                    "avoid": "不要直接总结情绪",
                    "confidence": 0.8,
                }],
                "uncertainties": [],
            },
        }, ensure_ascii=False),
    ])
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(
        title="缺少文笔依据的样本", source_type="paste", text="她推开门，停在原地。",
    )

    result = await system.model_analyze_reference(source["id"])

    assert len(result["mechanisms"]) == 1
    assert result["style_candidates"] == []
    assert gateway.roles == ["reference_analysis", "reference_synthesis"]


def test_confirmed_style_candidate_merges_into_versioned_prose_baseline(tmp_path) -> None:
    _db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="文笔应用", mode="short", genre="都市", premise="测试", target_words=8000,
    ))
    source = library.import_text(title="优秀样本", source_type="paste", text="她推开门。")
    candidate = system._save_node("style_rule", {
        "field": "dialogue", "rule": "每次回应都改变信息或人物关系",
        "when_to_use": "冲突对白", "avoid": "不要只重复已知信息",
        "supporting_windows": [1], "confidence": 0.9,
    }, source_id=source["id"], status="proposed")
    system.build_prose_baseline(project.id, {"psychology": ["先给证据，再写判断"]})

    with pytest.raises(ValueError, match="先确认"):
        system.apply_style_candidate(project.id, candidate["id"])

    system.revise_node(candidate["id"], "confirm", {})
    applied = system.apply_style_candidate(project.id, candidate["id"])
    repeated = system.apply_style_candidate(project.id, candidate["id"])

    assert applied["version"] == repeated["version"] == 2
    assert applied["data"]["psychology"] == ["先给证据，再写判断"]
    assert applied["data"]["dialogue"] == ["每次回应都改变信息或人物关系"]
    assert len(system.artifact_history(project.id, "prose_baseline")) == 2


async def test_model_analysis_updates_matching_local_candidate_instead_of_duplicating(tmp_path) -> None:
    db, library, projects, local_system = setup_system(tmp_path)
    source = library.import_text(
        title="合并判断样本", source_type="paste", text="她决定离开，却在门口发现了真相。",
    )
    local = local_system.analyze_reference(source["id"])["mechanisms"]
    local_id = next(item["id"] for item in local if item["data"]["name"] == "通过状态变化推动下一步选择")
    gateway = FakeGateway([
        valid_window_result(),
        json.dumps({
            "mechanisms": [{
                "name": "选择产生不可逆后果", "supporting_windows": [1],
                "trigger_conditions": ["人物面临明确选择"], "structural_position": "故事前段",
                "state_change": "人物失去退路", "emotional_effect": "增强紧迫感",
                "required_preparation": ["提前交代可选退路"], "downstream_consequence": "迫使人物承担后果",
                "transfer_guidance": "让选择改变人物之后能够采取的行动",
                "incompatible_conditions": ["选择没有实际后果时不要使用"], "confidence": 0.86,
                "local_match_id": local_id, "model_verdict": "confirmed",
                "review_reason": "原文中的选择确实改变了后续行动范围",
            }],
            "attraction_map": {},
        }, ensure_ascii=False),
    ])
    system = LearningSystem(db, library, projects, gateway)

    result = await system.model_analyze_reference(source["id"])
    listed = system.list_mechanisms(source["id"])

    assert [item["id"] for item in result["mechanisms"]] == [local_id]
    assert len([item for item in listed if item["id"] == local_id]) == 1
    matched = next(item for item in listed if item["id"] == local_id)
    assert matched["data"]["analysis_origin"] == "hybrid"
    assert matched["data"]["model_review"]["verdict"] == "confirmed"
    assert matched["analysis"]["state"] == "model_confirmed"
    assert local_id in gateway.requests[1]["user"]
    assert "先独立分析" in gateway.requests[0]["user"]
    assert "所有面向用户的文字必须使用简体中文" in gateway.requests[1]["user"]


async def test_model_analysis_keeps_independent_new_finding_as_model_only(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    gateway = FakeGateway([
        valid_window_result(),
        json.dumps({
            "mechanisms": [{
                "name": "关系变化推动线索升级", "supporting_windows": [1],
                "trigger_conditions": ["人物关系发生变化"], "structural_position": "故事中段",
                "state_change": "盟友转为对立", "emotional_effect": "提高不确定感",
                "required_preparation": ["提前建立合作关系"], "downstream_consequence": "旧线索获得新解释",
                "transfer_guidance": "让关系变化同时改变人物能够获得的信息",
                "incompatible_conditions": [], "confidence": 0.81,
                "local_match_id": None, "model_verdict": "new",
                "review_reason": "这是模型独立发现的关系变化，本地规则没有对应候选",
            }],
            "attraction_map": {},
        }, ensure_ascii=False),
    ])
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(title="模型新增样本", source_type="paste", text="盟友沉默地交出了主角的藏身处。")

    result = await system.model_analyze_reference(source["id"])
    created = result["mechanisms"][0]
    listed = next(item for item in system.list_mechanisms(source["id"]) if item["id"] == created["id"])

    assert created["data"]["analysis_origin"] == "model"
    assert listed["analysis"]["state"] == "model_only"
    assert listed["analysis"]["model"]["verdict"] == "new"


async def test_model_analysis_rejects_english_user_facing_synthesis(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    english_synthesis = json.dumps({
        "mechanisms": [{
            "name": "The Small Currency Covenant", "supporting_windows": [1],
            "trigger_conditions": ["small payment"], "structural_position": "opening",
            "state_change": "trust begins", "emotional_effect": "warmth",
            "required_preparation": ["protector appears"], "downstream_consequence": "future rescue",
            "transfer_guidance": "Use a small payment to establish trust",
            "incompatible_conditions": [], "confidence": 0.9,
            "local_match_id": None, "model_verdict": "new", "review_reason": "Found by model",
        }],
        "attraction_map": {},
    })
    gateway = FakeGateway([
        valid_window_result(),
        english_synthesis, english_synthesis,
    ])
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(title="英文输出样本", source_type="paste", text="他递出十元钱，约定以后再见。")

    with pytest.raises(ValueError, match="简体中文"):
        await system.model_analyze_reference(source["id"])


async def test_model_analysis_limits_window_shape_to_avoid_truncated_json(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    gateway = FakeGateway([valid_window_result(), valid_synthesis_result()])
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(
        title="compact-window", source_type="paste", text="一段需要分析的正文。",
    )

    await system.model_analyze_reference(source["id"])

    window_request = gateway.requests[0]
    assert window_request["max_output_tokens"] == 4096
    assert "Use at most 1 highest-value item in each list" in window_request["user"]
    assert '{"events":[],"state_changes":[],"reader_questions":[],' in window_request["user"]
    assert "Use [] when that category has no supported item" in window_request["user"]

    synthesis_request = gateway.requests[1]
    assert synthesis_request["role"] == "reference_synthesis"
    assert '{"mechanisms":[],"attraction_map":{},"style_profile":{}}' in synthesis_request["user"]
    assert "Use at most 3 mechanisms" in synthesis_request["user"]


async def test_model_analysis_saves_proposed_attraction_map_with_local_evidence(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    gateway = FakeGateway([
        '{"events":[{"start":0,"end":10,"fact":"递出钥匙","interpretation":"主动冒险","confidence":0.8}],'
        '"state_changes":[],"reader_questions":[],"turning_points":[],"relationship_changes":[],"style_evidence":[]}',
        json.dumps({
            "mechanisms": [],
            "attraction_map": {
                "fit": {"level": "strong", "explanation": "目标和推进清楚"},
                "opening": {
                    "mechanism": "opening_pressure_anomaly_future_promise",
                    "transfer_guidance": "先建立压力，再给反常行动和后果预告",
                    "evidence": [{"start": 0, "end": 10, "excerpt": "她把钥匙递给仇人"}],
                },
                "core_goal": {"surface": "把药送进封锁区", "emotional": "得到妹妹原谅"},
                "cycles": [{
                    "obstacle": "封锁", "effort": "冒险进入", "result": "药已送到",
                    "state_change": "妹妹获救但忘记主角", "transfer_guidance": "结果解决旧问题并产生新问题",
                }],
                "accidents": [],
                "reversal": None,
                "ending": {"surface_payoff": "药已送到", "emotional_payoff": "尚未和解", "cost": "失去共同记忆"},
                "question_chain": [], "relationship_arc": [], "uncertainties": [],
            },
        }, ensure_ascii=False),
    ])
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(
        title="无标签结构", source_type="paste",
        text="她把钥匙递给仇人，独自走进封锁区。三天后药送到了，妹妹却不再认得她。",
    )

    result = await system.model_analyze_reference(source["id"])

    assert "LOCAL ATTRACTION CANDIDATES" in gateway.users[0]
    assert result["attraction_map"]["status"] == "proposed"
    assert result["attraction_map"]["data"]["fit"]["level"] == "strong"
    assert result["attraction_map"]["data"]["cycles"][0]["state_change"] == "妹妹获救但忘记主角"
    assert system.attraction_map(source["id"])["id"] == result["attraction_map"]["id"]


async def test_model_analysis_explains_empty_window_response(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    system = LearningSystem(db, library, projects, FakeGateway(["", ""]))
    source = library.import_text(title="empty-model", source_type="paste", text="一段需要分析的正文。")

    with pytest.raises(ValueError, match="第 1 个文本窗口.*空内容"):
        await system.model_analyze_reference(source["id"])


async def test_model_analysis_uses_configured_fallback_for_invalid_json(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)

    class GatewayWithFallback(FakeGateway):
        def __init__(self):
            super().__init__([
                "", "",
                valid_synthesis_result(),
            ])
            self.fallback_roles = []

        async def complete_configured_fallback(self, role, system, user, **kwargs):
            self.fallback_roles.append(role)
            return SimpleNamespace(text=valid_window_result(), receipt={"model_id": "fallback"})

    gateway = GatewayWithFallback()
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(title="fallback-model", source_type="paste", text="一段需要分析的正文。")
    progress = []

    result = await system.model_analyze_reference(source["id"], progress.append)

    assert result["claims"] == 1
    assert gateway.fallback_roles == ["reference_analysis"]
    assert any(item["phase"] == "fallback_window" for item in progress)


async def test_model_analysis_retries_a_transient_fallback_failure(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)

    class GatewayWithTransientFallback(FakeGateway):
        def __init__(self):
            super().__init__(["", "", valid_synthesis_result()])
            self.fallback_calls = 0

        async def complete_configured_fallback(self, role, system, user, **kwargs):
            self.fallback_calls += 1
            if self.fallback_calls == 1:
                raise TimeoutError()
            return SimpleNamespace(text=valid_window_result(), receipt={"model_id": "fallback"})

    gateway = GatewayWithTransientFallback()
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(
        title="fallback-retry", source_type="paste", text="一段需要分析的正文。",
    )

    result = await system.model_analyze_reference(source["id"])

    assert result["claims"] == 1
    assert gateway.fallback_calls == 2


async def test_model_analysis_reuses_valid_fallback_for_remaining_windows(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)

    class GatewayWithReusableFallback(FakeGateway):
        def __init__(self):
            super().__init__(["", "", valid_synthesis_result()])
            self.fallback_roles = []

        async def complete_configured_fallback(self, role, system, user, **kwargs):
            self.fallback_roles.append(role)
            return SimpleNamespace(text=valid_window_result(), receipt={"model_id": "fallback"})

    gateway = GatewayWithReusableFallback()
    system = LearningSystem(db, library, projects, gateway)
    text = ("甲" * 3400) + "。\n\n" + ("乙" * 3400) + "。"
    source = library.import_text(title="two-windows", source_type="paste", text=text)

    result = await system.model_analyze_reference(source["id"])

    assert result["claims"] == 2
    assert gateway.roles == [
        "reference_analysis", "reference_analysis", "reference_synthesis",
    ]
    assert gateway.fallback_roles == ["reference_analysis", "reference_analysis"]


async def test_model_analysis_retries_one_transient_invalid_fallback_response(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)

    class GatewayWithTransientFallback(FakeGateway):
        def __init__(self):
            super().__init__(["", "", valid_synthesis_result()])
            self.fallback_outputs = iter(["not-json", valid_window_result()])
            self.fallback_roles = []

        async def complete_configured_fallback(self, role, system, user, **kwargs):
            self.fallback_roles.append(role)
            return SimpleNamespace(
                text=_final_receipt_for_prompt(user, next(self.fallback_outputs)),
                receipt={"model_id": "fallback"},
            )

    gateway = GatewayWithTransientFallback()
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(
        title="transient-fallback", source_type="paste", text="一段需要分析的正文。",
    )

    result = await system.model_analyze_reference(source["id"])

    assert result["claims"] == 1
    assert gateway.fallback_roles == ["reference_analysis", "reference_analysis"]


def valid_window_result() -> str:
    return json.dumps({
        "events": [], "state_changes": [], "reader_questions": [],
        "turning_points": [], "relationship_changes": [], "style_evidence": [],
    })


def valid_synthesis_result() -> str:
    return json.dumps({"mechanisms": [], "attraction_map": {}})


def _final_receipt_for_prompt(user: str, raw: str) -> str:
    """Let legacy test fixtures answer the production final receipt contract."""

    if "FINAL CHILD MANIFEST:\n" not in user:
        return raw
    try:
        semantic = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if isinstance(semantic, dict) and semantic.get("version") == 2:
        return raw
    manifest_text = user.split("FINAL CHILD MANIFEST:\n", 1)[1].split(
        "\n\nINDEPENDENT WINDOW CLAIMS:\n", 1,
    )[0]
    child_ids = json.loads(manifest_text)
    has_semantic = bool(
        isinstance(semantic, dict)
        and any(semantic.get(key) for key in (
            "mechanisms", "attraction_map", "style_profile",
        ))
    )
    dispositions = [{
        "child_id": child_id,
        "disposition": "promoted" if has_semantic else "no_transferable_claim",
        "reason": (
            "The child contributes to the retained aggregate semantic."
            if has_semantic else
            "The child contains no safely transferable aggregate semantic."
        ),
    } for child_id in child_ids]
    attributions = []
    if has_semantic:
        anchor_path = next(
            f"/{key}" for key in (
                "mechanisms", "attraction_map", "style_profile",
            ) if semantic.get(key)
        )
        attributions.append({
            "child_id": child_ids[0], "relation": "claim",
            "semantic_path": anchor_path, "related_child_ids": [],
        })
        attributions.extend({
            "child_id": child_id, "relation": "merged",
            "semantic_path": None, "related_child_ids": [child_ids[0]],
        } for child_id in child_ids[1:])
    return json.dumps({
        "version": 2,
        "covered_child_ids": child_ids,
        "child_dispositions": dispositions,
        "child_attributions": attributions,
        "semantic": semantic,
    }, ensure_ascii=False)


def test_synthesis_result_wraps_one_complete_mechanism_object() -> None:
    mechanism = {
        "name": "延迟揭示",
        "trigger_conditions": ["存在待解释线索"],
        "structural_position": "中段",
        "state_change": "人物获得新信息",
        "emotional_effect": "意外",
        "required_preparation": ["前置信息"],
        "downstream_consequence": "改变选择",
        "transfer_guidance": "只迁移结构",
        "incompatible_conditions": [],
        "supporting_windows": [1, 2],
        "confidence": 0.8,
    }

    result = LearningSystem._synthesis_result(mechanism)

    assert result == {"mechanisms": [mechanism], "attraction_map": {}, "style_profile": {}}


async def test_model_analysis_uses_fallback_for_wrong_window_shape(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)

    class GatewayWithFallback(FakeGateway):
        def __init__(self):
            super().__init__([
                '{"start":0,"end":10,"fact":"single claim"}',
                '{"start":0,"end":10,"fact":"single claim"}',
                valid_synthesis_result(),
            ])
            self.fallback_roles = []

        async def complete_configured_fallback(self, role, system, user, **kwargs):
            self.fallback_roles.append(role)
            return SimpleNamespace(text=valid_window_result(), receipt={"model_id": "fallback"})

    gateway = GatewayWithFallback()
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(title="wrong-window-shape", source_type="paste", text="sample text")

    result = await system.model_analyze_reference(source["id"])

    assert result["claims"] == 1
    assert gateway.fallback_roles == ["reference_analysis"]


async def test_model_analysis_uses_fallback_for_wrong_synthesis_shape(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)

    class GatewayWithFallback(FakeGateway):
        def __init__(self):
            super().__init__([
                valid_window_result(),
                '{"start":0,"fact":"not a synthesis"}',
            ])
            self.fallback_roles = []

        async def complete_configured_fallback(self, role, system, user, **kwargs):
            self.fallback_roles.append(role)
            return SimpleNamespace(
                text=_final_receipt_for_prompt(user, valid_synthesis_result()),
                receipt={"model_id": "fallback"},
            )

    gateway = GatewayWithFallback()
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(title="wrong-synthesis-shape", source_type="paste", text="sample text")

    result = await system.model_analyze_reference(source["id"])

    assert result["attraction_map"]["status"] == "proposed"
    assert gateway.fallback_roles == ["reference_synthesis"]


async def test_model_analysis_uses_fallback_when_mechanism_lacks_supporting_windows(
    tmp_path,
) -> None:
    db, library, projects, _system = setup_system(tmp_path)

    class GatewayWithFallback(FakeGateway):
        def __init__(self):
            super().__init__([
                valid_window_result(),
                json.dumps({
                    "mechanisms": [{
                        "name": "延迟揭示",
                        "transfer_guidance": "保留信息延迟出现的结构",
                    }],
                    "attraction_map": {},
                }, ensure_ascii=False),
            ])
            self.fallback_roles = []

        async def complete_configured_fallback(self, role, system, user, **kwargs):
            self.fallback_roles.append(role)
            return SimpleNamespace(
                text=_final_receipt_for_prompt(user, valid_synthesis_result()),
                receipt={"model_id": "fallback"},
            )

    gateway = GatewayWithFallback()
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(
        title="missing-supporting-windows", source_type="paste", text="sample text",
    )

    result = await system.model_analyze_reference(source["id"])

    assert result["attraction_map"]["status"] == "proposed"
    assert gateway.fallback_roles == ["reference_synthesis"]


async def test_model_analysis_retries_one_transient_invalid_synthesis_fallback(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)

    class GatewayWithTransientSynthesisFallback(FakeGateway):
        def __init__(self):
            super().__init__([valid_window_result(), ""])
            self.fallback_outputs = iter(["not-json", valid_synthesis_result()])
            self.fallback_roles = []

        async def complete_configured_fallback(self, role, system, user, **kwargs):
            self.fallback_roles.append(role)
            return SimpleNamespace(
                text=_final_receipt_for_prompt(user, next(self.fallback_outputs)),
                receipt={"model_id": "fallback"},
            )

    gateway = GatewayWithTransientSynthesisFallback()
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(
        title="transient-synthesis", source_type="paste", text="一段需要分析的正文。",
    )

    result = await system.model_analyze_reference(source["id"])

    assert result["attraction_map"]["status"] == "proposed"
    assert gateway.fallback_roles == ["reference_synthesis", "reference_synthesis"]


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
