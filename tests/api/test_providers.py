from pathlib import Path

from fastapi.testclient import TestClient

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore


def make_client(tmp_path) -> TestClient:
    db = Database(tmp_path / "app.db")
    return TestClient(create_app(db, MemorySecretStore()))


def test_provider_ui_exposes_observed_diagnostics_not_manual_capacity_controls() -> None:
    static = Path(__file__).parents[2] / "src" / "novel_flywheel" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    script = (static / "app.js").read_text(encoding="utf-8")

    assert 'name="context_window"' not in html
    assert 'name="max_output_tokens"' not in html
    assert 'name="structured_output"' not in html
    assert "由实际接口探测及运行观测自动管理" in html
    assert "严格 Schema" in script
    assert "探测结果已过期，将按安全模式运行" in script


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
    assert response.json()["capabilities"]["structured_output"] == "plain_text"


def test_model_capabilities_are_route_local_and_updateable(tmp_path) -> None:
    client = make_client(tmp_path)
    provider, model = add_provider_model(client, "third-party-relay")

    response = client.put(
        f"/api/providers/{provider['id']}/models/{model['id']}/capabilities",
        json={
            "tool_support": "enabled",
            "structured_output": "strict_tool",
        },
    )

    assert response.status_code == 200
    assert response.json()["capabilities"] == {
        "tool_support": "enabled",
        "structured_output": "strict_tool",
    }


def test_add_model_records_third_party_capacity_without_brand_inference(tmp_path) -> None:
    client = make_client(tmp_path)
    provider = client.post("/api/providers", json={
        "name": "relay",
        "protocol": "openai-chat",
        "base_url": "https://relay.test/v1",
        "api_key": "secret",
    }).json()

    response = client.post(f"/api/providers/{provider['id']}/models", json={
        "display_name": "Gemini through relay",
        "model_name": "gemini-compatible-name",
        "structured_output": "json_object",
        "context_window": 131072,
        "max_output_tokens": 8192,
    })

    assert response.status_code == 201
    assert response.json()["context_window"] == 131072
    assert response.json()["max_output_tokens"] == 8192
    assert response.json()["capabilities"]["structured_output"] == "json_object"


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


def test_update_provider_preserves_models_and_existing_api_key(tmp_path) -> None:
    client = make_client(tmp_path)
    provider, model = add_provider_model(client, "relay")

    response = client.put(f"/api/providers/{provider['id']}", json={
        "name": "renamed relay",
        "protocol": "openai-chat",
        "base_url": "https://new-relay.test/v1/",
        "auth_type": "bearer",
        "timeout_seconds": 240,
        "extra_headers": {"X-Relay": "novel"},
        "api_key": "",
    })

    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "renamed relay"
    assert updated["protocol"] == "openai-chat"
    assert updated["base_url"] == "https://new-relay.test/v1"
    assert updated["timeout_seconds"] == 240
    assert updated["extra_headers"] == {"X-Relay": "novel"}
    assert updated["models"][0]["id"] == model["id"]
    assert client.app.state.registry.secrets.get(provider["id"]) == "secret"


def test_update_provider_replaces_api_key_when_supplied(tmp_path) -> None:
    client = make_client(tmp_path)
    provider, _ = add_provider_model(client, "relay")

    response = client.put(f"/api/providers/{provider['id']}", json={
        "name": "relay",
        "protocol": "anthropic",
        "base_url": "https://relay.test",
        "api_key": "new-secret",
    })

    assert response.status_code == 200
    assert client.app.state.registry.secrets.get(provider["id"]) == "new-secret"
    assert "new-secret" not in response.text


def test_update_provider_rejects_invalid_url(tmp_path) -> None:
    client = make_client(tmp_path)
    provider, _ = add_provider_model(client, "relay")

    response = client.put(f"/api/providers/{provider['id']}", json={
        "name": "relay",
        "protocol": "anthropic",
        "base_url": "not-a-url",
    })

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_provider"


def test_update_missing_provider_returns_not_found(tmp_path) -> None:
    client = make_client(tmp_path)

    response = client.put("/api/providers/missing", json={
        "name": "relay",
        "protocol": "anthropic",
        "base_url": "https://relay.test",
    })

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "provider_not_found"


def test_delete_provider_removes_models_and_api_key(tmp_path) -> None:
    client = make_client(tmp_path)
    provider, model = add_provider_model(client, "relay")

    response = client.delete(f"/api/providers/{provider['id']}")

    assert response.status_code == 204
    assert client.app.state.registry.db.get_provider(provider["id"]) is None
    assert client.app.state.registry.db.get_model(model["id"]) is None
    assert client.app.state.registry.secrets.get(provider["id"]) is None


def test_delete_provider_removes_role_bindings_that_reference_it(tmp_path) -> None:
    client = make_client(tmp_path)
    provider, model = add_provider_model(client, "relay")
    client.put("/api/role-bindings/polish", json={
        "primary_provider_id": provider["id"],
        "primary_model_id": model["id"],
    })

    client.delete(f"/api/providers/{provider['id']}")

    assert client.get("/api/role-bindings").json() == []


def test_delete_fallback_provider_keeps_primary_role_binding(tmp_path) -> None:
    client = make_client(tmp_path)
    primary_provider, primary_model = add_provider_model(client, "primary")
    fallback_provider, fallback_model = add_provider_model(client, "fallback")
    client.put("/api/role-bindings/polish", json={
        "primary_provider_id": primary_provider["id"],
        "primary_model_id": primary_model["id"],
        "fallback_provider_id": fallback_provider["id"],
        "fallback_model_id": fallback_model["id"],
    })

    client.delete(f"/api/providers/{fallback_provider['id']}")

    binding = client.get("/api/role-bindings").json()[0]
    assert binding["primary_provider_id"] == primary_provider["id"]
    assert binding["fallback_provider_id"] is None
    assert binding["fallback_model_id"] is None


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
