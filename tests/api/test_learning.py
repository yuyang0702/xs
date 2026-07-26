import time

from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
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


def test_local_nlp_status_is_read_only_until_install_clicked(tmp_path) -> None:
    client = client_for(tmp_path)
    status = client.get("/api/settings/local-nlp").json()
    assert status["backend"] == "ltp"
    assert status["operation"] == "idle"


def test_project_analysis_flag_is_reversible(tmp_path) -> None:
    client = client_for(tmp_path)
    project_id, _ = project_and_mechanism(client)
    initial = client.get(f"/api/projects/{project_id}/learning/workflow-analysis")
    assert initial.json() == {"enabled": False}
    enabled = client.put(
        f"/api/projects/{project_id}/learning/workflow-analysis",
        json={"enabled": True},
    )
    assert enabled.json() == {"enabled": True}
    assert client.get(f"/api/projects/{project_id}/learning/workflow-analysis").json()["enabled"] is True
    assert client.put(
        f"/api/projects/{project_id}/learning/workflow-analysis",
        json={"enabled": False},
    ).json() == {"enabled": False}


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


def test_model_analysis_exposes_queryable_progress(tmp_path) -> None:
    client = client_for(tmp_path)
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
