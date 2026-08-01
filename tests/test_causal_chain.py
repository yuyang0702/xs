from novel_flywheel.causal_chain import (
    analyze_short_causal_chain,
    compact_causal_chain,
    cycle_range,
    extract_short_causal_chain,
)


def test_cycle_range_scales_with_short_story_length() -> None:
    assert cycle_range(2500) == (1, 2)
    assert cycle_range(6000) == (2, 3)
    assert cycle_range(12000) == (3, 5)
    assert cycle_range(24000) == (4, 7)
    assert cycle_range(50000) == (5, 9)


def test_analyzer_accepts_repeatable_cycles_with_reversal_evidence() -> None:
    chain = {
        "core_goal": {"content": "复活死去的朋友"},
        "cycles": [
            {
                "obstacle": "缺少灵魂媒介",
                "effort": "调查死亡现场",
                "result": "找到残缺记忆",
                "state_change": "确认灵魂仍在",
            },
            {
                "obstacle": "仪式需要交换生命",
                "effort": "寻找规则漏洞",
                "result": "朋友暂时复活",
                "state_change": "目标表面达成",
            },
        ],
        "accidents": [{"content": "朋友开始遗忘主角", "changes": "复活变得不稳定"}],
        "reversal": {"content": "朋友主动死亡是为了封印", "prior_evidence": ["死亡记录被销毁", "仪式异常顺利"]},
        "ending": {"surface_goal": "无法永久复活", "inner_goal": "主角放下愧疚", "cost": "再次失去朋友"},
    }

    report = analyze_short_causal_chain(chain, target_words=6000)

    assert report["status"] == "valid"
    assert not [item for item in report["findings"] if item["severity"] == "error"]
    compact = compact_causal_chain(chain)
    assert "复活死去的朋友" in compact
    assert "阻碍" in compact
    assert "反转" in compact


def test_analyzer_flags_missing_state_change_and_reversal_evidence() -> None:
    chain = {
        "core_goal": {"content": "复活朋友"},
        "cycles": [{"obstacle": "缺材料", "effort": "找材料", "result": "找到材料"}],
        "reversal": {"content": "朋友主动死亡", "prior_evidence": []},
        "ending": {"surface_goal": "朋友离开"},
    }

    report = analyze_short_causal_chain(chain, target_words=12000)

    codes = {item["code"] for item in report["findings"]}
    assert {"cycle_missing_state_change", "reversal_missing_evidence"} <= codes
    assert report["status"] == "needs_review"


def test_analyzer_flags_repeated_outcome_without_new_state() -> None:
    chain = {
        "core_goal": {"content": "把药送进封锁区"},
        "cycles": [
            {"obstacle": "守卫阻拦", "effort": "绕路", "result": "暂时脱险", "state_change": "继续前进"},
            {"obstacle": "追兵阻拦", "effort": "藏匿", "result": "暂时脱险", "state_change": "继续前进"},
        ],
        "ending": {"surface_goal": "药已送到", "inner_goal": "承认自己的愧疚"},
    }

    report = analyze_short_causal_chain(chain, target_words=3000)

    assert report["target_cycle_range"] == [2, 3]
    assert "cycle_repeated_outcome" in {item["code"] for item in report["findings"]}


def test_analyzer_accepts_attraction_fields_when_they_are_evidenced() -> None:
    chain = {
        "core_goal": {"content": "把药送进封锁区"},
        "opening": {
            "pressure": "妹妹只剩一夜", "anomaly": "主角把通行证交给仇人",
            "reader_question": "仇人为什么帮助她", "future_promise": "天亮前会有人失去记忆",
        },
        "cycles": [
            {"obstacle": "没有通行证", "effort": "与仇人交易", "result": "进入封锁区",
             "state_change": "仇人从威胁变成同行者", "escalation": "交易要求交出共同记忆",
             "next_question": "仇人要拿记忆做什么"},
            {"obstacle": "药被调包", "effort": "追查运输记录", "result": "找到真药",
             "state_change": "确认妹妹主动换药", "escalation": "救人目标被重新解释",
             "next_question": "妹妹为什么拒绝获救"},
        ],
        "question_chain": [{"question": "仇人为什么帮助她", "answer": "他欠妹妹一条命"}],
        "relationship_arc": [{"before": "敌对", "cause": "共同承担记忆代价", "after": "有限信任"}],
        "ending": {"surface_goal": "药已送到", "inner_goal": "接受妹妹的选择", "cost": "失去共同记忆"},
    }

    report = analyze_short_causal_chain(chain, target_words=3000)

    assert report["status"] == "valid"


