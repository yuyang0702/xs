from novel_flywheel.db import Database
from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.secrets import MemorySecretStore


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
