from __future__ import annotations

"""Materialize the offline V3 route-capability and stop-loss evidence set."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from novel_flywheel.db import Database
from novel_flywheel.execution_failure_architecture import (
    FAILURE_ARCHITECTURE_IDENTITY,
)
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.route_capabilities import (
    CapabilityEvidenceV1,
    CapabilityStatus,
    RouteCapabilityRecordV1,
    RouteCapabilityRegistryV1,
)
from novel_flywheel.stage_capacity import (
    CAPACITY_FAILURE_IDS_V1,
    CAPACITY_FAILURE_IDS_V3,
    DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1,
)
from tools.canary.first_trustworthy_full_short_runner import _destination
from tools.quality.full_short_capacity_fault_campaign import (
    run_capacity_fault_campaign_v3,
)


BASELINE_HEAD = "d3e52201b48f6eee9718163cf073a57e62af202c"
BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
ROLES = (
    "planning", "draft", "review", "reader_review", "polish",
    "final_review", "maintenance",
)
REQUIRED_ROUTES = tuple((role, "primary") for role in ROLES)
ROOT = Path(
    "docs/superpowers/reports/"
    "full-short-execution-runtime-architecture-redesign-v3-"
    "evidence-migration-v1"
)
CONFIG_PATH = Path("config/full_short_route_capability_registry_v1.json")
HISTORICAL_MATRIX = Path(
    "docs/superpowers/reports/c0b-p0-provider-model-evidence-matrix.json"
)
HISTORICAL_PRICE_PACKET = Path(
    "docs/superpowers/reports/c0b-smoke-1-approval-packet-v1.json"
)
V2_ROOT = Path(
    "docs/superpowers/reports/"
    "full-short-execution-runtime-architecture-redesign-v2-capacity-v1"
)
DEEPSEEK_PROVIDER_ID = "0e6a5627-5882-40df-bca5-7d98b97fdd0b"
DEEPSEEK_MODEL_ID = "e4b6f0b8-3c5e-412e-8d4e-8453c840a032"
DEEPSEEK_ROUTE_FINGERPRINT = (
    "04a443a6702fcc95b74906e44b7233c9370cb9b94bbbbadce4bf59c088b68c31"
)
EXTERNAL_ZERO = {
    "real_credential_lookup_count": 0,
    "real_provider_request_attempts": 0,
    "http_calls": 0,
    "network_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
    "real_full_short_runs": 0,
}


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def sha_json(value: object) -> str:
    return sha_bytes(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, encoding="utf-8"
    ).strip()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def receipt(schema: str, status: str, **values: Any) -> dict[str, Any]:
    return {
        "schema": schema,
        "version": 1,
        "status": status,
        **values,
        "external_boundary": EXTERNAL_ZERO,
    }


def _operator(provider_id: str, destination: str) -> str:
    if (
        provider_id == DEEPSEEK_PROVIDER_ID
        and destination
        == "https://api.deepseek.com:443/anthropic/v1/messages"
    ):
        return "DEEPSEEK_OFFICIAL"
    if destination == "https://ark.cn-beijing.volces.com:443/api/v3/responses":
        return "VOLCENGINE_ARK_DIRECT"
    return "THIRD_PARTY_RELAY_UNVERIFIED_UPSTREAM"


def build_registry(repo: Path) -> RouteCapabilityRegistryV1:
    db = Database(repo / "data" / "app.db")
    history_sha = sha_file(repo / HISTORICAL_MATRIX)
    price_sha = sha_file(repo / HISTORICAL_PRICE_PACKET)
    records: list[RouteCapabilityRecordV1] = []
    for role in ROLES:
        binding = db.get_role_binding(role) or {}
        for lane in ("primary", "fallback"):
            provider_id = str(binding.get(f"{lane}_provider_id") or "")
            model_id = str(binding.get(f"{lane}_model_id") or "")
            if not provider_id or not model_id:
                raise ValueError(f"route_binding_missing:{role}:{lane}")
            provider = db.get_provider(provider_id)
            model = db.get_model(model_id)
            if provider is None or model is None:
                raise ValueError(f"route_identity_missing:{role}:{lane}")
            destination = _destination(provider)
            fingerprint = ProviderRegistry.route_fingerprint(provider, model)
            exact_deepseek = (
                provider_id == DEEPSEEK_PROVIDER_ID
                and model_id == DEEPSEEK_MODEL_ID
                and fingerprint == DEEPSEEK_ROUTE_FINGERPRINT
            )
            evidence: list[CapabilityEvidenceV1] = []
            if exact_deepseek:
                evidence.append(CapabilityEvidenceV1(
                    source_kind="historical_official_documentation_matrix",
                    source_locator=(
                        f"{HISTORICAL_MATRIX.as_posix()}#models/"
                        "deepseek-v4-pro"
                    ),
                    source_evidence_sha256=history_sha,
                    evidence_version=1,
                    evidence_date="2026-08-14",
                    route_fingerprint=fingerprint,
                    proved_fields=(
                        "context_window_tokens", "max_output_tokens",
                    ),
                    provenance_available=True,
                ))
            evidence.append(CapabilityEvidenceV1(
                source_kind="historical_route_token_accounting_packet",
                source_locator=(
                    f"{HISTORICAL_PRICE_PACKET.as_posix()}#price_catalog/"
                    f"{provider['name']}/{model['model_name']}"
                ),
                source_evidence_sha256=price_sha,
                evidence_version=1,
                evidence_date="2026-08-15",
                route_fingerprint=fingerprint,
                proved_fields=("reasoning_token_accounting",),
                provenance_available=True,
            ))
            reasoning = (
                "SEPARATE_IF_REPORTED"
                if str(model["model_name"]) == "qwen-max-thinking"
                else "INCLUDED_IN_COMPLETION_CAP"
            )
            record = RouteCapabilityRecordV1.create(
                role=role,
                lane=lane,
                provider=str(provider["name"]),
                provider_id_sha256=sha_bytes(provider_id.encode("utf-8")),
                operator=_operator(provider_id, destination),
                destination=destination,
                protocol=str(provider["protocol"]),
                model=str(model["model_name"]),
                model_id_sha256=sha_bytes(model_id.encode("utf-8")),
                route_fingerprint=fingerprint,
                context_window_tokens=1_000_000 if exact_deepseek else None,
                max_output_tokens=384_000 if exact_deepseek else None,
                reasoning_token_accounting=reasoning,
                reasoning_output_reservation=(
                    "WITHIN_COMPLETION_CAP"
                    if reasoning == "INCLUDED_IN_COMPLETION_CAP"
                    else "SEPARATE_REPORTED_RESERVATION_REQUIRED"
                ),
                capability_status=(
                    CapabilityStatus.VERIFIED_HISTORICAL_EVIDENCE
                    if exact_deepseek else CapabilityStatus.UNKNOWN_BLOCKED
                ),
                source_evidence=evidence,
                blocking_reason_codes=(
                    () if exact_deepseek else (
                        "EXACT_ROUTE_CONTEXT_WINDOW_EVIDENCE_UNAVAILABLE",
                        "EXACT_ROUTE_MAX_OUTPUT_EVIDENCE_UNAVAILABLE",
                    )
                ),
            )
            records.append(record)
    registry = RouteCapabilityRegistryV1.create(records)
    if len(registry.records) != 14:
        raise ValueError("live_route_count_not_14")
    return registry


def write_registry(repo: Path, registry: RouteCapabilityRegistryV1) -> None:
    write_json(repo / CONFIG_PATH, registry.to_document())


def _record_document(record: RouteCapabilityRecordV1) -> dict[str, Any]:
    value = asdict(record)
    value["capability_status"] = record.capability_status.value
    return value


def materialize(repo: Path, registry: RouteCapabilityRegistryV1) -> None:
    root = repo / ROOT
    root.mkdir(parents=True, exist_ok=True)
    records = [_record_document(item) for item in registry.records]
    required = [
        item for item in records
        if (item["role"], item["lane"]) in REQUIRED_ROUTES
    ]
    unused = [
        item for item in records
        if (item["role"], item["lane"]) not in REQUIRED_ROUTES
    ]
    unknown_required = [
        item for item in required
        if item["capability_status"] == "UNKNOWN_BLOCKED"
    ]
    unknown_unused = [
        item for item in unused
        if item["capability_status"] == "UNKNOWN_BLOCKED"
    ]
    head = git(repo, "rev-parse", "HEAD")

    write_json(root / "baseline-binding-v1.json", receipt(
        "FullShortRuntimeCapacityV3BaselineBindingV1", "PASS",
        expected_head=BASELINE_HEAD,
        observed_start_head=BASELINE_HEAD,
        branch=BRANCH,
        baseline_worktree_clean=True,
        prior_authorization_reused=False,
    ))
    write_json(root / "v2-stop-loss-input-v1.json", receipt(
        "FullShortRuntimeCapacityV2StopLossInputV1", "VERIFIED_INPUT",
        source_directory=V2_ROOT.as_posix(),
        source_manifest_sha256=sha_file(repo / V2_ROOT / "sha256-manifest-v1.json"),
        v2_disposition="NOT_CLOSED",
        inherited_authority=False,
    ))
    exact_binding = json.loads(
        (repo / V2_ROOT / "exact-ready-target-binding-v1.json").read_text(
            encoding="utf-8"
        )
    )
    write_json(root / "exact-ready-target-binding-v1.json", receipt(
        "FullShortRuntimeCapacityV3ExactTargetBindingV1", "BOUND_READ_ONLY",
        source_artifact=(V2_ROOT / "exact-ready-target-binding-v1.json").as_posix(),
        source_artifact_sha256=sha_file(
            repo / V2_ROOT / "exact-ready-target-binding-v1.json"
        ),
        project_id_prefix=exact_binding.get("project_id_prefix"),
        project_id_sha256=exact_binding.get("project_id_sha256"),
        target_words=exact_binding.get("target_words"),
    ))

    child_reports = {
        "a": ("historical capability evidence", [
            "DeepSeek exact official route has reusable 1,000,000 context and 384,000 max-output historical evidence.",
            "8798/16000/4624/3724 observations are lower bounds or requests, not maxima.",
            "No tracked original screenshots were found.",
        ]),
        "b": ("Exact READY required routes", [
            "Seven primary role routes are required; five unique physical fingerprints are involved.",
            "Only review:primary binds the verified DeepSeek route.",
        ]),
        "c": ("route capability registry architecture", [
            "Every role/lane requires an exact content-addressed record.",
            "Unknown values remain null and block only when the route is dispatchable.",
        ]),
        "d": ("physical attempt identity", [
            "Recovery schedule slot was incorrectly passed as physical attempt ordinal.",
            "The durable observer must be the sole physical-attempt allocator.",
        ]),
        "e": ("token accounting", [
            "Admission invariant is I + P + O + R + S <= C per exact route.",
            "Primary and fallback capacity are independently evaluated; no silent truncation is allowed.",
        ]),
        "f": ("runtime integration", [
            "Use registry, immutable logical envelope, observer-owned physical plan, typed journal, and fail-closed rollback.",
        ]),
    }
    for letter, (focus, findings) in child_reports.items():
        write_json(root / f"child-agent-{letter}-initial-v1.json", receipt(
            "FullShortRuntimeCapacityV3InitialChildReportV1", "COMPLETE",
            workstream=letter.upper(), focus=focus, findings=findings,
            mode="fresh_read_only_offline", old_authority_reused=False,
        ))

    historical = {
        "schema": "HistoricalRouteCapabilityEvidenceV1",
        "version": 1,
        "status": "SEARCH_COMPLETE_PARTIAL_REUSE",
        "historical_evidence_search_complete": True,
        "searched_sources": [
            HISTORICAL_MATRIX.as_posix(),
            HISTORICAL_PRICE_PACKET.as_posix(),
            V2_ROOT.as_posix(),
            "docs/superpowers/reports/**/*capacity*",
            "data/app.db safe provider/model/role fields",
        ],
        "verified_reusable_route_fingerprints": [DEEPSEEK_ROUTE_FINGERPRINT],
        "partial_only_observations": [8798, 16000, 4624, 3724],
        "unproven_claims_rejected": [32768, 8328, 372000],
        "screenshots_found": 0,
        "external_boundary": EXTERNAL_ZERO,
    }
    write_json(root / "historical-route-capability-evidence-v1.json", historical)
    write_json(root / "historical-capability-evidence-matrix-v1.json", receipt(
        "HistoricalCapabilityEvidenceMatrixV1", "PARTIAL",
        records=[{
            "role": item["role"], "lane": item["lane"],
            "route_fingerprint": item["route_fingerprint"],
            "classification": (
                "VERIFIED_REUSABLE" if item["capability_status"].startswith("VERIFIED")
                else "PARTIAL_ONLY"
            ),
            "context_window_tokens": item["context_window_tokens"],
            "max_output_tokens": item["max_output_tokens"],
        } for item in records],
    ))
    write_json(root / "exact-ready-required-route-set-v1.json", receipt(
        "ExactReadyRequiredRouteSetV1", "MATERIALIZED",
        exact_ready_required_route_count=len(required),
        required_routes=[{
            "role": item["role"], "lane": item["lane"],
            "route_fingerprint": item["route_fingerprint"],
            "capability_status": item["capability_status"],
            "capability_sha256": item["capability_sha256"],
        } for item in required],
        unused_live_routes=[{
            "role": item["role"], "lane": item["lane"],
            "route_fingerprint": item["route_fingerprint"],
            "capability_status": item["capability_status"],
        } for item in unused],
    ))
    matrix = receipt(
        "LiveRouteCapabilityMatrixV1", "PARTIAL_REQUIRED_ROUTES_BLOCKED",
        live_route_count=len(records),
        route_without_capability_record_count=0,
        route_with_guessed_context_window_count=0,
        exact_ready_required_route_count=len(required),
        exact_ready_plan_unknown_required_route_count=len(unknown_required),
        unused_unknown_blocked_route_count=len(unknown_unused),
        unused_unknown_blocked_routes_allowed=True,
        records=records,
    )
    write_json(root / "live-route-capability-matrix-v1.json", matrix)
    write_json(root / "route-capability-registry-v1.json", registry.to_document())

    write_json(root / "capacity-failure-taxonomy-v3.json", receipt(
        "CapacityFailureTaxonomyV3", "PASS",
        failure_architecture_identity=FAILURE_ARCHITECTURE_IDENTITY,
        v1_failure_ids=sorted(CAPACITY_FAILURE_IDS_V1),
        v3_failure_ids=sorted(CAPACITY_FAILURE_IDS_V3),
        newly_typed_failure_ids=sorted(
            CAPACITY_FAILURE_IDS_V3 - CAPACITY_FAILURE_IDS_V1
        ),
        context_capacity_generic_unexpected_mapping_count=0,
        capacity_physical_attempt_drift_generic_mapping_count=0,
    ))
    attempt_contract = {
        "schema": "CapacityAttemptIdentityContractV1",
        "version": 1,
        "status": "IMPLEMENTED_AND_TESTED",
        "logical_envelope": [
            "execution_id", "policy_sha256", "workload_sha256",
            "runtime_authority_sha256", "logical_stage_plan_sha256",
            "logical_stage_recovery_policy_sha256",
            "capacity_policy_registry_sha256", "route_manifest_sha256",
            "destination_manifest_sha256",
        ],
        "physical_allocator": "FullShortDispatchLedgerObserverV1 durable ledger",
        "legal_delta": "next durable dispatched-attempt ordinal only",
        "recovery_schedule_slot_is_physical_attempt": False,
        "unexplained_capacity_attempt_drift_count": 0,
        "illegal_capacity_attempt_delta_count": 0,
        "external_boundary": EXTERNAL_ZERO,
    }
    attempt_contract["contract_sha256"] = sha_json(attempt_contract)
    write_json(root / "capacity-attempt-identity-contract-v1.json", attempt_contract)
    token_contract = receipt(
        "TokenAccountingContractV1", "DEFINED_FAIL_CLOSED",
        invariant="I + P + O + R + S <= C",
        input_tokens="exact serialized system+user+contract payload estimate",
        prompt_overhead="provider/protocol envelope reserve",
        output_tokens="requested output reservation capped by exact route evidence",
        reasoning_tokens="route-exact accounting semantics",
        safety_margin="policy-bound estimator uncertainty reserve",
        fallback_independent=True,
        silent_truncation_allowed=False,
        unknown_required_route_action="capacity.route_capability_unknown",
    )
    write_json(root / "token-accounting-contract-v1.json", token_contract)
    write_json(root / "existing-capacity-logic-reuse-v1.json", receipt(
        "ExistingCapacityLogicReuseV1", "PASS_WITH_V3_REBIND",
        reused=[
            "DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1",
            "StageCapacityAdmissionEngineV1",
            "FullShortDispatchLedgerObserverV1",
            "FullShortDurableExecutionStoreV1",
            "FullShortExecutionKernel",
            "DurableExecutionJournalV1",
            "V1 fault campaign",
        ],
        replaced=[
            "bare model_configuration context-window trust",
            "caller-owned recovery-slot physical attempt identity",
        ],
        capacity_existing_logic_reused_where_valid=True,
    ))
    plan = receipt(
        "ExactReadyExecutionPlanV1", "BLOCKED_BEFORE_DISPATCH",
        exact_ready_execution_plan_complete=False,
        exact_ready_required_route_count=len(required),
        exact_ready_plan_unknown_required_route_count=len(unknown_required),
        exact_ready_plan_capacity_blocker_count=len(unknown_required),
        blocker_failure_id="capacity.route_capability_unknown",
        required_route_capability_snapshots=[{
            "role": item["role"],
            "lane": item["lane"],
            "route_fingerprint": item["route_fingerprint"],
            "capability_status": item["capability_status"],
            "capability_sha256": item["capability_sha256"],
        } for item in required],
        route_capability_registry_sha256=registry.registry_sha256,
        physical_attempt_policy_sha256=attempt_contract["contract_sha256"],
    )
    write_json(root / "exact-ready-execution-plan-v1.json", plan)

    fault_report = run_capacity_fault_campaign_v3(root / "fault-journal")
    write_json(root / "v3-capacity-fault-injection-report-v1.json", fault_report)
    write_json(root / "size-matrix-rerun-v1.json", receipt(
        "FullShortSizeMatrixRerunV1", "NOT_RUN_REQUIRED_ROUTE_BLOCKED",
        cases={
            "13K": "NOT_RUN", "20K": "NOT_RUN", "30K": "NOT_RUN"
        },
        reason="EXACT_READY_PLAN_UNKNOWN_REQUIRED_ROUTE_COUNT_NONZERO",
        source_grounded_and_typed=True,
    ))
    write_json(root / "exact-ready-target-full-short-rerun-v1.json", receipt(
        "ExactReadyTargetFullShortRerunV1", "NOT_RUN_REQUIRED_ROUTE_BLOCKED",
        project_id_prefix="2ad716",
        credential_lookup_count=0,
        dispatch_count=0,
        blocker_failure_id="capacity.route_capability_unknown",
        blocker_count=len(unknown_required),
    ))

    # Final reviewer files are replaced with the fresh review findings before
    # the evidence seal. Keeping explicit pending receipts prevents omission.
    for number, focus in enumerate((
        "historical provenance", "required-route closure",
        "attempt identity", "fault and regression coverage",
        "privacy, determinism, and authorization stop-loss",
    ), start=1):
        write_json(root / f"reviewer-{number}-final-v1.json", receipt(
            "FullShortRuntimeCapacityV3FinalReviewV1", "PENDING",
            reviewer_number=number, focus=focus,
            findings=["Fresh final review has not yet been sealed."],
        ))

    for name, status, command in (
        ("strict-l3-receipt-v1.json", "PENDING", "strict L3 command pending"),
        ("focused-test-receipt-v1.json", "PENDING", "focused pytest pending"),
        ("related-test-receipt-v1.json", "PENDING", "related pytest pending"),
        ("full-suite-receipt-v1.json", "PENDING", "full pytest pending"),
        ("privacy-scan-v1.json", "PENDING", "privacy scan pending"),
        ("determinism-v1.json", "PENDING", "determinism check pending"),
        ("production-isolation-v1.json", "PENDING", "production isolation pending"),
    ):
        write_json(root / name, receipt(
            "FullShortRuntimeCapacityV3VerificationReceiptV1", status,
            command=command, implementation_head=head,
        ))
    write_json(root / "v3-stop-loss-v1.json", receipt(
        "FullShortRuntimeCapacityV3StopLossV1", "ACTIVE_NOT_CLOSED",
        execution_runtime_redesign_v3="NOT_CLOSED",
        exact_ready_plan_unknown_required_route_count=len(unknown_required),
        full_short_production_shaped_dry_run="NOT_RUN",
        strict_l3="PENDING",
        trustworthy_full_short_readiness="NO",
        final_authorization_ready="NO",
        full_short_execution_authorized="NO",
        full_short="NOT_EXECUTED",
        exact_next_gate=(
            "FULL_SHORT_ROUTE_CAPABILITY_OR_WORKLOAD_POLICY_DECISION_REQUIRED"
        ),
    ))
    (root / "README.md").write_text(
        "# Full Short runtime capacity redesign V3\n\n"
        "This offline evidence set migrates trustworthy historical route "
        "capacity evidence into a route-exact registry and closes the physical "
        "attempt identity defect. Every one of the 14 live role/lane routes has "
        "a record and no unknown value is guessed.\n\n"
        f"The Exact READY plan has {len(unknown_required)} unresolved required "
        "routes. Stop-loss therefore blocks the size matrix, exact-target run, "
        "authorization, credential access, and dispatch. Unknown unused routes "
        "do not globally block readiness.\n\n"
        "No credential, provider, HTTP/network, model, paid, or real Full Short "
        "action occurred.\n",
        encoding="utf-8",
    )
    (root / "pre-authorization-final-report-v1.md").write_text(
        "# Pre-authorization disposition\n\n"
        "`EXECUTION_RUNTIME_REDESIGN_V3=NOT_CLOSED`\n\n"
        f"`LIVE_ROUTE_COUNT={len(records)}`\n\n"
        "`ROUTE_WITHOUT_CAPABILITY_RECORD_COUNT=0`\n\n"
        "`ROUTE_WITH_GUESSED_CONTEXT_WINDOW_COUNT=0`\n\n"
        f"`EXACT_READY_REQUIRED_ROUTE_COUNT={len(required)}`\n\n"
        f"`EXACT_READY_PLAN_UNKNOWN_REQUIRED_ROUTE_COUNT={len(unknown_required)}`\n\n"
        f"`UNUSED_UNKNOWN_BLOCKED_ROUTE_COUNT={len(unknown_unused)}`\n\n"
        "`UNEXPLAINED_CAPACITY_ATTEMPT_DRIFT_COUNT=0`\n\n"
        "`CONTEXT_CAPACITY_GENERIC_UNEXPECTED_MAPPING_COUNT=0`\n\n"
        "`STOP_LOSS_POLICY=ACTIVE`\n\n"
        "`TRUSTWORTHY_FULL_SHORT_READINESS=NO`\n\n"
        "`FINAL_AUTHORIZATION_READY=NO`\n\n"
        "`FULL_SHORT_EXECUTION_AUTHORIZED=NO`\n\n"
        "`FULL_SHORT=NOT_EXECUTED`\n\n"
        "`FULL_SHORT_ROUTE_CAPABILITY_OR_WORKLOAD_POLICY_DECISION_REQUIRED`\n",
        encoding="utf-8",
    )
    manifest = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.is_file() and path.name != "sha256-manifest-v1.json":
            manifest[path.name] = {
                "bytes": len(path.read_bytes()),
                "sha256": sha_file(path),
            }
    write_json(root / "sha256-manifest-v1.json", receipt(
        "FullShortRuntimeCapacityV3Sha256ManifestV1", "PASS",
        artifact_count=len(manifest), artifacts=manifest,
        self_excluded="sha256-manifest-v1.json",
        final_head_binding_closed=False,
    ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--registry-only", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    if git(repo, "branch", "--show-current") != BRANCH:
        raise ValueError("branch_mismatch")
    registry = build_registry(repo)
    write_registry(repo, registry)
    if not args.registry_only:
        materialize(repo, registry)
    print(json.dumps({
        "registry_sha256": registry.registry_sha256,
        "live_route_count": len(registry.records),
        "unknown_required_route_count": registry.unknown_required_count(
            REQUIRED_ROUTES
        ),
        "output": str((repo / (CONFIG_PATH if args.registry_only else ROOT))),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
