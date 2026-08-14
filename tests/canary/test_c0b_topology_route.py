from copy import deepcopy
import hashlib

import pytest

from tools.canary.provider_matrix import (
    BOUNDED_UNKNOWN_ALLOWED_FOR_SMOKE,
    production_mirror_manifest,
    protocol_evidence_matrix,
    validate_production_mirror,
)
from tools.canary.descriptors import C0B_MAXIMUM_OUTPUT_TOKENS_PER_DISPATCH
from tools.canary.route_policy import (
    ApprovedRoutePolicy, CanaryRouteBlocked, RouteObservation,
)
from tools.canary.topology import (
    C0BElapsedBudgetV1,
    c0b_short_call_topology_v1,
    expand_dispatch_schedule,
    verify_topology_source_contract,
)


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_exact_production_mirror_route_manifest() -> None:
    manifest = production_mirror_manifest()
    assert manifest["schema"] == "ProductionMirrorRouteManifestV1"
    assert len(manifest["routes"]) == 8
    assert validate_production_mirror(manifest["routes"])["status"] == "EXACT_MATCH"


def test_unapproved_fallback_and_protocol_drift_are_detected() -> None:
    routes = deepcopy(production_mirror_manifest()["routes"])
    routes[0]["fallback_model"] = "unexpected"
    assert validate_production_mirror(routes)["status"] == "ROUTE_DRIFT"
    protocols = protocol_evidence_matrix(production_mirror_manifest()["routes"])
    happy = next(item for item in protocols["entries"] if item["provider"] == "happy")
    assert happy["status"] == "PARTIAL_EVIDENCE"


def test_unknown_max_output_is_bounded_not_a_hard_blocker() -> None:
    matrix = production_mirror_manifest()["capability_evidence"]
    row = next(item for item in matrix if item["model"] == "qwen-3.7-plus")
    assert row["max_output"] == "UNKNOWN"
    assert row["readiness"] == BOUNDED_UNKNOWN_ALLOWED_FOR_SMOKE


def test_unknown_capability_route_still_has_a_strict_canary_output_cap() -> None:
    route = {
        "provider_descriptor_hash": h("provider"),
        "model_binding_hash": h("model"), "protocol": "anthropic",
        "maximum_canary_output_tokens": C0B_MAXIMUM_OUTPUT_TOKENS_PER_DISPATCH,
    }
    policy = ApprovedRoutePolicy([{
        "role": "draft", "allowed_stages": ["draft"],
        "primary": route, "fallback": route,
    }])
    with pytest.raises(CanaryRouteBlocked, match="route_output_cap_exceeded"):
        policy.verify(RouteObservation(
            stage="draft", role="draft", ordinal=1, route_kind="primary",
            provider_descriptor_hash=h("provider"), model_binding_hash=h("model"),
            protocol="anthropic", contract_sha256=None,
            output_budget=C0B_MAXIMUM_OUTPUT_TOKENS_PER_DISPATCH + 1,
            retry_fallback_reason=None,
        ))


def test_exact_call_topology_matches_observed_normal_and_hard_cap() -> None:
    topology = c0b_short_call_topology_v1()
    assert topology["expected_logical_boundaries"] == 16
    assert topology["per_boundary_route_schedule"] == {
        "primary": 1, "protocol_retry": 1,
        "configured_fallback": 1, "fallback_retry": 1,
    }
    components = topology["maximum_components"]
    assert topology["maximum_total_paid_dispatches"] == sum(components.values())
    assert topology["maximum_total_paid_dispatches"] > 64
    assert topology["first_terminal_stop"] is True
    schedule = expand_dispatch_schedule(topology["maximum_primary_calls"])
    assert len(schedule) == topology["maximum_total_paid_dispatches"]
    assert schedule[-1]["ordinal"] == 144


def test_static_topology_invariants_are_present_in_current_sources() -> None:
    root = __import__("pathlib").Path(__file__).parents[2]
    workflows = (root / "src" / "novel_flywheel" / "workflows.py").read_text(
        encoding="utf-8"
    )
    quality = (root / "src" / "novel_flywheel" / "quality.py").read_text(
        encoding="utf-8"
    )
    contract = (root / "src" / "novel_flywheel" / "contract_runtime.py").read_text(
        encoding="utf-8"
    )
    assert verify_topology_source_contract(workflows + quality + contract)["status"] == "exact"


def test_elapsed_budget_is_topology_derived_and_enforced() -> None:
    topology = c0b_short_call_topology_v1()
    elapsed = C0BElapsedBudgetV1.from_topology(topology)
    assert elapsed.hard_launcher_timeout_seconds >= elapsed.worst_legal_run_seconds
    assert elapsed.worst_legal_run_seconds != 180 * topology["maximum_total_paid_dispatches"]
    elapsed.require_remaining(elapsed.hard_launcher_timeout_seconds - 1)
    with pytest.raises(TimeoutError, match="elapsed_budget_exceeded"):
        elapsed.require_remaining(elapsed.hard_launcher_timeout_seconds + 1)
