from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


class FakeWorkflows:
    async def run_short(self, project_id):
        return {"id": "run-1", "project_id": project_id, "status": "completed", "workflow": "short-story"}

    async def run_long_setup(self, project_id):
        return {"id": "run-2", "project_id": project_id, "status": "completed", "workflow": "long-setup"}

    async def run_chapter(self, project_id, chapter_goal):
        return {"id": "run-3", "project_id": project_id, "status": "completed", "workflow": "long-chapter"}


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


def test_start_long_setup_and_chapter(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", workflow_service=FakeWorkflows(),
    ))
    project = client.post("/api/projects", json={
        "title": "Long", "mode": "long", "genre": "fantasy",
        "premise": "An oath survives.", "target_words": 500000,
    }).json()
    assert client.post(f"/api/projects/{project['id']}/runs/setup").json()["workflow"] == "long-setup"
    response = client.post(
        f"/api/projects/{project['id']}/runs/chapter", json={"chapter_goal": "Reveal the old oath"},
    )
    assert response.json()["workflow"] == "long-chapter"


def test_run_detail_includes_tool_receipts(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("book", "Book", "long", tmp_path / "book")
    db.create_run("run", "book", "long-chapter")
    db.save_tool_receipt(run_id="run", stage="review", model_id="model",
                         execution_mode="degraded_prompt_mode", fallback_reason="unsupported")
    client = TestClient(create_app(db, MemorySecretStore(), workflow_service=FakeWorkflows()))
    detail = client.get("/api/runs/run").json()
    assert detail["tool_receipts"][0]["execution_mode"] == "degraded_prompt_mode"
