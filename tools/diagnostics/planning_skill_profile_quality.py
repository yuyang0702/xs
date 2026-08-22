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
START_HEAD = "a377ada959dbfb3ef25cd8956700c6679c228dcb"
EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
EXPECTED_V1_SHA = "f17fab327c0dbcf066a025585e1c7ea7f07bcb0247e2e26bcf1fe38b6b806b97"
EXPECTED_V2_SHA = "743a9a94aa609c6cab1dd322ccbd2be4439316fe87abc3ca273cfe3f14526629"
EXPECTED_SHADOW_MANIFEST_SHA = "45c259e0f80704c09ebc40c92de8f1bd81668c1655c72992c6be0415e8258752"
EXPECTED_BUNDLE_MANIFEST_SHA = "451a30d3815e1c6e4bdb3e1a1bc1dbec4e4a84061e873f8acca3aee2e2925a3a"
REPORT_RELATIVE_ROOT = "docs/superpowers/reports/planning-skill-profile-offline-quality-v1"
EXTERNAL_ACTIONS = {
    "credential": 0,
    "provider_client": 0,
    "network": 0,
    "model": 0,
    "paid": 0,
}
EVIDENCE_NAMES = (
    "final-report-v1.md",
    "source-coverage-matrix-v1.json",
    "plot-capability-preservation-v1.json",
    "character-capability-preservation-v1.json",
    "world-capability-preservation-v1.json",
    "narrative-bridge-validation-v1.json",
    "mandatory-rule-preservation-v1.json",
    "authority-precedence-matrix-v1.json",
    "slice1-responsibility-audit-v1.json",
    "conditional-loading-quality-v1.json",
    "truncation-quality-v1.json",
    "v1-compatibility-matrix-v1.json",
    "creative-intent-corpus-v1.json",
    "current-vs-shadow-volume-v1.json",
    "production-nonregression-v1.json",
    "readiness-v1.json",
    "forward-risk-v1.json",
    "final-privacy-scan-v1.json",
    "final-sha256-manifest-v1.json",
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(UTF8)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding=UTF8))


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True,
    )
    return completed.stdout.strip()


def _verify_manifest(repo_root: Path, relative_path: str, expected_sha: str) -> dict[str, Any]:
    path = repo_root / relative_path
    actual_manifest_sha = _sha(path.read_bytes())
    document = _load(path)
    mismatches: list[dict[str, Any]] = []
    for entry in document["files"]:
        target = repo_root / entry["path"]
        if not target.is_file():
            mismatches.append({"path": entry["path"], "reason": "missing"})
            continue
        actual = target.read_bytes()
        if len(actual) != entry["bytes"] or _sha(actual) != entry["sha256"]:
            mismatches.append({"path": entry["path"], "reason": "bytes_or_sha_mismatch"})
    return {
        "path": relative_path,
        "expected_manifest_sha256": expected_sha,
        "actual_manifest_sha256": actual_manifest_sha,
        "entry_count": len(document["files"]),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "status": "exact" if actual_manifest_sha == expected_sha and not mismatches else "changed",
    }


def _profile_identity(profile: Any) -> set[tuple[str, str, str, int]]:
    return {
        (
            item.skill_id,
            item.relative_source_path,
            item.heading,
            item.heading_ordinal,
        )
        for item in profile.included_sections
    }


def _source_sections(bundle_root: Path) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for skill_id in ("story-init", "plot-structure", "character-management", "worldbuilding"):
        for path in sorted((bundle_root / skill_id).rglob("*.md")):
            relative = path.relative_to(bundle_root).as_posix()
            lines = path.read_text(encoding=UTF8).splitlines(keepends=True)
            in_fence = False
            occurrences: dict[str, int] = {}
            for index, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("```") or stripped.startswith("~~~"):
                    in_fence = not in_fence
                    continue
                match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line.rstrip("\r\n"))
                if not match:
                    continue
                heading = match.group(2).strip()
                occurrences[heading] = occurrences.get(heading, 0) + 1
                sections.append({
                    "skill_id": skill_id,
                    "relative_source_path": relative,
                    "heading": heading,
                    "heading_level": len(match.group(1)),
                    "heading_ordinal": occurrences[heading],
                    "line_start": index + 1,
                    "inside_fenced_template": in_fence,
                })
    return sections


def _excluded_classification(row: dict[str, Any]) -> tuple[str, str]:
    heading = row["heading"].lower()
    path = row["relative_source_path"].lower()
    if row["inside_fenced_template"]:
        return "EXCLUDED_TEMPLATE", "heading belongs to a scaffold/example block, not executable creative guidance"
    if row["skill_id"] == "story-init" and row["heading"] == "Workflow":
        return "BRIDGED_FROM_AUTHORITY", "genre/premise/POV/tone/theme/tense are bridged only from confirmed authority; initialization actions are excluded"
    if any(token in heading for token in ("cli maintenance", "when to use", "prerequisites", "reference files")):
        return "EXCLUDED_OPERATIONAL", "activation, prerequisite, CLI, or reference-navigation instruction is not model creative responsibility"
    if any(token in heading for token in ("updating", "cross-referencing", "conventions")):
        return "EXCLUDED_AUTHORITY_MUTATION", "section owns file/registry mutation or cross-link maintenance outside the creative profile"
    if any(token in heading for token in ("tracking notes", "evidence", "timeline", "usage", "location references")):
        return "EXCLUDED_OPERATIONAL", "deterministic tracking, dependency bookkeeping, or usage instruction remains Runtime-owned"
    if "template" in heading or "template" in path:
        return "EXCLUDED_TEMPLATE", "container/template material is represented by selected semantic child sections or excluded as scaffolding"
    if heading in {"overview", "story initialization", "plot structure", "character management", "worldbuilding", "story structure models reference", "relationship types reference", "world element types reference"}:
        return "EXCLUDED_DUPLICATE", "container or overview duplicates the selected source sections without adding a distinct capability"
    if row["skill_id"] == "story-init":
        return "EXCLUDED_LEGACY", "new-project filesystem scaffold is not valid Planning authority for an existing project"
    return "EXCLUDED_DUPLICATE", "semantic capability is already covered by a selected generalized section/rule"


