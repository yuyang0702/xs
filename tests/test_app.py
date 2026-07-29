from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.launcher import data_dir_fingerprint
from novel_flywheel.secrets import MemorySecretStore


def test_health(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    response = client.get("/api/health")

    assert response.json() == {
        "status": "ok",
        "service": "novel-flywheel-console",
        "data_dir_fingerprint": data_dir_fingerprint(tmp_path),
    }
    assert str(tmp_path) not in response.text


def test_revision_routes_are_registered(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))

    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/projects/{project_id}/revisions" in paths
    assert "/api/runs/{run_id}/revision" in paths
