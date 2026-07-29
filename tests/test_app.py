from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


def test_health(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))
    assert client.get("/api/health").json() == {"status": "ok"}


def test_revision_routes_are_registered(tmp_path) -> None:
    client = TestClient(create_app(Database(tmp_path / "app.db"), MemorySecretStore()))

    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/projects/{project_id}/revisions" in paths
    assert "/api/runs/{run_id}/revision" in paths