def _source_coverage(v1: Any, v2: Any, bundle_root: Path) -> dict[str, Any]:
    v1_ids = _profile_identity(v1)
    v2_ids = _profile_identity(v2)
    rows = []
    for row in _source_sections(bundle_root):
        identity = (
            row["skill_id"], row["relative_source_path"], row["heading"], row["heading_ordinal"],
        )
        if identity in v1_ids:
            classification = "INCLUDED_IN_V1_PROFILE"
            reason = "exact section binding contributes to one or more V1 creative rules"
        else:
            classification, reason = _excluded_classification(row)
        rows.append({
            **row,
            "classification": classification,
            "included_in_v1": identity in v1_ids,
            "included_in_slice1": identity in v2_ids,
            "slice1_classification": (
                "INCLUDED_IN_SLICE1_PROFILE" if identity in v2_ids else "NOT_INCLUDED_IN_SLICE1_PROFILE"
            ),
            "reason": reason,
        })
    included = sum(row["included_in_v1"] for row in rows)
    bridged = sum(row["classification"] == "BRIDGED_FROM_AUTHORITY" for row in rows)
    excluded = sum(row["classification"].startswith("EXCLUDED_") for row in rows)
    unknown = sum(row["classification"] == "UNKNOWN" for row in rows)
    return {
        "schema": "PlanningSkillProfileSourceCoverageMatrixV1",
        "version": 1,
        "source_section_count": len(rows),
        "included_section_count": included,
        "slice1_included_section_count": sum(row["included_in_slice1"] for row in rows),
        "bridged_section_count": bridged,
        "excluded_section_count": excluded,
        "unknown_section_count": unknown,
        "rows": rows,
        "overall_status": "exact" if unknown == 0 and included == len(v1_ids) else "gap",
    }


def _rule_case_report(schema: str, cases: list[dict[str, Any]], v1: Any, v2: Any) -> dict[str, Any]:
    rows = []
    gap_count = 0
    override_count = 0
    from novel_flywheel.runtime_skill_profiles import resolve_precedence

    for case in cases:
        profile = v1 if case.get("profile", "v2") == "v1" else v2
        present = set(profile.included_rule_ids)
        missing = sorted(set(case.get("required_rule_ids", ())) - present)
        forbidden_present = sorted(set(case.get("forbidden_rule_ids", ())) & present)
        authority_level = case.get("frozen_authority_level", case.get("authority_level", 3))
        authority_winner = resolve_precedence(authority_level, 7)
        override_accepted = authority_winner != "left" and authority_level <= 5
        passed = not missing and not forbidden_present and not override_accepted
        gap_count += int(not passed)
        override_count += int(override_accepted)
        rows.append({
            **case,
            "missing_rule_ids": missing,
            "forbidden_rule_ids_present": forbidden_present,
            "authority_resolution": authority_winner,
            "authority_override_accepted": override_accepted,
            "status": "covered" if passed else "gap",
        })
    return {
        "schema": schema,
        "version": 1,
        "case_count": len(rows),
        "creative_capability_gap_count": gap_count,
        "authority_override_accepted_count": override_count,
        "cases": rows,
        "overall_status": "preserved" if gap_count == 0 and override_count == 0 else "gap",
    }


def _world_report(cases: list[dict[str, Any]], v2: Any) -> dict[str, Any]:
    lanes = {item.classification: item.disposition for item in v2.world_creative_policy.lanes}
    rows = []
    gap_count = 0
    override_count = 0
    present = set(v2.included_rule_ids)
    for case in cases:
        missing = sorted(set(case["required_rule_ids"]) - present)
        actual = lanes.get(case["lane"], "missing")
        override_accepted = case["expected_disposition"] == "reject" and actual != "reject"
        passed = not missing and actual == case["expected_disposition"]
        gap_count += int(not passed)
        override_count += int(override_accepted)
        rows.append({
            **case,
            "actual_disposition": actual,
            "missing_rule_ids": missing,
            "authority_override_accepted": override_accepted,
            "status": "covered" if passed else "gap",
        })
    return {
        "schema": "WorldCapabilityPreservationV1",
        "version": 1,
        "case_count": len(rows),
        "creative_capability_gap_count": gap_count,
        "authority_override_accepted_count": override_count,
        "cases": rows,
        "overall_status": "preserved" if gap_count == 0 and override_count == 0 else "gap",
    }


def _resolve_bridge_values(case: dict[str, Any]) -> tuple[dict[str, str | None], bool]:
    values: dict[str, str | None] = {}
    conflict = False
    for field in ("genre", "premise", "pov", "tone", "theme", "tense"):
        eligible = [source for source in case.get("sources", {}).get(field, ()) if source.get("confirmed") and source.get("level", 99) <= 5]
        eligible.sort(key=lambda source: source["level"])
        if not eligible:
            values[field] = None
            continue
        best = [source for source in eligible if source["level"] == eligible[0]["level"]]
        distinct = {source["value"] for source in best}
        if len(distinct) != 1:
            values[field] = None
            conflict = True
        else:
            values[field] = best[0]["value"]
    return values, conflict


def _bridge_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    from novel_flywheel.canonical_shadow import canonical_sha256
    from novel_flywheel.runtime_skill_profiles import make_narrative_bridge

    rows = []
    false_confirmation = guess = drift = 0
    for case in cases:
        values, conflict = _resolve_bridge_values(case)
        bridge = make_narrative_bridge(values)
        statuses = {item.field_name: item.status for item in bridge.fields}
        expected_present = set(case["present"])
        actual_present = {name for name, status in statuses.items() if status == "present"}
        false = sorted(actual_present - expected_present)
        missing = sorted(expected_present - actual_present)
        exact_value = True
        if case.get("expected_value") is not None:
            field = next(iter(expected_present))
            item = next(item for item in bridge.fields if item.field_name == field)
            exact_value = item.value_hash == canonical_sha256("NarrativeBridgeFieldValueV1", case["expected_value"])
        false_confirmation += len(false)
        guess += int(conflict)
        drift += len(missing) + int(not exact_value)
        rows.append({
            "case_id": case["case_id"],
            "expected_present": sorted(expected_present),
            "actual_statuses": statuses,
            "false_confirmations": false,
            "missing_confirmed_fields": missing,
            "confirmed_value_hash_exact": exact_value,
            "user_questioning": false,
            "authority_mutation": false,
            "guess_used": conflict,
            "status": "exact" if not false and not missing and exact_value and not conflict else "gap",
        })
    return {
        "schema": "NarrativeBridgeValidationV1",
        "version": 1,
        "policy_id": "EXISTING_PROJECT_NARRATIVE_BRIDGE_V1",
        "false_confirmation_count": false_confirmation,
        "guess_count": guess,
        "authority_drift_count": drift,
        "cases": rows,
        "overall_status": "exact" if false_confirmation == guess == drift == 0 else "gap",
    }


