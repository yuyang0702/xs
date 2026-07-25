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
