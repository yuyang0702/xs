import hashlib

from novel_flywheel import manuscript_analysis
from novel_flywheel.manuscript_analysis import (
    analysis_matches,
    analyze_manuscript,
    compact_analysis,
)


def test_analysis_covers_complete_text_and_opening_zone():
    text = "第一行。\n第二行。\n第三行。\n\n林晚发现门锁被换了。" + "中段事件。" * 700
    report = analyze_manuscript(text, nlp_analyze=None)
    assert report["text_hash"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert report["coverage"] == 1.0
    assert report["opening"]["first_three_lines"] == ["第一行。", "第二行。", "第三行。"]
    assert report["opening"]["zone_characters"] == 500
    assert report["windows"][-1]["end"] == len(text)
    assert analysis_matches(report, text)
    assert compact_analysis(report)["text_hash"] == report["text_hash"]
    assert report["narrative_ledger"]["text_hash"] == report["text_hash"]
    assert "narrative_ledger" in compact_analysis(report)


def test_analysis_rejects_cached_report_without_stable_units() -> None:
    text = "旧缓存正文。"
    old_report = {
        "analysis_version": "manuscript-analysis-v2",
        "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }

    assert analysis_matches(old_report, text) is False


def test_analysis_cache_is_bound_to_reference_corpus_authority() -> None:
    text = "正文不变，但参考资料库已经更新。"
    report = analyze_manuscript(
        text, nlp_analyze=None, reference_corpus_sha256="a" * 64,
    )

    assert report["reference_corpus_sha256"] == "a" * 64
    assert analysis_matches(report, text, "a" * 64) is True
    assert analysis_matches(report, text, "b" * 64) is False
    assert compact_analysis(report)["reference_corpus_sha256"] == "a" * 64


def test_analysis_normalizes_ltp_entities_and_events():
    def fake(_text):
        return {
            "backend": "ltp", "available": True, "backend_version": "ltp-v2",
            "result": {
                "cws": [["林晚", "打开", "木盒"]],
                "pos": [["nh", "v", "n"]],
                "ner": [[["Nh", 0, 0]]],
                "srl": [[[(1, [("A0", 0, 0), ("A1", 2, 2)])]]],
                "dep": [],
            },
        }

    report = analyze_manuscript("林晚打开木盒。", nlp_analyze=fake)
    assert report["nlp"]["available"] is True
    assert any(item["text"] == "林晚" for item in report["entities"])
    assert report["events"][0]["predicate"] == "打开"


def test_analysis_normalizes_current_ltp_entity_and_event_shapes():
    def fake(_text):
        return {
            "backend": "ltp", "available": True, "backend_version": "ltp-v2",
            "result": {
                "cws": [["林雾", "打开", "木盒"]],
                "pos": [["nh", "v", "n"]],
                "ner": [[["Nh", "林雾", 0, 0]]],
                "srl": [[{
                    "index": 1,
                    "predicate": "打开",
                    "arguments": [["A0", "林雾", 0, 0], ["A1", "木盒", 2, 2]],
                }]],
                "dep": [],
            },
        }

    report = analyze_manuscript("林雾打开木盒。", nlp_analyze=fake)

    assert report["entities"][0]["text"] == "林雾"
    assert report["events"][0]["predicate"] == "打开"
    assert report["events"][0]["arguments"] == [
        {"role": "A0", "text": "林雾"},
        {"role": "A1", "text": "木盒"},
    ]


def test_originality_candidates_are_limited_to_local_corpus():
    report = analyze_manuscript(
        "林知晚推开生锈铁门，发现地下室仍亮着灯。",
        nlp_analyze=None,
        comparison_sources=[{
            "id": "ref-1", "title": "参考",
            "text": "林之晚推开生锈铁门，发现地下室仍亮着灯。",
        }],
    )
    originality = report["originality"]
    assert originality["scope"] == "local_corpus_only"
    assert originality["continuous_passages"]
    assert originality["similar_names"]
    assert originality["semantic_candidates"]


def test_originality_prefers_ltp_entities_over_regex_name_fallback():
    def fake(_text):
        return {
            "backend": "ltp", "available": True,
            "result": {
                "cws": [["林雾", "从", "地下", "离开"]],
                "pos": [["nh", "p", "n", "v"]],
                "ner": [[["Nh", "林雾", 0, 0]]],
                "srl": [[]], "dep": [],
            },
        }

    report = analyze_manuscript(
        "林雾从地下离开。", nlp_analyze=fake,
        comparison_sources=[{"id": "ref", "text": "林晚从地上回来。"}],
    )

    assert {
        item["manuscript_name"] for item in report["originality"]["similar_names"]
    } <= {"林雾"}


def test_market_baseline_comparison_is_advisory_only():
    report = analyze_manuscript(
        "林晚回到家。她整理桌面，然后开始工作。",
        nlp_analyze=None,
        market_baseline={
            "sample_count": 12, "confidence_level": "advisory",
            "opening": {"question_percent": 80.0, "anomaly_percent": 75.0},
            "boundary": "本地样本",
        },
    )

    assert report["baseline_comparison"]["sample_count"] == 12
    assert {item["signal"] for item in report["baseline_comparison"]["deviations"]} == {
        "opening_question", "opening_anomaly",
    }
    assert all(item["blocking"] is False for item in report["baseline_comparison"]["deviations"])
    assert "baseline_comparison" in compact_analysis(report)


def test_stable_unit_ids_survive_unrelated_prefix_insertion() -> None:
    before = analyze_manuscript("甲段。\n\n父亲把银锁交给林晚。", nlp_analyze=None)
    after = analyze_manuscript("新增开头。\n\n甲段。\n\n父亲把银锁交给林晚。", nlp_analyze=None)

    before_unit = before["units"]["paragraphs"][1]
    after_unit = after["units"]["paragraphs"][2]
    assert before_unit["stable_id"] == after_unit["stable_id"]
    assert before_unit["start"] == 5
    assert after_unit["start"] == 12
    assert before_unit["text_hash"] == hashlib.sha256(
        "父亲把银锁交给林晚。".encode("utf-8")
    ).hexdigest()


def test_stable_text_units_distinguish_duplicate_occurrences() -> None:
    units = manuscript_analysis.stable_text_units("证人看见银锁。\n\n证人看见银锁。")

    first, second = units["paragraphs"]
    assert [first["occurrence"], second["occurrence"]] == [1, 2]
    assert first["stable_id"] == manuscript_analysis.stable_key("paragraph", first["text"], 1)
    assert second["stable_id"] == manuscript_analysis.stable_key("paragraph", second["text"], 2)
    assert first["stable_id"] != second["stable_id"]


def test_impact_index_keeps_evidence_location_and_confidence() -> None:
    report = analyze_manuscript(
        "桌上有一把异常的银锁。\n\n银锁的真相终于揭晓。",
        nlp_analyze=None,
    )

    entries = report["impact_index"]["terms"]["银锁"]
    assert [item["paragraph"] for item in entries] == [1, 2]
    assert all(item["source"] in {"rules", "ltp"} for item in entries)
    assert all(0 <= item["confidence"] <= 1 for item in entries)
    assert all(item["unit_id"] for item in entries)
    assert manuscript_analysis.build_impact_index(report) == report["impact_index"]


def test_impact_index_does_not_invent_terms_without_ledger_evidence() -> None:
    report = analyze_manuscript(
        "林晚今天回到房间。\n\n民警今天离开房间。",
        nlp_analyze=None,
    )

    assert report["narrative_ledger"]["questions"] == []
    assert report["narrative_ledger"]["promises"] == []
    assert report["narrative_ledger"]["setups"] == []
    assert report["impact_index"]["terms"] == {}


def test_impact_index_skips_rule_term_fallback_when_ltp_is_available() -> None:
    def fake(_text):
        return {
            "backend": "ltp", "available": True, "backend_version": "ltp-v2",
            "result": {"cws": [], "pos": [], "ner": [], "srl": [], "dep": []},
        }

    report = analyze_manuscript(
        "桌上有一把异常的银锁。\n\n银锁的真相终于揭晓。",
        nlp_analyze=fake,
    )

    assert report["narrative_ledger"]["setups"]
    assert report["impact_index"]["terms"] == {}


def test_impact_index_includes_ltp_entities_and_events() -> None:
    def fake(_text):
        return {
            "backend": "ltp", "available": True, "backend_version": "ltp-v2",
            "result": {
                "cws": [["林晚", "打开", "木盒"]],
                "pos": [["nh", "v", "n"]],
                "ner": [[["Nh", "林晚", 0, 0]]],
                "srl": [[[(1, [("A0", 0, 0), ("A1", 2, 2)])]]],
                "dep": [],
            },
        }

    report = analyze_manuscript("林晚打开木盒。", nlp_analyze=fake)

    entity = report["impact_index"]["entities"]["林晚"][0]
    event = report["impact_index"]["events"]["打开|林晚|木盒"][0]
    assert entity["source"] == event["source"] == "ltp"
    assert entity["start"] == 0
    assert event["start"] == 2


def test_analysis_exposes_payoff_evidence_with_provenance() -> None:
    report = analyze_manuscript(
        "桌上有一张异常的照片。\n\n照片的真相终于揭晓。",
        nlp_analyze=None,
    )

    payoff = report["payoffs"][0]
    assert payoff["source"] == "rules"
    assert payoff["unit_id"]
    assert payoff["end"] > payoff["start"]
    assert 0 <= payoff["confidence"] <= 1
