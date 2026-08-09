import json
import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from novel_flywheel.production_incidents import classify_production_failure


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
CREATE TABLE IF NOT EXISTS model_output_observations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  route_fingerprint TEXT NOT NULL,
  execution_mode TEXT NOT NULL,
  requested_max_output_tokens INTEGER,
  actual_output_tokens INTEGER NOT NULL DEFAULT 0,
  visible_characters INTEGER NOT NULL DEFAULT 0,
  finish_reason TEXT,
  transport_complete INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_node_checkpoints(
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  node_key TEXT NOT NULL,
  authority_sha256 TEXT NOT NULL,
  input_sha256 TEXT NOT NULL,
  output_sha256 TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  checkpoint_version INTEGER NOT NULL DEFAULT 2,
  validation_stage TEXT NOT NULL DEFAULT 'transport',
  attempt INTEGER NOT NULL DEFAULT 1,
  route_fingerprint TEXT NOT NULL DEFAULT '',
  next_node TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(run_id, node_key, input_sha256)
);
CREATE INDEX IF NOT EXISTS idx_workflow_node_checkpoints_resume
  ON workflow_node_checkpoints(run_id, node_key, authority_sha256, status);
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
            checkpoint_columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(workflow_node_checkpoints)"
                )
            }
            if "checkpoint_version" not in checkpoint_columns:
                connection.execute(
                    "ALTER TABLE workflow_node_checkpoints "
                    "ADD COLUMN checkpoint_version INTEGER NOT NULL DEFAULT 1"
                )
            if "validation_stage" not in checkpoint_columns:
                connection.execute(
                    "ALTER TABLE workflow_node_checkpoints "
                    "ADD COLUMN validation_stage TEXT NOT NULL DEFAULT 'transport'"
                )
            connection.execute(
                "UPDATE workflow_node_checkpoints "
                "SET validation_stage='promoted' "
                "WHERE checkpoint_version=1 AND status='validated'"
            )
            connection.execute(
                "UPDATE workflow_node_checkpoints SET checkpoint_version=2 "
                "WHERE checkpoint_version<2"
            )
            connection.execute(
                "UPDATE schema_version SET version=2 WHERE version<2"
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

    def save_workflow_node_checkpoint(
        self, *, run_id: str, node_key: str, authority_sha256: str,
        input_sha256: str, output_sha256: str, status: str,
        route_fingerprint: str = "", next_node: str = "",
        validation_stage: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one idempotent node envelope without promoting story data."""
        from novel_flywheel.workflow_state import (
            CheckpointEnvelope,
            checkpoint_stage_rank,
        )

        with self.connect() as connection:
            effective_validation_stage = validation_stage or (
                "promoted" if status == "validated" else "transport"
            )
            row = connection.execute(
                "SELECT * FROM workflow_node_checkpoints "
                "WHERE run_id=? AND node_key=? AND input_sha256=?",
                (run_id, node_key, input_sha256),
            ).fetchone()
            attempt = int(row["attempt"]) + 1 if row else 1
            envelope = CheckpointEnvelope.model_validate({
                "run_id": run_id,
                "node_key": node_key,
                "authority_sha256": authority_sha256,
                "input_sha256": input_sha256,
                "output_sha256": output_sha256,
                "status": status,
                "validation_stage": effective_validation_stage,
                "attempt": attempt,
                "route_fingerprint": route_fingerprint,
                "next_node": next_node,
                "payload": payload or {},
            })
            if row and row["status"] == "validated" and (
                row["authority_sha256"] != authority_sha256
                or row["output_sha256"] != output_sha256
            ):
                raise ValueError("validated workflow checkpoint conflict")
            if row and checkpoint_stage_rank(
                effective_validation_stage,
            ) < checkpoint_stage_rank(
                row["validation_stage"],
            ) and status not in {"failed", "stale"}:
                raise ValueError("workflow checkpoint validation stage regression")
            connection.execute(
                """INSERT INTO workflow_node_checkpoints
                (run_id, node_key, authority_sha256, input_sha256, output_sha256,
                 status, checkpoint_version, validation_stage, attempt,
                 route_fingerprint, next_node, payload_json,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(run_id, node_key, input_sha256) DO UPDATE SET
                authority_sha256=excluded.authority_sha256,
                output_sha256=excluded.output_sha256,
                status=excluded.status,
                checkpoint_version=excluded.checkpoint_version,
                validation_stage=excluded.validation_stage,
                attempt=excluded.attempt,
                route_fingerprint=excluded.route_fingerprint,
                next_node=excluded.next_node,
                payload_json=excluded.payload_json,
                updated_at=datetime('now')""",
                (
                    run_id, node_key, authority_sha256, input_sha256,
                    output_sha256, status, envelope.version,
                    envelope.validation_stage.value, attempt, route_fingerprint,
                    next_node, json.dumps(payload or {}, ensure_ascii=False),
                ),
            )
        return envelope.model_dump(mode="json")

    def load_workflow_node_checkpoint(
        self, *, run_id: str, node_key: str, authority_sha256: str,
        input_sha256: str, statuses: tuple[str, ...] = ("validated",),
        min_validation_stage: str = "promoted",
    ) -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in statuses)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_node_checkpoints "
                "WHERE run_id=? AND node_key=? AND authority_sha256=? "
                "AND input_sha256=? AND status IN (" + placeholders + ")",
                (run_id, node_key, authority_sha256, input_sha256, *statuses),
            ).fetchone()
        if row is None:
            return None
        from novel_flywheel.workflow_state import checkpoint_stage_rank
        if checkpoint_stage_rank(row["validation_stage"]) < checkpoint_stage_rank(
            min_validation_stage,
        ):
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

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

    @staticmethod
    def _incident_metadata(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        classified = classify_production_failure(
            str(row["message"] or ""),
            workflow=str(row["workflow"] or ""),
            stage=str(row["stage"] or row["current_stage"] or ""),
        )
        if metadata.get("incident_key") and metadata.get("incident_family"):
            # Early versions grouped every context preflight under one family.
            # Refine only when the original terminal evidence proves that the
            # event-owned recovery had already reached an indivisible scope.
            # This is a read-time compatibility upgrade; historical rows and
            # their occurrence timestamps remain untouched.
            if (
                metadata.get("incident_family")
                == "model.context_capacity_preflight"
                and classified.get("incident_family")
                == "model.context_capacity_indivisible_scope"
            ):
                return {**metadata, **classified}
            # Older runs may already carry an opaque ``unclassified.*``
            # fingerprint.  Reclassify that evidence at read time when the
            # shared catalog now knows its stable mechanism, retaining the
            # old identity for audit without rewriting historical rows.
            if (
                str(metadata.get("incident_family") or "").startswith("unclassified.")
                and classified.get("incident_family")
                and not str(classified["incident_family"]).startswith("unclassified.")
            ):
                return {
                    **metadata,
                    **classified,
                    "legacy_incident_key": metadata.get("incident_key"),
                    "legacy_incident_family": metadata.get("incident_family"),
                }
            return metadata
        return {**metadata, **classified}

    def record_run_failure(
        self, run_id: str, event_type: str, message: str, *,
        stage: str | None, incident: dict[str, str],
    ) -> dict[str, Any]:
        """Atomically record one terminal failure and its recurrence metadata."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT e.run_id, e.metadata_json, e.message, e.stage, e.created_at, "
                "r.workflow, r.current_stage "
                "FROM run_events e JOIN runs r ON r.id=e.run_id "
                "WHERE e.severity='error' "
                "AND e.event_type IN ('failed', 'short_revision_failed') "
                "ORDER BY e.id",
            ).fetchall()
            legacy_rows = connection.execute(
                "SELECT r.id AS run_id, COALESCE(e.message, r.error) AS message, "
                "COALESCE(e.stage, r.current_stage) AS stage, "
                "COALESCE(e.metadata_json, '{}') AS metadata_json, "
                "r.updated_at AS created_at, r.workflow, r.current_stage "
                "FROM runs r LEFT JOIN run_events e ON e.id=("
                "SELECT MAX(le.id) FROM run_events le "
                "WHERE le.run_id=r.id AND le.severity='error') "
                "WHERE r.status='failed' AND r.error IS NOT NULL AND r.id<>? "
                "AND NOT EXISTS (SELECT 1 FROM run_events terminal "
                "WHERE terminal.run_id=r.id AND terminal.severity='error' "
                "AND terminal.event_type IN ('failed', 'short_revision_failed')) "
                "ORDER BY r.updated_at",
                (run_id,),
            ).fetchall()
            rows = sorted(
                [*legacy_rows, *rows],
                key=lambda row: (row["created_at"], row["run_id"]),
            )
            same_key = []
            same_family = []
            for row in rows:
                metadata = self._incident_metadata(row)
                if metadata.get("incident_key") == incident["incident_key"]:
                    same_key.append(row)
                if metadata.get("incident_family") == incident["incident_family"]:
                    same_family.append(row)
            now = connection.execute("SELECT datetime('now')").fetchone()[0]
            first_seen = same_key[0]["created_at"] if same_key else now
            metadata: dict[str, Any] = {
                **incident,
                "occurrence_count": len(same_key) + 1,
                "family_occurrence_count": len(same_family) + 1,
                "first_seen_at": first_seen,
                "last_seen_at": now,
            }
            if same_key or same_family:
                recognized_scope = (
                    "同一流程阶段"
                    if same_key else "其他流程阶段"
                )
                connection.execute(
                    "INSERT INTO run_events(run_id, severity, event_type, stage, message, "
                    "metadata_json, created_at) VALUES (?, 'warning', "
                    "'production_incident_recognized', ?, ?, ?, datetime('now'))",
                    (
                        run_id, stage,
                        f"已识别为历史同类问题（{recognized_scope}）："
                        f"{incident['incident_title']}。"
                        f"已知处置：{incident['known_resolution']}",
                        json.dumps(metadata, ensure_ascii=False),
                    ),
                )
            connection.execute(
                "INSERT INTO run_events(run_id, severity, event_type, stage, message, "
                "metadata_json, created_at) VALUES (?, 'error', ?, ?, ?, ?, datetime('now'))",
                (
                    run_id, event_type, stage, message,
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
        return metadata

    def list_production_incidents(
        self, project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Aggregate new and legacy terminal failure events by stable incident key."""
        where = (
            "AND r.project_id=?" if project_id is not None else ""
        )
        arguments: tuple[Any, ...] = (project_id,) if project_id is not None else ()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT e.run_id, e.message, e.stage, e.metadata_json, e.created_at, "
                "r.project_id, r.workflow, r.current_stage "
                "FROM run_events e JOIN runs r ON r.id=e.run_id "
                "WHERE e.severity='error' "
                "AND e.event_type IN ('failed', 'short_revision_failed') "
                f"{where} ORDER BY e.id",
                arguments,
            ).fetchall()
            legacy_rows = connection.execute(
                "SELECT r.id AS run_id, COALESCE(e.message, r.error) AS message, "
                "COALESCE(e.stage, r.current_stage) AS stage, "
                "COALESCE(e.metadata_json, '{}') AS metadata_json, "
                "r.updated_at AS created_at, r.project_id, r.workflow, r.current_stage "
                "FROM runs r LEFT JOIN run_events e ON e.id=("
                "SELECT MAX(le.id) FROM run_events le "
                "WHERE le.run_id=r.id AND le.severity='error') "
                "WHERE r.status='failed' AND r.error IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM run_events terminal "
                "WHERE terminal.run_id=r.id AND terminal.severity='error' "
                "AND terminal.event_type IN ('failed', 'short_revision_failed')) "
                f"{where} ORDER BY r.updated_at",
                arguments,
            ).fetchall()
        rows = sorted(
            [*legacy_rows, *rows],
            key=lambda row: (row["created_at"], row["run_id"]),
        )
        grouped: dict[str, dict[str, Any]] = {}
        family_counts: dict[str, int] = {}
        for row in rows:
            metadata = self._incident_metadata(row)
            key = str(metadata["incident_key"])
            family = str(metadata["incident_family"])
            family_counts[family] = family_counts.get(family, 0) + 1
            item = grouped.setdefault(key, {
                "incident_key": key,
                "incident_family": family,
                "incident_title": metadata.get("incident_title", "生产失败"),
                "known_resolution": metadata.get("known_resolution", ""),
                "occurrence_count": 0,
                "first_seen_at": row["created_at"],
                "last_seen_at": row["created_at"],
                "latest_run_id": row["run_id"],
                "latest_project_id": row["project_id"],
                "latest_workflow": row["workflow"],
                "latest_stage": row["stage"] or row["current_stage"],
                "latest_message": row["message"],
            })
            item["occurrence_count"] += 1
            item["last_seen_at"] = row["created_at"]
            item["latest_run_id"] = row["run_id"]
            item["latest_project_id"] = row["project_id"]
            item["latest_workflow"] = row["workflow"]
            item["latest_stage"] = row["stage"] or row["current_stage"]
            item["latest_message"] = row["message"]
        for item in grouped.values():
            item["family_occurrence_count"] = family_counts[item["incident_family"]]
        return sorted(
            grouped.values(), key=lambda item: (item["last_seen_at"], item["incident_key"]),
            reverse=True,
        )

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

    def save_model_output_observation(
        self, *, provider_id: str, model_id: str, route_fingerprint: str,
        execution_mode: str, requested_max_output_tokens: int | None,
        actual_output_tokens: int, visible_characters: int,
        finish_reason: str | None, transport_complete: bool,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO model_output_observations("
                "provider_id, model_id, route_fingerprint, execution_mode, "
                "requested_max_output_tokens, actual_output_tokens, visible_characters, "
                "finish_reason, transport_complete, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (
                    provider_id, model_id, route_fingerprint, execution_mode,
                    requested_max_output_tokens, max(0, int(actual_output_tokens)),
                    max(0, int(visible_characters)), finish_reason,
                    int(transport_complete),
                ),
            )

    def model_output_profile(
        self, provider_id: str, model_id: str, route_fingerprint: str,
        execution_mode: str, limit: int = 20,
    ) -> dict[str, Any]:
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT * FROM model_output_observations "
                "WHERE provider_id=? AND model_id=? AND route_fingerprint=? "
                "AND execution_mode=? ORDER BY id DESC LIMIT ?",
                (provider_id, model_id, route_fingerprint, execution_mode, limit),
            )]
        hidden_limits = sorted(
            int(row["actual_output_tokens"])
            for row in rows
            if row.get("finish_reason") == "max_tokens"
            and row.get("transport_complete")
            and isinstance(row.get("requested_max_output_tokens"), int)
            and int(row["actual_output_tokens"]) > 0
            and int(row["actual_output_tokens"]) < int(row["requested_max_output_tokens"]) * 0.8
        )
        stable_limit = None
        if len(hidden_limits) >= 2 and hidden_limits[-1] <= hidden_limits[0] * 1.2:
            stable_limit = max(512, int(hidden_limits[-1] * 1.1))
        ratios = sorted(
            row["visible_characters"] / row["actual_output_tokens"]
            for row in rows
            if row["visible_characters"] > 0 and row["actual_output_tokens"] > 0
        )
        return {
            "samples": len(rows),
            "observed_output_high_water": max(
                (int(row["actual_output_tokens"]) for row in rows), default=0,
            ),
            "accepted_request_high_water": max(
                (
                    int(row["requested_max_output_tokens"])
                    for row in rows
                    if isinstance(row.get("requested_max_output_tokens"), int)
                    and row.get("transport_complete")
                ),
                default=0,
            ),
            "suspected_stable_output_tokens": stable_limit,
            "conservative_visible_characters_per_token": (
                ratios[max(0, len(ratios) // 10 - 1)] if ratios else None
            ),
        }

    def latest_model_output_profile(
        self, provider_id: str, model_id: str, execution_mode: str = "plain",
    ) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT route_fingerprint FROM model_output_observations "
                "WHERE provider_id=? AND model_id=? AND execution_mode=? "
                "ORDER BY id DESC LIMIT 1",
                (provider_id, model_id, execution_mode),
            ).fetchone()
        if row is None:
            return {"samples": 0, "suspected_stable_output_tokens": None}
        return self.model_output_profile(
            provider_id, model_id, str(row["route_fingerprint"]), execution_mode,
        )

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
