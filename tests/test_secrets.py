from novel_flywheel.secrets import MemorySecretStore


def test_secret_store_round_trip_without_exposing_values() -> None:
    store = MemorySecretStore()
    store.set("provider-1", "sk-secret-value")
    assert store.get("provider-1") == "sk-secret-value"
    assert "sk-secret-value" not in repr(store)


def test_secret_store_delete_is_idempotent() -> None:
    store = MemorySecretStore()
    store.delete("missing")
    store.set("provider-1", "secret")
    store.delete("provider-1")
    assert store.get("provider-1") is None
