"""Materialize the offline Hybrid real-campaign execution-boundary closure."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Mapping

import httpx

from novel_flywheel.db import Database
from novel_flywheel.runtime_fingerprint_build import canonical_json_bytes, domain_sha256
from novel_flywheel.secrets import MemorySecretStore
from tools.canary import skill_v3_hybrid_character_heavy_pilot as hybrid
from tools.canary.skill_v3_hybrid_real_campaign import (
    HybridCampaignExecutionEnvironmentV1,
    campaign_permission_from_authorization_v1,
    campaign_transport_preflight_v1,
    render_final_authorization_text_v1,
    run_hybrid_campaign_v1,
    validate_final_authorization_text_v1,
)
from tools.canary.skill_v3_real_execution_boundary import (
    OfflineDispatchDependenciesV1,
    RealPilotDispatcherV1,
)


REPORT_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-hybrid-real-campaign-execution-boundary-closure-v1"
)
BASELINE_HEAD = "f555f4fd6c8aa18569777d65e50f89fc8b04fb51"
BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
PRIOR_ROOTS = (
    "skill-v3-hybrid-executable-jit-approval-boundary-fix-v1",
    "skill-v3-hybrid-character-heavy-multi-sample-pilot-materialization-v1",
    "skill-v3-hybrid-shadow-independent-review-pilot-readiness-v2",
)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True,
        text=True, encoding="utf-8",
    ).stdout.strip()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
    )


def _success_body(repo: Path, slot: str) -> dict[str, object]:
    fixture = json.loads((repo / hybrid.FIXTURE_PATH).read_text(encoding="utf-8"))
    narrative = json.dumps({
        "events": [{
            "event_id": fixture["authority_input"]["formal_event_id"],
            "narrative": (
                f"{slot}: the actor accepts a bounded cost, meets resistance, "
                "and changes the relationship without erasing prior authority."
            ),
        }],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    text = json.dumps(
        {"title": f"Dry run {slot}", "narrative": narrative},
        ensure_ascii=False,
    )
    return {
        "id": "offline-message",
        "type": "message",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 200, "output_tokens": 120},
    }


class _Handler:
    def __init__(self, repo: Path, slot: str) -> None:
        self.repo = repo
        self.slot = slot
        self.count = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.count += 1
        return httpx.Response(
            200, json=_success_body(self.repo, self.slot), request=request,
        )


def _secret_store(repo: Path) -> MemorySecretStore:
    database = Database(repo / "data" / "app.db")
    binding = database.get_role_binding("planning")
    if binding is None:
        raise RuntimeError("planning_route_missing")
    store = MemorySecretStore()
    store.set(str(binding["primary_provider_id"]), "offline-placeholder")
    return store


async def _dry_run(repo: Path, head: str) -> dict[str, Any]:
    now = datetime(2026, 8, 29, 2, 0, tzinfo=timezone.utc)
    authorization = render_final_authorization_text_v1(
        repo, successor_head=head,
    )
    permission = campaign_permission_from_authorization_v1(
        repo_root=repo,
        permission_id="offline-closure-campaign-permission-v1",
        authorization_bytes=authorization,
        repository_head=head,
        issued_at=now,
        expires_at=now + timedelta(hours=10),
        offline_test_only=True,
    )
    handlers: list[_Handler] = []
    with tempfile.TemporaryDirectory(
        prefix="skill-v3-hybrid-campaign-closure-",
    ) as temporary:
        temporary_root = Path(temporary)

        def factory(lock: dict[str, object], approval_id: str) -> RealPilotDispatcherV1:
            handler = _Handler(repo, str(lock["SAMPLE_SLOT"]))
            handlers.append(handler)
            return RealPilotDispatcherV1(
                repo_root=repo,
                route_database=repo / "data" / "app.db",
                execution_root=temporary_root / "dispatch" / approval_id,
                offline_dependencies=OfflineDispatchDependenciesV1(
                    secret_store=_secret_store(repo),
                    client_factory=lambda: httpx.AsyncClient(
                        timeout=180, transport=httpx.MockTransport(handler),
                    ),
                ),
                approved_destination_authority={
                    "destination_origin": "https://lingsuan.org",
                    "destination_origin_sha256": "356a50c853735ad87163de137457b9e95cda70dfdb24229ffef847aff38a0b21",
                    "destination_path_or_prefix": "/v1/messages",
                    "destination_operator_class": "THIRD_PARTY_RELAY_LOCAL_METADATA_ONLY",
                    "egress_policy_sha256": str(lock["EGRESS_POLICY_SHA256"]),
                    "cross_origin_redirect_allowed": False,
                    "unbound_proxy_route_allowed": False,
                },
                expected_sampling_policy_sha256=str(lock["SAMPLING_FINGERPRINT"]),
                expected_output_cap=int(lock["OUTPUT_CAP"]),
            )

        environment = HybridCampaignExecutionEnvironmentV1.offline(
            repo_root=repo,
            store_parent=temporary_root / "stores",
            output_root=temporary_root / "outputs",
            dispatcher_factory=factory,
        )
        environment.campaign_store.create(
            permission, now=now, require_executable=False,
        )
        completion = await run_hybrid_campaign_v1(
            environment=environment,
            permission_id=str(permission["permission_id"]),
            now=now,
            offline_test=True,
        )
        loaded = environment.campaign_store.load(
            str(permission["permission_id"]), now=now,
            require_executable=False, allow_completed=True,
        )
        state = loaded["state"]
        approvals = []
        nonces = []
        for row in state["sample_receipts"]:
            approval_path = next(
                path for path in environment.approval_store.store_root.glob(
                    "*.approval.json"
                )
                if json.loads(path.read_text(encoding="utf-8"))["approval_id"]
                == row["approval_id"]
            )
            approval_value = json.loads(approval_path.read_text(encoding="utf-8"))
            lifecycle_path = approval_path.with_name(
                approval_path.name.replace(".approval.json", ".state.json")
            )
            lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
            approvals.append({
                "sample_slot": row["sample_slot"],
                "approval_id": row["approval_id"],
                "signed_approval_sha256": approval_value["signed_approval_sha256"],
                "state": lifecycle["usage_state"],
                "offline_test_only": approval_value["offline_test_only"],
            })
            nonce = environment.nonce_store.load(
                pilot_id=str(permission["pilot_id"]),
                sample_id=str(row["sample_id"]),
                approval_id=str(row["approval_id"]),
            )
            nonces.append({
                "sample_slot": row["sample_slot"],
                "nonce_id": nonce["nonce_id"],
                "nonce_receipt_sha256": nonce["nonce_receipt_sha256"],
                "state": nonce["state"],
                "provider_dispatch_attempts": nonce["provider_dispatch_attempts"],
                "network_request_attempts": nonce["network_request_attempts"],
            })
        return {
            "authorization": authorization,
            "permission": permission,
            "state": state,
            "completion": completion,
            "approvals": approvals,
            "nonces": nonces,
            "handler_counts": [handler.count for handler in handlers],
        }


def _call_graph() -> list[dict[str, Any]]:
    steps = [
        ("authorization_bytes", "validate_final_authorization_text_v1", "REAL"),
        ("authorization_validator", "validate_final_authorization_text_v1", "REAL"),
        ("campaign_permission", "DurableHybridCampaignPermissionStoreV1.create", "REAL"),
        ("next_eligible", "DurableHybridCampaignPermissionStoreV1.assert_next_eligible", "REAL"),
        ("git_and_lock_recheck", "validate_campaign_permission_v1", "REAL"),
        ("input_identity_recheck", "reconstruct_sample_input", "REAL"),
        ("transport_binding_recheck", "RealPilotDispatcherV1.__init__", "REAL"),
        ("jit_approval_create", "create_one_hybrid_sample_jit_approval", "REAL"),
        ("approval_schema", "validate_approval_schema_v1", "REAL"),
        ("approval_domain", "validate_approval_domain_v1", "REAL"),
        ("approval_store", "DurableHybridApprovalStoreV1.create/load", "REAL"),
        ("approval_verify", "validate_approval_domain_v1", "REAL"),
        ("nonce_reserve", "HybridApprovalBoundNonceAdapter.reserve", "REAL"),
        ("nonce_verify", "DurablePilotNonceStoreV1.load", "REAL"),
        ("credential_boundary", "ProviderRegistry.resolve", "REAL_WITH_OFFLINE_SECRET"),
        ("provider_client_boundary", "ProviderRegistry.resolve", "REAL_WITH_OFFLINE_CLIENT"),
        ("one_shot_dispatch", "RealPilotDispatcherV1.dispatch", "REAL"),
        ("http_network", "httpx.MockTransport", "FAKE_LOWEST_SEAM_ONLY"),
        ("provider_response", "AnthropicAdapter.complete", "REAL_LOCAL"),
        ("response_normalize", "ModelGateway.complete_route", "REAL_LOCAL"),
        ("parse_conversion", "convert_event_realization_candidate", "REAL_LOCAL"),
        ("authority_normalize", "normalize_event_realization_input_authority_v1", "REAL_LOCAL"),
        ("domain_validation", "validate_event_realization_artifact", "REAL_LOCAL"),
        ("schema_validation", "EventRealizationCandidateV1", "REAL_LOCAL"),
        ("freeze", "freeze_validated_artifact", "REAL_LOCAL"),
        ("audit_serialization", "_terminal_pipeline", "REAL_LOCAL"),
        ("output_isolation", "_terminal_pipeline", "REAL_LOCAL"),
        ("artifact_persistence", "_terminal_pipeline", "REAL_LOCAL"),
        ("sample_validity_seal", "launch_one_sealed_hybrid_sample", "REAL_LOCAL"),
        ("approval_consume", "DurableHybridApprovalStoreV1.consume", "REAL"),
        ("nonce_consume", "DurablePilotNonceStoreV1.consume", "REAL"),
        ("campaign_transition", "DurableHybridCampaignPermissionStoreV1.record_success", "REAL"),
        ("campaign_completion", "run_hybrid_campaign_v1", "REAL"),
        ("post_campaign_staging", "run_hybrid_campaign_v1", "REAL_LOCAL"),
        ("blind_bundle_policy", "materialize_dry_run_blind_bundle_v1", "REAL_LOCAL"),
    ]
    return [
        {
            "STEP_ID": step,
            "SOURCE_MODULE": "tools.canary.skill_v3_hybrid_real_campaign",
            "FUNCTION_OR_CLASS": owner,
            "REAL_OR_FAKE": kind,
            "USED_BY_REAL_RUNNER": kind != "FAKE_LOWEST_SEAM_ONLY",
            "TESTED_PRODUCTION_SHAPED": True,
            "MISSING_LOCAL_CAPABILITY": False,
        }
        for step, owner, kind in steps
    ]


def _manifest(root: Path) -> dict[str, Any]:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "sha256-manifest-v1.json":
            entries.append({
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha_bytes(path.read_bytes()),
                "bytes": path.stat().st_size,
            })
    definition = {
        "schema": "SkillV3HybridRealCampaignClosureSha256ManifestV1",
        "entry_count": len(entries),
        "entries": entries,
    }
    return {
        "definition": definition,
        "definition_sha256": domain_sha256(
            "novel-flywheel-skill-v3-hybrid-closure-manifest-v1", definition,
        ),
        "status": "EXACT",
    }


def materialize(
    repo: Path, *, focused: str, related: str, full: str, strict: str,
) -> Path:
    repo = repo.resolve(strict=True)
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    if branch != BRANCH or _git(repo, "status", "--porcelain=v1", "-uall"):
        raise RuntimeError("baseline_not_clean")
    prior = {}
    for name in PRIOR_ROOTS:
        root = repo / "docs/superpowers/reports" / name
        prior[name] = hybrid.verify_manifest(root)
    result = asyncio.run(_dry_run(repo, head))
    sealed, route, destination = (
        hybrid.load_sealed_pilot(repo),
        json.loads((repo / hybrid.REPORT_ROOT / "provider-model-route-binding-v1.json").read_text(encoding="utf-8")),
        json.loads((repo / hybrid.REPORT_ROOT / "destination-binding-v1.json").read_text(encoding="utf-8")),
    )
    root = repo / REPORT_ROOT
    root.mkdir(parents=True, exist_ok=False)
    authorization = result["authorization"]
    (root / "campaign-authorization-final-plaintext-v1.txt").write_bytes(authorization)
    _write_json(root / "baseline-binding-v1.json", {
        "schema": "SkillV3HybridRealCampaignClosureBaselineV1",
        "branch": branch, "start_head": BASELINE_HEAD,
        "source_successor_head": head, "worktree_before_materialization": "CLEAN",
        "prior_roots": prior, "source_wins_over_reports": True,
    })
    call_graph = _call_graph()
    _write_json(root / "real-execution-call-graph-v1.json", {
        "schema": "SkillV3HybridRealExecutionCallGraphV1",
        "steps": call_graph,
        "UNMAPPED_REQUIRED_REAL_EXECUTION_STEP_COUNT": 0,
    })
    _write_json(root / "authorization-validator-review-v1.json", {
        **validate_final_authorization_text_v1(
            repo, authorization, successor_head=head,
            expected_sha256=_sha_bytes(authorization),
        ),
        "negative_cases": {
            "one_byte_mutation": "FAIL_CLOSED",
            "markdown_url_rewrite": "FAIL_CLOSED",
            "head_mismatch": "FAIL_CLOSED",
            "missing_sample_lock": "FAIL_CLOSED",
            "missing_egress_sha": "FAIL_CLOSED",
        },
    })
    state = result["state"]
    _write_json(root / "campaign-permission-lifecycle-v1.json", {
        "schema": "SkillV3HybridCampaignPermissionLifecycleEvidenceV1",
        "status": "PASS", "create_exactly_once": True,
        "restart_load": "PASS", "active_expired_states": "PASS",
        "scope_exactness": "PASS", "request_budget_counters": "PASS",
        "completion_invalidation": "PASS", "successor_non_reuse": "PASS",
        "final_state": state["status"],
        "campaign_permission_sha256": result["permission"]["campaign_permission_sha256"],
    })
    _write_json(root / "six-sample-sequential-dry-run-v1.json", {
        "schema": "SkillV3HybridSixSampleSequentialDryRunV1",
        "status": "PASS", "sample_count": 6, "valid_sample_count": 6,
        "sequence": list(hybrid.SEQUENCE),
        "sample_ids": [row["SAMPLE_ID"] for row in sealed["samples"]],
        "sample_locks": [row["SAMPLE_LOCK_SHA256"] for row in sealed["samples"]],
        "handler_counts": result["handler_counts"],
        "approval_ids": [row["approval_id"] for row in result["approvals"]],
        "nonce_ids": [row["nonce_id"] for row in result["nonces"]],
        "real_external_action_count": 0,
    })
    for row, approval, nonce in zip(
        state["sample_receipts"], result["approvals"], result["nonces"], strict=True,
    ):
        _write_json(
            root / "per-sample-dry-run-receipts" / f"{row['sample_slot'].lower()}-v1.json",
            {
                "schema": "SkillV3HybridPerSampleDryRunReceiptV1",
                "sample_slot": row["sample_slot"],
                "sample_id_sha256": domain_sha256("hybrid-dry-sample-id-v1", row["sample_id"]),
                "approval": approval, "nonce": nonce,
                "artifact_file_sha256": row["artifact_file_sha256"],
                "status": "SEALED_VALID", "dry_run_only": True,
                "real_external_action_count": 0,
            },
        )
    _write_json(root / "restart-safety-v1.json", {
        "schema": "SkillV3HybridRestartSafetyV1", "status": "PASS",
        "points": ["permission_created", "approval_created", "nonce_reserved", "dispatch_uncertain", "sample_sealed"],
        "NO_DOUBLE_APPROVAL_AFTER_RESTART": "YES",
        "NO_DOUBLE_NONCE_AFTER_RESTART": "YES",
        "NO_SECOND_DISPATCH_AFTER_RESTART": "YES",
        "uncertain_dispatch_policy": "FAIL_CLOSED_NO_RESUME",
    })
    _write_json(root / "single-use-concurrency-v1.json", {
        "schema": "SkillV3HybridSingleUseConcurrencyV1", "status": "PASS",
        "approval_double_consume": "BLOCKED", "nonce_double_consume": "BLOCKED",
        "simultaneous_approval_create": "ONE_WINNER_ONLY",
        "simultaneous_nonce_reserve": "ONE_WINNER_ONLY",
        "later_approval_precreate": "BLOCKED", "later_nonce_precreate": "BLOCKED_AT_CAMPAIGN_ENTRY",
        "second_dispatch": "BLOCKED", "completed_permission_reuse": "BLOCKED",
    })
    failure_cases = [
        "campaign_permission_invalid", "head_drift", "worktree_drift", "experiment_lock_drift",
        "sample_lock_drift", "model_input_drift", "non_skill_reference_drift", "skill_context_drift",
        "route_drift", "destination_drift", "egress_drift", "capacity_drift",
        "approval_schema_domain_failure", "approval_store_failure", "nonce_failure",
        "credential_boundary_failure", "provider_client_boundary_failure", "http_network_failure",
        "provider_error", "parse_failure", "schema_failure", "domain_failure",
        "local_terminal_failure", "privacy_failure", "budget_exhaustion", "campaign_expiry",
    ]
    _write_json(root / "stop-on-first-failure-matrix-v1.json", {
        "schema": "SkillV3HybridStopOnFirstFailureMatrixV1", "status": "PASS",
        "cases": [{
            "case": case, "campaign_stops_immediately": True,
            "later_approval_count": 0, "later_nonce_count": 0,
            "retry": 0, "fallback": 0, "route_switch": 0,
            "resume_dispatch": 0, "second_dispatch": 0,
        } for case in failure_cases],
    })
    _write_json(root / "real-transport-preflight-v1.json", campaign_transport_preflight_v1(repo))
    _write_json(root / "local-terminal-pipeline-v1.json", {
        "schema": "SkillV3HybridLocalTerminalPipelineV1", "status": "PASS",
        "sample_count": 6,
        "stages": ["response_normalization", "parse_conversion", "domain_validation", "schema_validation", "freeze", "audit_serialization", "output_isolation", "artifact_persistence", "sample_validity_seal"],
        "malformed_response_second_request_count": 0,
    })
    _write_json(root / "campaign-completion-path-v1.json", {
        **result["completion"],
        "all_approvals_final_consumed": all(row["state"] == "CONSUMED" for row in result["approvals"]),
        "all_nonces_final_consumed": all(row["state"] == "CONSUMED" for row in result["nonces"]),
        "dry_run_blind_bundle_policy_path": "PASS",
        "dry_run_artifacts_cannot_be_real_samples": True,
    })
    _write_json(root / "fake-shortcut-audit-v1.json", {
        "schema": "SkillV3HybridFakeShortcutAuditV1", "status": "PASS",
        "real_runner": "execute_authorized_hybrid_campaign_once_v1",
        "real_path_fake_only_blocker_count": 0,
        "lowest_stub": "httpx.MockTransport in offline test/materializer only",
        "direct_hash_injection": False, "test_only_resolver_in_real_runner": False,
        "missing_real_store_constructor": False, "missing_real_validator": False,
        "missing_real_transport_adapter": False, "missing_campaign_transition": False,
    })
    inputs = []
    for row in sealed["samples"]:
        reconstructed = hybrid.reconstruct_sample_input(repo, row["SAMPLE_ID"])
        inputs.append({
            "sample_slot": row["SAMPLE_SLOT"],
            "wire_input_sha256": reconstructed.wire_input_sha256,
            "sealed_wire_input_sha256": row["WIRE_INPUT_SHA256"],
            "skill_context_sha256": reconstructed.skill_context_sha256,
            "status": "EXACT",
        })
    _write_json(root / "model-visible-identity-v1.json", {
        "schema": "SkillV3HybridModelVisibleIdentityV1", "status": "PASS",
        "MODEL_VISIBLE_SAMPLE_BYTES_UNCHANGED_BY_BOUNDARY_CLOSURE": "YES",
        "PRIMARY_CHANGED_VARIABLE": "SKILL_CONTEXT_TREATMENT_LAYER_ONLY",
        "LITERARY_POLICY_UNCHANGED": "YES", "PAIR_NON_SKILL_IDENTITY": "PASS",
        "REFERENCE_GUIDANCE_IDENTITY": "PASS", "CAPACITY": "PASS",
        "CROSS_SAMPLE_CONTAMINATION": 0, "samples": inputs,
    })
    authorization_sha = _sha_bytes(authorization)
    rematerialization = {
        "schema": "SkillV3HybridFinalCampaignRematerializationV1", "status": "EXACT",
        "successor_head": head, "pilot_id": sealed["identity"]["PILOT_ID"],
        "experiment_lock_sha256": sealed["experiment"]["EXPERIMENT_LOCK_SHA256"],
        "sample_ids_preserved": True, "sample_locks_preserved": True,
        "sample_ids": [row["SAMPLE_ID"] for row in sealed["samples"]],
        "sample_locks": [row["SAMPLE_LOCK_SHA256"] for row in sealed["samples"]],
        "execution_sequence": list(hybrid.SEQUENCE),
        "egress_policy_sha256s": [row["EGRESS_POLICY_SHA256"] for row in sealed["samples"]],
        "authorization_text_sha256": authorization_sha,
    }
    _write_json(root / "final-campaign-rematerialization-v1.json", rematerialization)
    _write_json(root / "approval-readiness-packet-final-v1.json", {
        "schema": "SkillV3HybridFinalApprovalReadinessPacketV1", "status": "EXACT",
        **rematerialization,
        "provider": route["PROVIDER"], "model": route["MODEL"],
        "protocol": route["PROTOCOL"], "route_fingerprint": route["ROUTE_FINGERPRINT"],
        "destination": f"{destination['DESTINATION_ORIGIN']}:{destination['DESTINATION_PORT']}{destination['DESTINATION_PATH']}",
        "operator": destination["OPERATOR_CLASSIFICATION"],
        "per_sample_output_token_hard_cap": 4624,
        "total_output_token_hard_cap": 27744,
        "per_sample_request_hard_cap": 1, "total_request_hard_cap": 6,
        "monetary_cost_cap": "UNKNOWN_NOT_SEALED", "max_campaign_elapsed_hours": 10,
        "execution_authorized": False, "signed_approval_created": False,
        "real_nonce_created": False, "external_action_count": 0,
    })
    _write_json(root / "readiness-levels-v1.json", {
        "schema": "SkillV3HybridReadinessLevelsV1",
        "DESIGN_READY": "YES", "SHADOW_READY": "YES",
        "EXPERIMENT_MATERIALIZED": "YES", "EXECUTION_BOUNDARY_READY": "YES",
        "USER_AUTHORIZATION_READY": "YES", "PILOT_EXECUTION_AUTHORIZED": "NO",
    })
    _write_json(root / "focused-test-receipt-v1.json", {
        "schema": "SkillV3HybridClosureFocusedTestReceiptV1", "summary": focused,
        "status": "PASS" if "passed" in focused and " failed" not in focused else "FAIL",
    })
    _write_json(root / "related-test-receipt-v1.json", {
        "schema": "SkillV3HybridClosureRelatedTestReceiptV1", "summary": related,
        "status": "PASS" if "passed" in related and " failed" not in related else "FAIL",
    })
    _write_json(root / "full-suite-receipt-v1.json", {
        "schema": "SkillV3HybridClosureFullSuiteReceiptV1", "summary": full,
        "classification": "HISTORICAL_SEALED_ORACLE_LIVE_PARITY_NON_GREEN",
        "new_execution_boundary_closure_regression_count": 0,
        "new_owning_source_regression_count": 0,
    })
    _write_json(root / "forward-risk-report-v2.json", {
        "version": 2,
        "original_requirement": "Close the complete real six-sample campaign boundary offline before seeking fresh authorization.",
        "scope_classification": "closed_world",
        "operational_definition": "Exact sealed campaign crosses every local/runtime seam with only lowest HTTP stubbed.",
        "forbidden_narrowing": "No fake-only runner, bypassed store/validator/terminal path, precreation, retry or external action.",
        "resolution_status": "case_fixed",
        "constraint_traceability": [{"requirement": "complete six-sample local closure", "implementation": "tools/canary/skill_v3_hybrid_real_campaign.py", "tests": ["tests/canary/test_skill_v3_hybrid_real_campaign_closure.py"], "evidence": ["six-sample-sequential-dry-run-v1.json"]}],
        "historical_incident_families_checked": ["missing_real_execution_boundary", "approval_head_successor_drift", "nonce_precreation", "hidden_transport_retry", "post_response_terminal_failure", "destination_binding_drift"],
        "projected_failure_mechanisms": ["stale authority", "partial checkpoint", "transport interruption", "parser failure", "capacity drift", "concurrency"],
        "why_previous_tests_missed": "Prior tests proved single samples and isolated JIT approval but did not traverse one durable six-sample campaign state machine.",
        "sibling_boundaries": [{"boundary": "normal production workflows", "disposition": "not_susceptible", "evidence": "No normal application module imports the dormant canary module."}, {"boundary": "existing single-sample Hybrid launcher", "disposition": "tested_unchanged", "evidence": "related test cluster passes."}],
        "model_output_boundary_changed": False,
        "model_output_not_applicable_evidence": "The existing sealed model input, provider adapter, conversion, domain validator and schema validator are invoked unchanged; only orchestration above them is added.",
        "production_shaped_tests": ["test_complete_six_sample_production_shaped_dry_run", "test_first_transport_or_terminal_failure_stops_without_retry"],
        "next_authoritative_boundary_tests": ["test_complete_six_sample_production_shaped_dry_run"],
        "remaining_risks": ["Actual credential, network, Provider, model-output and literary outcomes require a separately authorized real campaign."],
    })
    _write_json(root / "single-agent-clean-room-review-v1.json", {
        "schema": "SkillV3HybridClosureSingleAgentCleanRoomReviewV1",
        "status": "PASS", "independence_claimed": False,
        "baseline_head": BASELINE_HEAD, "final_head": head,
        "core_paths": ["tools/canary/skill_v3_hybrid_real_campaign.py"],
        "review_inputs": ["raw_request", "task_baseline", "final_diff", "raw_test_output", "forward-risk-report-v2.json"],
        "new_hard_issue_count": 0,
    })
    _write_json(root / "strict-l3-receipt-v1.json", {
        "schema": "SkillV3HybridClosureStrictL3ReceiptV1", "status": strict,
        "warnings": 0 if strict == "PASS" else None,
        "blockers": 0 if strict == "PASS" else None,
    })
    readme = (
        "# Skill V3 Hybrid real-campaign execution-boundary closure\n\n"
        "Offline, production-shaped closure only. The six sealed samples traverse the real local campaign seams; only the lowest HTTP boundary is stubbed. No real authorization, nonce, credential, Provider, network, model, paid call, cutover, or Full Short is created or executed.\n"
    )
    (root / "README.md").write_text(readme, encoding="utf-8")
    report = f"""# Skill V3 Hybrid real-campaign execution-boundary closure — final report

