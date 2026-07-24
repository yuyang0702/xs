from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


class FakeInterviews:
    def __init__(self):
        self.messages = []

    def history(self, wizard_id):
        return self.messages

    async def turn(self, wizard_id, message=None):
        result = {"id": "assistant", "wizard_id": wizard_id, "role": "assistant",
                  "content": "主角最害怕失去什么？", "suggestions": [],
                  "suggestion_status": "none"}
        self.messages.append(result)
        return result

    def apply(self, wizard_id, message_id, field_ids):
        return {"wizard": {"id": wizard_id}, "applied_fields": field_ids}


class FailingInterviews(FakeInterviews):
    async def turn(self, wizard_id, message=None):
        raise ConnectionError("planning provider disconnected")


def test_wizard_create_autosave_resume_and_confirm(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    wizard = client.post("/api/wizards", json={"mode": "long"}).json()
    response = client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "Web Book", "policy": "locked"},
        "genre": {"value": "fantasy", "policy": "locked"},
        "premise": {"value": "An oath.", "policy": "locked"},
        "target_words": {"value": 500000, "policy": "suggestible"},
    }})
    assert response.status_code == 200
    assert client.get(f"/api/wizards/{wizard['id']}").json()["answers"]["title"]["value"] == "Web Book"
    project = client.post(f"/api/wizards/{wizard['id']}/confirm").json()
    assert project["title"] == "Web Book"
    assert project["wizard_id"] == wizard["id"]


def test_wizard_rejects_unknown_answer_field(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()
    response = client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "filesystem_path": {"value": "../x", "policy": "locked"},
    }})
    assert response.status_code == 400


def test_initialize_skills_returns_tracked_background_run(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "Short", "policy": "locked"},
        "genre": {"value": "suspense", "policy": "suggestible"},
        "premise": {"value": "A door opens.", "policy": "locked"},
        "target_words": {"value": 5000, "policy": "suggestible"},
    }})
    project = client.post(f"/api/wizards/{wizard['id']}/confirm").json()

    response = client.post(f"/api/projects/{project['id']}/initialize-skills")

    assert response.status_code == 202
    assert response.json()["workflow"] == "initialize-skills"


def test_wizard_interview_history_turn_and_apply_routes(tmp_path) -> None:
    interviews = FakeInterviews()
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", interview_service=interviews,
    ))
    wizard = client.post("/api/wizards", json={"mode": "long"}).json()

    turn = client.post(f"/api/wizards/{wizard['id']}/interview", json={
        "message": "我不知道怎么设计人物弧光",
    })
    history = client.get(f"/api/wizards/{wizard['id']}/interview")
    applied = client.post(f"/api/wizards/{wizard['id']}/interview/assistant/apply", json={
        "field_ids": ["protagonist.arc"],
    })

    assert turn.status_code == 201
    assert turn.json()["content"] == "主角最害怕失去什么？"
    assert history.json()[0]["id"] == "assistant"
    assert applied.json()["applied_fields"] == ["protagonist.arc"]


def test_wizard_interview_returns_provider_connection_error(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", interview_service=FailingInterviews(),
    ))
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()

    response = client.post(f"/api/wizards/{wizard['id']}/interview", json={"message": "outline"})

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "interview_model_failed", "message": "planning provider disconnected",
    }
