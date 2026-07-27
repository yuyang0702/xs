from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.reference_library import ReferenceLibrary
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


def test_wizard_confirm_rejects_invalid_market_baseline_key(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()
    response = client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "短篇", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一扇门。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
        "market_baseline_enabled": {"value": "enabled", "policy": "suggestible"},
        "market_baseline_key": {"value": "not-json", "policy": "suggestible"},
    }})
    assert response.status_code == 200

    confirmed = client.post(f"/api/wizards/{wizard['id']}/confirm")

    assert confirmed.status_code == 400
    assert confirmed.json()["detail"]["code"] == "invalid_market_baseline"


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


def test_wizard_lists_safe_confirmed_methods_and_adopts_only_selected_items(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
        reference_library=ReferenceLibrary(db, tmp_path / "references"),
    ))
    source = client.post("/api/references", json={
        "title": "可学习样本", "source_type": "paste", "text": "他推门后却发现真相。",
    }).json()
    mechanism = client.post(f"/api/references/{source['id']}/learn").json()["mechanisms"][0]
    client.post(
        f"/api/learning/nodes/{mechanism['id']}/revisions",
        json={"action": "confirm", "data": {}},
    )
    competitor = client.post("/api/references", json={
        "title": "竞品", "source_type": "paste", "text": "她转身后门外传来枪声。",
    }).json()
    client.patch(f"/api/references/{competitor['id']}/metadata", json={
        "platform": "知乎", "content_type": "competitor_work", "project_id": None,
    })
    competitor_node = client.post(
        f"/api/references/{competitor['id']}/learn",
    ).json()["mechanisms"][0]
    client.post(
        f"/api/learning/nodes/{competitor_node['id']}/revisions",
        json={"action": "confirm", "data": {}},
    )
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "选择写法", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一封来信。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})

    choices = client.get(f"/api/wizards/{wizard['id']}/confirmed-mechanisms")
    project = client.post(
        f"/api/wizards/{wizard['id']}/confirm",
        json={"selected_mechanism_ids": [mechanism["id"]]},
    )

    assert choices.status_code == 200
    assert [item["id"] for item in choices.json()] == [mechanism["id"]]
    assert len(choices.json()) <= 12
    assert project.status_code == 201
    learning = client.get(f"/api/projects/{project.json()['id']}/learning").json()
    assert [item["node_id"] for item in learning["adoptions"]] == [mechanism["id"]]


def test_wizard_does_not_adopt_confirmed_methods_without_explicit_selection(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
        reference_library=ReferenceLibrary(db, tmp_path / "references"),
    ))
    source = client.post("/api/references", json={
        "title": "样本", "source_type": "paste", "text": "他推门后却发现真相。",
    }).json()
    mechanism = client.post(f"/api/references/{source['id']}/learn").json()["mechanisms"][0]
    client.post(f"/api/learning/nodes/{mechanism['id']}/revisions", json={"action": "confirm", "data": {}})
    wizard = client.post("/api/wizards", json={"mode": "short"}).json()
    client.put(f"/api/wizards/{wizard['id']}/answers", json={"answers": {
        "title": {"value": "默认不选", "policy": "locked"},
        "genre": {"value": "悬疑", "policy": "locked"},
        "premise": {"value": "一扇门。", "policy": "locked"},
        "target_words": {"value": 8000, "policy": "suggestible"},
    }})

    project = client.post(f"/api/wizards/{wizard['id']}/confirm", json={})

    assert client.get(f"/api/projects/{project.json()['id']}/learning").json()["adoptions"] == []
