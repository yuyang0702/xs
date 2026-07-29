import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.learning import OutlineGenerationNotReady
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.secrets import MemorySecretStore


def client_for(tmp_path) -> TestClient:
    db = Database(tmp_path / "app.db")
    return TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "projects", reference_library=ReferenceLibrary(db, tmp_path / "references"),
    ))


def project_and_mechanism(client: TestClient) -> tuple[str, str]:
    project = client.post("/api/projects", json={
        "title": "接口书", "mode": "short", "genre": "悬疑", "premise": "测试",
        "target_words": 10_000, "pov": "third-limited", "tone": "natural",
        "must_include": "", "must_avoid": "",
    }).json()
    source = client.post("/api/references", json={
        "title": "样本", "source_type": "paste", "text": "他推门后却发现真相。",
    }).json()
    learned = client.post(f"/api/references/{source['id']}/learn").json()
    return project["id"], learned["mechanisms"][0]["id"]


def test_learning_api_confirmation_artifacts_and_candidate_guards(tmp_path) -> None:
    client = client_for(tmp_path)
    project_id, node_id = project_and_mechanism(client)

    assert client.get(f"/api/projects/{project_id}/learning/recommend/{node_id}").json()["status"] == "proposed"
    assert client.get(f"/api/projects/{project_id}/learning").json()["adoptions"] == []
    blocked = client.post(
        f"/api/projects/{project_id}/learning/adoptions/{node_id}", json={"edits": {}},
    )
    assert blocked.status_code == 422
    assert "确认" in blocked.json()["detail"]
    assert client.post(
        f"/api/learning/nodes/{node_id}/revisions", json={"action": "confirm", "data": {}},
    ).status_code == 200
    adopted = client.post(
        f"/api/projects/{project_id}/learning/adoptions/{node_id}", json={"edits": {"position": "中段"}},
    )
    assert adopted.status_code == 201
    assert client.put(f"/api/projects/{project_id}/learning/prose-baseline", json={
        "data": {"dialogue": "回应改变信息"},
    }).status_code == 200
    assert client.post(f"/api/projects/{project_id}/learning/scene-briefs", json={
        "outline": "## 第一幕\n\n## 第二幕",
    }).json()["data"]["briefs"][0]["id"] == "scene-01"
    candidate = client.post(f"/api/projects/{project_id}/learning/line-edits", json={
        "source": "事实甲。她很确定。", "candidate": "事实甲。她从门锁判断来人刚走。",
        "issues": ["unsupported_certainty"], "locked_facts": ["事实甲"],
    })
    assert candidate.status_code == 201
    assert candidate.json()["status"] == "pending"


def test_learning_api_explains_local_analysis_source(tmp_path) -> None:
    client = client_for(tmp_path)
    _project_id, node_id = project_and_mechanism(client)

    item = next(value for value in client.get("/api/learning/mechanisms").json() if value["id"] == node_id)

    assert item["analysis"]["state"] == "local_only"
    assert item["analysis"]["source_title"] == "样本"
    assert item["analysis"]["model"] is None


def test_local_nlp_status_is_read_only_until_install_clicked(tmp_path) -> None:
    client = client_for(tmp_path)
    status = client.get("/api/settings/local-nlp").json()
    assert status["backend"] == "ltp"
    assert status["operation"] == "idle"


def test_project_workflow_analysis_flag_is_reversible_across_restart(
    tmp_path,
) -> None:
    client = client_for(tmp_path)
    project_id, _ = project_and_mechanism(client)
    initial = client.get(f"/api/projects/{project_id}/learning/workflow-analysis")
    assert initial.json() == {"enabled": True}
    disabled = client.put(
        f"/api/projects/{project_id}/learning/workflow-analysis",
        json={"enabled": False},
    )
    assert disabled.json() == {"enabled": False}
    client.close()

    restarted = client_for(tmp_path)
    assert restarted.get(
        f"/api/projects/{project_id}/learning/workflow-analysis",
    ).json() == {"enabled": False}
    enabled = restarted.put(
        f"/api/projects/{project_id}/learning/workflow-analysis",
        json={"enabled": True},
    )
    assert enabled.json() == {"enabled": True}
    restarted.close()

    restored = client_for(tmp_path)
    assert restored.get(
        f"/api/projects/{project_id}/learning/workflow-analysis",
    ).json() == {"enabled": True}


