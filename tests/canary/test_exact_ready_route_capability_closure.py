from __future__ import annotations

import json
from pathlib import Path

from tools.diagnostics.materialize_exact_ready_route_capability_closure import (
    ROOT,
    materialize,
)


REQUIRED_FILES = {
    "README.md",
    "baseline-binding-v1.json",
    "change-contract-v1.json",
    "exact-ready-required-route-set-v1.json",
    "required-route-historical-evidence-search-v1.json",
    "child-lingsuan-v1.json",
    "child-happy-v1.json",
    "child-doubao-v1.json",
    "child-integrator-v1.json",
    "required-route-public-evidence-v1.json",
    "required-route-capability-closure-v1.json",
    "workload-capacity-admission-v1.json",
    "workload-shape-research-v1.json",
    "route-capability-registry-delta-v1.json",
    "capacity-attempt-identity-revalidation-v1.json",
    "exact-ready-execution-plan-v1.json",
    "size-matrix-rerun-v1.json",
    "exact-ready-target-full-short-rerun-v1.json",
    "reviewer-1-final-v1.json",
    "reviewer-2-final-v1.json",
    "reviewer-3-final-v1.json",
    "strict-l3-receipt-v1.json",
    "focused-test-receipt-v1.json",
    "related-test-receipt-v1.json",
    "privacy-scan-v1.json",
    "determinism-v1.json",
    "forward-risk-report-v1.json",
    "readiness-disposition-v1.json",
    "pre-authorization-final-report-v1.md",
    "sha256-manifest-v1.json",
}


def test_materializer_seals_blocked_required_routes_without_guessing() -> None:
    repo = Path(__file__).resolve().parents[2]
    materialize(repo)
    root = repo / ROOT
    assert REQUIRED_FILES <= {path.name for path in root.iterdir()}

    closure = json.loads(
        (root / "required-route-capability-closure-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert closure["required_route_capability_closure"] == "BLOCKED"
    assert closure["exact_ready_plan_unknown_required_route_count"] == 5
    assert closure["exact_ready_plan_unknown_required_unique_route_count"] == 3
    assert closure["route_with_guessed_context_window_count"] == 0
    assert closure["route_with_guessed_max_output_count"] == 0
    assert {item["role"] for item in closure["remaining"]} == {
        "planning", "draft", "polish", "final_review", "maintenance",
    }

    delta = json.loads(
        (root / "route-capability-registry-delta-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert delta["before_sha256"] != delta["after_sha256"]
    assert delta["changed_record_count"] == 1
    assert delta["scheduling_change_count"] == 0

    readiness = json.loads(
        (root / "readiness-disposition-v1.json").read_text(encoding="utf-8")
    )
    assert readiness["trustworthy_full_short_readiness"] == "NO"
    assert readiness["final_authorization_ready"] == "NO"
    assert readiness["full_short"] == "NOT_EXECUTED"
    assert readiness["exact_ready_workload_capacity_verified_count"] == 0
    assert readiness["required_route_with_insufficient_capacity_evidence_count"] == 7
    assert readiness["route_with_guessed_capability_count"] == 0
    assert readiness["exact_next_gate"] == (
        "FULL_SHORT_REQUIRED_ROUTE_CAPABILITY_MANUAL_EVIDENCE_OR_"
        "ROUTE_DECISION_REQUIRED"
    )
    assert all(value == 0 for value in readiness["external_boundary"].values())


def test_public_evidence_rejects_unbound_third_party_capacity_claims() -> None:
    repo = Path(__file__).resolve().parents[2]
    materialize(repo)
    evidence = json.loads(
        (repo / ROOT / "required-route-public-evidence-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["status"] == "PARTIAL_CLOSURE_ONE_DIRECT_ROUTE_PROMOTED"
    assert evidence["provider_api_call_count"] == 0
    assert sum(
        bool(item["accepted_for_verification"]) for item in evidence["sources"]
    ) == 1
