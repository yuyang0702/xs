import copy

import pytest

from novel_flywheel.db import Database
from novel_flywheel.passage_protection import (
    PassageProtectionService,
    applicable_passage_locks,
    validate_candidate_protections,
    validate_passage_protections,
)


def service(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    return db, PassageProtectionService(db)


def test_all_active_protections_are_checked_against_complete_candidate(tmp_path) -> None:
    db, protections = service(tmp_path)
    source = "Protected opening.\n\nMiddle.\n\nProtected ending."
    protections.create(
        "project", source, excerpt="Protected opening.", mode="exact", label="opening",
    )
    protections.create(
        "project", source, excerpt="Protected ending.", mode="exact", label="ending",
    )

    result = validate_candidate_protections(
        "Protected opening.\n\nChanged middle.", db.list_locks("project"),
    )

    assert [item["label"] for item in result["conflicts"]] == ["ending"]
    assert result["conflicts"][0]["status"] == "missing"


def test_candidate_protections_classify_exact_and_soft_matches_in_input_order() -> None:
    locks = [
        {"key": "passage.exact-moved", "value": {
            "id": "exact-moved", "label": "exact moved", "mode": "exact",
            "excerpt": "Punctuation, changed!", "normalized_excerpt": "punctuationchanged",
            "paragraph_start": 6, "paragraph_end": 6, "active": True,
        }},
        {"key": "passage.soft", "value": {
            "id": "soft", "label": "soft", "mode": "soft",
            "excerpt": "Keep, this!", "normalized_excerpt": "keepthis",
            "paragraph_start": 1, "paragraph_end": 1, "active": True,
        }},
        {"key": "passage.exact-ambiguous", "value": {
            "id": "exact-ambiguous", "label": "exact ambiguous", "mode": "exact",
            "excerpt": "Exact repeat.", "normalized_excerpt": "exactrepeat",
            "paragraph_start": 3, "paragraph_end": 3, "active": True,
        }},
        {"key": "passage.soft-ambiguous", "value": {
            "id": "soft-ambiguous", "label": "soft ambiguous", "mode": "soft",
            "excerpt": "Repeat this.", "normalized_excerpt": "repeatthis",
            "paragraph_start": 3, "paragraph_end": 3, "active": True,
        }},
        {"key": "passage.soft-missing", "value": {
            "id": "soft-missing", "label": "soft missing", "mode": "soft",
            "excerpt": "Gone forever.", "normalized_excerpt": "goneforever",
            "paragraph_start": 10, "paragraph_end": 10, "active": True,
        }},
        {"key": "passage.soft-mutated", "value": {
            "id": "soft-mutated", "label": "soft mutated", "mode": "soft",
            "excerpt": "Original soft.", "normalized_excerpt": "originalsoft",
            "paragraph_start": 7, "paragraph_end": 7, "active": True,
        }},
    ]
    candidate = (
        "Keep this.\n\nPunctuation changed.\n\nExact repeat.\n\nExact repeat.\n\n"
        "Repeat-this.\n\nRepeat this!\n\nRewritten soft."
    )

    result = validate_candidate_protections(candidate, locks)

    assert [item["status"] for item in result["results"]] == [
        "mutated", "unchanged", "ambiguous", "ambiguous", "missing", "mutated",
    ]
    assert [item["id"] for item in result["conflicts"]] == [
        "exact-moved", "exact-ambiguous", "soft-ambiguous",
        "soft-missing", "soft-mutated",
    ]


def test_candidate_protection_permission_is_reported_without_being_consumed() -> None:
    locks = [
        {"key": "passage.inactive", "value": {
            "id": "inactive", "mode": "exact", "excerpt": "Old text.",
            "normalized_excerpt": "oldtext", "active": False,
            "allow_next_change": False, "status": "changed_once",
        }},
        {"key": "passage.allowed", "value": {
            "id": "allowed", "label": "one change", "mode": "exact",
            "excerpt": "Original text.", "normalized_excerpt": "originaltext",
            "paragraph_start": 1, "paragraph_end": 1, "active": True,
            "allow_next_change": True, "status": "allow_next_change",
        }},
    ]
    before = copy.deepcopy(locks)

    result = validate_candidate_protections("Changed text.", locks)

    assert result["passed"] is True
    assert result["conflicts"] == []
    assert [(item["id"], item["status"]) for item in result["allowed"]] == [
        ("allowed", "mutated"),
    ]
    assert [item["id"] for item in result["results"]] == ["allowed"]
    assert locks == before


def test_candidate_protections_fail_closed_for_empty_legacy_values() -> None:
    locks = [
        {"key": "passage.empty-exact", "value": {
            "id": "empty-exact", "mode": "exact", "excerpt": "",
            "normalized_excerpt": "", "paragraph_end": 1,
            "active": True, "allow_next_change": True,
        }},
        {"key": "passage.empty-soft", "value": {
            "id": "empty-soft", "mode": "soft", "excerpt": "!!!",
            "normalized_excerpt": "", "paragraph_end": 1,
            "active": True, "allow_next_change": True,
        }},
        {"key": "passage.legacy-exact", "value": {
            "id": "legacy-exact", "mode": "exact", "excerpt": "Candidate text.",
            "normalized_excerpt": "", "paragraph_end": 1,
            "active": True, "allow_next_change": True,
        }},
    ]

    result = validate_candidate_protections("Candidate text.", locks)

    assert result["passed"] is False
    assert [(item["id"], item["status"], item["reason"])
            for item in result["conflicts"]] == [
        ("empty-exact", "missing", "empty_excerpt"),
        ("empty-soft", "missing", "empty_normalized_excerpt"),
        ("legacy-exact", "missing", "empty_normalized_excerpt"),
    ]
    assert {item["label"] for item in result["conflicts"]} == {"保护片段"}
    assert result["allowed"] == []


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
