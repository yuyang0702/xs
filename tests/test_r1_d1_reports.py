import json
from pathlib import Path


FIXTURE = Path(
    "tests/fixtures/reliability/r1_d1/historical-draft-replay-v1.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_historical_replay_fixture_is_hash_only() -> None:
    value = _fixture()
    serialized = FIXTURE.read_text(encoding="utf-8")

    assert value["schema"] == "R1D1HistoricalDraftReplayV1"
    assert value["raw_content_included"] is False
    assert value["prompt_content_included"] is False
    assert value["absolute_path_included"] is False
    assert value["private_identifier_included"] is False
    for forbidden in (
        "SignalKey", "raw_prompt", "story_text", "api_key", "headers",
    ):
        assert forbidden.casefold() not in serialized.casefold()


def test_exact_replay_preserves_true_positives_and_removes_only_false_positive() -> None:
    value = _fixture()
    calls = value["calls"]

    assert [item["ordinal"] for item in calls] == [20, 21, 22]
    assert [item["before_mixed_script_count"] for item in calls] == [6, 7, 1]
    assert [item["after_mixed_script_count"] for item in calls] == [6, 7, 0]
    assert [item["target_term_exemption_count"] for item in calls] == [0, 0, 1]
    assert all(item["other_findings_unchanged"] for item in calls)
    assert all(item["draft_bytes_modified"] is False for item in calls)
    assert calls[0]["leaf_blocking_codes"] == ["prose_invalid"]
    assert calls[1]["leaf_blocking_codes"] == ["prose_invalid"]
    assert calls[2]["leaf_blocking_codes"] == []
    assert value["exact_last_attempt_crosses_prose_boundary"] is True


def test_exact_term_provenance_is_current_and_fully_hash_bound() -> None:
    value = _fixture()
    authority = value["authority"]
    term = value["target_term"]
    provenance = term["provenance_sources"]

    assert authority["story_state_revision"] == 2
    assert authority["normalization_version"] == (
        "nfkc-case-sensitive-exact-token-v1"
    )
    assert len(authority["draft_authority_sha256"]) == 64
    assert len(authority["planning_artifact_sha256"]) == 64
    assert len(authority["execution_manifest_sha256"]) == 64
    assert len(authority["segment_binding_sha256"]) == 64
    assert term["term_length"] == 8
    assert term["provenance_count"] == sum(
        len(item["source_field_path_sha256s"]) for item in provenance
    )
    assert {
        item["source_artifact_kind"] for item in provenance
    } == {"planning_segment_ir", "short_execution_manifest"}
    assert all(
        item["segment_binding_sha256"]
        == authority["segment_binding_sha256"]
        for item in provenance
    )


def test_retry_reclassification_and_zero_paid_calls_are_explicit() -> None:
    value = _fixture()

    assert value["historical_mixed_script_regeneration_count"] == 2
    assert value["current_reclassified_true_positive_regeneration_count"] == 2
    assert value["after_false_positive_regeneration_count"] == 0
    assert value["after_total_regeneration_count"] == 2
    assert value["before_terminal_due_authority_false_positive"] is True
    assert value["after_terminal_due_authority_false_positive"] is False
    assert value["real_provider_calls"] == 0
    assert value["paid_model_calls"] == 0
    assert sum(item["model_calls"] for item in value["calls"]) == 0
