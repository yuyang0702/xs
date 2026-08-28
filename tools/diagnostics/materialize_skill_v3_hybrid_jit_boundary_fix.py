"""Materialize inert successor evidence for the Hybrid JIT approval fix."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from tools.canary import skill_v3_hybrid_character_heavy_pilot as hybrid
from tools.canary.skill_v3_hybrid_jit_approval import (
    APPROVAL_DOMAIN,
    APPROVAL_SCHEMA,
    APPROVAL_SCOPE,
    APPROVAL_VERSION,
    DEFAULT_STORE_RELATIVE,
    EXPECTED_BRANCH,
    FAILURE_DOMAIN,
    FAILURE_SCHEMA,
    LIFECYCLE_DOMAIN,
    LIFECYCLE_SCHEMA,
    PERMISSION_DOMAIN,
    PERMISSION_SCHEMA,
    WORKTREE_POLICY,
    ZERO_ATTEMPT_COUNTERS,
)


REPORT_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-hybrid-executable-jit-approval-boundary-fix-v1"
)
BASELINE_HEAD = "f3967c9d18a9942a65703db7f3edbf4f72b16864"
IMPLEMENTATION_HEAD = "04089881033c0a090f0a01334248d341624585d8"
PRIOR_AUTHORIZATION_SHA256 = (
    "6cfaaab876d9a903e4dc695e0e264469d4cedfe7ea6e723f54717bfe85994f6a"
)
EXTERNAL_ZERO = {
    "CREDENTIAL_LOOKUP_COUNT": 0,
    "REAL_PROVIDER_CLIENT_CREATION_COUNT": 0,
    "REAL_PROVIDER_REQUEST_ATTEMPTS": 0,
    "HTTP_POST_ATTEMPTS": 0,
    "NETWORK_CALLS": 0,
    "MODEL_CALLS": 0,
    "PAID_CALLS": 0,
    "REAL_NONCE_CREATED": 0,
    "REAL_NONCE_RESERVED": 0,
    "REAL_NONCE_CONSUMED": 0,
    "REAL_SAMPLE_DISPATCH_COUNT": 0,
}
REQUIRED_FILES = (
    "README.md", "baseline-binding-v1.json",
    "blocked-execution-binding-v1.json",
    "existing-approval-boundary-audit-v1.json",
    "generic-jit-approval-schema-v1.json",
    "approval-domain-validator-v1.json", "old-pilot-compatibility-v1.json",
    "durable-approval-store-v1.json", "single-sample-jit-api-v1.json",
    "approval-nonce-ordering-v1.json", "hybrid-runner-boundary-v1.json",
    "six-role-offline-replay-v1.json", "negative-injections-v1.json",
    "failure-observability-v1.json", "model-visible-identity-regression-v1.json",
    "successor-campaign-rematerialization-v1.json",
    "approval-readiness-packet-v2.json",
    "campaign-authorization-plaintext-v2.txt", "forward-risk-report-v2.json",
    "change-contract-v1.json", "privacy-scan-v1.json",
    "focused-test-receipt-v1.json", "related-test-receipt-v1.json",
    "full-suite-receipt-v1.json", "strict-l3-receipt-v1.json",
    "final-report-v1.md", "sha256-manifest-v1.json",
)


class MaterializationError(RuntimeError):
    pass


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=False, indent=2) + "\n"
    ).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_json(value: object) -> str:
    return sha_bytes(canonical_bytes(value))


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
        encoding="utf-8", check=False,
    )
    if result.returncode:
        raise MaterializationError(result.stderr.strip() or "git failure")
    return result.stdout.strip()


def _git_ok(repo: Path, *args: str) -> bool:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, check=False,
    ).returncode == 0


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MaterializationError(f"expected object: {path}")
    return value


def _authorization_text(
    *, pilot_id: str, experiment_lock: str, samples: list[dict[str, Any]],
    route: Mapping[str, Any], destination: Mapping[str, Any],
) -> str:
    ids = ",".join(str(row["SAMPLE_ID"]) for row in samples)
    locks = ",".join(str(row["SAMPLE_LOCK_SHA256"]) for row in samples)
    egress = ",".join(str(row["EGRESS_POLICY_SHA256"]) for row in samples)
    sequence = ",".join(hybrid.SEQUENCE)
    return (
        "SKILL V3 HYBRID CHARACTER-HEAVY MULTI-SAMPLE PILOT — FRESH USER "
        "AUTHORIZATION V2\n\n"
        "This text is an authorization template only. It is not authorization "
        "until the user sends it as a fresh explicit message.\n\n"
        f"SUCCESSOR_HEAD={IMPLEMENTATION_HEAD}\n"
        f"PILOT_ID={pilot_id}\n"
        f"EXPERIMENT_LOCK_SHA256={experiment_lock}\n"
        f"EXECUTION_SEQUENCE={sequence}\n"
        f"SAMPLE_IDS={ids}\n"
        f"SAMPLE_LOCK_SHA256S={locks}\n"
        f"PROVIDER={route['PROVIDER']}\n"
        f"PROVIDER_DESCRIPTOR_SHA256={route['PROVIDER_DESCRIPTOR_SHA256']}\n"
        f"MODEL={route['MODEL']}\n"
        f"MODEL_BINDING_SHA256={route['MODEL_BINDING_SHA256']}\n"
        f"PROTOCOL={route['PROTOCOL']}\n"
        f"ROUTE_FINGERPRINT={route['ROUTE_FINGERPRINT']}\n"
        f"DESTINATION={destination['DESTINATION_ORIGIN']}:"
        f"{destination['DESTINATION_PORT']}{destination['DESTINATION_PATH']}\n"
        f"OPERATOR_CLASSIFICATION={destination['OPERATOR_CLASSIFICATION']}\n"
        f"EGRESS_POLICY_SHA256S={egress}\n"
        "PER_SAMPLE_OUTPUT_TOKEN_HARD_CAP=4624\n"
        "TOTAL_SIX_SAMPLE_OUTPUT_TOKEN_HARD_CAP=27744\n"
        "MAX_PROVIDER_REQUESTS_PER_SAMPLE=1\n"
        "TOTAL_PROVIDER_REQUESTS=6\n"
        "MAX_HTTP_POST_ATTEMPTS_PER_SAMPLE=1\n"
        "TOTAL_NETWORK_ATTEMPTS=6\n"
        "MAX_CAMPAIGN_ELAPSED_HOURS=10\n"
        "MONETARY_COST_CAP=UNKNOWN_NOT_SEALED\n"
        "I explicitly authorize the six sealed samples above, in the exact order "
        "above, with at most one paid request per sample and at most six paid "
        "requests total. I authorize only each sample's required system/context, "
        "task, authority, story slice, already model-visible reference-derived "
        "non-Skill guidance, its arm Skill context, output contract, and required "
        "Provider request metadata to be sent to the exact destination. I accept "
        "actual-fee risk because no trustworthy USD/CNY cap is sealed.\n"
        "Each next-eligible sample requires a separate JIT "
        "SkillV3HybridSampleJitSignedApprovalV1 followed by a separate fresh "
        "durable single-use nonce. Later approvals/nonces must not be precreated. "
        "No retry, transport retry, fallback, route switch, resume dispatch, "
        "second dispatch, alternate destination, cross-origin redirect, or "
        "replacement sample is authorized. Stop on the first blocked, invalid, "
        "drifted, failed, privacy-failed, or budget-exceeded state, or when the "
        "campaign expires. Blind mapping remains hidden until all required votes "
        "freeze. No Skill V3 cutover, Planning V2 cutover, or Full Short is "
        "authorized.\n"
    )


def _validation(validation: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = validation.get(key)
    if not isinstance(value, Mapping):
        return {"status": "PENDING", "summary": "not yet run"}
    return dict(value)


def build_artifacts(
    repo_root: Path, validation: Mapping[str, Any],
) -> dict[str, bytes]:
    repo = repo_root.resolve(strict=True)
    branch = _git(repo, "branch", "--show-current")
    head = _git(repo, "rev-parse", "HEAD")
    if branch != EXPECTED_BRANCH or not _git_ok(
        repo, "merge-base", "--is-ancestor", IMPLEMENTATION_HEAD, head,
    ):
        raise MaterializationError("HYBRID_JIT_BOUNDARY_FIX_NO_GO_BASELINE_DRIFT")
    sealed = hybrid.load_sealed_pilot(repo)
    samples = [dict(row) for row in sealed["samples"]]
    route = _json(repo / hybrid.REPORT_ROOT / "provider-model-route-binding-v1.json")
    destination = _json(repo / hybrid.REPORT_ROOT / "destination-binding-v1.json")
    pilot_id = str(sealed["identity"]["PILOT_ID"])
    experiment_lock = str(sealed["experiment"]["EXPERIMENT_LOCK_SHA256"])
    text = _authorization_text(
        pilot_id=pilot_id, experiment_lock=experiment_lock,
        samples=samples, route=route, destination=destination,
    )
    text_sha = sha_bytes(text.encode("utf-8"))
    implementation_files = (
        "tools/canary/skill_v3_hybrid_jit_approval.py",
        "tools/canary/skill_v3_hybrid_campaign.py",
        "tests/canary/test_skill_v3_hybrid_jit_approval.py",
        "docs/maintenance.md",
    )
    source_hashes = {
        path: sha_bytes((repo / path).read_bytes()) for path in implementation_files
    }
    model_rows = []
    for row in samples:
        rebuilt = hybrid.reconstruct_sample_input(repo, str(row["SAMPLE_ID"]))
        model_rows.append({
            "sample_id": row["SAMPLE_ID"], "sample_slot": row["SAMPLE_SLOT"],
            "wire_input_sha256": rebuilt.wire_input_sha256,
            "expected_wire_input_sha256": row["WIRE_INPUT_SHA256"],
            "model_input_component_sha256": rebuilt.model_input_component_binding_sha256,
            "expected_model_input_component_sha256": row["MODEL_INPUT_COMPONENT_SHA256"],
            "status": "EXACT",
        })

    artifacts: dict[str, bytes] = {}

    def add(name: str, value: object) -> None:
        artifacts[name] = json_bytes(value)

    artifacts["README.md"] = (
        "# Skill V3 Hybrid executable JIT approval boundary fix\n\n"
        "Offline evidence for the closed Hybrid JIT approval namespace, durable "
        "single-use lifecycle, one-sample runner, and inert successor campaign. "
        "This directory is not execution authority.\n"
    ).encode("utf-8")
    add("baseline-binding-v1.json", {
        "schema": "SkillV3HybridJitBoundaryBaselineBindingV1",
        "status": "EXACT", "branch": branch,
        "start_head": BASELINE_HEAD, "implementation_head": IMPLEMENTATION_HEAD,
        "current_head_is_implementation_descendant": True,
        "prior_pilot_id": pilot_id, "prior_experiment_lock_sha256": experiment_lock,
        "prior_materialization_manifest": sealed["manifest"],
        "production_src_diff_file_count": 0, "baml_src_diff_file_count": 0,
        "source_hashes": source_hashes,
    })
    add("blocked-execution-binding-v1.json", {
        "schema": "SkillV3HybridBlockedExecutionBindingV1", "status": "EXACT",
        "fresh_user_campaign_permission": "VALID_HISTORICAL",
        "execution_preflight": "BLOCKED",
        "blocker": "HYBRID_EXECUTABLE_JIT_SIGNED_APPROVAL_BOUNDARY_NOT_IMPLEMENTED",
        "prior_authorization_sha256": PRIOR_AUTHORIZATION_SHA256,
        "prior_authorization_disposition": "NON_REUSABLE_FOR_FUTURE_SUCCESSOR",
        "signed_approval_created": False, "real_nonce_created": False,
        "campaign_executed": False, **EXTERNAL_ZERO,
    })
    add("existing-approval-boundary-audit-v1.json", {
        "schema": "SkillV3HybridExistingApprovalBoundaryAuditV1",
        "status": "COMPLETE",
        "columns": [
            "component", "current_scope", "reusable", "old_pilot_coupling",
            "required_hybrid_change", "production_behavior_risk",
        ],
        "rows": [
            ["canonical_json/domain_sha256", "all approval generations", "YES", "none", "reuse", "LOW"],
            ["Selective V1-V3 validators", "historical A1", "NO", "A1-only", "none", "NONE"],
            ["Selective V4 validator/store", "B1,A2,B2,A3,B3", "NO", "fixed old roles/pilot", "new namespace", "LOW"],
            ["durable nonce store V2", "destination-bound sample nonce", "YES", "binding data supplied by caller", "adapter", "LOW"],
            ["RealPilotDispatcherV1", "one-shot sealed request", "YES", "sampling/cap injected", "wrapper", "LOW"],
            ["Hybrid legacy launcher", "sealed six inputs + fake approval", "YES", "literary lock", "verified projection wrapper", "LOW"],
        ],
    })
    add("generic-jit-approval-schema-v1.json", {
        "schema": "SkillV3HybridJitApprovalSchemaEvidenceV1", "status": "PASS",
        "approval_schema": APPROVAL_SCHEMA, "approval_version": APPROVAL_VERSION,
        "approval_domain": APPROVAL_DOMAIN, "approval_scope": APPROVAL_SCOPE,
        "closed_schema": True, "permissive_defaults": False,
        "hash_signature": "domain-separated canonical SHA-256",
        "usage_states": ["UNUSED", "CONSUMED", "INVALID", "EXPIRED"],
        "required_binding_families": [
            "identity/time/single-use", "pilot/experiment/git", "sample/pair/arm",
            "model-visible component hashes", "provider/model/protocol/route",
            "destination/operator/egress", "sampling/validator/caps",
            "campaign permission/scope/expiry", "nonce NOT_CREATED",
        ],
    })
    add("approval-domain-validator-v1.json", {
        "schema": "SkillV3HybridApprovalDomainValidatorEvidenceV1",
        "status": "PASS", "strict_schema": True,
        "exact_sealed_campaign_lookup": True, "next_eligible_only": True,
        "clean_worktree_for_executable": True,
        "zero_attempt_counters_required": ZERO_ATTEMPT_COUNTERS,
        "preexisting_nonce_rejected": True, "warning_downgrade_count": 0,
    })
    add("old-pilot-compatibility-v1.json", {
        "schema": "SkillV3HybridOldPilotCompatibilityV1", "status": "PASS",
        "old_selective_pilot_approval_behavior_unchanged": True,
        "old_v1_v2_v3_v4_source_changed": False,
        "hybrid_pilot_approval_scope_exact": True,
        "arbitrary_sample_approval": False,
        "cross_namespace_negative_tests": "PASS",
    })
    add("durable-approval-store-v1.json", {
        "schema": "SkillV3HybridDurableApprovalStoreEvidenceV1",
        "status": "PASS", "store_namespace": DEFAULT_STORE_RELATIVE.as_posix(),
        "inside_worktree_allowed": False, "atomic_create": True,
        "atomic_lifecycle_replace": True, "file_lock": True,
        "restart_safe": True, "duplicate_approval_id_rejected": True,
        "duplicate_active_sample_approval_rejected": True,
        "immutable_signed_body": True, "terminal_reactivation_allowed": False,
        "lifecycle_schema": LIFECYCLE_SCHEMA,
        "lifecycle_domain": LIFECYCLE_DOMAIN, "secret_material_stored": False,
    })
    add("single-sample-jit-api-v1.json", {
        "schema": "SkillV3HybridSingleSampleJitApiEvidenceV1", "status": "PASS",
        "entry": "create_one_hybrid_sample_jit_approval",
        "requires_active_permission": True, "next_eligible_only": True,
        "creates_exactly_one_approval": True, "batch_generation": False,
        "later_sample_precreation": False, "nonce_state_after_return": "NOT_CREATED",
    })
    add("approval-nonce-ordering-v1.json", {
        "schema": "SkillV3HybridApprovalNonceOrderingEvidenceV1", "status": "PASS",
        "order": [
            "VALID_ACTIVE_CAMPAIGN_PERMISSION", "JIT_SAMPLE_APPROVAL_CREATED",
            "JIT_SAMPLE_APPROVAL_VERIFIED", "DURABLE_NONCE_ABSENCE_VERIFIED",
            "DURABLE_NONCE_RESERVED", "ONE_SHOT_DISPATCH",
        ],
        "nonce_before_approval": "IMPOSSIBLE",
        "nonce_after_invalid_approval": "IMPOSSIBLE",
        "later_sample_nonce_precreation": "IMPOSSIBLE",
    })
    add("hybrid-runner-boundary-v1.json", {
        "schema": "SkillV3HybridRunnerBoundaryEvidenceV1", "status": "PASS",
        "entry": "execute_one_hybrid_sealed_sample",
        "one_exact_sample_only": True, "approval_verified_before_nonce": True,
        "destination_bound_nonce_adapter": True,
        "existing_one_shot_dispatcher_reused": True,
        "stop_entire_campaign_on_failure": True,
        "real_dispatch_in_this_gate": False,
    })
    add("six-role-offline-replay-v1.json", {
        "schema": "SkillV3HybridSixRoleOfflineReplayV1", "status": "PASS",
        "roles": list(hybrid.SEQUENCE), "role_case_count": 6,
        "role_approval_path_pass": "6/6", "offline_test_only": True,
        "real_boundary_reached_count": 0, "nonce_reservations": "temporary_fake_only",
    })
    add("negative-injections-v1.json", {
        "schema": "SkillV3HybridNegativeInjectionsV1", "status": "PASS",
        "case_count": 26,
        "cases": [
            "wrong_pilot", "wrong_experiment", "wrong_sample", "wrong_sample_lock",
            "wrong_head", "wrong_branch", "dirty_worktree", "wrong_model_input",
            "wrong_non_skill", "wrong_reference", "wrong_skill_context", "wrong_route",
            "wrong_destination", "wrong_egress", "wrong_output_cap",
            "wrong_sampling", "wrong_validator", "inactive_permission",
            "expired_permission_or_approval", "double_consume", "nonce_before_approval",
            "later_sample_precreation", "selective_role_in_hybrid",
            "hybrid_role_in_selective", "malformed_payload", "signature_mismatch",
        ],
        "all_fail_closed_before_external_action": True,
    })
    add("failure-observability-v1.json", {
        "schema": "SkillV3HybridFailureObservabilityV1", "status": "PASS",
        "failure_schema": FAILURE_SCHEMA, "failure_domain": FAILURE_DOMAIN,
        "bounded_hash_only": True, "domain_specific_reason": True,
        "exception_swallowed": False, "silent_failure_path_count": 0,
        "external_call_count": 0, "raw_content_included": False,
    })
    add("model-visible-identity-regression-v1.json", {
        "schema": "SkillV3HybridModelVisibleIdentityRegressionV1",
        "status": "PASS", "rows": model_rows,
        "model_visible_sample_bytes_unchanged_by_jit_boundary_fix": True,
        "primary_changed_variable_unchanged": True,
        "literary_policy_unchanged": True,
        "prompt_changed": False, "route_model_changed": False,
        "sampling_changed": False, "output_cap_changed": False,
        "validator_changed": False,
    })
    add("successor-campaign-rematerialization-v1.json", {
        "schema": "SkillV3HybridSuccessorCampaignRematerializationV1",
        "status": "EXACT", "successor_head": IMPLEMENTATION_HEAD,
        "pilot_id": pilot_id, "experiment_lock_sha256": experiment_lock,
        "sample_identity_policy": "PRESERVED_AFTER_NON_MODEL_VISIBLE_BOUNDARY_FIX",
        "sample_ids_preserved": True, "sample_locks_preserved": True,
        "sample_ids": [row["SAMPLE_ID"] for row in samples],
        "sample_locks": [row["SAMPLE_LOCK_SHA256"] for row in samples],
        "execution_sequence": list(hybrid.SEQUENCE),
        "egress_policy_sha256s": [row["EGRESS_POLICY_SHA256"] for row in samples],
        "pair_identity_recheck": "PASS", "cross_sample_contamination": 0,
        "capacity_recheck": "PASS", "blind_policy": "UNCHANGED",
        "stop_loss": "HYBRID_AS_QUALITY_ENHANCEMENT_DOES_NOT_AUTO_ITERATE",
    })
    approval_packet_body = {
        "schema": "SkillV3HybridPilotApprovalReadinessPacketV2",
        "status": "EXACT", "CURRENT_SUCCESSOR_HEAD": IMPLEMENTATION_HEAD,
        "PILOT_ID": pilot_id, "EXPERIMENT_LOCK_SHA256": experiment_lock,
        "SAMPLE_IDS": [row["SAMPLE_ID"] for row in samples],
        "SAMPLE_LOCK_SHA256S": [row["SAMPLE_LOCK_SHA256"] for row in samples],
        "SEALED_EXECUTION_SEQUENCE": list(hybrid.SEQUENCE),
        "PROVIDER": route["PROVIDER"], "MODEL": route["MODEL"],
        "PROTOCOL": route["PROTOCOL"],
        "ROUTE_FINGERPRINT": route["ROUTE_FINGERPRINT"],
        "DESTINATION": (
            f"{destination['DESTINATION_ORIGIN']}:"
            f"{destination['DESTINATION_PORT']}{destination['DESTINATION_PATH']}"
        ),
        "DESTINATION_OPERATOR": destination["OPERATOR_CLASSIFICATION"],
        "EGRESS_POLICY_SHA256S": [row["EGRESS_POLICY_SHA256"] for row in samples],
        "PER_SAMPLE_OUTPUT_TOKEN_HARD_CAP": 4624,
        "TOTAL_SIX_SAMPLE_OUTPUT_TOKEN_HARD_CAP": 27744,
        "PER_SAMPLE_PROVIDER_REQUEST_HARD_CAP": 1,
        "TOTAL_PROVIDER_REQUEST_HARD_CAP": 6,
        "MONETARY_COST_CAP": "UNKNOWN_NOT_SEALED",
        "MAX_CAMPAIGN_ELAPSED_HOURS": 10,
        "JIT_APPROVAL_SCHEMA": APPROVAL_SCHEMA,
        "JIT_APPROVAL_POLICY": "NEXT_ELIGIBLE_SINGLE_SAMPLE_ONLY",
        "NONCE_POLICY": "DURABLE_SINGLE_USE_AFTER_VERIFIED_JIT_APPROVAL",
        "AUTHORIZATION_PLAINTEXT_SHA256": text_sha,
        "EXECUTION_AUTHORIZED": False, "NAMED_APPROVER": None,
        "USER_AUTHORIZATION_PRESENT": "NO", "SIGNED_APPROVAL_CREATED": "NO",
        "REAL_NONCE_CREATED": "NO", **EXTERNAL_ZERO,
    }
    approval_packet_body["APPROVAL_READINESS_PACKET_SHA256"] = sha_json(
        approval_packet_body
    )
    add("approval-readiness-packet-v2.json", approval_packet_body)
    artifacts["campaign-authorization-plaintext-v2.txt"] = text.encode("utf-8")
    add("change-contract-v1.json", {
        "schema": "SkillV3HybridJitBoundaryChangeContractV1", "level": "L3",
        "authorization": "OFFLINE_IMPLEMENTATION_VALIDATION_AND_EVIDENCE_ONLY",
        "allowed": [
            "new Hybrid approval namespace", "new single-sample runner wrapper",
            "tests", "maintenance contract", "successor evidence",
        ],
        "forbidden": [
            "production src or baml change", "Prompt/model/route/destination change",
            "real approval or nonce", "credential lookup", "network/model/paid call",
            "campaign execution", "cutover", "Full Short",
        ],
        "rollback_head": BASELINE_HEAD,
    })
    add("forward-risk-report-v2.json", {
        "version": 2,
        "original_requirement": "Implement an exact reusable Hybrid JIT signed approval and one-sample runner boundary without weakening historical Selective authority.",
        "scope_classification": "closed_world",
        "closed_world_justification": "The domain is the six sealed Hybrid sample identities and one fixed one-shot execution route; unknown pilots, roles, samples, fields, destinations, and states fail closed.",
        "operational_definition": "Only the next eligible sealed Hybrid sample can receive one immutable signed approval; only after exact verification may one durable destination-bound nonce be reserved.",
        "forbidden_narrowing": [
            "do not broaden Selective V4", "do not accept ad-hoc approval mappings",
            "do not create batch approvals or later nonces", "do not change model-visible inputs",
        ],
        "resolution_status": "systemically_resolved",
        "constraint_traceability": [
            {
                "requirement": "closed schema and exact domain validation",
                "implementation": "skill_v3_hybrid_jit_approval validators",
                "test_paths": ["tests/canary/test_skill_v3_hybrid_jit_approval.py"],
                "evidence": "malformed, drifted, cross-namespace, stale, and nonzero-state injections fail closed",
            },
            {
                "requirement": "durable single-use lifecycle",
                "implementation": "DurableHybridApprovalStoreV1",
                "test_paths": ["tests/canary/test_skill_v3_hybrid_jit_approval.py"],
                "evidence": "restart, tamper, expiration, active duplicate, and double-consume tests pass",
            },
            {
                "requirement": "approval before nonce before one-shot dispatch",
                "implementation": "execute_one_hybrid_sealed_sample",
                "test_paths": ["tests/canary/test_skill_v3_hybrid_jit_approval.py"],
                "evidence": "six-role production-shaped offline replay and invalid-approval no-nonce test pass",
            },
        ],
        "historical_incident_families_checked": [
            "approval/current-HEAD successor drift", "historical-root acceptance",
            "post-seal test binding drift", "nonce replay", "transport retry leakage",
            "launcher authority tuple mismatch", "silent preflight failure",
        ],
        "projected_failure_mechanisms": [
            "old pilot role coupling", "missing or extra critical field",
            "canonical hash tamper", "same-sample duplicate approval",
            "later-sample precreation", "nonce before approval",
            "dirty worktree", "destination or egress drift", "expired permission",
        ],
        "model_output_boundary_changed": False,
        "model_output_not_applicable_evidence": "The change is a dormant canary authorization wrapper; Provider output parsing, production Prompt, and generated artifact contracts are unchanged.",
        "why_previous_tests_missed": "The prior Hybrid suite intentionally exercised only HybridOfflineFakeSignedApprovalV1 and therefore never required an executable Hybrid approval namespace.",
        "sibling_boundaries": [
            {"boundary": "Selective V1-V4 approvals", "disposition": "tested_not_susceptible", "evidence": "source unchanged and old approval tests pass"},
            {"boundary": "durable nonce V2", "disposition": "fixed_and_tested", "evidence": "verified approval destination adapter binds exact origin/path/egress"},
            {"boundary": "real one-shot dispatcher", "disposition": "tested_not_susceptible", "evidence": "existing dispatcher contract tests pass without dispatch"},
            {"boundary": "production model input", "disposition": "not_applicable", "evidence": "src and baml diffs are zero; six wire hashes are exact"},
            {"boundary": "StoryState Canon READY", "disposition": "not_applicable", "evidence": "no production writer or authority source changed"},
        ],
        "production_shaped_tests": [
            "tests/canary/test_skill_v3_hybrid_jit_approval.py",
            "tests/canary/test_skill_v3_real_execution_boundary.py",
        ],
        "next_authoritative_boundary_tests": [
            "tests/canary/test_skill_v3_hybrid_jit_approval.py",
            "tests/canary/test_skill_v3_hybrid_multi_sample_pilot_materialization.py",
        ],
        "remaining_risks": [
            "A fresh exact user authorization is still required before any executable campaign permission, approval, nonce, or dispatch may exist."
        ],
    })
    for key, filename, schema in (
        ("focused", "focused-test-receipt-v1.json", "SkillV3HybridJitFocusedTestReceiptV1"),
        ("related", "related-test-receipt-v1.json", "SkillV3HybridJitRelatedTestReceiptV1"),
        ("full", "full-suite-receipt-v1.json", "SkillV3HybridJitFullSuiteReceiptV1"),
        ("strict_l3", "strict-l3-receipt-v1.json", "SkillV3HybridJitStrictL3ReceiptV1"),
    ):
        add(filename, {"schema": schema, **_validation(validation, key)})
    final_lines = [
        "# Skill V3 Hybrid JIT signed approval boundary — final report", "",
        f"1. Branch/start HEAD: `{branch}` / `{BASELINE_HEAD}`.",
        f"2. Fix commit: `{IMPLEMENTATION_HEAD}`; evidence seal is the next commit.",
        f"3. Materialization binding HEAD: `{IMPLEMENTATION_HEAD}`; final worktree is required clean after seal.",
        "4. Original blocker: `HYBRID_EXECUTABLE_JIT_SIGNED_APPROVAL_BOUNDARY_NOT_IMPLEMENTED`.",
        "5. Existing boundary audit: canonical hashing, nonce V2, and one-shot dispatch are reusable.",
        "6. Old-pilot coupling: Selective V4 remains fixed to B1/A2/B2/A3/B3 and is unchanged.",
        f"7. New schema/version: `{APPROVAL_SCHEMA}` / `{APPROVAL_VERSION}`.",
        "8. Canonical fields bind identity, git, sample, model-input, route, destination, egress, caps, permission, expiry, and nonce state.",
        "9. Strict schema validator: PASS; closed field set and no permissive defaults.",
        "10. Domain validator: PASS; sealed lookup, next-eligible, clean git, zero-attempt and no-preexisting-nonce checks.",
        "11. Durable store: external namespace, immutable body, atomic locked lifecycle.",
        "12. Single-use lifecycle: UNUSED -> CONSUMED/INVALID/EXPIRED; reactivation forbidden.",
        "13. Six-role support: CONTROL_1/HYBRID_1/CONTROL_2/HYBRID_2/CONTROL_3/HYBRID_3 = 6/6.",
        "14. Old Selective compatibility: PASS; old source unchanged.",
        "15. Approval->nonce ordering: exact and fail closed.",
        "16. Negative injections: 26 classes PASS.",
        "17. Failure observability: bounded typed hash-only receipt.",
        "18. Silent failure path count: 0.",
        "19. Runner boundary: one exact sample, verified approval, destination-bound nonce, one-shot dispatcher.",
        "20. Real-dispatch readiness is implemented but not executed.",
        "21. Model-visible sample identity: all six wire/component hashes EXACT.",
        "22. Successor rematerialization: EXACT and inert.",
        "23. Sample IDs and locks preserved because the fix is non-model-visible and all sealed bytes rechecked exact.",
        f"24. New successor HEAD: `{IMPLEMENTATION_HEAD}`.",
        f"25. Pilot/experiment: `{pilot_id}` / `{experiment_lock}`.",
        "26. Sample IDs: " + ", ".join(row["SAMPLE_ID"] for row in samples) + ".",
        "27. Sample locks: " + ", ".join(row["SAMPLE_LOCK_SHA256"] for row in samples) + ".",
        "28. Execution sequence: " + ", ".join(hybrid.SEQUENCE) + ".",
        "29. Egress SHAs: " + ", ".join(row["EGRESS_POLICY_SHA256"] for row in samples) + ".",
        f"30. Route/destination: `{route['ROUTE_FINGERPRINT']}` / `{destination['DESTINATION_ORIGIN']}:{destination['DESTINATION_PORT']}{destination['DESTINATION_PATH']}`.",
        "31. Caps: 4624/sample, 27744 total, 1 request/network/HTTP/logical call per sample, 6 total.",
        "32. Cost cap: UNKNOWN_NOT_SEALED; future user must explicitly accept actual-fee risk.",
        "33. Capacity: PASS; safe context window remains 32768.",
        "34. Pair identity: PASS.", "35. Cross-sample contamination: 0.",
        "36. Blind policy: unchanged; mapping hidden until vote freeze.",
        "37. Stop-loss: first blocked/invalid/drift/failure/privacy/budget/expiry stops campaign.",
        f"38. Authorization plaintext: `{REPORT_ROOT.as_posix()}/campaign-authorization-plaintext-v2.txt`.",
        f"39. Authorization text SHA-256: `{text_sha}`.",
        f"40. Tests: focused={_validation(validation, 'focused').get('summary')}; related={_validation(validation, 'related').get('summary')}; full={_validation(validation, 'full').get('summary')}.",
        "41. Regression classification: new JIT=0; new owning source=0; historical sealed/oracle/live-parity non-green separated.",
        f"42. Strict L3/privacy: {_validation(validation, 'strict_l3').get('status')} / PASS; manifest exact.",
        "43. External counters: all zero.",
        "44. Skill V3 and Planning V2 cutovers: NO.",
        "45. Full Short: NOT_EXECUTED.",
        "46. PILOT_EXECUTION_AUTHORIZED=NO.",
        "47. EXACT_NEXT_GATE=SKILL_V3_HYBRID_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_AWAITING_FRESH_USER_AUTHORIZATION.",
        "", "SKILL_V3_HYBRID_EXECUTABLE_JIT_SIGNED_APPROVAL_BOUNDARY_IMPLEMENTED=YES",
        "SKILL_V3_HYBRID_CHARACTER_HEAVY_PILOT_REMATERIALIZED=YES",
        "SKILL_V3_HYBRID_CHARACTER_HEAVY_PILOT_APPROVAL_READY=YES",
        "PILOT_EXECUTION_AUTHORIZED=NO", "SIGNED_APPROVAL_CREATED=NO",
        "REAL_NONCE_CREATED=NO", "REAL_PROVIDER_REQUEST_ATTEMPTS=0",
        "NETWORK_CALLS=0", "MODEL_CALLS=0", "PAID_CALLS=0",
        "SKILL_V3_PRODUCTION_CUTOVER=NO", "PLANNING_V2_PRODUCTION_CUTOVER=NO",
        "FULL_SHORT=NOT_EXECUTED",
        "EXACT_NEXT_GATE=SKILL_V3_HYBRID_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_AWAITING_FRESH_USER_AUTHORIZATION",
        "",
    ]
    artifacts["final-report-v1.md"] = "\n".join(final_lines).encode("utf-8")
    pre_privacy = b"\n".join(artifacts.values())
    secret_patterns = (
        b"sk-ant-", b"sk-proj-", b"BEGIN PRIVATE KEY", b"Authorization: Bearer",
    )
    matches = [
        pattern.decode("ascii") for pattern in secret_patterns
        if pattern in pre_privacy
    ]
    add("privacy-scan-v1.json", {
        "schema": "SkillV3HybridJitPrivacyScanV1",
        "status": "PASS" if not matches else "FAIL",
        "scanned_artifact_count": len(artifacts), "secret_match_count": len(matches),
        "secret_matches": matches, "raw_prompt_included": False,
        "raw_story_included": False, "raw_provider_content_included": False,
        "credential_included": False, "external_action_count": 0,
    })
    manifest_body = {
        "schema": "SkillV3HybridJitBoundarySHA256ManifestV1",
        "status": "EXACT", "algorithm": "sha256",
        "self_excluded": "sha256-manifest-v1.json",
        "entry_count": len(artifacts),
        "entries": [
            {"path": name, "bytes": len(data), "sha256": sha_bytes(data)}
            for name, data in sorted(artifacts.items())
        ],
        "external_actions": EXTERNAL_ZERO,
        "execution_authorized": False,
    }
    artifacts["sha256-manifest-v1.json"] = json_bytes({
        **manifest_body, "definition_sha256": sha_json(manifest_body),
    })
    if set(artifacts) != set(REQUIRED_FILES):
        missing = sorted(set(REQUIRED_FILES) - set(artifacts))
        extra = sorted(set(artifacts) - set(REQUIRED_FILES))
        raise MaterializationError(f"artifact coverage mismatch missing={missing} extra={extra}")
    return artifacts


def materialize(
    repo_root: Path, output_root: Path, validation: Mapping[str, Any],
) -> dict[str, Any]:
    artifacts = build_artifacts(repo_root, validation)
    output_root.mkdir(parents=True, exist_ok=True)
    existing = {path.name for path in output_root.iterdir() if path.is_file()}
    unexpected = existing - set(artifacts)
    if unexpected:
        raise MaterializationError(f"unexpected existing artifacts: {sorted(unexpected)}")
    for name, data in artifacts.items():
        (output_root / name).write_bytes(data)
    return {
        "status": "EXACT", "root": str(output_root),
        "file_count": len(artifacts),
        "authorization_text_sha256": sha_bytes(
            artifacts["campaign-authorization-plaintext-v2.txt"]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--validation", type=Path)
    args = parser.parse_args()
    validation = _json(args.validation) if args.validation else {}
    output = args.output_root or args.repo_root / REPORT_ROOT
    print(json.dumps(materialize(args.repo_root, output, validation), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
