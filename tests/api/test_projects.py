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


def test_manuscript_falls_back_to_latest_run_candidate(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Recovery", "mode": "short", "genre": "romance",
        "premise": "A relationship changes.", "target_words": 6000,
    }).json()
    db.create_run("failed-archive", project["id"], "short-story", status="failed")
    output = tmp_path / "workspace" / f"recovery-{project['id'][:6]}" / "runs" / "failed-archive" / "outputs"
    output.mkdir(parents=True)
    (output / "polish.md").write_text("# Recovered manuscript", encoding="utf-8")

    response = client.get(f"/api/projects/{project['id']}/manuscript")

    assert response.status_code == 200
    assert response.json() == {
        "project_id": project["id"],
        "content": "# Recovered manuscript",
        "source": "run_candidate",
        "run_id": "failed-archive",
    }


def test_project_trash_restore_and_permanent_delete_api(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Book", "mode": "long", "genre": "fantasy",
        "premise": "An oath.", "target_words": 100000,
    }).json()

    assert client.delete(f"/api/projects/{project['id']}").status_code == 200
    assert client.get("/api/projects").json() == []
    assert client.get("/api/projects/trash").json()[0]["id"] == project["id"]
    assert client.post(f"/api/projects/{project['id']}/restore").status_code == 200
    assert client.get("/api/projects").json()[0]["id"] == project["id"]

    client.delete(f"/api/projects/{project['id']}")
    response = client.delete(f"/api/projects/{project['id']}/permanent")
    assert response.status_code == 204
    assert client.get("/api/projects/trash").json() == []
