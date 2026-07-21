import json
import re

from novel_flywheel.db import Database


class StoryMemory:
    def __init__(self, db: Database) -> None:
        self.db = db

    def index_chapter(self, project_id: str, chapter_id: str, chapter_number: int,
                      content: str, summary: str) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "DELETE FROM chapter_search WHERE project_id = ? AND chapter_id = ?",
                (project_id, chapter_id),
            )
            connection.execute(
                "INSERT INTO chapter_search VALUES (?, ?, ?, ?, ?)",
                (project_id, chapter_id, chapter_number, content, summary),
            )

    def add_fact(self, project_id: str, fact_key: str, value: str,
                 confirmed: bool, source: str) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO canon_facts VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (project_id, fact_key, value, source, int(confirmed)),
            )

    def save_state(self, project_id: str, chapter_id: str, state: dict) -> None:
        with self.db.connect() as connection:
            connection.execute(
                """INSERT INTO chapter_states VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(project_id, chapter_id) DO UPDATE SET
                state_json=excluded.state_json, created_at=excluded.created_at""",
                (project_id, chapter_id, json.dumps(state, ensure_ascii=False)),
            )

    def record_drift(self, project_id: str, category: str, score: int, message: str) -> None:
        if not 0 <= score <= 100:
            raise ValueError("Drift score must be between 0 and 100")
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO drift_findings(project_id, category, score, message, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (project_id, category, score, message),
            )

    def context(self, project_id: str, query: str, limit: int = 6) -> dict:
        with self.db.connect() as connection:
            facts = [dict(row) for row in connection.execute(
                "SELECT fact_key, value, source FROM canon_facts "
                "WHERE project_id = ? AND confirmed = 1 ORDER BY created_at, rowid",
                (project_id,),
            )]
            state_row = connection.execute(
                "SELECT state_json FROM chapter_states WHERE project_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            drift = [dict(row) for row in connection.execute(
                "SELECT category, score, message FROM drift_findings "
                "WHERE project_id = ? AND resolved = 0 ORDER BY score DESC, id DESC",
                (project_id,),
            )]
            terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
            relevant = []
            if terms:
                match = " OR ".join(f'"{term}"' for term in terms)
                relevant = [dict(row) for row in connection.execute(
                    "SELECT chapter_id, CAST(chapter_number AS INTEGER) AS chapter_number, summary, "
                    "snippet(chapter_search, 3, '', '', ' ... ', 32) AS excerpt "
                    "FROM chapter_search WHERE project_id = ? AND chapter_search MATCH ? "
                    "ORDER BY bm25(chapter_search) LIMIT ?",
                    (project_id, match, limit),
                )]
        return {
            "canon": facts,
            "recent_state": json.loads(state_row[0]) if state_row else {},
            "relevant_chapters": relevant,
            "drift": drift,
        }

    def search_chapters(self, project_id: str, query: str, limit: int = 6) -> list[dict]:
        return self.context(project_id, query, min(max(limit, 1), 10))["relevant_chapters"]
