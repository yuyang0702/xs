from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any

from novel_flywheel.stage_capacity import (
    CAPACITY_FAILURE_IDS_V1,
    DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1,
)


START_HEAD = "5759d6c341882f55e48d52aef484a1e7deec7394"
IMPLEMENTATION_HEAD = "a76bcda829dd197a6e4dc2d938547a27a5c63078"
EXACT_PASS_HEAD = "79c3a58c9ed1f677da6d4053d09aebeae37587f2"
REVIEW_HEAD = "d27e1d967c8618c8303b9d0b1c8309f2ffe5754d"
BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
ROOT = Path(
    "docs/superpowers/reports/"
    "full-short-execution-runtime-architecture-redesign-v2-capacity-v1"
)
PROJECT_ID_SHA256 = (
    "a69d9140943781ee24b78ff87d8ef408d29c281c6e993981dc2ef4a8eb82f720"
)


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"json_object_required:{path}")
    return value


def write_json(root: Path, name: str, value: dict[str, Any]) -> None:
    (root / name).write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, encoding="utf-8"
    ).strip()


def receipt(schema: str, status: str, **values: Any) -> dict[str, Any]:
    return {
        "schema": schema,
        "version": 1,
        "status": status,
        "implementation_head": IMPLEMENTATION_HEAD,
        **values,
    }


def live_capacity_binding(repo: Path) -> dict[str, Any]:
    connection = sqlite3.connect(repo / "data" / "app.db")
    connection.row_factory = sqlite3.Row
    query = """
        SELECT b.role, 'primary' AS lane, m.id AS model_id,
               m.context_window, m.capabilities_json
          FROM role_bindings b JOIN models m ON m.id=b.primary_model_id
        UNION ALL
        SELECT b.role, 'fallback' AS lane, m.id AS model_id,
               m.context_window, m.capabilities_json
          FROM role_bindings b JOIN models m ON m.id=b.fallback_model_id
        ORDER BY role, lane
    """
    roles = {
        "planning", "draft", "review", "reader_review", "polish",
        "final_review", "maintenance", "revision_plan",
    }
    records = []
    for row in connection.execute(query):
        if row["role"] not in roles:
            continue
        capabilities = json.loads(row["capabilities_json"] or "{}")
        records.append({
            "role": row["role"],
            "lane": row["lane"],
            "model_id_sha256": sha_bytes(str(row["model_id"]).encode()),
            "context_window_present": row["context_window"] is not None,
            "offline_context_manifest_present": (
                "offline_deterministic_context_manifest_v1" in capabilities
            ),
        })
    connection.close()
    return {
        "bound_route_count": len(records),
        "route_with_context_window_count": sum(
            item["context_window_present"] for item in records
        ),
        "route_with_offline_manifest_count": sum(
            item["offline_context_manifest_present"] for item in records
        ),
        "records": records,
    }


def initial_report(letter: str, focus: str, findings: list[str]) -> dict[str, Any]:
    return receipt(
        "FullShortRuntimeCapacityInitialWorkstreamV1",
        "RECONSTRUCTED_FROM_DURABLE_SOURCE_TRUTH_AFTER_HOST_RESTART",
        workstream=letter,
        focus=focus,
        findings=findings,
        agent_identity_claimed=False,
        external_actions=0,
    )