def test_extract_short_causal_chain_keeps_outline_text() -> None:
    text = """
# 正常大纲

开头调查死亡现场。

SHORT_CAUSAL_CHAIN_JSON_START
{"core_goal":{"content":"复活朋友"},"cycles":[{"obstacle":"缺材料","effort":"寻找","result":"找到","state_change":"获得媒介"}],"ending":{"surface_goal":"复活失败"}}
SHORT_CAUSAL_CHAIN_JSON_END
"""

    outline, chain = extract_short_causal_chain(text)

    assert "# 正常大纲" in outline
    assert "SHORT_CAUSAL_CHAIN_JSON_START" not in outline
    assert chain["core_goal"]["content"] == "复活朋友"


def test_extract_short_causal_chain_accepts_markdown_json_fence() -> None:
    text = """
# 正常大纲

SHORT_CAUSAL_CHAIN_JSON_START
```json
{"core_goal":{"content":"复活朋友"},"cycles":[],"ending":{"surface_goal":"告别"}}
```
SHORT_CAUSAL_CHAIN_JSON_END

## 附录
保留这部分。
"""

    outline, chain = extract_short_causal_chain(text)

    assert "SHORT_CAUSAL_CHAIN_JSON_START" not in outline
    assert "## 附录" in outline
    assert chain["core_goal"]["content"] == "复活朋友"


def test_extract_short_causal_chain_accepts_html_comments_crlf_and_json_label_case() -> None:
    text = (
        "# 正常大纲\r\n\r\n"
        "  <!--  SHORT_CAUSAL_CHAIN_JSON_START  -->  \r\n"
        "```  JsOn  \r\n"
        '{"core_goal":{"content":"查清真相"},"cycles":[],"ending":{"surface_goal":"回家"}}\r\n'
        "```\r\n"
        "<!-- SHORT_CAUSAL_CHAIN_JSON_END -->\r\n\r\n"
        "## 附录\r\n保留这部分。\r\n"
    )

    outline, chain = extract_short_causal_chain(text)

    assert "# 正常大纲" in outline
    assert "## 附录\r\n保留这部分。" in outline
    assert "SHORT_CAUSAL_CHAIN_JSON_START" not in outline
    assert chain["core_goal"]["content"] == "查清真相"


def test_extract_short_causal_chain_accepts_long_and_tilde_fences() -> None:
    payload = '{"core_goal":{"content":"查清真相"},"cycles":[],"ending":{"surface_goal":"回家"}}'
    for fence in ("````json", "~~~JSON"):
        marker = fence[:4] if fence.startswith("````") else "~~~"
        text = (
            "# 正常大纲\n\nSHORT_CAUSAL_CHAIN_JSON_START\n"
            f"{fence}\n{payload}\n{marker}\n"
            "SHORT_CAUSAL_CHAIN_JSON_END\n"
        )

        outline, chain = extract_short_causal_chain(text)

        assert outline == "# 正常大纲"
        assert chain["core_goal"]["content"] == "查清真相"


def test_extract_short_causal_chain_does_not_consume_marker_text_inside_prose() -> None:
    text = (
        "前文 <!-- SHORT_CAUSAL_CHAIN_JSON_START --> 不是独立标记行\n"
        '{"core_goal":{"content":"不应提取"}}\n'
        "<!-- SHORT_CAUSAL_CHAIN_JSON_END -->\n"
        "后文"
    )

    outline, chain = extract_short_causal_chain(text)

    assert outline == text
    assert chain is None
