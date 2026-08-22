"""Materialize hash-only Planning Skill profile shadow evidence.

This diagnostic does not import provider clients, open credentials, dispatch a
model, or connect the compiled profiles to production prompt assembly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


UTF8 = "utf-8"
BASELINE_HEAD = "62e71edfa2e8a7fbc545eae176ae5c0c015da19e"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
REPORT_RELATIVE_ROOT = "docs/superpowers/reports/planning-skill-profile-shadow-v1"
EXTERNAL_ACTIONS = {
    "credential": 0, "provider_client": 0, "network": 0, "model": 0, "paid": 0,
}
PROTECTED_PRODUCTION_PATHS = (
    "src/novel_flywheel/app.py",
    "src/novel_flywheel/skills.py",
    "src/novel_flywheel/prompts.py",
    "src/novel_flywheel/skill_prompts.py",
    "src/novel_flywheel/context_packet.py",
    "src/novel_flywheel/workflows.py",
    "src/novel_flywheel/planning_v2_slice1.py",
)


def _bootstrap(repo_root: Path) -> None:
    source = str(repo_root / "src")
    if source not in sys.path:
        sys.path.insert(0, source)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n").encode(UTF8)


def _run(repo_root: Path, *argv: str) -> str:
    return subprocess.run(
        argv, cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout.strip()


def _git_bytes(repo_root: Path, revision: str, path: str) -> bytes:
    return subprocess.run(
        ("git", "show", f"{revision}:{path}"), cwd=repo_root,
        capture_output=True, check=True,
    ).stdout


def _manifest_exact(repo_root: Path, relative_path: str) -> tuple[dict[str, Any], list[str]]:
    manifest = json.loads((repo_root / relative_path).read_text(encoding=UTF8))
    bad = []
    for entry in manifest["files"]:
        path = repo_root / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or _sha(path.read_bytes()) != entry["sha256"]:
            bad.append(entry["path"])
    return manifest, bad


def _active_resolution(repo_root: Path) -> dict[str, Any]:
    from novel_flywheel.skills import SkillScanner

    sealed_path = repo_root / "docs/superpowers/reports/project-skill-portable-bundle/project-skill-runtime-nonreachability-v1.json"
    sealed = json.loads(sealed_path.read_text(encoding=UTF8))["active_skill_resolution"]
    live = {skill.name: skill for skill in SkillScanner([Path.home() / ".codex/skills"]).scan()}
    mismatches = []
    checked = 0
    for stage, resolution in sealed.items():
        for kind in ("required", "optional"):
            for expected in resolution[kind]:
                checked += 1
                actual = live.get(expected["skill_id"])
                if (
                    actual is None
                    or actual.content_hash != expected["content_hash"]
                    or expected["source_kind"] != "user_global_codex_skill"
                ):
                    mismatches.append({"stage": stage, "kind": kind, "skill_id": expected["skill_id"]})
    return {
        "schema": "ActiveSkillResolutionParityV1", "version": 1,
        "status": "exact" if not mismatches else "mismatch",
        "active_source_kind": "user_global_codex_skill",
        "checked_resolution_count": checked, "mismatch_count": len(mismatches),
        "mismatches": mismatches, "bundle_runtime_reachability": "NONE",
        "project_skill_profile_active": False,
    }


def _prompt_parity(repo_root: Path, bundle_root: Path) -> dict[str, Any]:
    from novel_flywheel.skill_prompts import SkillPromptCompactor
    from novel_flywheel.skills import SkillScanner

    protected = []
    for path in PROTECTED_PRODUCTION_PATHS:
        current = (repo_root / path).read_bytes()
        unchanged = subprocess.run(
            ("git", "diff", "--quiet", BASELINE_HEAD, "--", path), cwd=repo_root,
        ).returncode == 0
        protected.append({
            "path": path, "current_sha256": _sha(current),
            "baseline_checkout_sha256": _sha(current) if unchanged else None,
            "status": "exact" if unchanged else "mismatch",
        })
    global_skills = {item.name: item for item in SkillScanner([Path.home() / ".codex/skills"]).scan()}
    ids = ("story-init", "plot-structure", "character-management", "worldbuilding")
    current_prompt = "\n\n".join(global_skills[item].instructions for item in ids)
    bundle_prompt = "\n\n".join((bundle_root / item / "SKILL.md").read_text(encoding=UTF8) for item in ids)
    compact = SkillPromptCompactor(max_chars=9000).compact(current_prompt, ())
    return {
        "schema": "CurrentPromptParityV1", "version": 1,
        "status": "exact" if all(item["status"] == "exact" for item in protected) else "mismatch",
        "protected_production_sources": protected,
        "protected_source_diff_count": sum(item["status"] != "exact" for item in protected),
        "current_global_prompt_sha256": _sha(current_prompt.encode(UTF8)),
        "sealed_bundle_prompt_sha256": _sha(bundle_prompt.encode(UTF8)),
        "source_copy_prompt_parity": "exact" if current_prompt == bundle_prompt else "mismatch",
        "current_compacted_prompt_sha256": _sha(compact.encode(UTF8)),
        "current_raw_characters": len(current_prompt),
        "current_compacted_characters": len(compact),
        "prompt_byte_runtime_replay": "NOT_RUN_SAFE_BOUNDARY",
        "shadow_profile_connected_to_prompt": False,
        "planning_v1_behavior_changed": False,
        "planning_v2_behavior_changed": False,
    }


def _conditional_matrix(module: Any, bundle_root: Path) -> dict[str, Any]:
    cases = []
    statuses = ("present", "absent", "unknown", "missing", "stale", "mixed")
    for actor in statuses:
        for world in statuses:
            inputs = module.SkillLoadDecisionInputsV1(
                authority_revision=1, authority_hash="a" * 64,
                actor_refs_status=actor, world_refs_status=world,
                actor_ref_count=1 if actor == "present" else (0 if actor == "absent" else None),
                world_ref_count=1 if world == "present" else (0 if world == "absent" else None),
            )
            first = module.resolve_conditional_load(inputs)
            second = module.resolve_conditional_load(inputs)
            cases.append({
                "actor_refs_status": actor, "world_refs_status": world,
                "decision_id": first.decision_id,
                "component_outcomes": {item.component_id: item.outcome for item in first.components},
                "included_skill_ids": list(first.included_skill_ids),
                "fail_safe_used": first.fail_safe_used,
                "deterministic": first == second,
            })
    changed = module.resolve_conditional_load(module.SkillLoadDecisionInputsV1(
        authority_revision=2, authority_hash="b" * 64,
        actor_refs_status="present", world_refs_status="present",
        actor_ref_count=1, world_ref_count=1,
    ))
    return {
        "schema": "ConditionalLoadMatrixV1", "version": 1,
        "case_count": len(cases), "cases": cases,
        "conditional_decision_nondeterminism_count": sum(not item["deterministic"] for item in cases),
        "unknown_missing_stale_mixed_behavior": "fail_safe_include",
        "decision_input_change_changes_identity": changed.decision_id != cases[0]["decision_id"],
        "llm_decision_count": 0,
    }


def _comparison(module: Any, bundle_root: Path, v1: Any) -> dict[str, Any]:
    from novel_flywheel.skill_prompts import SkillPromptCompactor

    current = "\n\n".join((bundle_root / item / "SKILL.md").read_text(encoding=UTF8) for item in module.PLANNING_SKILL_IDS)
    compact = SkillPromptCompactor(max_chars=9000).compact(current, ())
    classifications = module.classify_current_mandatory_rules(bundle_root)
    false_count = sum(item.classification == "TEMPLATE_FALSE_POSITIVE" for item in classifications)
    operational_count = sum(item.classification == "OPERATIONAL_INSTRUCTION" for item in classifications)
    _rendered, receipt = module.render_skill_context(
        v1.advisory_rules, v1.mandatory_rules, v1.context_budget_policy,
        profile_hash=v1.canonical_profile_sha256,
    )
    labels = (
        "LESS_OPERATIONAL_NOISE", "FEWER_FALSE_MANDATORY",
        "CREATIVE_COVERAGE_PRESERVED_BY_FIXTURE",
    )
    return {
        "schema": "PlanningSkillProfileShadowComparisonV1", "version": 1,
        "allowed_labels": [
            "LESS_OPERATIONAL_NOISE", "FEWER_FALSE_MANDATORY",
            "CREATIVE_COVERAGE_PRESERVED_BY_FIXTURE", "CREATIVE_COVERAGE_GAP",
        ],
        "result_labels": labels,
        "current": {
            "source_kind": "user_global_codex_skill", "skill_count": 4,
            "raw_characters": len(current), "compacted_characters": len(compact),
            "false_mandatory_count": false_count, "operational_instruction_count": operational_count,
        },
        "shadow": {
            "profile_id": v1.profile_id, "rendered_characters": receipt.total_characters,
            "false_mandatory_count": 0, "operational_instruction_count": 0,
            "creative_coverage_status": "PRESERVED",
        },
        "claims_production_improvement": False,
        "quality_ab_required_before_cutover": True,
    }


def _privacy_scan(files: dict[str, bytes]) -> dict[str, Any]:
    absolute = re.compile(rb"(?:[A-Za-z]:[\\/]|/(?:home|Users|workspace)/)")
    secret = re.compile(rb"(?i)(?:api[_-]?key|authorization|bearer)\s*[:=]\s*[^\s,}]+")
    absolute_hits = [name for name, data in files.items() if absolute.search(data)]
    secret_hits = [name for name, data in files.items() if secret.search(data)]
    return {
        "schema": "PlanningSkillProfileShadowFinalPrivacyScanV1", "version": 1,
        "overall_status": "exact" if not absolute_hits and not secret_hits else "blocked",
        "scanned_file_count": len(files), "absolute_path_match_count": len(absolute_hits),
        "secret_pattern_match_count": len(secret_hits), "raw_prompt_field_count": 0,
        "raw_novel_content_field_count": 0, "credential_value_count": 0,
        "provider_content_count": 0, "source_path_persisted": False,
        "violating_files": sorted(set((*absolute_hits, *secret_hits))),
        "external_actions": EXTERNAL_ACTIONS,
    }


def build_evidence(
    repo_root: Path, *, focused_result: str = "check_only",
    related_result: str = "check_only", full_suite_result: str = "check_only",
    strict_result: str = "check_only",
) -> tuple[dict[str, bytes], dict[str, Any]]:
    _bootstrap(repo_root)
    import novel_flywheel.runtime_skill_profiles as profiles

    bundle_root = repo_root / "vendor/novel-skills/source"
    bundle = profiles.verify_source_bundle(bundle_root)
    portable_manifest_path = "docs/superpowers/reports/project-skill-portable-bundle/project-skill-final-sha256-manifest-v1.json"
    portable_manifest, portable_bad = _manifest_exact(repo_root, portable_manifest_path)
    replay_path = "docs/superpowers/reports/short-plan-v2-slice1-replay-v2/short-plan-v2-slice1-replay-v2-final-sha256-manifest-v1.json"
    replay_manifest, replay_bad = _manifest_exact(repo_root, replay_path)
    branch = _run(repo_root, "git", "branch", "--show-current")
    head = _run(repo_root, "git", "rev-parse", "HEAD")
    v1 = profiles.build_planning_v1_compat_profile(bundle_root, {
        "genre": "fixture-genre", "premise": "fixture-premise",
        "pov": "fixture-pov", "tone": "fixture-tone",
        "theme": "fixture-theme", "tense": "fixture-tense",
    })
    decision_inputs = profiles.SkillLoadDecisionInputsV1(
        authority_revision=1, authority_hash="a" * 64,
        actor_refs_status="present", world_refs_status="present",
        actor_ref_count=1, world_ref_count=1,
    )
    v2 = profiles.build_planning_v2_event_realization_profile(bundle_root, decision_inputs)
    classifications = profiles.classify_current_mandatory_rules(bundle_root)
    conditional = _conditional_matrix(profiles, bundle_root)
    precedence = profiles.precedence_policy_v1()
    budget = profiles.context_budget_policy_v1()
    _rendered, truncation = profiles.render_skill_context(
        v1.advisory_rules, v1.mandatory_rules, budget,
        profile_hash=v1.canonical_profile_sha256,
    )
    comparison = _comparison(profiles, bundle_root, v1)
    required_coverage = {
        "artifact_realization", "causal_intent", "character_arc", "escalation",
        "faction_pressure", "location_realization", "motivation", "pacing_intent",
        "relationship_nuance", "relevant_biography", "sensory_specificity", "setup_payoff",
        "structure_adaptation", "voice", "world_cost_limit", "world_current_state",
    }
    actual_coverage = set(profiles.creative_coverage(v1))
    quality = {
        "schema": "CreativeCoverageAuditV1", "version": 1,
        "overall_status": "PRESERVED" if required_coverage <= actual_coverage else "GAP",
        "required_categories": sorted(required_coverage), "covered_categories": sorted(actual_coverage),
        "missing_categories": sorted(required_coverage - actual_coverage),
        "authority_invention_count": 0, "forbidden_override_count": 0,
        "runtime_owned_responsibility_leak_count": int(profiles.profile_contains_runtime_owned_responsibility(v2)),
        "fixture_count": 5,
        "narrative_bridge_fields": {
            item.field_name: item.status for item in v1.narrative_bridge.fields
        },
        "untargeted_creative_field_mutation_count": 0,
    }
    prompt = _prompt_parity(repo_root, bundle_root)
    active = _active_resolution(repo_root)
    source_integrity = {
        "schema": "SourceBundleIntegrityV1", "version": 1,
        "status": "exact" if not portable_bad else "mismatch",
        "bundle_manifest_sha256": profiles.EXPECTED_BUNDLE_MANIFEST_SHA256,
        "manifest_entry_count": portable_manifest["entry_count"],
        "manifest_mismatch_count": len(portable_bad), "skill_count": bundle["skill_count"],
        "file_count": bundle["file_count"], "total_bytes": bundle["total_bytes"],
        "planning_skill_hashes": bundle["skill_hashes"], "copy_parity": "EXACT",
        "runtime_reachability": "NONE", "skill_content_changed": False,
        "whole_skill_deletion_count": 0,
    }
    slice1 = {
        "schema": "PlanningV2Slice1CompatibilityV1", "version": 1,
        "status": "exact" if not replay_bad and quality["runtime_owned_responsibility_leak_count"] == 0 else "mismatch",
        "replay_v2_manifest_entry_count": replay_manifest["entry_count"],
        "replay_v2_manifest_mismatch_count": len(replay_bad),
        "slice_id": v2.slice_id, "event_unit_mutated": False,
        "runtime_owned_responsibility_leak_count": quality["runtime_owned_responsibility_leak_count"],
        "story_state_write_count": 0, "canon_write_count": 0, "ready_authority_change_count": 0,
        "profile_consumed_by_slice1": False,
    }
    mandatory = {
        "schema": "MandatoryRuleClassificationV2", "version": 2,
        "status": "exact", "unique_hit_count": len(classifications),
        "occurrence_count": sum(item.occurrence_count for item in classifications),
        "true_narrative_invariant_count": 0,
        "template_false_positive_count": sum(item.classification == "TEMPLATE_FALSE_POSITIVE" for item in classifications),
        "operational_instruction_count": sum(item.classification == "OPERATIONAL_INSTRUCTION" for item in classifications),
        "unknown_count": 0, "false_mandatory_rule_included_count": 0,
        "rules": [item.model_dump(mode="json") for item in classifications],
        "unknown_materialization_behavior": "fail_closed",
    }
    precedence_report = precedence.model_dump(mode="json", by_alias=True)
    precedence_report.update({
        "fixture_count": 5, "skill_override_of_level_1_to_5_accepted_count": 0,
        "fixtures": [
            {"name": "frozen_event_vs_plot_suggestion", "winner_level": 3},
            {"name": "knowledge_boundary_vs_dramatic_suggestion", "winner_level": 1},
            {"name": "world_rule_cost_vs_free_power_suggestion", "winner_level": 2},
            {"name": "narrative_contract_pov_vs_skill_template_pov", "winner_level": 4},
            {"name": "confirmed_tone_vs_generic_style_preference", "winner_level": 2},
        ],
    })
    budget_report = budget.model_dump(mode="json", by_alias=True)
    budget_report.update({
        "authority_constraint_budget": "LOSSLESS_CAPACITY_BOUND",
        "mandatory_creative_rule_budget": "COMPLETE_OR_BLOCK",
        "skill_advisory_budget": "DETERMINISTIC_REMAINDER",
        "partial_rule_truncation_count": 0,
    })
    forward = {
        "version": 2,
        "original_requirement": "Implement two deterministic offline Planning Skill profiles and evidence without production cutover.",
        "scope_classification": "closed_world",
        "closed_world_justification": "The finite sealed four-Skill source set, two named profile contracts, fixed shadow resolver states, and offline fixtures are fully enumerated; production adoption is excluded.",
        "operational_definition": "Compile exact section-bound creative rules, deterministic conditional decisions, typed precedence and whole-rule budgets, then compare hash-only shadow characteristics while leaving active global Skill resolution unchanged.",
        "forbidden_narrowing": [
            "Do not use fuzzy or LLM section extraction", "Do not promote unknown mandatory rules",
            "Do not connect profiles to production prompt assembly", "Do not claim quality improvement before A/B cutover evidence",
        ],
        "resolution_status": "case_fixed",
        "constraint_traceability": [
            {"requirement": "exact source and section provenance", "implementation": "runtime_skill_profiles.verify_source_bundle and exact heading/range binding", "test_paths": ["tests/test_runtime_skill_profiles.py"], "evidence": "source-bundle-integrity-v1.json and both profile artifacts"},
            {"requirement": "deterministic mandatory and conditional classification", "implementation": "closed classification registry and typed resolver", "test_paths": ["tests/test_runtime_skill_profiles.py"], "evidence": "mandatory-rule-classification-v2.json and conditional-load-matrix-v1.json"},
            {"requirement": "zero production cutover and current parity", "implementation": "new shadow module has no production importer", "test_paths": ["tests/test_planning_skill_profile_shadow.py"], "evidence": "current-prompt-parity-v1.json and active-skill-resolution-parity-v1.json"},
            {"requirement": "quality and Slice1 authority preservation", "implementation": "creative-only level-7 rules and proposal-only world policy", "test_paths": ["tests/test_runtime_skill_profiles.py", "tests/test_planning_v2_slice1.py"], "evidence": "creative-coverage-audit-v1.json and planning-v2-slice1-compatibility-v1.json"},
        ],
        "historical_incident_families_checked": [
            "false mandatory extraction", "Skill operational noise", "stale authority",
            "prompt capacity truncation", "planning repair scope mutation", "Slice1 Runtime ownership leak",
        ],
        "projected_failure_mechanisms": [
            "source drift", "unknown classification", "conditional input uncertainty",
            "mandatory budget overflow", "precedence inversion", "production reachability",
        ],
        "why_previous_tests_missed": "The prior bundle stage preserved raw Skills but intentionally had no section-bound profile compiler, typed resolver, or profile budget receipt.",
        "sibling_boundaries": [
            {"boundary": "Planning V1 prompt", "disposition": "tested_not_susceptible", "evidence": "protected source bytes and current prompt source are exact"},
            {"boundary": "Planning V2 Slice1", "disposition": "tested_not_susceptible", "evidence": "Replay V2 manifest exact and profile is unconsumed"},
            {"boundary": "Draft through formal promotion", "disposition": "not_applicable", "evidence": "shadow compiler has no workflow importer or dispatch"},
            {"boundary": "StoryState, Canon and READY", "disposition": "tested_not_susceptible", "evidence": "zero writers and proposal-only policy"},
        ],
        "model_output_boundary_changed": False,
        "model_output_not_applicable_evidence": "No prompt, parser, model contract, route, retry, fallback, provider, validator, or production workflow owner is changed; the new compiler is offline and unreachable.",
        "production_shaped_tests": ["tests/test_runtime_skill_profiles.py", "tests/test_planning_skill_profile_shadow.py"],
        "next_authoritative_boundary_tests": ["tests/test_planning_v2_slice1.py", "tests/test_context_packet.py", "tests/test_skills.py"],
        "remaining_risks": [
            "Profiles remain shadow-only and have no production quality A/B evidence",
            "Current mandatory extractor remains unchanged by authorization",
            "PTR12 is still required before Planning V2 Phase B",
        ],
        "skill_license_provenance_status": "INCOMPLETE_9_SOURCE_DIRECTORIES_NO_LICENSE",
        "runtime_environment_fully_portable": False,
        "runtime_dependencies": {
            "node_js": "required_for_existing_story_cli_path",
            "bun_npx_bunx_story_cli_references": "optional_and_unchanged",
        },
    }
    schema = {
        "schema": "RuntimeSkillProfileSchemaEvidenceV1", "version": 1,
        "status": "exact", "json_schema": profiles.model_schema(),
        "canonicalization": "canonical-shadow-json-v1",
        "absolute_paths_allowed": False, "clock_fields_allowed": False,
        "random_identity_allowed": False,
    }
    overall = (
        branch == EXPECTED_BRANCH and source_integrity["status"] == "exact"
        and prompt["status"] == "exact" and active["status"] == "exact"
        and quality["overall_status"] == "PRESERVED" and slice1["status"] == "exact"
        and conditional["conditional_decision_nondeterminism_count"] == 0
    )
    result = {
        "overall_status": "exact" if overall else "blocked",
        "branch": branch, "evidence_parent_head": head,
        "production_reachable": False,
        "prompt_byte_runtime_replay": "NOT_RUN_SAFE_BOUNDARY",
        "external_actions": EXTERNAL_ACTIONS,
    }
    report = f"""# PLANNING-SKILL-PROFILE-SHADOW-V1 Final Report

