from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from tools.canary import skill_v2_pair1_fixture_narrow_fix as fixture_fix
from tools.diagnostics import skill_v2_bounded_repeated_ab as historical_campaign


REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def built() -> tuple[dict[str, bytes], dict[str, object]]:
    return fixture_fix.build_documents(
        REPO,
        materialization_parent_head=fixture_fix.BASELINE_HEAD,
        validation_evidence={
            "focused": "TEST",
            "related": "TEST",
            "full_suite": "TEST",
            "strict_l3": "TEST",
        },
    )


def _json(documents: dict[str, bytes], relative: str) -> dict[str, object]:
    return json.loads(
        documents[f"{fixture_fix.OUTPUT_ROOT}/{relative}"].decode("utf-8")
    )


def test_event_id_policy_is_deterministic_canonical_and_collision_free() -> None:
    corrected = fixture_fix.corrected_pair1_case_v2()
    assert corrected["event_id"] == "EV-3D3AE01E"
    assert corrected["event_id"] == fixture_fix.canonical_fixture_event_id_v2(
        historical_campaign.CASE_DEFINITIONS[0]
    )
    assert re.fullmatch(r"EV-[0-9A-F]{8}", corrected["event_id"])
    prospective = fixture_fix.prospective_campaign_event_ids_v2()
    assert len(prospective) == len(set(prospective.values())) == 5


def test_successor_changes_only_versioned_case_and_event_identity() -> None:
    old = historical_campaign.CASE_DEFINITIONS[0]
    new = fixture_fix.corrected_pair1_case_v2()
    assert old["pair_case_id"] == "restored-character-heavy-v1"
    assert new["pair_case_id"] == "restored-character-heavy-v2"
    assert old["event_id"] == "AB-CHARACTER-0001"
    assert new["event_id"] == "EV-3D3AE01E"
    for field in (
        "creative_demand_class",
        "primary_dimensions",
        "entry_state",
        "required_change",
        "exit_state",
        "obligations",
    ):
        assert new[field] == old[field]


def test_all_historical_campaign_ids_are_audited_without_broad_mutation() -> None:
    audit = fixture_fix.campaign_fixture_compatibility_audit_v1()
    assert audit["campaign_wide_fixture_id_defect_detected"] is True
    assert audit["affected_pair_count"] == 5
    assert all(row["matches_ev_regex"] is False for row in audit["pairs"])
    assert historical_campaign.CASE_DEFINITIONS[1]["event_id"] == "AB-WORLD-0001"
    assert historical_campaign.CASE_DEFINITIONS[4]["event_id"] == "AB-MIXED-0001"


def test_old_reproduction_rejects_and_corrected_reproduction_passes() -> None:
    reproduction = fixture_fix.validator_reproduction_v1()
    assert reproduction["old_fixture"]["status"] == "REJECTED"
    assert reproduction["old_fixture"]["rule_codes"] == [
        "SLICE1_EVENT_REALIZATION_INVALID"
    ]
    assert reproduction["new_fixture"]["status"] == "PASS"
    assert reproduction["new_fixture"]["rule_codes"] == []
    assert reproduction["candidate_semantics_identical"] is True


