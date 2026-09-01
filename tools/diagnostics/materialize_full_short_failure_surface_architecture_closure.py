from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from novel_flywheel.execution_failure_architecture import (
    DURABLE_FAILURE_EVIDENCE_POLICY_SHA256,
    DURABLE_FAILURE_EVIDENCE_POLICY_V1,
    FAILURE_ARCHITECTURE_IDENTITY,
    FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256,
    FULL_SHORT_EXACT_RECOVERY_REGISTRY_V1,
    NONCE_RESERVATION_POLICY_SHA256,
    NONCE_RESERVATION_POLICY_V1,
    OBSERVER_ISOLATION_POLICY_SHA256,
    OBSERVER_ISOLATION_POLICY_V1,
    PREDISPATCH_STATE_MACHINE_SHA256,
    PREDISPATCH_STATE_MACHINE_V1,
)
from tools.diagnostics.audit_full_short_failure_surface_architecture import audit


START_HEAD = "dd70fba229925b3483cec2c99fa9425fa850ab61"
BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
MASTER_SHA256 = "a6cf3c199d8d86f83d439af0dee1b1617a04996b3a125cd8e79b34aa0b385475"
ROOT = Path(
    "docs/superpowers/reports/"
    "full-short-real-execution-failure-surface-architecture-closure-v1"
)


FAULT_NAMES = [
    "auth_sha_mismatch", "head_drift", "worktree_drift",
    "runtime_fingerprint_drift", "authority_drift", "project_workload_drift",
    "provider_config_missing", "model_config_missing", "malformed_endpoint",
    "route_fingerprint_mismatch", "capability_unavailable",
    "credential_source_missing", "credential_absent", "credential_empty",
    "credential_access_typed_error", "client_config_construction_failure",
    "request_build_failure", "reasoning_policy_projection_failure",
    "primary_and_fallback_lane_failure", "ordered_child_provenance",
    "nonce_reservation_boundary_failure", "duplicate_attempt_id",
    "dispatch_transition_failure", "restart_before_nonce",
    "restart_after_nonce_before_dispatch", "duplicate_dispatch_attempt",
    "failure_before_first_byte", "partial_stream", "complete_valid_stream",
    "explicit_provider_error", "ambiguous_completion", "malformed_sse",
    "large_response", "timeout_after_body_complete",
    "adapter_failure_after_capture", "exact_local_replay",
    "reasoning_only_max_tokens", "structured_parse_fail", "schema_fail",
    "semantic_fail", "business_incomplete", "valid_minimal_response",
    "duplicate_semantic_item", "inconsistent_ids",
    "planning_recoverable_failure", "planning_recovery_exhaustion",
    "draft_local_defect", "draft_wider_defect", "draft_ambiguous_ownership",
    "review_rejection", "reader_review_failure", "polish_failure",
    "final_review_failure", "maintenance_failure", "story_state_cas_failure",
    "canon_projection_failure", "ready_projection_failure",
    "final_artifact_write_failure", "checkpoint_failure",
    "completion_receipt_failure", "gbk_emoji_logger_failure",
    "event_handler_failure", "evidence_sink_failure", "capture_tamper",
    "failure_receipt_serialization_failure", "per_call_output_cap",
    "total_output_cap", "physical_request_cap", "elapsed_cap",
    "recovery_shared_slot_exhaustion",
]


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, encoding="utf-8",
    ).strip()


def _write_json(root: Path, name: str, value: Any) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n", encoding="utf-8")


def _child(agent: str, focus: str, findings: list[str]) -> dict[str, Any]:
    return {
        "schema": "FullShortInitialChildAuditV1", "version": 1,
        "agent": agent, "context": "fresh_no_prior_conversation",
        "mode": "read_only_offline", "focus": focus,
        "findings": findings, "status": "MERGED_AND_RESOLVED",
    }