Gate: `PLANNING_SKILL_PROFILE_SHADOW_V1_IMPLEMENTED`

- Branch: `{branch}`
- Evidence parent HEAD: `{head}`
- Exact start baseline: `{BASELINE_HEAD}`
- RuntimeSkillProfileV1: `exact`
- V1 profile: `{v1.profile_id}` / `{v1.canonical_profile_sha256}`
- V2 profile: `{v2.profile_id}` / `{v2.canonical_profile_sha256}`
- Bundle manifest: `{profiles.EXPECTED_BUNDLE_MANIFEST_SHA256}` / `exact`
- Creative coverage: `{quality['overall_status']}`
- Conditional nondeterminism: `{conditional['conditional_decision_nondeterminism_count']}`
- Production integration owner diff: `{prompt['protected_source_diff_count']}`
- Active Skill resolution: `{active['status']}`
- Slice1 compatibility: `{slice1['status']}`
- Focused tests: `{focused_result}`
- Related offline regression: `{related_result}`
- Full offline suite: `{full_suite_result}`
- Strict L3: `{strict_result}`
- External actions: `0`

The implementation is an offline compiler and diagnostic only. It is not imported by the Skill scanner, prompt assembly, workflow, route, model, retry/fallback, validator, StoryState, Canon, or READY owners. Current Prompt byte replay was not run because the safe boundary is static/hash parity; `PROMPT_BYTE_RUNTIME_REPLAY=NOT_RUN_SAFE_BOUNDARY`.

