from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


def test_create_and_list_projects(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    ))
    response = client.post("/api/projects", json={
        "title": "Night Train", "mode": "short", "genre": "suspense",
        "premise": "A passenger disappears.", "target_words": 6000,
    })
    assert response.status_code == 201
    assert response.json()["mode"] == "short"
    assert client.get("/api/projects").json()[0]["title"] == "Night Train"