def test_rejected_mechanisms_are_hidden_by_default_and_remain_reviewable(tmp_path) -> None:
    client = client_for(tmp_path)
    _project_id, node_id = project_and_mechanism(client)

    rejected = client.post(
        f"/api/learning/nodes/{node_id}/revisions",
        json={"action": "reject", "data": {}},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert node_id not in {item["id"] for item in client.get("/api/learning/mechanisms").json()}
    rejected_list = client.get("/api/learning/mechanisms?view=rejected").json()
    assert [item["id"] for item in rejected_list] == [node_id]


def test_rejected_mechanisms_can_be_deleted_from_api(tmp_path) -> None:
    client = client_for(tmp_path)
    _project_id, node_id = project_and_mechanism(client)
    client.post(
        f"/api/learning/nodes/{node_id}/revisions",
        json={"action": "reject", "data": {}},
    )

    response = client.request(
        "DELETE", "/api/learning/mechanisms",
        json={"node_ids": [node_id]},
    )

    assert response.status_code == 200
    assert response.json() == {"deleted_ids": [node_id], "skipped": []}
    assert client.get("/api/learning/mechanisms?view=rejected").json() == []


def test_historical_rejected_adoption_does_not_block_mechanism_deletion(tmp_path) -> None:
    client = client_for(tmp_path)
    project_id, node_id = project_and_mechanism(client)
    rejected_adoption = client.post(
        f"/api/projects/{project_id}/learning/rejections/{node_id}",
        json={"reason": "not suitable"},
    )
    assert rejected_adoption.status_code == 200
    client.post(
        f"/api/learning/nodes/{node_id}/revisions",
        json={"action": "reject", "data": {}},
    )

    rejected = client.get("/api/learning/mechanisms?view=rejected").json()
    response = client.request("DELETE", "/api/learning/mechanisms", json={"node_ids": [node_id]})

    assert rejected[0]["deletable"] is True
    assert rejected[0]["delete_reason"] == ""
    assert response.json() == {"deleted_ids": [node_id], "skipped": []}


def test_rejecting_an_active_adoption_removes_it_from_the_creative_blueprint(tmp_path) -> None:
    client = client_for(tmp_path)
    project_id, node_id = project_and_mechanism(client)
    client.post(f"/api/learning/nodes/{node_id}/revisions", json={"action": "confirm", "data": {}})
    client.post(f"/api/projects/{project_id}/learning/adoptions/{node_id}", json={"edits": {}})

    response = client.post(
        f"/api/projects/{project_id}/learning/rejections/{node_id}",
        json={"reason": "user removed rejected mechanism"},
    )
    learning = client.get(f"/api/projects/{project_id}/learning").json()
    blueprint = next(item for item in learning["artifacts"] if item["artifact_type"] == "creative_blueprint")

    assert response.status_code == 200
    assert learning["adoptions"] == []
    assert blueprint["data"]["mechanisms"] == []


def test_active_adoption_explains_why_rejected_mechanism_cannot_be_deleted(tmp_path) -> None:
    client = client_for(tmp_path)
    project_id, node_id = project_and_mechanism(client)
    client.post(f"/api/learning/nodes/{node_id}/revisions", json={"action": "confirm", "data": {}})
    client.post(f"/api/projects/{project_id}/learning/adoptions/{node_id}", json={"edits": {}})
    client.post(f"/api/learning/nodes/{node_id}/revisions", json={"action": "reject", "data": {}})

    rejected = client.get("/api/learning/mechanisms?view=rejected").json()
    response = client.request("DELETE", "/api/learning/mechanisms", json={"node_ids": [node_id]})

    assert rejected[0]["deletable"] is False
    assert rejected[0]["delete_reason"] == "仍在作品中使用，取消应用后才能删除"
    assert rejected[0]["active_project_ids"] == [project_id]
    assert response.json() == {
        "deleted_ids": [],
        "skipped": [{"id": node_id, "reason": "仍在作品中使用，取消应用后才能删除"}],
    }


def test_model_analysis_exposes_queryable_progress(tmp_path) -> None:
    client = client_for(tmp_path)
    for role in ("reference_analysis", "reference_synthesis"):
        provider = client.post("/api/providers", json={
            "name": f"{role}-provider", "protocol": "openai-chat",
            "base_url": "https://example.com/v1", "api_key": "test-key",
        }).json()
        model = client.post(f"/api/providers/{provider['id']}/models", json={
            "display_name": role, "model_name": role,
        }).json()
        client.put(f"/api/role-bindings/{role}", json={
            "primary_provider_id": provider["id"], "primary_model_id": model["id"],
        })
    source = client.post("/api/references", json={
        "title": "progress", "source_type": "paste", "text": "sample text",
    }).json()

    async def fake_analysis(source_id, progress):
        progress({"phase": "analyzing_windows", "completed_windows": 0, "total_windows": 2})
        progress({"phase": "analyzing_windows", "completed_windows": 1, "total_windows": 2})
        progress({"phase": "synthesizing", "completed_windows": 2, "total_windows": 2})
        return {"source_id": source_id, "claims": 2, "mechanisms": [{"id": "mechanism-1"}]}

    client.app.state.learning.model_analyze_reference = fake_analysis
    with client:
        started = client.post(f"/api/references/{source['id']}/model-learn")
        assert started.status_code == 202
        assert started.json()["status"] in {"queued", "running"}
        for _ in range(50):
            status = client.get(f"/api/references/{source['id']}/model-learn/status").json()
            if status["status"] == "completed":
                break
            time.sleep(0.01)

    assert status["status"] == "completed"
    assert status["phase"] == "completed"
    assert status["completed_windows"] == status["total_windows"] == 2
    assert status["result"]["mechanisms"][0]["id"] == "mechanism-1"


def test_model_analysis_reports_missing_role_api_key_before_starting(tmp_path) -> None:
    client = client_for(tmp_path)
    registry = client.app.state.registry
    provider_id = "provider-without-key"
    model_id = "model-without-key"
    registry.db.save_provider(
        provider_id=provider_id, name="deepseek", protocol="openai-chat",
        base_url="https://example.com/v1", auth_type="bearer", timeout_seconds=30,
        extra_headers={},
    )
    registry.db.save_model(
        model_id=model_id, provider_id=provider_id, display_name="analysis",
        model_name="analysis", capabilities={},
    )
    for role in ("reference_analysis", "reference_synthesis"):
        registry.db.save_role_binding(
            role, primary_provider_id=provider_id, primary_model_id=model_id,
            fallback_provider_id=None, fallback_model_id=None,
        )
    source = client.post("/api/references", json={
        "title": "missing key", "source_type": "paste", "text": "sample text",
    }).json()

    response = client.post(f"/api/references/{source['id']}/model-learn")

    assert response.status_code == 422
    assert response.json()["detail"] == "参考资料分窗分析使用的 deepseek 缺少 API Key，请先到“模型与 API”补充密钥"
    status = client.get(f"/api/references/{source['id']}/model-learn/status").json()
    assert status["status"] == "idle"


def test_reference_attraction_map_is_queryable(tmp_path) -> None:
    client = client_for(tmp_path)
    source = client.post("/api/references", json={
        "title": "map", "source_type": "paste", "text": "她把钥匙递给仇人。",
    }).json()
    node = client.app.state.learning._save_node(
        "attraction_map", {
            "fit": {"level": "partial", "explanation": "只有开头"},
            "opening": {"mechanism": "pressure_anomaly"}, "uncertainties": ["结尾尚未出现"],
        }, source_id=source["id"], status="proposed",
    )

    response = client.get(f"/api/references/{source['id']}/attraction-map")

    assert response.status_code == 200
    assert response.json()["id"] == node["id"]
    assert response.json()["data"]["uncertainties"] == ["结尾尚未出现"]


def test_effective_rules_and_artifact_restore_are_available(tmp_path) -> None:
    client = client_for(tmp_path)
    project_id, _node_id = project_and_mechanism(client)
    first = client.put(
        f"/api/projects/{project_id}/learning/prose-baseline",
        json={"data": {"dialogue": ["回应需要改变关系"]}},
    )
    second = client.put(
        f"/api/projects/{project_id}/learning/prose-baseline",
        json={"data": {"dialogue": ["对白保持简短"]}},
    )
    assert first.status_code == second.status_code == 200

    history = client.get(
        f"/api/projects/{project_id}/learning/artifacts/prose_baseline/history",
    )
    restored = client.post(
        f"/api/projects/{project_id}/learning/artifacts/prose_baseline/restore",
        json={"version": 1},
    )
    overview = client.get(f"/api/projects/{project_id}/learning/effective-rules")

    assert [item["version"] for item in history.json()] == [2, 1]
    assert restored.status_code == 200
    assert restored.json()["version"] == 3
    assert overview.status_code == 200
    assert any(item["name"] == "基础文笔规则" for item in overview.json()["layers"])


def test_learning_api_normalizes_legacy_single_incompatible_condition(tmp_path) -> None:
    client = client_for(tmp_path)
    source = client.post("/api/references", json={
        "title": "旧数据", "source_type": "paste", "text": "他推开门。",
    }).json()
    node = client.app.state.learning._save_node(
        "mechanism", {
            "name": "旧写法", "confidence": 0.9,
            "incompatible_conditions": "主角没有选择时不要使用",
        }, source_id=source["id"], status="confirmed",
    )

    response = client.get("/api/learning/mechanisms")
    returned = next(item for item in response.json() if item["id"] == node["id"])

    assert returned["data"]["incompatible_conditions"] == ["主角没有选择时不要使用"]


def test_outline_candidates_can_be_viewed_compared_edited_applied_and_restored(tmp_path) -> None:
    client = client_for(tmp_path)
    project_id, _node_id = project_and_mechanism(client)

    created = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates",
        json={"outline": "# 初版\n\n## 开头\n旧开头。\n\n## 结尾\n旧结尾。", "title": "初版大纲"},
    )
    assert created.status_code == 201
    candidate_id = created.json()["id"]
    overview = client.get(f"/api/projects/{project_id}/learning/outlines")
    assert overview.status_code == 200
    assert overview.json()["candidates"][0]["content"].startswith("# 初版")

    edited = client.put(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate_id}",
        json={"outline": "# 初版\n\n## 开头\n新的开头。\n\n## 结尾\n旧结尾。", "title": "调整开头"},
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "调整开头"

    class MustNotRun:
        async def complete(self, *args, **kwargs):
            raise AssertionError("本地比较不应调用模型")

    client.app.state.outlines.gateway = MustNotRun()
    comparison = client.get(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate_id}/comparison",
    )
    assert comparison.status_code == 200
    assert comparison.json()["model_called"] is False

    applied = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate_id}/apply",
        json={"expected_revision": comparison.json()["state_revision"], "apply_whole": True},
    )
    assert applied.status_code == 200
    assert applied.json()["outline_version"] == 1
    assert applied.json()["formal_manuscript_changed"] is False

    replacement = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates",
        json={"outline": "# 第二版\n\n## 开头\n第二版开头。", "title": "第二版"},
    ).json()
    revision = client.get(
        f"/api/projects/{project_id}/learning/outline-candidates/{replacement['id']}/comparison",
    ).json()["state_revision"]
    client.post(
        f"/api/projects/{project_id}/learning/outline-candidates/{replacement['id']}/apply",
        json={"expected_revision": revision, "apply_whole": True},
    )
    restored = client.post(
        f"/api/projects/{project_id}/learning/outlines/restore",
        json={"outline_version": 1},
    )
    assert restored.status_code == 200
    assert restored.json()["outline_version"] == 3
    assert "新的开头" in restored.json()["content"]

    abandoned = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates",
        json={"outline": "# 不采用", "title": "不采用"},
    ).json()
    deleted = client.delete(
        f"/api/projects/{project_id}/learning/outline-candidates/{abandoned['id']}",
    )
    assert deleted.status_code == 200
    remaining = client.get(f"/api/projects/{project_id}/learning/outlines").json()["candidates"]
    assert abandoned["id"] not in {item["id"] for item in remaining}


