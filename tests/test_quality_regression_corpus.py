import json
from pathlib import Path

from novel_flywheel.local_editorial import analyze_prose


def test_quality_regression_corpus_keeps_expected_rule_ids() -> None:
    path = Path(__file__).parents[1] / "src" / "novel_flywheel" / "quality_regression.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert len(cases) >= 6
    for case in cases:
        actual = {item["rule_id"] for item in analyze_prose(case["text"])["findings"]}
        assert set(case["expected"]) <= actual, case["id"]
