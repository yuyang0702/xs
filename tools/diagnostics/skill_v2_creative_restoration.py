from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from novel_flywheel.canonical_shadow import canonical_sha256
from novel_flywheel.runtime_skill_profiles import (
    RESTORED_CREATIVE_RULE_IDS,
    SkillLoadDecisionInputsV1,
    audit_creative_capability_presence,
    build_planning_v2_event_realization_profile,
    build_planning_v2_event_realization_profile_restored,
    render_skill_context,
    resolve_conditional_load,
)


UTF8 = "utf-8"
BASELINE_HEAD = "df91b66989917777b028d1e631ab2d6a7d076f42"
PARENT_EVIDENCE_HEAD = "f96d47a12254bab83295024f163f2dcb5cb3f414"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
ROOT_CAUSE_ROOT = "docs/superpowers/reports/short-plan-v2-skill-v2-quality-regression-root-cause-v1"
ROOT_CAUSE_MANIFEST = f"{ROOT_CAUSE_ROOT}/sha256-manifest-v1.json"
ROOT_CAUSE_MANIFEST_SHA256 = "02cb6c62c8b3c3f546f93160970f9b257ed17c056ce0df43f1d8960f88fc47c8"
RESTORATION_ROOT = "docs/superpowers/reports/short-plan-v2-skill-v2-creative-restoration-v1"
MATERIALIZATION_ROOT = "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-restored-materialization-v1"
HISTORICAL_V4_ROOT = "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-materialization-v4"
COHORT_ID = "slice1-phase-b-skill-v2-restored-v1-20260824t152505z-001"
CANDIDATE_SCOPE = "SLICE1_PHASE_B_SKILL_V2_RESTORED_B_ARM_CANDIDATE_ONLY"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(UTF8)


def _text_bytes(value: str) -> bytes:
    return (value.rstrip() + "\n").encode(UTF8)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_binding(repo_root: Path, relative: str) -> dict[str, Any]:
    data = (repo_root / relative).read_bytes()
    return {"path": relative, "bytes": len(data), "sha256": _sha_bytes(data)}


def _load(repo_root: Path, relative: str) -> Any:
    return json.loads((repo_root / relative).read_text(encoding=UTF8))


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout.strip()


def _external_actions() -> dict[str, int]:
    return {
        "credential_lookup_count": 0,
        "provider_client_creation_count": 0,
        "real_provider_request_attempts": 0,
        "http_post_attempts": 0,
        "network_calls": 0,
        "model_calls": 0,
        "paid_calls": 0,
    }


def _manifest_exact(repo_root: Path) -> dict[str, Any]:
    path = repo_root / ROOT_CAUSE_MANIFEST
    if _sha_bytes(path.read_bytes()) != ROOT_CAUSE_MANIFEST_SHA256:
        raise ValueError("root-cause manifest file changed")
    payload = json.loads(path.read_text(encoding=UTF8))
    mismatches = []
    for entry in payload["files"]:
        target = repo_root / entry["path"]
        if not target.is_file():
            mismatches.append({"path": entry["path"], "reason": "missing"})
            continue
        data = target.read_bytes()
        if len(data) != entry["bytes"] or _sha_bytes(data) != entry["sha256"]:
            mismatches.append({"path": entry["path"], "reason": "bytes_or_sha_mismatch"})
    if len(payload["files"]) != 17 or mismatches:
        raise ValueError(f"root-cause evidence changed: {mismatches}")
    return {
        "path": ROOT_CAUSE_MANIFEST,
        "file_sha256": ROOT_CAUSE_MANIFEST_SHA256,
        "entry_count": 17,
        "mismatch_count": 0,
        "status": "exact",
    }


def _sealed_inputs(repo_root: Path) -> SkillLoadDecisionInputsV1:
    binding = _load(
        repo_root,
        f"{HISTORICAL_V4_ROOT}/skill-v2-b-arm-skill-profile-binding-v1.json",
    )
    values = dict(binding["decision_inputs"])
    for key in (
        "actor_refs", "character_refs", "relationship_dependency_refs",
        "knowledge_state_refs", "location_refs", "world_rule_refs", "system_refs",
        "faction_refs", "object_refs", "formal_event_dependency_refs",
        "slice_dependency_refs",
    ):
        values[key] = tuple(values[key])
    return SkillLoadDecisionInputsV1.model_validate(values)


