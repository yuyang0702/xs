import hashlib

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