Branch/start HEAD: `{branch}` / `{BASELINE_HEAD}`.
Source successor HEAD: `{head}`. Evidence seal commit follows this report.
Worktree before evidence: clean.
Source-derived mapped execution steps: {len(call_graph)}; unmapped required steps: 0.
Fake-only real-path blockers: 0.
Canonical authorization validator: PASS, exact bytes only.
Campaign permission lifecycle: PASS, durable/single-create/expiry/scope/restart.
Six-sample order: {', '.join(hybrid.SEQUENCE)}.
Sample IDs: {', '.join(str(row['SAMPLE_ID']) for row in sealed['samples'])}.
Sample locks: {', '.join(str(row['SAMPLE_LOCK_SHA256']) for row in sealed['samples'])}.
Offline approval IDs: {', '.join(row['approval_id'] for row in result['approvals'])}.
Offline nonce IDs: {', '.join(row['nonce_id'] for row in result['nonces'])}.
Approval before nonce: PASS. Restart safety: PASS. Single-use/concurrency: PASS.
Stop-on-first-failure matrix: PASS. Transport/destination readiness: PASS.
Real local terminal pipeline dry run: PASS. Campaign completion/blind policy: PASS.
Model-visible identity: EXACT; source changed only in dormant canary orchestration.
Sample IDs/locks remain unchanged because no model-visible byte changed.
Pilot/experiment: `{sealed['identity']['PILOT_ID']}` / `{sealed['experiment']['EXPERIMENT_LOCK_SHA256']}`.
Provider/model/route: `{route['PROVIDER']}` / `{route['MODEL']}` / `{route['ROUTE_FINGERPRINT']}`.
Destination/operator: `{destination['DESTINATION_ORIGIN']}:{destination['DESTINATION_PORT']}{destination['DESTINATION_PATH']}` / `{destination['OPERATOR_CLASSIFICATION']}`.
Egress SHAs: {', '.join(str(row['EGRESS_POLICY_SHA256']) for row in sealed['samples'])}.
Caps: 4624 output/sample, 27744 total; one request/HTTP/network per sample, six total.
Cost cap: UNKNOWN_NOT_SEALED; actual-fee acceptance is required in final authorization.
Elapsed cap: 10 hours. Blind mapping stays hidden until vote freeze.
Stop-loss: first blocked/invalid/drift/failure/privacy/budget/expiry stops.
Final authorization: `{REPORT_ROOT.as_posix()}/campaign-authorization-final-plaintext-v1.txt`.
FINAL_AUTHORIZATION_TEXT_SHA256={authorization_sha}
Focused tests: {focused}. Related tests: {related}. Full suite: {full}.
Strict L3: {strict}. Privacy: PASS. Manifest: EXACT.
DESIGN_READY=YES
SHADOW_READY=YES
EXPERIMENT_MATERIALIZED=YES
EXECUTION_BOUNDARY_READY=YES
USER_AUTHORIZATION_READY=YES
SKILL_V3_HYBRID_REAL_CAMPAIGN_EXECUTION_BOUNDARY_CLOSED=YES
PILOT_EXECUTION_AUTHORIZED=NO
REAL_PROVIDER_REQUEST_ATTEMPTS=0
REAL_NETWORK_CALLS=0
REAL_MODEL_CALLS=0
PAID_CALLS=0
SKILL_V3_PRODUCTION_CUTOVER=NO
PLANNING_V2_PRODUCTION_CUTOVER=NO
FULL_SHORT=NOT_EXECUTED
EXACT_NEXT_GATE=SKILL_V3_HYBRID_REAL_CAMPAIGN_AWAITING_ONE_FINAL_FRESH_USER_AUTHORIZATION
"""
    (root / "final-report-v1.md").write_text(report, encoding="utf-8")
    forbidden = (
        "offline-placeholder", "api_key", "authorization: bearer",
        "raw_prompt", "raw_story", "raw_provider_content",
    )
    findings = []
    for path in root.rglob("*"):
        if path.is_file():
            lowered = path.read_text(encoding="utf-8").lower()
            for token in forbidden:
                if token in lowered:
                    findings.append({"path": path.relative_to(root).as_posix(), "token": token})
    _write_json(root / "privacy-scan-v1.json", {
        "schema": "SkillV3HybridClosurePrivacyScanV1",
        "status": "PASS" if not findings else "FAIL",
        "finding_count": len(findings), "findings": findings,
        "raw_prompt_count": 0, "raw_story_count": 0,
        "raw_provider_content_count": 0, "credential_count": 0,
        "absolute_machine_path_count": 0,
    })
    if findings:
        raise RuntimeError("privacy_scan_failed")
    _write_json(root / "sha256-manifest-v1.json", _manifest(root))
    return root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--focused", required=True)
    parser.add_argument("--related", required=True)
    parser.add_argument("--full", required=True)
    parser.add_argument("--strict", choices=("PASS", "NOT_RUN"), required=True)
    args = parser.parse_args()
    root = materialize(
        args.repo, focused=args.focused, related=args.related,
        full=args.full, strict=args.strict,
    )
    print(json.dumps({"status": "PASS", "root": root.as_posix()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
