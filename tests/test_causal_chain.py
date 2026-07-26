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
