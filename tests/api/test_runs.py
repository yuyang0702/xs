from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


class FakeWorkflows:
    async def run_short(self, project_id):
        return {"id": "run-1", "project_id": project_id, "status": "completed", "workflow": "short-story"}


def test_start_short_run_and_list_history(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", workflow_service=FakeWorkflows(),
    ))
    project = client.post("/api/projects", json={
        "title": "Short", "mode": "short", "genre": "suspense",
        "premise": "Someone vanishes.", "target_words": 5000,
    }).json()
    response = client.post(f"/api/projects/{project['id']}/runs/short")
    assert response.status_code == 201
    assert response.json()["status"] == "completed"
