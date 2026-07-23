from fastapi.testclient import TestClient
from unittest.mock import Mock

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


class FakeStyleSamples:
    def __init__(self):
        self.value = {"configured": False, "source_characters": 0, "profile": None}

    def status(self, project):
        return {**self.value, "project_id": project.id}

    async def analyze(self, project, text, source_name):
        self.value = {
            "configured": True, "source_characters": len(text),
            "profile": {"summary": "克制的动作叙事", "source_name": source_name},
        }
        return self.status(project)

    def delete(self, project):
        self.value = {"configured": False, "source_characters": 0, "profile": None}
        return self.status(project)


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


def test_project_locations_resolve_formal_draft_candidate_and_latest_run(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Files", "mode": "short", "genre": "romance",
        "premise": "A relationship changes.", "target_words": 6000,
    }).json()
    root = tmp_path / "workspace" / f"files-{project['id'][:6]}"
    db.create_run("older", project["id"], "short-story", status="failed")
    older = root / "runs" / "older" / "outputs"
    older.mkdir(parents=True)
    (older / "best-candidate.md").write_text("best", encoding="utf-8")
    db.create_run("newest", project["id"], "short-story", status="failed")
    newest = root / "runs" / "newest" / "outputs"
    newest.mkdir(parents=True)
    (newest / "draft.md").write_text("draft", encoding="utf-8")

    response = client.get(f"/api/projects/{project['id']}/locations")

    assert response.status_code == 200
    locations = {item["kind"]: item for item in response.json()["locations"]}
    assert locations["project"]["exists"] is True
    assert locations["formal"]["exists"] is False
    assert locations["draft"]["path"].endswith(r"runs\newest\outputs\draft.md")
    assert locations["best_candidate"]["path"].endswith(
        r"runs\older\outputs\best-candidate.md"
    )
    assert locations["latest_run"]["path"].endswith(r"runs\newest")


def test_open_project_location_uses_server_resolved_path(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Open", "mode": "short", "genre": "romance",
        "premise": "A relationship changes.", "target_words": 6000,
    }).json()
    popen = Mock()
    monkeypatch.setattr("novel_flywheel.api.projects.platform.system", lambda: "Windows")
    monkeypatch.setattr("novel_flywheel.api.projects.subprocess.Popen", popen)

    response = client.post(f"/api/projects/{project['id']}/locations/project/open")

    assert response.status_code == 200
    command = popen.call_args.args[0]
    assert command[0] == "explorer.exe"
    assert command[1].endswith(f"open-{project['id'][:6]}")
    assert client.post(f"/api/projects/{project['id']}/locations/unknown/open").status_code == 404
    assert client.post(f"/api/projects/{project['id']}/locations/formal/open").status_code == 409


def test_candidate_diagnostics_and_controlled_publication(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Publish", "mode": "short", "genre": "romance",
        "premise": "A relationship changes.", "target_words": 6000,
    }).json()
    root = tmp_path / "workspace" / f"publish-{project['id'][:6]}"
    db.create_run("candidate-run", project["id"], "short-story", status="failed")
    output = root / "runs" / "candidate-run" / "outputs"
    output.mkdir(parents=True)
    (output / "best-candidate.md").write_text('他说："回来。"\n她关上门。', encoding="utf-8")

    diagnostics = client.get(f"/api/projects/{project['id']}/candidate")
    published = client.post(f"/api/projects/{project['id']}/candidate/publish")

    assert diagnostics.status_code == 200
    assert diagnostics.json()["available"] is True
    assert diagnostics.json()["run_id"] == "candidate-run"
    assert published.status_code == 201
    assert (root / "manuscript" / "story.md").read_text(encoding="utf-8") == "他说：“回来。”\n她关上门。"
    assert (root / "chapters" / "chapter-01.md").is_file()


def test_candidate_publication_rejects_process_text(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace",
    ))
    project = client.post("/api/projects", json={
        "title": "Unsafe", "mode": "short", "genre": "romance",
        "premise": "A relationship changes.", "target_words": 6000,
    }).json()
    root = tmp_path / "workspace" / f"unsafe-{project['id'][:6]}"
    db.create_run("bad-run", project["id"], "short-story", status="failed")
    output = root / "runs" / "bad-run" / "outputs"
    output.mkdir(parents=True)
    (output / "best-candidate.md").write_text("以下是本片段的润色版本：\n正文。", encoding="utf-8")

    response = client.post(f"/api/projects/{project['id']}/candidate/publish")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_blocked"


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


def test_project_style_sample_status_analyze_and_delete_api(tmp_path) -> None:
    service = FakeStyleSamples()
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
        style_sample_service=service,
    ))
    project = client.post("/api/projects", json={
        "title": "Voice", "mode": "short", "genre": "悬疑",
        "premise": "一封失踪的信。", "target_words": 6000,
    }).json()
    endpoint = f"/api/projects/{project['id']}/style-sample"

    assert client.get(endpoint).json()["configured"] is False
    analyzed = client.post(endpoint, json={"text": "动作与对白。" * 40, "source_name": "范文.txt"})
    assert analyzed.status_code == 201
    assert analyzed.json()["profile"]["summary"] == "克制的动作叙事"
    assert client.delete(endpoint).json()["configured"] is False


def test_project_style_sample_rejects_invalid_analysis(tmp_path) -> None:
    class InvalidStyleSamples(FakeStyleSamples):
        async def analyze(self, project, text, source_name):
            raise ValueError("范文至少需要 200 个字符")

    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
        style_sample_service=InvalidStyleSamples(),
    ))
    project = client.post("/api/projects", json={
        "title": "Voice", "mode": "short", "genre": "悬疑",
        "premise": "一封失踪的信。", "target_words": 6000,
    }).json()

    response = client.post(f"/api/projects/{project['id']}/style-sample", json={"text": "短"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_style_sample"
