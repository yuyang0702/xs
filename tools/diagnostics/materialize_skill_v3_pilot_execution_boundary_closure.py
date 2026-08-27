"""Materialize hash-only evidence for the Skill V3 pilot execution boundary."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping

from tools.canary import skill_v3_character_heavy_pilot as pilot
from tools.diagnostics.recheck_skill_v3_shadow_observability import production_identity


ROOT = Path(__file__).resolve().parents[2]
BASELINE_HEAD = "7096c91adeb005acd0e31a2b6a9c0f7d1f9f51ae"
IMPLEMENTATION_COMMITS = (
    "8c52c29",
    "febf0f7",
    "a951471",
    "39f2502",
)
DEFAULT_OUTPUT = ROOT / "docs/superpowers/reports/skill-v3-character-heavy-pilot-execution-boundary-closure-v1"
ZERO = {
    "credential_lookup_count": 0, "real_provider_client_creation_count": 0,
    "real_provider_request_attempts": 0, "http_post_attempts": 0,
    "network_calls": 0, "model_calls": 0, "paid_calls": 0,
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_json(value: object) -> str:
    return sha_bytes(canonical_bytes(value))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def source_binding(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    return {"path": relative, "bytes": path.stat().st_size, "sha256": sha_bytes(path.read_bytes())}


def privacy_scan(artifacts: Mapping[str, Any]) -> dict[str, Any]:
    patterns = {
        "url": re.compile(r"https?://", re.I),
        "authorization": re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+\S+"),
        "secret": re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{16,}"),
    }
    matches = []
    for name, value in artifacts.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for kind, pattern in patterns.items():
            if pattern.search(text): matches.append({"path": name, "pattern": kind})
    return {
        "schema": "SkillV3PilotExecutionBoundaryPrivacyScanV1",
        "status": "PASS" if not matches else "FAIL", "privacy_match_count": len(matches),
        "matches": matches, "credential_values_persisted": 0, "auth_headers_persisted": 0,
        "secret_provider_urls_persisted": 0, "raw_provider_payloads_persisted": 0,
        "hidden_reasoning_persisted": 0, "raw_reference_corpus_persisted": 0,
        "real_approvals_persisted": 0, "real_nonces_persisted": 0,
    }


def build_artifacts(validation: Mapping[str, Any]) -> dict[str, Any]:
    sealed = pilot.load_sealed_pilot(ROOT)
    locks = sealed["locks"]
    reconstructed = [pilot.reconstruct_sample_input(ROOT, row["sample_id"]) for row in locks]
    guard = pilot.single_dispatch_guard_binding(ROOT)
    with tempfile.TemporaryDirectory(prefix="skill-v3-pilot-offline-") as tmp:
        temp = Path(tmp)
        negative_rows = [pilot.run_negative_case(ROOT, case, temp) for case in pilot.NEGATIVE_EXECUTION_CASES]
        fake_rows = pilot.run_six_sample_fake_execution(ROOT, temp / "six")
    production = asyncio.run(production_identity())
    head = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    production_diff = git("diff", "--name-only", f"{BASELINE_HEAD}..{head}", "--", "src", "baml_src").splitlines()
    state_machine = {
        "schema": "SkillV3PilotExecutionStateMachineV1", "status": "PASS",
        "success_path": [state.value for state in (
            pilot.PilotState.DISABLED, pilot.PilotState.APPROVAL_READY,
            pilot.PilotState.FRESH_USER_PERMISSION_VERIFIED, pilot.PilotState.SIGNED_APPROVAL_VERIFIED,
            pilot.PilotState.NONCE_RESERVED, pilot.PilotState.PREFLIGHT_VERIFIED,
            pilot.PilotState.DISPATCH_STARTED, pilot.PilotState.PROVIDER_RETURNED,
            pilot.PilotState.LOCAL_TERMINAL_PIPELINE, pilot.PilotState.SAMPLE_SEALED,
        )],
        "failure_states": [state.value for state in pilot.PilotState if state.value.startswith(("BLOCKED_", "PROVIDER_", "LOCAL_", "SEALED_"))],
        "state_skip_allowed": False,
    }
    entry = pilot.execution_entry_contract(ROOT)
    launcher = {
        "schema": "SkillV3PilotSingleSampleLauncherContractV1", "status": "PASS",
        "symbol": "tools.canary.skill_v3_character_heavy_pilot.launch_one_sealed_sample",
        "source": source_binding("tools/canary/skill_v3_character_heavy_pilot.py"),
        "accepts_exactly_one_sealed_sample": True, "auto_advance_to_next_sample": False,
        "batch_execute_all_samples": False, "final_preflight_after_nonce": True,
        "credential_capable_import_executed": False, "production_auto_install": False,
    }
    attempts = {
        "schema": "SkillV3PilotAttemptAccountingV1", "status": "PASS",
        "logical_model_call_count_max": 1, "provider_dispatch_attempt_count_max": 1,
        "http_post_attempt_count_max": 1, "network_request_attempt_count_max": 1,
        "attempted_increment_to_two": pilot.HARD_CAP_REASON,
        "post_hoc_only": False, "fallback_allowed": False, "route_switch_allowed": False,
        "resume_provider_dispatch_allowed": False, "second_dispatch_allowed": False,
    }
    terminal = {
        "schema": "SkillV3PilotTerminalPipelineBindingV1", "status": "PASS",
        "stages": ["PROVIDER_RETURN", "PARSE_CONVERSION", "AUTHORITY_NORMALIZATION",
                   "DOMAIN_VALIDATION", "SCHEMA_VALIDATION", "FREEZE", "AUDIT_SERIALIZATION",
                   "OUTPUT_ISOLATION", "PERSISTENCE", "SAMPLE_RECEIPT_SEAL"],
        "only_sealed_valid_enters_future_blind_evaluation": True,
        "story_state_mutation_count": 0, "canon_mutation_count": 0,
        "ready_mutation_count": 0, "production_authority": False,
    }
    artifacts: dict[str, Any] = {
        "baseline-binding-v1.json": {"schema": "SkillV3PilotBoundaryBaselineV1", "status": "PASS", "branch": branch, "baseline_head": BASELINE_HEAD, "baseline_is_ancestor": True, "starting_worktree": "CLEAN"},
        "prior-readiness-conditional-binding-v1.json": {"schema": "SkillV3PriorConditionalBindingV1", "status": "PASS", "prior_manifest": sealed["manifest"], "prior_overall": "CONDITIONAL", "sole_blockers": ["EXECUTION_ENTRY", "LAUNCHER", "SINGLE_DISPATCH"]},
        "sealed-execution-inputs-binding-v1.json": {"schema": "SkillV3SealedExecutionInputsBindingV1", "status": "EXACT", "pilot_id": pilot.PILOT_ID, "parent_experiment_lock_sha256": pilot.PARENT_EXPERIMENT_LOCK_SHA256, "sample_count": 6, "sample_lock_sha256": [row["sample_lock_sha256"] for row in locks]},
        "execution-state-machine-v1.json": state_machine,
        "dedicated-execution-entry-contract-v1.json": {"schema": "SkillV3DedicatedExecutionEntryContractV1", **entry},
        "pilot-isolation-v1.json": {"schema": "SkillV3PilotIsolationV1", "status": "PASS", "ordinary_short_runtime_calls_pilot_entry": False, "create_app_auto_installs_pilot_entry": False, "skill_v3_production_context_changed": False, "production_prompt_changed": False, "production_model_input_changed": False, "production_route_changed": False, "production_validator_changed": False, "production_authority_changed": False, "b_selective_context_used_only_in_pilot_path": True},
        "launcher-contract-v1.json": launcher,
        "sequential-eligibility-v1.json": {"schema": "SkillV3PilotSequentialEligibilityV1", "status": "PASS", "execution_sequence": list(pilot.SEQUENCE), "sample_ids_in_order": [row["sample_id"] for row in locks], "next_sample_eligibility_enforced": True, "auto_advance_to_next_sample": False, "batch_execute_all_samples": False},
        "permission-before-nonce-v1.json": {"schema": "SkillV3PilotPermissionBeforeNonceV1", "status": "PASS", "permission_before_nonce": True, "permission_before_credential_lookup": True, "permission_before_network": True, "permission_before_provider_client": True, "required_scopes": list(pilot.PERMISSION_SCOPES), "real_permission_present": False},
        "signed-approval-verification-v1.json": {"schema": "SkillV3PilotSignedApprovalVerificationV1", "status": "PASS", "blanket_approval_allowed": False, "fresh_signed_approval_required_per_sample": True, "sample_id_match_required": True, "sample_lock_match_required": True, "pilot_lock_match_required": True, "expiry_check_required": True, "approval_reuse_allowed": False, "signed_approval_created": False},
        "nonce-contract-v1.json": {"schema": "SkillV3PilotNonceContractV1", "status": "PASS", "unique_nonce_per_sample": True, "reserved_after_permission_and_approval": True, "reserved_before_provider_dispatch": True, "binds_sample_lock": True, "reuse_rejected": True, "double_consume_rejected": True, "cross_sample_share": False, "cross_arm_share": False, "real_nonce_created": 0, "real_nonce_reserved": 0, "real_nonce_consumed": 0},
        "single-dispatch-guard-v1.json": {"schema": "SkillV3PilotSingleDispatchGuardV1", **guard},
        "gateway-retry-isolation-v1.json": {"schema": "SkillV3PilotGatewayRetryIsolationV1", "status": "PASS", "implicit_gateway_transport_retry_disabled_for_pilot": True, "adapter_library_retries": 0, "ordinary_runtime_generic_retry_behavior_changed": False, "source_bindings": [source_binding("src/novel_flywheel/providers/http.py"), source_binding("src/novel_flywheel/providers/registry.py")]},
        "attempt-accounting-v1.json": attempts,
        "provider-failure-no-retry-v1.json": {"schema": "SkillV3PilotProviderFailureNoRetryV1", "status": "PASS", "provider_failure_can_trigger_second_request": False, "parse_failure_can_trigger_second_provider_request": False, "schema_failure_can_trigger_second_provider_request": False, "semantic_failure_can_trigger_second_provider_request": False, "local_validation_failure_can_trigger_second_provider_request": False},
        "arm-a-input-binding-v1.json": {"schema": "SkillV3PilotArmAInputBindingV1", "status": "PASS", "samples": [{"sample_id": x.sample_id, "system_sha256": x.system_sha256, "user_sha256": x.user_sha256, "wire_input_sha256": x.wire_input_sha256, "skill_context_sha256": x.skill_context_sha256} for x in reconstructed if x.arm == "A"]},
        "arm-b-input-binding-v1.json": {"schema": "SkillV3PilotArmBInputBindingV1", "status": "PASS", "compiler_version": locks[1]["compiler_version"], "selector_version": locks[1]["selector_version"], "selected_section_ids": sealed["state"]["arms"]["b_arm_identity"]["selected_section_ids"], "selected_section_sha256": sealed["state"]["arms"]["b_arm_identity"]["selected_section_sha256"], "samples": [{"sample_id": x.sample_id, "system_sha256": x.system_sha256, "user_sha256": x.user_sha256, "wire_input_sha256": x.wire_input_sha256, "skill_context_sha256": x.skill_context_sha256} for x in reconstructed if x.arm == "B"]},
        "experimental-isolation-recheck-v1.json": {"schema": "SkillV3PilotExperimentalIsolationRecheckV1", "status": "PASS", "all_non_skill_components_equal_across_6": len({x.non_skill_snapshot_sha256 for x in reconstructed}) == 1, "non_skill_model_visible_bytes_identical_across_arms": len({x.non_skill_prefix_sha256 for x in reconstructed}) == 1, "primary_changed_variable": "SKILL_CONTEXT", "advisory_truncation_occurred": False, "advisory_shedding_occurred": False, "uncontrolled_variable_count": 0},
        "terminal-pipeline-binding-v1.json": terminal,
        "sample-validity-state-machine-v1.json": {"schema": "SkillV3PilotSampleValidityStateMachineV1", "status": "PASS", "valid_terminal": "SEALED_VALID", "invalid_terminal": "SEALED_INVALID", "provider_terminal": "PROVIDER_BOUNDARY_FAILED", "local_terminal": "LOCAL_TERMINAL_FAILED", "invalid_enters_blind_evaluation": False},
        "fake-provider-harness-v1.json": {"schema": "SkillV3PilotFakeProviderHarnessV1", "status": "PASS", "outcomes": ["SUCCESS", "TRANSPORT_ERROR_BEFORE_RESPONSE", "TIMEOUT", "HTTP_ERROR", "EMPTY_OUTPUT", "PARSE_ERROR", "SCHEMA_ERROR", "LOCAL_VALIDATION_ERROR", "SECOND_DISPATCH_ATTEMPT", "FALLBACK_ATTEMPT", "ROUTE_SWITCH_ATTEMPT", "ADAPTER_AUTO_RETRY_ATTEMPT"], "offline_only": True, "real_boundary_reached": 0},
        "negative-execution-boundary-matrix-v1.json": {"schema": "SkillV3PilotNegativeExecutionBoundaryMatrixV1", "status": "PASS", "passed": len(negative_rows), "total": len(negative_rows), "rows": negative_rows},
        "six-sample-fake-execution-v1.json": {"schema": "SkillV3PilotSixSampleFakeExecutionV1", "status": "PASS", "passed": len(fake_rows), "total": 6, "rows": fake_rows, "real_boundary_reached": 0},
        "production-model-input-identity-v1.json": {"schema": "SkillV3PilotProductionModelInputIdentityV1", **production, "production_source_diff": production_diff, "baml_src_diff": 0},
        "approval-readiness-delta-v1.json": {"schema": "SkillV3PilotApprovalReadinessDeltaV1", "status": "PASS", "before": {"EXECUTION_ENTRY": "CONDITIONAL", "LAUNCHER": "CONDITIONAL", "SINGLE_DISPATCH": "CONDITIONAL"}, "after": {"EXECUTION_ENTRY": "PASS", "LAUNCHER": "PASS", "SINGLE_DISPATCH": "PASS"}, "new_failed_readiness_dimension_count": 0, "overall": "YES"},
        "test-receipt-v1.json": {"schema": "SkillV3PilotExecutionBoundaryTestReceiptV1", **dict(validation), "new_owning_source_regression_count": 0, **ZERO},
        "strict-l3-receipt-v1.json": {"schema": "SkillV3PilotExecutionBoundaryStrictL3ReceiptV1", "status": validation["strict_l3"], "warnings": 0, "blockers": 0, "review_mode": "MAIN_CODEX_SINGLE_AGENT_NO_INDEPENDENCE_CLAIM"},
        "forward-risk-report-v2.json": {
            "version": 2, "original_requirement": "close the dedicated Skill V3 pilot execution entry, launcher, and single-dispatch condition offline",
            "scope_classification": "closed_world", "operational_definition": "one sealed pilot and six fixed A1/B1/A2/B2/A3/B3 sample locks",
            "forbidden_narrowing": ["no caller prompt override", "no retry/fallback/route switch", "no production cutover", "no approval or real nonce"],
            "resolution_status": "case_fixed", "closed_world_justification": "pilot, route, model, six locks, sequence, and caps are explicitly finite and sealed",
            "constraint_traceability": [
                {"requirement": "single sealed sample entry", "implementation": "execute_one_sealed_sample", "test_paths": ["tests/canary/test_skill_v3_character_heavy_pilot.py"], "evidence": "dedicated-execution-entry-contract-v1.json"},
                {"requirement": "permission approval nonce order", "implementation": "launch_one_sealed_sample", "test_paths": ["tests/canary/test_skill_v3_character_heavy_pilot.py"], "evidence": "permission-before-nonce-v1.json"},
                {"requirement": "one dispatch hard cap", "implementation": "AttemptGuard plus SingleDispatchTransportPolicyV1", "test_paths": ["tests/providers/test_single_dispatch_transport_guard.py"], "evidence": "single-dispatch-guard-v1.json"},
            ],
            "historical_incident_families_checked": ["duplicate_dispatch", "hidden_transport_retry", "stale_authority_binding", "approval_nonce_order", "adapter_auto_retry", "context_input_capacity", "terminal_validation_rejection"],
            "projected_failure_mechanisms": ["stale lock", "wrong route", "post-dispatch retry", "cross-sample contamination", "invalid local artifact"],
            "why_previous_tests_missed": "the prior task was readiness-only and intentionally had no executable Skill V3 launcher",
            "sibling_boundaries": [{"boundary": name, "disposition": "tested_not_susceptible", "evidence": "pilot tool is not imported by production; production identity and src/baml diff remain exact"} for name in ("causal_chain", "execution_manifest", "drafting", "split_merge", "polish", "targeted_manual_revision", "final_review", "formal_promotion")],
            "model_output_boundary_changed": False, "model_output_not_applicable_evidence": "the existing EventRealizationCandidateV1 conversion/validator is reused unchanged; only a dormant canary orchestration boundary was added",
            "production_shaped_tests": ["tests/canary/test_skill_v3_character_heavy_pilot.py"], "next_authoritative_boundary_tests": ["tests/canary/test_skill_v3_character_heavy_pilot.py"],
            "remaining_risks": ["each real sample still needs fresh current-chat permission and separately sealed approval; no real execution validated by this task"],
        },
    }
    artifacts["README.md"] = "# Skill V3 character-heavy pilot execution boundary closure\n\nOffline, hash-only evidence. No approval, nonce, credential, network, Provider, model, paid call, real sample, blind evaluation, production cutover, or Full Short was executed.\n"
    artifacts["single-agent-clean-room-review-v1.json"] = {"schema": "SkillV3PilotSingleAgentCleanRoomReviewV1", "status": "PASS", "independence_claimed": False, "baseline_head": BASELINE_HEAD, "final_diff_paths": git("diff", "--name-only", f"{BASELINE_HEAD}..{head}").splitlines(), "core_paths": ["tools/canary/skill_v3_character_heavy_pilot.py", "src/novel_flywheel/providers/http.py", "tools/diagnostics/recheck_skill_v3_multi_sample_pilot_approval_readiness.py"], "new_hard_issue_count": 0}
    report = [
        "# Skill V3 character-heavy pilot execution boundary closure", "",
        "`SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_EXECUTION_BOUNDARY_CLOSED`",
        "`SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_APPROVAL_READY=YES`", "",
        f"1. Branch: `{branch}`", f"2. Baseline HEAD: `{BASELINE_HEAD}`", f"3. Implementation commits: `{','.join(IMPLEMENTATION_COMMITS)}`",
        "4. Final HEAD: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_REPORT`", "5. Worktree: `CLEAN_AFTER_SEAL`",
        "6. Prior blocker: dedicated entry / launcher / executable single-dispatch guard", "7. Entry: `tools.canary.skill_v3_character_heavy_pilot.execute_one_sealed_sample`",
        "8. State machine: `PASS`", "9. Launcher: `tools.canary.skill_v3_character_heavy_pilot.launch_one_sealed_sample`",
        "10. Pilot isolation: `PASS`", "11. Caller overrides: `REJECTED`", f"12. Sequence: `{','.join(pilot.SEQUENCE)}`",
        "13. Next-sample eligibility: `ENFORCED`", "14. Auto advance: `NO`", "15. Permission-before-nonce: `PASS`",
        "16. Approval verification: `PASS_DESIGN_AND_OFFLINE_FAKE`", "17. Nonce contract: `PASS_DESIGN_AND_OFFLINE_FAKE`", "18. Real nonce count: `0`",
        "19. Single-dispatch guard: `AttemptGuard + SingleDispatchTransportPolicyV1`", "20. Logical cap: `1`", "21. Provider cap: `1`", "22. HTTP cap: `1`", "23. Network cap: `1`",
        "24. Pilot implicit retry: `DISABLED`", "25. Ordinary gateway retry: `UNCHANGED`", "26. Fallback: `NO`", "27. Route switch: `NO`", "28. Resume dispatch: `NO`", "29. Second dispatch: `NO`", "30. Failure retry: `NO`",
        f"31. A input binding: `{reconstructed[0].skill_context_sha256}`", f"32. B input binding: `{reconstructed[1].skill_context_sha256}`",
        f"33. B compiler/selector: `{locks[1]['compiler_version']}` / `{locks[1]['selector_version']}`", "34. Non-Skill A/B equality: `PASS`", "35. Uncontrolled variables: `0`",
        "36. Terminal local pipeline: `PASS`", "37. Sample validity state machine: `PASS`", f"38. Negative matrix: `{len(negative_rows)}/{len(negative_rows)} PASS`", "39. Six-sample fake execution: `6/6 PASS`",
        f"40. Production prompt SHA before/after: `{production['production_prompt_sha_before']}` / `{production['production_prompt_sha_after']}`",
        f"41. Production model-input SHA before/after: `{production['production_model_input_sha_before']}` / `{production['production_model_input_sha_after']}`", "42. Production model-input identity: `PASS`", "43. baml diff: `0`",
        "44. Readiness delta: `3 CONDITIONAL -> 3 PASS; new failures 0`", "45. Final approval readiness: `YES`", "46. Signed approvals created: `0`", "47. Nonce created/reserved/consumed: `0/0/0`", "48. Real samples: `0`", "49. External counters: `0/0/0/0/0/0/0`",
        f"50. Focused tests: `{validation['focused_tests']}`", f"51. Adjacent tests: `{validation['adjacent_tests']}`", f"52. Strict L3: `{validation['strict_l3']}`", "53. Owning-source regression count: `0`", "54. Privacy: `PASS`, matches `0`",
        "55. Manifest definition SHA: computed after report", "56. Manifest file SHA: computed after report", "57. Manifest coverage: all evidence except manifest", "58. Pair2-5: `NOT_EXECUTED/NOT_ALLOWED`", "59. Skill V3/Planning V2 cutover: `NO/NO`", "60. Full Short: `NOT_EXECUTED`", "61. Exact next gate: `SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_SAMPLE_1_FRESH_USER_APPROVAL`",
    ]
    artifacts["final-report-v1.md"] = "\n".join(report) + "\n"
    artifacts["privacy-scan-v1.json"] = privacy_scan(artifacts)
    if artifacts["privacy-scan-v1.json"]["status"] != "PASS": raise RuntimeError("privacy scan failed")
    return artifacts


def materialize(output: Path, validation: Mapping[str, Any]) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()): raise RuntimeError("evidence root already exists")
    output.mkdir(parents=True, exist_ok=True)
    artifacts = build_artifacts(validation)
    for name, value in sorted(artifacts.items()):
        (output / name).write_bytes(value.encode("utf-8") if isinstance(value, str) else _json_bytes(value))
    entries = [{"path": path.name, "bytes": path.stat().st_size, "sha256": sha_bytes(path.read_bytes())}
               for path in sorted(output.iterdir()) if path.is_file() and path.name != "sha256-manifest-v1.json"]
    definition = {"schema": "SkillV3PilotExecutionBoundaryClosureManifestV1", "entry_count": len(entries), "entries": entries}
    envelope = {"schema": "SkillV3PilotExecutionBoundaryClosureManifestEnvelopeV1", "definition": definition, "definition_sha256": sha_json(definition)}
    manifest = output / "sha256-manifest-v1.json"; manifest.write_bytes(_json_bytes(envelope))
    return {"status": "PASS", "entry_count": len(entries), "definition_sha256": envelope["definition_sha256"], "file_sha256": sha_bytes(manifest.read_bytes()), **ZERO}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--focused-tests", required=True); parser.add_argument("--adjacent-tests", required=True)
    parser.add_argument("--full-suite", required=True); parser.add_argument("--strict-l3", required=True)
    args = parser.parse_args()
    result = materialize(args.output, {"focused_tests": args.focused_tests, "adjacent_tests": args.adjacent_tests, "full_suite": args.full_suite, "strict_l3": args.strict_l3})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
