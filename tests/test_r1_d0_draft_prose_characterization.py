import json
from pathlib import Path

import pytest

from novel_flywheel.prose_quality import analyze_prose
from novel_flywheel.workflows import WorkflowService


FIXTURE = Path(
    "tests/fixtures/reliability/r1_d0/draft-prose-validation-replay-v1.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _blocking_codes(text: str) -> list[str]:
    return [
        str(item["code"])
        for item in analyze_prose(text)["findings"]
        if item["blocking"]
    ]


def test_private_replay_fixture_contains_only_hashes_and_structural_metrics() -> None:
    value = _fixture()

    assert value["schema"] == "R1D0DraftProseValidationReplayFixtureV1"
    assert value["raw_content_included"] is False
    assert value["prompt_content_included"] is False
    assert value["absolute_path_included"] is False
    assert value["private_identifier_included"] is False
    serialized = FIXTURE.read_text(encoding="utf-8")
    for forbidden in ("raw_prompt", "story_text", "api_key", "headers"):
        assert forbidden not in serialized.casefold()


def test_exact_real_draft_replay_characterizes_first_concrete_failure() -> None:
    value = _fixture()

    assert [item["ordinal"] for item in value["calls"]] == [20, 21, 22]
    assert all(item["finish_reason"] == "end_turn" for item in value["calls"])
    assert all(
        item["completeness_status"] == "complete_end_turn_sentence_closed"
        for item in value["calls"]
    )
    assert [
        item["first_concrete_issue_count"] for item in value["calls"]
    ] == [6, 7, 1]
    assert all(
        item["first_concrete_issue_code"] == "mixed_script_corruption"
        for item in value["calls"]
    )
    assert all(
        2700 <= item["effective_han"] <= 8700 for item in value["calls"]
    )


def test_current_mixed_script_rule_cannot_distinguish_corruption_from_authorized_term() -> None:
    corrupted_name = "苏quila转身离开。"
    authorized_term = "她核对了SignalKey记录，确认编号仍然一致。"

    assert _blocking_codes(corrupted_name) == ["mixed_script_corruption"]
    assert _blocking_codes(authorized_term) == ["mixed_script_corruption"]


def test_punctuation_only_counterexample_removes_blocker_without_changing_tokens() -> None:
    adjacent = "她核对了SignalKey记录，确认编号仍然一致。"
    punctuation_bounded = "她核对了“SignalKey”记录，确认编号仍然一致。"

    assert _blocking_codes(adjacent) == ["mixed_script_corruption"]
    assert _blocking_codes(punctuation_bounded) == []
    assert adjacent.replace("SignalKey", "") == punctuation_bounded.replace(
        "“SignalKey”", ""
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "R1-D0 acceptance: authority-approved Latin terms must not be classified "
        "as mixed-script corruption; production behavior is intentionally unchanged."
    ),
)
def test_future_validator_accepts_authorized_term_but_rejects_corrupted_name() -> None:
    authorized_term = "她核对了SignalKey记录，确认编号仍然一致。"
    corrupted_name = "苏quila转身离开。"

    assert _blocking_codes(authorized_term) == []
    assert _blocking_codes(corrupted_name) == ["mixed_script_corruption"]


def test_validator_result_is_deterministic_for_the_same_sanitized_shape() -> None:
    text = "她核对了SignalKey记录，确认编号仍然一致。"

    results = [_blocking_codes(text) for _ in range(20)]

    assert results == [["mixed_script_corruption"]] * 20


def test_current_leaf_gate_collapses_concrete_issue_to_prose_invalid() -> None:
    text = "她核对了SignalKey记录，确认编号仍然一致。" * 60

    findings = WorkflowService._draft_segment_findings(text, 600, [])

    assert [item["code"] for item in findings] == ["prose_invalid"]
    assert "mixed_script_corruption" not in {
        item["code"] for item in findings
    }


def test_scope_retry_evidence_proves_whole_regeneration_not_patch() -> None:
    retry = _fixture()["scope_retry"]

    assert retry["scope_kind"] == "whole_ownership_unit_regeneration"
    assert retry["previous_draft_supplied"] is False
    assert retry["immutable_prose_freeze_supplied"] is False
    assert retry["issue_receipt_status"] == "unavailable_not_materialized"
    assert retry["call_20_to_21_exact_retained_paragraphs"] == 0
    assert retry["call_21_to_22_exact_retained_paragraphs"] == 3


def test_stage_outputs_are_not_legal_short_checkpoint_candidates(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "draft-part-01.md").write_text(
        "transport-complete but locally rejected", encoding="utf-8"
    )
    (outputs / "draft-part-01-scope-retry.md").write_text(
        "another transport-complete rejected result", encoding="utf-8"
    )

    with pytest.raises(
        ValueError, match="Short-story checkpoint has no complete manuscript"
    ):
        WorkflowService._short_checkpoint_manuscript(outputs, 1)


def test_real_run_created_no_draft_candidate_or_segment_checkpoint() -> None:
    containment = _fixture()["containment"]

    assert containment["draft_candidate_rows"] == 0
    assert containment["sealed_draft_generation_units"] == 0
    assert containment["draft_segment_checkpoint_exists"] is False
    assert containment["draft_artifact_exists"] is False
    assert containment["best_candidate_exists"] is False
    assert containment["recoverable_legal_draft"] is False
    assert containment["recoverable_upstream_checkpoint"] is True