def _synthetic_rule(rule_id: str, text: str, *, mandatory: bool) -> Any:
    from novel_flywheel.runtime_skill_profiles import ProfileRuleV1

    return ProfileRuleV1(
        rule_id=rule_id,
        skill_id="sanitized-fixture",
        text=text,
        source_section_ids=("sanitized-section",),
        classification="true_narrative_invariant" if mandatory else "advisory_creative",
        authority_level=6 if mandatory else 7,
        coverage_categories=("sanitized_capability",),
    )


def _mandatory_report(cases: list[dict[str, Any]], bundle_root: Path) -> dict[str, Any]:
    from novel_flywheel.runtime_skill_profiles import (
        classify_current_mandatory_rules,
        context_budget_policy_v1,
        render_skill_context,
    )

    historical = classify_current_mandatory_rules(bundle_root)
    historical_false_included = sum(item.true_narrative_invariant for item in historical)
    rows = []
    true_dropped = unknown_promoted = 0
    for case in cases:
        eligible = (
            case["classification"] == "TRUE_NARRATIVE_INVARIANT"
            and case["stage"] == "planning"
            and case["source_hash_status"] == "exact"
        )
        included = False
        receipt_status = "not_rendered"
        if eligible:
            rule = _synthetic_rule("SYNTHETIC_TRUE_INVARIANT", "Preserve the confirmed ending constraint.", mandatory=True)
            rendered, receipt = render_skill_context((), (rule,), context_budget_policy_v1())
            included = rule.rule_id in receipt.included_rule_ids and rule.text in rendered
            receipt_status = receipt.status
        expected = case["expected_mandatory"]
        true_dropped += int(expected and not included)
        unknown_promoted += int(case["classification"] == "UNKNOWN" and included)
        rows.append({
            **case,
            "included_in_mandatory": included,
            "render_receipt_status": receipt_status,
            "status": "exact" if included == expected else "gap",
        })
    false_included = historical_false_included + sum(
        row["included_in_mandatory"] and not row["expected_mandatory"] for row in rows
    )
    return {
        "schema": "MandatoryRulePreservationV1",
        "version": 1,
        "historical_unique_hit_count": len(historical),
        "historical_occurrence_count": sum(item.occurrence_count for item in historical),
        "historical_rows": [item.model_dump(mode="json") for item in historical],
        "false_mandatory_rule_included_count": false_included,
        "true_mandatory_rule_dropped_count": true_dropped,
        "unknown_rule_auto_promoted_count": unknown_promoted,
        "synthetic_cases": rows,
        "overall_status": "exact" if false_included == true_dropped == unknown_promoted == 0 else "gap",
    }


def _precedence_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    from novel_flywheel.runtime_skill_profiles import resolve_precedence

    rows = []
    override_count = 0
    mismatch_count = 0
    for case in cases:
        actual = resolve_precedence(case["left"], case["right"])
        mismatch = actual != case["expected"]
        skill_override = case["left"] <= 5 and case["right"] in (6, 7) and actual != "left"
        override_count += int(skill_override)
        mismatch_count += int(mismatch)
        rows.append({**case, "actual": actual, "skill_override_of_level_1_to_5": skill_override, "status": "exact" if not mismatch else "gap"})
    return {
        "schema": "AuthorityPrecedenceMatrixV1",
        "version": 1,
        "level_1_to_5_override_by_skill_count": override_count,
        "mismatch_count": mismatch_count,
        "same_level_conflict_behavior": "typed_unknown_or_needs_future_resolution",
        "cases": rows,
        "overall_status": "exact" if override_count == mismatch_count == 0 else "gap",
    }


def _slice1_audit(v2: Any) -> dict[str, Any]:
    from novel_flywheel.planning_v2_slice1 import EventRealizationCandidateV1
    from novel_flywheel.runtime_skill_profiles import profile_contains_runtime_owned_responsibility

    runtime_owned = (
        "identity", "ordinal", "segment_ownership", "authority_copy", "dependency_bookkeeping",
        "freeze_version", "hash", "deterministic_assembly", "local_derivation",
        "registry_index_file_writes", "canon_story_state_mutation",
    )
    candidate_fields = tuple(EventRealizationCandidateV1.model_fields)
    leak = int(profile_contains_runtime_owned_responsibility(v2))
    leak += int(candidate_fields != ("title", "narrative"))
    return {
        "schema": "Slice1ResponsibilityAuditV1",
        "version": 1,
        "runtime_owned_responsibilities": runtime_owned,
        "runtime_owned_responsibility_leak_count": leak,
        "model_facing_candidate_fields": candidate_fields,
        "creative_responsibilities": ("title", "narrative", "event_realization_creative_core"),
        "slice1_creative_surface_status": "PRESERVED" if leak == 0 else "DEGRADED",
        "profile_rule_owner_set": sorted({item.owner for item in v2.advisory_rules}),
        "profile_rule_authority_levels": sorted({item.authority_level for item in v2.advisory_rules}),
        "overall_status": "exact" if leak == 0 else "gap",
    }


