from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


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