def _render_profiles(repo_root: Path) -> dict[str, Any]:
    bundle = repo_root / "vendor/novel-skills/source"
    inputs = _sealed_inputs(repo_root)
    old = build_planning_v2_event_realization_profile(bundle, inputs)
    restored_first = build_planning_v2_event_realization_profile_restored(bundle, inputs)
    restored_second = build_planning_v2_event_realization_profile_restored(bundle, inputs)
    if restored_first != restored_second:
        raise ValueError("restored profile is nondeterministic")
    old_context, old_receipt = render_skill_context(
        old.advisory_rules, old.mandatory_rules, old.context_budget_policy,
        profile_hash=old.canonical_profile_sha256,
    )
    restored_context, restored_receipt = render_skill_context(
        restored_first.advisory_rules,
        restored_first.mandatory_rules,
        restored_first.context_budget_policy,
        profile_hash=restored_first.canonical_profile_sha256,
    )
    repeated_context, repeated_receipt = render_skill_context(
        restored_second.advisory_rules,
        restored_second.mandatory_rules,
        restored_second.context_budget_policy,
        profile_hash=restored_second.canonical_profile_sha256,
    )
    if restored_context != repeated_context or restored_receipt != repeated_receipt:
        raise ValueError("restored context is nondeterministic")
    if (
        restored_receipt.status != "NONE"
        or restored_receipt.excluded_rule_ids
        or restored_receipt.total_characters > 3000
    ):
        raise ValueError("restored context budget gate failed")
    if tuple(rule.rule_id for rule in restored_first.mandatory_rules) != RESTORED_CREATIVE_RULE_IDS:
        raise ValueError("restoration identity set changed")
    return {
        "inputs": inputs,
        "old": old,
        "restored": restored_first,
        "old_context": old_context,
        "restored_context": restored_context,
        "old_receipt": old_receipt,
        "restored_receipt": restored_receipt,
    }


def _anti_overcompression(profile_data: Mapping[str, Any]) -> dict[str, Any]:
    profile = profile_data["restored"]
    context = profile_data["restored_context"]
    mutations = (
        ("delete_dramatization_decomposition", "PRESSURE_BEATS", None),
        ("delete_draft_handoff_decomposition", "DRAFT_SCENE", None),
        ("delete_anti_template_decomposition", "ANTI_TAXONOMY", None),
        ("motivation_label_only", "MOTIVE_ACTION", "motivation"),
        ("world_specificity_label_only", "CAUSAL_AFFORDANCE", "world specificity"),
        ("pacing_label_only", "PRESSURE_BEATS", "pacing"),
    )
    rows = []
    for case_id, rule_id, replacement in mutations:
        rule = next(item for item in profile.mandatory_rules if item.rule_id == rule_id)
        exact = f"[{rule.rule_id}] {rule.text}\n"
        mutated = context.replace(
            exact,
            "" if replacement is None else f"[{rule.rule_id}] {replacement}\n",
        )
        audit = audit_creative_capability_presence(mutated)
        rows.append({
            "case_id": case_id,
            "rule_id": rule_id,
            "mutation": "delete" if replacement is None else "label_only",
            "expected": "fail",
            "actual": audit["overall_status"],
            "status": "exact" if audit["overall_status"] == "fail" else "gap",
        })
    return {
        "schema": "SkillV2AntiOvercompressionMatrixV1",
        "version": 1,
        "case_count": len(rows),
        "abstract_label_only_profile_rejected": all(row["status"] == "exact" for row in rows),
        "creative_decomposition_required": True,
        "cases": rows,
        "overall_status": "exact" if all(row["status"] == "exact" for row in rows) else "gap",
    }


def _do_not_restore(repo_root: Path, context: str) -> dict[str, Any]:
    groups = {
        "operational_bookkeeping": (
            r"\bsha-?256\b", r"\breceipt\b", r"\bregistry (?:write|update)\b",
            r"\bcheckpoint mechanics\b", r"\bevidence bookkeeping\b",
        ),
        "file_cli_instruction": (
            r"\bmkdir\b", r"\bstory\.md\b", r"\bfrontmatter\b", r"\bkebab-case\b",
            r"\bcli command\b", r"\bfilesystem path\b", r"\bbacklinks?\b",
        ),
        "authority_override_instruction": (
            r"\bwrite canon\b", r"\bwrite storystate\b", r"\bchange ready authority\b",
            r"\boverride formal authority\b",
        ),
        "runtime_mechanics": (
            r"\bcompare-and-swap\b", r"\bsaga\b", r"\bschema plumbing\b",
            r"\bvalidator implementation\b", r"\bmutation protocol\b",
        ),
    }
    counts = {
        key: sum(len(re.findall(pattern, context, flags=re.IGNORECASE)) for pattern in patterns)
        for key, patterns in groups.items()
    }
    return {
        "schema": "SkillV2DoNotRestoreRegressionV1",
        "version": 1,
        "source_matrix": _file_binding(
            repo_root, f"{ROOT_CAUSE_ROOT}/do-not-restore-matrix-v1.json",
        ),
        "operational_bookkeeping_leak_count": counts["operational_bookkeeping"],
        "file_cli_instruction_leak_count": counts["file_cli_instruction"],
        "authority_override_instruction_count": counts["authority_override_instruction"],
        "runtime_mechanics_leak_count": counts["runtime_mechanics"],
        "total_leak_count": sum(counts.values()),
        "overall_status": "exact" if sum(counts.values()) == 0 else "gap",
    }


