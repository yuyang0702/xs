import sqlite3

from novel_flywheel.db import Database


def test_market_migration_is_idempotent_and_preserves_references(tmp_path) -> None:
    path = tmp_path / "app.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE reference_sources(
          id TEXT PRIMARY KEY, title TEXT NOT NULL, source_type TEXT NOT NULL,
          source_uri TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        INSERT INTO reference_sources VALUES(
          'ref-1', '旧资料', 'txt', 'old.txt', 'active', datetime('now'), datetime('now')
        );
        """
    )
    connection.close()

    db = Database(path)
    db.migrate()
    db.migrate()

    assert {"market_sources", "market_snapshots", "market_works", "market_entries",
            "reference_market_links"} <= db.table_names()
    assert db.get_reference_source("ref-1")["title"] == "旧资料"

