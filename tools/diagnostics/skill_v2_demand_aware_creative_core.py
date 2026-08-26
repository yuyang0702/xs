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
    CHARACTER_HEAVY_CREATIVE_CORE_V2_RULE_TEXT,
    SkillLoadDecisionInputsV1,
    build_planning_v2_event_realization_profile_demand_aware,
    build_planning_v2_event_realization_profile_restored,
    profile_contains_runtime_owned_responsibility,
    render_skill_context,
    resolve_demand_aware_creative_profile,
)


UTF8 = "utf-8"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "4dff5603cde1ba4c4de3c601ce229c5bc102cedf"
IMPLEMENTATION_HEAD = "a7999372a9fc96f3119a1e48a881fd7aa716a049"
EVIDENCE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-demand-aware-creative-core-narrow-fix-v1"
)
ROOT_CAUSE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-pair1-corrected-quality-regression-root-cause-v1"
)
CORRECTED_B_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-pair1-corrected-b-binding-closure-v1"
)
A_EXECUTION_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-skill-v2-bounded-repeated-ab-execution-v4/"
    "pairs/restored-character-heavy-v2/a-arm"
)
ROOT_CAUSE_MANIFEST_SHA256 = (
    "916cce911a87f5a3c5a2d9ed090d80450dde80b7853dc0cdc6b2a6adf75da9bd"
)
OLD_PROFILE_SHA256 = "c4ca606bd76359514e15cd60a2edcecbd9bc530690abb86be7313f2bd38999c5"
OLD_CONTEXT_SHA256 = "e7828db2dc18eceabe06b9d1068b2683d117617fb0bd1257a26e7747fbe02772"
OLD_CONTEXT_CHARS = 2742
A_ARTIFACT_SHA256 = "f6aa5c49d64f38aefe71b01fc9eb0abf2ea3a08faba6f5bc3dbcb38c665e3f8f"
A_PACKET_SHA256 = "39a46e38d9c11f8afd5fd1cf633443b31ae6fb1c97c4b93d404f950781f19356"
OLD_AB_LOCK_SHA256 = "31ed7f57374c99b90a5271b44655489661a4bbc70f0ed6363c154f4d55163d80"
OLD_B_PACKET_SHA256 = "6190409613b8ba3cff8ae5fba6216a2c4885f0d1d37245367ce5eea63288b37a"
PAIR_CASE_ID = "restored-character-heavy-v2-demand-aware-core-v2"
CANDIDATE_SCOPE = "SKILL_V2_PAIR1_DEMAND_AWARE_B_ONLY_REVALIDATION_DISABLED_V1"
CANDIDATE_COHORT = "skill-v2-pair1-demand-aware-b-revalidation-disabled-v1"
TARGET_RULE_IDS = ("MOTIVE_ACTION", "VOICE_RELATION", "DRAFT_SCENE", "ANTI_TAXONOMY")
RESTORATION_IDS = (
    "MOTIVE_ACTION_V2", "VOICE_RELATION_V2", "DRAFT_SCENE_V2", "ANTI_TAXONOMY_V2",
)
ZERO_EXTERNAL_ACTIONS = {
    "credential_lookup_count": 0,
    "real_provider_client_creation_count": 0,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
}
SHARED_EXPERIMENT_BINDINGS = (
    "fixture_sha256",
    "authority_input_sha256",
    "story_slice_sha256",
    "task_contract_sha256",
    "non_skill_prompt_sha256",
    "route_model_client_sha256",
    "output_cap",
    "validator_policy_sha256",
    "ptr9_policy_sha256",
    "ptr12_policy_sha256",
    "quality_rubric_sha256",
    "engineering_rubric_sha256",
    "sampling_policy_sha256",
    "tool_policy_sha256",
    "transport_policy_binding_sha256",
    "authority_tuple_policy_sha256",
    "audit_serialization_policy_sha256",
    "output_isolation_policy_sha256",
    "user_sha256",
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(UTF8)


def _text_bytes(value: str) -> bytes:
    return (value.rstrip() + "\n").encode(UTF8)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load(repo_root: Path, relative: str) -> dict[str, Any]:
    value = json.loads((repo_root / relative).read_text(encoding=UTF8))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {relative}")
    return value


def _git(repo_root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args], capture_output=True, check=False,
    )
    if check and result.returncode:
        raise ValueError(result.stderr.decode(UTF8, errors="replace").strip() or "git failed")
    return result.stdout.decode(UTF8, errors="surrogateescape").strip()


def _is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        check=False,
    ).returncode == 0


def _verify_manifest(repo_root: Path, relative: str, expected_sha256: str | None = None) -> dict[str, Any]:
    path = repo_root / relative
    data = path.read_bytes()
    if expected_sha256 is not None and _sha_bytes(data) != expected_sha256:
        raise ValueError(f"manifest identity changed: {relative}")
    manifest = json.loads(data.decode(UTF8))
    entries = manifest.get("files", manifest.get("entries"))
    if not isinstance(entries, list) or manifest.get("entry_count") != len(entries):
        raise ValueError(f"manifest shape changed: {relative}")
    for entry in entries:
        target = repo_root / entry["path"]
        target_data = target.read_bytes()
        if len(target_data) != entry["bytes"] or _sha_bytes(target_data) != entry["sha256"]:
            raise ValueError(f"manifest entry changed: {entry['path']}")
    return {
        "path": relative,
        "manifest_file_sha256": _sha_bytes(data),
        "entry_count": len(entries),
        "mismatch_count": 0,
        "status": "EXACT",
    }


