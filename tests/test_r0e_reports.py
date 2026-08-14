from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from r0e_evidence import GATES, residual_prioritization_matrix
from r0e_report_evidence import (
    exposure_sample_plan,
    live_parity_snapshot,
    runtime_fingerprint_availability,
)


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "docs" / "superpowers" / "reports"


def test_runtime_fingerprint_is_an_explicit_real_canary_blocker() -> None:
    availability = runtime_fingerprint_availability(ROOT)

    assert availability["fingerprint_instrumentation"] == "IMPLEMENTED_R0F"
    assert availability["real_provider_canary"] == (
        "BLOCKED_BY_APPROVAL_AND_EXACT_BINDING"
    )
    assert availability["paid_llm_calls"] == 0
    assert availability["source_characterization"] == {
        "RuntimeBuildFingerprintV1_present": True,
        "run_runtime_fingerprint_field_present": True,
    }
    assert availability["phase1b_flags"]["environment_effective"] is False
    assert availability["phase1b_flags"]["project_effective"] is False


def test_zero_failure_plan_uses_exact_conservative_bounds() -> None:
    plan = exposure_sample_plan()
    rows = {row["runs"]: row for row in plan["rows"]}

    assert 0.049 < rows[59]["zero_failure_upper_bound"] < 0.050
    assert 0.029 < rows[99]["zero_failure_upper_bound"] < 0.030
    assert 0.0099 < rows[299]["zero_failure_upper_bound"] < 0.0101
    assert [rows[count]["estimated_model_calls"] for count in (59, 99, 299)] == [
        861, 1444, 4359,
    ]
    assert "canary-mixture" in plan["claim_boundary"]


def test_committed_residual_matrix_matches_parent_denominator_and_gates() -> None:
    committed = json.loads((
        REPORTS / "r0e-residual-prioritization-matrix.json"
    ).read_text(encoding="utf-8"))
    built = residual_prioritization_matrix(ROOT)

    assert committed["family_count"] == built["family_count"] == 44
    assert committed["historical_incident_count"] == 97
    assert built["historical_incident_count"] == 97
    assert {row["family"] for row in committed["rows"]} == {
        row["family"] for row in built["rows"]
    }
    assert all(row["gate"] in GATES for row in committed["rows"])
    assert all(row["policy_violation"] is None for row in committed["rows"])
    assert Counter(row["gate"] for row in committed["rows"]) == {
        "DEVELOPMENT_NO_GO": 31,
        "NOT_CURRENTLY_REACHABLE": 10,
        "NEEDS_PRODUCTION_EXPOSURE": 3,
    }
    assert all(
        item["gate"] == "MECHANISM_FIX_CANDIDATE"
        and item["historical_count"] == 0
        for item in committed["mechanism_probes"]
    )


def test_live_db_and_formal_artifact_baseline_remains_r0_identical() -> None:
    snapshot = live_parity_snapshot(ROOT)

    assert snapshot["database_sha256"] == (
        "5deb7bdf811c90366ee1342de108c53355cea1c39aff72670bacd99cd5ffab87"
    )
    assert snapshot["artifact_manifests"]["formal"]["count"] == 1
    assert snapshot["artifact_manifests"]["canon"]["count"] == 1
    assert snapshot["artifact_manifests"]["candidate"]["count"] == 0
    assert snapshot["artifact_manifests"]["checkpoint"]["count"] == 0
    assert snapshot["artifact_manifests"]["saga"]["count"] == 0
    assert snapshot["table_counts"] == {
        "story_states": 6,
        "story_candidates": 11,
        "workflow_node_checkpoints": 917,
    }


def test_final_report_stops_before_runtime_or_real_canary() -> None:
    report = (
        REPORTS / "r0e-short-post-fix-evidence-closure.md"
    ).read_text(encoding="utf-8")
    parity = json.loads((
        REPORTS / "r0e-live-parity.json"
    ).read_text(encoding="utf-8"))

    assert "BLOCKED_BY_FINGERPRINT" in report
    assert "HISTORICAL DEVELOPMENT NO-GO" in report
    assert "Paid LLM calls: 0" in report
    assert "2409 passed, 1 skipped, 5 xfailed" in report
    assert parity["parity"] == "identical"
    assert parity["src_novel_flywheel_diff_from_parent"] == []
    assert parity["paid_llm_calls"] == 0
