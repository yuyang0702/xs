import json
import hashlib

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


def test_short_run_waits_for_incomplete_initialization_materials(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", workflow_service=FakeWorkflows(),
    ))
    project = client.post("/api/projects", json={
        "title": "Short", "mode": "short", "genre": "suspense",
        "premise": "Someone vanishes.", "target_words": 5000,
    }).json()
    stored = client.app.state.projects.get(project["id"])
    metadata = json.loads((stored.path / "project.json").read_text(encoding="utf-8"))
    metadata["initialization_skills"] = ["character-management"]
    (stored.path / "project.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8",
    )
    confirm_outline(client, project["id"])

    response = client.post(f"/api/projects/{project['id']}/runs/short")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "initialization_required"
    assert "继续初始化" in response.json()["detail"]["message"]


def test_short_run_accepts_legacy_duplicate_manifest_after_materials_are_ready(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", workflow_service=FakeWorkflows(),
    ))
    project = client.post("/api/projects", json={
        "title": "Short", "mode": "short", "genre": "suspense",
        "premise": "Someone vanishes.", "target_words": 5000,
    }).json()
    confirm_outline(client, project["id"])
    stored = client.app.state.projects.get(project["id"])
    metadata = json.loads((stored.path / "project.json").read_text(encoding="utf-8"))
    metadata["initialization_skills"] = ["plot-structure"]
    (stored.path / "project.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8",
    )
    (stored.path / "plot" / "arcs" / "act-one.md").write_text(
        "---\nname: 第一幕：错入高门\n---\n# 第一幕：错入高门\n", encoding="utf-8",
    )
    (stored.path / "plot" / "_index.md").write_text(
        "# Plot\n\n[第一幕：错入高门](arcs/act-one.md)\n", encoding="utf-8",
    )
    (stored.path / "plot" / "timeline.md").write_text(
        "# Timeline\n\n| Time | Event |\n|---|---|\n| 第1章 | 错入高门 |\n", encoding="utf-8",
    )
    (stored.path / "continuity" / "questions" / "mistaken.md").write_text(
        "---\nname: 花穗为何被错认？\n---\n# 花穗为何被错认？\n", encoding="utf-8",
    )
    (stored.path / "continuity" / "questions" / "_index.md").write_text(
        "# Questions\n\n[花穗为何被错认？](mistaken.md)\n", encoding="utf-8",
    )
    current = client.app.state.outlines.current(project["id"])
    content = current["content"]
    cache = stored.path / "memory" / "outline-manifest.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({
        "outline_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "manifest": {
            "plot_arcs": [
                {"name": "第一幕：错入高门（约3000字）", "evidence": "同一幕"},
                {"name": "第一幕：错入高门", "evidence": "同一幕"},
            ],
            "questions": [
                {"name": "花穗被人带回沈府并错认成三小姐", "evidence": "同一问题"},
                {"name": "花穗为何被错认？", "evidence": "同一问题"},
            ],
        },
    }, ensure_ascii=False), encoding="utf-8")

    response = client.post(f"/api/projects/{project['id']}/runs/short")

    assert response.status_code == 202
    assert response.json()["workflow"] == "short-story"


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
    blocked = client.post(f"/api/projects/{project['id']}/runs/setup")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "outline_confirmation_required"
    confirm_outline(client, project["id"])
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


def test_resume_is_blocked_while_another_project_run_is_active(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    workspace = tmp_path / "workspace"
    db.save_project("book", "Book", "short", workspace / "book")
    db.create_run("failed-run", "book", "short-story", status="failed")
    client = TestClient(create_app(
        db, MemorySecretStore(), workflow_service=FakeWorkflows(),
        workspace_root=workspace,
    ))
    db.create_run("active-run", "book", "materials-audit", status="running")

    response = client.post("/api/runs/failed-run/resume")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "project_run_active"
    assert db.get_run("failed-run")["status"] == "failed"


def test_production_incident_endpoint_includes_history_and_known_catalog(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    client = TestClient(create_app(
        db, MemorySecretStore(), skill_roots=[tmp_path / "skills"],
        workspace_root=tmp_path / "workspace", workflow_service=FakeWorkflows(),
    ))
    project = client.post("/api/projects", json={
        "title": "Short", "mode": "short", "genre": "suspense",
        "premise": "Someone vanishes.", "target_words": 5000,
    }).json()
    db.create_run("legacy-failure", project["id"], "short-story", status="failed")
    db.add_run_event(
        "legacy-failure", "error", "failed",
        "正文事件、入口或出口缺少可核对原文证据",
        stage="draft",
    )

    response = client.get(f"/api/projects/{project['id']}/production-incidents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["incidents"][0]["incident_family"] == "draft.semantic_receipt_unsatisfied"
    assert any(
        item["incident_family"] == "planning.structure_drift"
        for item in payload["known_families"]
    )