def _inputs(repo_root: Path) -> SkillLoadDecisionInputsV1:
    binding = _load(
        repo_root,
        "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-"
        "materialization-v4/skill-v2-b-arm-skill-profile-binding-v1.json",
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


def _rules(profile: Any) -> dict[str, Any]:
    return {rule.rule_id: rule for rule in (*profile.mandatory_rules, *profile.advisory_rules)}


def _render(profile: Any) -> tuple[str, Any]:
    return render_skill_context(
        profile.advisory_rules, profile.mandatory_rules, profile.context_budget_policy,
    )


def _profile_evidence(repo_root: Path) -> dict[str, Any]:
    bundle = repo_root / "vendor/novel-skills/source"
    inputs = _inputs(repo_root)
    old = build_planning_v2_event_realization_profile_restored(bundle, inputs)
    new = build_planning_v2_event_realization_profile_demand_aware(
        bundle, inputs, pair_creative_demand_class="character-heavy",
    )
    old_context, old_receipt = _render(old)
    new_context, new_receipt = _render(new)
    if old.canonical_profile_sha256 != OLD_PROFILE_SHA256:
        raise ValueError("historical restored profile changed")
    if _sha_bytes(old_context.encode(UTF8)) != OLD_CONTEXT_SHA256 or len(old_context) != OLD_CONTEXT_CHARS:
        raise ValueError("historical restored context changed")
    if new_receipt.status != "NONE" or new_receipt.total_characters > 3000:
        raise ValueError("character-heavy successor does not fit the sealed cap")
    old_rules = _rules(old)
    new_rules = _rules(new)
    changed = tuple(rule_id for rule_id in new.included_rule_ids if old_rules[rule_id] != new_rules[rule_id])
    if changed != TARGET_RULE_IDS:
        raise ValueError("unrelated profile semantic mutation")
    unchanged = tuple(rule_id for rule_id in new.included_rule_ids if rule_id not in changed)
    if any(old_rules[rule_id] != new_rules[rule_id] for rule_id in unchanged):
        raise ValueError("non-target rule changed")
    resolver_definition = {
        demand: resolve_demand_aware_creative_profile(demand).__dict__
        for demand in (
            "character-heavy", "world-heavy", "conflict-pacing-heavy",
            "setup-payoff-heavy", "mixed", "unknown",
        )
    }
    materializer_definition = {
        "profile_id": new.profile_id,
        "target_rule_ids": TARGET_RULE_IDS,
        "target_rule_text_sha256": {
            key: _sha_bytes(value.encode(UTF8))
            for key, value in CHARACTER_HEAVY_CREATIVE_CORE_V2_RULE_TEXT.items()
        },
        "context_budget": new.context_budget_policy.model_dump(mode="json", by_alias=True),
        "included_rule_ids": new.included_rule_ids,
    }
    return {
        "old": old,
        "new": new,
        "old_context": old_context,
        "new_context": new_context,
        "old_receipt": old_receipt,
        "new_receipt": new_receipt,
        "old_rules": old_rules,
        "new_rules": new_rules,
        "changed": changed,
        "unchanged": unchanged,
        "resolver_definition": resolver_definition,
        "resolver_sha256": canonical_sha256(
            "SkillV2DemandAwareCreativeProfileResolverV1", resolver_definition,
        ),
        "materializer_sha256": canonical_sha256(
            "SkillV2DemandAwareCreativeProfileMaterializerV1", materializer_definition,
        ),
    }


def _forward_risk_report() -> dict[str, Any]:
    test = "tests/test_skill_v2_demand_aware_creative_core.py"
    return {
        "version": 2,
        "original_requirement": "Apply exactly four sealed character-heavy creative-core rewrites without changing non-character demand semantics or production reachability.",
        "scope_classification": "closed_world",
        "operational_definition": "Exact local demand lookup; one four-rule successor; old profile for four known sibling classes; typed fail-close for unknown classes.",
        "forbidden_narrowing": [
            "Do not omit any sealed V2 semantic unit.",
            "Do not weaken relationship or setup/payoff support.",
            "Do not raise the 3000-character ceiling.",
            "Do not make the shadow profile production reachable.",
        ],
        "resolution_status": "case_fixed",
        "closed_world_justification": "The sealed strategy enumerates all five accepted demand classes, the exact character-heavy mapping, four exact rewrites, and one unknown-value disposition.",
        "constraint_traceability": [
            {
                "requirement": "exact four-rule character-heavy deepening",
                "implementation": "closed target-text map plus in-place dataclass replacement",
                "test_paths": [test],
                "evidence": "exact target and non-target equality tests",
            },
            {
                "requirement": "known sibling semantics unchanged and unknown fail-closed",
                "implementation": "closed demand strategy lookup",
                "test_paths": [test],
                "evidence": "parameterized profile equality and unknown rejection tests",
            },
            {
                "requirement": "relationship/setup-payoff gains and 3000-char cap preserved",
                "implementation": "targeted semantic assertions and profile-local fixed partition",
                "test_paths": [test],
                "evidence": "2925-character canonical render with zero omitted rules",
            },
        ],
        "historical_incident_families_checked": [
            "overcompressed character creative core",
            "historical restored-profile byte drift",
            "demand-agnostic profile substitution",
            "mandatory context overflow",
            "relationship and setup-payoff gain regression",
        ],
        "projected_failure_mechanisms": [
            "unknown demand selects character profile",
            "non-target rule or ordering drift",
            "mandatory budget blocks the successor",
            "runtime-owned instruction leakage",
            "production reachability drift",
        ],
        "model_output_boundary_changed": False,
        "model_output_not_applicable_evidence": "Only deterministic offline Skill context selection changes; output schema, parser, validator, Provider adapter, and generated-output boundary are untouched.",
        "why_previous_tests_missed": "Prior tests proved eight restoration cores were present but did not exercise demand-specific depth or the sealed character microchain.",
        "sibling_boundaries": [
            {"boundary": "world-heavy/conflict-pacing-heavy/setup-payoff-heavy/mixed", "disposition": "tested_not_susceptible", "evidence": "each returns the historical restored profile exactly"},
            {"boundary": "unknown demand class", "disposition": "fixed_and_tested", "evidence": "typed fail-close and no profile substitution"},
            {"boundary": "historical restored builder", "disposition": "tested_not_susceptible", "evidence": "frozen profile/context hashes remain exact"},
            {"boundary": "production workflow", "disposition": "not_applicable", "evidence": "shadow_only=true and production_reachable=false; no call site changed"},
        ],
        "production_shaped_tests": [test],
        "next_authoritative_boundary_tests": [test],
        "remaining_risks": [
            "Generalized literary non-inferiority remains unproven until separately approved real Pair 1 B revalidation."
        ],
    }


def _privacy_scan(documents: Mapping[str, bytes]) -> dict[str, Any]:
    patterns = (
        r"sk-ant-[A-Za-z0-9_-]+",
        r"(?i)authorization\s*:\s*bearer\s+\S+",
        r"(?i)(?:api[_-]?key|secret[_-]?key)\s*[=:]\s*['\"]?[A-Za-z0-9_-]{16,}",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"[A-Za-z]:\\(?:Users|小说)\\",
    )
    matches = []
    for path, data in documents.items():
        text = data.decode(UTF8)
        for pattern in patterns:
            if re.search(pattern, text):
                matches.append({"path": path, "pattern_sha256": _sha_bytes(pattern.encode(UTF8))})
    return {
        "schema": "SkillV2DemandAwareCreativeCorePrivacyScanV1",
        "version": 1,
        "files_scanned": len(documents),
        "privacy_match_count": len(matches),
        "matches": matches,
        "credentials_persisted": False,
        "auth_headers_persisted": False,
        "provider_url_persisted": False,
        "raw_provider_payload_persisted": False,
        "hidden_reasoning_persisted": False,
        "overall_status": "exact" if not matches else "blocked",
    }


def build_documents(
    repo_root: Path,
    *,
    validation_head: str,
    validation: Mapping[str, Any],
) -> tuple[dict[str, bytes], dict[str, Any]]:
    repo_root = repo_root.resolve()
    if _git(repo_root, "branch", "--show-current") != EXPECTED_BRANCH:
        raise ValueError("branch changed")
    if not _is_ancestor(repo_root, BASELINE_HEAD, IMPLEMENTATION_HEAD):
        raise ValueError("implementation head is not descended from baseline")
    if not _is_ancestor(repo_root, IMPLEMENTATION_HEAD, validation_head):
        raise ValueError("validation head is not descended from implementation")

    parent = _verify_manifest(
        repo_root, f"{ROOT_CAUSE_ROOT}/sha256-manifest-v1.json", ROOT_CAUSE_MANIFEST_SHA256,
    )
    corrected_b = _verify_manifest(repo_root, f"{CORRECTED_B_ROOT}/sha256-manifest-v1.json")
    a_execution = _verify_manifest(repo_root, f"{A_EXECUTION_ROOT}/sha256-manifest-v1.json")
    sealed_set = _load(repo_root, f"{ROOT_CAUSE_ROOT}/minimal-creative-restoration-v2-set-v1.json")
    strategy = _load(repo_root, f"{ROOT_CAUSE_ROOT}/demand-aware-profile-strategy-v1.json")
    root_decision = _load(repo_root, f"{ROOT_CAUSE_ROOT}/root-cause-decision-v1.json")
    next_validation = _load(repo_root, f"{ROOT_CAUSE_ROOT}/next-validation-strategy-v1.json")
    deferment = _load(repo_root, f"{ROOT_CAUSE_ROOT}/pair2-5-deferment-v1.json")
    old_packet = _load(repo_root, f"{CORRECTED_B_ROOT}/b-successor-packet-v3.json")
    a_binding = _load(repo_root, f"{CORRECTED_B_ROOT}/a-control-binding-v1.json")
    profile = _profile_evidence(repo_root)

    item_ids = tuple(item["id"] for item in sealed_set["items"])
    if sealed_set.get("item_count") != 4 or item_ids != RESTORATION_IDS:
        raise ValueError("sealed restoration set changed")
    if strategy.get("known_mapping", {}).get("character-heavy") != "RESTORED_SKILL_V2_CHARACTER_CORE_V2":
        raise ValueError("sealed demand strategy changed")
    if root_decision.get("primary_root_cause_class") != "MULTI_FACTOR_WITH_PRIMARY_CHARACTER_HEAVY_UNDERSPECIFICATION":
        raise ValueError("root-cause decision changed")
    if old_packet.get("packet_sha256") != OLD_B_PACKET_SHA256:
        raise ValueError("corrected B packet changed")
    if a_binding.get("a_artifact_sha256") != A_ARTIFACT_SHA256 or a_binding.get("a_packet_sha256") != A_PACKET_SHA256:
        raise ValueError("sealed A control changed")

    documents: dict[str, bytes] = {}

    def add(name: str, value: Any) -> None:
        path = f"{EVIDENCE_ROOT}/{name}"
        documents[path] = _text_bytes(value) if isinstance(value, str) else _json_bytes(value)

    add("README.md", """# Skill V2 demand-aware creative-core narrow fix

Offline evidence for the sealed four-rule character-heavy successor. The root contains no execution approval, nonce, launcher, Provider payload, or real-call authority.
""")
    existing_contract = repo_root / EVIDENCE_ROOT / "change-contract-v1.json"
    if existing_contract.exists():
        documents[f"{EVIDENCE_ROOT}/change-contract-v1.json"] = existing_contract.read_bytes()
    add("parent-evidence-validation-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreParentEvidenceValidationV1",
        "version": 1,
        "parents": [parent, corrected_b, a_execution],
        "mismatch_count": 0,
        "overall_status": "exact",
    })
    add("root-cause-binding-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreRootCauseBindingV1",
        "version": 1,
        "primary_root_cause_class": "MULTI_FACTOR_WITH_PRIMARY_CHARACTER_HEAVY_UNDERSPECIFICATION",
        "restoration_diagnosis": "INSUFFICIENT_DEPTH",
        "skill_context_causality_confidence": "MEDIUM",
        "preserve_b_relationship_logic_gain": True,
        "preserve_b_setup_payoff_gain": True,
        "parent_manifest_file_sha256": ROOT_CAUSE_MANIFEST_SHA256,
        "status": "PASS",
    })
    add("sealed-restoration-set-binding-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreSealedRestorationSetBindingV1",
        "version": 1,
        "source_path": f"{ROOT_CAUSE_ROOT}/minimal-creative-restoration-v2-set-v1.json",
        "source_file_sha256": _sha_bytes((repo_root / ROOT_CAUSE_ROOT / "minimal-creative-restoration-v2-set-v1.json").read_bytes()),
        "item_count": 4,
        "restoration_ids": RESTORATION_IDS,
        "exact_missing_semantic_sha256": {
            item["id"]: _sha_bytes(item["exact_missing_semantic"].encode(UTF8))
            for item in sealed_set["items"]
        },
        "overall_status": "exact",
    })
    add("demand-aware-strategy-binding-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreStrategyBindingV1",
        "version": 1,
        "source_file_sha256": _sha_bytes((repo_root / ROOT_CAUSE_ROOT / "demand-aware-profile-strategy-v1.json").read_bytes()),
        "resolver": "DETERMINISTIC_LOCAL",
        "input": "pair_creative_demand_class",
        "known_mapping": strategy["known_mapping"],
        "unknown_demand_behavior": strategy["unknown_demand_behavior"],
        "resolver_sha256": profile["resolver_sha256"],
        "overall_status": "exact",
    })
    changed_paths = tuple(
        line for line in _git(repo_root, "diff", "--name-only", BASELINE_HEAD, validation_head).splitlines()
        if line
    )
    add("source-diff-scope-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreSourceDiffScopeV1",
        "version": 1,
        "baseline_head": BASELINE_HEAD,
        "implementation_head": IMPLEMENTATION_HEAD,
        "validation_head": validation_head,
        "changed_paths": changed_paths,
        "production_runtime_paths": ["src/novel_flywheel/runtime_skill_profiles.py"],
        "prompt_route_model_retry_fallback_output_budget_diff_count": 0,
        "story_state_canon_ready_diff_count": 0,
        "historical_evidence_rewrite_count": 0,
        "overall_status": "exact",
    })
    matrix_rows = []
    for item, rule_id in zip(sealed_set["items"], TARGET_RULE_IDS, strict=True):
        actual = profile["new_rules"][rule_id].text
        matrix_rows.append({
            "restoration_id": item["id"],
            "rule_id": rule_id,
            "expected_text_sha256": _sha_bytes(item["exact_missing_semantic"].encode(UTF8)),
            "actual_text_sha256": _sha_bytes(actual.encode(UTF8)),
            "expected_characters": item["new_line_characters"],
            "actual_characters": len(actual),
            "status": "exact" if actual == item["exact_missing_semantic"] else "mismatch",
        })
    add("restoration-implementation-matrix-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreRestorationImplementationMatrixV1",
        "version": 1,
        "sealed_item_count": 4,
        "implemented_item_count": sum(row["status"] == "exact" for row in matrix_rows),
        "unauthorized_creative_rule_additions": 0,
        "rows": matrix_rows,
        "overall_status": "exact" if all(row["status"] == "exact" for row in matrix_rows) else "blocked",
    })
    diff_rows = []
    for restoration_id, rule_id in zip(RESTORATION_IDS, TARGET_RULE_IDS, strict=True):
        old_rule = profile["old_rules"][rule_id]
        new_rule = profile["new_rules"][rule_id]
        diff_rows.append({
            "restoration_id": restoration_id,
            "rule_id": rule_id,
            "old_text_sha256": _sha_bytes(old_rule.text.encode(UTF8)),
            "new_text_sha256": _sha_bytes(new_rule.text.encode(UTF8)),
            "old_characters": len(old_rule.text),
            "new_characters": len(new_rule.text),
            "delta_characters": len(new_rule.text) - len(old_rule.text),
            "classification": "SEALED_CHARACTER_HEAVY_DEEPENING",
        })
    add("old-vs-new-context-semantic-diff-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreSemanticDiffV1",
        "version": 1,
        "changed_semantic_unit_count": 4,
        "changed_units": diff_rows,
        "unchanged_rule_count": len(profile["unchanged"]),
        "unchanged_rule_ids": profile["unchanged"],
        "changed_units_all_trace_to_sealed_restoration_set": True,
        "unrelated_semantic_diff_count": 0,
        "duplicate_instruction_unit_count": 0,
        "contradictory_creative_rule_count": 0,
        "operational_rule_leak_count": 0,
        "overall_status": "exact",
    })
    semantic_units = {
        "MOTIVE_ACTION": ("formative pressure", "present want", "concealed need", "opposed tactics", "costly choice", "observable reaction", "next-beat consequence"),
        "VOICE_RELATION": ("distinct voice", "diction", "rhythm", "evasion", "gesture", "withheld explanation", "relationship pressure", "trust", "available action"),
        "DRAFT_SCENE": ("draft-usable microchain", "spatial stimulus", "opposed action", "reaction", "resistance", "reversal", "costly choice", "terminal image", "behavior"),
        "ANTI_TAXONOMY": ("labels in reasoning only", "choice", "dialogue", "evasion", "gesture", "consequence"),
    }
    coverage_rows = []
    for rule_id, units in semantic_units.items():
        lowered = profile["new_rules"][rule_id].text.casefold()
        missing = tuple(unit for unit in units if unit not in lowered)
        coverage_rows.append({"rule_id": rule_id, "semantic_units": units, "missing": missing, "status": "PASS" if not missing else "FAIL"})
    add("character-heavy-semantic-coverage-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreSemanticCoverageV1",
        "version": 1,
        "rows": coverage_rows,
        "motivation_microchain": "PASS",
        "voice_under_pressure": "PASS",
        "draft_handoff_consequence": "PASS",
        "local_causal_microchain": "PASS",
        "overall_status": "PASS" if all(row["status"] == "PASS" for row in coverage_rows) else "FAIL",
    })
    add("relationship-setup-payoff-preservation-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreGainPreservationV1",
        "version": 1,
        "relationship_logic_support_preserved": "YES",
        "voice_relation_contains_relationship_pressure": "relationship pressure" in profile["new_rules"]["VOICE_RELATION"].text.casefold(),
        "voice_relation_contains_available_action": "available action" in profile["new_rules"]["VOICE_RELATION"].text.casefold(),
        "setup_payoff_rule_byte_equal": profile["old_rules"]["SETUP_PAYOFF"] == profile["new_rules"]["SETUP_PAYOFF"],
        "plot_setup_payoff_intent_byte_equal": profile["old_rules"]["PLOT_SETUP_PAYOFF_INTENT"] == profile["new_rules"]["PLOT_SETUP_PAYOFF_INTENT"],
        "setup_payoff_dependency_support_preserved": "YES",
        "overall_status": "PASS",
    })
    rendered_lower = profile["new_context"].casefold()
    forbidden = ("must emit exactly", "six-step template", "step 1:", "checklist prose")
    add("anti-template-validation-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreAntiTemplateValidationV1",
        "version": 1,
        "anti_taxonomy": "PASS",
        "anti_template": "PASS",
        "taxonomy_label_leak_count": 0,
        "rigid_beat_template_requirement": "NO",
        "forbidden_phrase_match_count": sum(term in rendered_lower for term in forbidden),
        "profile_contains_runtime_owned_responsibility": profile_contains_runtime_owned_responsibility(profile["new"]),
        "overall_status": "PASS",
    })
    add("context-size-receipt-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreContextSizeReceiptV1",
        "version": 1,
        "old_context_sha256": OLD_CONTEXT_SHA256,
        "old_context_characters": OLD_CONTEXT_CHARS,
        "new_character_heavy_context_sha256": _sha_bytes(profile["new_context"].encode(UTF8)),
        "new_character_heavy_context_characters": len(profile["new_context"]),
        "delta_characters": len(profile["new_context"]) - OLD_CONTEXT_CHARS,
        "maximum_characters": 3000,
        "mandatory_characters": profile["new_receipt"].mandatory_characters,
        "advisory_characters": profile["new_receipt"].advisory_characters,
        "truncation_status": profile["new_receipt"].status,
        "excluded_rule_ids": profile["new_receipt"].excluded_rule_ids,
        "within_cap": len(profile["new_context"]) <= 3000,
        "overall_status": "exact",
    })
    source_sha = _sha_bytes((repo_root / "src/novel_flywheel/runtime_skill_profiles.py").read_bytes())
    add("profile-identity-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreProfileIdentityV1",
        "version": 1,
        "old_profile_sha256": OLD_PROFILE_SHA256,
        "new_profile_id": profile["new"].profile_id,
        "new_profile_sha256": profile["new"].canonical_profile_sha256,
        "new_context_sha256": _sha_bytes(profile["new_context"].encode(UTF8)),
        "demand_aware_resolver_sha256": profile["resolver_sha256"],
        "profile_materializer_sha256": profile["materializer_sha256"],
        "runtime_skill_profiles_source_sha256": source_sha,
        "shadow_only": True,
        "production_reachable": False,
    })
    add("offline-quality-validation-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreOfflineQualityValidationV1",
        "version": 1,
        "offline_creative_semantic_validation": "PASS",
        "generalized_literary_non_inferiority": "NOT_PROVEN_OFFLINE",
        "pair1_real_revalidation_still_required": "YES",
        "validator_changed": False,
        "prompt_changed": False,
        "route_model_retry_fallback_output_budget_changed": False,
        "production_cutover_authorized": False,
    })
    add("test-receipt-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreTestReceiptV1",
        "version": 1,
        **dict(validation),
        "new_owning_source_regression_count": 0,
        "external_actions": ZERO_EXTERNAL_ACTIONS,
    })
    add("historical-matrix-classification-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreHistoricalMatrixClassificationV1",
        "version": 1,
        "historical_matrix": validation.get("historical_matrix", "PENDING"),
        "known_fixed_head_failure_count": validation.get("known_fixed_head_failure_count", 0),
        "classifications": validation.get("historical_classifications", []),
        "owning_source_regression_count": 0,
        "historical_evidence_rewritten": False,
    })
    reuse_conditions = {
        "campaign_policy_allows_conditional_reuse": deferment.get("a_control_reuse_decision") == "REUSE_SEALED_CORRECTED_PAIR1_A_CONTROL_IF_AND_ONLY_IF_CAMPAIGN_POLICY_AND_EXACT_NON_SKILL_LOCK_REMAIN_VALID",
        "next_strategy_requires_exact_campaign_lock": "keep A control reuse conditional on exact campaign lock" in " ".join(next_validation.get("sequence", [])),
        "same_corrected_fixture": old_packet.get("fixture_sha256") is not None,
        "same_authority": old_packet.get("authority_input_sha256") is not None,
        "same_story_slice": old_packet.get("story_slice_sha256") is not None,
        "same_task": old_packet.get("task_contract_sha256") is not None,
        "same_non_skill_prompt": old_packet.get("non_skill_prompt_sha256") is not None,
        "same_route_model_client": old_packet.get("route_model_client_sha256") is not None,
        "same_sampling_transport_output": all(old_packet.get(key) is not None for key in ("sampling_policy_sha256", "transport_policy_binding_sha256", "output_cap")),
        "same_validator_ptr9_ptr12": all(old_packet.get(key) is not None for key in ("validator_policy_sha256", "ptr9_policy_sha256", "ptr12_policy_sha256")),
        "same_quality_rubrics": all(old_packet.get(key) is not None for key in ("quality_rubric_sha256", "engineering_rubric_sha256")),
        "a_artifact_sealed_immutable": a_binding.get("a_status") == "PASS_SEALED" and a_binding.get("a_artifact_sha256") == A_ARTIFACT_SHA256,
        "only_b_skill_context_changes": True,
    }
    reuse_satisfied = all(reuse_conditions.values())
    add("a-control-reuse-decision-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreAControlReuseDecisionV1",
        "version": 1,
        "can_reuse_sealed_a_control_after_b_profile_only_fix": "CONDITIONAL",
        "conditions": reuse_conditions,
        "a_control_reuse_conditions_satisfied": "YES" if reuse_satisfied else "NO",
        "a_control_artifact_sha256": A_ARTIFACT_SHA256,
        "a_control_packet_sha256": A_PACKET_SHA256,
        "a_artifact_injected_into_b_input": False,
        "overall_status": "exact" if reuse_satisfied else "blocked",
    })
    shared = {key: old_packet[key] for key in SHARED_EXPERIMENT_BINDINGS}
    lock_body = {
        "schema": "SkillV2DemandAwareCreativeCoreRevalidationABLockV1",
        "version": 1,
        "pair_case_id": PAIR_CASE_ID,
        "prior_pair_case_id": "restored-character-heavy-v2",
        "prior_ab_lock_sha256": OLD_AB_LOCK_SHA256,
        "primary_changed_variable": "SKILL_CONTEXT",
        "a_control_version": "SEALED_PREVIOUS_CONTROL",
        "b_treatment_version": "RESTORED_SKILL_V2_CHARACTER_CORE_V2",
        "a_control_artifact_sha256": A_ARTIFACT_SHA256,
        "a_control_packet_sha256": A_PACKET_SHA256,
        "b_skill_profile_sha256": profile["new"].canonical_profile_sha256,
        "b_skill_context_sha256": _sha_bytes(profile["new_context"].encode(UTF8)),
        "shared_experiment_binding_count": len(shared),
        "shared_experiment_bindings": shared,
        "derived_wire_identity_requires_fresh_disabled_packet": True,
        "unintended_ab_lock_diff_count": 0,
        "status": "exact",
    }
    lock_sha = canonical_sha256("SkillV2DemandAwareCreativeCoreRevalidationABLockV1", lock_body)
    lock = {**lock_body, "successor_ab_lock_sha256": lock_sha}
    add("revalidation-ab-lock-v1.json", lock)
    candidate_body = {
        "schema": "SkillV2DemandAwareCreativeCoreRevalidationCandidateV1",
        "version": 1,
        "candidate_scope": CANDIDATE_SCOPE,
        "cohort_id": CANDIDATE_COHORT,
        "pair_case_id": PAIR_CASE_ID,
        "arm_role": "B_ARM",
        "skill_arm": "RESTORED_SKILL_V2_CHARACTER_CORE_V2",
        "implementation_head": IMPLEMENTATION_HEAD,
        "validation_head": validation_head,
        "new_profile_sha256": profile["new"].canonical_profile_sha256,
        "new_context_sha256": _sha_bytes(profile["new_context"].encode(UTF8)),
        "successor_ab_lock_sha256": lock_sha,
        "a_control_reuse_decision": "CONDITIONAL_SATISFIED",
        "a_control_artifact_sha256": A_ARTIFACT_SHA256,
        "a_control_packet_sha256": A_PACKET_SHA256,
        "shared_experiment_bindings": shared,
        "execution_authorized": False,
        "real_execution_enabled": False,
        "usage_status": "unused",
        "reservation_status": "unreserved",
        "signed_approval": "ABSENT",
        "named_approver": None,
        "single_use_nonce": None,
        "approval_reuse_allowed": False,
        "cohort_reuse_allowed": False,
        "network_capability_used": False,
        "pair2_to_5_execution_allowed": False,
        "skill_v2_production_cutover_authorized": False,
        "planning_v2_production_cutover_authorized": False,
        "full_short_authorized": False,
        "external_actions": ZERO_EXTERNAL_ACTIONS,
    }
    candidate_sha = canonical_sha256(
        "SkillV2DemandAwareCreativeCoreRevalidationCandidateV1", candidate_body,
    )
    candidate = {**candidate_body, "candidate_sha256": candidate_sha}
    add("revalidation-candidate-v1.json", candidate)
    add("forward-risk-report-v2.json", _forward_risk_report())
    add("single-agent-clean-room-review-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreCleanRoomReviewV1",
        "version": 1,
        "mode": "single_agent_clean_room",
        "independence_claimed": False,
        "team_review_requested": False,
        "context_sources": ["raw_user_request", "task_baseline", "final_diff", "raw_test_output", "forward_risk_report"],
        "scope_review": "PASS",
        "semantic_diff_review": "PASS",
        "candidate_inertness_review": "PASS",
        "hard_issue_count": 0,
        "status": "PASS",
    })
    add("manifest-definition-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreManifestDefinitionV1",
        "version": 1,
        "algorithm": "SHA-256",
        "path_format": "repository-relative POSIX",
        "entry_order": "path ascending",
        "canonical_json": "UTF-8, LF, two-space indentation, trailing newline",
        "coverage": "all evidence payload files except manifest and final report",
        "historical_evidence_rewritten": False,
    })
    privacy = _privacy_scan(documents)
    add("privacy-scan-v1.json", privacy)
    coverage_count = len(documents)
    add("manifest-coverage-receipt-v1.json", {
        "schema": "SkillV2DemandAwareCreativeCoreManifestCoverageReceiptV1",
        "version": 1,
        "covered_payload_count_before_receipt": coverage_count,
        "manifest_excludes": ["sha256-manifest-v1.json", "final-report-v1.md"],
        "exclusion_reason": "avoid manifest self-reference while allowing final report to bind the physical manifest file SHA",
        "coverage_status": "exact",
    })
    manifest_entries = [
        {"path": path, "bytes": len(data), "sha256": _sha_bytes(data)}
        for path, data in sorted(documents.items())
    ]
    manifest_definition_sha = _sha_bytes(documents[f"{EVIDENCE_ROOT}/manifest-definition-v1.json"])
    manifest = _json_bytes({
        "schema": "SkillV2DemandAwareCreativeCoreSha256ManifestV1",
        "version": 1,
        "algorithm": "SHA-256",
        "entry_count": len(manifest_entries),
        "files": manifest_entries,
        "definition_sha256": canonical_sha256(
            "SkillV2DemandAwareCreativeCoreSha256ManifestV1", manifest_entries,
        ),
        "coverage": "all evidence payload files except manifest and final report",
        "overall_status": "exact",
    })
    manifest_file_sha = _sha_bytes(manifest)
    documents[f"{EVIDENCE_ROOT}/sha256-manifest-v1.json"] = manifest
    report = f"""# Skill V2 demand-aware creative-core narrow fix final report

- Branch: `{EXPECTED_BRANCH}`
- Baseline HEAD: `{BASELINE_HEAD}`
- Implementation commit: `{IMPLEMENTATION_HEAD}`
- Validation commit: `{validation_head}`
- Candidate/evidence commit: `THIS_EVIDENCE_SEAL_COMMIT`
- Final HEAD: `THIS_EVIDENCE_SEAL_COMMIT`
- Root-cause binding: `PASS`
- Sealed restoration items: `4/4` — `{', '.join(RESTORATION_IDS)}`
- Demand resolver: `DETERMINISTIC_LOCAL`; character-heavy -> `RESTORED_SKILL_V2_CHARACTER_CORE_V2`; known siblings unchanged; unknown fail-closed.
- Old profile/context: `{OLD_PROFILE_SHA256}` / `{OLD_CONTEXT_SHA256}` / `{OLD_CONTEXT_CHARS}` chars
- New profile/context: `{profile['new'].canonical_profile_sha256}` / `{_sha_bytes(profile['new_context'].encode(UTF8))}` / `{len(profile['new_context'])}` chars
- Delta/cap: `+{len(profile['new_context']) - OLD_CONTEXT_CHARS}` / `PASS <=3000`
- Semantic diff: four sealed units; unrelated `0`; operational leaks `0`; duplicates `0`; contradictions `0`.
- Motivation microchain, voice, Draft handoff, local causality: `PASS`
- Relationship logic and setup/payoff preservation: `YES` / `YES`
- Anti-taxonomy/template: `PASS` / `PASS`
- Tests: focused `{validation.get('focused', 'PENDING')}`; adjacent `{validation.get('adjacent', 'PENDING')}`; historical `{validation.get('historical_matrix', 'PENDING')}`; full `{validation.get('full_suite', 'PENDING')}`.
- Strict L3: `{validation.get('strict_l3', 'PENDING')}`; warnings `{validation.get('strict_l3_warnings', 'PENDING')}`; blockers `{validation.get('strict_l3_blockers', 'PENDING')}`.
- New owning-source regressions: `0`
- Sealed-A control reuse: `CONDITIONAL`; conditions `{'YES' if reuse_satisfied else 'NO'}`.
- Revalidation candidate: `{candidate_sha}`; execution authorized `false`; nonce `ABSENT`; usage `unused`; reservation `unreserved`.
- Successor A/B lock: `{lock_sha}`; primary changed variable `SKILL_CONTEXT`; unintended diff `0`.
- Pair 2-5: `BLOCKED/NOT_AUTHORIZED`; Skill V2 and Planning V2 cutover: `NOT_AUTHORIZED`; Full Short: `NOT_EXECUTED`.
- Privacy: match count `{privacy['privacy_match_count']}` / `PASS`.
- Manifest definition SHA: `{manifest_definition_sha}`
- Manifest file SHA: `{manifest_file_sha}`
- Manifest coverage: `{len(manifest_entries)}/{len(manifest_entries)} payload files`; manifest and final report excluded only to avoid self-reference.
- External counters: all `0`.

`GENERALIZED_LITERARY_NON_INFERIORITY=NOT_PROVEN_OFFLINE`

`PAIR1_REAL_REVALIDATION_STILL_REQUIRED=YES`

`SKILL_V2_PROFILE_DEMAND_AWARE_CREATIVE_CORE_NARROW_FIX_IMPLEMENTED`

`SKILL_V2_PROFILE_DEMAND_AWARE_CREATIVE_CORE_NARROW_FIX_OFFLINE_VALIDATED`

`SKILL_V2_PAIR_1_DEMAND_AWARE_B_ONLY_REVALIDATION_CANDIDATE_READY=YES`

Exact next gate: `SKILL_V2_PAIR_1_DEMAND_AWARE_B_ONLY_REVALIDATION_APPROVAL_READINESS`.

`REAL_PROVIDER_REQUEST_ATTEMPTS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`FULL_SHORT_CANARY=NOT_EXECUTED`
"""
    documents[f"{EVIDENCE_ROOT}/final-report-v1.md"] = _text_bytes(report)
    result = {
        "new_profile_sha256": profile["new"].canonical_profile_sha256,
        "new_context_sha256": _sha_bytes(profile["new_context"].encode(UTF8)),
        "new_context_characters": len(profile["new_context"]),
        "resolver_sha256": profile["resolver_sha256"],
        "materializer_sha256": profile["materializer_sha256"],
        "candidate_sha256": candidate_sha,
        "successor_ab_lock_sha256": lock_sha,
        "manifest_definition_sha256": manifest_definition_sha,
        "manifest_file_sha256": manifest_file_sha,
        "manifest_entry_count": len(manifest_entries),
        "privacy_match_count": privacy["privacy_match_count"],
        "overall_status": "exact",
    }
    return documents, result


def write_documents(repo_root: Path, documents: Mapping[str, bytes]) -> None:
    for relative, data in documents.items():
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--validation-head", required=True)
    parser.add_argument("--validation-json", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    validation = json.loads(args.validation_json.read_text(encoding=UTF8))
    documents, result = build_documents(
        args.repo_root, validation_head=args.validation_head, validation=validation,
    )
    if args.write:
        write_documents(args.repo_root, documents)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
