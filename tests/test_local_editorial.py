from novel_flywheel.local_editorial import analyze_prose
from novel_flywheel.prose_quality import prose_metrics


def finding_ids(text: str) -> set[str]:
    return {item["rule_id"] for item in analyze_prose(text)["findings"]}


def test_editorial_and_polish_metrics_share_sentence_boundaries() -> None:
    text = "她推开门。屋里没人！\n\n“你来了？”他问。"

    editorial = analyze_prose(text)["metrics"]
    polish = prose_metrics(text)

    assert editorial["sentence_count"] == 4
    assert polish.get("sentence_count") == editorial["sentence_count"]


def test_detects_checklist_judgment_with_exact_evidence_offsets() -> None:
    text = "血是暗红色，静脉血。插得不深，没伤到大动脉。刀还不能拔。"

    report = analyze_prose(text)
    finding = next(item for item in report["findings"] if item["rule_id"] == "checklist_judgment")

    assert finding["severity"] == "review"
    assert text[finding["start"]:finding["end"]] == finding["evidence"]


def test_detects_functional_repetition_across_neighboring_paragraphs() -> None:
    text = "他沉默了一会儿。\n\n她沉默了很久。\n\n两人都没有说话。"

    assert "functional_repetition" in finding_ids(text)


def test_detects_exact_phrase_reuse_and_mechanical_dialogue() -> None:
    text = (
        "“你是谁？”\n\n“我不知道。”\n\n“你从哪来？”\n\n“我不知道。”\n\n"
        "她转身看向门外，夜色已经沉了下来。夜色已经沉了下来。"
    )

    ids = finding_ids(text)
    assert "mechanical_dialogue_run" in ids
    assert "repeated_phrase" in ids


def test_changed_loop_anchor_is_marked_as_intentional_candidate() -> None:
    text = (
        "第一轮，电梯门在十二点打开，他死了。\n\n"
        "第二轮，电梯门在十二点打开，但死者换了位置。"
    )
    finding = next(item for item in analyze_prose(text)["findings"] if item["rule_id"] == "repeated_phrase")
    assert finding["intentional_repetition_candidate"] is True
    assert "叙事作用" in finding["repair_goal"]


def test_unchanged_duplicate_remains_plain_review() -> None:
    text = "夜色已经沉了下来。夜色已经沉了下来。"
    finding = next(item for item in analyze_prose(text)["findings"] if item["rule_id"] == "repeated_phrase")
    assert finding["intentional_repetition_candidate"] is False


def test_detects_unusually_regular_sentence_lengths() -> None:
    text = "他推开门走进去。她抬起头看着他。风从窗外吹进来。灯在桌上轻轻晃。"

    assert "regular_sentence_rhythm" in finding_ids(text)


def test_mixed_scene_prose_has_no_blocking_findings() -> None:
    text = (
        "雨敲在窗上，林知晚翻过半页账册，忽然停住。\n\n"
        "“这个数是谁改的？”她没有抬头，只用指腹压住那道新墨。\n\n"
        "管事张了张嘴。院外有人跑过，湿鞋踩得石阶一阵乱响。"
    )

    report = analyze_prose(text)
    assert not [item for item in report["findings"] if item["severity"] == "blocking"]
    assert report["metrics"]["sentence_count"] >= 4
    assert report["analyzer"] == "local-editorial"


def test_detects_project_forbidden_pattern_and_unsupported_certainty() -> None:
    text = "她很确定，门外的人一定就是凶手。她心头一紧。"
    ids = finding_ids(text)
    assert "unsupported_certainty" in ids
    report = analyze_prose(text, {"forbidden_patterns": ["心头一紧"]})
    assert any(item["rule_id"] == "project_forbidden_pattern" and item["severity"] == "blocking"
               for item in report["findings"])


def test_detects_repeated_body_reaction() -> None:
    report = analyze_prose("她皱了皱眉。\n\n他皱了皱眉。\n\n她又皱了皱眉。")
    assert any(item["rule_id"] == "repeated_body_reaction" for item in report["findings"])
