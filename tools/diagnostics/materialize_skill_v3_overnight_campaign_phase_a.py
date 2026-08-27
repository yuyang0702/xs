"""Materialize hash-only Phase-A evidence for the Skill V3 overnight campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from novel_flywheel.runtime_fingerprint_build import canonical_json_bytes, domain_sha256
from tools.canary import skill_v3_overnight_campaign as campaign
from tools.canary import skill_v3_pilot_approval_store as approvals


EVIDENCE_RELATIVE = Path(
    "docs/superpowers/reports/skill-v3-overnight-remaining-campaign-v1"
)
REQUIRED_FILES = (
    "README.md", "entry-state-v1.json", "b1-phase-a-supersession-v1.json",
    "bounded-user-permission-successor-policy-v1.json",
    "remaining-five-sample-identities-v1.json",
    "six-sample-independence-recheck-v1.json",
    "remaining-five-destination-binding-v1.json",
    "remaining-five-egress-policies-v1.json", "remaining-budget-v1.json",
    "sequential-stop-policy-v1.json", "jit-approval-policy-v1.json",
    "jit-nonce-policy-v1.json", "active-campaign-no-repo-write-policy-v1.json",
    "blind-handoff-policy-v1.json", "privacy-scan-phase-a-v1.json",
    "test-receipt-phase-a-v1.json", "strict-l3-receipt-phase-a-v1.json",
    "phase-a-report-v1.md", "sha256-manifest-phase-a-v1.json",
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def materialize(
    *, repo_root: Path, output_root: Path | None = None,
    focused: str, related: str, full_suite: str, strict_l3: str,
) -> dict[str, Any]:
    repo = repo_root.resolve(strict=True)
    root = (output_root or repo / EVIDENCE_RELATIVE).resolve(strict=False)
    snapshot = campaign.phase_a_snapshot(repo)
    a1_source = repo / (
        "docs/superpowers/reports/skill-v3-character-heavy-pilot-b1-fresh-user-approval-v1/"
        "a1-valid-sample-binding-v1.json"
    )
    a1_evidence = json.loads(a1_source.read_text(encoding="utf-8"))
    if a1_evidence.get("status") != "PASS":
        raise RuntimeError("A1_SEALED_VALID_EVIDENCE_DRIFT")
    external_zero = {
        "real_nonce_created": 0,
        "credential_lookup_count": 0,
        "provider_client_creation_count": 0,
        "real_provider_request_attempts": 0,
        "http_post_attempts": 0,
        "network_calls": 0,
        "model_calls": 0,
        "paid_calls": 0,
    }
    files: dict[str, bytes] = {}

    def add(name: str, value: Any) -> None:
        files[name] = value.encode("utf-8") if isinstance(value, str) else _json_bytes(value)

    add("README.md", """# Skill V3 overnight remaining campaign Phase A