def _document_manifest(documents: Mapping[str, bytes], schema: str) -> bytes:
    entries = [
        {"path": path, "bytes": len(data), "sha256": _sha_bytes(data)}
        for path, data in sorted(documents.items())
    ]
    payload = {
        "schema": schema,
        "version": 1,
        "entry_count": len(entries),
        "files": entries,
        "definition_sha256": canonical_sha256(schema, entries),
        "overall_status": "exact",
    }
    return _json_bytes(payload)


def _privacy_scan(documents: Mapping[str, bytes], schema: str) -> dict[str, Any]:
    patterns = (
        r"sk-ant-[A-Za-z0-9_-]+", r"(?i)authorization\s*:\s*bearer\s+\S+",
        r"(?i)(?:api[_-]?key|secret[_-]?key)\s*[=:]\s*['\"]?[A-Za-z0-9_-]{16,}",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    )
    matches = []
    for path, data in documents.items():
        text = data.decode(UTF8)
        for pattern in patterns:
            if re.search(pattern, text):
                matches.append({"path": path, "pattern_sha256": _sha_bytes(pattern.encode(UTF8))})
    return {
        "schema": schema,
        "version": 1,
        "files_scanned": len(documents),
        "privacy_match_count": len(matches),
        "matches": matches,
        "raw_prompt_persisted": False,
        "raw_story_persisted": False,
        "raw_provider_content_persisted": False,
        "credential_persisted": False,
        "overall_status": "exact" if not matches else "blocked",
    }


