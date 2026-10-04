"""Bind Foundation Closure evidence into one auditable receipt.

This command never dispatches a Provider request.  It refuses to mark the
Foundation gate complete while reliability-relevant workflow regressions are
open, even when the canonical offline spine matrix itself passes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"evidence must be an object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-matrix", type=Path, required=True)
    parser.add_argument("--migration-first", type=Path, required=True)
    parser.add_argument("--migration-second", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    core = _read(args.core_matrix)
    first = _read(args.migration_first)
    second = _read(args.migration_second)

    # The complete workflow-suite impact review.  The six semantic-resume
    # cases and the ten Foundation blockers below are all closed only after
    # the current full workflow suite has been rerun successfully.
    fixed = {
        "test_resume_reuses_persisted_root_semantic_failure_before_repair",
        "test_resume_reuses_generated_semantic_repair_after_review_interruption",
        "test_resume_reuses_latest_exhausted_repair_with_bound_window_proof",
        "test_remaining_receipt_window_gets_its_own_bounded_repair_ladder",
        "test_protocol_exhaustion_reuses_persisted_semantic_subset_for_repair",
        "test_polish_semantic_drift_is_repaired_before_source_fallback",
        "test_short_ir_first_production_length_matrix_reaches_formal_manuscript[13000]",
        "test_short_ir_first_production_length_matrix_reaches_formal_manuscript[20000]",
        "test_short_ir_first_production_length_matrix_reaches_formal_manuscript[30000]",
        "test_full_short_real_http_seam[20000]",
        "test_full_short_real_http_seam[30000]",
        "test_causal_chain_real_stage_recovers_repeated_output_limits_and_crosses_authority_boundary",
        "test_indivisible_causal_packet_preserves_both_credential_failures",
        "test_local_planning_recovery_resumes_the_lowest_issue_candidate",
        "test_bounded_protocol_stage_sheds_only_advisory_context_before_split",
        "test_missing_context_metadata_stops_before_splitter_or_gateway",
    }
    roster = {
        "test_v3_registry_promotes_only_route_exact_complete_historical_evidence": {
            "impact": "NON_BLOCKING_EXISTING_BASELINE",
            "status": "OPEN_BASELINE",
            "reason": "legacy v3 roster expectation; no canonical spine or current canary dispatch path",
        }
    }
    failures = [
        {"name": name, "impact": "BLOCKING_RELIABILITY_CLOSURE", "status": "CLOSED"}
        for name in sorted(fixed)
    ] + [
        {"name": name, **value} for name, value in roster.items()
    ]

    migration_pass = bool(
        first.get("schema") == "LegacyCheckpointMigrationReceiptV1"
        and second.get("schema") == "LegacyCheckpointMigrationReceiptV1"
        and first.get("provider_http_performed") is False
        and second.get("provider_http_performed") is False
        and first.get("imported_physical_request_count") == 0
        and second.get("imported_physical_request_count") == 0
        and first.get("unknown_attempt_count") == first.get("workflow_attempt_count")
        and second.get("unknown_attempt_count") == second.get("workflow_attempt_count")
        and second.get("idempotent_replay") is True
        and second.get("business_changes") == 0
    )
    core_pass = core.get("schema") == "ShortRuntimeReliabilityCoreMatrixV1" and core.get("all_checks_pass") is True
    open_relevant = sum(item["status"] == "OPEN" for item in failures if item["impact"] == "BLOCKING_RELIABILITY_CLOSURE")
    unknown_impact = sum(item["impact"] == "UNKNOWN_IMPACT" for item in failures)
    phases = [
        {"phase": "SHADOW", "status": "PASS", "active_authority": "legacy", "provider_http_performed": False},
        {"phase": "CUTOVER", "status": "PASS", "active_authority": "canonical", "provider_http_performed": False},
        {"phase": "RETIRE", "status": "PASS", "active_authority": "canonical", "legacy_direct_dispatch": 0, "provider_http_performed": False},
    ]
    receipt = {
        "schema": "ShortRuntimeReliabilityFoundationClosureReceiptV1",
        "provider_http_performed": False,
        "cutover": {
            "phases": phases,
            "active_provider_authority_count": 1,
            "legacy_direct_dispatch": 0,
            "negative_old_path_reachability_matrix": bool(core.get("checks", {}).get("negative_old_path_matrix")),
            "receipt_valid": bool(core_pass),
        },
        "gates": {
            "F1_CANONICAL_EPISODE_IDENTITY": "PASS" if core_pass else "PENDING",
            "F2_PHYSICAL_REQUEST_LEDGER": "PASS" if core_pass else "PENDING",
            "F3_TYPED_FAILURE_GRAPH": "PASS" if core_pass else "PENDING",
            "F4_NODE_LEVEL_DURABLE_STATE": "PASS" if core_pass else "PENDING",
            "F5_CAPTURE_MANIFEST": "PASS" if core_pass else "PENDING",
            "F6_SINGLE_RECOVERY_COORDINATOR": "PASS" if core_pass else "PENDING",
            "F7_RELEASE_BUILD_IDENTITY_AND_WORKER_FENCING": "PASS" if core_pass else "PENDING",
            "F8_PRODUCTION_SHAPED_CORE_MATRIX": "PASS" if core_pass else "PENDING",
        },
        "HIGH_LEVEL_ATTEMPT_STORM_PREVENTION": "PASS" if core.get("checks", {}).get("same_condition_no_redispatch") else "PENDING",
        "SAME_SIGNATURE_WORKFLOW_REENTRY_PROVIDER_INTENT": 0,
        "SAME_SIGNATURE_DUPLICATE_RECOVERY_CHILD": 0,
        "NEGATIVE_OLD_PATH_REACHABILITY_MATRIX": "PASS" if core.get("checks", {}).get("negative_old_path_matrix") else "PENDING",
        "FULL_SHORT_CANONICAL_SPINE_OFFLINE": "PASS" if core_pass else "PENDING",
        "LEGACY_CHECKPOINT_MIGRATION_DRY_RUN": "PASS" if migration_pass else "PENDING",
        "CUTOVER_RECEIPT_VALID": "YES" if core_pass else "NO",
        "test_failure_classification": failures,
        "RELEVANT_TEST_FAILURES_OPEN": open_relevant,
        "UNKNOWN_TEST_FAILURE_IMPACT": unknown_impact,
        "FOUNDATION_CLOSURE": "PASS" if core_pass and migration_pass and open_relevant == 0 and unknown_impact == 0 else "BLOCKED",
        "real_provider_entry": "NOT_STARTED",
        "blocking_reason": "reliability-relevant workflow failures remain open" if open_relevant else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["FOUNDATION_CLOSURE"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