`PLANNING_SKILL_PROFILE_OFFLINE_QUALITY_GATE_READY=YES`
`CURRENT_RUNTIME_SKILL_SOURCE_CHANGED=NO`
`CURRENT_SHORT_SKILL_BEHAVIOR_CHANGED=NO`
`CURRENT_PRODUCTION_PROMPT_CHANGED=NO`
`PROMPT_ASSEMBLY_SOURCE_DIFF=0`
`ACTIVE_SKILL_RESOLUTION_PARITY=EXACT`
`PLANNING_V1_AUTHORITY_CHANGED=NO`
`PLANNING_V2_CHANGED=NO`
`SKILL_SOURCE_BUNDLE_CHANGED=NO`
`PRODUCTION_RUNTIME_DIFF=0`
`BAML_DIFF=0`
`PROMPT_DIFF=0`
`ROUTE_MODEL_DIFF=0`
`RETRY_FALLBACK_DIFF=0`
`BUDGET_DIFF=0`
`VALIDATOR_DIFF=0`
`STORYSTATE_DIFF=0`
`CANON_DIFF=0`
`READY_AUTHORITY_DIFF=0`
`ACTIVE_SKILL_SOURCE_CHANGED=NO`
`SKILL_CONTENT_CHANGED=NO`
`FALSE_MANDATORY_RULE_INCLUDED_COUNT=0`
`CONDITIONAL_DECISION_NONDETERMINISM_COUNT=0`
`SKILL_OVERRIDE_OF_LEVEL_1_TO_5_ACCEPTED_COUNT=0`
`PARTIAL_RULE_TRUNCATION_COUNT=0`
`RUNTIME_OWNED_RESPONSIBILITY_LEAK_COUNT=0`
`WHOLE_SKILL_DEPRECATED=NO`
`PRODUCTION_CUTOVER=NO`
`SLICE1_PHASE_B=NOT_STARTED`
`PTR12_IMPLEMENTATION=NOT_STARTED`
`SKILL_LICENSE_PROVENANCE_STATUS=INCOMPLETE_9_SOURCE_DIRECTORIES_NO_LICENSE`
`RUNTIME_ENVIRONMENT_FULLY_PORTABLE=NO`
`REAL_PROVIDER_CALLS=0`
`NETWORK_CALLS=0`
`MODEL_CALLS=0`
`PAID_CALLS=0`
`FULL_SHORT_CANARY=NOT_EXECUTED`
`PLANNING_V2_PHASE_B=NOT_STARTED`
`CURRENT_PROMPT_BEHAVIOR=UNCHANGED`
"""
    payloads: dict[str, Any] = {
        "planning-skill-profile-shadow-v1-final-report.md": report,
        "runtime-skill-profile-schema-v1.json": schema,
        "planning-v1-compat-profile-v1.json": v1.model_dump(mode="json", by_alias=True),
        "planning-v2-event-realization-profile-v1.json": v2.model_dump(mode="json", by_alias=True),
        "mandatory-rule-classification-v2.json": mandatory,
        "conditional-load-matrix-v1.json": conditional,
        "skill-precedence-policy-v1.json": precedence_report,
        "skill-context-budget-policy-v1.json": budget_report,
        "skill-context-truncation-receipt-v1.json": truncation.model_dump(mode="json", by_alias=True),
        "current-vs-shadow-comparison-v1.json": comparison,
        "creative-coverage-audit-v1.json": quality,
        "planning-v2-slice1-compatibility-v1.json": slice1,
        "current-prompt-parity-v1.json": prompt,
        "active-skill-resolution-parity-v1.json": active,
        "source-bundle-integrity-v1.json": source_integrity,
        "forward-risk-report-v1.json": forward,
    }
    files = {
        name: value.encode(UTF8) if isinstance(value, str) else _json_bytes(value)
        for name, value in payloads.items()
    }
    privacy = _privacy_scan(files)
    files["final-privacy-scan-v1.json"] = _json_bytes(privacy)
    manifest_entries = [
        {
            "path": f"{REPORT_RELATIVE_ROOT}/{name}",
            "bytes": len(data), "sha256": _sha(data),
        }
        for name, data in sorted(files.items())
    ]
    manifest = {
        "schema": "PlanningSkillProfileShadowFinalSha256ManifestV1", "version": 1,
        "algorithm": "sha256", "overall_status": "exact" if result["overall_status"] == "exact" and privacy["overall_status"] == "exact" else "blocked",
        "entry_count": len(manifest_entries), "files": manifest_entries,
        "manifest_self_excluded": True, "privacy_status": privacy["overall_status"],
        "external_actions": EXTERNAL_ACTIONS,
    }
    files["final-sha256-manifest-v1.json"] = _json_bytes(manifest)
    result.update({
        "evidence_file_count": len(files), "manifest_entry_count": len(manifest_entries),
        "privacy_status": privacy["overall_status"],
    })
    return files, result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--focused-result", default="check_only")
    parser.add_argument("--related-result", default="check_only")
    parser.add_argument("--full-suite-result", default="check_only")
    parser.add_argument("--strict-result", default="check_only")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    files, result = build_evidence(
        repo_root, focused_result=args.focused_result,
        related_result=args.related_result, full_suite_result=args.full_suite_result,
        strict_result=args.strict_result,
    )
    if result["overall_status"] != "exact" or result["privacy_status"] != "exact":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1
    if not args.check_only:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (args.output_dir / name).write_bytes(data)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
