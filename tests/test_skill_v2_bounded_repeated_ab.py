from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.diagnostics import skill_v2_bounded_repeated_ab as bounded_ab


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built() -> tuple[dict[str, bytes], dict[str, object]]:
    return bounded_ab.build_documents(REPO_ROOT, materialization_parent_head=bounded_ab.BASELINE_HEAD)


def _load(documents: dict[str, bytes], relative: str) -> dict[str, object]:
    return json.loads(documents[f"{bounded_ab.OUTPUT_ROOT}/{relative}"].decode("utf-8"))


def test_sealed_plan_becomes_exact_five_pair_ten_arm_campaign(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, result = built
    plan = _load(documents, "campaign-plan-binding-v1.json")
    budget = _load(documents, "campaign-budget-v1.json")
    pair_index = _load(documents, "pair-case-index-v1.json")

    assert result["overall_status"] == "exact"
    assert plan["sealed_pair_count"] == 5
    assert pair_index["pair_case_ids"] == list(bounded_ab.PAIR_CASE_IDS)
    assert budget["max_a_arm_real_calls"] == 5
    assert budget["max_b_arm_real_calls"] == 5
    assert budget["max_campaign_real_provider_calls"] == 10
    assert budget["max_campaign_http_posts"] == 10
    assert len(result["arm_scopes"]) == 10
    assert len(set(result["arm_scopes"])) == 10


@pytest.mark.parametrize("case_id", bounded_ab.PAIR_CASE_IDS)
def test_each_pair_is_closed_world_and_only_skill_context_differs(
    built: tuple[dict[str, bytes], dict[str, object]], case_id: str,
) -> None:
    documents, _ = built
    lock = _load(documents, f"pairs/{case_id}/pair-ab-lock-v1.json")
    fixture = _load(documents, f"pairs/{case_id}/sanitized-fixture-v1.json")
    a_packet = _load(documents, f"pairs/{case_id}/a-arm/disabled-packet-v1.json")
    b_packet = _load(documents, f"pairs/{case_id}/b-arm/disabled-packet-v1.json")

    assert fixture["repository_owned_sanitized_fixture"] is True
    assert fixture["private_user_data"] is False
    assert lock["primary_changed_variable"] == "SKILL_CONTEXT"
    assert lock["semantic_diff_keys"] == [
        "skill_context_sha256",
        "skill_profile_sha256",
        "system_sha256",
        "wire_input_sha256",
    ]
    for key in bounded_ab.AB_EQUALITY_FIELDS:
        assert lock[key] is True
    assert a_packet["pair_case_id"] == b_packet["pair_case_id"] == case_id
    assert a_packet["skill_arm"] == "CURRENT_RUNTIME_SKILL"
    assert b_packet["skill_arm"] == "RESTORED_SKILL_V2"
    assert a_packet["skill_context_sha256"] != b_packet["skill_context_sha256"]
    assert a_packet["skill_context_sha256"] == bounded_ab.CURRENT_CONTEXT_SHA256
    assert b_packet["skill_context_sha256"] == bounded_ab.RESTORED_CONTEXT_SHA256
    assert a_packet["non_skill_prompt_sha256"] == b_packet["non_skill_prompt_sha256"]
    assert a_packet["authority_input_sha256"] == b_packet["authority_input_sha256"]
    assert a_packet["story_slice_sha256"] == b_packet["story_slice_sha256"]
    assert a_packet["task_contract_sha256"] == b_packet["task_contract_sha256"]


@pytest.mark.parametrize("case_id", bounded_ab.PAIR_CASE_IDS)
@pytest.mark.parametrize("arm", ("a-arm", "b-arm"))
def test_every_arm_is_disabled_unique_and_single_dispatch(
    built: tuple[dict[str, bytes], dict[str, object]], case_id: str, arm: str,
) -> None:
    documents, _ = built
    packet = _load(documents, f"pairs/{case_id}/{arm}/disabled-packet-v1.json")
    approval = _load(documents, f"pairs/{case_id}/{arm}/approval-template-v1.json")
    nonce = _load(documents, f"pairs/{case_id}/{arm}/nonce-policy-v1.json")
    launcher = _load(documents, f"pairs/{case_id}/{arm}/launcher-binding-v1.json")

    assert packet["execution_authorized"] is False
    assert packet["usage_status"] == "unused"
    assert packet["reservation_status"] == "unreserved"
    assert packet["signed_approval"] == "ABSENT"
    assert packet["single_use_nonce"] is None
    assert approval["execution_authorized"] is False
    assert approval["named_approver"] is None
    assert approval["signed_approval"] == "ABSENT"
    assert nonce["nonce_present"] is False
    assert nonce["nonce_reservation_allowed_during_materialization"] is False
    assert launcher["packet_scope_equals_launcher_scope"] is True
    assert launcher["packet_cohort_equals_launcher_cohort"] is True
    assert launcher["hard_max_model_calls"] == 1
    assert launcher["hard_max_http_post_attempts"] == 1
    assert launcher["sdk_retries_disabled"] is True
    assert launcher["route_fallback_after_dispatch_allowed"] is False


def test_manifest_privacy_context_and_external_action_gates(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, result = built
    manifest = _load(documents, "sha256-manifest-v1.json")
    privacy = _load(documents, "privacy-scan-v1.json")
    context = _load(documents, "per-pair-skill-context-binding-v1.json")
    receipt = _load(documents, "offline-test-receipt-v1.json")

    assert manifest["entry_count"] == len(documents) - 1
    for entry in manifest["files"]:
        data = documents[entry["path"]]
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert privacy["privacy_match_count"] == 0
    assert privacy["credential_persisted"] is False
    assert privacy["raw_provider_content_persisted"] is False
    assert context["all_b_contexts_within_3000_chars"] is True
    assert all(row["b_restoration_items_present"] == "8/8" for row in context["pairs"])
    assert receipt["overall_status"] == "exact"
    assert set(result["external_actions"].values()) == {0}


def test_campaign_stops_and_approval_sequencing_are_fail_closed(
    built: tuple[dict[str, bytes], dict[str, object]],
) -> None:
    documents, _ = built
    stop = _load(documents, "campaign-stop-rules-v1.json")
    decision = _load(documents, "campaign-decision-rule-v1.json")
    approvals = _load(documents, "per-arm-approval-design-v1.json")

    assert stop["critical_quality_regression_stops_campaign"] is True
    assert stop["engineering_hard_failure_stops_campaign"] is True
    assert stop["a_b_lock_failure_stops_campaign"] is True
    assert decision["critical_pair_regression_can_be_averaged_away"] is False
    assert approvals["blanket_campaign_approval_allowed"] is False
    assert approvals["one_approval_per_real_request"] is True
    assert approvals["b_arm_approval_requires_matching_a_arm_pass"] is True