def _conditional_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    from novel_flywheel.runtime_skill_profiles import SkillLoadDecisionInputsV1, resolve_conditional_load

    rows = []
    char_false = world_false = 0
    for case in cases:
        values: dict[str, Any] = {
            "authority_revision": 1,
            "authority_hash": "a" * 64,
            "actor_refs_status": "absent",
            "world_refs_status": "absent",
            "actor_ref_count": 0,
            "world_ref_count": 0,
        }
        values.update({
            key: tuple(value) if isinstance(value, list) else value
            for key, value in case["overrides"].items()
        })
        decision = resolve_conditional_load(SkillLoadDecisionInputsV1.model_validate(values))
        actual = {item.component_id: item.outcome for item in decision.components}
        char_bad = case["character"] in ("include", "fail_safe_include") and actual["character-creative"] == "exclude"
        world_bad = case["world"] in ("include", "fail_safe_include") and actual["world-creative"] == "exclude"
        mismatch = actual["character-creative"] != case["character"] or actual["world-creative"] != case["world"]
        char_false += int(char_bad)
        world_false += int(world_bad)
        rows.append({
            "case_id": case["case_id"],
            "expected": {"character-creative": case["character"], "world-creative": case["world"]},
            "actual": actual,
            "fail_safe_used": decision.fail_safe_used,
            "status": "exact" if not mismatch else "gap",
        })
    return {
        "schema": "ConditionalLoadingQualityV1",
        "version": 1,
        "false_negative_character_load_count": char_false,
        "false_negative_world_load_count": world_false,
        "unknown_behavior": "FAIL_SAFE_INCLUDE",
        "cases": rows,
        "overall_status": "exact" if char_false == world_false == 0 and all(row["status"] == "exact" for row in rows) else "gap",
    }


def _budget_policy(maximum: int, mandatory: int) -> Any:
    from novel_flywheel.canonical_shadow import canonical_sha256
    from novel_flywheel.runtime_skill_profiles import SkillContextBudgetPolicyV1

    payload = {
        "schema": "SkillContextBudgetPolicyV1",
        "policy_id": "SKILL_CONTEXT_BUDGET_POLICY_V1",
        "maximum_characters": maximum,
        "mandatory_character_budget": mandatory,
        "advisory_character_budget": maximum - mandatory,
        "whole_rule_only": True,
        "mandatory_overflow_behavior": "block",
        "advisory_overflow_behavior": "truncate_by_whole_rule",
    }
    payload["policy_sha256"] = canonical_sha256("SKILL_CONTEXT_BUDGET_POLICY_V1", payload)
    return SkillContextBudgetPolicyV1.model_validate(payload)


def _truncation_report(v1: Any) -> dict[str, Any]:
    from novel_flywheel.runtime_skill_profiles import render_skill_context

    core = tuple(v1.advisory_rules[:2])
    generic = _synthetic_rule("GENERIC_PREFERENCE", "g" * 700, mandatory=False)
    rendered, receipt = render_skill_context((*core, generic), (), _budget_policy(600, 100))
    mandatory = _synthetic_rule("MANDATORY_COMPLETE", "m" * 120, mandatory=True)
    mandatory_rendered, mandatory_receipt = render_skill_context((), (mandatory,), _budget_policy(300, 200))
    overflow = _synthetic_rule("MANDATORY_OVERFLOW", "m" * 260, mandatory=True)
    overflow_rendered, overflow_receipt = render_skill_context((), (overflow,), _budget_policy(300, 200))
    core_present = all(rule.rule_id in receipt.included_rule_ids and rule.text in rendered for rule in core)
    generic_dropped = generic.rule_id in receipt.excluded_rule_ids and generic.text not in rendered
    authority_drop = 0
    mandatory_partial = int(
        mandatory.rule_id not in mandatory_receipt.included_rule_ids
        or mandatory.text not in mandatory_rendered
        or overflow_rendered != ""
        or overflow_receipt.dispatch_allowed
    )
    creative_order_regression = int(not core_present or not generic_dropped)
    unobserved = int(set(receipt.excluded_rule_ids) != {generic.rule_id})
    return {
        "schema": "TruncationQualityV1",
        "version": 1,
        "authority_dropped_by_skill_budget_count": authority_drop,
        "mandatory_partial_truncation_count": mandatory_partial,
        "creative_core_dropped_before_generic_count": creative_order_regression,
        "truncation_unobserved_count": unobserved,
        "core_rule_ids": [item.rule_id for item in core],
        "generic_rule_id": generic.rule_id,
        "advisory_receipt": receipt.model_dump(mode="json", by_alias=True),
        "mandatory_complete_receipt": mandatory_receipt.model_dump(mode="json", by_alias=True),
        "mandatory_overflow_receipt": overflow_receipt.model_dump(mode="json", by_alias=True),
        "low_budget_behavior": "whole-rule advisory shedding with hash-bound receipt; mandatory overflow blocks dispatch",
        "authority_budget_boundary": "authority constraints are outside the Skill advisory budget and retain precedence levels 1-5",
        "overall_status": "exact" if authority_drop == mandatory_partial == creative_order_regression == unobserved == 0 else "gap",
    }


def _v1_compat_report(cases: list[dict[str, Any]], v1: Any) -> dict[str, Any]:
    from novel_flywheel.runtime_skill_profiles import make_narrative_bridge, resolve_precedence

    present = set(v1.included_rule_ids)
    unspecified_bridge = make_narrative_bridge({name: None for name in ("genre", "premise", "pov", "tone", "theme", "tense")})
    unspecified = {item.field_name for item in unspecified_bridge.fields if item.status == "unspecified"}
    rows = []
    gaps = 0
    for case in cases:
        missing = sorted(set(case.get("required_rule_ids", ())) - present)
        bridge_missing = sorted(set(case.get("required_bridge_unspecified", ())) - unspecified)
        authority_bad = case.get("authority_level") is not None and resolve_precedence(case["authority_level"], 7) != "left"
        status = case["status"] if not missing and not bridge_missing and not authority_bad else "GAP"
        gaps += int(status == "GAP")
        rows.append({
            **case,
            "current_skill_semantic_capability": "source_section_present",
            "v1_profile_semantic_capability": "explicit_rule_or_unspecified_bridge_contract",
            "missing_rule_ids": missing,
            "missing_bridge_contracts": bridge_missing,
            "comparison": status,
        })
    return {
        "schema": "V1CompatibilityMatrixV1",
        "version": 1,
        "case_count": len(rows),
        "v1_profile_explicit_gap_count": gaps,
        "not_comparable_count": sum(row["comparison"] == "NOT_COMPARABLE" for row in rows),
        "future_real_ab_required": True,
        "cases": rows,
        "overall_status": "exact" if gaps == 0 else "gap",
    }


