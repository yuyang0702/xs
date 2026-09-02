from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from novel_flywheel.stage_capacity import CAPACITY_FAILURE_IDS_V3


SCRIPT = (
    Path(__file__).parents[2]
    / "tools" / "quality" / "full_short_capacity_fault_campaign.py"
)
SPEC = importlib.util.spec_from_file_location(
    "full_short_capacity_fault_campaign_v3", SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
CAMPAIGN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CAMPAIGN
SPEC.loader.exec_module(CAMPAIGN)


MASTER_V3_SCENARIOS = (
    "missing_capability_record", "unknown_blocked_required_route",
    "unknown_blocked_unused_route", "stale_evidence",
    "evidence_wrong_operator", "relay_inherits_upstream",
    "capability_registry_version_drift", "route_fingerprint_drift",
    "context_window_exceeded", "output_limit_mismatch",
    "estimator_uncertainty", "legitimate_recovery_attempt_delta",
    "illegal_route_delta", "illegal_authority_delta",
    "illegal_output_cap_delta", "exact_ready_review_capacity_edge",
    "20k_edge", "30k_edge", "restart_after_logical_envelope",
    "restart_after_physical_plan",
)


def test_v3_campaign_covers_all_registered_failures_and_master_scenarios(
    tmp_path: Path,
) -> None:
    report = CAMPAIGN.run_capacity_fault_campaign_v3(tmp_path)

    assert report["status"] == "PASS"
    assert report["master_enumerated_scenario_count"] == 20
    assert tuple(item["scenario_id"] for item in report["results"]) == (
        MASTER_V3_SCENARIOS
    )
    injected = {
        item["failure_id"] for item in report["results"]
        if item["failure_id"] is not None
    }
    injected.update(
        item["failure_id"]
        for item in report["supplemental_registered_failure_proofs"]
    )
    assert injected == CAPACITY_FAILURE_IDS_V3
    assert report["registered_capacity_failure_coverage"] == "100_PERCENT"
    assert report["coverage_kind"] == (
        "REGISTERED_FAILURE_ADAPTER_INJECTION"
    )
    assert report["production_observer_behavior_coverage_claimed"] is False


def test_unused_unknown_and_legal_recovery_delta_are_not_faults(
    tmp_path: Path,
) -> None:
    report = CAMPAIGN.run_capacity_fault_campaign_v3(tmp_path)
    allowed = {
        item["scenario_id"]: item for item in report["results"]
        if item["classification"] == "ALLOWED_BY_POLICY"
    }

    assert set(allowed) == {
        "unknown_blocked_unused_route",
        "legitimate_recovery_attempt_delta",
    }
    assert all(item["failure_id"] is None for item in allowed.values())
    assert all(item["dispatch_attempt_count"] == 0 for item in allowed.values())
    assert all(item["no_authority_mutation"] is True for item in allowed.values())


def test_v3_campaign_is_hash_deterministic(tmp_path: Path) -> None:
    first = CAMPAIGN.run_capacity_fault_campaign_v3(tmp_path / "first")
    second = CAMPAIGN.run_capacity_fault_campaign_v3(tmp_path / "second")

    assert first == second
    assert first["report_sha256"] == second["report_sha256"]
    assert first["credential_lookup_count"] == 0
    assert first["network_call_count"] == 0
    assert first["model_call_count"] == 0
    assert first["full_short_execution_count"] == 0
