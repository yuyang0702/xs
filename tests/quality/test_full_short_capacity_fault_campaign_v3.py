from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).parents[2] / "tools" / "quality" / "full_short_capacity_fault_campaign.py"
SPEC = importlib.util.spec_from_file_location("full_short_capacity_fault_campaign_v3", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CAMPAIGN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CAMPAIGN
SPEC.loader.exec_module(CAMPAIGN)

MASTER_V3_SCENARIOS = (
    "missing_capability_record", "unknown_blocked_required_route",
    "unknown_blocked_unused_route", "stale_evidence", "evidence_wrong_operator",
    "relay_inherits_upstream", "capability_registry_version_drift",
    "route_fingerprint_drift", "context_window_exceeded",
    "output_limit_mismatch", "estimator_uncertainty",
    "legitimate_recovery_attempt_delta", "illegal_route_delta",
    "illegal_authority_delta", "illegal_output_cap_delta",
    "exact_ready_review_capacity_edge", "20k_edge", "30k_edge",
    "restart_after_logical_envelope", "restart_after_physical_plan",
)


@pytest.fixture
def report(tmp_path: Path) -> dict[str, object]:
    return CAMPAIGN.run_capacity_fault_campaign_v3(tmp_path)


def test_v3_campaign_executes_all_twenty_named_production_probes(report) -> None:
    assert report["status"] == "PASS"
    assert tuple(item["scenario_id"] for item in report["results"]) == MASTER_V3_SCENARIOS
    assert all(
        item["execution_mode"] == "PRODUCTION_PRIMITIVE"
        and item["production_behavior_exercised"] is True
        and item["status"] == "PASS"
        for item in report["results"]
    )
    assert report["scenario_coverage"] == "20_PRODUCTION_PRIMITIVE_PROBES"
    assert report["static_policy_assertion_count"] == 0
    assert report["v3_capacity_fault_injection_coverage"] == "100_PERCENT"
    assert report["coverage_kind"] == "NAMED_PRODUCTION_PRIMITIVE_BEHAVIOR"
    assert report["registered_capacity_failure_coverage"] == "REGISTRY_MEMBERSHIP_ONLY"


def test_allowed_routes_recovery_and_capacity_edges_are_observed(report) -> None:
    by_id = {item["scenario_id"]: item for item in report["results"]}
    assert by_id["unknown_blocked_unused_route"]["unused_unknown_allowed"] is True
    assert by_id["legitimate_recovery_attempt_delta"]["allowed_delta_accepted"] is True
    assert by_id["exact_ready_review_capacity_edge"]["admission_status"] == "PASS"
    assert by_id["20k_edge"]["admission_status"] == "PASS"
    assert by_id["30k_edge"]["parent_status"] == "WINDOWING_REQUIRED"
    assert by_id["30k_edge"]["complete_token_coverage"] == 30_000


def test_capacity_failures_are_produced_and_durably_classified(report) -> None:
    by_id = {item["scenario_id"]: item for item in report["results"]}
    expected = {
        "missing_capability_record": "capacity.route_capability_unknown",
        "unknown_blocked_required_route": "capacity.route_capability_unknown",
        "context_window_exceeded": "capacity.context_window_exceeded",
        "output_limit_mismatch": "capacity.output_reserve_unsatisfied",
        "estimator_uncertainty": "capacity.estimator_uncertainty_exceeded",
        "illegal_route_delta": "capacity.invalid_attempt_delta",
        "illegal_authority_delta": "capacity.physical_attempt_drift",
        "illegal_output_cap_delta": "capacity.invalid_attempt_delta",
    }
    for scenario_id, failure_id in expected.items():
        assert by_id[scenario_id]["failure_id"] == failure_id
        assert by_id[scenario_id]["expected_failure_id"] == failure_id
        assert by_id[scenario_id]["typed_failure"] is True
        assert by_id[scenario_id]["durable_receipt"] is True


def test_report_states_narrow_scope_instead_of_claiming_observer_or_full_short(report) -> None:
    assert report["production_observer_behavior_coverage_claimed"] is True
    assert "not Full Short" in report["narrow_scope_scenarios"]["17_18"]
    assert "durable store reopen" in report["narrow_scope_scenarios"]["19_20"]
    assert report["credential_lookup_count"] == 0
    assert report["network_call_count"] == 0
    assert report["model_call_count"] == 0
    assert report["full_short_execution_count"] == 0


def test_restart_probes_reopen_durable_state_and_fail_closed_without_dispatch(
    report,
) -> None:
    by_id = {item["scenario_id"]: item for item in report["results"]}
    logical = by_id["restart_after_logical_envelope"]
    physical = by_id["restart_after_physical_plan"]
    assert logical["reopened_durable_store"] is True
    assert physical["physical_plan_reopened"] is True
    for item in (logical, physical):
        assert item["restart_blocked"] is True
        assert item["restart_reason"] == "OBSERVER_ALREADY_CLAIMED_NO_RESTART"
        assert item["dispatch_attempt_count"] == 0


def test_a_missing_behavior_probe_makes_campaign_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = CAMPAIGN._run_v3_probe

    def mutate(scenario_id: str, artifact_dir: Path):
        result = original(scenario_id, artifact_dir)
        return {**result, "status": "FAIL"} if scenario_id == "route_fingerprint_drift" else result

    monkeypatch.setattr(CAMPAIGN, "_run_v3_probe", mutate)
    assert CAMPAIGN.run_capacity_fault_campaign_v3(tmp_path)["status"] == "FAIL"


def test_v3_campaign_is_hash_deterministic(tmp_path: Path) -> None:
    first = CAMPAIGN.run_capacity_fault_campaign_v3(tmp_path / "first")
    second = CAMPAIGN.run_capacity_fault_campaign_v3(tmp_path / "second")
    assert first == second
    assert first["report_sha256"] == second["report_sha256"]


def test_cli_defaults_to_v3_campaign(tmp_path: Path) -> None:
    output = tmp_path / "v3-report.json"
    assert CAMPAIGN.main(["--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "FullShortCapacityFaultCampaignV3"
    assert payload["scenario_coverage"] == "20_PRODUCTION_PRIMITIVE_PROBES"
