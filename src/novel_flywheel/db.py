import json
import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


WIZARD_MUTATION_LOCK = threading.RLock()


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
CREATE TABLE IF NOT EXISTS project_trash(
  project_id TEXT PRIMARY KEY REFERENCES projects(id),
  original_path TEXT NOT NULL,
  trash_path TEXT NOT NULL,
  trashed_at TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS run_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  severity TEXT NOT NULL,
  event_type TEXT NOT NULL,
  stage TEXT,
  message TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chapter_search USING fts5(
  project_id UNINDEXED, chapter_id UNINDEXED, chapter_number UNINDEXED, content, summary
);
CREATE TABLE IF NOT EXISTS canon_facts(
  project_id TEXT NOT NULL,
  fact_key TEXT NOT NULL,
  value TEXT NOT NULL,
  source TEXT NOT NULL,
  confirmed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  PRIMARY KEY(project_id, fact_key, confirmed)
);
CREATE TABLE IF NOT EXISTS chapter_states(
  project_id TEXT NOT NULL,
  chapter_id TEXT NOT NULL,
  state_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(project_id, chapter_id)
);
CREATE TABLE IF NOT EXISTS drift_findings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  category TEXT NOT NULL,
  score INTEGER NOT NULL,
  message TEXT NOT NULL,
  resolved INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_receipts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  stage TEXT NOT NULL,
  model_id TEXT NOT NULL,
  execution_mode TEXT NOT NULL,
  tool_name TEXT,
  arguments_json TEXT NOT NULL DEFAULT '{}',
  result_size INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  fallback_reason TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wizard_sessions(
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  mode TEXT NOT NULL,
  schema_json TEXT NOT NULL,
  answers_json TEXT NOT NULL,
  project_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wizard_interview_messages(
  id TEXT PRIMARY KEY,
  wizard_id TEXT NOT NULL REFERENCES wizard_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  suggestions_json TEXT NOT NULL DEFAULT '[]',
  suggestion_status TEXT NOT NULL DEFAULT 'none',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS story_locks(
  project_id TEXT NOT NULL,
  lock_key TEXT NOT NULL,
  revision INTEGER NOT NULL,
  value_json TEXT NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(project_id, lock_key, revision)
);
CREATE TABLE IF NOT EXISTS skill_executions(
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  skill_name TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  context_hash TEXT,
  status TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS file_proposals(
  id TEXT PRIMARY KEY,
  execution_id TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS change_requests(
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  lock_key TEXT NOT NULL,
  current_json TEXT NOT NULL,
  proposed_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS story_states(
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL,
  state_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS story_state_history(
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL,
  state_json TEXT NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(project_id, revision)
);
CREATE TABLE IF NOT EXISTS story_candidates(
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  run_id TEXT,
  base_revision INTEGER NOT NULL,
  kind TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  reason TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS reference_sources(
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_uri TEXT,
  platform TEXT,
  content_type TEXT NOT NULL DEFAULT 'reference_work',
  project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
  classification_json TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reference_versions(
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES reference_sources(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  character_count INTEGER NOT NULL,
  storage_path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(source_id, version),
  UNIQUE(source_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_reference_versions_source
  ON reference_versions(source_id, version DESC);
CREATE TABLE IF NOT EXISTS reference_analyses(
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES reference_sources(id) ON DELETE CASCADE,
  version_id TEXT NOT NULL REFERENCES reference_versions(id) ON DELETE CASCADE,
  analyzer TEXT NOT NULL,
  analyzer_version TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(version_id, analyzer, analyzer_version, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_reference_analyses_version
  ON reference_analyses(version_id, analyzer, analyzer_version);
CREATE TABLE IF NOT EXISTS quality_reference_groups(
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  profile_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  action TEXT NOT NULL,
  items_json TEXT NOT NULL DEFAULT '[]',
  decisions_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(project_id, profile_id, version)
);
CREATE INDEX IF NOT EXISTS idx_quality_reference_groups_scope
  ON quality_reference_groups(project_id, profile_id, version DESC);
CREATE TABLE IF NOT EXISTS learning_nodes(
  id TEXT PRIMARY KEY, node_type TEXT NOT NULL, source_id TEXT,
  project_id TEXT, status TEXT NOT NULL, data_json TEXT NOT NULL,
  valid_from TEXT, valid_to TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_learning_nodes_scope ON learning_nodes(node_type, source_id, project_id, status);
CREATE TABLE IF NOT EXISTS learning_edges(
  id TEXT PRIMARY KEY, edge_type TEXT NOT NULL,
  from_node_id TEXT NOT NULL REFERENCES learning_nodes(id) ON DELETE CASCADE,
  to_node_id TEXT NOT NULL REFERENCES learning_nodes(id) ON DELETE CASCADE,
  data_json TEXT NOT NULL DEFAULT '{}', valid_from TEXT, valid_to TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_learning_edges_from ON learning_edges(from_node_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_learning_edges_to ON learning_edges(to_node_id, edge_type);
CREATE TABLE IF NOT EXISTS learning_evidence(
  id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES learning_nodes(id) ON DELETE CASCADE,
  version_id TEXT NOT NULL REFERENCES reference_versions(id) ON DELETE CASCADE,
  start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, excerpt TEXT NOT NULL,
  confidence REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_revisions(
  id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES learning_nodes(id) ON DELETE CASCADE,
  action TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_adoptions(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  node_id TEXT NOT NULL REFERENCES learning_nodes(id), status TEXT NOT NULL,
  data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(project_id, node_id)
);
CREATE TABLE IF NOT EXISTS project_learning_artifacts(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  artifact_type TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
  data_json TEXT NOT NULL, source_hash TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(project_id, artifact_type, version)
);
CREATE TABLE IF NOT EXISTS learning_feedback(
  id TEXT PRIMARY KEY, project_id TEXT, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
  action TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_sources(
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  config_json TEXT NOT NULL DEFAULT '{}',
  refresh_status TEXT NOT NULL DEFAULT 'never',
  refresh_error TEXT,
  last_success_at TEXT,
  last_attempt_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_snapshots(
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES market_sources(id) ON DELETE CASCADE,
  captured_at TEXT NOT NULL,
  status TEXT NOT NULL,
  work_count INTEGER NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_source
  ON market_snapshots(source_id, captured_at DESC);
CREATE TABLE IF NOT EXISTS market_works(
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  platform_work_id TEXT NOT NULL,
  title TEXT NOT NULL,
  normalized_title TEXT NOT NULL,
  author TEXT,
  summary TEXT,
  cover_url TEXT,
  detail_url TEXT,
  original_category TEXT,
  unified_category TEXT,
  tags_json TEXT NOT NULL DEFAULT '[]',
  latest_metrics_json TEXT NOT NULL DEFAULT '{}',
  length_type TEXT NOT NULL DEFAULT 'unknown',
  platform_length_type TEXT,
  length_source TEXT NOT NULL DEFAULT 'unknown',
  length_evidence TEXT,
  length_override TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(platform, platform_work_id)
);
CREATE INDEX IF NOT EXISTS idx_market_works_title
  ON market_works(platform, normalized_title);
CREATE TABLE IF NOT EXISTS market_entries(
  id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL REFERENCES market_snapshots(id) ON DELETE CASCADE,
  work_id TEXT NOT NULL REFERENCES market_works(id) ON DELETE CASCADE,
  ranking_name TEXT NOT NULL,
  category TEXT,
  rank INTEGER,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_entries_work
  ON market_entries(work_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_entries_snapshot
  ON market_entries(snapshot_id, ranking_name, rank);
CREATE TABLE IF NOT EXISTS reference_market_links(
  reference_id TEXT PRIMARY KEY REFERENCES reference_sources(id) ON DELETE CASCADE,
  work_id TEXT NOT NULL REFERENCES market_works(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  confirmed_at TEXT NOT NULL,
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
        self._backup_before_story_state_upgrade()
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(reference_sources)")}
            if "platform" not in columns:
                connection.execute("ALTER TABLE reference_sources ADD COLUMN platform TEXT")
            if "content_type" not in columns:
                connection.execute(
                    "ALTER TABLE reference_sources ADD COLUMN content_type TEXT NOT NULL DEFAULT 'reference_work'"
                )
            if "project_id" not in columns:
                connection.execute(
                    "ALTER TABLE reference_sources ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL"
                )
            if "classification_json" not in columns:
                connection.execute("ALTER TABLE reference_sources ADD COLUMN classification_json TEXT")
            skill_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(skill_executions)")
            }
            if "context_hash" not in skill_columns:
                connection.execute("ALTER TABLE skill_executions ADD COLUMN context_hash TEXT")
            connection.execute(
                "UPDATE reference_sources SET classification_json=? WHERE classification_json IS NULL",
                (json.dumps({"trust": "legacy", "confidence": 0.5,
                             "reasons": ["根据已有分类恢复"]}, ensure_ascii=False),),
            )
            market_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(market_works)")
            }
            market_additions = {
                "length_type": "TEXT NOT NULL DEFAULT 'unknown'",
                "platform_length_type": "TEXT",
                "length_source": "TEXT NOT NULL DEFAULT 'unknown'",
                "length_evidence": "TEXT",
                "length_override": "TEXT",
            }
            for name, declaration in market_additions.items():
                if name not in market_columns:
                    connection.execute(
                        f"ALTER TABLE market_works ADD COLUMN {name} {declaration}"
                    )

    def _backup_before_story_state_upgrade(self) -> None:
        if not self.path.is_file() or self.path.stat().st_size == 0:
            return
        backup = self.path.with_name(f"{self.path.stem}.pre-story-state{self.path.suffix}")
        if backup.exists():
            return
        source = sqlite3.connect(self.path)
        try:
            tables = {row[0] for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "projects" not in tables or "story_states" in tables:
                return
            target = sqlite3.connect(backup)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()

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
            connection.execute(
                "DELETE FROM role_bindings WHERE primary_provider_id = ?",
                (provider_id,),
            )
            connection.execute(
                """UPDATE role_bindings
                SET fallback_provider_id = NULL, fallback_model_id = NULL
                WHERE fallback_provider_id = ?""",
                (provider_id,),
            )
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
                "SELECT * FROM projects WHERE NOT EXISTS "
                "(SELECT 1 FROM project_trash WHERE project_id=projects.id) "
                "ORDER BY created_at DESC, rowid DESC"
            )]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id=? AND NOT EXISTS "
                "(SELECT 1 FROM project_trash WHERE project_id=projects.id)", (project_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_project_path(self, project_id: str, path: Path) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE projects SET path=? WHERE id=?", (str(path), project_id))

    def trash_project(self, project_id: str, original_path: Path, trash_path: Path) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE projects SET path=? WHERE id=?", (str(trash_path), project_id))
            connection.execute(
                "INSERT INTO project_trash VALUES (?, ?, ?, datetime('now'))",
                (project_id, str(original_path), str(trash_path)),
            )

    def list_trashed_projects(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT projects.*, project_trash.original_path, project_trash.trash_path, "
                "project_trash.trashed_at FROM projects JOIN project_trash "
                "ON project_trash.project_id=projects.id ORDER BY project_trash.trashed_at DESC"
            )]

    def get_trashed_project(self, project_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT projects.*, project_trash.original_path, project_trash.trash_path, "
                "project_trash.trashed_at FROM projects JOIN project_trash "
                "ON project_trash.project_id=projects.id WHERE projects.id=?", (project_id,),
            ).fetchone()
        return dict(row) if row else None

    def restore_project(self, project_id: str, path: Path) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE projects SET path=? WHERE id=?", (str(path), project_id))
            connection.execute("DELETE FROM project_trash WHERE project_id=?", (project_id,))

    def delete_project_data(self, project_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM run_events WHERE run_id IN (SELECT id FROM runs WHERE project_id=?)",
                (project_id,),
            )
            connection.execute(
                "DELETE FROM tool_receipts WHERE run_id IN (SELECT id FROM runs WHERE project_id=?)",
                (project_id,),
            )
            connection.execute("DELETE FROM runs WHERE project_id=?", (project_id,))
            connection.execute("DELETE FROM chapter_search WHERE project_id=?", (project_id,))
            for table in ("canon_facts", "chapter_states", "drift_findings", "story_locks", "change_requests"):
                connection.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))
            connection.execute(
                "DELETE FROM file_proposals WHERE execution_id IN "
                "(SELECT id FROM skill_executions WHERE project_id=?)", (project_id,),
            )
            connection.execute("DELETE FROM skill_executions WHERE project_id=?", (project_id,))
            connection.execute("UPDATE wizard_sessions SET project_id=NULL WHERE project_id=?", (project_id,))
            connection.execute("DELETE FROM project_trash WHERE project_id=?", (project_id,))
            connection.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def create_run(self, run_id: str, project_id: str, workflow: str,
                   status: str = "running") -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, NULL, NULL, datetime('now'), datetime('now'))",
                (run_id, project_id, workflow, status),
            )

    def create_run_if_idle(self, run_id: str, project_id: str, workflow: str,
                           status: str = "queued") -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO runs (id, project_id, workflow, status, current_stage, error, created_at, updated_at) "
                "SELECT ?, ?, ?, ?, NULL, NULL, datetime('now'), datetime('now') "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM runs WHERE project_id=? AND status IN ('queued','running','cancelling')"
                ")",
                (run_id, project_id, workflow, status, project_id),
            )
        return cursor.rowcount == 1

    def update_run(self, run_id: str, status: str, current_stage: str | None = None,
                   error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE runs SET status = ?, current_stage = ?, error = ?, updated_at = datetime('now') WHERE id = ?",
                (status, current_stage, error, run_id),
            )

    def claim_run_status(
        self, run_id: str, expected_statuses: set[str],
        status: str, current_stage: str | None = None, *,
        require_project_idle: bool = False,
    ) -> bool:
        if not expected_statuses:
            return False
        ordered = sorted(expected_statuses)
        placeholders = ", ".join("?" for _ in ordered)
        idle_clause = ""
        arguments: list[Any] = [status, current_stage, run_id, *ordered]
        if require_project_idle:
            idle_clause = (
                " AND NOT EXISTS ("
                "SELECT 1 FROM runs active WHERE active.project_id=("
                "SELECT project_id FROM runs WHERE id=?"
                ") AND active.id<>? "
                "AND active.status IN ('queued','running','cancelling')"
                ")"
            )
            arguments.extend((run_id, run_id))
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE runs SET status=?, current_stage=?, error=NULL, "
                "updated_at=datetime('now') "
                f"WHERE id=? AND status IN ({placeholders}){idle_clause}",
                arguments,
            )
        return cursor.rowcount == 1

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM runs WHERE project_id = ? ORDER BY created_at DESC, rowid DESC",
                (project_id,),
            )]

    def has_active_runs(self, project_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM runs WHERE project_id=? AND status IN ('queued', 'running', 'cancelling') LIMIT 1",
                (project_id,),
            ).fetchone()
        return row is not None

    def add_run_event(self, run_id: str, severity: str, event_type: str,
                      message: str, *, stage: str | None = None,
                      metadata: dict[str, Any] | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO run_events(run_id, severity, event_type, stage, message, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (run_id, severity, event_type, stage, message,
                 json.dumps(metadata or {}, ensure_ascii=False)),
            )

    def list_run_events(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM run_events WHERE run_id=? ORDER BY id", (run_id,),
            ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["metadata"] = json.loads(event.pop("metadata_json"))
            events.append(event)
        return events

    def interrupt_active_runs(self) -> int:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM runs WHERE status IN ('queued', 'running', 'cancelling')"
            ).fetchall()
            connection.execute(
                "UPDATE runs SET status='interrupted', error='Program restarted while task was active', "
                "updated_at=datetime('now') WHERE status IN ('queued', 'running', 'cancelling')"
            )
            for row in rows:
                connection.execute(
                    "INSERT INTO run_events(run_id, severity, event_type, stage, message, metadata_json, created_at) "
                    "VALUES (?, 'warning', 'interrupted', NULL, '程序重启，任务已中断', '{}', datetime('now'))",
                    (row["id"],),
                )
        return len(rows)

    def save_tool_receipt(self, *, run_id: str | None, stage: str, model_id: str,
                          execution_mode: str, tool_name: str | None = None,
                          arguments: dict | None = None, result_size: int = 0,
                          duration_ms: int = 0, status: str = "succeeded",
                          fallback_reason: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO tool_receipts(run_id, stage, model_id, execution_mode, tool_name, "
                "arguments_json, result_size, duration_ms, status, fallback_reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (run_id, stage, model_id, execution_mode, tool_name,
                 json.dumps(arguments or {}, ensure_ascii=False), result_size, duration_ms,
                 status, fallback_reason),
            )

    def list_tool_receipts(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM tool_receipts WHERE run_id = ? ORDER BY id", (run_id,),
            )]

    def save_wizard(self, wizard_id: str, status: str, mode: str,
                    schema: dict, answers: dict, project_id: str | None = None) -> None:
        with WIZARD_MUTATION_LOCK, self.connect() as connection:
            connection.execute(
                """INSERT INTO wizard_sessions VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(id) DO UPDATE SET status=excluded.status, mode=excluded.mode,
                schema_json=excluded.schema_json, answers_json=excluded.answers_json,
                project_id=COALESCE(excluded.project_id, wizard_sessions.project_id),
                updated_at=datetime('now')""",
                (wizard_id, status, mode, json.dumps(schema, ensure_ascii=False),
                 json.dumps(answers, ensure_ascii=False), project_id),
            )

    def get_wizard(self, wizard_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM wizard_sessions WHERE id = ?", (wizard_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["schema"] = json.loads(result.pop("schema_json"))
        result["answers"] = json.loads(result.pop("answers_json"))
        return result

    def delete_wizard(self, wizard_id: str) -> bool:
        with WIZARD_MUTATION_LOCK, self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM wizard_sessions WHERE id = ? AND project_id IS NULL "
                "AND status IN (?, ?, ?)",
                (wizard_id, "draft", "gathering_input", "ready"),
            )
        return cursor.rowcount == 1

    def list_wizards(self, status: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if status:
                ids = [row[0] for row in connection.execute(
                    "SELECT id FROM wizard_sessions WHERE status = ? ORDER BY updated_at DESC", (status,),
                )]
            else:
                ids = [row[0] for row in connection.execute(
                    "SELECT id FROM wizard_sessions ORDER BY updated_at DESC",
                )]
        return [wizard for item in ids if (wizard := self.get_wizard(item))]

    def save_interview_message(self, message_id: str, wizard_id: str, role: str,
                               content: str, suggestions: list[dict]) -> None:
        suggestion_status = "pending" if suggestions else "none"
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO wizard_interview_messages VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (message_id, wizard_id, role, content,
                 json.dumps(suggestions, ensure_ascii=False), suggestion_status),
            )

    def get_interview_message(self, message_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM wizard_interview_messages WHERE id=?", (message_id,),
            ).fetchone()
        if row is None:
            return None
        message = dict(row)
        message["suggestions"] = json.loads(message.pop("suggestions_json"))
        return message

    def list_interview_messages(self, wizard_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT id FROM wizard_interview_messages WHERE wizard_id=? ORDER BY rowid",
                (wizard_id,),
            )]
        return [message for item in ids if (message := self.get_interview_message(item))]

    def update_interview_message_status(self, message_id: str, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE wizard_interview_messages SET suggestion_status=? WHERE id=?",
                (status, message_id),
            )

    def save_lock(self, project_id: str, lock_key: str, value: Any, source: str) -> None:
        with self.connect() as connection:
            revision = connection.execute(
                "SELECT COALESCE(MAX(revision), 0) + 1 FROM story_locks WHERE project_id = ? AND lock_key = ?",
                (project_id, lock_key),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO story_locks VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (project_id, lock_key, revision, json.dumps(value, ensure_ascii=False), source),
            )

    def list_locks(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT item.* FROM story_locks item JOIN (
                SELECT lock_key, MAX(revision) revision FROM story_locks
                WHERE project_id = ? GROUP BY lock_key) latest
                ON item.lock_key=latest.lock_key AND item.revision=latest.revision
                WHERE item.project_id = ? ORDER BY item.lock_key""",
                (project_id, project_id),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["key"] = item.pop("lock_key")
            item["value"] = json.loads(item.pop("value_json"))
            result.append(item)
        return result

    def create_skill_execution(self, execution_id: str, project_id: str,
                               skill_name: str, content_hash: str,
                               status: str = "pending", *,
                               context_hash: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO skill_executions "
                "(id, project_id, skill_name, content_hash, context_hash, status, error, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, datetime('now'), datetime('now'))",
                (execution_id, project_id, skill_name, content_hash, context_hash, status),
            )

    def update_skill_execution(self, execution_id: str, status: str,
                               error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE skill_executions SET status=?, error=?, updated_at=datetime('now') WHERE id=?",
                (status, error, execution_id),
            )

    def get_skill_execution(self, execution_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM skill_executions WHERE id=?", (execution_id,),
            ).fetchone()
        return dict(row) if row else None

    def has_completed_skill_execution(self, project_id: str, skill_name: str,
                                      content_hash: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM skill_executions WHERE project_id=? AND skill_name=? "
                "AND content_hash=? AND status='completed' LIMIT 1",
                (project_id, skill_name, content_hash),
            ).fetchone()
        return row is not None

    def save_file_proposal(self, proposal_id: str, execution_id: str,
                           relative_path: str, content: str, status: str,
                           error: str | None = None) -> None:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO file_proposals VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (proposal_id, execution_id, relative_path, content, digest, status, error),
            )

    def list_file_proposals(self, execution_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM file_proposals WHERE execution_id=? ORDER BY created_at, rowid",
                (execution_id,),
            )]

    def update_file_proposal(self, proposal_id: str, status: str,
                             error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE file_proposals SET status=?, error=? WHERE id=?",
                (status, error, proposal_id),
            )

    def update_file_proposals_status(
        self, execution_id: str, current_status: str, status: str,
        error: str | None = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE file_proposals SET status=?, error=? "
                "WHERE execution_id=? AND status=?",
                (status, error, execution_id, current_status),
            )
        return cursor.rowcount

    def file_proposal_summary(self, execution_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) count FROM file_proposals "
                "WHERE execution_id=? GROUP BY status ORDER BY status",
                (execution_id,),
            ).fetchall()
        counts = {row["status"]: int(row["count"]) for row in rows}
        recoverable = {"pending", "retained", "failed"}
        return {
            "execution_id": execution_id,
            "total": sum(counts.values()),
            "recoverable_count": sum(
                count for status, count in counts.items() if status in recoverable
            ),
            "counts": counts,
        }

    def list_recoverable_skill_executions(
        self, project_id: str, skill_name: str | None = None,
        content_hash: str | None = None, context_hash: str | None = None,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT * FROM skill_executions WHERE project_id=? AND status='recoverable'"
        )
        arguments: list[Any] = [project_id]
        if skill_name:
            query += " AND skill_name=?"
            arguments.append(skill_name)
        if content_hash:
            query += " AND content_hash=?"
            arguments.append(content_hash)
        if context_hash:
            query += " AND context_hash=?"
            arguments.append(context_hash)
        query += " ORDER BY updated_at DESC, rowid DESC"
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(query, arguments)]
        for row in rows:
            row["proposal_summary"] = self.file_proposal_summary(row["id"])
        return rows

    def create_reference_source(self, source_id: str, title: str, source_type: str,
                                source_uri: str | None = None, platform: str | None = None,
                                content_type: str = "reference_work",
                                project_id: str | None = None,
                                classification: dict | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO reference_sources "
                "(id,title,source_type,source_uri,platform,content_type,project_id,classification_json,status,created_at,updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', datetime('now'), datetime('now'))",
                (source_id, title, source_type, source_uri, platform, content_type, project_id,
                 json.dumps(classification or {}, ensure_ascii=False)),
            )

    def update_reference_source_metadata(
        self, source_id: str, platform: str | None, content_type: str, project_id: str | None,
        classification: dict | None = None,
    ) -> bool:
        with self.connect() as connection:
            current = connection.execute(
                "SELECT platform,content_type,project_id FROM reference_sources WHERE id=?",
                (source_id,),
            ).fetchone()
            if current is None:
                return False
            changed = (
                current["platform"] != platform
                or current["content_type"] != content_type
                or current["project_id"] != project_id
            )
            cursor = connection.execute(
                "UPDATE reference_sources SET platform=?,content_type=?,project_id=?,classification_json=COALESCE(?,classification_json),updated_at=datetime('now') "
                "WHERE id=?",
                (platform, content_type, project_id,
                 json.dumps(classification, ensure_ascii=False) if classification is not None else None, source_id),
            )
            if changed:
                affected_projects = [
                    row["project_id"] for row in connection.execute(
                        "SELECT DISTINCT adoption.project_id FROM project_adoptions adoption "
                        "JOIN learning_nodes node ON node.id=adoption.node_id "
                        "WHERE node.source_id=? AND adoption.status='adopted'",
                        (source_id,),
                    )
                ]
                connection.execute(
                    "UPDATE learning_nodes SET status='needs_review',updated_at=datetime('now') "
                    "WHERE source_id=? AND node_type='mechanism' AND status='proposed'",
                    (source_id,),
                )
                connection.execute(
                    "UPDATE project_adoptions SET status='review_source_metadata_changed',updated_at=datetime('now') "
                    "WHERE status='adopted' AND node_id IN "
                    "(SELECT id FROM learning_nodes WHERE source_id=?)",
                    (source_id,),
                )
                if affected_projects:
                    placeholders = ",".join("?" for _ in affected_projects)
                    connection.execute(
                        f"UPDATE project_learning_artifacts SET status='stale' "
                        f"WHERE artifact_type='creative_blueprint' AND project_id IN ({placeholders}) "
                        "AND status='active'",
                        affected_projects,
                    )
        return cursor.rowcount > 0

    def get_reference_source(self, source_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reference_sources WHERE id=?", (source_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_reference_sources(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM reference_sources ORDER BY updated_at DESC, rowid DESC",
            )]

    def save_quality_reference_group(
        self, group_id: str, project_id: str, profile_id: str, action: str,
        items: list[dict[str, Any]], decisions: dict[str, str],
    ) -> dict[str, Any]:
        with self.connect() as connection:
            version = int(connection.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM quality_reference_groups "
                "WHERE project_id=? AND profile_id=?",
                (project_id, profile_id),
            ).fetchone()[0])
            connection.execute(
                "INSERT INTO quality_reference_groups VALUES "
                "(?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (group_id, project_id, profile_id, version, action,
                 json.dumps(items, ensure_ascii=False),
                 json.dumps(decisions, ensure_ascii=False)),
            )
        return self.latest_quality_reference_group(project_id, profile_id) or {}

    def latest_quality_reference_group(
        self, project_id: str, profile_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM quality_reference_groups WHERE project_id=? "
                "AND profile_id=? ORDER BY version DESC LIMIT 1",
                (project_id, profile_id),
            ).fetchone()
        return self._public_quality_reference_group(row) if row else None

    def list_quality_reference_group_history(
        self, project_id: str, profile_id: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM quality_reference_groups WHERE project_id=? "
                "AND profile_id=? ORDER BY version DESC",
                (project_id, profile_id),
            ).fetchall()
        return [self._public_quality_reference_group(row) for row in rows]

    @staticmethod
    def _public_quality_reference_group(row) -> dict[str, Any]:
        item = dict(row)
        item["items"] = json.loads(item.pop("items_json"))
        item["decisions"] = json.loads(item.pop("decisions_json"))
        return item

    def delete_reference_source(self, source_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM reference_sources WHERE id=?", (source_id,))
        return cursor.rowcount > 0

    def find_reference_source_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT source.* FROM reference_sources source
                JOIN reference_versions version ON version.source_id=source.id
                WHERE version.content_hash=? ORDER BY source.updated_at DESC LIMIT 1""",
                (content_hash,),
            ).fetchone()
        return dict(row) if row else None

    def create_reference_version(self, version_id: str, source_id: str, content_hash: str,
                                 character_count: int, storage_path: str) -> dict[str, Any]:
        with self.connect() as connection:
            version = int(connection.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM reference_versions WHERE source_id=?",
                (source_id,),
            ).fetchone()[0])
            connection.execute(
                "INSERT INTO reference_versions VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (version_id, source_id, version, content_hash, character_count, storage_path),
            )
            connection.execute(
                "UPDATE reference_sources SET updated_at=datetime('now') WHERE id=?", (source_id,),
            )
        return self.get_reference_version(version_id)

    def get_reference_version(self, version_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reference_versions WHERE id=?", (version_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_reference_versions(self, source_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM reference_versions WHERE source_id=? ORDER BY version DESC",
                (source_id,),
            )]

    def save_reference_analysis(self, analysis_id: str, source_id: str, version_id: str,
                                analyzer: str, analyzer_version: str, content_hash: str,
                                result: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO reference_analyses VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (analysis_id, source_id, version_id, analyzer, analyzer_version, content_hash,
                 json.dumps(result, ensure_ascii=False)),
            )
        return self.get_reference_analysis(version_id, analyzer, analyzer_version, content_hash)

    def get_reference_analysis(self, version_id: str, analyzer: str, analyzer_version: str,
                               content_hash: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM reference_analyses WHERE version_id=? AND analyzer=?
                AND analyzer_version=? AND content_hash=?""",
                (version_id, analyzer, analyzer_version, content_hash),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json"))
        return result

    def save_change_request(self, request_id: str, project_id: str, lock_key: str,
                            current: Any, proposed: Any, reason: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO change_requests VALUES (?, ?, ?, ?, ?, ?, 'pending', datetime('now'), NULL)",
                (request_id, project_id, lock_key, json.dumps(current, ensure_ascii=False),
                 json.dumps(proposed, ensure_ascii=False), reason),
            )

    def list_change_requests(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM change_requests WHERE project_id=? ORDER BY created_at, rowid",
                (project_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["current"] = json.loads(item.pop("current_json"))
            item["proposed"] = json.loads(item.pop("proposed_json"))
            result.append(item)
        return result