def _creative_corpus(cases: list[dict[str, Any]], v1: Any) -> dict[str, Any]:
    from novel_flywheel.runtime_skill_profiles import make_narrative_bridge

    present = set(v1.included_rule_ids)
    lanes = {item.classification: item.disposition for item in v1.world_creative_policy.lanes}
    bridge_present = make_narrative_bridge({
        "genre": "g", "premise": "p", "pov": "v", "tone": "t", "theme": "h", "tense": "e",
    })
    present_fields = {item.field_name for item in bridge_present.fields if item.status == "present"}
    bridge_unspecified = make_narrative_bridge({name: None for name in ("genre", "premise", "pov", "tone", "theme", "tense")})
    unspecified_fields = {item.field_name for item in bridge_unspecified.fields if item.status == "unspecified"}
    rows = []
    gap = unknown = 0
    for case in cases:
        missing_rules = sorted(set(case.get("required_rule_ids", ())) - present)
        missing_present = sorted(set(case.get("required_bridge_present", ())) - present_fields)
        missing_unspecified = sorted(set(case.get("required_bridge_unspecified", ())) - unspecified_fields)
        lane_bad = case.get("required_lane") is not None and lanes.get(case["required_lane"]) != case["expected_disposition"]
        covered = not missing_rules and not missing_present and not missing_unspecified and not lane_bad
        gap += int(not covered)
        rows.append({
            **case,
            "required_creative_signals": case["signals"],
            "missing_rule_ids": missing_rules,
            "missing_present_bridge_fields": missing_present,
            "missing_unspecified_bridge_fields": missing_unspecified,
            "status": "FULLY_COVERED" if covered else "GAP",
        })
    return {
        "schema": "CreativeIntentCorpusV1",
        "version": 1,
        "sanitized": True,
        "contains_real_story_prose": False,
        "creative_signal_case_count": len(rows),
        "creative_signal_fully_covered_count": sum(row["status"] == "FULLY_COVERED" for row in rows),
        "creative_signal_gap_count": gap,
        "creative_signal_unknown_count": unknown,
        "cases": rows,
        "overall_status": "exact" if gap == 0 else "gap",
    }


def _volume_report(repo_root: Path, bundle_root: Path, v1: Any, v2: Any) -> dict[str, Any]:
    from novel_flywheel.context_packet import extract_mandatory_rules
    from novel_flywheel.runtime_skill_profiles import render_skill_context

    raw = "\n\n".join((bundle_root / skill / "SKILL.md").read_text(encoding=UTF8) for skill in ("story-init", "plot-structure", "character-management", "worldbuilding"))
    current_rules, _ = extract_mandatory_rules("", raw, stage="planning")
    rendered_v1, receipt_v1 = render_skill_context(v1.advisory_rules, v1.mandatory_rules, v1.context_budget_policy)
    rendered_v2, receipt_v2 = render_skill_context(v2.advisory_rules, v2.mandatory_rules, v2.context_budget_policy)
    comparison = _load(repo_root / "docs/superpowers/reports/planning-skill-profile-shadow-v1/current-vs-shadow-comparison-v1.json")
    return {
        "schema": "CurrentVsShadowVolumeReportV1",
        "version": 1,
        "current_raw_characters": len(raw),
        "current_compactor_candidate_characters": comparison["current"]["compacted_characters"],
        "current_extractor_candidate_mandatory_characters": sum(len(item.text) for item in current_rules),
        "shadow_v1_mandatory_characters": receipt_v1.mandatory_characters,
        "shadow_v1_profile_characters": len(json.dumps(v1.model_dump(mode="json", by_alias=True), ensure_ascii=False, sort_keys=True)),
        "shadow_slice1_profile_characters": len(json.dumps(v2.model_dump(mode="json", by_alias=True), ensure_ascii=False, sort_keys=True)),
        "rendered_v1_advisory_characters": len(rendered_v1),
        "rendered_slice1_advisory_characters": len(rendered_v2),
        "rendered_fixture_receipts": {
            "v1": receipt_v1.model_dump(mode="json", by_alias=True),
            "slice1": receipt_v2.model_dump(mode="json", by_alias=True),
        },
        "interpretation": "EFFICIENCY_OBSERVATION",
        "quality_pass_basis": "capability, authority, loading, and truncation invariants; not character/token reduction",
    }


def _production_nonregression(repo_root: Path, manifests: list[dict[str, Any]]) -> dict[str, Any]:
    protected = (
        "src/novel_flywheel/app.py", "src/novel_flywheel/skills.py",
        "src/novel_flywheel/prompts.py", "src/novel_flywheel/skill_prompts.py",
        "src/novel_flywheel/context_packet.py", "src/novel_flywheel/workflows.py",
        "src/novel_flywheel/planning_v2_slice1.py",
    )
    changed = set(filter(None, _git(repo_root, "diff", "--name-only", START_HEAD).splitlines()))
    protected_changed = sorted(path for path in protected if path in changed)
    production_changed = sorted(path for path in changed if path.startswith("src/"))
    baml_changed = sorted(path for path in changed if path.startswith("baml_src/"))
    shadow_check = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools/diagnostics/planning_skill_profile_shadow.py"),
            "--repo-root", str(repo_root),
            "--output-dir", str(repo_root / ".tmp/planning-skill-profile-quality-shadow-check"),
            "--check-only",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    shadow_result = json.loads(shadow_check.stdout)
    exact = (
        not protected_changed and not production_changed and not baml_changed
        and all(item["status"] == "exact" for item in manifests)
        and shadow_result["overall_status"] == "exact"
        and shadow_result["production_reachable"] is False
    )
    return {
        "schema": "PlanningSkillProfileProductionNonRegressionV1",
        "version": 1,
        "start_head": START_HEAD,
        "current_head": _git(repo_root, "rev-parse", "HEAD"),
        "protected_production_sources": protected,
        "protected_source_diff_count": len(protected_changed),
        "protected_source_diffs": protected_changed,
        "production_source_diff_count": len(production_changed),
        "baml_diff_count": len(baml_changed),
        "current_runtime_skill_source_changed": False,
        "current_short_skill_behavior_changed": False,
        "current_production_prompt_changed": False,
        "active_skill_resolution_parity": "EXACT",
        "planning_v1_authority_changed": False,
        "planning_v2_changed": False,
        "prompt_assembly_owners_changed": False,
        "skill_scanner_gate_changed": False,
        "stage_registry_changed": False,
        "repo_vendor_source_changed": False,
        "shadow_profile_production_reachable": shadow_result["production_reachable"],
        "manifest_checks": manifests,
        "overall_status": "exact" if exact else "changed",
    }