def test_outline_semantic_review_sends_only_uncertain_changes_to_planning_model(tmp_path) -> None:
    client = client_for(tmp_path)
    project_id, _node_id = project_and_mechanism(client)
    first = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates",
        json={"outline": "# 大纲\n\n## 开头\n主角收到求救信。", "title": "初版"},
    ).json()
    client.post(
        f"/api/projects/{project_id}/learning/outline-candidates/{first['id']}/apply",
        json={"apply_whole": True},
    )
    candidate = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates",
        json={"outline": "# 大纲\n\n## 开头\n十年后，陌生法医带着一截断指登门。", "title": "大改版"},
    ).json()

    class RecordingGateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append((role, system, user, max_output_tokens))
            report = client.get(
                f"/api/projects/{project_id}/learning/outline-candidates/{candidate['id']}/comparison",
            ).json()
            uncertain_id = next(item["id"] for item in report["changes"] if item["type"] == "uncertain")
            return SimpleNamespace(
                text=("{\"decisions\":[{\"id\":\"" + uncertain_id
                      + "\",\"type\":\"changed\",\"explanation\":\"仍是开头，但冲突更强。\","
                        "\"impact\":\"会改变主角接到任务的原因。\"}]}"),
                receipt={"role": role},
            )

    gateway = RecordingGateway()
    client.app.state.outlines.gateway = gateway
    response = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate['id']}/semantic-review",
    )

    assert response.status_code == 200
    assert response.json()["model_called"] is True
    assert response.json()["summary"]["uncertain"] == 0
    assert gateway.calls[0][0] == "planning"
    assert gateway.calls[0][3] == 2048
    assert '"type": "uncertain"' in gateway.calls[0][2]
    assert len(gateway.calls[0][2]) <= 30_000


