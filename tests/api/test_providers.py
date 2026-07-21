from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


def make_client(tmp_path) -> TestClient:
    db = Database(tmp_path / "app.db")
    return TestClient(create_app(db, MemorySecretStore()))


def test_provider_response_never_returns_api_key(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.post("/api/providers", json={
        "name": "relay",
        "protocol": "openai-chat",
        "base_url": "https://relay.test/v1",
        "api_key": "sk-secret",
        "auth_type": "bearer",
        "timeout_seconds": 180,
    })
    assert response.status_code == 201
    assert "sk-secret" not in response.text
    assert response.json()["has_api_key"] is True


def test_add_model_mapping_to_custom_provider(tmp_path) -> None:
    client = make_client(tmp_path)
    provider = client.post("/api/providers", json={
        "name": "relay", "protocol": "anthropic", "base_url": "https://relay.test/v1",
        "api_key": "secret",
    }).json()
    response = client.post(f"/api/providers/{provider['id']}/models", json={
        "display_name": "Claude Sonnet", "model_name": "claude-sonnet-5", "tool_support": "disabled",
    })
    assert response.status_code == 201
    assert response.json()["model_name"] == "claude-sonnet-5"
    assert response.json()["capabilities"]["tool_support"] == "disabled"


def test_reject_unsupported_protocol_without_storing_key(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.post("/api/providers", json={
        "name": "bad", "protocol": "unknown", "base_url": "https://bad.test", "api_key": "secret",
    })
    assert response.status_code == 422