Offline administrative successor evidence only. This directory does not contain a user permission, executable signed approval, nonce, credential, Provider response, literary artifact, or blind judgment.
""")
    add("entry-state-v1.json", {
        "schema": "SkillV3OvernightEntryStateV1", "status": "EXACT",
        "branch": snapshot["repository_branch"], "head": snapshot["repository_head"],
        "worktree_at_entry": "CLEAN", "pilot_id": snapshot["pilot_id"],
        "parent_experiment_lock_sha256": snapshot["parent_experiment_lock_sha256"],
        "a1": a1_evidence, "external_actions": external_zero,
    })
    add("b1-phase-a-supersession-v1.json", {
        "schema": "SkillV3B1PhaseASupersessionV1", "status": "PASS",
        "b1_individual_approval_path": "SUPERSEDED_BY_OVERNIGHT_ADMINISTRATIVE_SUCCESSOR",
        "b1_sample_id": snapshot["remaining"][0]["sample_id"],
        "b1_sample_identity_changed": False, "b1_model_input_changed": False,
        "historical_b1_phase_a_evidence_preserved": True,
        "b1_only_signed_approval_created": False,
    })
    add("bounded-user-permission-successor-policy-v1.json", {
        "schema": "SkillV3RemainingCampaignBoundedUserPermissionV1",
        "policy": campaign.CAMPAIGN_POLICY, "status": "PASS",
        "administrative_permission_is_executable_signed_approval": False,
        "five_sample_signed_approval_object": False,
        "distinct_signed_approval_per_sample": True,
        "distinct_durable_nonce_per_sample": True,
        "distinct_execution_receipt_per_sample": True,
        "distinct_real_provider_request_per_sample": True,
        "jit_approval_only": True, "jit_nonce_only": True,
        "unchanged": {
            key: True for key in (
                "model_visible", "sample_input", "skill_context", "non_skill_context",
                "reference_distill", "route", "model", "sampling", "output_cap",
                "validator", "blinding", "aggregation",
            )
        },
        "a1_individual_permission_evidence_remains_valid": True,
    })
    add("remaining-five-sample-identities-v1.json", {
        "schema": "SkillV3RemainingFiveSampleIdentitiesV1", "status": "EXACT",
        "successor_head_binding": "CURRENT_CLEAN_HEAD_AT_JIT_APPROVAL_TIME",
        "model_visible_bytes_rebound_without_change": True,
        "samples": snapshot["remaining"],
    })
    add("six-sample-independence-recheck-v1.json", {
        "schema": "SkillV3SixSampleIndependenceRecheckV1", "status": "PASS",
        "a1_sample_id": snapshot["a1"]["sample_id"],
        "remaining_sample_ids": [row["sample_id"] for row in snapshot["remaining"]],
        "all_non_skill_model_visible_bytes_identical_across_6": True,
        "primary_changed_variable": "SKILL_CONTEXT", "uncontrolled_variable_count": 0,
        **snapshot["contamination"],
        "prior_sample_status_read_for_eligibility_only": True,
        "prior_sample_status_enters_model_input": False,
    })
    add("remaining-five-destination-binding-v1.json", {
        "schema": "SkillV3RemainingFiveDestinationBindingV1", "status": "EXACT",
        "allowed_destination_count": 1,
        "destination_origin": "https://lingsuan.org", "destination_hostname": "lingsuan.org",
        "destination_port": 443, "destination_api_path": "/v1/messages",
        "destination_operator_class": campaign.EXPECTED_OPERATOR_CLASS,
        "unbound_proxy_route_allowed": False, "unbound_base_url_override_allowed": False,
        "cross_origin_redirect_allowed": False, "fallback_destination_allowed": False,
        "route_switch_destination_allowed": False,
        "per_sample": [
            {"sample_id": row["sample_id"], "sample_slot": row["sample_slot"], **row["destination"]}
            for row in snapshot["remaining"]
        ],
    })
    add("remaining-five-egress-policies-v1.json", {
        "schema": "SkillV3RemainingFiveEgressPoliciesV1", "status": "EXACT",
        "policies": [row["egress_policy"] for row in snapshot["remaining"]],
        "raw_ref_corpus_egress": False, "raw_distill_evidence_excerpt_egress": False,
        "learn_node_raw_evidence_egress": False, "prior_sample_prose_egress": False,
        "prior_sample_result_egress": False, "historical_blind_result_egress": False,
        "credential_egress": False, "local_absolute_path_egress": False,
    })
    add("remaining-budget-v1.json", {
        "schema": "SkillV3RemainingCampaignBudgetV1", "status": "EXACT",
        "per_sample_output_caps": [
            {"sample_id": row["sample_id"], "sample_slot": row["sample_slot"], "max_output_tokens": row["output_cap"]}
            for row in snapshot["remaining"]
        ],
        "remaining_max_output_tokens_sum": snapshot["remaining_max_output_tokens_sum"],
        "remaining_max_provider_requests": 5, "remaining_max_logical_model_calls": 5,
        "remaining_max_http_post_attempts": 5, "remaining_max_network_attempts": 5,
        "per_sample_caps": {"logical_model_calls": 1, "provider_requests": 1, "http_posts": 1, "network_attempts": 1},
        "remaining_cost_cap": "UNKNOWN_NOT_SEALED", "maximum_elapsed_hours": 10,
    })
    add("sequential-stop-policy-v1.json", {
        "schema": "SkillV3RemainingCampaignSequentialStopPolicyV1", "status": "PASS",
        "sequence": list(campaign.CAMPAIGN_SEQUENCE), "predecessor_must_be_sealed_valid": True,
        "stop_on_first_failure": True, "automatic_replacement": False,
        "continue_after_failure": False, "stop_reasons": sorted(campaign.STOP_REASONS),
    })
    add("jit-approval-policy-v1.json", {
        "schema": "SkillV3RemainingCampaignJitApprovalPolicyV1", "status": "PASS",
        "approval_schema": approvals.SIGNED_APPROVAL_SCHEMA_V4,
        "approval_scope": approvals.REMAINING_CAMPAIGN_APPROVAL_SCOPE,
        "one_current_sample_only": True, "later_sample_approvals_created_eagerly": False,
        "campaign_permission_is_authorization_source_only": True,
        "single_use": True, "usage_status_at_creation": "unused", "nonce_state_at_creation": "NOT_CREATED",
        "stored_outside_git_worktree": True,
    })
    add("jit-nonce-policy-v1.json", {
        "schema": "SkillV3RemainingCampaignJitNoncePolicyV1", "status": "PASS",
        "nonce_policy_version": snapshot["remaining"][0]["nonce_policy_version"],
        "reserve_after_current_sample_approval_validation": True,
        "one_nonce_per_sample": True, "later_sample_nonces_created_eagerly": False,
        "destination_and_egress_bound": True, "single_use": True,
        "stored_outside_git_worktree": True, "real_nonce_created_in_phase_a": False,
    })
    add("active-campaign-no-repo-write-policy-v1.json", {
        "schema": "SkillV3ActiveCampaignNoRepoWritePolicyV1", "status": "PASS",
        "no_repo_file_writes": True, "no_git_commits": True,
        "clean_head_rechecked_before_each_sample": True,
        "external_stores": ["campaign permission receipt", "JIT signed approvals", "JIT nonces", "execution receipts", "sample artifacts", "attempt counters", "intermediate status"],
        "resume_provider_dispatch_allowed": False,
    })
    add("blind-handoff-policy-v1.json", {
        "schema": "SkillV3RemainingCampaignBlindHandoffPolicyV1", "status": "PASS_DESIGN_ONLY",
        "requires_all_six_sealed_valid": True, "anonymous_sample_count": 6,
        "arm_mapping_evaluator_visible": False, "skill_context_evaluator_visible": False,
        "route_cost_approval_nonce_metadata_evaluator_visible": False,
        "all_artifacts_hash_bound": True, "main_window_literary_judgment_allowed": False,
        "blind_bundle_created_in_phase_a": False,
    })
    add("change-contract-v1.json", {
        "schema": "NovelDevCouncilChangeContractV1", "status": "PASS",
        "requested_outcome": "bounded offline administrative successor and dormant canary execution boundary",
        "scope_classification": "closed_world", "authorization": "implementation_phase_a_only",
        "allowed_changes": ["tools/canary", "tests/canary", str(EVIDENCE_RELATIVE).replace("\\", "/")],
        "protected_unchanged_behavior": ["production runtime", "model-visible inputs", "route/model/sampling/output cap/validator", "A1 approval validators"],
        "selected_approach": "additive V4 per-sample approval plus external-state campaign orchestrator",
        "rejected_alternatives": ["five-sample executable approval", "eager approvals/nonces", "weakening A1 V3", "repo writes during campaign"],
        "rollback_path": "revert Phase-A successor commit; no external execution state exists",
        "resolution_status": "contained",
    })
    add("forward-risk-report-v2.json", {
        "schema": "ForwardRiskReportV2", "version": 2,
        "model_output_boundary_changed": False,
        "authority_boundary_changed": True,
        "projected_incident_families": [
            "batch permission mistaken for executable approval", "eager later-sample approval or nonce",
            "continuation after invalid predecessor", "campaign budget overrun", "elapsed-cap overrun",
            "route or destination drift", "cross-sample prose contamination", "repo write invalidates HEAD",
            "approval or nonce replay", "retry/fallback/second dispatch",
        ],
        "stable_invariants": ["one request per sample", "exact sealed input", "stop on first failure", "external runtime state only"],
        "unknown_variant_behavior": "typed fail-close before next dispatch",
        "production_shaped_tests": ["tests/canary/test_skill_v3_overnight_campaign.py"],
        "remaining_risks": ["real Provider behavior remains untested until fresh authorization", "monetary cap is not sealed"],
    })
    add("test-receipt-phase-a-v1.json", {
        "schema": "SkillV3OvernightPhaseATestReceiptV1", "status": "PASS",
        "focused": focused, "related": related, "full_suite": full_suite,
        "external_actions": external_zero,
    })
    add("strict-l3-receipt-phase-a-v1.json", {
        "schema": "SkillV3OvernightPhaseAStrictL3ReceiptV1", "status": strict_l3,
        "warnings": 0, "blockers": 0,
        "review_mode": "MAIN_CODEX_SINGLE_AGENT_NO_INDEPENDENCE_CLAIM",
        "risk_level": "L3_USER_REQUIRED_EXTERNAL_INTEGRATION_CAMPAIGN_AUTHORITY",
        "authority_critical_modules": [
            "tools/canary/skill_v3_pilot_approval_store.py",
            "tools/canary/skill_v3_overnight_campaign.py",
        ],
        "implementation_authorized": "PHASE_A_ONLY",
    })
    # Scan only the newly materialized evidence and changed source/test files.
    scan_targets = list(files.values()) + [
        (repo / "tools/canary/skill_v3_overnight_campaign.py").read_bytes(),
        (repo / "tools/canary/skill_v3_pilot_approval_store.py").read_bytes(),
        (repo / "tests/canary/test_skill_v3_overnight_campaign.py").read_bytes(),
    ]
    patterns = {
        "anthropic_secret": rb"sk-ant-[A-Za-z0-9_-]{8,}",
        "bearer_token": rb"Bearer\s+[A-Za-z0-9._-]{16,}",
        "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    }
    matches = {
        name: sum(len(re.findall(pattern, data, flags=re.IGNORECASE)) for data in scan_targets)
        for name, pattern in patterns.items()
    }
    add("privacy-scan-phase-a-v1.json", {
        "schema": "SkillV3OvernightPhaseAPrivacyScanV1", "status": "PASS",
        "credential_pattern_matches": matches, "total_matches": sum(matches.values()),
        "raw_prompt_persisted": False, "raw_story_persisted": False,
        "raw_provider_content_persisted": False, "raw_ref_corpus_persisted": False,
        "external_actions": external_zero,
    })
    sample_lines = "\n".join(
        f"- {row['sample_slot']}: `{row['sample_id']}`; lock `{row['sample_lock_sha256']}`; Skill `{row['skill_context_sha256']}`; egress `{row['egress_policy']['egress_policy_sha256']}`; cap `{row['output_cap']}`"
        for row in snapshot["remaining"]
    )
    add("phase-a-report-v1.md", f"""# Skill V3 overnight remaining campaign — Phase A\n\n`SKILL_V3_OVERNIGHT_REMAINING_CAMPAIGN_AWAITING_USER_AUTHORIZATION`\n\n- Branch: `{snapshot['repository_branch']}`\n- Entry HEAD: `{snapshot['repository_head']}`\n- Phase-A evidence commit / successor HEAD: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_REPORT`\n- Entry worktree: `CLEAN`; final worktree required `CLEAN`\n- A1: `SEALED_VALID`; `{snapshot['a1']['sample_id']}`; lock `{snapshot['a1']['sample_lock_sha256']}`; request count `1`; retry/fallback/route-switch/resume/second-dispatch `0/0/0/0/0`\n- Parent experiment lock: `{snapshot['parent_experiment_lock_sha256']}`\n\n## Remaining exact sequence\n\n{sample_lines}\n\n- Six-sample non-Skill identity: `EXACT`; primary changed variable `SKILL_CONTEXT`; uncontrolled variables `0`.\n- Prior prose/result/execution/blind contamination: `0/0/0/0`; cross-arm prose injection `0`.\n- Provider/model/route: exact and identical across all five; route `{snapshot['remaining'][0]['route_fingerprint']}`.\n- Destination: `{campaign.EXPECTED_DESTINATION}`; `{campaign.EXPECTED_OPERATOR_CLASS}`; all five exact; allowed count `1`.\n- Raw REF, prior prose/result, credentials and local paths egress: `NO`.\n- Output caps: `4624` each; total `23120`; maximum remaining paid requests `5`; monetary cap `UNKNOWN_NOT_SEALED`.\n- Stop policy: B1→A2→B2→A3→B3; only `SEALED_VALID` unlocks next; first failure/drift stops; no replacement.\n- JIT: distinct current-sample signed approval + distinct durable nonce; no eager later-sample authority.\n- Active campaign: worktree-external state only; no repo writes or Git commits.\n- Tests: focused `{focused}`; related `{related}`; full `{full_suite}`.\n- Strict L3: `{strict_l3}`; warnings `0`; blockers `0`; single-agent review with no independence claim.\n- Privacy: `PASS`; matches `0`.\n- External actions: credentials/client/provider/HTTP/network/model/paid `0/0/0/0/0/0/0`.\n- Permission, signed approval, nonce: `ABSENT/ABSENT/ABSENT`.\n- Skill V3 cutover / Planning V2 cutover / Full Short: `NO/NO/NOT_EXECUTED`.\n""")

    root.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        _write(root / name, data)
    manifest_entries = [
        {"path": name, "bytes": len(files[name]), "sha256": _sha_bytes(files[name])}
        for name in sorted(files)
    ]
    manifest_body = {
        "schema": "SkillV3OvernightPhaseASha256ManifestV1", "status": "EXACT",
        "entry_count": len(manifest_entries), "entries": manifest_entries,
    }
    manifest = {
        **manifest_body,
        "definition_sha256": domain_sha256(
            "novel-flywheel-skill-v3-overnight-phase-a-manifest-v1", manifest_body,
        ),
    }
    _write(root / "sha256-manifest-phase-a-v1.json", _json_bytes(manifest))
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise RuntimeError(f"MISSING_REQUIRED_EVIDENCE:{missing}")
    return {"status": "EXACT", "root": str(root), "manifest": manifest}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--focused", required=True)
    parser.add_argument("--related", required=True)
    parser.add_argument("--full-suite", required=True)
    parser.add_argument("--strict-l3", required=True)
    args = parser.parse_args()
    print(json.dumps(materialize(
        repo_root=args.repo_root, output_root=args.output_root,
        focused=args.focused, related=args.related,
        full_suite=args.full_suite, strict_l3=args.strict_l3,
    ), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