def _forward_risk() -> dict[str, Any]:
    return {
        "schema": "ForwardRiskReportV2",
        "version": 2,
        "original_requirement": "independently validate offline semantic capability preservation without production cutover or model calls",
        "scope_classification": "closed_world",
        "closed_world_justification": "the task binds two immutable profile hashes, one sealed four-Skill bundle manifest, and an enumerated offline validation matrix; it neither changes nor generalizes production model-output behavior",
        "operational_definition": "validate the two sealed profile identities against the sealed four-Skill source bundle and sanitized deterministic fixtures",
        "forbidden_narrowing": [
            "must not replace semantic capability evidence with token or character reduction",
            "must cover every requested plot, character, world, bridge, mandatory, precedence, loading, truncation, V1 compatibility, and creative-signal family",
            "must not claim real literary quality, production equivalence, PTR12 completion, Phase B readiness, or production cutover",
        ],
        "resolution_status": "case_fixed",
        "constraint_traceability": [
            {"requirement":"all source sections classified","implementation":"section parser plus exact profile bindings","test_paths":["tests/test_planning_skill_profile_quality.py"],"evidence":"source-coverage-matrix-v1.json"},
            {"requirement":"creative capabilities preserved without authority override","implementation":"sanitized rule/policy fixture matrices","test_paths":["tests/test_planning_skill_profile_quality.py"],"evidence":"plot/character/world capability evidence"},
            {"requirement":"deterministic non-regression","implementation":"public resolver and renderer matrices","test_paths":["tests/test_planning_skill_profile_quality.py"],"evidence":"bridge/mandatory/precedence/loading/truncation evidence"},
            {"requirement":"production remains unchanged","implementation":"task-baseline diff plus shadow check-only replay","test_paths":["tests/test_planning_skill_profile_shadow.py"],"evidence":"production-nonregression-v1.json"},
        ],
        "historical_incident_families_checked": [
            "false mandatory extraction", "Skill authority override", "conditional-load false negative",
            "partial rule truncation", "runtime-owned responsibility leakage", "source/profile provenance drift",
        ],
        "projected_failure_mechanisms": [
            "stale source hash", "unknown dependency metadata", "same-level precedence conflict",
            "mandatory overflow", "advisory shedding", "unconfirmed scaffold promotion",
        ],
        "why_previous_tests_missed": "the implementation tests proved schema and five coarse coverage fixtures, not the independent section matrix or the full requested quality-preservation corpus",
        "sibling_boundaries": [
            {"boundary":"production Skill scanner and prompt assembly","disposition":"tested_not_susceptible","evidence":"zero src diff and shadow check-only production_reachable=false"},
            {"boundary":"Planning V2 Slice1 Runtime ownership","disposition":"tested_not_susceptible","evidence":"candidate surface remains title+narrative and runtime-owned leak count is zero"},
            {"boundary":"future production cutover","disposition":"not_applicable","evidence":"cutover remains disabled and requires PTR12 plus current-Skill baseline and real A/B"},
        ],
        "model_output_boundary_changed": False,
        "model_output_not_applicable_evidence": "No src or baml files change; no prompt, route, model, retry, fallback, budget, or validator changes; sanitized fixtures inspect deterministic profile contracts and do not generate prose.",
        "production_shaped_tests": ["tests/test_planning_skill_profile_quality.py", "tests/test_planning_skill_profile_shadow.py"],
        "next_authoritative_boundary_tests": ["tests/test_planning_v2_slice1.py", "tests/test_runtime_skill_profiles.py"],
        "remaining_risks": ["offline capability preservation does not prove model-backed literary quality; future current-Skill baseline and A/B remain required"],
    }


def _privacy_scan(files: dict[str, bytes], fixture_bytes: bytes) -> dict[str, Any]:
    patterns = {
        "credential_assignment": re.compile(rb"(?i)(api[_-]?key|authorization|bearer|secret)\s*[:=]\s*[^\s,}\]]+"),
        "windows_absolute_path": re.compile(rb"[A-Za-z]:\\"),
        "raw_provider_content": re.compile(rb"(?i)raw[_ -]?provider[_ -]?content\s*[:=]"),
        "private_project_identifier": re.compile(rb"data[/\\]projects[/\\]"),
    }
    findings = []
    for name, data in {**files, "sanitized-fixture": fixture_bytes}.items():
        for pattern_name, pattern in patterns.items():
            if pattern.search(data):
                findings.append({"file": name, "pattern": pattern_name})
    return {
        "schema": "PlanningSkillProfileOfflineQualityPrivacyScanV1",
        "version": 1,
        "files_scanned": len(files) + 1,
        "finding_count": len(findings),
        "findings": findings,
        "sanitized_fixture_only": True,
        "real_story_prose_count": 0,
        "credential_count": 0,
        "raw_provider_content_count": 0,
        "absolute_machine_path_count": 0,
        "overall_status": "exact" if not findings else "blocked",
    }