def test_corrected_fixture_and_ab_lock_are_exact(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, _ = built
    fixture = _json(documents, "corrected-pair1/sanitized-fixture-v2.json")
    lock = _json(documents, "corrected-pair1/pair-ab-lock-v2.json")
    assert fixture["corrected_formal_event_id"] == "EV-3D3AE01E"
    assert fixture["authority_input"]["formal_event_ids"] == ["EV-3D3AE01E"]
    assert fixture["authority_input"]["segment_event_ids"] == [["EV-3D3AE01E"]]
    assert fixture["story_slice"]["formal_event_id"] == "EV-3D3AE01E"
    assert lock["primary_changed_variable"] == "SKILL_CONTEXT"
    assert lock["semantic_diff_keys"] == [
        "skill_context_sha256",
        "skill_profile_sha256",
        "system_sha256",
        "wire_input_sha256",
    ]
    assert all(lock[field] is True for field in historical_campaign.AB_EQUALITY_FIELDS)


@pytest.mark.parametrize("arm", ("a-arm", "b-arm"))
def test_corrected_packets_are_fresh_disabled_and_nonce_free(
    built: tuple[dict[str, bytes], dict[str, object]], arm: str,
) -> None:
    documents, _ = built
    packet = _json(documents, f"corrected-pair1/{arm}/disabled-packet-v2.json")
    approval = _json(documents, f"corrected-pair1/{arm}/approval-template-v2.json")
    nonce = _json(documents, f"corrected-pair1/{arm}/nonce-policy-v2.json")
    assert packet["execution_authorized"] is False
    assert packet["usage_status"] == "unused"
    assert packet["reservation_status"] == "unreserved"
    assert packet["signed_approval"] == "ABSENT"
    assert packet["single_use_nonce"] is None
    assert approval["execution_authorized"] is False
    assert approval["signed_approval"] == "ABSENT"
    assert nonce["nonce_present"] is False
    assert nonce["ledger_entry_count"] == 0


def test_old_approval_and_nonce_cannot_authorize_corrected_packet(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, _ = built
    packet = _json(documents, "corrected-pair1/a-arm/disabled-packet-v2.json")
    result = fixture_fix.validate_old_approval_nonreuse_v1(REPO, packet)
    assert result["old_approval_reuse_allowed"] is False
    assert result["old_nonce_reuse_allowed"] is False
    assert result["old_packet_reuse_allowed"] is False
    assert result["mismatch_dimensions"] == [
        "pair_case_id",
        "scope",
        "cohort_id",
        "packet_sha256",
    ]


def test_b_and_later_progression_remain_blocked(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, _ = built
    state = _json(documents, "campaign-successor-state-v1.json")
    assert state["campaign_real_execution_resumed"] is False
    assert state["pair1_corrected_b_approval_allowed"] is False
    assert state["pair2_or_later_allowed"] is False
    assert state["state"] == "READY_FOR_PAIR1_CORRECTED_A_FRESH_APPROVAL"


def test_unsigned_approval_readiness_is_ready_without_approval_or_nonce(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, result = built
    readiness = fixture_fix.validate_unsigned_approval_readiness_v1(
        REPO, documents
    )
    assert readiness["approval_dry_run_result"] == "READY"
    assert all(
        value == "PASS"
        for key, value in readiness.items()
        if key.endswith("_binding") or key.endswith("_compatibility")
    )
    assert readiness["signed_approval"] == "ABSENT"
    assert readiness["single_use_nonce"] == "ABSENT"
    assert result["corrected_a_approval_ready"] is True


def test_historical_roots_are_closed_world(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, _ = built
    policy = _json(documents, "historical-root-binding-v1.json")
    assert policy["historical_root_policy"] == "CLOSED_WORLD"
    assert fixture_fix.OLD_EXECUTION_ROOT in policy["accepted_roots"]
    assert fixture_fix.OUTPUT_ROOT in policy["accepted_roots"]
    assert fixture_fix.validate_historical_root_v1(fixture_fix.OLD_EXECUTION_ROOT) == "PASS"
    with pytest.raises(fixture_fix.Pair1FixtureFixError, match="historical_root_not_allowed"):
        fixture_fix.validate_historical_root_v1(
            "docs/superpowers/reports/arbitrary-report-root"
        )


def test_documents_manifest_privacy_and_external_actions_are_exact(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, result = built
    manifest = _json(documents, "sha256-manifest-v1.json")
    privacy = _json(documents, "privacy-scan-v1.json")
    assert manifest["entry_count"] == len(documents) - 1
    for entry in manifest["files"]:
        data = documents[entry["path"]]
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert privacy["privacy_match_count"] == 0
    assert privacy["raw_failed_provider_output_persisted"] is False
    assert set(result["external_actions"].values()) == {0}
    assert result["execution_authorized"] is False


def test_forward_risk_is_closed_world_and_model_boundary_is_unchanged(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, _ = built
    report = _json(documents, "forward-risk-report-v2.json")
    assert report["version"] == 2
    assert report["scope_classification"] == "closed_world"
    assert report["resolution_status"] == "case_fixed"
    assert report["model_output_boundary_changed"] is False
    assert len(report["constraint_traceability"]) == 4
    assert len(report["sibling_boundaries"]) == 5
    pair_2_to_5 = next(
        item for item in report["sibling_boundaries"]
        if item["boundary"] == "Pair 2-5 campaign fixtures"
    )
    assert pair_2_to_5["disposition"] == "not_applicable"


def test_clean_room_review_is_truthful_and_passed(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, _ = built
    review = _json(documents, "clean-room-review-v1.json")
    assert review["mode"] == "single_agent_clean_room"
    assert review["independence_claimed"] is False
    assert review["hard_issue_count"] == 0
    assert review["status"] == "passed"


def test_historical_evidence_files_remain_byte_exact() -> None:
    result = fixture_fix.verify_historical_evidence_unchanged_v1(REPO)
    assert result["historical_sealed_reference_mutation_count"] == 0
    assert result["old_execution_manifest_exact"] is True
    assert result["root_cause_manifest_exact"] is True