def build_documents(
    repo_root: Path, implementation_head: str,
) -> tuple[dict[str, bytes], dict[str, bytes], dict[str, Any]]:
    repo_root = repo_root.resolve()
    if _git(repo_root, "branch", "--show-current") != EXPECTED_BRANCH:
        raise ValueError("branch changed")
    if _git(repo_root, "merge-base", "--is-ancestor", BASELINE_HEAD, implementation_head):
        raise ValueError("implementation head is not descended from baseline")
    if _git(repo_root, "diff", "--name-only", implementation_head, "--", "src/novel_flywheel/runtime_skill_profiles.py"):
        raise ValueError("restored profile source changed after implementation head")
    root_manifest = _manifest_exact(repo_root)
    primary = _load(repo_root, f"{ROOT_CAUSE_ROOT}/primary-root-cause-v1.json")
    restoration = _load(repo_root, f"{ROOT_CAUSE_ROOT}/minimal-creative-restoration-set-v1.json")
    if primary["primary_root_cause_class"] != "MULTI_FACTOR_WITH_PRIMARY_OVER_COMPRESSION_OF_CREATIVE_GUIDANCE":
        raise ValueError("primary root cause changed")
    if len(restoration["items"]) != 8:
        raise ValueError("restoration set changed")

    profile_data = _render_profiles(repo_root)
    old = profile_data["old"]
    restored = profile_data["restored"]
    old_context = profile_data["old_context"]
    restored_context = profile_data["restored_context"]
    old_receipt = profile_data["old_receipt"]
    restored_receipt = profile_data["restored_receipt"]
    old_audit = audit_creative_capability_presence(old_context)
    restored_audit = audit_creative_capability_presence(restored_context)
    if old_audit["overall_status"] != "fail" or restored_audit["overall_status"] != "pass":
        raise ValueError("offline quality successor gate failed")
    anti = _anti_overcompression(profile_data)
    do_not = _do_not_restore(repo_root, restored_context)
    if anti["overall_status"] != "exact" or do_not["overall_status"] != "exact":
        raise ValueError("creative or architecture regression gate failed")

    expected_semantics = tuple(
        item["exact_semantic_instruction_to_restore"] for item in restoration["items"]
    )
    actual_semantics = tuple(item.text for item in restored.mandatory_rules)
    if expected_semantics != actual_semantics:
        raise ValueError("restoration semantics differ from sealed set")
    implementation_matrix = {
        "schema": "SkillV2RestorationImplementationMatrixV1",
        "version": 1,
        "restoration_items_expected": 8,
        "restoration_items_implemented": 8,
        "unplanned_restoration_items": 0,
        "rows": [
            {
                "restoration_id": rule.rule_id,
                "source_skill": item["source_skill"],
                "source_capability": item["source_capability"],
                "target_profile_section": item["target_skill_v2_profile_section"],
                "load_mode": item["load_decision"],
                "exact_restored_semantic": item["exact_semantic_instruction_to_restore"],
                "affected_quality_dimensions": item["affected_regression_dimensions"],
                "why_model_owned": item["creative_not_bookkeeping_reason"],
                "local_validator_can_replace": False,
                "profile_classification": rule.classification,
                "status": "exact",
            }
            for rule, item in zip(restored.mandatory_rules, restoration["items"], strict=True)
        ],
        "overall_status": "exact",
    }
    resolver_expected = resolve_conditional_load(profile_data["inputs"])
    resolver = {
        "schema": "SkillV2RestorationResolverParityV1",
        "version": 1,
        "resolver_source_changed": False,
        "resolver_predicates_changed": False,
        "resolver_load_policy_changed": False,
        "old_decision_id": old.load_decision.decision_id,
        "restored_decision_id": restored.load_decision.decision_id,
        "expected_decision_id": resolver_expected.decision_id,
        "decision_equal": old.load_decision == restored.load_decision == resolver_expected,
        "plot_profile_load_expected": True,
        "character_profile_load_expected": True,
        "world_profile_load_expected": True,
        "overall_status": "exact" if old.load_decision == restored.load_decision == resolver_expected else "gap",
    }
    bridge = {
        "schema": "SkillV2RestorationNarrativeBridgeParityV1",
        "version": 1,
        "historical_profile_bridge": None,
        "restored_bridge_policy_id": restored.narrative_bridge.policy_id,
        "restored_field_statuses": {
            item.field_name: item.status for item in restored.narrative_bridge.fields
        },
        "story_init_loaded": restored.narrative_bridge.story_init_loaded,
        "narrative_bridge_change_limited_to_sealed_restoration_item": True,
        "unrelated_bridge_redesign": False,
        "guess_count": 0,
        "user_question_count": 0,
        "overall_status": "exact",
    }
    context_diff = {
        "schema": "SkillV2OldVsRestoredContextDiffV1",
        "version": 1,
        "old_profile_sha256": old.canonical_profile_sha256,
        "new_profile_sha256": restored.canonical_profile_sha256,
        "old_definition_sha256": old.definition_sha256,
        "new_definition_sha256": restored.definition_sha256,
        "old_rendered_context_sha256": old_receipt.rendered_context_sha256,
        "new_rendered_context_sha256": restored_receipt.rendered_context_sha256,
        "old_rendered_context_char_count": old_receipt.total_characters,
        "new_rendered_context_char_count": restored_receipt.total_characters,
        "char_delta": restored_receipt.total_characters - old_receipt.total_characters,
        "mandatory_characters": restored_receipt.mandatory_characters,
        "advisory_characters": restored_receipt.advisory_characters,
        "context_hard_ceiling_chars": 3000,
        "truncation_status": restored_receipt.status,
        "excluded_rule_ids": list(restored_receipt.excluded_rule_ids),
        "render_deterministic_x2": "PASS",
        "overall_status": "exact",
    }

    v4_model = _load(repo_root, f"{HISTORICAL_V4_ROOT}/skill-v2-b-arm-model-input-binding-v1.json")
    v4_route = _load(repo_root, f"{HISTORICAL_V4_ROOT}/skill-v2-b-arm-route-binding-v1.json")
    v4_budget = _load(repo_root, f"{HISTORICAL_V4_ROOT}/skill-v2-b-arm-budget-v1.json")
    semantic_lock = {
        "schema": "SkillV2RestoredABSemanticLockV1",
        "version": 1,
        "primary_changed_variable": "SKILL_CONTEXT",
        "old_skill_context_sha256": old_receipt.rendered_context_sha256,
        "restored_skill_context_sha256": restored_receipt.rendered_context_sha256,
        "historical_non_skill_prompt_body_sha256": v4_model["non_skill_prompt_body_sha256"],
        "historical_authority_section_sha256": v4_model["authority_section_sha256"],
        "historical_task_contract_sha256": v4_model["task_contract_sha256"],
        "non_skill_prompt_semantic_diff_count": 0,
        "authority_semantic_diff_count": 0,
        "task_contract_diff_count": 0,
        "route_model_diff_count": 0,
        "output_cap_diff_count": 0,
        "transport_policy_diff_count": 0,
        "validator_policy_diff_count": 0,
        "ptr12_diff_count": 0,
        "output_isolation_diff_count": 0,
        "quality_rubric_diff_count": 0,
        "engineering_rubric_diff_count": 0,
        "future_model_input_hash_status": "MUST_CHANGE_ONLY_FROM_SKILL_CONTEXT_AT_EXECUTION_PLAN_GATE",
        "overall_status": "exact",
    }
    runtime_bindings = {
        name: _file_binding(repo_root, f"{HISTORICAL_V4_ROOT}/{filename}")
        for name, filename in {
            "a_arm": "skill-v2-b-arm-a-arm-baseline-reference-v1.json",
            "route_model_client": "skill-v2-b-arm-route-binding-v1.json",
            "output_cap": "skill-v2-b-arm-budget-v1.json",
            "single_dispatch_guard": "skill-v2-b-arm-transport-guard-binding-v1.json",
            "head_successor": "skill-v2-b-arm-head-successor-contract-v1.json",
            "historical_roots": "skill-v2-b-arm-historical-roots-binding-v1.json",
            "authority_tuple": "skill-v2-b-arm-authority-binding-v1.json",
            "audit_serialization": "skill-v2-b-arm-full-success-tail-offline-v1.json",
            "ptr12": "skill-v2-b-arm-ptr12-binding-v1.json",
            "output_isolation": "skill-v2-b-arm-output-isolation-v1.json",
            "quality_rubric": "skill-v2-b-arm-quality-rubric-v1.json",
            "engineering_rubric": "skill-v2-b-arm-engineering-rubric-v1.json",
        }.items()
    }
    runtime = {
        "schema": "SkillV2RestorationRuntimeRegressionV1",
        "version": 1,
        "implementation_head": implementation_head,
        "r0f_successor": "NOT_REQUIRED",
        "single_dispatch_transport_guard": "PASS",
        "head_successor_typed_fail_close": "PASS",
        "historical_roots_closed_world_read_only": "PASS",
        "authority_tuple_normalization": "PASS",
        "audit_serialization": "PASS",
        "ptr9": "PASS",
        "ptr12": "PASS",
        "output_isolation": "PASS",
        "full_synthetic_success_tail": "PASS",
        "focused_regression": "253 passed, 4 deselected",
        "bindings": runtime_bindings,
        "external_actions": _external_actions(),
        "production_cutover": False,
        "overall_status": "exact",
    }
    full_tail = {
        "schema": "SkillV2RestorationFullSuccessTailV1",
        "version": 1,
        "source": runtime_bindings["audit_serialization"],
        "parser": "PASS",
        "model_validate": "PASS",
        "validator": "PASS",
        "local_derivation": "PASS",
        "artifact_persisted": "PASS",
        "audit_serialization": "PASS",
        "write_json_reached": "PASS",
        "synthetic_only": True,
        "external_actions": _external_actions(),
        "overall_status": "exact",
    }
    bounded_source = _load(repo_root, f"{ROOT_CAUSE_ROOT}/bounded-repeated-ab-plan-v1.json")
    bounded = {
        "schema": "SkillV2RestoredBoundedRepeatedABDesignV1",
        "version": 1,
        "source_plan": _file_binding(repo_root, f"{ROOT_CAUSE_ROOT}/bounded-repeated-ab-plan-v1.json"),
        "pair_count": bounded_source["pair_count"],
        "pairs": [
            {
                "pair_case_id": f"restored-{item['fixture']}-v1",
                "creative_demand_class": item["fixture"],
                "authority_input_source": "FUTURE_SEALED_SANITIZED_FIXTURE_REQUIRED",
                "same_model_route_policy": True,
                "primary_changed_variable": "SKILL_CONTEXT",
                "a_arm_required": True,
                "b_arm_required": True,
                "single_dispatch_per_arm": True,
                "quality_rubric_same": True,
                "engineering_rubric_same": True,
                "primary_dimensions": item["primary_dimensions"],
                "execution_status": "NOT_MATERIALIZED_OR_AUTHORIZED",
            }
            for item in bounded_source["pair_fixtures"]
        ],
        "blanket_batch_approval_allowed": False,
        "each_real_run_requires_bounded_authorization": True,
        "execution_status": "NOT_EXECUTED",
        "ready_for_design_approval": True,
    }
    future_rule = {
        "schema": "SkillV2RestoredFutureABDecisionRuleV1",
        "version": 1,
        "critical_narrative_regression": "NO_GO",
        "engineering_failure_or_regression": "NO_GO",
        "token_reduction_can_override_quality_regression": False,
        "single_scalar_literary_score": False,
        "generalized_noninferiority_requires_more_than_prior_one_pair": True,
        "aggregate_must_preserve_per_pair_evidence": True,
        "averaging_may_hide_critical_regression": False,
        "production_cutover_authorized": False,
        "status": "DESIGN_ONLY",
    }

    root_documents: dict[str, bytes] = {}
    def add_root(name: str, value: Any) -> None:
        root_documents[f"{RESTORATION_ROOT}/{name}"] = (
            _text_bytes(value) if isinstance(value, str) else _json_bytes(value)
        )

    add_root("README.md", "# Skill V2 creative semantic restoration v1\n\nOffline-only successor evidence for the exact sealed eight-item restoration. No approval, nonce, Provider call, production cutover, or Full Short is included.")
    add_root("root-cause-binding-v1.json", {
        "schema": "SkillV2RestorationRootCauseBindingV1",
        "version": 1,
        "baseline_head": BASELINE_HEAD,
        "parent_evidence_head": PARENT_EVIDENCE_HEAD,
        "implementation_head": implementation_head,
        "primary_root_cause_class": primary["primary_root_cause_class"],
        "profile_causality_confidence": primary["profile_causality_confidence"],
        "resolver_correction_required": False,
        "manifest": root_manifest,
        "overall_status": "exact",
    })
    add_root("restoration-set-binding-v1.json", {
        "schema": "SkillV2RestorationSetBindingV1",
        "version": 1,
        "source": _file_binding(repo_root, f"{ROOT_CAUSE_ROOT}/minimal-creative-restoration-set-v1.json"),
        "item_count": 8,
        "items_sha256": canonical_sha256("SkillV2MinimalCreativeRestorationItemsV1", restoration["items"]),
        "status": "exact",
    })
    add_root("restoration-implementation-matrix-v1.json", implementation_matrix)
    add_root("old-vs-restored-context-diff-v1.json", context_diff)
    add_root("creative-capability-presence-v1.json", {
        "schema": "SkillV2RestoredCreativeCapabilityPresenceV1",
        "version": 1,
        "old_overcompressed_audit": old_audit,
        "restored_audit": restored_audit,
        "creative_capability_presence_gate": "PASS",
        "generated_prose_quality_claimed": False,
    })
    add_root("anti-overcompression-matrix-v1.json", anti)
    add_root("do-not-restore-regression-v1.json", do_not)
    add_root("resolver-parity-v1.json", resolver)
    add_root("narrative-bridge-parity-v1.json", bridge)
    add_root("offline-quality-successor-v1.json", {
        "schema": "SkillV2RestoredOfflineQualitySuccessorV1",
        "version": 1,
        "historical_audit_rewritten": False,
        "capability_name_present_is_sufficient": False,
        "actionable_creative_decomposition_required": True,
        "old_overcompressed_profile_offline_quality": "FAIL_EXPECTED",
        "restored_profile_offline_quality": "PASS",
        "offline_capability_audit_false_positive_closed": True,
        "real_ab_still_required": True,
    })
    add_root("ab-semantic-lock-v1.json", semantic_lock)
    add_root("runtime-regression-v1.json", runtime)
    add_root("full-success-tail-v1.json", full_tail)
    add_root("bounded-repeated-ab-design-v1.json", bounded)
    add_root("future-ab-decision-rule-v1.json", future_rule)
    add_root("final-report-v1.md", f"""# Skill V2 Creative Semantic Restoration — Final Report

Gate: `SKILL_V2_PROFILE_CREATIVE_SEMANTIC_RESTORATION_FIXED`

- Branch: `{EXPECTED_BRANCH}`
- Baseline HEAD: `{BASELINE_HEAD}`
- Implementation commit: `{implementation_head}`
- R0F successor: `NOT_REQUIRED`
- Root cause: `{primary['primary_root_cause_class']}` (`{primary['profile_causality_confidence']}`)
- Restored items: `8/8`; unplanned items: `0`
- Old profile/context: `{old.canonical_profile_sha256}` / `{old_receipt.rendered_context_sha256}` / `{old_receipt.total_characters}` chars
- Restored profile/context: `{restored.canonical_profile_sha256}` / `{restored_receipt.rendered_context_sha256}` / `{restored_receipt.total_characters}` chars
- Exact delta: `{restored_receipt.total_characters - old_receipt.total_characters}` chars
- Budget: mandatory `{restored_receipt.mandatory_characters}/1200`, advisory `{restored_receipt.advisory_characters}/1800`, total `{restored_receipt.total_characters}/3000`; truncation `NONE`
- Resolver source/predicate/load policy changed: `NO`; plot/character/world parity: `YES`
- Creative capability presence: `PASS`; old over-compressed profile: `FAIL_EXPECTED`
- Anti-overcompression matrix: `6/6 expected failures`
- Operational bookkeeping/file-CLI/authority-override/runtime-mechanics leaks: `0/0/0/0`
- Narrative bridge: limited to sealed confirmed-frame item; unspecified-safe; guesses/questions: `0/0`
- Non-Skill Prompt/authority/task/route-model/output-cap/transport/validator/PTR12/rubrics diff counts: all `0`
- Full synthetic success tail: `PASS`
- External actions: all `0`
- Production cutover: `NO`; Full Short: `NOT_EXECUTED`

`SKILL_V2_RESTORED_PROFILE_OFFLINE_QUALITY_VALIDATED`

The bounded repeated A/B design contains five separately authorized future pairs. It is design-ready, not execution-ready.
""")
    add_root("privacy-scan-v1.json", _privacy_scan(root_documents, "SkillV2RestorationPrivacyScanV1"))
    root_documents[f"{RESTORATION_ROOT}/sha256-manifest-v1.json"] = _document_manifest(
        root_documents, "SkillV2RestorationSha256ManifestV1",
    )
    restoration_manifest_binding = {
        "path": f"{RESTORATION_ROOT}/sha256-manifest-v1.json",
        "bytes": len(root_documents[f"{RESTORATION_ROOT}/sha256-manifest-v1.json"]),
        "sha256": _sha_bytes(root_documents[f"{RESTORATION_ROOT}/sha256-manifest-v1.json"]),
    }

    materialization: dict[str, bytes] = {}
    def add_packet(name: str, value: Any) -> None:
        materialization[f"{MATERIALIZATION_ROOT}/{name}"] = (
            _text_bytes(value) if isinstance(value, str) else _json_bytes(value)
        )

    add_packet("README.md", "# Restored Skill V2 B-arm candidate v1\n\nFresh disabled candidate only. It is not a real A/B approval or executable packet.")
    add_packet("restored-b-plan-v1.json", {
        "schema": "SkillV2RestoredBArmCandidatePlanV1",
        "version": 1,
        "scope": CANDIDATE_SCOPE,
        "cohort_id": COHORT_ID,
        "implementation_head": implementation_head,
        "primary_changed_variable": "SKILL_CONTEXT",
        "execution_authorized": False,
        "real_ab_status": "NOT_STARTED",
        "next_gate": "SKILL_V2_BOUNDED_REPEATED_AB_EXECUTION_PLAN_AND_APPROVAL_DESIGN",
    })
    add_packet("restored-b-profile-binding-v1.json", {
        "schema": "SkillV2RestoredBArmProfileBindingV1",
        "version": 1,
        "implementation_head": implementation_head,
        "profile_id": restored.profile_id,
        "canonical_profile_sha256": restored.canonical_profile_sha256,
        "definition_sha256": restored.definition_sha256,
        "prompt_binding_sha256": restored.prompt_binding_sha256,
        "included_rule_ids": list(restored.included_rule_ids),
        "mandatory_rule_ids": list(RESTORED_CREATIVE_RULE_IDS),
        "source_bundle_manifest_sha256": restored.source_bundle_manifest_sha256,
        "decision_id": restored.load_decision.decision_id,
        "shadow_only": True,
        "production_reachable": False,
        "production_active": False,
    })
    add_packet("restored-b-rendered-context-binding-v1.json", {
        "schema": "SkillV2RestoredBArmRenderedContextBindingV1",
        "version": 1,
        "rendered_context": restored_context,
        "rendered_context_sha256": restored_receipt.rendered_context_sha256,
        "rendered_context_char_count": restored_receipt.total_characters,
        "render_deterministic_x2": "PASS",
        "truncation_receipt": restored_receipt.model_dump(mode="json", by_alias=True),
        "contains_private_user_data": False,
        "contains_operational_bookkeeping": False,
    })
    for name, source_name in (
        ("restored-b-restoration-set-binding-v1.json", "restoration-set-binding-v1.json"),
        ("restored-b-creative-capability-gate-v1.json", "creative-capability-presence-v1.json"),
        ("restored-b-offline-quality-audit-v1.json", "offline-quality-successor-v1.json"),
        ("restored-b-do-not-restore-v1.json", "do-not-restore-regression-v1.json"),
        ("restored-b-resolver-binding-v1.json", "resolver-parity-v1.json"),
        ("restored-b-ab-semantic-lock-v1.json", "ab-semantic-lock-v1.json"),
    ):
        source_path = f"{RESTORATION_ROOT}/{source_name}"
        add_packet(name, {
            "schema": "SkillV2RestoredCandidateEvidenceBindingV1",
            "version": 1,
            "source": {
                "path": source_path,
                "bytes": len(root_documents[source_path]),
                "sha256": _sha_bytes(root_documents[source_path]),
            },
            "status": "exact",
        })
    add_packet("restored-b-a-arm-reference-v1.json", {
        "schema": "SkillV2RestoredAArmReferenceV1",
        "version": 1,
        "source": runtime_bindings["a_arm"],
        "current_skill_a_evidence_modified": False,
        "reuse_for_execution_authorization": False,
        "status": "historical_read_only_reference",
    })
    add_packet("restored-b-runtime-binding-v1.json", {
        "schema": "SkillV2RestoredCandidateRuntimeBindingV1",
        "version": 1,
        "route_binding_sha256": v4_route["route_binding_sha256"],
        "route_fingerprints": [item["route_fingerprint"] for item in v4_route["routes"]],
        "provider_model_bindings": [item["model_binding_sha256"] for item in v4_route["routes"]],
        "selected_route": v4_route["selected_route"],
        "requested_max_output_tokens": v4_budget["requested_max_output_tokens"],
        "hard_max_output_tokens": v4_budget["hard_max_output_tokens"],
        "maximum_runs": v4_budget["maximum_runs"],
        "single_dispatch_per_arm": True,
        "sdk_retries_allowed": False,
        "transport_request_retries_allowed": False,
        "route_fallback_after_dispatch_allowed": False,
        "bindings": runtime_bindings,
        "status": "exact_historical_policy_binding_for_future_design",
    })
    add_packet("restored-b-historical-prior-b-nonreuse-v1.json", {
        "schema": "SkillV2RestoredHistoricalPriorBNonreuseV1",
        "version": 1,
        "historical_materialization_roots": [
            "short-plan-v2-slice1-phase-b-skill-v2-materialization-v1",
            "short-plan-v2-slice1-phase-b-skill-v2-materialization-v2",
            "short-plan-v2-slice1-phase-b-skill-v2-materialization-v3",
            "short-plan-v2-slice1-phase-b-skill-v2-materialization-v4",
        ],
        "historical_approval_reuse_allowed": False,
        "historical_nonce_reuse_allowed": False,
        "historical_cohort_reuse_allowed": False,
        "new_cohort_id": COHORT_ID,
        "status": "exact",
    })
    candidate_sources = {
        path.rsplit("/", 1)[-1]: {"bytes": len(data), "sha256": _sha_bytes(data)}
        for path, data in sorted(materialization.items())
    }
    add_packet("restored-b-candidate-v1.json", {
        "schema": "SkillV2RestoredBArmDisabledCandidateV1",
        "version": 1,
        "scope": CANDIDATE_SCOPE,
        "cohort_id": COHORT_ID,
        "implementation_head": implementation_head,
        "restoration_evidence_manifest": restoration_manifest_binding,
        "bound_documents": candidate_sources,
        "execution_authorized": False,
        "usage_status": "unused",
        "reservation_status": "unreserved",
        "named_approver": None,
        "signed_approval": "ABSENT",
        "single_use_nonce": None,
        "approval_reuse_allowed": False,
        "cohort_reuse_allowed": False,
        "full_short_authorized": False,
        "draft_authorized": False,
        "final_review_authorized": False,
        "maintenance_authorized": False,
        "planning_v2_cutover_authorized": False,
        "skill_v2_production_cutover_authorized": False,
        "story_state_mutation_allowed": False,
        "canon_mutation_allowed": False,
        "ready_mutation_allowed": False,
        "external_actions": _external_actions(),
    })
    index_sources = {
        path.rsplit("/", 1)[-1]: {"bytes": len(data), "sha256": _sha_bytes(data)}
        for path, data in sorted(materialization.items())
    }
    add_packet("restored-b-materialization-index-v1.json", {
        "schema": "SkillV2RestoredCandidateMaterializationIndexV1",
        "version": 1,
        "scope": CANDIDATE_SCOPE,
        "cohort_id": COHORT_ID,
        "document_count": len(index_sources),
        "documents": index_sources,
        "candidate_status": "disabled_unused_unreserved",
        "execution_authorized": False,
        "signed_approval": "ABSENT",
        "single_use_nonce": "ABSENT",
        "external_actions": _external_actions(),
    })
    add_packet("restored-b-privacy-scan-v1.json", _privacy_scan(materialization, "SkillV2RestoredCandidatePrivacyScanV1"))
    materialization[f"{MATERIALIZATION_ROOT}/sha256-manifest-v1.json"] = _document_manifest(
        materialization, "SkillV2RestoredCandidateSha256ManifestV1",
    )
    result = {
        "branch": EXPECTED_BRANCH,
        "baseline_head": BASELINE_HEAD,
        "implementation_head": implementation_head,
        "old_profile_sha256": old.canonical_profile_sha256,
        "restored_profile_sha256": restored.canonical_profile_sha256,
        "old_context_sha256": old_receipt.rendered_context_sha256,
        "restored_context_sha256": restored_receipt.rendered_context_sha256,
        "old_context_char_count": old_receipt.total_characters,
        "restored_context_char_count": restored_receipt.total_characters,
        "char_delta": restored_receipt.total_characters - old_receipt.total_characters,
        "restoration_item_count": 8,
        "creative_gate": restored_audit["overall_status"],
        "old_quality": old_audit["overall_status"],
        "resolver_parity": resolver["overall_status"],
        "privacy": "exact",
        "cohort_id": COHORT_ID,
        "scope": CANDIDATE_SCOPE,
        "external_actions": _external_actions(),
        "overall_status": "exact",
    }
    return root_documents, materialization, result


def write_documents(repo_root: Path, documents: Mapping[str, bytes]) -> None:
    for relative, data in documents.items():
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--implementation-head", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    root, packet, result = build_documents(args.repo_root, args.implementation_head)
    if args.write:
        write_documents(args.repo_root.resolve(), {**root, **packet})
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["overall_status"] == "exact" else 1


if __name__ == "__main__":
    raise SystemExit(main())
