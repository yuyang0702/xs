from novel_flywheel.narrative_attraction import (
    compact_attraction_guidance,
    local_attraction_candidates,
    normalize_attraction_map,
)


def test_local_candidates_find_unlabelled_actions_with_absolute_offsets() -> None:
    middle = "平静的日子一天天过去。" * 400
    text = "雨夜里，她把唯一的钥匙递给仇人。谁会打开那扇门？\n" + middle + "门后的人接过钥匙，城门因此失守。"

    result = local_attraction_candidates(text)

    assert result["coverage_percent"] == 100.0
    anomaly_start = text.index("她把唯一的钥匙")
    consequence_start = text.index("门后的人接过钥匙")
    assert any(item["start"] <= anomaly_start < item["end"] for item in result["opening"]["anomaly"])
    assert any(item["start"] <= consequence_start < item["end"] for item in result["consequences"])
    assert result["questions"][0]["excerpt"].endswith("？")
    assert "候选证据" in result["boundary"]


def test_local_candidates_do_not_require_literal_seven_step_labels() -> None:
    text = "她烧掉返程票，独自走进封锁区。三天后，药送到了，妹妹却不再认得她。"

    result = local_attraction_candidates(text)

    assert result["decisions"]
    assert result["consequences"]
    assert all(word not in text for word in ("目标", "阻碍", "努力", "结果", "反转"))


def test_normalizer_keeps_accident_separate_from_unsupported_reversal() -> None:
    value = {
        "fit": {"level": "partial", "explanation": "推进清楚但没有足够反转证据"},
        "core_goal": {"surface": "送药", "emotional": "得到妹妹原谅"},
        "cycles": [],
        "accidents": [{"content": "途中停电", "evidence": []}],
        "reversal": {"content": "停电者是同伴", "prior_evidence": []},
        "ending": {"surface_payoff": "药送到", "emotional_payoff": "尚未和解", "cost": "失去记忆"},
    }

    result = normalize_attraction_map(value, text_length=1_000)

    assert result["accidents"][0]["content"] == "途中停电"
    assert result["reversal"] is None
    assert "反转缺少可回看的前置证据" in result["uncertainties"]


def test_normalizer_marks_unsupported_structure_instead_of_inventing_nodes() -> None:
    result = normalize_attraction_map(
        {"fit": {"level": "not_applicable", "explanation": "生活流片段"}},
        text_length=200,
    )

    assert result["fit"]["level"] == "not_applicable"
    assert result["cycles"] == []
    assert "未识别出有证据支持的核心目标" in result["uncertainties"]
    assert "未识别出有证据支持的结局兑现" in result["uncertainties"]


def test_compact_guidance_excludes_source_evidence_and_concrete_packaging() -> None:
    attraction_map = normalize_attraction_map({
        "fit": {"level": "strong", "explanation": "因果推进完整"},
        "opening": {
            "mechanism": "opening_pressure_anomaly_future_promise",
            "transfer_guidance": "先给危险，再让主角采取反常行动，最后预告长期后果",
            "evidence": [{"start": 0, "end": 8, "excerpt": "周海晏收下十块钱"}],
        },
        "core_goal": {"surface": "获得保护", "emotional": "获得归属"},
        "cycles": [{
            "obstacle": "暴力威胁", "effort": "主动求助", "result": "得到临时庇护",
            "state_change": "从孤立变为拥有保护者", "transfer_guidance": "每轮结果改变可用选择",
            "evidence": [{"start": 0, "end": 8, "excerpt": "十块钱保护十年"}],
        }],
        "ending": {"surface_payoff": "承诺兑现", "emotional_payoff": "确认被爱", "cost": "永久失去保护者"},
    }, text_length=100)

    guidance = compact_attraction_guidance(attraction_map)
    serialized = str(guidance)

    assert guidance["opening"] == "opening_pressure_anomaly_future_promise"
    assert guidance["cycle_rules"] == ["每轮结果改变可用选择"]
    assert "周海晏" not in serialized
    assert "十块钱" not in serialized
    assert "excerpt" not in serialized
