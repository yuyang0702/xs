import json
import sqlite3

from novel_flywheel.db import Database
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.reference_policy import reference_usage


def library(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    return db, ReferenceLibrary(db, tmp_path / "references")


def test_import_records_inferred_and_user_confirmed_classification(tmp_path) -> None:
    _db, references = library(tmp_path)

    inferred = references.import_text(
        title="知乎高赞故事", text="热门回答正文。", source_type="paste",
    )
    confirmed = references.import_text(
        title="写作样本", text="另一份正文。", source_type="paste",
        platform="知乎", content_type="reference_work",
    )

    assert inferred["classification"]["trust"] == "inferred"
    assert inferred["classification"]["confidence"] > 0.5
    assert inferred["classification"]["reasons"]
    assert confirmed["classification"]["trust"] == "user_confirmed"
    assert confirmed["classification"]["platform"] == "知乎"


def test_metadata_save_marks_classification_user_confirmed(tmp_path) -> None:
    _db, references = library(tmp_path)
    source = references.import_text(title="普通故事", text="故事正文。", source_type="paste")

    updated = references.update_metadata(
        source["id"], platform="知乎", content_type="competitor_work", project_id=None,
    )

    assert updated["classification"]["trust"] == "user_confirmed"
    assert updated["classification"]["content_type"] == "competitor_work"


def test_reference_usage_separates_self_described_and_verified_popular_samples() -> None:
    source = {
        "content_type": "popular_sample", "platform": "知乎",
        "classification": {"trust": "inferred", "confidence": 0.8, "reasons": ["标题写有高赞"]},
    }

    unverified = reference_usage(source, None)
    verified = reference_usage(source, {"status": "confirmed", "title": "榜单作品"})

    assert unverified["trust"] == "self_described"
    assert "真实市场统计" in unverified["excluded"]
    assert verified["trust"] == "market_verified"
    assert "市场趋势参考" in verified["allowed"]


def test_competitor_and_platform_rules_have_safe_usage_boundaries() -> None:
    competitor = reference_usage({"content_type": "competitor_work", "classification": {}}, None)
    rules = reference_usage({"content_type": "platform_rule", "classification": {}}, None)

    assert "原创风险比较" in competitor["allowed"]
    assert "文笔学习" in competitor["excluded"]
    assert "投稿规则检查" in rules["allowed"]
    assert "文笔学习" in rules["excluded"]


def test_reference_classification_column_migration_is_idempotent(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE projects(id TEXT PRIMARY KEY,title TEXT,mode TEXT,path TEXT,created_at TEXT)")
    connection.execute("""CREATE TABLE reference_sources(
        id TEXT PRIMARY KEY,title TEXT,source_type TEXT,source_uri TEXT,platform TEXT,
        content_type TEXT,project_id TEXT,status TEXT,created_at TEXT,updated_at TEXT)""")
    connection.execute("INSERT INTO reference_sources VALUES ('r','旧资料','txt',NULL,'知乎','reference_work',NULL,'active','now','now')")
    connection.commit()
    connection.close()

    db = Database(path)
    db.migrate()
    db.migrate()

    with db.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(reference_sources)")}
        snapshot = json.loads(connection.execute(
            "SELECT classification_json FROM reference_sources WHERE id='r'",
        ).fetchone()[0])
    assert "classification_json" in columns
    assert snapshot["trust"] == "legacy"
