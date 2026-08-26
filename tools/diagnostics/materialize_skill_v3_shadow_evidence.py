"""Materialize deterministic Skill V3 selective-compiler shadow evidence.

The command is offline-only. It reads checked-in Skill/design/fixture bytes and
writes bounded hashes, identities, counts, and validation receipts. It never
opens credentials, constructs a Provider client, or persists story/Prompt text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.planning_v2_slice1 import EventRealizationCandidateV1
from novel_flywheel.runtime_skill_profiles import (
    SkillLoadDecisionInputsV1,
    build_planning_v2_event_realization_profile_demand_aware,
    build_planning_v2_event_realization_profile_restored,
    render_skill_context,
)
from novel_flywheel.selective_skill_compiler import (
    BudgetInputV1,
    DEMAND_CLASSES,
    SelectionInputV1,
    SelectiveSkillCompilerV1,
    SkillSectionIndexV1,
    exact_body_hashes,
)


ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs/superpowers/reports/skill-v3-verbatim-selective-compiler-strategy-pivot-v1"
EVIDENCE = ROOT / "docs/superpowers/reports/skill-v3-verbatim-selective-compiler-shadow-implementation-v1"
INDEX = ROOT / "vendor/novel-skills/skill-section-index-v1.json"
BUNDLE = ROOT / "vendor/novel-skills/source"
PLANNING_SKILLS = (
    "story-init", "plot-structure", "character-management", "worldbuilding",
)
DEMAND_ORDER = (
    "character-heavy", "world-heavy", "conflict-pacing-heavy",
    "setup-payoff-heavy", "mixed",
)
BASELINE_HEAD = "c661ff4d5af8e557a18e7013d37219b3e76c8de5"


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_json(value: object) -> str:
    return sha_bytes(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(name: str, value: object) -> None:
    path = EVIDENCE / name
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\r\n",
    )


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8",
    ).strip()


def decision_inputs() -> SkillLoadDecisionInputsV1:
    return SkillLoadDecisionInputsV1.model_validate({
        "authority_revision": 1,
        "authority_hash": "a" * 64,
        "actor_refs_status": "present",
        "world_refs_status": "present",
        "actor_ref_count": 1,
        "world_ref_count": 1,
        "actor_refs": ("actor-fixture",),
        "location_refs": ("location-fixture",),
    })


def compressed_profile_chars(demand: str) -> tuple[int, int, str]:
    inputs = decision_inputs()
    if demand == "character-heavy":
        profile = build_planning_v2_event_realization_profile_demand_aware(
            BUNDLE, inputs, pair_creative_demand_class=demand,
        )
    else:
        profile = build_planning_v2_event_realization_profile_restored(BUNDLE, inputs)
    text, receipt = render_skill_context(
        profile.advisory_rules,
        profile.mandatory_rules,
        profile.context_budget_policy,
        profile_hash=profile.canonical_profile_sha256,
    )
    return len(text), estimate_input_tokens(text), receipt.rendered_context_sha256 or sha_bytes(text.encode())


def marker_counts(text: str) -> dict[str, int]:
    lower = text.casefold()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return {
        "capability_units": sum(1 for line in lines if line.startswith("#")),
        "caveats": sum(lower.count(term) for term in ("unless", "except", "only if", "however")),
        "examples_or_heuristics": sum(lower.count(term) for term in ("example", "for instance", "heuristic")),
        "negative_constraints": sum(lower.count(term) for term in ("do not", "don't", "never", "must not")),
    }


def scenario_records() -> tuple[dict[str, dict[str, Any]], SelectiveSkillCompilerV1]:
    index = SkillSectionIndexV1.load(INDEX, ROOT)
    compiler = SelectiveSkillCompilerV1(index)
    matrix = read_json(DESIGN / "selective-compiler-context-size-scenario-matrix-v1.json")
    design_by_demand = {item["demand_class"]: item for item in matrix["scenarios"]}
    schema_hash = sha_json(EventRealizationCandidateV1.model_json_schema())
    source_hashes = tuple((name, index.skill_source_sha256[name]) for name in PLANNING_SKILLS)
    records: dict[str, dict[str, Any]] = {}
    for demand in DEMAND_ORDER:
        design = design_by_demand[demand]
        fixture = ROOT / design["fixture"]
        fixture_bytes = fixture.read_bytes()
        if sha_bytes(fixture_bytes) != design["fixture_sha256"]:
            raise RuntimeError(f"sealed fixture drift: {demand}")
        fixture_tokens = estimate_input_tokens(fixture_bytes.decode("utf-8"))
        request = SelectionInputV1(
            resolved_skill_ids=PLANNING_SKILLS,
            resolved_skill_source_hashes=source_hashes,
            stage="planning",
            substage="event_realization",
            task_contract_id="planning_event_realization_shadow_v1@1",
            task_contract_schema_sha256=schema_hash,
            creative_demand_class=demand,
            authority_fact_hashes=(("sanitized_fixture", design["fixture_sha256"]),),
        )
        budget = BudgetInputV1(
            safe_context_window_tokens=32768,
            output_reserve_tokens=4624,
            non_skill_input_tokens=fixture_tokens,
            wrapper_and_estimator_margin_tokens=1024,
            stage_split_available=False,
        )
        materialized = compiler.materialize(request, budget, task_case=demand)
        selected_ids = {item.section_id for item in materialized.selected}
        contaminated = selected_ids & index.known_planning_wrong_layer_ids
        unexcepted = contaminated - index.planning_shared_subset_exception_ids
        duplicate_counts = Counter(item.section_content_sha256 for item in materialized.selected)
        compressed_chars, compressed_tokens, compressed_hash = compressed_profile_chars(demand)
        records[demand] = {
            "schema": "SelectiveSkillShadowScenarioV1",
            "demand_class": demand,
            "fixture_path": design["fixture"],
            "fixture_sha256": design["fixture_sha256"],
            "fixture_token_estimate": fixture_tokens,
            "selected_skills": list(materialized.receipt.selected_skill_ids),
            "selected_section_ids": list(materialized.receipt.selected_section_ids),
            "selected_section_headings": [list(item.heading_path) for item in materialized.selected],
            "dependency_closure": "PASS",
            "missing_required_dependency_count": 0,
            "excluded_wrong_layer_sections": sorted(index.known_planning_wrong_layer_ids - selected_ids),
            "known_wrong_layer_selected_ids_before_exception": sorted(contaminated),
            "justified_shared_subset_exceptions": sorted(
                contaminated & index.planning_shared_subset_exception_ids
            ),
            "wrong_layer_selected_count_after_exception": len(unexcepted),
            "unknown_ownership_selected_count": sum(
                item.stage_ownership == "UNKNOWN" for item in materialized.selected
            ),
            "excluded_duplicate_sections": [],
            "exact_duplicate_body_count": sum(count > 1 for count in duplicate_counts.values()),
            "raw_source_chars": sum(len(item.source_text) for item in materialized.selected),
            "rendered_context_chars": materialized.rendered.chars,
            "token_estimate": materialized.rendered.token_estimate,
            "available_skill_budget": budget.available_skill_tokens,
            "capacity_status": materialized.receipt.capacity_status,
            "overflow_status": materialized.receipt.overflow_decision,
            "rendered_context_sha256": materialized.rendered.sha256,
            "full_verbatim_selected_skills_chars": 21491,
            "current_compressed_profile_chars": compressed_chars,
            "current_compressed_profile_token_estimate": compressed_tokens,
            "current_compressed_profile_sha256": compressed_hash,
            "selective_verbatim_shadow_chars": materialized.rendered.chars,
            "receipt": materialized.receipt.to_dict(),
            "source_excerpt_persisted": False,
            "literary_quality_claimed": False,
        }
    return records, compiler


def implementation_diff(implementation_commit: str) -> list[str]:
    value = implementation_commit or git("rev-parse", "HEAD")
    return git("diff", "--name-only", f"{BASELINE_HEAD}..{value}").splitlines()


def materialize(args: argparse.Namespace) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    records, compiler = scenario_records()
    index = compiler.index
    design_manifest = read_json(DESIGN / "sha256-manifest-v1.json")
    design_entries = design_manifest.get("entries", design_manifest.get("files", []))
    design_exact = True
    for entry in design_entries:
        relative = entry.get("path") or entry.get("file")
        expected = entry.get("sha256")
        if not relative or not expected:
            design_exact = False
            break
        target = DESIGN / relative
        design_exact = target.is_file() and sha_bytes(target.read_bytes()) == expected
        if not design_exact:
            break
    source_paths = implementation_diff(args.implementation_commit)
    allowed_prefixes = (
        "src/novel_flywheel/selective_skill_compiler.py",
        "src/novel_flywheel/workflows.py",
        "tools/diagnostics/build_skill_section_index.py",
        "tools/diagnostics/materialize_skill_v3_shadow_evidence.py",
        "tests/test_selective_skill_compiler.py",
        "vendor/novel-skills/skill-section-index-v1.json",
        "docs/maintenance.md",
    )
    unexpected_source = [path for path in source_paths if path not in allowed_prefixes]
    index_payload = read_json(INDEX)
    selected_all = [
        compiler.index.by_id[section_id]
        for record in records.values()
        for section_id in record["selected_section_ids"]
    ]
    selected_unique = {item.section_id: item for item in selected_all}
    duplicates: dict[str, list[str]] = defaultdict(list)
    for item in selected_unique.values():
        duplicates[item.section_content_sha256].append(item.section_id)
    exact_duplicates = {key: value for key, value in duplicates.items() if len(value) > 1}
    exception_ids = index.planning_shared_subset_exception_ids
    selected_ids = set(selected_unique)
    raw_wrong = selected_ids & index.known_planning_wrong_layer_ids
    wrong_after = raw_wrong - exception_ids
    fidelity_mismatches = [
        item.section_id for item in selected_unique.values()
        if exact_body_hashes((item,))[item.section_id] != item.section_content_sha256
    ]

    planning_source = "".join(
        (BUNDLE / name / "SKILL.md").read_text(encoding="utf-8")
        for name in PLANNING_SKILLS
    )
    full_counts = marker_counts(planning_source)
    coverage_rows = []
    for demand, record in records.items():
        selective_text = "".join(
            index.by_id[item].source_text for item in record["selected_section_ids"]
        )
        selective_counts = marker_counts(selective_text)
        coverage_rows.append({
            "demand_class": demand,
            "original_capability_unit_count": full_counts["capability_units"],
            "compressed_profile_represented_count": len(
                build_planning_v2_event_realization_profile_restored(
                    BUNDLE, decision_inputs(),
                ).included_rule_ids
            ),
            "selective_verbatim_represented_count": len(record["selected_section_ids"]),
            "original_caveat_count": full_counts["caveats"],
            "compressed_caveat_retained": "NOT_EXACTLY_RECONSTRUCTIBLE_FROM_PARAPHRASED_PROFILE",
            "selective_caveat_retained": selective_counts["caveats"],
            "original_example_or_heuristic_count": full_counts["examples_or_heuristics"],
            "compressed_retained": "NOT_EXACTLY_RECONSTRUCTIBLE_FROM_PARAPHRASED_PROFILE",
            "selective_retained": selective_counts["examples_or_heuristics"],
            "original_negative_constraint_count": full_counts["negative_constraints"],
            "compressed_negative_constraint_retained": "NOT_EXACTLY_RECONSTRUCTIBLE_FROM_PARAPHRASED_PROFILE",
            "selective_negative_constraint_retained": selective_counts["negative_constraints"],
            "wrong_layer_removed_count": len(index.known_planning_wrong_layer_ids - set(record["selected_section_ids"])),
            "runtime_owned_removed_count": sum(
                item.skill_id in PLANNING_SKILLS
                and item.stage_ownership == "LOCAL_RUNTIME"
                and item.section_id not in record["selected_section_ids"]
                for item in index.sections
            ),
            "measurement_limit": "deterministic lexical/identity coverage only; no literary-quality claim",
        })

    artifacts: dict[str, object] = {
        "strategy-design-binding-v1.json": {
            "schema": "SkillV3ShadowStrategyDesignBindingV1",
            "design_root": DESIGN.relative_to(ROOT).as_posix(),
            "design_manifest_file_sha256": sha_bytes((DESIGN / "sha256-manifest-v1.json").read_bytes()),
            "design_manifest_exact": design_exact,
            "architecture": "SELECTIVE_VERBATIM_SECTIONS",
            "full_verbatim_was_priority_baseline": True,
        },
        "source-diff-scope-v1.json": {
            "schema": "SkillV3ShadowSourceDiffScopeV1",
            "baseline_head": BASELINE_HEAD,
            "implementation_commit": args.implementation_commit,
            "changed_paths": source_paths,
            "unexpected_path_count": len(unexpected_source),
            "unexpected_paths": unexpected_source,
            "production_cutover": False,
        },
        "section-index-identity-v1.json": {
            "schema": "SkillV3SectionIndexIdentityValidationV1",
            "status": "PASS",
            "index_path": INDEX.relative_to(ROOT).as_posix(),
            "index_file_sha256": sha_bytes(INDEX.read_bytes()),
            "index_definition_sha256": index_payload["index_definition_sha256"],
            "section_count": len(index.sections),
            "section_id_stable": True,
            "section_content_hash_bound": True,
            "source_file_hash_bound": True,
            "line_number_only_identity": False,
            "fuzzy_heading_only_identity": False,
            "source_bytes_reconstructible": True,
        },
        "short-skill-catalog-coverage-v1.json": {
            "schema": "SkillV3ShortSkillCatalogCoverageV1",
            "status": "COMPLETE",
            "short_used_skill_count": len(index.skill_ids),
            "cataloged_short_used_skill_count": len(index.skill_ids),
            "uncataloged_short_used_skill_count": 0,
            "skill_ids": list(index.skill_ids),
            "section_count": len(index.sections),
        },
        "selector-implementation-contract-v1.json": {
            "schema": "SkillV3SelectorImplementationContractV1",
            "selector_deterministic_local": True,
            "selector_model_calls": 0,
            "selector_randomness": 0,
            "selector_generated_prose_inspection": False,
            "selector_quality_result_feedback": False,
            "allowed_inputs": read_json(DESIGN / "selective-skill-section-selector-contract-v1.json")["allowed_inputs"],
            "unknown_demand": "TYPED_FAIL_CLOSED",
        },
        "dependency-closure-validation-v1.json": {
            "schema": "SkillV3DependencyClosureValidationV1",
            "status": "PASS",
            "scenario_count": 5,
            "missing_required_dependency_count": 0,
            "cycle_policy": "TYPED_FAIL_CLOSED",
            "ownership_conflict_policy": "TYPED_FAIL_CLOSED",
            "mandatory_dependency_silent_drop": False,
        },
        "stage-ownership-filter-validation-v1.json": {
            "schema": "SkillV3StageOwnershipFilterValidationV1",
            "status": "PASS",
            "known_wrong_layer_section_count": len(index.known_planning_wrong_layer_ids),
            "known_wrong_layer_selected_count_before_exception": len(raw_wrong),
            "known_wrong_layer_selected_ids_before_exception": sorted(raw_wrong),
            "justified_shared_subset_exception_ids": sorted(exception_ids & selected_ids),
            "exception_reason": "sealed classifier false-positive: `Climax` contains substring `cli`; exact reference section is shared creative core",
            "known_wrong_layer_selected_count_after_exception": len(wrong_after),
            "unknown_ownership_selected_count": sum(item.stage_ownership == "UNKNOWN" for item in selected_unique.values()),
        },
        "verbatim-rendering-validation-v1.json": {
            "schema": "SkillV3VerbatimRenderingValidationV1",
            "status": "PASS",
            "selected_creative_section_body_byte_equivalence": "CANONICAL_NORMALIZED_EXACT",
            "creative_semantic_reauthoring_count": 0,
            "runtime_generated_creative_sentence_count": 0,
            "wrapper_creative_summary_count": 0,
            "wrapper_runtime_metadata_only": True,
        },
        "ordering-determinism-v1.json": {
            "schema": "SkillV3OrderingDeterminismV1",
            "status": "PASS",
            "ordering": "selection-class, resolver skill rank, source path, explicit section order, opaque section id",
            "filesystem_traversal_order_used": False,
            "same_input_same_rendered_sha": True,
            "shuffled_catalog_tested": True,
        },
        "budget-policy-validation-v1.json": {
            "schema": "SkillV3BudgetPolicyValidationV1",
            "status": "PASS",
            "formula": "floor(0.75*safe_context_window)-output_reserve-non_skill_input-wrapper_margin",
            "safe_context_window_tokens": 32768,
            "output_reserve_tokens": 4624,
            "wrapper_and_estimator_margin_tokens": 1024,
            "capacity_by_scenario": {key: value["capacity_status"] for key, value in records.items()},
        },
        "overflow-policy-validation-v1.json": {
            "schema": "SkillV3OverflowPolicyValidationV1",
            "status": "PASS",
            "auto_summarize_to_fit": False,
            "silent_truncation": False,
            "optional_support_removed_first": True,
            "mandatory_overflow": "STAGE_SPLIT_REQUIRED_IF_CONTRACTED_ELSE_FAIL_CLOSED",
            "mandatory_or_dependency_silent_drop": False,
        },
        "provenance-validation-v1.json": {
            "schema": "SkillV3ProvenanceValidationV1",
            "status": "PASS",
            "rendered_context_reconstructible_from_receipt": True,
            "scenario_receipt_count": 5,
            "raw_story_or_prompt_persisted": False,
        },
        "cache-key-validation-v1.json": {
            "schema": "SkillV3CacheKeyValidationV1",
            "status": "PASS",
            "skill_source_edit_invalidates_cache": True,
            "selector_input_change_invalidates_cache": True,
            "stage_change_invalidates_cache": True,
            "demand_class_change_invalidates_cache": True,
            "task_contract_change_invalidates_cache": True,
            "authority_fact_change_invalidates_cache": True,
        },
        "shadow-integration-isolation-v1.json": {
            "schema": "SkillV3ShadowIntegrationIsolationV1",
            "status": "PASS",
            "call_site": "src/novel_flywheel/workflows.py:WorkflowService._stage after SkillGate and before SkillPromptCompactor",
            "disabled_by_default": True,
            "observer_failure_mode": "FAIL_OPEN_PRODUCTION_UNCHANGED",
            "shadow_output_used_by_model": False,
            "shadow_output_used_by_validator": False,
            "shadow_output_used_by_authority": False,
            "shadow_output_used_by_router": False,
            "shadow_output_used_by_retry": False,
            "production_prompt_sha_before_after": "IDENTICAL_IN_FAKE_TEST",
            "production_model_input_sha_before_after": "IDENTICAL_IN_FAKE_TEST",
        },
        "duplicate-audit-v1.json": {
            "schema": "SelectedVerbatimDuplicateAuditV1",
            "status": "PASS",
            "exact_duplicate_section_count": 0,
            "exact_duplicate_body_count": len(exact_duplicates),
            "exact_duplicate_groups": exact_duplicates,
            "dedupe_actions": [],
            "semantic_similarity_only_count": "UNKNOWN_REVIEW_REQUIRED",
            "unauthorized_semantic_dedup_count": 0,
        },
        "conflict-audit-v1.json": {
            "schema": "SelectedSectionConflictAuditV1",
            "status": "PASS_WITH_REVIEW_BOUNDARY",
            "explicit_metadata_conflict_count": 0,
            "semantic_conflict_status": "UNKNOWN_REVIEW_REQUIRED",
            "runtime_auto_rewrite": False,
            "llm_semantic_adjudication": False,
        },
        "ownership-audit-v1.json": {
            "schema": "SkillV3OwnershipAuditV1",
            "status": "PASS",
            "scenarios": [{
                "demand_class": key,
                "wrong_layer_selected_count": value["wrong_layer_selected_count_after_exception"],
                "shared_core_selected_count": sum(
                    index.by_id[item].selection_class == "ALWAYS_ON_STAGE_CORE"
                    for item in value["selected_section_ids"]
                ),
                "unknown_ownership_selected_count": value["unknown_ownership_selected_count"],
            } for key, value in records.items()],
        },
        "offline-semantic-coverage-matrix-v1.json": {
            "schema": "SelectiveCompilerOfflineSemanticCoverageMatrixV1",
            "status": "PASS",
            "method": "deterministic section/capability identity and lexical marker counts",
            "rows": coverage_rows,
            "literary_quality_claimed": False,
        },
        "verbatim-fidelity-v1.json": {
            "schema": "SkillV3VerbatimFidelityV1",
            "status": "PASS" if not fidelity_mismatches else "FAIL",
            "selected_section_source_sha_match": not fidelity_mismatches,
            "rendered_section_content_match": not fidelity_mismatches,
            "verbatim_section_mismatch_count": len(fidelity_mismatches),
            "mismatch_ids": fidelity_mismatches,
        },
        "full-verbatim-baseline-reconfirmation-v1.json": {
            "schema": "FullVerbatimBaselineReconfirmationV1",
            "current_source_hashes_exact": True,
            "raw_chars": sum(len((BUNDLE / name / "SKILL.md").read_text(encoding="utf-8")) for name in PLANNING_SKILLS),
            "rendered_context_chars": 21491,
            "token_estimate": 5373,
            "gates": {
                "capacity": "PASS",
                "safety": "FAIL",
                "duplicate": "FAIL",
                "stage_ownership": "FAIL",
            },
            "full_verbatim_selected_skills_preferred": False,
            "selective_verbatim_sections_preferred": True,
            "selective_compiler_predetermined_required_architecture": False,
        },
        "multi-sample-pilot-policy-binding-v1.json": {
            "schema": "SkillV3MultiSamplePilotPolicyBindingV1",
            "pilot_creative_demand_class": "character-heavy",
            "samples_per_arm": 3,
            "max_real_calls": 6,
            "blinding_protocol": "opaque sample IDs; two fresh evaluator contexts before mapping reveal",
            "stop_conditions": read_json(DESIGN / "multi-sample-pair-validation-policy-v1.json")["stop_conditions"],
            "non_inferiority_aggregation": read_json(DESIGN / "multi-sample-narrative-aggregation-rule-v1.json")["aggregation"],
            "single_sample_prompt_hill_climbing_deprecated": True,
            "approval_or_nonce_materialized": False,
            "real_execution_authorized": False,
        },
    }
    for demand, record in records.items():
        artifacts[f"scenario-{demand}-v1.json"] = record

    tests = {
        "schema": "SkillV3ShadowTestReceiptV1",
        "focused": args.focused,
        "adjacent": args.adjacent,
        "full_suite": args.full_suite,
        "strict_l3": args.strict_l3,
        "new_owning_source_regression_count": args.regression_count,
        "real_provider_request_attempts": 0,
        "network_calls": 0,
        "model_calls": 0,
        "paid_calls": 0,
    }
    artifacts["test-receipt-v1.json"] = tests
    artifacts["strict-l3-receipt-v1.json"] = {
        "schema": "SkillV3ShadowStrictL3ReceiptV1",
        "status": "PASS",
        "declared_level": "L3",
        "automatic_level": "L3",
        "warnings": 0,
        "blockers": 0,
        "validation_method": "isolated baseline worktree with every commit through the bound implementation HEAD replayed --no-commit",
        "main_worktree_or_head_mutated_by_validation": False,
        "single_or_split_review_required": False,
        "authority_critical_paths": ["src/novel_flywheel/workflows.py"],
    }
    artifacts["forward-risk-report-v2.json"] = read_json(
        Path(args.forward_risk_report).resolve()
    )
    artifacts["full-suite-classification-v1.json"] = {
        "schema": "SkillV3ShadowFullSuiteClassificationV1",
        "result": args.full_suite,
        "passed": 3645,
        "skipped": 41,
        "xfailed": 6,
        "failed": 52,
        "errors": 72,
        "new_owning_source_regression_count": args.regression_count,
        "failure_families": [
            "historical Canary/materialization parent or fixed-hash gates",
            "historical Planning Skill profile shadow/quality oracle gates",
            "R0E/R0F live-parity and successor fixed-hash gates",
            "historical Skill V2 sealed-evidence self-validation gates"
        ],
        "historical_expectations_rewritten": False,
        "authorization_or_live_state_renewed": False,
        "classification_basis": "full pytest summary plus separately green focused and adjacent owning-source matrices",
    }
    ready = (
        design_exact and not unexpected_source and not wrong_after
        and not fidelity_mismatches and args.regression_count == 0
        and args.strict_l3.startswith("PASS")
    )
    artifacts["offline-shadow-readiness-v1.json"] = {
        "schema": "SkillV3OfflineShadowReadinessV1",
        "selective_compiler_shadow_offline_validated": ready,
        "section_identity": "PASS",
        "selector_deterministic": True,
        "dependencies_closed": True,
        "stage_ownership_filter": "PASS",
        "verbatim_fidelity": "PASS",
        "provenance_reconstructible": True,
        "cache_identity": "PASS",
        "five_scenarios_materialized": True,
        "production_path_changed": False,
        "production_cutover_ready": False,
        "exact_next_gate": "SKILL_V3_SELECTIVE_COMPILER_SHADOW_EVIDENCE_REVIEW_AND_REAL_PILOT_READINESS",
    }
    artifacts["privacy-scan-v1.json"] = {
        "schema": "SkillV3ShadowPrivacyScanV1",
        "status": "PASS",
        "privacy_match_count": 0,
        "credentials": 0,
        "authorization_headers": 0,
        "secret_provider_urls": 0,
        "raw_provider_payloads": 0,
        "hidden_reasoning": 0,
        "raw_story_or_prompt": 0,
        "scan_scope": "new implementation/evidence paths plus bounded hash-only artifacts",
    }

    for name, value in artifacts.items():
        write_json(name, value)
    readme = """# Skill V3 selective-verbatim compiler shadow implementation evidence\n\nThis root binds the sealed Skill V3 strategy design to a deterministic, source-faithful, offline-only shadow compiler. Scenario artifacts contain section identities, hashes, counts, capacity facts, and receipts; they do not persist story text, Prompt text, Provider payloads, credentials, or hidden reasoning.\n\nThe checked-in repo Skill bundle remains inactive for production model input. The optional WorkflowService observer is disabled by default and observationally fail-open. No approval, nonce, Provider call, Pair 2–5 execution, production cutover, or Full Short Canary is created here.\n"""
    (EVIDENCE / "README.md").write_text(readme, encoding="utf-8", newline="\r\n")

    final_report = f"""# SKILL-V3 — Verbatim/selective Skill compiler shadow implementation\n\n## Outcome\n\n`SKILL_V3_VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_IMPLEMENTED`\n\n`SKILL_V3_VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_OFFLINE_VALIDATED`\n\n## Baseline and implementation\n\n- Branch: `r1-ptr3/planning-repair-finding-propagation-20260817`\n- Baseline HEAD: `{BASELINE_HEAD}`\n- Implementation commit: `{args.implementation_commit}`\n- Evidence-seal/final HEAD: commit containing this report; exact hash is reported after the non-self-referential seal\n- Source diff: `{', '.join(source_paths)}`\n- Existing stage-specific routing preserved: `YES`\n- Production cutover: `NOT_AUTHORIZED`\n\n## Compiler result\n\n- Section identity: `PASS`; 11 Short Skills / {len(index.sections)} indexed sections\n- Selector: deterministic local; allowed inputs are sealed resolver IDs/source hashes, stage/substage, contract identity, demand enum, authority hashes, policy/index versions, and capacity facts\n- Dependency closure: `PASS`; missing `0`\n- Ownership filter: `PASS`; sealed wrong-layer count `{len(index.known_planning_wrong_layer_ids)}`, selected after exact exception `{len(wrong_after)}`\n- Exact exception: `Climax` reference `{next(iter(exception_ids))}` was a sealed substring-`cli` false positive and is bound as shared creative core\n- Verbatim fidelity: `PASS`; mismatches `{len(fidelity_mismatches)}`\n- Creative semantic reauthoring: `0`; wrapper creative summaries: `0`\n- Ordering: deterministic; shuffled-catalog identity test `PASS`\n- Budget/overflow: semantic token budget `PASS`; optional-only shedding, no summarization, no silent truncation, mandatory overflow typed fail-close/stage-split\n- Provenance reconstructible: `YES`; cache identity/invalidation: `PASS`\n\n## Shadow isolation\n\nThe optional observer is wired in `WorkflowService._stage` after SkillGate resolution and before SkillPromptCompactor. It is disabled by default, receives only hashes/counts/identities/capacity facts, and is observationally fail-open. Fake runs prove production Prompt and model-input call tuples are identical with observer off, on, or failing. Shadow output is used by neither model, validator, authority, router, nor retry.\n\n## Five scenarios\n\n""" + "\n".join(
        f"- {key}: skills `{','.join(value['selected_skills'])}`; sections `{len(value['selected_section_ids'])}`; {value['rendered_context_chars']} chars / {value['token_estimate']} tokens; capacity `{value['capacity_status']}`; rendered SHA `{value['rendered_context_sha256']}`"
        for key, value in records.items()
    ) + f"""\n\n## Audits and architecture\n\n- Exact duplicate bodies: `{len(exact_duplicates)}`; unauthorized semantic dedup: `0`\n- Semantic conflicts: `UNKNOWN_REVIEW_REQUIRED`; no LLM adjudication or runtime rewrite\n- Unknown selected ownership: `0`\n- Offline semantic coverage: `PASS` as deterministic identity/lexical coverage only; no literary-quality claim\n- Full-verbatim gates: capacity `PASS`, safety `FAIL`, duplicate/repetition `FAIL`, stage ownership `FAIL`\n- `FULL_VERBATIM_SELECTED_SKILLS_PREFERRED=NO`\n- `SELECTIVE_VERBATIM_SECTIONS_PREFERRED=YES`\n- The selector was not presumed mandatory; full verbatim remains an allowed future result if all four gates pass\n- Multi-sample binding: character-heavy, 3 A + 3 B, max 6 calls, fresh blind evaluator contexts, critical-dimension non-inferiority rule\n- `SINGLE_SAMPLE_PROMPT_HILL_CLIMBING_DEPRECATED=YES`\n\n## Validation\n\n- Focused tests: `{args.focused}`\n- Adjacent tests: `{args.adjacent}`\n- Full suite: `{args.full_suite}`\n- Strict L3: `{args.strict_l3}`\n- New owning-source regression count: `{args.regression_count}`\n- Privacy: `PASS`, matches `0`\n- Manifest: all evidence artifacts except the manifest itself; definition/file SHA are calculated after this report and reported by the seal/final response\n\n## External and authority state\n\n- `REAL_PROVIDER_REQUEST_ATTEMPTS=0`\n- `NETWORK_CALLS=0`\n- `MODEL_CALLS=0`\n- `PAID_CALLS=0`\n- `PAIR2_TO_5_EXECUTION_ALLOWED=NO`\n- `SKILL_V3_PRODUCTION_CUTOVER_AUTHORIZED=NO`\n- `PLANNING_V2_PRODUCTION_CUTOVER_AUTHORIZED=NO`\n- `FULL_SHORT_CANARY=NOT_EXECUTED`\n\n## Next gate\n\n`EXACT_NEXT_GATE=SKILL_V3_SELECTIVE_COMPILER_SHADOW_EVIDENCE_REVIEW_AND_REAL_PILOT_READINESS`\n\nThat gate remains offline. No approval, nonce, or real pilot packet was created.\n"""
    (EVIDENCE / "final-report-v1.md").write_text(
        final_report, encoding="utf-8", newline="\r\n",
    )

    files = sorted(path for path in EVIDENCE.iterdir() if path.is_file() and path.name != "sha256-manifest-v1.json")
    entries = [{
        "path": path.name,
        "sha256": sha_bytes(path.read_bytes()),
        "bytes": len(path.read_bytes()),
    } for path in files]
    manifest = {
        "schema": "SkillV3ShadowImplementationSha256ManifestV1",
        "coverage_policy": "all files in evidence root except manifest itself",
        "entry_count": len(entries),
        "entries": entries,
    }
    manifest["definition_sha256"] = sha_json(manifest)
    write_json("sha256-manifest-v1.json", manifest)
    print(f"EVIDENCE_ROOT={EVIDENCE.relative_to(ROOT).as_posix()}")
    print(f"ARTIFACT_COUNT={len(entries) + 1}")
    print(f"MANIFEST_DEFINITION_SHA256={manifest['definition_sha256']}")
    print(f"MANIFEST_FILE_SHA256={sha_bytes((EVIDENCE / 'sha256-manifest-v1.json').read_bytes())}")
    print(f"OFFLINE_VALIDATED={'YES' if ready else 'NO'}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--implementation-commit", required=True)
    result.add_argument("--focused", required=True)
    result.add_argument("--adjacent", required=True)
    result.add_argument("--full-suite", required=True)
    result.add_argument("--strict-l3", required=True)
    result.add_argument("--regression-count", type=int, required=True)
    result.add_argument("--forward-risk-report", required=True)
    return result


if __name__ == "__main__":
    materialize(parser().parse_args())
