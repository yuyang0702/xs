import json
from pathlib import Path


REPORT_ROOT = Path("docs/superpowers/reports/r1-pa2")


def test_post_accepted_timeline_covers_exactly_calls_10_through_22() -> None:
    value = json.loads(
        (REPORT_ROOT / "post-accepted-receipt-call-timeline-v1.json").read_text(
            encoding="utf-8",
        )
    )
    assert value["schema"] == "PostAcceptedReceiptCallTimelineV1"
    assert [item["ordinal"] for item in value["calls"]] == list(range(10, 23))
    assert value["calls"][0]["final_outcome"] == "VALID_ACCEPTED_ARTIFACT"
    assert value["calls"][-1]["final_outcome"] == "WORKFLOW_TERMINAL_AFTER_RETURN"
    assert value["raw_content_included"] is False


def test_accepted_whole_receipt_closure_preserves_unverifiable_checkpoint() -> None:
    value = json.loads(
        (REPORT_ROOT / "accepted-whole-receipt-closure-v1.json").read_text(
            encoding="utf-8",
        )
    )
    assert value["schema"] == "AcceptedWholeReceiptClosureV1"
    assert len(value["questions"]) == 12
    assert value["closure_levels"]["accepted_artifact_materialized"] is True
    assert value["closure_levels"]["checkpoint_binding_exact"] is False
    assert value["closure_levels"]["workflow_completed"] is False
    assert value["raw_content_included"] is False
