from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novel_flywheel.db import Database
from novel_flywheel.narrative_ir import migrate_narrative_graph
from novel_flywheel.narrative_rules import validate_narrative_graph


STORY_STATE_SCHEMA = 3
AUTHORITATIVE_FACT_FIELDS = (
    "locked_facts",
    "confirmed_facts",
    "world_rules",
    "character_states",
    "timeline_events",
    "narrative_graph",
    "narrative_rule_profile",
)


def migrate_story_state_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return the additive, idempotent schema-v3 StoryState representation."""
    migrated = copy.deepcopy(data)
    migrated["story_state_schema"] = STORY_STATE_SCHEMA
    migrated["narrative_graph"] = migrate_narrative_graph(
        migrated.get("narrative_graph"),
    )
    profile = migrated.get("narrative_rule_profile")
    if not isinstance(profile, dict):
        profile = {}
    migrated["narrative_rule_profile"] = {
        "version": 1,
        "genres": list(dict.fromkeys(
            str(item or "").strip() for item in profile.get("genres", [])
            if str(item or "").strip()
        )),
        "project_rules": list(dict.fromkeys(
            str(item or "").strip() for item in profile.get("project_rules", [])
            if str(item or "").strip()
        )),
    }
    return migrated


def authoritative_fact_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy({key: state.get(key) for key in AUTHORITATIVE_FACT_FIELDS})


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
            if (int(current.data.get("story_state_schema", 0)) >= STORY_STATE_SCHEMA
                    and current.revision > 1):
                return current
            imported = self._import(project_path)
            missing = {
                key: imported[key]
                for key in (
                    "locked_facts", "confirmed_facts", "world_rules",
                    "character_states", "timeline_events", "narrative_rule_profile",
                )
                if not current.data.get(key) and imported.get(key)
            }
            data = migrate_story_state_data({**current.data, **missing})
            if data != current.data:
                serialized = json.dumps(data, ensure_ascii=False)
                with self.db.connect() as connection:
                    connection.execute(
                        "UPDATE story_states SET state_json=?, updated_at=datetime('now') "
                        "WHERE project_id=? AND revision=?",
                        (serialized, project_id, current.revision),
                    )
                    connection.execute(
                        "UPDATE story_state_history SET state_json=? "
                        "WHERE project_id=? AND revision=?",
                        (serialized, project_id, current.revision),
                    )
                return self.get(project_id) or current
            return current
        data = migrate_story_state_data(self._import(project_path))
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

    def list_candidates(self, project_id: str, *, kind: str | None = None,
                        status: str | None = None) -> list[StoryCandidate]:
        query = "SELECT id FROM story_candidates WHERE project_id=?"
        params: list[Any] = [project_id]
        if kind is not None:
            query += " AND kind=?"
            params.append(kind)
        if status is not None:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY created_at DESC, rowid DESC"
        with self.db.connect() as connection:
            ids = [row["id"] for row in connection.execute(query, params)]
        return [candidate for candidate_id in ids
                if (candidate := self.get_candidate(candidate_id)) is not None]

    def update_candidate(self, candidate_id: str, *, content_hash: str,
                         metadata: dict[str, Any]) -> StoryCandidate:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("Candidate not found")
        if candidate.status != "pending":
            raise ValueError("Candidate is already resolved")
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE story_candidates SET content_hash=?, metadata_json=? "
                "WHERE id=? AND status='pending'",
                (content_hash, json.dumps(metadata, ensure_ascii=False), candidate_id),
            )
        updated = self.get_candidate(candidate_id)
        if updated is None:
            raise RuntimeError("Updated candidate is unavailable")
        return updated

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
        graph = migrate_narrative_graph(data.get("narrative_graph"))
        profile = data.get("narrative_rule_profile")
        genres = profile.get("genres", []) if isinstance(profile, dict) else []
        graph_findings = validate_narrative_graph(graph, genres=genres)
        hard_findings = [item for item in graph_findings if item.severity == "hard"]
        if hard_findings:
            self.reject(candidate_id, "narrative fact graph validation failed")
            raise ValueError(
                "narrative fact graph validation failed: "
                + "; ".join(item.code for item in hard_findings)
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
            if isinstance(fact, dict):
                key = str(fact.get("fact_key") or fact.get("subject") or f"legacy.{index}")
                value = fact.get("value", fact.get("fact", ""))
            elif isinstance(fact, str):
                key, value = f"legacy.{index}", fact
            else:
                continue
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
        world_rules = canon.get("world_rules", [])
        if not world_rules and isinstance(requirements, dict) and requirements.get("world.rules"):
            world_rules = [requirements["world.rules"]]
        manuscript = project_path / "manuscript" / "story.md"
        character_states = canon.get("state") or StoryStateStore._character_states(project_path)
        timeline = canon.get("timeline") or StoryStateStore._timeline(project_path)
        return {
            "story_state_schema": STORY_STATE_SCHEMA,
            "locked_facts": list(locked.values()),
            "confirmed_facts": facts,
            "provisional_facts": [],
            "world_rules": world_rules,
            "character_states": character_states,
            "timeline_events": timeline,
            "narrative_graph": migrate_narrative_graph(None),
            "narrative_rule_profile": {
                "version": 1,
                "genres": [str(metadata.get("genre") or "").strip()]
                if str(metadata.get("genre") or "").strip() else [],
                "project_rules": [],
            },
            "issue_ledger": [],
            "manuscript_revision": 1 if manuscript.is_file() and manuscript.stat().st_size else 0,
        }

    @staticmethod
    def _character_states(project_path: Path) -> dict[str, Any]:
        path = project_path / "continuity" / "state.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return {}
        states: dict[str, Any] = {}
        frontmatter = text.split("---", 2)[1] if text.startswith("---") and text.count("---") >= 2 else ""
        block = re.search(r"(?ms)^character-state:\s*\n(?P<body>(?:^[ \t].*\n?)*)", frontmatter)
        if block:
            current: dict[str, str] | None = None
            for line in block.group("body").splitlines():
                item = re.match(r"\s*-\s+name:\s*(.+)", line)
                field = re.match(r"\s+([\w-]+):\s*(.+)", line)
                if item:
                    current = {}
                    states[item.group(1).strip()] = current
                elif current is not None and field:
                    current[field.group(1).replace("-", "_")] = field.group(2).strip()
        body = text.split("---", 2)[2] if text.startswith("---") and text.count("---") >= 2 else text
        for name, value in re.findall(r"(?m)^-\s*([^:：|]+)[：:]\s*(.+)$", body):
            states.setdefault(name.strip(), {"state": value.strip()})
        for profile in (project_path / "characters").glob("*.md"):
            if profile.name == "_index.md":
                continue
            try:
                profile_text = profile.read_text(encoding="utf-8")
            except OSError:
                continue
            frontmatter = (
                profile_text.split("---", 2)[1]
                if profile_text.startswith("---") and profile_text.count("---") >= 2
                else ""
            )
            fields = {
                key: value.strip().strip('"\'')
                for key, value in re.findall(
                    r"(?m)^(name|role|status|arc):\s*(.+)$", frontmatter,
                )
            }
            name = fields.pop("name", "")
            if name:
                states.setdefault(name, fields)
        return states

    @staticmethod
    def _timeline(project_path: Path) -> list[dict[str, str]]:
        path = project_path / "plot" / "timeline.md"
        try:
            rows = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip().startswith("|")]
        except OSError:
            return []
        if len(rows) < 3:
            return []
        cells = lambda row: [value.strip() for value in row.strip("|").split("|")]
        headers = cells(rows[0])
        return [dict(zip(headers, values)) for row in rows[2:]
                if len(values := cells(row)) == len(headers)
                and not all(set(value) <= {"-", ":"} for value in values)]
