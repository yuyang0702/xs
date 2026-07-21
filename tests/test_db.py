from novel_flywheel.db import Database


def test_database_creates_foundation_tables(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    assert {"providers", "models", "role_bindings", "schema_version"} <= db.table_names()


def test_database_provider_round_trip_omits_secrets(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="relay",
        name="Relay",
        protocol="openai-chat",
        base_url="https://relay.test/v1",
        auth_type="bearer",
        timeout_seconds=180,
        extra_headers={"X-Channel": "novel"},
    )
    provider = db.get_provider("relay")
    assert provider is not None
    assert provider["name"] == "Relay"
    assert "api_key" not in provider
    assert "secret" not in str(provider).lower()