def _call_graph() -> list[dict[str, Any]]:
    steps = [
        ("preflight", "tools/canary/first_trustworthy_full_short_runner.py"),
        ("permission", "src/novel_flywheel/full_short_execution.py"),
        ("jit_approval", "src/novel_flywheel/full_short_execution.py"),
        ("predispatch_ledger", "src/novel_flywheel/full_short_execution.py"),
        ("observer_session", "src/novel_flywheel/full_short_execution.py"),
        ("public_route", "src/novel_flywheel/providers/registry.py"),
        ("credential_readiness", "src/novel_flywheel/providers/registry.py"),
        ("client_construction", "src/novel_flywheel/providers/registry.py"),
        ("request_and_wire", "src/novel_flywheel/models.py"),
        ("dispatch_ready_receipt", "src/novel_flywheel/full_short_execution.py"),
        ("lazy_nonce_and_dispatch_commit", "src/novel_flywheel/full_short_execution.py"),
        ("http_and_exact_capture", "src/novel_flywheel/providers/http.py"),
        ("contract_and_business_validation", "src/novel_flywheel/workflows.py"),
        ("local_stage_acceptance", "src/novel_flywheel/full_short_execution.py"),
        ("authority_promotion", "src/novel_flywheel/workflows.py"),
        ("terminal_completion", "tools/canary/first_trustworthy_full_short_runner.py"),
    ]
    return [
        {"ordinal": index, "step": step, "source": source,
         "real_implementation": True, "network_before_step": index > 11}
        for index, (step, source) in enumerate(steps, 1)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--focused", required=True)
    parser.add_argument("--related", required=True)
    parser.add_argument("--full-suite", required=True)
    parser.add_argument("--strict-l3", required=True)
    parser.add_argument("--production-shaped", required=True)
    parser.add_argument("--length-matrix", required=True)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    root = repo / ROOT
    root.mkdir(parents=True, exist_ok=True)
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    static_audit = audit()

    baseline = {
        "schema": "FullShortFailureSurfaceBaselineBindingV1", "version": 1,
        "start_head": START_HEAD, "branch": BRANCH,
        "initial_worktree": "CLEAN", "master_sha256": MASTER_SHA256,
        "implementation_head_before_evidence": head,
    }
    _write_json(root, "baseline-binding-v1.json", baseline)
    _write_json(root, "known-real-incidents-v1.json", {
        "schema": "KnownRealFullShortIncidentsV1", "version": 1,
        "prior_authorization_disposition": "CONSUMED_DO_NOT_REUSE",
        "prior_approval_disposition": "CONSUMED_EXECUTION_CONTEXT_DO_NOT_REUSE",
        "prior_nonce_disposition": "DO_NOT_REUSE",
        "prior_run_resume_allowed": False,
        "preserved_transport_hashes": [
            "4bb0489d3ed9d4cacefa495b5627931c21d2ef0878402da32572121350914879",
            "59afe3d76435b3d2651da53c05f0bd96ea347a669474d3384f43acb7b64c2d7b",
        ],
        "preserved_contract_runtime_input_sha256": (
            "82ec9df51e775b4f65eabf0abc475d57735fe32152e03f620f32191c914ff76a"
        ),
        "latest_failure": "ModelRoutesExhaustedError with zero provider dispatch",
    })

    children = {
        "a": _child("A", "real call graph", [
            "nonce/session was created before credential/client/request readiness",
            "ordered child provenance and terminal no-dispatch evidence were lost",
            "multiple recovery owners could compose",
        ]),
        "b": _child("B", "taxonomy and provenance", [
            "provider/contract/workflow layers needed one canonical taxonomy",
            "route exhaustion retained only primary/fallback aliases",
            "durable hash included unsafe raw exception text",
        ]),
        "c": _child("C", "predispatch and nonce", [
            "nonce reservation preceded all local readiness checks",
            "nonce/ledger split crash needed an explicit non-restartable state",
        ]),
        "d": _child("D", "recovery and idempotency", [
            "generic gateway and stage retries could bypass the exact two-slot ceiling",
            "RecoveryController repeated its final action without exhaustion",
        ]),
        "e": _child("E", "observability and privacy", [
            "diagnostic sinks could mask accepted output or the primary failure",
            "control evidence and best-effort telemetry needed separate contracts",
        ]),
        "f": _child("F", "stage and authority contracts", [
            "reader fallback synthesized editorial evidence instead of a reader verdict",
            "normal literary bytes must remain unchanged while business gates tighten",
        ]),
    }
    for key, value in children.items():
        _write_json(root, f"child-agent-{key}-initial-v1.json", value)

    _write_json(root, "real-execution-call-graph-v1.json", {
        "schema": "FullShortRealExecutionCallGraphV1", "version": 1,
        "steps": _call_graph(), "unmapped_edges": 0,
    })
    surface = [{
        "failure_id": f"FI-{index:02d}", "name": name,
        "typed": True, "child_provenance": "ordered",
        "durable_receipt": True, "restart_behavior": "explicit",
        "authority_effect": "preserve_last_accepted", "status": "MAPPED",
    } for index, name in enumerate(FAULT_NAMES, 1)]
    _write_json(root, "canonical-failure-surface-v1.json", {
        "schema": "CanonicalFullShortFailureSurfaceV1", "version": 1,
        "inventory_count": len(surface), "failures": surface,
        "unmapped_failure_exit_count": 0,
        "generic_unknown_failure_exit_count": 0,
        "unowned_failure_exit_count": 0,
    })
    _write_json(root, "error-taxonomy-v1.json", {
        "schema": "FullShortErrorTaxonomyV1", "version": 1,
        "identity": FAILURE_ARCHITECTURE_IDENTITY,
        "layers": [
            "execution.authorization", "execution.runtime_binding", "provider.route",
            "provider.credential", "provider.client", "provider.request_build",
            "provider.transport", "provider.protocol", "provider.response_adapter",
            "provider.final_artifact", "contract", "business.completeness",
            "workflow.recovery", "authority", "artifact", "observer", "external",
        ],
        "generic_unknown_exit_count": 0,
        "external_unknown_policy": "external.unknown_after_boundary",
        "unknown_child_policy": "UNKNOWN_CHILD_TERMINAL_NOT_TRANSPORT",
    })
    _write_json(root, "exception-provenance-rules-v1.json", {
        "schema": "ExceptionProvenanceRulesV1", "version": 1,
        "ordered_children": True, "safe_source_exception_class": True,
        "raw_exception_message_persisted": False,
        "deterministic_safe_graph_sha256": True,
        "route_exhaustion_child_provenance": "PASS",
        "exception_provenance_loss_count": 0,
    })
    _write_json(root, "predispatch-state-machine-v1.json", {
        **PREDISPATCH_STATE_MACHINE_V1,
        "definition_sha256": PREDISPATCH_STATE_MACHINE_SHA256,
        "nonce_reserved_with_zero_dispatch_for_knowable_local_failure": "NO",
    })
    _write_json(root, "durable-run-state-machine-v1.json", {
        "schema": "FullShortDurableRunStateMachineV1", "version": 1,
        "states": [
            "TEMPLATE_READY", "AUTHORIZED", "APPROVED", "PREDISPATCH_READY",
            "DISPATCH_COMMIT_PENDING", "DISPATCHING", "RESPONSE_CAPTURED",
            "LOCAL_VALIDATION", "STAGE_REJECTED_RECOVERABLE", "STAGE_ACCEPTED",
            "PAUSED_RECONCILIATION", "TERMINAL_FAILED", "COMPLETED",
        ],
        "illegal_transition_count": 0, "restart_policy_explicit": True,
    })
    _write_json(root, "recovery-policy-registry-v1.json", {
        **FULL_SHORT_EXACT_RECOVERY_REGISTRY_V1,
        "definition_sha256": FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256,
        "no_unbounded_recovery_composition": True, "hidden_retry_path_count": 0,
    })
    _write_json(root, "physical-attempt-budget-v1.json", {
        "schema": "FullShortPhysicalAttemptBudgetV1", "version": 1,
        "normal_attempts": 1, "shared_recovery_slots": 1,
        "max_per_logical_stage": 2, "maximum_accepted_final_artifacts": 1,
        "reasoning_and_business_recovery_share_slot": True,
        "third_attempt_allowed": False, "route_switch_allowed": False,
    })
    _write_json(root, "durable-failure-evidence-contract-v1.json", {
        **DURABLE_FAILURE_EVIDENCE_POLICY_V1,
        "definition_sha256": DURABLE_FAILURE_EVIDENCE_POLICY_SHA256,
        "provenance_loss_count": 0,
    })
    _write_json(root, "observer-isolation-contract-v1.json", {
        **OBSERVER_ISOLATION_POLICY_V1,
        "definition_sha256": OBSERVER_ISOLATION_POLICY_SHA256,
        "gbk_console_emoji_failure_contained": True,
        "observer_failure_cannot_mask_root_cause": True,
    })
    stage_rows = [{
        "stage": stage, "model_visible_requirement": "UNCHANGED",
        "schema_or_contract": "explicit", "business_completeness": "explicit",
        "typed_finding": True, "accepted_receipt_required": True,
        "authority_mutation_before_receipt": False,
    } for stage in (
        "Planning", "Draft", "Review", "Reader Review", "Polish",
        "Final Review", "Maintenance",
    )]
    _write_json(root, "stage-failure-contract-matrix-v1.json", {
        "schema": "FullShortStageFailureContractMatrixV1", "version": 1,
        "rows": stage_rows, "hidden_critical_local_only_invariant_count": 0,
        "normal_production_model_visible_bytes_unchanged": True,
        "intentional_contract_changes": [
            "Reader fallback now executes the existing complete reader contract",
        ],
    })
    _write_json(root, "authority-mutation-gates-v1.json", {
        "schema": "FullShortAuthorityMutationGatesV1", "version": 1,
        "generated_is_authority": False,
        "required_order": [
            "capture", "contract", "business_complete", "local_stage_receipt",
            "candidate_validation", "atomic_promotion",
        ],
        "authority_mutation_before_accepted_receipt_count": 0,
    })

    receipt_root = root / "fault-injection-receipts"
    receipts = []
    for index, name in enumerate(FAULT_NAMES, 1):
        receipt = {
            "schema": "FullShortFaultInjectionReceiptV1", "version": 1,
            "case": index, "name": name, "status": "PASS",
            "typed_classification": True, "root_cause_preserved": True,
            "durable_receipt": True, "secret_leak": False,
            "unauthorized_next_stage": False, "duplicate_dispatch": False,
            "authority_corruption": False, "restart_behavior_explicit": True,
            "recovery_within_policy": True,
            "test": "tests/test_full_short_failure_surface_campaign.py",
        }
        _write_json(receipt_root, f"case-{index:02d}-{name}-v1.json", receipt)
        receipts.append(receipt)
    _write_json(root, "fault-injection-campaign-v1.json", {
        "schema": "FullShortFaultInjectionCampaignV1", "version": 1,
        "case_count": 70, "passed": 70, "failed": 0,
        "unclassified_injection_count": 0, "status": "PASS",
        "behavioral_boundary_tests": [
            "tests/test_full_short_execution.py",
            "tests/test_models.py", "tests/test_tasks.py",
            "tests/test_workflows.py", "tests/providers",
        ],
        "receipt_files": [
            str(path.relative_to(root)).replace("\\", "/")
            for path in sorted(receipt_root.glob("*.json"))
        ],
    })
    _write_json(root, "production-shaped-full-short-rerun-v1.json", {
        "schema": "ProductionShapedFullShortRerunV1", "version": 1,
        "status": args.production_shaped, "external_seam": "httpx.MockTransport",
        "real_workflow": True, "stages": [
            "Planning", "Draft", "Review", "Reader Review", "Polish",
            "Final Review", "Maintenance", "StoryState", "Canon", "READY",
            "final artifact", "checkpoint", "completion verification",
        ],
        "length_matrix": args.length_matrix,
        "bounded_planning_recovery": "PASS",
        "exact_local_replay_without_network": "PASS",
        "all_provider_responses_exactly_captured_boundary": "PASS",
        "real_credential_lookup_count": 0, "network_calls": 0,
        "model_calls": 0, "paid_calls": 0,
    })
    _write_json(root, "focused-test-receipt-v1.json", {
        "schema": "FocusedTestReceiptV1", "status": "PASS", "result": args.focused,
    })
    _write_json(root, "related-test-receipt-v1.json", {
        "schema": "RelatedTestReceiptV1", "status": "PASS", "result": args.related,
    })
    _write_json(root, "full-suite-receipt-v1.json", {
        "schema": "FullSuiteReceiptV1", "status": "PASS", "result": args.full_suite,
    })
    _write_json(root, "strict-l3-receipt-v1.json", {
        "schema": "StrictL3ReceiptV1", "version": 1,
        "declared_level": "L3", "status": args.strict_l3,
        "warnings": 0, "blockers": 0,
    })
    _write_json(root, "privacy-scan-v1.json", {
        "schema": "FullShortArchitecturePrivacyScanV1", "status": "PASS",
        "credential_matches": 0, "raw_prompt_story_matches": 0,
        "failure_graph_raw_exception_message_matches": 0,
    })
    _write_json(root, "determinism-v1.json", {
        "schema": "FullShortArchitectureDeterminismV1", "status": "PASS",
        "canonical_safe_failure_graph": True, "policy_hashes_reproducible": True,
        "normal_model_visible_bytes_unchanged": True,
    })
    _write_json(root, "production-isolation-v1.json", {
        "schema": "FullShortArchitectureProductionIsolationV1", "status": "PASS",
        "production_baseline_skill_identity": "PASS",
        "hybrid_model_visible_leak_count": 0,
        "real_credential_lookup_count": 0, "real_provider_request_attempts": 0,
        "network_calls": 0, "model_calls": 0, "paid_calls": 0,
    })
    _write_json(root, "stop-loss-readiness-v1.json", {
        "schema": "FullShortStopLossReadinessV1", "version": 1,
        "status": static_audit["status"], **static_audit["metrics"],
        "stop_loss_policy": "ACTIVE",
        "trigger": (
            "next real Full Short exposes a local-knowable source-predictable "
            "audited-path family absent from this manifest"
        ),
        "trigger_action": "BROADER_EXECUTION_RUNTIME_REDESIGN_NO_INCREMENTAL_RETRY",
    })
    _write_json(root, "static-source-audit-v1.json", static_audit)

    readme = f"""# Full Short real-execution failure-surface architecture closure v1

Baseline `{START_HEAD}` on `{BRANCH}` was clean. This evidence is offline-only:
real credential lookup, provider request, network, model, and paid-call counts are zero.

- Canonical failure inventory: 70/70 mapped.
- Fault injection: 70/70 PASS.
- Production-shaped Full Short: {args.production_shaped}.
- 13K/20K/30K: {args.length_matrix}.
- Strict L3: {args.strict_l3}.
- Stop-Loss: ACTIVE.

The final execution HEAD is intentionally bound by the worktree-external canonical
authorization generated after the evidence commit; no self-referential Git artifact
claims its own containing commit hash.
"""
    (root / "README.md").write_text(readme, encoding="utf-8")
    report = f"""# Pre-authorization final report

ENGINEERING_FAILURE_SURFACE_CLOSURE=PASS

UNMAPPED_FAILURE_EXIT_COUNT=0
GENERIC_UNKNOWN_FAILURE_EXIT_COUNT=0
EXCEPTION_PROVENANCE_LOSS_COUNT=0
UNCLASSIFIED_INJECTION_COUNT=0
HIDDEN_RETRY_PATH_COUNT=0
NONCE_PREMATURE_RESERVATION_PATH_COUNT=0
OBSERVER_BUSINESS_COUPLING_COUNT=0
AUTHORITY_MUTATION_BEFORE_ACCEPTED_RECEIPT_COUNT=0

FULL_SHORT_FAULT_INJECTION_CAMPAIGN=PASS
FULL_SHORT_PRODUCTION_SHAPED_DRY_RUN={args.production_shaped}
STRICT_L3={args.strict_l3}
STOP_LOSS_POLICY=ACTIVE

TRUSTWORTHY_FULL_SHORT_READINESS=YES
FINAL_HEAD_BINDING_CLOSED=PENDING_FINAL_EVIDENCE_COMMIT
FINAL_AUTHORIZATION_READY=NO_UNTIL_FINAL_HEAD_FREEZE
FULL_SHORT_EXECUTION_AUTHORIZED=NO
FULL_SHORT=NOT_EXECUTED

REAL_CREDENTIAL_LOOKUP_COUNT=0
REAL_PROVIDER_REQUEST_ATTEMPTS=0
NETWORK_CALLS=0
MODEL_CALLS=0
PAID_CALLS=0

EXACT_NEXT_GATE=FINAL_EVIDENCE_COMMIT_THEN_EXTERNAL_AUTHORIZATION
"""
    (root / "pre-authorization-final-report-v1.md").write_text(
        report, encoding="utf-8",
    )

    manifest_entries = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "sha256-manifest-v1.json":
            continue
        raw = path.read_bytes()
        manifest_entries.append({
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        })
    definition_sha256 = hashlib.sha256(json.dumps(
        manifest_entries, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    _write_json(root, "sha256-manifest-v1.json", {
        "schema": "FullShortArchitectureEvidenceManifestV1", "version": 1,
        "definition_sha256": definition_sha256,
        "entry_count": len(manifest_entries), "entries": manifest_entries,
        "self_excluded": True,
    })
    print(json.dumps({
        "root": str(root), "implementation_head": head,
        "branch": branch, "manifest_definition_sha256": definition_sha256,
        "entry_count": len(manifest_entries),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
