import hashlib

from novel_flywheel.narrative_ledger import build_narrative_ledger


def test_ledger_links_explicit_question_to_later_answer() -> None:
    text = "朋友为什么主动赴死？\n\n我找到被烧毁的信，继续调查。\n\n真相是，他为了封印灾难才选择死亡。"

    ledger = build_narrative_ledger(text)

    assert ledger["text_hash"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert ledger["questions"][0]["status"] == "linked"
    relation = ledger["relations"][0]
    assert relation["kind"] == "question_answer"
    assert relation["from_start"] == 0
    assert relation["to_start"] > relation["from_start"]


def test_ledger_tracks_setup_payoff_and_scene_state_changes() -> None:
    text = (
        "他发现桌上有一张烧焦的照片，却认不出照片里的人。\n\n"
        "调查失败后，他决定冒险举行复活仪式。\n\n"
        "照片上的真相终于揭晓：被抹去的人正是他自己。"
    )

    ledger = build_narrative_ledger(text)

    assert any(item["kind"] == "setup_payoff" for item in ledger["relations"])
    assert len(ledger["scenes"]) == 3
    changed = [item for item in ledger["scenes"] if item["state_changes"]]
    assert changed
    assert any("决定" in change["evidence"] for item in changed for change in item["state_changes"])


def test_ledger_marks_important_unresolved_promise_for_review() -> None:
    text = "我一定会让死去的朋友回来。\n\n仪式开始了，但故事在这里结束。"

    ledger = build_narrative_ledger(text)

    assert ledger["promises"][0]["status"] == "unresolved"
    assert ledger["important_uncertainties"][0]["requires_model_review"] is True


def test_stable_unit_relation_ids_survive_unrelated_prefix_insertion() -> None:
    body = "朋友为什么主动赴死？\n\n真相是，他为了封印灾难才选择死亡。"
    before = build_narrative_ledger(body)
    after = build_narrative_ledger("无关开场。\n\n" + body)

    assert before["questions"][0]["id"] == after["questions"][0]["id"]
    assert before["relations"][0]["id"] == after["relations"][0]["id"]
    assert before["relations"][0]["from_start"] != after["relations"][0]["from_start"]


def test_ledger_evidence_records_source_confidence_and_unit_id() -> None:
    text = (
        "朋友为什么主动赴死？\n\n"
        "我一定会让银锁回到林晚手里。\n\n"
        "桌上有一把异常的银锁。\n\n"
        "银锁的真相终于揭晓。"
    )

    ledger = build_narrative_ledger(text)

    evidence = [
        *ledger["questions"], *ledger["promises"], *ledger["setups"],
    ]
    assert evidence
    assert all(item["source"] == "rules" for item in evidence)
    assert all(0 <= item["confidence"] <= 1 for item in evidence)
    assert all(item["unit_id"] for item in evidence)
    assert all(item["end"] > item["start"] for item in evidence)
    assert ledger["relations"]
    assert all(relation["from_unit_id"] for relation in ledger["relations"])
    assert all(relation["to_unit_id"] for relation in ledger["relations"])