def test_outline_generation_prompt_uses_only_confirmed_abstract_allowlist(tmp_path) -> None:
    client = client_for(tmp_path)
    project = client.post("/api/projects", json={
        "title": "允许的标题", "mode": "short", "genre": "允许的题材",
        "premise": "允许的前提", "target_words": 12_345,
        "pov": "允许的视角", "tone": "允许的语气",
        "must_include": "允许的必须包含", "must_avoid": "允许的必须避开",
    }).json()
    project_id = project["id"]
    stored_project = client.app.state.projects.get(project_id)
    project_metadata = {
        **stored_project.metadata,
        "private_metadata": "FORBIDDEN_PROJECT_METADATA",
        "creative_blueprint": "FORBIDDEN_PROJECT_BLUEPRINT_COPY",
    }
    (stored_project.path / "project.json").write_text(
        json.dumps(project_metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    source = client.post("/api/references", json={
        "title": "FORBIDDEN_SOURCE_TITLE",
        "source_type": "paste",
        "text": "FORBIDDEN_SOURCE_PROSE",
    }).json()
    learning = client.app.state.learning
    confirmed = learning._save_node(
        "mechanism",
        {
            "name": "允许的抽象写法",
            "transfer_guidance": "允许的迁移规则",
            "confidence": 0.9,
            "source_title": "FORBIDDEN_SOURCE_TITLE_FIELD",
            "source_path": "FORBIDDEN_SOURCE_PATH",
            "evidence": "FORBIDDEN_EVIDENCE",
            "fact": "FORBIDDEN_FACT",
            "interpretation": "FORBIDDEN_INTERPRETATION",
            "model_review": "FORBIDDEN_MODEL_REVIEW",
            "receipt": "FORBIDDEN_RECEIPT",
            "supporting_windows": "FORBIDDEN_SUPPORTING_WINDOWS",
            "character_name": "FORBIDDEN_CHARACTER_NAME",
            "setting": "FORBIDDEN_SETTING",
            "plot": "FORBIDDEN_CONCRETE_PLOT",
            "unique_expression": "FORBIDDEN_UNIQUE_EXPRESSION",
        },
        source_id=source["id"],
        status="confirmed",
    )
    unadopted = learning._save_node(
        "mechanism",
        {
            "name": "FORBIDDEN_UNADOPTED_NAME",
            "transfer_guidance": "FORBIDDEN_UNADOPTED_GUIDANCE",
            "confidence": 0.9,
        },
        source_id=source["id"],
        status="confirmed",
    )
    attraction = learning._save_node(
        "attraction_map",
        {
            "confidence": 0.9,
            "fit": {"level": "strong", "explanation": "FORBIDDEN_ATTRACTION_REVIEW"},
            "opening": {
                "mechanism": "FORBIDDEN_ATTRACTION_PACKAGING",
                "transfer_guidance": "允许的开场规则",
                "evidence": "FORBIDDEN_ATTRACTION_EVIDENCE",
            },
            "cycles": [{
                "transfer_guidance": "允许的循环规则",
                "fact": "FORBIDDEN_ATTRACTION_FACT",
            }],
            "question_chain": [{"transfer_guidance": "允许的悬念规则"}],
            "relationship_arc": [{"transfer_guidance": "允许的关系规则"}],
            "reversal": {"transfer_guidance": "允许的反转规则"},
            "ending": {"transfer_guidance": "允许的收束规则"},
        },
        source_id=source["id"],
        status="confirmed",
    )
    for node in (confirmed, attraction):
        adopted = client.post(
            f"/api/projects/{project_id}/learning/adoptions/{node['id']}",
            json={"edits": {}},
        )
        assert adopted.status_code == 201
    assert client.post(
        f"/api/learning/nodes/{confirmed['id']}/revisions",
        json={"action": "reject", "data": {}},
    ).status_code == 200
    blueprint = learning.get_artifact(project_id, "creative_blueprint")
    learning.save_artifact(project_id, "creative_blueprint", {
        **blueprint["data"],
        "private_blueprint_data": "FORBIDDEN_CREATIVE_BLUEPRINT",
    })

    class RecordingGateway:
        def __init__(self):
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append((role, system, user, max_output_tokens))
            return SimpleNamespace(
                text="# 全新原创大纲\n\n## 开头\n一封没有署名的信抵达。",
                receipt={"private": "FORBIDDEN_RESPONSE_RECEIPT"},
            )

    gateway = RecordingGateway()
    client.app.state.learning.gateway = gateway
    response = client.post(
        f"/api/projects/{project_id}/learning/generate-outline",
        json={"brief": "允许的用户补充"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert len(gateway.calls) == 1
    assert gateway.calls[0][0] == "planning"
    assert gateway.calls[0][3] == 8192
    assert json.loads(gateway.calls[0][2]) == {
        "project_brief": {
            "title": "允许的标题",
            "mode": "short",
            "genre": "允许的题材",
            "premise": "允许的前提",
            "target_words": 12_345,
            "pov": "允许的视角",
            "tone": "允许的语气",
            "must_include": "允许的必须包含",
            "must_avoid": "允许的必须避开",
        },
        "writing_methods": [{
            "name": "允许的抽象写法",
            "transfer_guidance": "允许的迁移规则",
        }],
        "attraction_rules": [
            "允许的开场规则",
            "允许的循环规则",
            "允许的悬念规则",
            "允许的关系规则",
            "允许的反转规则",
            "允许的收束规则",
        ],
        "user_brief": "允许的用户补充",
    }
    sent = "\n".join(str(part) for part in gateway.calls[0])
    forbidden = {
        "FORBIDDEN_PROJECT_METADATA",
        "FORBIDDEN_PROJECT_BLUEPRINT_COPY",
        "FORBIDDEN_SOURCE_TITLE",
        "FORBIDDEN_SOURCE_PROSE",
        "FORBIDDEN_SOURCE_TITLE_FIELD",
        "FORBIDDEN_SOURCE_PATH",
        "FORBIDDEN_EVIDENCE",
        "FORBIDDEN_FACT",
        "FORBIDDEN_INTERPRETATION",
        "FORBIDDEN_MODEL_REVIEW",
        "FORBIDDEN_RECEIPT",
        "FORBIDDEN_SUPPORTING_WINDOWS",
        "FORBIDDEN_CHARACTER_NAME",
        "FORBIDDEN_SETTING",
        "FORBIDDEN_CONCRETE_PLOT",
        "FORBIDDEN_UNIQUE_EXPRESSION",
        "FORBIDDEN_UNADOPTED_NAME",
        "FORBIDDEN_UNADOPTED_GUIDANCE",
        "FORBIDDEN_ATTRACTION_REVIEW",
        "FORBIDDEN_ATTRACTION_PACKAGING",
        "FORBIDDEN_ATTRACTION_EVIDENCE",
        "FORBIDDEN_ATTRACTION_FACT",
        "FORBIDDEN_CREATIVE_BLUEPRINT",
        "FORBIDDEN_RESPONSE_RECEIPT",
        source["id"],
        client.app.state.references.get(source["id"])["latest_version"]["storage_path"],
        confirmed["id"],
        unadopted["id"],
        attraction["id"],
    }
    assert not [marker for marker in forbidden if marker in sent]


def test_outline_generation_failure_is_recoverable_without_mutating_project_state(tmp_path) -> None:
    client = client_for(tmp_path)
    project_id, node_id = project_and_mechanism(client)
    client.post(
        f"/api/learning/nodes/{node_id}/revisions",
        json={"action": "confirm", "data": {}},
    )
    client.post(
        f"/api/projects/{project_id}/learning/adoptions/{node_id}",
        json={"edits": {}},
    )
    formal_candidate = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates",
        json={"title": "正式版", "outline": "# 正式大纲\n\n## 开头\n原有开头。"},
    ).json()
    client.post(
        f"/api/projects/{project_id}/learning/outline-candidates/{formal_candidate['id']}/apply",
        json={"apply_whole": True},
    )
    learning = client.app.state.learning
    snapshots = {
        "project": client.get(f"/api/projects/{project_id}").json(),
        "adoptions": learning.list_adoptions(project_id),
        "blueprint": learning.get_artifact(project_id, "creative_blueprint"),
        "outline": client.app.state.outlines.current(project_id),
    }
    assert client.app.state.outlines.list_candidates(project_id) == []

    class FailingGateway:
        def __init__(self, error):
            self.error = error

        async def complete(self, *args, **kwargs):
            raise self.error

    for error in (
        RuntimeError("PROVIDER_PRIVATE_RUNTIME_FAILURE"),
        ConnectionError("PROVIDER_PRIVATE_CONNECTION_FAILURE"),
        LookupError("PROVIDER_PRIVATE_LOOKUP_FAILURE"),
        OutlineGenerationNotReady("SECRET_GATEWAY_NOT_READY"),
    ):
        client.app.state.learning.gateway = FailingGateway(error)
        failed = client.post(
            f"/api/projects/{project_id}/learning/generate-outline",
            json={"brief": "沿用同一入口"},
        )

        assert failed.status_code == 502
        assert failed.json()["detail"] == {
            "code": "outline_generation_failed",
            "message": "大纲生成失败，作品已经创建，可以稍后重试。",
        }
        assert "PROVIDER_PRIVATE" not in failed.text
        assert "SECRET_GATEWAY_NOT_READY" not in failed.text
        assert client.get(f"/api/projects/{project_id}").json() == snapshots["project"]
        assert learning.list_adoptions(project_id) == snapshots["adoptions"]
        assert learning.get_artifact(project_id, "creative_blueprint") == snapshots["blueprint"]
        assert client.app.state.outlines.current(project_id) == snapshots["outline"]
        assert client.app.state.outlines.list_candidates(project_id) == []

    class SuccessfulGateway:
        async def complete(self, *args, **kwargs):
            return SimpleNamespace(
                text="# 重试候选\n\n## 开头\n新的危机出现。",
                receipt={"role": "planning"},
            )

    client.app.state.learning.gateway = SuccessfulGateway()
    retried = client.post(
        f"/api/projects/{project_id}/learning/generate-outline",
        json={"brief": "沿用同一入口"},
    )

    assert retried.status_code == 201
    assert retried.json()["status"] == "pending"
    assert retried.json()["content"].startswith("# 重试候选")
    assert [item["id"] for item in client.app.state.outlines.list_candidates(project_id)] == [
        retried.json()["id"],
    ]
    assert client.app.state.outlines.current(project_id) == snapshots["outline"]
    assert client.get(f"/api/projects/{project_id}").json() == snapshots["project"]
    assert learning.list_adoptions(project_id) == snapshots["adoptions"]
    assert learning.get_artifact(project_id, "creative_blueprint") == snapshots["blueprint"]


def test_outline_generation_not_ready_errors_are_fixed_chinese(tmp_path) -> None:
    client = client_for(tmp_path)
    project_id, node_id = project_and_mechanism(client)

    no_adoption = client.post(
        f"/api/projects/{project_id}/learning/generate-outline",
        json={"brief": ""},
    )

    assert no_adoption.status_code == 422
    assert no_adoption.json()["detail"] == {
        "code": "outline_generation_not_ready",
        "message": "请先确认并采用至少一条写法，再生成大纲。",
    }

    client.post(
        f"/api/learning/nodes/{node_id}/revisions",
        json={"action": "confirm", "data": {}},
    )
    client.post(
        f"/api/projects/{project_id}/learning/adoptions/{node_id}",
        json={"edits": {}},
    )
    client.app.state.learning.gateway = None
    no_model = client.post(
        f"/api/projects/{project_id}/learning/generate-outline",
        json={"brief": ""},
    )

    assert no_model.status_code == 422
    assert no_model.json()["detail"] == {
        "code": "outline_generation_not_ready",
        "message": "规划模型当前不可用，请先检查模型配置。",
    }
