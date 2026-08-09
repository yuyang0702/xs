from novel_flywheel.db import Database
from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.secrets import MemorySecretStore
from datetime import datetime, timedelta, timezone


def test_registry_resolves_custom_provider_model(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    registry = ProviderRegistry(db, MemorySecretStore())
    provider_id = registry.add_provider(provider_id="relay", name="Relay", protocol="openai-chat",
                                        base_url="https://relay.test/v1", api_key="secret")
    model_id = registry.add_model(provider_id, "Claude Sonnet", "claude-sonnet-5")
    resolved = registry.resolve(provider_id, model_id)
    assert resolved.model_name == "claude-sonnet-5"
    assert isinstance(resolved.adapter, OpenAIChatAdapter)


def test_registry_rejects_unsupported_protocol(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    registry = ProviderRegistry(db, MemorySecretStore())
    try:
        registry.add_provider(name="Bad", protocol="unknown", base_url="https://bad.test", api_key="secret")
    except ValueError as exc:
        assert str(exc) == "unsupported_protocol"
    else:
        raise AssertionError("unsupported protocol was accepted")


def test_observed_capability_is_invalidated_when_third_party_route_changes(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    registry = ProviderRegistry(db, MemorySecretStore())
    provider_id = registry.add_provider(
        provider_id="relay", name="Relay", protocol="openai-chat",
        base_url="https://relay.test/v1", api_key="secret",
    )
    model_id = registry.add_model(provider_id, "Model", "actual-model")
    resolved = registry.resolve(provider_id, model_id)
    registry.update_model_capabilities(provider_id, model_id, {
        "structured_output": "strict_json_schema",
        "tool_support": "enabled",
        "capability_probe_status": "succeeded",
        "capability_probe_route_fingerprint": resolved.route_fingerprint,
        "capability_probe_expires_at": (
            datetime.now(timezone.utc) + timedelta(days=7)
        ).isoformat(),
    })

    registry.update_provider(
        provider_id, name="Relay", protocol="openai-responses",
        base_url="https://relay.test/v1", api_key=None,
    )
    stale = registry.resolve(provider_id, model_id)

    assert stale.capabilities["capability_probe_status"] == "stale"
    assert stale.capabilities["capability_probe_stale_reason"] == "route_changed"
    assert stale.capabilities["structured_output"] == "plain_text"
    assert stale.capabilities["tool_support"] == "auto"


def test_expired_probe_degrades_safely_but_manual_legacy_config_stays_compatible(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    registry = ProviderRegistry(db, MemorySecretStore())
    provider_id = registry.add_provider(
        provider_id="relay", name="Relay", protocol="anthropic",
        base_url="https://relay.test", api_key="secret",
    )
    manual_id = registry.add_model(
        provider_id, "Manual", "manual-model",
        {"structured_output": "json_object", "tool_support": "disabled"},
    )
    expired_id = registry.add_model(provider_id, "Expired", "expired-model")
    route = registry.resolve(provider_id, expired_id)
    registry.update_model_capabilities(provider_id, expired_id, {
        "structured_output": "strict_tool",
        "tool_support": "enabled",
        "capability_probe_status": "succeeded",
        "capability_probe_route_fingerprint": route.route_fingerprint,
        "capability_probe_expires_at": (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat(),
    })

    assert registry.resolve(provider_id, manual_id).capabilities["structured_output"] == "json_object"
    expired = registry.resolve(provider_id, expired_id).capabilities
    assert expired["capability_probe_stale_reason"] == "expired"
    assert expired["structured_output"] == "plain_text"
