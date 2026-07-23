from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novel_flywheel.db import Database


def validate_locked_facts(source: str, candidate: str,
                          state: dict[str, Any]) -> list[str]:
    failures = []
    for item in state.get("locked_facts", []):
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if (isinstance(value, str) and 1 < len(value) <= 160
                and value in source and value not in candidate):
            failures.append(f"locked fact removed: {item.get('key', 'unknown')}")
    return failures


class StaleStoryState(RuntimeError):
    pass


@dataclass(frozen=True)
class StoryState:
    project_id: str
    revision: int
    data: dict[str, Any]


@dataclass(frozen=True)
class StoryCandidate:
    id: str
    project_id: str
    run_id: str | None
    base_revision: int
    kind: str
    content_hash: str
    status: str
    reason: str | None
    metadata: dict[str, Any]


class StoryStateStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, project_id: str) -> StoryState | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT project_id, revision, state_json FROM story_states WHERE project_id=?",
                (project_id,),
            ).fetchone()
        return self._state(row) if row else None

    def ensure(self, project_id: str, project_path: Path) -> StoryState:
        current = self.get(project_id)
        if current:
            imported = self._import(project_path)
            if (current.revision == 1 and not current.data.get("locked_facts")
                    and imported.get("locked_facts")):
                data = {**current.data, "locked_facts": imported["locked_facts"]}
                serialized = json.dumps(data, ensure_ascii=False)
                with self.db.connect() as connection:
                    connection.execute(
                        "UPDATE story_states SET state_json=?, updated_at=datetime('now') "
                        "WHERE project_id=? AND revision=1",
                        (serialized, project_id),
                    )
                    connection.execute(
                        "UPDATE story_state_history SET state_json=? "
                        "WHERE project_id=? AND revision=1",
                        (serialized, project_id),
                    )
                return self.get(project_id) or current
            return current
        data = self._import(project_path)
        with self.db.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO story_states VALUES (?, 1, ?, datetime('now'), datetime('now'))",
                (project_id, json.dumps(data, ensure_ascii=False)),
            )
            connection.execute(
                "INSERT OR IGNORE INTO story_state_history VALUES (?, 1, ?, 'migration', datetime('now'))",
                (project_id, json.dumps(data, ensure_ascii=False)),
            )
        state = self.get(project_id)
        if state is None:
            raise RuntimeError("StoryState initialization failed")
        return state

    def create_candidate(self, project_id: str, run_id: str | None, base_revision: int,
                         kind: str, content_hash: str,
                         metadata: dict[str, Any] | None = None) -> StoryCandidate:
        candidate_id = uuid.uuid4().hex
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO story_candidates VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, ?, datetime('now'), NULL)",
                (candidate_id, project_id, run_id, base_revision, kind, content_hash,
                 json.dumps(metadata or {}, ensure_ascii=False)),
            )
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise RuntimeError("Candidate creation failed")
        return candidate

    def get_candidate(self, candidate_id: str) -> StoryCandidate | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM story_candidates WHERE id=?", (candidate_id,),
            ).fetchone()
        if not row:
            return None
        return StoryCandidate(
            row["id"], row["project_id"], row["run_id"], row["base_revision"],
            row["kind"], row["content_hash"], row["status"], row["reason"],
            json.loads(row["metadata_json"]),
        )

    def reject(self, candidate_id: str, reason: str) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE story_candidates SET status='rejected', reason=?, resolved_at=datetime('now') "
                "WHERE id=? AND status='pending'",
                (reason, candidate_id),
            )

    def commit(self, candidate_id: str, expected_revision: int,
               data: dict[str, Any]) -> StoryState:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("Candidate not found")
        current = self.get(candidate.project_id)
        if current is None:
            raise LookupError("StoryState not found")
        if candidate.status != "pending":
            raise ValueError("Candidate is already resolved")
        if current.revision != expected_revision or candidate.base_revision != expected_revision:
            self.reject(candidate_id, "stale base revision")
            raise StaleStoryState(
                f"Expected StoryState revision {expected_revision}, found {current.revision}"
            )
        next_revision = expected_revision + 1
        serialized = json.dumps(data, ensure_ascii=False)
        with self.db.connect() as connection:
            cursor = connection.execute(
                "UPDATE story_states SET revision=?, state_json=?, updated_at=datetime('now') "
                "WHERE project_id=? AND revision=?",
                (next_revision, serialized, candidate.project_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise StaleStoryState("StoryState changed during commit")
            connection.execute(
                "INSERT INTO story_state_history VALUES (?, ?, ?, ?, datetime('now'))",
                (candidate.project_id, next_revision, serialized, candidate_id),
            )
            connection.execute(
                "UPDATE story_candidates SET status='accepted', resolved_at=datetime('now') WHERE id=?",
                (candidate_id,),
            )
        state = self.get(candidate.project_id)
        if state is None:
            raise RuntimeError("Committed StoryState is unavailable")
        return state

    def history(self, project_id: str) -> list[StoryState]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT project_id, revision, state_json FROM story_state_history "
                "WHERE project_id=? ORDER BY revision", (project_id,),
            ).fetchall()
        return [self._state(row) for row in rows]

    @staticmethod
    def _state(row) -> StoryState:
        return StoryState(row["project_id"], int(row["revision"]), json.loads(row["state_json"]))

    @staticmethod
    def _import(project_path: Path) -> dict[str, Any]:
        canon_path = project_path / "memory" / "canon.json"
        try:
            canon = json.loads(canon_path.read_text(encoding="utf-8")) if canon_path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            canon = {}
        facts = []
        for index, fact in enumerate(canon.get("facts", [])):
            if not isinstance(fact, dict):
                continue
            key = str(fact.get("fact_key") or fact.get("subject") or f"legacy.{index}")
            value = fact.get("value", fact.get("fact", ""))
            facts.append({"key": key, "value": value, "level": "confirmed", "source": "canon.json"})
        locked: dict[str, dict[str, Any]] = {}
        locks_path = project_path / "continuity" / "locks.json"
        try:
            locks = json.loads(locks_path.read_text(encoding="utf-8")).get("locks", [])
        except (OSError, json.JSONDecodeError):
            locks = []
        for item in locks:
            if isinstance(item, dict) and item.get("key"):
                key = str(item["key"])
                locked[key] = {"key": key, "value": item.get("value"), "source": "locks.json"}
        project_path_json = project_path / "project.json"
        try:
            metadata = json.loads(project_path_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}
        requirements = metadata.get("story_requirements", {})
        lockable = {
            "ending", "must_include", "must_avoid", "protagonist.name",
            "protagonist.arc", "world.rules",
        }
        if isinstance(requirements, dict):
            for key in lockable:
                if key in requirements and requirements[key] not in (None, ""):
                    locked.setdefault(key, {
                        "key": key, "value": requirements[key], "source": "project.json",
                    })
        manuscript = project_path / "manuscript" / "story.md"
        return {
            "locked_facts": list(locked.values()),
            "confirmed_facts": facts,
            "provisional_facts": [],
            "world_rules": canon.get("world_rules", []),
            "character_states": canon.get("state", {}),
            "timeline_events": canon.get("timeline", []),
            "issue_ledger": [],
            "manuscript_revision": 1 if manuscript.is_file() and manuscript.stat().st_size else 0,
        }
