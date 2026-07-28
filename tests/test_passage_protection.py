import pytest

from novel_flywheel.db import Database
from novel_flywheel.passage_protection import (
    PassageProtectionService,
    applicable_passage_locks,
    validate_passage_protections,
)


def service(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    return db, PassageProtectionService(db)


def test_selection_must_cover_complete_consecutive_paragraphs(tmp_path) -> None:
    _db, protections = service(tmp_path)
    text = "第一段完整内容。\n\n第二段完整内容。\n\n第三段完整内容。"

    with pytest.raises(ValueError, match="完整段落"):
        protections.create(
            "project", text, excerpt="一段完整", mode="soft", label="喜欢的开头",
        )

    created = protections.create(
        "project", text,
        excerpt="第一段完整内容。\n\n第二段完整内容。",
        mode="soft", label="喜欢的开头",
    )

    assert created["paragraph_start"] == 1
    assert created["paragraph_end"] == 2
    assert created["active"] is True


def test_soft_allows_punctuation_but_exact_rejects_any_change(tmp_path) -> None:
    db, protections = service(tmp_path)
    source = "他终于说：“我会回来。”\n\n她没有回答。"
    soft = protections.create(
        "project", source, excerpt="他终于说：“我会回来。”", mode="soft",
        label="关键承诺",
    )
    exact = protections.create(
        "project", source, excerpt="她没有回答。", mode="exact",
        label="结尾停顿",
    )
    candidate = '他终于说，"我会回来"。\n\n她回答了。'

    result = validate_passage_protections(
        source, candidate, applicable_passage_locks(db.list_locks("project"), source),
    )

    assert [item["id"] for item in result["conflicts"]] == [
        exact["id"],
    ]
    assert result["conflicts"][0]["message"] == "“结尾停顿”被修改，已保留原文"
    assert soft["id"] not in {
        item["id"] for item in result["conflicts"]
    }


def test_inactive_lock_is_ignored_and_allow_next_change_is_consumed(tmp_path) -> None:
    db, protections = service(tmp_path)
    source = "必须保留这一段。\n\n后续内容。"
    inactive = protections.create(
        "project", source, excerpt="后续内容。", mode="exact", label="后续",
    )
    protections.remove("project", inactive["id"])
    active = protections.create(
        "project", source, excerpt="必须保留这一段。", mode="exact", label="核心",
    )
    protections.allow_next_change("project", active["id"])

    locks = applicable_passage_locks(db.list_locks("project"), source)
    result = validate_passage_protections(source, "这一段允许改一次。\n\n已经改了。", locks)
    protections.consume_allowed_changes("project", result["consumed"])

    assert result["conflicts"] == []
    assert [item["id"] for item in result["consumed"]] == [active["id"]]
    latest = {item["value"]["id"]: item["value"] for item in db.list_locks("project")}
    assert latest[inactive["id"]]["active"] is False
    assert latest[active["id"]]["active"] is False
    assert latest[active["id"]]["status"] == "changed_once"
