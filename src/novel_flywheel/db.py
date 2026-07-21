import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
CREATE TABLE IF NOT EXISTS providers(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  protocol TEXT NOT NULL,
  base_url TEXT NOT NULL,
  auth_type TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  timeout_seconds INTEGER NOT NULL DEFAULT 180,
  extra_headers_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS models(
  id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
  display_name TEXT NOT NULL,
  model_name TEXT NOT NULL,
  context_window INTEGER,
  max_output_tokens INTEGER,
  capabilities_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(provider_id, display_name)
);
CREATE TABLE IF NOT EXISTS role_bindings(
  role TEXT PRIMARY KEY,
  primary_provider_id TEXT NOT NULL,
  primary_model_id TEXT NOT NULL,
  fallback_provider_id TEXT,
  fallback_model_id TEXT
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def table_names(self) -> set[str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            return {row[0] for row in rows}

    def save_provider(
        self,
        *,
        provider_id: str,
        name: str,
        protocol: str,
        base_url: str,
        auth_type: str,
        timeout_seconds: int,
        extra_headers: dict[str, str],
        enabled: bool = True,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO providers
                (id, name, protocol, base_url, auth_type, enabled, timeout_seconds, extra_headers_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, protocol=excluded.protocol,
                base_url=excluded.base_url, auth_type=excluded.auth_type, enabled=excluded.enabled,
                timeout_seconds=excluded.timeout_seconds, extra_headers_json=excluded.extra_headers_json""",
                (provider_id, name, protocol, base_url.rstrip("/"), auth_type, int(enabled),
                 timeout_seconds, json.dumps(extra_headers, ensure_ascii=False)),
            )

    def get_provider(self, provider_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["enabled"] = bool(result["enabled"])
        result["extra_headers"] = json.loads(result.pop("extra_headers_json"))
        return result

    def list_providers(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            ids = [row[0] for row in connection.execute("SELECT id FROM providers ORDER BY name")]
        return [provider for provider_id in ids if (provider := self.get_provider(provider_id))]

    def delete_provider(self, provider_id: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM providers WHERE id = ?", (provider_id,))

