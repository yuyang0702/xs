from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.launcher import data_dir_fingerprint, runtime_fingerprint
from novel_flywheel.secrets import MemorySecretStore
from novel_flywheel.tasks import RunTaskManager


def test_health(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    response = client.get("/api/health")

    assert response.json() == {
        "status": "ok",
        "service": "novel-flywheel-console",
        "data_dir_fingerprint": data_dir_fingerprint(tmp_path),
        "runtime_fingerprint": runtime_fingerprint(),
    }
    assert str(tmp_path) not in response.text


def test_revision_routes_are_registered(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))

    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/projects/{project_id}/revisions" in paths
    assert "/api/runs/{run_id}/revision" in paths
    assert "/api/runs/{run_id}/short-receipt-resume" in paths


def test_lifespan_owns_durable_recovery_once_per_app(tmp_path, monkeypatch) -> None:
    app = create_app(Database(tmp_path / "app.db"), MemorySecretStore())
    calls: list[str] = []
    monkeypatch.setattr(
        app.state.run_tasks, "recover_due_runs",
        lambda: calls.append("runs") or [],
    )
    monkeypatch.setattr(
        app.state.reference_analysis_tasks, "recover_pending",
        lambda: calls.append("references") or [],
    )

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

    assert calls == ["runs", "references"]


def test_app_startup_terminalizes_exact_once_reservation_before_recovery(
    tmp_path,
) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db.save_project("book", "Book", "short", workspace / "book")
    RunTaskManager(db).reserve_exact_once(
        "exact-once-before-restart", "book", "short-story",
    )

    app = create_app(
        db, MemorySecretStore(), skill_roots=[],
        workspace_root=workspace,
    )

    run = db.get_run("exact-once-before-restart")
    supervision = db.get_workflow_supervision("exact-once-before-restart")
    assert run["status"] == "failed"
    assert run["error"] == "EXACT_ONCE_RUN_INTERRUPTED_NO_RESUME"
    assert supervision["state"] == "irrecoverable"
    assert supervision["restart_policy"] == "exact_once_no_resume"
    assert app.state.run_tasks.recover_due_runs() == []
    assert db.list_recoverable_workflow_supervisions(
        include_future=True,
    ) == []
    assert db.list_workflow_attempts("exact-once-before-restart")[-1][
        "action"
    ] == "exact_once_restart_fail_closed"
