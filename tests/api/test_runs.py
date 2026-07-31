import json

from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


class FakeWorkflows:
    async def run_short(self, project_id, run_id=None):
        return {"id": run_id, "project_id": project_id, "status": "completed", "workflow": "short-story"}

    async def run_long_setup(self, project_id, run_id=None):
        return {"id": run_id, "project_id": project_id, "status": "completed", "workflow": "long-setup"}

    async def run_chapter(self, project_id, chapter_goal, run_id=None):
        return {"id": run_id, "project_id": project_id, "status": "completed", "workflow": "long-chapter"}

    async def run_materials_audit(self, project_id, run_id=None):
        return {"id": run_id, "project_id": project_id, "status": "completed", "workflow": "materials-audit"}

    async def run_materials_repair(self, project_id, run_id=None):
        return {"id": run_id, "project_id": project_id, "status": "completed", "workflow": "materials-repair"}

    async def run_short_revision(self, project_id, issue_ids, run_id=None):
        return {
            "id": run_id, "project_id": project_id, "status": "waiting_confirmation",
            "workflow": "short-revision", "issue_ids": issue_ids,
        }


def confirm_outline(client: TestClient, project_id: str) -> None:
    candidate = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates",
        json={"title": "第一版", "outline": "# 正式大纲\n\n## 开头\n主角发现异常。"},
    ).json()
    comparison = client.get(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate['id']}/comparison",
    ).json()
    response = client.post(
        f"/api/projects/{project_id}/learning/outline-candidates/{candidate['id']}/apply",
        json={"expected_revision": comparison["state_revision"], "apply_whole": True},
    )
    assert response.status_code == 200


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
    blocked = client.post(f"/api/projects/{project['id']}/runs/short")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "outline_confirmation_required"

    confirm_outline(client, project["id"])
    response = client.post(f"/api/projects/{project['id']}/runs/short")
    assert response.status_code == 202
    assert response.json()["status"] in {"queued", "running"}


def test_resume_rejects_interrupted_short_story(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", workflow_service=FakeWorkflows(),
    ))
    project = client.post("/api/projects", json={
        "title": "Interrupted", "mode": "short", "genre": "suspense",
        "premise": "Someone vanishes.", "target_words": 5000,
    }).json()
    db.create_run(
        "interrupted-short", project["id"], "short-story", status="interrupted",
    )

    response = client.post("/api/runs/interrupted-short/resume")

    assert response.status_code == 409
    assert db.get_run("interrupted-short")["status"] == "interrupted"


def test_start_long_setup_and_chapter(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", workflow_service=FakeWorkflows(),
    ))
    project = client.post("/api/projects", json={
        "title": "Long", "mode": "long", "genre": "fantasy",
        "premise": "An oath survives.", "target_words": 500000,
    }).json()
    setup = client.post(f"/api/projects/{project['id']}/runs/setup")
    assert setup.status_code == 202
    assert setup.json()["workflow"] == "long-setup"
    response = client.post(
        f"/api/projects/{project['id']}/runs/chapter", json={"chapter_goal": "Reveal the old oath"},
    )
    assert response.status_code == 202
    assert response.json()["workflow"] == "long-chapter"


def test_start_material_audit_and_repair_runs(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        workspace_root=tmp_path / "workspace", workflow_service=FakeWorkflows(),
    ))
    project = client.post("/api/projects", json={
        "title": "Audit", "mode": "short", "genre": "test",
        "premise": "audit", "target_words": 1000,
    }).json()

    audit = client.post(f"/api/projects/{project['id']}/runs/materials-audit")
    assert audit.status_code == 202
    assert audit.json()["workflow"] == "materials-audit"


def test_start_material_audit_resumes_latest_interrupted_audit(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), workspace_root=tmp_path / "workspace",
        workflow_service=FakeWorkflows(),
    ))
    project = client.post("/api/projects", json={
        "title": "Resume audit", "mode": "short", "genre": "test",
        "premise": "audit", "target_words": 1000,
    }).json()
    db.create_run("interrupted-audit", project["id"], "materials-audit", status="cancelled")

    response = client.post(f"/api/projects/{project['id']}/runs/materials-audit")

    assert response.status_code == 202
    assert response.json()["id"] == "interrupted-audit"


def test_run_detail_includes_tool_receipts(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    workspace = tmp_path / "workspace"
    db.save_project("book", "Book", "long", workspace / "book")
    db.create_run("run", "book", "long-chapter", status="completed")
    db.save_tool_receipt(run_id="run", stage="review", model_id="model",
                         execution_mode="degraded_prompt_mode", fallback_reason="unsupported")
    client = TestClient(create_app(
        db, MemorySecretStore(), workflow_service=FakeWorkflows(),
        workspace_root=workspace,
    ))
    detail = client.get("/api/runs/run").json()
    assert detail["tool_receipts"][0]["execution_mode"] == "degraded_prompt_mode"
    assert detail["events"] == []


def test_run_detail_includes_quality_report_when_present(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    workspace = tmp_path / "workspace"
    project_path = workspace / "book"
    report_path = project_path / "runs" / "run" / "outputs" / "quality-report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({
        "status": "failed",
        "final_review_evidence": {"coverage": 1.0, "window_count": 4},
    }), encoding="utf-8")
    db.save_project("book", "Book", "short", project_path)
    db.create_run("run", "book", "short-story", status="failed")
    client = TestClient(create_app(
        db, MemorySecretStore(), workflow_service=FakeWorkflows(),
        workspace_root=workspace,
    ))

    detail = client.get("/api/runs/run").json()

    assert detail["quality_report"]["final_review_evidence"]["coverage"] == 1.0


def test_cancel_run_endpoint_is_idempotent(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    workspace = tmp_path / "workspace"
    db.save_project("book", "Book", "long", workspace / "book")
    db.create_run("run", "book", "long-chapter", status="completed")
    client = TestClient(create_app(
        db, MemorySecretStore(), workflow_service=FakeWorkflows(),
        workspace_root=workspace,
    ))

    response = client.post("/api/runs/run/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_resume_failed_short_run_keeps_original_run_id(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    workspace = tmp_path / "workspace"
    db.save_project("book", "Book", "short", workspace / "book")
    db.create_run("failed-run", "book", "short-story", status="failed")
    client = TestClient(create_app(
        db, MemorySecretStore(), workflow_service=FakeWorkflows(),
        workspace_root=workspace,
    ))

    response = client.post("/api/runs/failed-run/resume")

    assert response.status_code == 202
    assert response.json()["id"] == "failed-run"
