from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from novel_flywheel import prose_quality
from novel_flywheel.workflows import WorkflowService
from tools.diagnostics.r1_d2_draft_mixed_script import build_report


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((
    ROOT / "tests/fixtures/reliability/r1_d2/draft-mixed-script-closure-v1.json"
).read_text(encoding="utf-8"))


def _sha(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _context(*terms: str):
    source_hash = _sha("r1-d2-sanitized-authority")
    binding = _sha("r1-d2-segment")
    authority = _sha("r1-d2-authority")
    source = prose_quality.AuthorityTermSourceArtifactV1(
        artifact_kind="planning_segment_ir",
        artifact_sha256=source_hash,
        contract="PlanningSegmentIR",
        version=1,
        authority_status="accepted_current",
    )
    fields = tuple(
        prose_quality.AuthorityTermProjectionFieldV1(
            source_artifact_sha256=source_hash,
            field_path=f"segments/1/event_body/{index}",
            value=f"权威字段含有{term}术语",
            segment_binding_sha256=binding,
        )
        for index, term in enumerate(terms)
    )
    term_set = prose_quality.build_authority_approved_latin_term_set(
        draft_authority_revision=2,
        draft_authority_sha256=authority,
        segment_binding_sha256=binding,
        source_artifacts=(source,),
        fields=fields,
    )
    return prose_quality.DraftProseAuthorityContextV1(
        term_set=term_set,
        current_draft_authority_revision=2,
        current_draft_authority_sha256=authority,
        current_segment_binding_sha256=binding,
        current_source_artifact_sha256s=(source_hash,),
    )


def _decisions(text: str, context=None) -> list[str]:
    return [
        item["decision"]
        for item in prose_quality.analyze_prose(
            text, authority_context=context,
        ).get("mixed_script_decisions", [])
    ]


@pytest.fixture(scope="session")
def private_report():
    evidence = os.environ.get("NOVEL_R1_D2_PRIVATE_EVIDENCE_ROOT")
    run = os.environ.get("NOVEL_R1_D2_PRIVATE_RUN_ROOT")
    if not evidence or not run:
        pytest.skip("private sealed Canary evidence is operator-supplied")
    return build_report(
        Path(evidence), Path(run),
        ROOT / "docs/superpowers/reports/sc-standard-window-1/"
        "sc-standard-window-1-model-boundary-ledger-v1.json",
    )


def test_fixture_is_hash_only_and_private_safe() -> None:
    serialized = json.dumps(FIXTURE, ensure_ascii=False)
    assert FIXTURE["raw_content_included"] is False
    assert FIXTURE["prompt_content_included"] is False
    assert FIXTURE["exact_token_text_included"] is False
    assert FIXTURE["absolute_path_included"] is False
    assert "controlled-fixture" not in serialized


@pytest.mark.parametrize("ordinal", [20, 21, 22])
def test_exact_private_replay_reproduces_attempt_reject_set(
    private_report, ordinal: int,
) -> None:
    actual = next(
        item for item in private_report["attempt_rejected_sets"]
        if item["boundary_ordinal"] == ordinal
    )
    expected = next(item for item in FIXTURE["calls"] if item["ordinal"] == ordinal)
    assert actual["occurrence_count"] == expected["rejected_item_count"]
    assert actual["set_sha256"] == expected["rejected_set_sha256"]


def test_authority_inventory_hash_is_exact(private_report) -> None:
    assert private_report["authority"]["approved_term_inventory_sha256"] == (
        FIXTURE["authority"]["approved_term_inventory_sha256"]
    )
    assert private_report["authority"]["term_set_sha256"] == (
        FIXTURE["authority"]["term_set_sha256"]
    )


def test_rejected_token_first_appearance_trace_is_exact(private_report) -> None:
    assert len(private_report["rejected_items"]) == 4
    assert sorted(item["token_sha256"] for item in private_report["rejected_items"]) == (
        FIXTURE["rejected_token_sha256s"]
    )
    assert {item["first_appearance_call_ordinal"] for item in private_report["rejected_items"]} == {1, 20}


def test_set_diff_20_to_21_is_exact(private_report) -> None:
    diff = next(item for item in private_report["set_diffs"] if item["transition"] == "20->21")
    assert (len(diff["added"]), len(diff["removed"]), len(diff["retained"])) == (1, 3, 0)


def test_set_diff_21_to_22_is_exact(private_report) -> None:
    diff = next(item for item in private_report["set_diffs"] if item["transition"] == "21->22")
    assert (len(diff["added"]), len(diff["removed"]), len(diff["retained"])) == (0, 0, 1)
    assert list(diff["occurrence_delta"].values()) == [1]


def test_r1_d1_approved_exact_token_still_passes() -> None:
    assert _decisions("系统SignalKey记录稳定。", _context("SignalKey")) == [
        "exempt_authority_approved_term"
    ]


def test_truly_unapproved_mixed_token_still_rejects() -> None:
    assert _decisions("系统UnlistedKey记录异常。", _context("SignalKey")) == [
        "reject_unapproved_mixed_script"
    ]


def test_actual_corruption_still_rejects() -> None:
    assert _decisions("日志zzzzzz破损。", _context("SignalKey")) == [
        "reject_unapproved_mixed_script"
    ]


def test_stale_authority_scenario_is_fail_closed() -> None:
    current = _context("SignalKey")
    stale = replace(current, current_draft_authority_sha256=_sha("advanced"))
    assert _decisions("系统SignalKey记录稳定。", stale) == [
        "reject_stale_authority"
    ]


def test_normalization_counterfactual_preserves_current_rejects(private_report) -> None:
    rows = [
        item for item in private_report["counterfactual_matrix"]
        if item["variant"] == "normalization_only"
    ]
    assert [item["reject_count"] for item in rows] == [3, 1, 2]


def test_punctuation_counterfactual_removes_surface_candidate(private_report) -> None:
    rows = [
        item for item in private_report["counterfactual_matrix"]
        if item["variant"] == "punctuation_adjacency_only"
    ]
    assert all(item["pass"] and not item["policy_relaxation"] for item in rows)


def test_authority_addition_counterfactual_is_policy_relaxation(private_report) -> None:
    rows = [
        item for item in private_report["counterfactual_matrix"]
        if item["variant"] == "test_only_add_rejected_tokens_to_authority"
    ]
    assert all(item["pass"] and item["policy_relaxation"] for item in rows)


def test_latest_and_retry_authority_snapshots_do_not_change_result(private_report) -> None:
    grouped = {
        variant: [
            item["reject_count"] for item in private_report["counterfactual_matrix"]
            if item["variant"] == variant
        ]
        for variant in (
            "original_validator_original_authority",
            "latest_visible_authority",
            "retry_before_after_authority",
        )
    }
    assert set(map(tuple, grouped.values())) == {(3, 1, 2)}


def test_retry_finding_propagation_characterization(private_report) -> None:
    contract = private_report["retry_contract"]
    assert contract["validator_decisions_persisted_hash_only"] is True
    assert contract["precise_decisions_passed_to_retry"] is False
    assert contract["retry_input_issue_codes"] == [["prose_invalid"], ["prose_invalid"]]


def test_retry_scope_characterization(private_report) -> None:
    contract = private_report["retry_contract"]
    assert contract["retry_scope"] == "whole_owned_event_scope_regeneration"
    assert contract["previous_draft_used_as_edit_baseline"] is False
    assert contract["keep_other_draft_content_unchanged_instruction"] is False


def test_leaf_gate_collapses_precise_mixed_script_to_generic_finding() -> None:
    findings = WorkflowService._draft_segment_findings(
        "系统UnlistedKey记录异常。", 10, [], authority_context=_context("SignalKey"),
    )
    blocking = [item for item in findings if item.get("blocking")]
    assert [item["code"] for item in blocking] == ["prose_invalid"]
    assert "token_sha256" not in repr(blocking)


def test_replay_contract_has_no_prompt_route_or_model_invocation(private_report) -> None:
    assert private_report["model_calls_during_replay"] == 0
    assert private_report["paid_calls_during_replay"] == 0
    assert private_report["network_calls_during_replay"] == 0


def test_live_parity_remains_exact_in_parent_evidence() -> None:
    evidence = json.loads((
        ROOT / "docs/superpowers/reports/sc-standard-window-1/"
        "sc-standard-window-1-real-evidence-v1.json"
    ).read_text(encoding="utf-8"))
    parity = evidence["live_parity"]
    assert parity["status"] == "exact"
    assert parity["before_sha256"] == parity["after_sha256"] == FIXTURE["live_parity_sha256"]


def test_r1_d1_declared_policy_and_current_production_hash_are_bound(private_report) -> None:
    assert private_report["policy"]["r1_d1_declared_policy_sha256"] == (
        "7e9875e3341f811fc3882b8161de6ca9f4e81243ce0262a0b1c72cb54353c940"
    )
    assert private_report["policy"]["production_source_sha256"] == (
        "b56475366aa7f64edc2f65f03ebf87dc76ed454751661efd0346631888a50789"
    )


def test_all_rejected_items_have_exactly_one_allowed_class(private_report) -> None:
    assert {item["classification"] for item in private_report["rejected_items"]} == {
        "LEGITIMATE_NEW_LATIN_TERM_INTRODUCED_BY_DRAFT"
    }


def test_r1_d1_is_not_a_regression_and_validator_is_correct(private_report) -> None:
    assert private_report["r1_d1_regression"] == "NO"
    assert private_report["validator_correctness"] == "correct"


def test_retry_closure_is_incorrect_with_one_primary_root_cause(private_report) -> None:
    assert private_report["retry_closure_correctness"] == "incorrect"
    assert private_report["primary_root_cause"] == "draft.retry_finding_not_propagated"
    assert private_report["secondary_contributors"] == ["draft.retry_scope_too_broad"]


def test_local_deterministic_repair_is_unsafe(private_report) -> None:
    assert private_report["local_deterministic_repair_safe"] == "no"
    placeholders = [
        item for item in private_report["counterfactual_matrix"]
        if item["variant"] == "chinese_placeholder"
    ]
    assert all(item["pass"] and item["changes_draft_semantics"] for item in placeholders)


def test_alternate_mechanisms_are_all_excluded(private_report) -> None:
    assert private_report["excluded_mechanisms"]
    assert all(private_report["excluded_mechanisms"].values())


def test_parent_evidence_commit_is_exact(private_report) -> None:
    assert private_report["parent_evidence_commit"] == FIXTURE["parent_evidence_commit"]
