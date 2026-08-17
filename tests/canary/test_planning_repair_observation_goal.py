from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools.canary.goal_stop import CanaryObservationGoalReachedStop
from tools.canary.planning_repair_goal_stop import (
    PlanningRepairObservationGoalLatch,
)


def h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def envelope(event_type: str, payload: dict) -> dict:
    return {
        "event_type": event_type,
        "stage_id": "planning",
        "observation_status": "confirmed",
        "payload": payload,
    }


def domain_failure() -> dict:
    return envelope("diagnostic_planning_repair_domain", {
        "schema": "PlanningRepairDomainValidationSnapshotV1",
        "domain_result": "failed",
        "substage": "planning_repair_patch",
        "receipt_sha256": h("domain"),
        "domain_rule_codes": ["planning_repair_patch.authority_mismatch"],
        "exact_field_paths": ["$.authority_sha256"],
        "invariant_ids": ["repair_authority_fresh"],
        "normalized_payload_sha256": h("payload"),
        "normalized_payload_shape_sha256": h("shape"),
        "repair_target_identity_sha256": h("target-identity"),
    })


def propagation() -> dict:
    return envelope("diagnostic_planning_repair_finding_propagation", {
        "schema": "PlanningRepairFindingPropagationSnapshotV1",
        "source_finding_receipt_sha256": h("domain"),
        "source_attempt_ordinal": 1,
        "target_attempt_ordinal": 2,
        "finding_count": 1,
        "exact_rule_codes": ["planning_repair_patch.authority_mismatch"],
        "exact_field_paths": ["$.authority_sha256"],
        "finding_propagation_status": "exact",
        "repair_request_semantic_sha256": h("request"),
        "receipt_sha256": h("propagation"),
    })


def fallback_shape() -> dict:
    return envelope("diagnostic_provider_content_block_shape", {
        "schema": "ProviderContentBlockShapeSnapshotV1",
        "route_kind": "configured_fallback",
        "snapshot_sha256": h("provider-shape"),
        "content_block_count": 1,
        "content_block_type_sequence": ["text"],
        "text_block_count": 1,
        "tool_call_block_count": 0,
        "reasoning_block_count": 0,
        "total_visible_text_chars": 10,
        "tool_argument_presence": False,
        "tool_argument_byte_length": 0,
        "stop_reason": "end_turn",
        "usage_output_tokens": 8,
        "zero_visible": False,
        "max_tokens": False,
        "requested_max_output_tokens": 1977,
    })


def test_primary_evidence_waits_for_safe_planning_exit(tmp_path: Path) -> None:
    latch = PlanningRepairObservationGoalLatch(
        receipt_path=tmp_path / "goal.json",
    )
    assert latch.observe(domain_failure()) is True
    assert latch.observe(propagation()) is True
    assert latch.reached is False
    latch.before_dispatch(stage="planning", boundary_ordinal=3)
    assert latch.snapshot()["primary_evidence_status"] == "captured"


def test_primary_evidence_stops_before_next_major_stage(tmp_path: Path) -> None:
    latch = PlanningRepairObservationGoalLatch(
        receipt_path=tmp_path / "goal.json",
    )
    latch.observe(domain_failure())
    latch.observe(propagation())
    with pytest.raises(CanaryObservationGoalReachedStop):
        latch.before_dispatch(stage="causal_chain", boundary_ordinal=3)
    snapshot = latch.snapshot()
    assert snapshot["observation_goal_outcome"] == "PRIMARY_EVIDENCE_CAPTURED"
    assert snapshot["terminal_amplifier_status"] == "not_reexercised"
    assert snapshot["first_blocked_boundary_ordinal"] == 3


def test_natural_fallback_after_primary_evidence_reaches_goal(tmp_path: Path) -> None:
    latch = PlanningRepairObservationGoalLatch(
        receipt_path=tmp_path / "goal.json",
    )
    latch.observe(domain_failure())
    latch.observe(propagation())
    assert latch.observe(fallback_shape()) is True
    assert latch.reached is True
    with pytest.raises(CanaryObservationGoalReachedStop):
        latch.before_dispatch(stage="planning", boundary_ordinal=4)
    assert latch.snapshot()["terminal_amplifier_status"] == "captured"


def test_no_target_stops_at_planning_exit_without_fabricating_evidence(
    tmp_path: Path,
) -> None:
    latch = PlanningRepairObservationGoalLatch(
        receipt_path=tmp_path / "goal.json",
    )
    latch.before_dispatch(stage="planning", boundary_ordinal=1)
    with pytest.raises(CanaryObservationGoalReachedStop):
        latch.before_dispatch(stage="causal_chain", boundary_ordinal=2)
    snapshot = latch.snapshot()
    assert snapshot["observation_goal_outcome"] == (
        "PLANNING_REPAIR_OBSERVATION_TARGET_NOT_EXERCISED"
    )
    assert snapshot["domain_failure_snapshot"] is None
    assert snapshot["finding_propagation_snapshot"] is None


def test_first_exact_domain_and_propagation_win_idempotently(tmp_path: Path) -> None:
    latch = PlanningRepairObservationGoalLatch(
        receipt_path=tmp_path / "goal.json",
    )
    assert latch.observe(domain_failure()) is True
    assert latch.observe(domain_failure()) is False
    assert latch.observe(propagation()) is True
    assert latch.observe(propagation()) is False
    snapshot = latch.snapshot()
    assert snapshot["duplicate_observation_count"] == 2
    assert snapshot["raw_content_included"] is False