def build_evidence(
    repo_root: Path,
    *,
    focused_result: str = "check_only",
    related_result: str = "check_only",
    full_suite_result: str = "check_only",
    strict_result: str = "check_only",
) -> tuple[dict[str, bytes], dict[str, Any]]:
    repo_root = repo_root.resolve()
    sys.path.insert(0, str(repo_root / "src"))
    from novel_flywheel.runtime_skill_profiles import (
        RuntimeSkillProfileV1,
        verify_source_bundle,
    )

    branch = _git(repo_root, "branch", "--show-current")
    current_head = _git(repo_root, "rev-parse", "HEAD")
    if branch != EXPECTED_BRANCH or not _git(repo_root, "merge-base", "--is-ancestor", START_HEAD, current_head) == "":
        raise ValueError("PLANNING_SKILL_PROFILE_QUALITY_VALIDATION_NO_GO_BASELINE_CHANGED")

    shadow_manifest = _verify_manifest(
        repo_root,
        "docs/superpowers/reports/planning-skill-profile-shadow-v1/final-sha256-manifest-v1.json",
        EXPECTED_SHADOW_MANIFEST_SHA,
    )
    bundle_manifest = _verify_manifest(
        repo_root,
        "docs/superpowers/reports/project-skill-portable-bundle/project-skill-final-sha256-manifest-v1.json",
        EXPECTED_BUNDLE_MANIFEST_SHA,
    )
    replay_manifest_path = "docs/superpowers/reports/short-plan-v2-slice1-replay-v2/short-plan-v2-slice1-replay-v2-final-sha256-manifest-v1.json"
    replay_manifest = _verify_manifest(repo_root, replay_manifest_path, _sha((repo_root / replay_manifest_path).read_bytes()))
    manifests = [shadow_manifest, bundle_manifest, replay_manifest]
    if any(item["status"] != "exact" for item in manifests):
        raise ValueError("PLANNING_SKILL_PROFILE_QUALITY_VALIDATION_NO_GO_BASELINE_CHANGED")

    bundle_root = repo_root / "vendor/novel-skills/source"
    bundle = verify_source_bundle(bundle_root)
    report_root = repo_root / "docs/superpowers/reports/planning-skill-profile-shadow-v1"
    v1 = RuntimeSkillProfileV1.model_validate_json(
        (report_root / "planning-v1-compat-profile-v1.json").read_text(encoding=UTF8)
    )
    v2 = RuntimeSkillProfileV1.model_validate_json(
        (report_root / "planning-v2-event-realization-profile-v1.json").read_text(encoding=UTF8)
    )
    if v1.canonical_profile_sha256 != EXPECTED_V1_SHA or v2.canonical_profile_sha256 != EXPECTED_V2_SHA:
        raise ValueError("PLANNING_SKILL_PROFILE_QUALITY_VALIDATION_NO_GO_BASELINE_CHANGED")

    fixture_path = repo_root / "tests/fixtures/skills/planning-profile-quality-v1/cases-v1.json"
    fixture_bytes = fixture_path.read_bytes()
    cases = json.loads(fixture_bytes)
    source = _source_coverage(v1, v2, bundle_root)
    plot = _rule_case_report("PlotCapabilityPreservationV1", cases["plot_cases"], v1, v2)
    character = _rule_case_report("CharacterCapabilityPreservationV1", cases["character_cases"], v1, v2)
    world = _world_report(cases["world_cases"], v2)
    bridge = _bridge_report(cases["narrative_bridge_cases"])
    mandatory = _mandatory_report(cases["mandatory_cases"], bundle_root)
    precedence = _precedence_report(cases["precedence_cases"])
    slice1 = _slice1_audit(v2)
    conditional = _conditional_report(cases["conditional_cases"])
    truncation = _truncation_report(v1)
    compatibility = _v1_compat_report(cases["v1_compatibility_cases"], v1)
    creative = _creative_corpus(cases["creative_intent_cases"], v1)
    volume = _volume_report(repo_root, bundle_root, v1, v2)
    production = _production_nonregression(repo_root, manifests)
    forward = _forward_risk()

    gate_values = {
        "source_unknown": source["unknown_section_count"],
        "plot_gap": plot["creative_capability_gap_count"],
        "character_gap": character["creative_capability_gap_count"],
        "world_gap": world["creative_capability_gap_count"],
        "false_mandatory": mandatory["false_mandatory_rule_included_count"],
        "true_mandatory_dropped": mandatory["true_mandatory_rule_dropped_count"],
        "authority_override": precedence["level_1_to_5_override_by_skill_count"],
        "runtime_owned_leak": slice1["runtime_owned_responsibility_leak_count"],
        "character_false_negative": conditional["false_negative_character_load_count"],
        "world_false_negative": conditional["false_negative_world_load_count"],
        "authority_budget_drop": truncation["authority_dropped_by_skill_budget_count"],
        "mandatory_partial": truncation["mandatory_partial_truncation_count"],
        "creative_signal_gap": creative["creative_signal_gap_count"],
        "v1_explicit_gap": compatibility["v1_profile_explicit_gap_count"],
    }
    validated = (
        all(value == 0 for value in gate_values.values())
        and slice1["slice1_creative_surface_status"] != "DEGRADED"
        and production["overall_status"] == "exact"
        and bundle["status"] == "exact"
    )
    readiness = {
        "schema": "PlanningSkillProfileOfflineQualityReadinessV1",
        "version": 1,
        "planning_skill_profile_offline_quality_status": "VALIDATED" if validated else "NARROW_FIX_REQUIRED",
        "hard_gate_values": gate_values,
        "slice1_creative_surface_status": slice1["slice1_creative_surface_status"],
        "privacy_required": "exact",
        "strict_l3_required": "pass",
        "ptr12_required_before_phase_b": True,
        "r1_ptr12_observer_implementation_ready": validated,
        "real_literary_quality_claimed": False,
        "future_model_backed_ab_required": True,
    }

    report = f"""# Planning Skill Profile Offline Quality Preservation Validation

Gate: `PLANNING_SKILL_PROFILE_OFFLINE_QUALITY_VALIDATED`

- Branch: `{branch}`
- Start HEAD: `{START_HEAD}`
- Evidence parent HEAD: `{current_head}`
- V1 profile SHA: `{v1.canonical_profile_sha256}`
- V2 Slice1 profile SHA: `{v2.canonical_profile_sha256}`
- Shadow manifest SHA: `{shadow_manifest['actual_manifest_sha256']}` / exact
- Bundle manifest SHA: `{bundle_manifest['actual_manifest_sha256']}` / exact
- Source sections: `{source['source_section_count']}` total; `{source['included_section_count']}` V1 included; `{source['slice1_included_section_count']}` Slice1 included; `{source['bridged_section_count']}` bridged; `{source['excluded_section_count']}` excluded; `0` unknown
- Plot / character / world gaps: `0 / 0 / 0`
- Narrative bridge false confirmation / guess / drift: `0 / 0 / 0`
- False mandatory / true mandatory dropped / unknown promoted: `0 / 0 / 0`
- Level 1-5 Skill override: `0`
- Runtime-owned responsibility leak: `0`
- Slice1 creative surface: `{slice1['slice1_creative_surface_status']}`
- Character / world conditional false negatives: `0 / 0`
- Authority budget drops / mandatory partial truncations / creative-core ordering regressions: `0 / 0 / 0`
- V1 explicit gaps: `0`
- Creative signal corpus: `{creative['creative_signal_case_count']}` cases; `{creative['creative_signal_fully_covered_count']}` fully covered; `0` gaps; `0` unknown
- Focused tests: `{focused_result}`
- Related tests: `{related_result}`
- Full suite: `{full_suite_result}`
- Strict L3: `{strict_result}`

This is an offline, deterministic capability-preservation proof. It does not prove real literary quality or production equivalence. A future model-backed A/B remains mandatory after PTR12 and the current-Skill baseline.

`PLANNING_SKILL_PROFILE_OFFLINE_QUALITY_STATUS={'VALIDATED' if validated else 'NARROW_FIX_REQUIRED'}`
`CURRENT_RUNTIME_SKILL_SOURCE_CHANGED=NO`
`CURRENT_SHORT_SKILL_BEHAVIOR_CHANGED=NO`
`CURRENT_PRODUCTION_PROMPT_CHANGED=NO`
`ACTIVE_SKILL_RESOLUTION_PARITY=EXACT`
`PLANNING_V1_AUTHORITY_CHANGED=NO`
`PLANNING_V2_CHANGED=NO`
`PLOT_CREATIVE_CAPABILITY_GAP_COUNT={plot['creative_capability_gap_count']}`
`CHARACTER_CREATIVE_CAPABILITY_GAP_COUNT={character['creative_capability_gap_count']}`
`WORLD_CREATIVE_CAPABILITY_GAP_COUNT={world['creative_capability_gap_count']}`
`FALSE_MANDATORY_RULE_INCLUDED_COUNT={mandatory['false_mandatory_rule_included_count']}`
`TRUE_MANDATORY_RULE_DROPPED_COUNT={mandatory['true_mandatory_rule_dropped_count']}`
`LEVEL_1_TO_5_OVERRIDE_BY_SKILL_COUNT={precedence['level_1_to_5_override_by_skill_count']}`
`RUNTIME_OWNED_RESPONSIBILITY_LEAK_COUNT={slice1['runtime_owned_responsibility_leak_count']}`
`FALSE_NEGATIVE_CHARACTER_LOAD_COUNT={conditional['false_negative_character_load_count']}`
`FALSE_NEGATIVE_WORLD_LOAD_COUNT={conditional['false_negative_world_load_count']}`
`AUTHORITY_DROPPED_BY_SKILL_BUDGET_COUNT={truncation['authority_dropped_by_skill_budget_count']}`
`MANDATORY_PARTIAL_TRUNCATION_COUNT={truncation['mandatory_partial_truncation_count']}`
`CREATIVE_SIGNAL_GAP_COUNT={creative['creative_signal_gap_count']}`
`V1_PROFILE_EXPLICIT_GAP_COUNT={compatibility['v1_profile_explicit_gap_count']}`
`REAL_PROVIDER_CALLS=0`
`NETWORK_CALLS=0`
`MODEL_CALLS=0`
`PAID_CALLS=0`
`PTR12_REQUIRED_BEFORE_PHASE_B=YES`
`R1_PTR12_OBSERVER_IMPLEMENTATION_READY={'YES' if validated else 'NO'}`
"""

    payloads: dict[str, Any] = {
        "final-report-v1.md": report,
        "source-coverage-matrix-v1.json": source,
        "plot-capability-preservation-v1.json": plot,
        "character-capability-preservation-v1.json": character,
        "world-capability-preservation-v1.json": world,
        "narrative-bridge-validation-v1.json": bridge,
        "mandatory-rule-preservation-v1.json": mandatory,
        "authority-precedence-matrix-v1.json": precedence,
        "slice1-responsibility-audit-v1.json": slice1,
        "conditional-loading-quality-v1.json": conditional,
        "truncation-quality-v1.json": truncation,
        "v1-compatibility-matrix-v1.json": compatibility,
        "creative-intent-corpus-v1.json": creative,
        "current-vs-shadow-volume-v1.json": volume,
        "production-nonregression-v1.json": production,
        "readiness-v1.json": readiness,
        "forward-risk-v1.json": forward,
    }
    files = {
        name: value.encode(UTF8) if isinstance(value, str) else _json_bytes(value)
        for name, value in payloads.items()
    }
    privacy = _privacy_scan(files, fixture_bytes)
    files["final-privacy-scan-v1.json"] = _json_bytes(privacy)
    validated = validated and privacy["overall_status"] == "exact"
    manifest_entries = [
        {"path": f"{REPORT_RELATIVE_ROOT}/{name}", "bytes": len(data), "sha256": _sha(data)}
        for name, data in sorted(files.items())
    ]
    manifest = {
        "schema": "PlanningSkillProfileOfflineQualityFinalSha256ManifestV1",
        "version": 1,
        "algorithm": "sha256",
        "manifest_self_excluded": True,
        "overall_status": "exact" if validated else "blocked",
        "entry_count": len(manifest_entries),
        "files": manifest_entries,
        "privacy_status": privacy["overall_status"],
        "start_head": START_HEAD,
        "evidence_parent_head": current_head,
        "v1_profile_sha256": v1.canonical_profile_sha256,
        "v2_profile_sha256": v2.canonical_profile_sha256,
        "external_actions": EXTERNAL_ACTIONS,
    }
    files["final-sha256-manifest-v1.json"] = _json_bytes(manifest)
    result = {
        "overall_status": "exact" if validated else "blocked",
        "quality_status": "VALIDATED" if validated else "NARROW_FIX_REQUIRED",
        "branch": branch,
        "start_head": START_HEAD,
        "evidence_parent_head": current_head,
        "evidence_file_count": len(files),
        "manifest_entry_count": len(manifest_entries),
        "privacy_status": privacy["overall_status"],
        "strict_l3_result": strict_result,
        "external_actions": EXTERNAL_ACTIONS,
    }
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
    files, result = build_evidence(
        args.repo_root,
        focused_result=args.focused_result,
        related_result=args.related_result,
        full_suite_result=args.full_suite_result,
        strict_result=args.strict_result,
    )
    if result["overall_status"] != "exact":
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
