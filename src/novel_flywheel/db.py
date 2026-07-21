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
CREATE TABLE IF NOT EXISTS skill_approvals(
  skill_name TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  PRIMARY KEY(skill_name, content_hash)
);
CREATE TABLE IF NOT EXISTS skill_receipts(
  id TEXT PRIMARY KEY,
  stage TEXT NOT NULL,
  skill_name TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  output TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects(
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  mode TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  workflow TEXT NOT NULL,
  status TEXT NOT NULL,
  current_stage TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
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

    def save_model(
        self,
        *,
        model_id: str,
        provider_id: str,
        display_name: str,
        model_name: str,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO models
                (id, provider_id, display_name, model_name, context_window, max_output_tokens, capabilities_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,
                model_name=excluded.model_name, context_window=excluded.context_window,
                max_output_tokens=excluded.max_output_tokens,
                capabilities_json=excluded.capabilities_json""",
                (model_id, provider_id, display_name, model_name, context_window, max_output_tokens,
                 json.dumps(capabilities or {}, ensure_ascii=False)),
            )

    def list_models(self, provider_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM models WHERE provider_id = ? ORDER BY display_name", (provider_id,)
            ).fetchall()
        models = []
        for row in rows:
            model = dict(row)
            model["capabilities"] = json.loads(model.pop("capabilities_json"))
            models.append(model)
        return models

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
        if row is None:
            return None
        model = dict(row)
        model["capabilities"] = json.loads(model.pop("capabilities_json"))
        return model

    def save_role_binding(
        self,
        role: str,
        primary_provider_id: str,
        primary_model_id: str,
        fallback_provider_id: str | None,
        fallback_model_id: str | None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO role_bindings
                (role, primary_provider_id, primary_model_id, fallback_provider_id, fallback_model_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(role) DO UPDATE SET primary_provider_id=excluded.primary_provider_id,
                primary_model_id=excluded.primary_model_id, fallback_provider_id=excluded.fallback_provider_id,
                fallback_model_id=excluded.fallback_model_id""",
                (role, primary_provider_id, primary_model_id, fallback_provider_id, fallback_model_id),
            )

    def list_role_bindings(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM role_bindings ORDER BY role")]

    def get_role_binding(self, role: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM role_bindings WHERE role = ?", (role,)).fetchone()
        return dict(row) if row else None

    def approve_skill(self, skill_name: str, content_hash: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO skill_approvals VALUES (?, ?, datetime('now'))",
                (skill_name, content_hash),
            )

    def is_skill_approved(self, skill_name: str, content_hash: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM skill_approvals WHERE skill_name = ? AND content_hash = ?",
                (skill_name, content_hash),
            ).fetchone()
        return row is not None

    def save_skill_receipt(self, receipt_id: str, stage: str, skill_name: str,
                           content_hash: str, status: str, output: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO skill_receipts VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (receipt_id, stage, skill_name, content_hash, status, output),
            )

    def list_skill_receipts(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM skill_receipts ORDER BY created_at, rowid"
            )]

    def save_project(self, project_id: str, title: str, mode: str, path: Path) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO projects VALUES (?, ?, ?, ?, datetime('now'))",
                (project_id, title, mode, str(path)),
            )

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM projects ORDER BY created_at DESC, rowid DESC"
            )]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None