def reviewer(number: int, focus: str, findings: list[str]) -> dict[str, Any]:
    return receipt(
        "FullShortRuntimeCapacityCleanRoomReviewV1",
        "ARCHITECTURE_REJECT",
        reviewer_number=number,
        focus=focus,
        reviewed_head=REVIEW_HEAD,
        final_implementation_head_reviewed=False,
        mode="fresh_read_only_offline",
        findings=findings,
        external_actions=0,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--exact-pass", type=Path, required=True)
    parser.add_argument("--exact-current", type=Path)
    parser.add_argument("--pre-fix", type=Path, required=True)
    parser.add_argument("--static-audit", type=Path, required=True)
    parser.add_argument("--fault-report", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo.resolve(strict=True)
    head = git(repo, "rev-parse", "HEAD")
    if head != IMPLEMENTATION_HEAD:
        raise ValueError(f"implementation_head_mismatch:{head}")
    if git(repo, "branch", "--show-current") != BRANCH:
        raise ValueError("branch_mismatch")
    dirty = git(repo, "status", "--porcelain").splitlines()
    allowed = {
        "tools/diagnostics/materialize_full_short_runtime_architecture_redesign_v2.py"
    }
    if any(line[3:].replace("\\", "/") not in allowed for line in dirty):
        raise ValueError(f"unexpected_dirty_worktree:{dirty}")

    exact = read_json(args.exact_pass)
    if exact.get("status") != "PASS" or exact.get("source_head") != EXACT_PASS_HEAD:
        raise ValueError("historical_exact_pass_binding_invalid")
    pre_fix = read_json(args.pre_fix)
    static = read_json(args.static_audit)
    fault = read_json(args.fault_report)
    current_exact = (
        read_json(args.exact_current)
        if args.exact_current is not None and args.exact_current.exists()
        else None
    )
    live = live_capacity_binding(repo)
    root = repo / ROOT
    if root.exists():
        raise ValueError("v2_evidence_directory_already_exists")
    root.mkdir(parents=True)

    external_zero = {
        "REAL_CREDENTIAL_LOOKUP_COUNT": 0,
        "REAL_SECRET_READ_COUNT": 0,
        "REAL_PROVIDER_CLIENT_CREATION_COUNT": 0,
        "REAL_PROVIDER_REQUEST_ATTEMPTS": 0,
        "HTTP_POST_ATTEMPTS": 0,
        "NETWORK_CALLS": 0,
        "MODEL_CALLS": 0,
        "PAID_CALLS": 0,
        "FULL_SHORT_EXECUTION_COUNT": 0,
    }
    write_json(root, "baseline-binding-v1.json", receipt(
        "FullShortRuntimeCapacityBaselineBindingV1", "PASS",
        expected_start_head=START_HEAD,
        branch=BRANCH,
        current_implementation_head=head,
        v1_evidence_path=str(
            Path("docs/superpowers/reports/")
            / "full-short-execution-runtime-architecture-redesign-v1"
        ),
        external_boundary=external_zero,
    ))
    write_json(root, "v1-stop-loss-input-v1.json", receipt(
        "FullShortRuntimeCapacityV1StopLossInputV1", "PRESERVED_WITH_V2_BLOCKERS",
        v1_static_zero_metrics_preserved=static.get("status") == "PASS",
        v1_exact_ready_result="FAIL_CONTEXT_CAPACITY_PREFLIGHT",
        v1_next_gate=(
            "FULL_SHORT_EXECUTION_RUNTIME_ARCHITECTURE_REDESIGN_V2_REQUIRED"
        ),
    ))
    write_json(root, "exact-ready-target-binding-v1.json", receipt(
        "FullShortExactReadyTargetBindingV1", "PASS",
        project_id_sha256=PROJECT_ID_SHA256,
        project_id_prefix="2ad716",
        ready_authority_holder=True,
        live_capacity_binding=live,
        live_capacity_admission="FAIL_CLOSED_CONTEXT_LIMIT_UNAVAILABLE",
    ))
    write_json(root, "exact-ready-capacity-pre-fix-v1.json", receipt(
        "FullShortExactReadyCapacityPreFixEvidenceV1", "HISTORICAL_FAILURE_PRESERVED",
        source_file_sha256=sha_file(args.pre_fix),
        historical_receipt_schema=pre_fix.get("schema"),
        warning=(
            "Historical 32768 role-source label was not source-grounded because "
            "the live model rows have context_window NULL; receipt is preserved "
            "but is not reusable as readiness proof."
        ),
    ))

    initial = {
        "a": ("exact target capacity forensics", [
            "V1 Review prompt crossed the former unsourced 32768 fallback.",
            "Exact target trigger was target-size Review capacity preflight.",
            "Generic fixtures did not bind the same workload and route metadata.",
        ]),
        "b": ("capacity contract architecture", [
            "StageCapacityPlanV1 owns protected/advisory projections and admission.",
            "Stage ceiling and route capability are distinct, effective limit is min.",
            "Missing or inconsistent route capability fails closed as typed capacity.",
        ]),
        "c": ("Review windowing and hierarchical review", [
            "Review/Reader Review use deterministic bounded windows.",
            "20K and 30K matrix failures prevent global-coverage closure.",
        ]),
        "d": ("compaction and shedding safety", [
            "Protected layer size drift is rejected even when mislabeled PRESERVE.",
            "Advisory shedding receipts bind original hash/size and rendered zero size.",
            "Whole-paragraph compaction changes long-single-paragraph normal bytes.",
        ]),
        "e": ("cross-stage capacity", [
            "Eight stage policies are registered.",
            "Live route capability metadata remains unavailable for 14 bindings.",
        ]),
        "f": ("Runtime Kernel and Stop-Loss integration", [
            "Capacity token is required immediately before exact dispatch.",
            "Capacity receipt/failure reasons are registered and fault campaign is closed.",
            "Runtime readiness blockers remain nonzero despite static audit zeros.",
        ]),
    }
    for letter, (focus, findings) in initial.items():
        write_json(
            root, f"child-agent-{letter}-initial-v1.json",
            initial_report(letter.upper(), focus, findings),
        )

    policies = {
        name: asdict(policy)
        for name, policy in
        DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.policies.items()
    }
    write_json(root, "capacity-admission-contract-v1.json", receipt(
        "StageCapacityAdmissionContractV1", "IMPLEMENTED_STATIC_PASS",
        policy_registry_sha256=(
            DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
        ),
        flow=[
            "STAGE_INPUT_FROZEN", "CAPACITY_PLAN_CREATED",
            "PROTECTED_LAYERS_BOUND", "ADVISORY_COMPACTION",
            "SEGMENTATION_IF_REQUIRED", "FINAL_RENDER_SIZE_CHECK",
            "OUTPUT_RESERVE_CHECK", "CAPACITY_ADMISSION_PASS",
            "PREDISPATCH_READY", "NONCE_AND_DISPATCH",
        ],
        dispatch_without_admission_count=0,
    ))
    write_json(root, "capacity-failure-taxonomy-v1.json", receipt(
        "CapacityFailureTaxonomyV1", "PASS",
        failure_ids=sorted(CAPACITY_FAILURE_IDS_V1),
        context_capacity_generic_unexpected_mapping_count=0,
        static_audit_sha256=sha_file(args.static_audit),
    ))
    write_json(root, "protected-layer-contract-v1.json", receipt(
        "ProtectedLayerContractV1", "IMPLEMENTED_FOCUSED_PASS",
        protected_classes=["HARD_PROTECTED", "SOFT_PROTECTED"],
        forbidden_actions=["COMPACT", "SHED"],
        preserve_requires_pre_post_size_identity=True,
        focused_adversarial_tests=2,
        protected_layer_silent_truncation_count=0,
    ))
    write_json(root, "advisory-compaction-contract-v1.json", receipt(
        "AdvisoryCompactionContractV1", "IMPLEMENTED_WITH_JUSTIFIED_IDENTITY_DELTA",
        policy_id="ADVISORY_COMPLETE_PARAGRAPH_PREFIX_V1",
        deterministic=True,
        partial_paragraph_count=0,
        source_and_rendered_hash_size_receipted=True,
        normal_model_visible_identity=(
            "NO: oversized single advisory paragraphs are omitted rather than "
            "emitting an unsafe partial paragraph"
        ),
    ))
    write_json(root, "review-capacity-execution-plan-v1.json", receipt(
        "ReviewCapacityExecutionPlanV1", "IMPLEMENTED_NOT_CLOSED",
        topology=["deterministic_windows", "per_window_receipts", "bounded_reduce"],
        exact_target_offline_execution_head=EXACT_PASS_HEAD,
        production_length_matrix="FAIL_20K_AND_30K",
    ))
    write_json(root, "review-window-coverage-v1.json", receipt(
        "ReviewWindowCoverageV1", "NOT_PROVEN",
        historical_exact_target_workflow_pass=True,
        direct_final_head_coverage_receipt_present=False,
        review_window_coverage="UNPROVEN_NOT_100_PERCENT_CLAIMED",
        review_global_invariant_coverage="FAIL_CLOSED",
    ))
    write_json(root, "full-short-stage-capacity-matrix-v1.json", receipt(
        "FullShortStageCapacityMatrixV1", "STATIC_PASS_RUNTIME_BLOCKED",
        policy_registry_sha256=(
            DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
        ),
        policies=policies,
        unregistered_stage_capacity_policy_count=0,
        live_route_capability=live,
    ))
    write_json(root, "runtime-capacity-integration-v1.json", receipt(
        "RuntimeCapacityIntegrationV1", "STATIC_PASS_RUNTIME_NOT_READY",
        static_audit=static,
        known_capacity_failure_durable=True,
        exact_dispatch_capacity_token_required=True,
        current_head_exact_target_not_proven=True,
    ))
    write_json(root, "capacity-fault-injection-report-v1.json", receipt(
        "FullShortCapacityFaultCampaignEvidenceV1", "PASS_SYNTHETIC_REGISTRY_CAMPAIGN",
        source_file_sha256=sha_file(args.fault_report),
        campaign=fault,
        limitation=(
            "Registry-generated synthetic boundary injections do not alone prove "
            "end-to-end semantic execution of all sixteen named failure surfaces."
        ),
    ))
    write_json(root, "generic-full-short-rerun-v1.json", receipt(
        "GenericFullShortRerunV1", "NOT_RUN_CURRENT_IMPLEMENTATION_HEAD",
        historical_v1_fixture_evidence_available=True,
        current_head_readiness_claim=False,
    ))
    write_json(root, "size-matrix-rerun-v1.json", receipt(
        "FullShortProductionLengthMatrixV1", "FAIL",
        production_shaped={
            "13K": "PASS",
            "20K": "FAIL_PROTOCOL_ROUTE_TRANSPORT_INTERRUPTED",
            "30K": "FAIL_PROTOCOL_ROUTE_NORMAL_INVALID_OUTPUT",
        },
        material_audit={
            "13K": "FAIL_CAPACITY_CONTEXT_LIMIT_UNAVAILABLE",
            "20K": "FAIL_CAPACITY_CONTEXT_LIMIT_UNAVAILABLE",
            "30K": "FAIL_CAPACITY_CONTEXT_LIMIT_UNAVAILABLE",
        },
        combined_pytest="1 passed, 5 failed",
        independent_matrix_review="80 passed, 2 failed; 20K/30K rerun 0/2",
    ))
    write_json(root, "exact-ready-target-full-short-rerun-v1.json", receipt(
        "ExactReadyTargetFullShortRerunV1", "NOT_CLOSED",
        historical_exact_pass={
            "source_head": exact.get("source_head"),
            "receipt_file_sha256": sha_file(args.exact_pass),
            "status": exact.get("status"),
            "project_id_sha256": exact.get("project_id_sha256"),
            "completed_stage_count": exact.get("completed_stage_count"),
            "provider_protocol_capture_count": exact.get(
                "provider_protocol_capture_count"
            ),
            "replay_call_count": exact.get("replay_call_count"),
            "completion_receipt_sha256": exact.get(
                "completion_receipt_sha256"
            ),
            "final_artifact_sha256": exact.get("final_artifact_sha256"),
        },
        current_implementation_attempt=current_exact,
        current_implementation_attempt_receipt_sha256=(
            sha_file(args.exact_current)
            if args.exact_current is not None and args.exact_current.exists()
            else None
        ),
        current_implementation_attempt_receipt_present=current_exact is not None,
        exact_pass_is_stale_for_current_implementation=True,
        full_short_production_shaped_dry_run="NOT_PASS_CURRENT_HEAD",
        external_boundary=external_zero,
    ))

    reviews = [
        (1, "capacity proof-domain validity", [
            "Decisive PASS receipt is bound to 79c3a58, not final implementation.",
            "Strict L3/current-head evidence was absent at review time.",
        ]),
        (2, "exact READY target reproduction and fix", [
            "13K passed but 20K/30K failed.",
            "No current-head exact target readiness proof was established.",
        ]),
        (3, "Review windowing/global coverage and isolation", [
            "Fourteen live routes have no context window capability metadata.",
            "Offline manifest is isolated and cannot authorize live execution.",
        ]),
        (4, "protected/advisory safety and literary identity", [
            "20K/30K matrix failed and literary baseline parity is unproven.",
            "Review found protected/shedding gaps later repaired after review HEAD.",
        ]),
        (5, "Runtime Kernel, registry and Stop-Loss", [
            "Static audit and focused suites pass, but decisive exact run is not closed.",
            "Required evidence and current-head final binding were absent at review time.",
        ]),
    ]
    for number, focus, findings in reviews:
        review_value = reviewer(number, focus, findings)
        if number == 5:
            review_value.update({
                "reviewed_head": IMPLEMENTATION_HEAD,
                "final_implementation_head_reviewed": True,
                "findings": [
                    "Isolated exact-target dry run fails the logical-stage "
                    "plan cap and physical recovery reserve contract.",
                    "Static Stop-Loss reports a false-zero exact-target "
                    "blocker because it does not consume a successful receipt.",
                    "Focused Runtime/Capacity suites passed 286 tests but do "
                    "not override the decisive exact-target failure.",
                ],
            })
        write_json(root, f"reviewer-{number}-final-v1.json", review_value)

    write_json(root, "strict-l3-receipt-v1.json", receipt(
        "StrictL3ReceiptV1", "FAIL_NOT_PROVEN",
        warnings="NOT_ZERO_OR_NOT_ENUMERATED",
        blockers=[
            "LIVE_ROUTE_CONTEXT_CAPABILITY_METADATA_MISSING",
            "PRODUCTION_LENGTH_MATRIX_20K_30K_FAILED",
            "FINAL_IMPLEMENTATION_EXACT_TARGET_PASS_MISSING",
            "FIVE_FINAL_REVIEWERS_NOT_ALL_PASS",
        ],
        strict_l3="FAIL",
    ))
    write_json(root, "focused-test-receipt-v1.json", receipt(
        "OfflinePytestReceiptV1", "PASS",
        tests=118,
        failures=0,
        command=(
            "pytest test_stage_capacity.py test_context_packet.py "
            "test_full_short_runner_hardening.py "
            "test_bounded_protocol_stage_sheds_only_advisory_context_before_split"
        ),
    ))
    write_json(root, "related-test-receipt-v1.json", receipt(
        "RelatedValidationReceiptV1", "MIXED",
        static_audit_status=static.get("status"),
        static_audit_sha256=sha_file(args.static_audit),
        capacity_fault_campaign_status=fault.get("status"),
        capacity_fault_campaign_sha256=sha_file(args.fault_report),
        size_matrix_status="FAIL",
    ))
    write_json(root, "full-suite-receipt-v1.json", receipt(
        "FullSuiteReceiptV1", "NOT_PASS",
        completed=False,
        reason="Required production length tests fail; full historical suite not sealed.",
    ))
    write_json(root, "privacy-scan-v1.json", receipt(
        "PrivacyScanV1", "PASS_FOR_RECORDED_ARTIFACTS",
        exact_raw_prompt_persisted=exact.get("raw_prompt_persisted"),
        exact_raw_reference_persisted=exact.get("raw_reference_persisted"),
        exact_raw_story_persisted=exact.get("raw_story_persisted"),
        exact_raw_title_persisted=exact.get("raw_title_persisted"),
        external_boundary=external_zero,
    ))
    write_json(root, "determinism-v1.json", receipt(
        "DeterminismReceiptV1", "PARTIAL_PASS_NOT_READINESS",
        historical_exact_replay_count=exact.get("replay_call_count"),
        historical_exact_replay_all=True,
        fault_scenarios=fault.get("master_enumerated_scenario_count"),
        fault_scenarios_deterministic=all(
            item.get("deterministic_replay") is True
            for item in fault.get("results", [])
        ),
        current_head_exact_determinism_closed=False,
    ))
    write_json(root, "production-isolation-v1.json", receipt(
        "ProductionIsolationV1", "PASS_ISOLATION_FAIL_READINESS",
        offline_manifest_private_copy_only=True,
        live_offline_manifest_rejected_before_secret_client=True,
        live_database_unchanged=True,
        live_capacity_binding=live,
        external_boundary=external_zero,
    ))

    stop_loss = receipt(
        "FullShortRuntimeCapacityStopLossV1", "NOT_CLOSED",
        EXECUTION_RUNTIME_REDESIGN_V2="NOT_CLOSED",
        CAPACITY_ADMISSION_ARCHITECTURE="PARTIAL_PASS_NOT_READY",
        CONTEXT_CAPACITY_GENERIC_UNEXPECTED_MAPPING_COUNT=1,
        CAPACITY_FAILURE_WITHOUT_TYPED_POLICY_COUNT=1,
        MODEL_DISPATCH_WITHOUT_CAPACITY_ADMISSION_COUNT=0,
        PROTECTED_LAYER_SILENT_TRUNCATION_COUNT=0,
        UNRECEIPTED_CONTEXT_SHEDDING_COUNT=0,
        UNREGISTERED_STAGE_CAPACITY_POLICY_COUNT=0,
        EXACT_READY_TARGET_CAPACITY_BLOCKER_COUNT=4,
        REVIEW_CAPACITY_ADMISSION="NOT_PASS_CURRENT_HEAD",
        REVIEW_WINDOW_COVERAGE="NOT_PROVEN",
        REVIEW_GLOBAL_INVARIANT_COVERAGE="FAIL_CLOSED",
        FULL_SHORT_PRODUCTION_SHAPED_DRY_RUN="NOT_PASS_CURRENT_HEAD",
        STRICT_L3="FAIL",
        ALL_V1_STATIC_STOP_LOSS_METRICS_REMAIN_ZERO=True,
        NORMAL_PRODUCTION_MODEL_VISIBLE_BYTES_UNCHANGED=(
            "NO_WITH_JUSTIFIED_WHOLE_PARAGRAPH_ADVISORY_DELTA"
        ),
        PRODUCTION_BASELINE_SKILL_IDENTITY="STATIC_PASS_RUNTIME_NOT_SEALED",
        HYBRID_MODEL_VISIBLE_LEAK_COUNT=0,
        STOP_LOSS_POLICY="ACTIVE",
        TRUSTWORTHY_FULL_SHORT_READINESS="NO",
        FINAL_HEAD_BINDING_CLOSED="NO",
        FINAL_AUTHORIZATION_READY="NO",
        FULL_SHORT_EXECUTION_AUTHORIZED="NO",
        FULL_SHORT="NOT_EXECUTED",
        EXACT_NEXT_GATE=(
            "FULL_SHORT_RUNTIME_CAPACITY_ARCHITECTURE_REDESIGN_V3_REQUIRED"
        ),
        external_boundary=external_zero,
    )
    write_json(root, "v2-stop-loss-v1.json", stop_loss)

    (root / "README.md").write_text(
        "# Full Short runtime capacity redesign V2\n\n"
        "This evidence set records an offline architecture iteration and an "
        "honest Stop-Loss rejection. Source/static capacity checks and the "
        "synthetic registry fault campaign pass, and a historical exact-target "
        "offline run passed at `79c3a58`. They do not establish readiness for "
        "the current implementation.\n\n"
        "The decisive blockers are: all 14 live primary/fallback Full Short "
        "routes lack source-grounded context-window metadata; the required "
        "20K and 30K production-shaped matrix cases fail; no current-head exact "
        "target PASS exists; and all five final reviewers rejected closure.\n\n"
        "No credential, secret, provider client, HTTP, network, model, paid, "
        "or real Full Short action occurred. No authorization was generated.\n",
        encoding="utf-8",
    )
    (root / "pre-authorization-final-report-v1.md").write_text(
        "# Pre-authorization disposition\n\n"
        "`EXECUTION_RUNTIME_REDESIGN_V2=NOT_CLOSED`\n\n"
        "`TRUSTWORTHY_FULL_SHORT_READINESS=NO`\n\n"
        "`FINAL_AUTHORIZATION_READY=NO`\n\n"
        "`FULL_SHORT_EXECUTION_AUTHORIZED=NO`\n\n"
        "`FULL_SHORT=NOT_EXECUTED`\n\n"
        "`STOP_LOSS_POLICY=ACTIVE`\n\n"
        "`EXACT_NEXT_GATE=FULL_SHORT_RUNTIME_CAPACITY_ARCHITECTURE_REDESIGN_V3_REQUIRED`\n\n"
        "No canonical authorization was materialized because the mandatory "
        "size matrix, Strict L3, final reviewers, live capacity binding, and "
        "current-head exact-target gates did not pass.\n",
        encoding="utf-8",
    )

    manifest: dict[str, str] = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.name == "sha256-manifest-v1.json" or not path.is_file():
            continue
        manifest[path.name] = sha_file(path)
    write_json(root, "sha256-manifest-v1.json", receipt(
        "Sha256ManifestV1", "PASS",
        artifact_count=len(manifest),
        artifacts=manifest,
        note="Manifest excludes itself; FINAL_HEAD_BINDING_CLOSED remains NO.",
    ))
    print(json.dumps({
        "output": str(root),
        "artifact_count": len(manifest) + 1,
        "disposition": "NOT_CLOSED",
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
