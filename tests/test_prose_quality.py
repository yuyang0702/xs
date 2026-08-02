import pytest

from novel_flywheel.prose_quality import analyze_prose, compare_voice_metrics, prose_metrics


@pytest.mark.parametrize(("text", "expected"), [
    ("她推开门。屋里没有人。灯却亮着。", 3),
    ("“你来了？”她问。\n\n他点头。", 3),
    ("First sentence. Second sentence! Third?", 3),
    ("第一句！）第二句？】第三句。", 3),
    ("第一句。\r\n\r\n第二句。", 2),
])
def test_sentence_metrics_count_common_prose_boundaries(text: str, expected: int) -> None:
    assert prose_metrics(text).get("sentence_count") == expected


def test_multi_sentence_chinese_paragraph_does_not_extend_single_paragraph_run() -> None:
    text = "她停住。风从门缝钻进来。\n\n他回头。\n\n灯灭了。"

    metrics = prose_metrics(text)

    assert metrics.get("sentence_count") == 4
    assert metrics["one_sentence_paragraph_run"] == 2


def test_analyzer_blocks_model_process_text_and_locates_segment() -> None:
    text = "第一段正文。\n\n<!-- NOVEL_FLYWHEEL_SEGMENT -->\n\n以下是本片段的润色版本：\n故事开始。"

    report = analyze_prose(text)

    finding = next(item for item in report["findings"] if item["code"] == "production_text")
    assert finding["blocking"] is True
    assert finding["segment"] == 2
    assert report["blocking_count"] == 1


def test_analyzer_blocks_planning_notes_mixed_script_and_duplicate_paragraphs() -> None:
    repeated = "苏荞把门闩压回原位，又检查了一遍窗纸上的影子，确认院外的人还没有离开。"
    report = analyze_prose(
        f"{repeated}\n\n- **状态变化**：她决定离开。\n\n苏quila转身。\n\n{repeated}"
    )

    codes = {item["code"] for item in report["findings"] if item["blocking"]}
    assert {"production_text", "mixed_script_corruption", "duplicate_paragraph"} <= codes


def test_analyzer_blocks_replacement_glyphs_and_invalid_control_characters() -> None:
    report = analyze_prose("她推开门，纸页上却只剩�个名字。\x00他没有出声。")

    codes = {item["code"] for item in report["findings"] if item["blocking"]}
    assert {"unicode_replacement_character", "invalid_control_character"} <= codes


def test_analyzer_reports_formulaic_explanation_as_soft_signal() -> None:
    text = "这一刻，他终于明白，这不是逃避，而是命运的选择。" * 3

    report = analyze_prose(text)

    assert report["blocking_count"] == 0
    assert report["targeted_count"] > 0
    assert report["naturalness_score"] < 90


def test_analyzer_flags_generic_theme_summary_at_ending() -> None:
    report = analyze_prose("他关上门，走进雨里。\n\n这座城市还在运转，时代仍在向前。")

    assert any(item["code"] == "theme_summary_ending" for item in report["findings"])


def test_clean_specific_prose_keeps_high_naturalness() -> None:
    report = analyze_prose("锅里的水开了。王婶用围裙垫着锅耳，把面汤倒进缺口瓷碗。\n\n门外有人咳了一声，她没抬头。")

    assert report["blocking_count"] == 0
    assert report["naturalness_score"] >= 85


def test_analyzer_flags_four_consecutive_fragment_sentences() -> None:
    report = analyze_prose("门开了。他进去。灯亮了。雨停了。走廊尽头传来脚步声，他停下来侧耳听。")

    assert any(item["code"] == "uniform_short_sentence_run" for item in report["findings"])


def test_short_sentence_metrics_exclude_dialogue_and_headings() -> None:
    report = analyze_prose(
        "# 夜谈\n\n“你没走。”\n\n“我走了你就死了。”\n\n“你也可能死。”\n\n“知道了也不行。”"
    )

    assert report["metrics"]["short_sentence_run"] == 0
    assert report["metrics"]["one_sentence_paragraph_run"] == 0
    assert not any(item["code"] == "uniform_short_sentence_run" for item in report["findings"])
    assert any(item["code"] == "dialogue_ping_pong" for item in report["findings"])


def test_analyzer_flags_timestamp_followed_by_static_scene_fragment() -> None:
    text = (
        "林知晚把最后一份需求文档发出去，看了眼时间——二十三点四十七分。"
        "会议室的白板上还留着下午评审时画的流程图。"
    )

    report = analyze_prose(text)

    assert any(item["code"] == "timestamp_scene_fragment" for item in report["findings"])


def test_analyzer_flags_consecutive_one_sentence_paragraphs() -> None:
    text = (
        "Rain covered the road.\n\n"
        "She missed the light.\n\n"
        "A horn sounded.\n\n"
        "The car crossed the flooded junction."
    )

    report = analyze_prose(text)

    finding = next(
        item for item in report["findings"]
        if item["code"] == "one_sentence_paragraph_run"
    )
    assert finding["count"] == 4
    assert report["metrics"]["one_sentence_paragraph_run"] == 4


def test_analyzer_flags_four_consecutive_dialogue_turns_without_scene_business() -> None:
    text = (
        "“你没走。”他说。\n\n"
        "“我走了你就死了。”\n\n"
        "“你也可能死。”\n\n"
        "“知道了也不行。”她说。"
    )

    report = analyze_prose(text)

    assert report["metrics"]["dialogue_turn_run"] == 4
    assert any(item["code"] == "dialogue_ping_pong" for item in report["findings"])


def test_voice_drift_is_advisory() -> None:
    baseline = [prose_metrics("他说：“走吧。”\n她摇头。" * 20) for _ in range(3)]
    current = prose_metrics("这是一个极长的叙述句，它不断延伸并持续解释人物为什么这样行动以及这意味着什么。" * 30)

    drift = compare_voice_metrics(current, baseline)

    assert drift["drifted"] is True
    assert drift["blocking"] is False
    assert drift["signals"]
