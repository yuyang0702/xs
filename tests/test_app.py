from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.launcher import data_dir_fingerprint, runtime_fingerprint
from novel_flywheel.secrets import MemorySecretStore


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
