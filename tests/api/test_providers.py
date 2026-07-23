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


def test_update_provider_api_key_without_recreating_provider(tmp_path) -> None:
    client = make_client(tmp_path)
    provider = client.post("/api/providers", json={
        "name": "relay", "protocol": "anthropic", "base_url": "https://relay.test",
        "api_key": "old-secret",
    }).json()

    response = client.put(f"/api/providers/{provider['id']}/api-key", json={
        "api_key": "new-secret",
    })

    assert response.status_code == 200
    assert response.json() == {"id": provider["id"], "has_api_key": True}
    assert client.app.state.registry.secrets.get(provider["id"]) == "new-secret"
    assert "new-secret" not in response.text


def add_provider_model(client: TestClient, name: str) -> tuple[dict, dict]:
    provider = client.post("/api/providers", json={
        "name": name, "protocol": "anthropic", "base_url": f"https://{name}.test",
        "api_key": "secret",
    }).json()
    model = client.post(f"/api/providers/{provider['id']}/models", json={
        "display_name": name, "model_name": name,
    }).json()
    return provider, model


def test_role_binding_saves_configured_fallback(tmp_path) -> None:
    client = make_client(tmp_path)
    primary_provider, primary_model = add_provider_model(client, "primary")
    fallback_provider, fallback_model = add_provider_model(client, "fallback")

    response = client.put("/api/role-bindings/polish", json={
        "primary_provider_id": primary_provider["id"],
        "primary_model_id": primary_model["id"],
        "fallback_provider_id": fallback_provider["id"],
        "fallback_model_id": fallback_model["id"],
    })

    assert response.status_code == 200
    assert response.json()["fallback_model_id"] == fallback_model["id"]
    assert client.get("/api/role-bindings").json()[0]["fallback_provider_id"] == fallback_provider["id"]


def test_role_binding_rejects_partial_fallback(tmp_path) -> None:
    client = make_client(tmp_path)
    provider, model = add_provider_model(client, "primary")

    response = client.put("/api/role-bindings/polish", json={
        "primary_provider_id": provider["id"],
        "primary_model_id": model["id"],
        "fallback_provider_id": provider["id"],
    })

    assert response.status_code == 422


def test_role_binding_rejects_same_primary_and_fallback(tmp_path) -> None:
    client = make_client(tmp_path)
    provider, model = add_provider_model(client, "primary")

    response = client.put("/api/role-bindings/polish", json={
        "primary_provider_id": provider["id"],
        "primary_model_id": model["id"],
        "fallback_provider_id": provider["id"],
        "fallback_model_id": model["id"],
    })

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "fallback_matches_primary"
