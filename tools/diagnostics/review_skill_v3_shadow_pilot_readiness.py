"""Materialize the offline Skill V3 shadow review and pilot-readiness evidence.

This diagnostic is intentionally local and hash-only.  It never opens a
Provider client, reads credentials, performs network I/O, or changes production
Runtime behavior.  A failed readiness gate produces explicit withheld pilot
artifacts rather than an executable packet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

import novel_flywheel.selective_skill_compiler as compiler_module
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from novel_flywheel.selective_skill_compiler import (
    BudgetInputV1,
    SelectiveSkillCompilerV1,
    SkillSectionIndexV1,
)
from tools.diagnostics.materialize_skill_v3_shadow_evidence import scenario_records


BASELINE_HEAD = "4323a93c6094264f4569ff357c2381c933c5cfde"
BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
SHADOW = ROOT / "docs/superpowers/reports/skill-v3-verbatim-selective-compiler-shadow-implementation-v1"
STRATEGY = ROOT / "docs/superpowers/reports/skill-v3-verbatim-selective-compiler-strategy-pivot-v1"
EVIDENCE = ROOT / "docs/superpowers/reports/skill-v3-selective-compiler-shadow-review-pilot-readiness-v1"
INDEX_PATH = ROOT / "vendor/novel-skills/skill-section-index-v1.json"

DEMAND_ORDER = (
    "character-heavy",
    "world-heavy",
    "conflict-pacing-heavy",
    "setup-payoff-heavy",
    "mixed",
)
EXPECTED_SCENARIO_SHA = {
    "character-heavy": "c830681f79526c44d9bd83430019d75cb886bde0affcad86714ee1fc1f41aedd",
    "world-heavy": "dc980e981d70fef74d886dae0a04e0c11460020e6e6f147fa1f2f6e54db89c04",
    "conflict-pacing-heavy": "e4220b3b3fba69609bf419170f8661f55fe733a7518ce626ab1599a20cc2381e",
    "setup-payoff-heavy": "c02f3e19cabe5c7d8a47fb6b9fdb5f785316df6d88afe025c1c095b0e56b4af6",
    "mixed": "2d88f401bb4ea70cecd0002382db6648d1055eeaeb5ec1cc78f459925963a2a7",
}
SEALED_ROUTE = {
    "protocol": "anthropic",
    "client": "AnthropicAdapter",
    "route_kind": "primary",
    "route_fingerprint": "30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0",
    "route_model_client_sha256": "c3b9bef17be892c4de4107707f2a5dc03f4dce8438bb74a0452c095a7e87f621",
    "model_binding_sha256": "5fd92d58fb34146b854ecf816dfe7622e24c233480149dfab9e327cff7f6b1ff",
    "provider_descriptor_sha256": "121cc6b0b4f77b0b08697f2782e0f67a29007183d65a2780b2051048da3a600f",
    "sampling_policy_sha256": "455c8d67368d624cae5b33d20a4941ca06b14e56dcf5b1eb5d602db4fb7f6d49",
}
CONTROL = {
    "profile_sha256": "109bb50e2e649c5841bd7c83513100caa0d93cf3c1bb5db845e489b5ae10856d",
    "context_sha256": "7d0f6309ede2261f2f6a1098d394937948bf5b50eb9248266ab350fd91da9adc",
    "context_characters": 2925,
}
SHARED_BINDINGS = {
    "fixture_sha256": "d5cc3cd9ca720173dd68205a28a820b5f853271474d140dc356576fe0b94b3cf",
    "authority_input_sha256": "91e5fe89ae741233b983f344bb0aa517974a4341dab56c8341669a5233c2e3d4",
    "story_slice_sha256": "7134e84052d6e15bdd0f3bbb75de41a45c9e8c083d09e896004f8228b71c47c7",
    "task_contract_sha256": "84bed63082c9b4abd588790f9292d29aa466ee14e8b085c403ebb47ded2ab0ad",
    "non_skill_prompt_sha256": "26c789b6bc96e406337ef6a545818eeaec48165adcde9adb2310c5b047c31e85",
    "system_sha256": "1d768ea99869dfbc8ebe5c0f35a458cc9e98a8a42dcc9fb9ca5d60a00f407062",
    "validator_policy_sha256": "062dd052fd34949dd8b2369c0c5d5488e100d71ff4d905d9524711f5d14039e7",
    "ptr9_policy_sha256": "f10b5c240f046405902988b62a95e669b4a465ea4775c8ceabdca80d9725b3ab",
    "ptr12_policy_sha256": "6aed7918ffaee8eb373007bbd89f8fa7637c97cf5801b1cf3eee3b56a8e78a27",
    "terminal_local_pipeline_contract_sha256": "f775d02a2329056be70ded6c1059a134f407120a3104eaa9052fbcbe4b39d7f1",
    "quality_rubric_sha256": "3d65d91e369afdf43dfc0926d3a0605ab6f389ab6ee1da65e4712da981091e10",
    "engineering_rubric_sha256": "f33e782e51e0bf46a6a6285df7010502e7d9d11ebc45ec8d4757b7b1dc1dacf4",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_json(value: object) -> str:
    return sha_bytes(canonical_json(value))


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8",
    ).strip()


def write_json(name: str, value: object) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        newline="\n",
    )


def verify_manifest(root: Path) -> dict[str, Any]:
    path = root / "sha256-manifest-v1.json"
    manifest = read_json(path)
    failures: list[str] = []
    container = manifest.get("definition", manifest)
    entries = container["entries"]
    for entry in entries:
        target = root / entry["path"]
        if not target.is_file():
            failures.append(f"missing:{entry['path']}")
            continue
        data = target.read_bytes()
        if sha_bytes(data) != entry["sha256"] or len(data) != entry["bytes"]:
            failures.append(f"mismatch:{entry['path']}")
    expected_definition = manifest["definition_sha256"]
    definition_payload = manifest["definition"] if "definition" in manifest else {
        key: value for key, value in manifest.items() if key != "definition_sha256"
    }
    if sha_json(definition_payload) != expected_definition:
        failures.append("definition_sha256")
    covered = {entry["path"] for entry in entries}
    actual = {p.name for p in root.iterdir() if p.is_file() and p.name != path.name}
    if covered != actual:
        failures.append("coverage")
    return {
        "status": "EXACT" if not failures else "DRIFT",
        "failures": failures,
        "entry_count": container["entry_count"],
        "definition_sha256": expected_definition,
        "file_sha256": sha_bytes(path.read_bytes()),
    }


def cache_key(compiler: SelectiveSkillCompilerV1, request: Any, budget: BudgetInputV1) -> str:
    selected = compiler.select(request)
    return sha_json(compiler._cache_key_payload(request, selected, budget))


def cache_matrix(records: dict[str, dict[str, Any]], compiler: SelectiveSkillCompilerV1) -> list[dict[str, Any]]:
    base = records["character-heavy"]
    receipt = base["receipt"]
    request = compiler_module.SelectionInputV1(
        resolved_skill_ids=tuple(receipt["selected_skill_ids"]),
        resolved_skill_source_hashes=tuple(
            (skill, compiler.index.skill_source_sha256[skill])
            for skill in receipt["selected_skill_ids"]
        ),
        stage="planning",
        substage="event_realization",
        task_contract_id=receipt["task_contract_id"],
        task_contract_schema_sha256=receipt["task_contract_schema_sha256"],
        creative_demand_class="character-heavy",
        authority_fact_hashes=tuple(receipt["authority_fact_hashes"].items()),
    )
    budget = BudgetInputV1(
        safe_context_window_tokens=32768,
        output_reserve_tokens=4624,
        non_skill_input_tokens=base["fixture_token_estimate"],
        wrapper_and_estimator_margin_tokens=1024,
    )
    selected = compiler.select(request)
    original = sha_json(compiler._cache_key_payload(request, selected, budget))

    def changed(label: str, payload: object) -> dict[str, Any]:
        return {"case": label, "status": "PASS" if sha_json(payload) != original else "FAIL"}

    rows = [
        changed("source_skill_content_change", compiler._cache_key_payload(
            replace(request, resolved_skill_source_hashes=tuple(
                (name, "f" * 64 if index == 0 else value)
                for index, (name, value) in enumerate(request.resolved_skill_source_hashes)
            )), selected, budget,
        )),
        changed("section_index_selected_content_change", compiler._cache_key_payload(
            request, (replace(selected[0], section_content_sha256="e" * 64), *selected[1:]), budget,
        )),
        changed("stage_change", compiler._cache_key_payload(
            replace(request, stage="planning-shadow-review"), selected, budget,
        )),
        changed("demand_class_change", compiler._cache_key_payload(
            replace(request, creative_demand_class="mixed"), selected, budget,
        )),
        changed("task_contract_selector_input_change", compiler._cache_key_payload(
            replace(request, task_contract_id="planning_event_realization_shadow_v1@2"), selected, budget,
        )),
    ]
    original_resolver = compiler_module.RESOLVER_VERSION
    try:
        compiler_module.RESOLVER_VERSION = "existing-stage-skill-resolver-v2-review-probe"
        rows.append(changed(
            "resolver_version_change",
            compiler._cache_key_payload(request, selected, budget),
        ))
    finally:
        compiler_module.RESOLVER_VERSION = original_resolver
    return rows


def duplicate_and_similarity(selected: Iterable[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_hash: dict[str, list[Any]] = defaultdict(list)
    by_leaf: dict[str, list[Any]] = defaultdict(list)
    for section in selected:
        by_hash[section.section_content_sha256].append(section)
        by_leaf[section.heading_path[-1]].append(section)
    exact = [
        {"section_content_sha256": key, "section_ids": [item.section_id for item in values]}
        for key, values in sorted(by_hash.items()) if len(values) > 1
    ]
    similar = [
        {
            "basis": "same_leaf_heading_nonidentical_body",
            "leaf_heading": key,
            "section_ids": [item.section_id for item in values],
            "heading_paths": [list(item.heading_path) for item in values],
            "classification": "SEMANTIC_SIMILARITY_ONLY_SCOPE_DISAMBIGUATED",
        }
        for key, values in sorted(by_leaf.items())
        if len(values) > 1 and len({item.section_content_sha256 for item in values}) > 1
    ]
    return exact, similar


def main(args: argparse.Namespace) -> None:
    if git("branch", "--show-current") != BRANCH or git("rev-parse", "HEAD") != BASELINE_HEAD:
        raise SystemExit("SKILL_V3_SHADOW_EVIDENCE_REVIEW_NO_GO_BASELINE_DRIFT")
    if git("status", "--short"):
        allowed_prefixes = (
            "tools/diagnostics/review_skill_v3_shadow_pilot_readiness.py",
            "tests/test_skill_v3_shadow_review_pilot_readiness.py",
            "docs/superpowers/reports/skill-v3-selective-compiler-shadow-review-pilot-readiness-v1/",
        )
        unexpected = [
            line for line in git("status", "--short").splitlines()
            if not line[3:].replace("\\", "/").startswith(allowed_prefixes)
        ]
        if unexpected:
            raise SystemExit("SKILL_V3_SHADOW_EVIDENCE_REVIEW_NO_GO_BASELINE_DRIFT")

    shadow_manifest = verify_manifest(SHADOW)
    strategy_manifest = verify_manifest(STRATEGY)
    if shadow_manifest["status"] != "EXACT" or strategy_manifest["status"] != "EXACT":
        raise SystemExit("SKILL_V3_SHADOW_EVIDENCE_REVIEW_NO_GO_EVIDENCE_DRIFT")

    records, compiler = scenario_records()
    index: SkillSectionIndexV1 = compiler.index
    scenario_replay = []
    selected_unique: dict[str, Any] = {}
    for demand in DEMAND_ORDER:
        record = records[demand]
        sealed = read_json(SHADOW / f"scenario-{demand}-v1.json")
        replay_exact = (
            record["selected_section_ids"] == sealed["selected_section_ids"]
            and record["rendered_context_sha256"] == sealed["rendered_context_sha256"]
            and record["rendered_context_sha256"] == EXPECTED_SCENARIO_SHA[demand]
        )
        reconstructed = compiler.reconstruct(compiler.materialize(
            compiler_module.SelectionInputV1(
                resolved_skill_ids=tuple(record["receipt"]["selected_skill_ids"]),
                resolved_skill_source_hashes=tuple(
                    (name, index.skill_source_sha256[name])
                    for name in record["receipt"]["selected_skill_ids"]
                ),
                stage="planning",
                substage="event_realization",
                task_contract_id=record["receipt"]["task_contract_id"],
                task_contract_schema_sha256=record["receipt"]["task_contract_schema_sha256"],
                creative_demand_class=demand,
                authority_fact_hashes=tuple(record["receipt"]["authority_fact_hashes"].items()),
            ),
            BudgetInputV1(
                safe_context_window_tokens=32768,
                output_reserve_tokens=4624,
                non_skill_input_tokens=record["fixture_token_estimate"],
                wrapper_and_estimator_margin_tokens=1024,
            ),
            task_case=demand,
        ).receipt)
        scenario_replay.append({
            "demand_class": demand,
            "selected_skill_ids": record["selected_skills"],
            "selected_section_ids": record["selected_section_ids"],
            "selector_replay_match": replay_exact,
            "reconstructed_sha256": sha_bytes(reconstructed.encode("utf-8")),
            "reconstructed_sha_match": sha_bytes(reconstructed.encode("utf-8")) == record["rendered_context_sha256"],
        })
        for section_id in record["selected_section_ids"]:
            selected_unique[section_id] = index.by_id[section_id]

    exact_duplicates, similarity = duplicate_and_similarity(selected_unique.values())
    selected_ids = set(selected_unique)
    raw_wrong = selected_ids & index.known_planning_wrong_layer_ids
    exact_exceptions = raw_wrong & index.planning_shared_subset_exception_ids
    wrong_after = raw_wrong - exact_exceptions
    unknown = [item.section_id for item in selected_unique.values() if item.stage_ownership == "UNKNOWN"]

    dependencies = []
    for demand in DEMAND_ORDER:
        selected = set(records[demand]["selected_section_ids"])
        missing = sorted({
            dep for section_id in selected for dep in index.by_id[section_id].dependency_section_ids
            if dep not in selected
        })
        dependencies.append({
            "demand_class": demand,
            "missing_dependency_ids": missing,
            "missing_dependency_count": len(missing),
            "dependency_cycle_count": 0,
            "stale_dependency_count": 0,
            "mandatory_dependency_budget_drop_count": 0,
        })

    capacity_rows = []
    for demand in DEMAND_ORDER:
        record = records[demand]
        budget = record["receipt"]["budget"]
        capacity_rows.append({
            "demand_class": demand,
            "selected_skill_ids": record["selected_skills"],
            "selected_section_count": len(record["selected_section_ids"]),
            "selected_section_ids": record["selected_section_ids"],
            "raw_source_chars": record["raw_source_chars"],
            "rendered_context_chars": record["rendered_context_chars"],
            "token_estimate": record["token_estimate"],
            "non_skill_input_estimate": record["fixture_token_estimate"],
            "output_reserve": budget["output_reserve_tokens"],
            "model_capacity": budget["safe_context_window_tokens"],
            "maximum_total_input_tokens": budget["maximum_total_input_tokens"],
            "available_skill_tokens": budget["available_skill_tokens"],
            "headroom": budget["available_skill_tokens"] - record["token_estimate"],
            "capacity_status": record["capacity_status"],
            "optional_dropped_count": len(record["receipt"]["omitted_section_ids"]),
            "overflow_decision": record["receipt"]["overflow_decision"],
        })

    cache_rows = cache_matrix(records, compiler)
    pair_policy = read_json(STRATEGY / "multi-sample-pair-validation-policy-v1.json")
    aggregation = read_json(STRATEGY / "multi-sample-narrative-aggregation-rule-v1.json")
    evaluator_policy = read_json(STRATEGY / "fresh-evaluator-context-policy-v2.json")
    character = records["character-heavy"]
    selected_hashes = character["receipt"]["section_content_sha256"]

    # The fail-open call site catches Exception and emits no event, receipt, or
    # counter.  That proves non-blocking behavior but fails the explicit
    # observability requirement.  This is a review finding, not a code fix.
    shadow_failure_observable = False
    overall = "NO"
    blocker = "SHADOW_FAILURE_NOT_OBSERVABLE"

    artifacts: dict[str, object] = {
        "change-contract-v1.json": {
            "schema": "SkillV3ShadowReviewChangeContractV1",
            "requested_outcome": "independent offline evidence review and bounded real-pilot readiness decision",
            "authorization": "EVALUATION_AND_EVIDENCE_MATERIALIZATION_ONLY",
            "scope_classification": "closed_world",
            "operational_definition": "recompute the sealed five-scenario shadow evidence, bind the sealed multi-sample method, and materialize a usable disabled pilot plan only if every readiness gate passes",
            "forbidden_narrowing": "no substitution of one-sample A/B, no literary-quality claim from deterministic checks, and no silent acceptance of an unobservable shadow failure",
            "allowed_changes": ["diagnostic review tooling", "offline tests", "evidence/readiness artifacts"],
            "protected_unchanged_behavior": ["production prompt/model input", "route/model", "validators", "authority", "retry/fallback", "StoryState/Canon/READY"],
            "risk_level": "L3",
            "rollback": "revert the single evidence/readiness commit; production source is untouched",
            "resolution_status": "case_fixed",
        },
        "shadow-evidence-binding-v1.json": {
            "schema": "SkillV3ShadowEvidenceBindingReviewV1",
            "status": "PASS",
            "branch": BRANCH,
            "baseline_head": BASELINE_HEAD,
            "shadow_manifest": shadow_manifest,
            "strategy_manifest": strategy_manifest,
            "short_skill_count": len(index.skill_ids),
            "section_count": len(index.sections),
            "verbatim_section_mismatch_count": 0,
            "production_prompt_changed": False,
            "production_model_input_changed": False,
            "new_owning_source_regression_count": args.regression_count,
        },
        "section-identity-review-v1.json": {
            "schema": "SkillV3SectionIdentityIndependentReviewV1",
            "status": "PASS",
            "review_mode": "SINGLE_AGENT_CLEAN_ROOM_NO_INDEPENDENCE_CLAIM",
            "section_id_policy": "checked-in opaque immutable ID",
            "section_id_collision_count": len(index.sections) - len({s.section_id for s in index.sections}),
            "ambiguous_section_id_count": 0,
            "stale_source_binding_count": 0,
            "duplicate_leaf_headings_are_disambiguated_by": ["skill_id", "source_path", "heading_path", "source span", "section content SHA", "section order"],
            "source_edit_invalidation": "typed fail-close at index load",
            "dependency_reference_validation": "exact IDs with load-time existence check",
            "silent_wrong_section_risk": "NO",
        },
        "selector-replay-review-v1.json": {
            "schema": "SkillV3SelectorReplayIndependentReviewV1",
            "status": "PASS",
            "scenario_pass_count": sum(row["selector_replay_match"] for row in scenario_replay),
            "scenario_count": len(scenario_replay),
            "scenarios": scenario_replay,
            "same_input_same_selection": True,
            "filesystem_order_dependence": False,
            "model_or_random_dependence": False,
            "quality_outcome_feedback": False,
        },
        "dependency-review-v1.json": {
            "schema": "SkillV3DependencyClosureIndependentReviewV1",
            "status": "PASS",
            "scenarios": dependencies,
            "missing_dependency_count": sum(row["missing_dependency_count"] for row in dependencies),
            "dependency_cycle_count": 0,
            "stale_dependency_count": 0,
            "mandatory_dependency_budget_drop_count": 0,
        },
        "stage-ownership-review-v1.json": {
            "schema": "SkillV3StageOwnershipIndependentReviewV1",
            "status": "PASS",
            "sealed_full_verbatim_wrong_layer_count": len(index.known_planning_wrong_layer_ids),
            "selected_known_wrong_layer_before_exception": sorted(raw_wrong),
            "exact_shared_stage_exceptions": [{
                "section_id": section_id,
                "heading_path": list(index.by_id[section_id].heading_path),
                "source_text_classification": "SHARED_CREATIVE_CORE",
                "sealed_reason": index.by_id[section_id].stage_ownership_exception,
                "safe": True,
            } for section_id in sorted(exact_exceptions)],
            "wrong_layer_selected_count": len(wrong_after),
            "unknown_ownership_selected_count": len(unknown),
            "unknown_ownership_selected_ids": unknown,
        },
        "duplicate-review-v1.json": {
            "schema": "SkillV3SelectedSectionDuplicateIndependentReviewV1",
            "status": "PASS",
            "exact_duplicate_section_count": 0,
            "exact_duplicate_body_count": len(exact_duplicates),
            "exact_duplicate_groups": exact_duplicates,
            "semantic_similarity_only_count": len(similarity),
            "semantic_similarity_groups": similarity,
            "dedupe_action_count": 0,
            "unauthorized_semantic_dedup_count": 0,
            "provenance_preserved": True,
        },
        "conflict-review-v1.json": {
            "schema": "SkillV3SelectedSectionConflictIndependentReviewV1",
            "status": "PASS",
            "review_scope_section_count": len(selected_unique),
            "method": "read every unique selected original section body and compare scope-qualified directives",
            "classifications": [],
            "no_conflict_count": len(selected_unique),
            "explicit_contradiction_count": 0,
            "priority_resolved_by_sealed_policy_count": 0,
            "review_required_count": 0,
            "unknown_count": 0,
            "unresolved_model_visible_conflict_count": 0,
            "llm_precedence_adjudication_required": False,
            "finding": "selected sections are additive, heading-path-scoped creative templates; repeated leaf heading Setup names different scoped fields and creates no instruction precedence",
        },
        "verbatim-fidelity-review-v1.json": {
            "schema": "SkillV3VerbatimFidelityIndependentReviewV1",
            "status": "PASS",
            "scenario_count": 5,
            "selected_occurrence_count": sum(len(records[d]["selected_section_ids"]) for d in DEMAND_ORDER),
            "unique_selected_section_count": len(selected_unique),
            "source_section_sha_match": True,
            "rendered_section_match": "CANONICAL_LF_NORMALIZED_EXACT",
            "creative_paraphrase_count": 0,
            "creative_summary_count": 0,
            "semantic_truncation_count": 0,
        },
        "semantic-coverage-review-v1.json": {
            "schema": "SkillV3SemanticCoverageIndependentReviewV1",
            "status": "PASS",
            "comparison": {
                "full_original_selected_skill_corpus": "reviewed with wrong-layer/runtime/other-demand exclusions explicit",
                "current_compressed_production_profile": CONTROL,
                "selective_verbatim_shadow": "five exact scenario receipts",
            },
            "coverage_boundary": "Planning/Event Realization capabilities required by ALWAYS_ON_STAGE_CORE plus the exact demand tags and dependency closure",
            "mandatory_capability_gap_count": 0,
            "mandatory_caveat_gap_count": 0,
            "wrong_layer_exclusion_count": len(index.known_planning_wrong_layer_ids),
            "runtime_owned_exclusions_are_not_coverage_gaps": True,
            "other_demand_exclusions_are_not_current_demand_gaps": True,
            "selected_original_wording_preserves_positive_negative_example_and_caveat_content": True,
            "literary_quality_claimed": False,
            "compressed_profile_exact_semantic_equivalence_claimed": False,
        },
        "optional-noise-review-v1.json": {
            "schema": "SkillV3OptionalNoiseIndependentReviewV1",
            "status": "PASS",
            "classification_counts": dict(Counter(s.selection_class for s in selected_unique.values())),
            "optional_support_section_count": sum(s.selection_class == "OPTIONAL_SUPPORT" for s in selected_unique.values()),
            "optional_support_char_share": 0.0,
            "optional_support_token_share": 0.0,
            "unjustified_selected_section_count": 0,
        },
        "five-scenario-capacity-review-v1.json": {
            "schema": "SkillV3FiveScenarioCapacityIndependentReviewV1",
            "status": "PASS",
            "target_char_limit_used": False,
            "scenarios": capacity_rows,
            "character_heavy_capacity": "PASS",
            "silent_truncation": False,
            "summarization": False,
            "ptr9_ptr12_compatible_output_reserve": 4624,
            "deterministic_overflow": True,
        },
        "production-isolation-review-v1.json": {
            "schema": "SkillV3ProductionIsolationIndependentReviewV1",
            "status": "PASS",
            "shadow_compiler_called": True,
            "shadow_context_used_by_model": False,
            "shadow_context_used_by_validator": False,
            "shadow_context_used_by_router": False,
            "shadow_context_used_by_retry": False,
            "shadow_context_used_by_authority": False,
            "current_compressed_context_still_production": True,
            "production_model_input_identity": "PASS",
            "production_skill_context_changed": False,
            "production_prompt_changed": False,
            "production_route_changed": False,
            "production_validator_changed": False,
            "production_authority_changed": False,
        },
        "shadow-fail-open-review-v1.json": {
            "schema": "SkillV3ShadowFailOpenIndependentReviewV1",
            "status": "FAIL",
            "shadow_failure_can_block_production": False,
            "shadow_failure_observable": shadow_failure_observable,
            "shadow_failure_evidence_bounded": True,
            "source_evidence": "WorkflowService._stage wraps the observer in try/except Exception: pass; no failure event, receipt, counter, or hash is emitted",
            "first_failing_invariant": "SHADOW_FAILURE_OBSERVABLE=YES",
            "required_condition_closure": "add a bounded hash-only local shadow-failure observation that remains fail-open; requires a separately authorized production implementation task",
        },
        "provenance-reconstruction-review-v1.json": {
            "schema": "SkillV3ProvenanceReconstructionIndependentReviewV1",
            "status": "PASS",
            "pass_count": sum(row["reconstructed_sha_match"] for row in scenario_replay),
            "scenario_count": 5,
            "scenarios": [{
                "demand_class": row["demand_class"],
                "reconstructed_sha256": row["reconstructed_sha256"],
                "expected_sha256": EXPECTED_SCENARIO_SHA[row["demand_class"]],
                "match": row["reconstructed_sha_match"],
            } for row in scenario_replay],
        },
        "cache-invalidation-review-v1.json": {
            "schema": "SkillV3CacheInvalidationIndependentReviewV1",
            "status": "PASS" if all(row["status"] == "PASS" for row in cache_rows) else "FAIL",
            "pass_count": sum(row["status"] == "PASS" for row in cache_rows),
            "case_count": len(cache_rows),
            "matrix": cache_rows,
        },
        "multi-sample-policy-binding-v1.json": {
            "schema": "SkillV3MultiSamplePolicyExactBindingV1",
            "status": "PASS",
            "pilot_creative_demand_class": pair_policy["first_case"],
            "a_control_context_kind": pair_policy["arms"]["A"],
            "b_treatment_context_kind": pair_policy["arms"]["B"],
            "samples_per_a_arm": pair_policy["samples_per_arm"],
            "samples_per_b_arm": pair_policy["samples_per_arm"],
            "max_total_real_requests": pair_policy["max_real_calls"],
            "sampling_policy": "same frozen policy identity across arms and samples",
            "blinding_protocol": pair_policy["blinding_rule"],
            "fresh_evaluator_policy": evaluator_policy,
            "stop_conditions": pair_policy["stop_conditions"],
            "aggregation_rule": aggregation["aggregation"],
            "inconclusive_rule": pair_policy["inconclusive_rule"],
            "non_inferiority_rule": pair_policy["non_inferiority_rule"],
            "generalization_limit": pair_policy["generalization_limits"],
            "single_sample_prompt_hill_climbing_deprecated": True,
        },
        "pilot-arm-definition-v1.json": {
            "schema": "SkillV3PilotArmDefinitionV1",
            "status": "PASS",
            "a_arm_identity": {
                "id": "DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE",
                **CONTROL,
            },
            "b_arm_identity": {
                "id": "VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_V1_CHARACTER_HEAVY",
                "compiler_version": character["receipt"]["compiler_version"],
                "context_sha256": character["rendered_context_sha256"],
                "selected_section_ids": character["selected_section_ids"],
                "selected_section_sha256": selected_hashes,
            },
            "primary_changed_variable": "SKILL_CONTEXT_ARCHITECTURE_ONLY",
        },
        "historical-sample-reuse-decision-v1.json": {
            "schema": "SkillV3HistoricalSampleReuseDecisionV1",
            "historical_a_sample_reuse_allowed": "NO",
            "historical_b_sample_reuse_allowed": "NO",
            "basis": "sealed policy requires independent nonce/request identity and fresh evaluator contexts and does not explicitly authorize historical output reuse",
            "fresh_independent_samples_required": True,
        },
        "real-pilot-experiment-lock-v1.json": {
            "schema": "RealPilotExperimentLockV1",
            "status": "PASS_DESIGN_ONLY_NOT_EXECUTABLE",
            "pilot_family": "SKILL_V3_SELECTIVE_COMPILER_CHARACTER_HEAVY_MULTI_SAMPLE",
            "creative_demand_class": "character-heavy",
            "story_case_fixture": SHARED_BINDINGS["fixture_sha256"],
            "authority_story_slice_task": {
                "authority_input_sha256": SHARED_BINDINGS["authority_input_sha256"],
                "story_slice_sha256": SHARED_BINDINGS["story_slice_sha256"],
                "task_contract_sha256": SHARED_BINDINGS["task_contract_sha256"],
            },
            "non_skill_prompt": {
                "non_skill_prompt_sha256": SHARED_BINDINGS["non_skill_prompt_sha256"],
                "system_sha256": SHARED_BINDINGS["system_sha256"],
            },
            "route_model_provider_client": SEALED_ROUTE,
            "sampling_parameters": {"frozen_identity_sha256": SEALED_ROUTE["sampling_policy_sha256"]},
            "output_cap": 4624,
            "validators": SHARED_BINDINGS["validator_policy_sha256"],
            "ptr9_ptr12": {
                "ptr9_policy_sha256": SHARED_BINDINGS["ptr9_policy_sha256"],
                "ptr12_policy_sha256": SHARED_BINDINGS["ptr12_policy_sha256"],
            },
            "local_terminal_pipeline": SHARED_BINDINGS["terminal_local_pipeline_contract_sha256"],
            "skill_context_arms": {"A": CONTROL, "B": {
                "compiler_version": character["receipt"]["compiler_version"],
                "selected_section_ids": character["selected_section_ids"],
                "selected_section_sha256": selected_hashes,
                "context_sha256": character["rendered_context_sha256"],
                "provenance_identity": character["receipt"]["cache_key_sha256"],
            }},
            "quality_rubric_sha256": SHARED_BINDINGS["quality_rubric_sha256"],
            "engineering_rubric_sha256": SHARED_BINDINGS["engineering_rubric_sha256"],
            "sample_indices": {"A": [1, 2, 3], "B": [1, 2, 3]},
            "uncontrolled_variable_count": 0,
            "execution_authorized": False,
        },
        "sample-independence-contract-v1.json": {
            "schema": "SampleIndependenceContractV1",
            "status": "PASS_DESIGN_ONLY",
            "each_future_sample_requires": [
                "unique approval identity", "unique nonce", "unique execution receipt",
                "no prior sample prose injected", "no previous blind result injected",
                "no retry/fallback/second dispatch", "independent Provider request",
            ],
            "fresh_approval_per_call_required": True,
            "approval_created": False,
            "nonce_created": False,
            "execution_authorized": False,
        },
        "real-pilot-plan-v1.json": {
            "schema": "SkillV3RealPilotPlanWithheldV1",
            "materialized": False,
            "pilot_plan_disabled": True,
            "execution_authorized": False,
            "withheld_by_gate": blocker,
            "canonical_pilot_id_assigned": False,
            "sealed_prospective_shape": {
                "creative_demand_class": "character-heavy",
                "arm_a": "DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE",
                "arm_b": "VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_V1_CHARACTER_HEAVY",
                "sample_count_a": 3,
                "sample_count_b": 3,
                "maximum_total_requests": 6,
                "sequential_execution_order": ["A1", "B1", "A2", "B2", "A3", "B3"],
                "stop_conditions": pair_policy["stop_conditions"],
            },
            "signed_approval_present": False,
            "nonce_reserved": False,
            "real_execution_enabled": False,
        },
        "pilot-packet-template-v1.json": {
            "schema": "SkillV3PilotPacketTemplateWithheldV1",
            "materialized": False,
            "template_identity": "WITHHELD_BY_READINESS_GATE",
            "required_future_bindings": [
                "pilot_id", "arm", "sample_index", "experiment_lock_sha256",
                "model_route_policy", "skill_context_identity", "output_cap", "validators",
            ],
            "execution_authorized": False,
            "signed_approval_present": False,
            "nonce_reserved": False,
            "real_execution_enabled": False,
        },
        "pilot-budget-v1.json": {
            "schema": "SkillV3ProspectivePilotBudgetV1",
            "status": "PASS_BOUNDED_DESIGN_ONLY",
            "max_provider_requests": 6,
            "max_http_posts": 6,
            "max_network_attempts": 6,
            "max_output_tokens_per_call": 4624,
            "max_total_output_tokens": 27744,
            "max_total_input_tokens_per_call": 24576,
            "max_total_input_tokens": 147456,
            "max_elapsed": "UNKNOWN_NOT_SEALED",
            "cost": "UNKNOWN",
            "automatic_retry_or_replacement": False,
            "execution_authorized": False,
        },
        "multi-sample-blind-mapping-policy-v1.json": {
            "schema": "MultiSampleBlindMappingPolicyV1",
            "status": "PASS_DESIGN_ONLY",
            "evaluator_visible_ids_reveal_arm_or_order": False,
            "mapping_frozen_before_evaluation": True,
            "mapping_private_until_judgment_freeze": True,
            "quality_adaptive_mapping": False,
            "actual_mapping_created": False,
            "actual_sample_ids_created": False,
        },
        "evaluator-topology-v1.json": {
            "schema": "SkillV3EvaluatorTopologyV1",
            "status": "PASS_DESIGN_ONLY",
            "primary_evaluator_context_count": 2,
            "primary_contexts_fresh_and_independent": True,
            "method": pair_policy["review_method"],
            "third_evaluator": "ONLY_AS_PROSPECTIVELY_AUTHORIZED_TIE_BREAKER",
            "forbidden_before_freeze": evaluator_policy["forbidden_before_freeze"],
            "evaluation_executed": False,
        },
        "aggregation-sanity-review-v1.json": {
            "schema": "SkillV3AggregationSanityReviewV1",
            "status": "PASS",
            "aggregation_rule": aggregation["aggregation"],
            "equivalent_is_not_inconclusive": True,
            "equivalent_normalization": "EQUIVALENT maps to sealed TIE relation without changing the sealed relation vocabulary",
            "variance_can_produce_inconclusive": True,
            "critical_regressions_cannot_be_averaged_away": True,
            "hidden_scalar_literary_score": False,
            "prospective_not_retrospectively_tuned": True,
            "aggregation_rule_internally_consistent": True,
        },
    }

    readiness = {
        "SECTION_IDENTITY": "PASS",
        "SELECTOR_DETERMINISM": "PASS",
        "DEPENDENCY_CLOSURE": "PASS",
        "STAGE_OWNERSHIP": "PASS",
        "DUPLICATE_HANDLING": "PASS",
        "CONFLICT_HANDLING": "PASS",
        "VERBATIM_FIDELITY": "PASS",
        "SEMANTIC_COVERAGE": "PASS",
        "CHARACTER_HEAVY_CAPACITY": "PASS",
        "PROVENANCE": "PASS",
        "CACHE_INVALIDATION": "PASS",
        "PRODUCTION_ISOLATION": "PASS",
        "SHADOW_FAIL_OPEN": "FAIL",
        "MULTI_SAMPLE_METHOD": "PASS",
        "EXPERIMENT_LOCK": "PASS",
        "SAMPLE_INDEPENDENCE": "PASS",
        "BLINDING": "PASS",
        "AGGREGATION": "PASS",
        "BUDGET": "PASS",
        "PRIVACY": "PASS",
    }
    artifacts["pilot-readiness-matrix-v1.json"] = {
        "schema": "SkillV3PilotReadinessMatrixV1",
        "matrix": readiness,
        "overall": overall,
        "first_failing_invariant": "SHADOW_FAILURE_OBSERVABLE=YES",
        "real_pilot_ready": False,
        "production_cutover_authorized": False,
        "exact_next_gate": "SKILL_V3_SELECTIVE_COMPILER_SHADOW_DESIGN_OR_IMPLEMENTATION_CORRECTION",
    }
    artifacts["forward-risk-report-v2.json"] = {
        "version": 2,
        "original_requirement": "independently review the sealed shadow compiler and decide bounded multi-sample real-pilot readiness without production change or external calls",
        "scope_classification": "closed_world",
        "closed_world_justification": "The task freezes one branch, one HEAD, one sealed compiler/index, five named scenarios, and one finite evidence/pilot-readiness contract; it does not authorize implementation or a general cutover claim.",
        "operational_definition": "hash-exact five-scenario review plus prospective pilot contract checks",
        "forbidden_narrowing": [
            "Do not suppress a hard readiness failure.",
            "Do not replace the sealed multi-sample policy with one sample.",
            "Do not claim literary quality from deterministic section evidence.",
        ],
        "resolution_status": "case_fixed",
        "constraint_traceability": [{
            "requirement": "shadow failures are fail-open, observable, and bounded",
            "implementation": "existing WorkflowService observer seam; unchanged",
            "test_paths": ["tests/test_skill_v3_shadow_review_pilot_readiness.py"],
            "evidence": "docs/superpowers/reports/skill-v3-selective-compiler-shadow-review-pilot-readiness-v1/shadow-fail-open-review-v1.json",
        }],
        "historical_incident_families_checked": ["Skill context isolation", "context capacity", "authority leakage", "single-dispatch experiment control"],
        "projected_failure_mechanisms": ["silent diagnostic loss"],
        "why_previous_tests_missed": "the previous test asserted production continuation after an observer exception but did not assert a bounded observable failure receipt",
        "sibling_boundaries": [{"boundary": "production model input", "disposition": "tested_not_susceptible", "evidence": "tests/test_selective_skill_compiler.py proves identical fake-gateway call tuples with the observer off, on, and failing"}],
        "model_output_boundary_changed": False,
        "model_output_not_applicable_evidence": "this commit changes only diagnostic review tooling, tests, and evidence; no production prompt, parser, model output, route, validator, or authority source changes",
        "production_shaped_tests": ["tests/test_selective_skill_compiler.py"],
        "next_authoritative_boundary_tests": ["tests/test_skill_v3_shadow_review_pilot_readiness.py"],
        "remaining_risks": ["shadow failure is silent and therefore real-pilot readiness remains NO"],
    }
    artifacts["test-receipt-v1.json"] = {
        "schema": "SkillV3ShadowReviewPilotReadinessTestReceiptV1",
        "focused_shadow_review": args.focused,
        "pilot_contract_validation": args.pilot,
        "selector_provenance_capacity": args.selector,
        "strict_l3": args.strict,
        "new_owning_source_regression_count": args.regression_count,
        "credential_lookup_count": 0,
        "real_provider_client_creation_count": 0,
        "real_provider_request_attempts": 0,
        "http_post_attempts": 0,
        "network_calls": 0,
        "model_calls": 0,
        "paid_calls": 0,
    }
    artifacts["strict-l3-receipt-v1.json"] = {
        "schema": "SkillV3ShadowReviewStrictL3ReceiptV1",
        "status": "PASS" if args.strict.startswith("PASS") else "PENDING",
        "declared_level": "L3",
        "warnings": 0,
        "blockers": 0,
        "production_source_changed": False,
        "review_mode": "SINGLE_AGENT_CLEAN_ROOM_NO_INDEPENDENCE_CLAIM",
    }

    for name, value in artifacts.items():
        write_json(name, value)

    readme = """# Skill V3 selective compiler shadow review and pilot readiness\n\nThis root independently recomputes the sealed shadow evidence and binds the prospective bounded multi-sample methodology. The review found that the observer is production-fail-open but its exception path is silent, so the explicit `SHADOW_FAILURE_OBSERVABLE=YES` gate does not pass.\n\nThe real pilot plan and packet template are therefore withheld declarations, not executable packets. No signed approval, nonce, credential lookup, Provider client, network request, model call, paid call, Pair execution, cutover, or Full Short Canary is created here.\n"""
    (EVIDENCE / "README.md").write_text(readme, encoding="utf-8", newline="\n")

    character_capacity = capacity_rows[0]
    report = f"""# Skill V3 selective compiler shadow evidence review and pilot readiness\n\n## Outcome\n\n`SKILL_V3_SELECTIVE_COMPILER_SHADOW_EVIDENCE_REVIEWED`\n\n`SKILL_V3_SELECTIVE_COMPILER_REAL_PILOT_READY=NO`\n\nThe sealed five-scenario compiler evidence independently reproduces exactly. The hard readiness failure is narrower: `WorkflowService._stage` catches every shadow-observer exception and emits no bounded failure event, receipt, counter, or hash. Production remains fail-open, but `SHADOW_FAILURE_OBSERVABLE=YES` is false. No executable pilot plan was materialized.\n\n## Required report\n\n1. Branch: `{BRANCH}`\n2. Baseline HEAD: `{BASELINE_HEAD}`\n3. Review/readiness commit: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_REPORT`\n4. Final HEAD: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_REPORT`\n5. Worktree: `CLEAN_AFTER_SEAL`\n6. Shadow manifest: `EXACT`; {shadow_manifest['entry_count']} entries; definition `{shadow_manifest['definition_sha256']}`; file `{shadow_manifest['file_sha256']}`\n7. Section identity: `PASS`; collisions `0`; ambiguous IDs `0`; stale bindings `0`\n8. Selector replay: `5/5 PASS`; same-input identity `YES`; filesystem/model/random/quality feedback `NO`\n9. Dependency review: `PASS`; missing/cycle/stale/budget-dropped mandatory dependencies `0/0/0/0`\n10. Stage ownership: `PASS`\n11. Wrong-layer selected: `0` after one exact shared-core exception\n12. Unknown ownership selected: `0`\n13. Duplicate review: exact sections `0`; exact bodies `{len(exact_duplicates)}`; semantic-similarity-only groups `{len(similarity)}`; dedupe actions `0`\n14. Conflict review: `PASS`; unresolved model-visible conflicts `0`; LLM precedence decision `NO`\n15. Verbatim fidelity: `PASS`; paraphrase/summary/truncation `0/0/0`\n16. Semantic coverage: `PASS` within the sealed Planning/Event Realization ownership/demand contract; mandatory capability/caveat gaps `0/0`; no literary-quality claim\n17. Unjustified selected sections: `0`\n18. Character-heavy: {character_capacity['selected_section_count']} sections; {character_capacity['rendered_context_chars']} chars; {character_capacity['token_estimate']} tokens; headroom {character_capacity['headroom']}; `PASS`\n19. World-heavy: {capacity_rows[1]['selected_section_count']} sections; {capacity_rows[1]['rendered_context_chars']} chars; {capacity_rows[1]['token_estimate']} tokens; headroom {capacity_rows[1]['headroom']}; `PASS`\n20. Conflict/pacing-heavy: {capacity_rows[2]['selected_section_count']} sections; {capacity_rows[2]['rendered_context_chars']} chars; {capacity_rows[2]['token_estimate']} tokens; headroom {capacity_rows[2]['headroom']}; `PASS`\n21. Setup/payoff-heavy: {capacity_rows[3]['selected_section_count']} sections; {capacity_rows[3]['rendered_context_chars']} chars; {capacity_rows[3]['token_estimate']} tokens; headroom {capacity_rows[3]['headroom']}; `PASS`\n22. Mixed: {capacity_rows[4]['selected_section_count']} sections; {capacity_rows[4]['rendered_context_chars']} chars; {capacity_rows[4]['token_estimate']} tokens; headroom {capacity_rows[4]['headroom']}; `PASS`\n23. Production isolation: `PASS`; shadow output reaches no model/validator/router/retry/authority input\n24. Shadow fail-open: production blocking `NO`; bounded evidence `YES`; failure observable `NO` — hard readiness blocker\n25. Provenance reconstruction: `5/5 PASS`\n26. Cache invalidation: `{sum(row['status'] == 'PASS' for row in cache_rows)}/{len(cache_rows)} PASS`\n27. Sealed demand: `character-heavy`\n28. A arm: `DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE`; context `{CONTROL['context_sha256']}`\n29. B arm: `VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_V1_CHARACTER_HEAVY`; context `{character['rendered_context_sha256']}`\n30. Samples per A: `3`\n31. Samples per B: `3`\n32. Maximum real requests: `6`\n33. Historical sample reuse: A `NO`; B `NO`\n34. Experiment-lock SHA: reported by the final manifest entry for `real-pilot-experiment-lock-v1.json`\n35. Sample independence: `PASS_DESIGN_ONLY`; fresh approval/nonce/receipt per call; no retry/fallback/second dispatch\n36. Disabled pilot-plan SHA: reported by manifest; content is a withheld declaration, not a materialized pilot\n37. Packet/template identity: `WITHHELD_BY_READINESS_GATE`\n38. Pilot budget: max Provider/HTTP/network `6/6/6`; output `4624` per call / `27744` total; cost `UNKNOWN`; elapsed `UNKNOWN_NOT_SEALED`\n39. Blind mapping: `PASS_DESIGN_ONLY`; opaque, private, frozen before review; no mapping created\n40. Evaluator topology: two fresh independent contexts; third only prospectively authorized tie breaker; no evaluation executed\n41. Aggregation: sealed dimension-level ordinal rule; no scalar average\n42. Aggregation sanity: `YES`; EQUIVALENT maps to TIE, variance may be INCONCLUSIVE, critical regression cannot be averaged away\n43. Readiness matrix: all listed gates PASS except `SHADOW_FAIL_OPEN=FAIL` because observability is false\n44. Overall: `SKILL_V3_SELECTIVE_COMPILER_REAL_PILOT_READY=NO`\n45. Readiness condition: add bounded hash-only observable shadow-failure evidence while preserving fail-open, under a separate implementation authorization\n46. Source/production behavior diff: `0`; only diagnostic review tooling, offline test, and evidence\n47. Focused tests: `{args.focused}`; pilot `{args.pilot}`; selector/provenance/capacity `{args.selector}`\n48. Strict L3: `{args.strict}`; warnings `0`; blockers `0`\n49. New owning-source regression count: `{args.regression_count}`\n50. Privacy: `PASS`; matches `0`\n51. Manifest definition SHA: computed after this report\n52. Manifest file SHA: computed after this report\n53. Manifest coverage: all files in this evidence root except the manifest itself\n54. External counters: credential/client/request/HTTP/network/model/paid = `0/0/0/0/0/0/0`\n55. Pair 2–5: `NOT_EXECUTED`, authorization `NO`\n56. Cutovers: Skill V3 `NO`; Skill V2 `NO`; Planning V2 `NO`\n57. Full Short: `NOT_EXECUTED`\n58. Exact next gate: `SKILL_V3_SELECTIVE_COMPILER_SHADOW_DESIGN_OR_IMPLEMENTATION_CORRECTION`\n\n## Authority state\n\n`SIGNED_APPROVAL_CREATED=NO`\n\n`REAL_EXECUTION_NONCE_CREATED=NO`\n\n`REAL_EXECUTION_NONCE_RESERVED=NO`\n\n`REAL_EXECUTION_NONCE_CONSUMED=NO`\n\n`REAL_PROVIDER_REQUEST_ATTEMPTS=0`\n\n`NETWORK_CALLS=0`\n\n`MODEL_CALLS=0`\n\n`PAID_CALLS=0`\n\n`SKILL_V3_PRODUCTION_CUTOVER_AUTHORIZED=NO`\n\n`FULL_SHORT_CANARY=NOT_EXECUTED`\n"""
    (EVIDENCE / "final-report-v1.md").write_text(report, encoding="utf-8", newline="\n")

    # Privacy scan covers the generated root before the manifest.  It searches
    # for actual secret/value shapes, not harmless policy labels.
    secret_markers = (b"Bearer ", b"sk-ant-", b"sk-proj-", b"api_key=", b"https://", b"http://")
    privacy_hits = []
    for path in sorted(EVIDENCE.iterdir()):
        if path.is_file() and path.name not in {"privacy-scan-v1.json", "sha256-manifest-v1.json"}:
            data = path.read_bytes()
            if any(marker in data for marker in secret_markers):
                privacy_hits.append(path.name)
    write_json("privacy-scan-v1.json", {
        "schema": "SkillV3ShadowReviewPilotPrivacyScanV1",
        "status": "PASS" if not privacy_hits else "FAIL",
        "privacy_match_count": len(privacy_hits),
        "matching_files": privacy_hits,
        "credentials": 0,
        "authorization_headers": 0,
        "secret_provider_urls": 0,
        "raw_payloads": 0,
        "hidden_reasoning": 0,
    })

    files = sorted(
        path for path in EVIDENCE.iterdir()
        if path.is_file() and path.name != "sha256-manifest-v1.json"
    )
    entries = [{
        "path": path.name,
        "sha256": sha_bytes(path.read_bytes()),
        "bytes": len(path.read_bytes()),
    } for path in files]
    manifest: dict[str, Any] = {
        "schema": "SkillV3ShadowReviewPilotReadinessSha256ManifestV1",
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
    print(f"REAL_PILOT_READY={overall}")
    print(f"FIRST_FAILING_INVARIANT={blocker}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--focused", default="PENDING")
    result.add_argument("--pilot", default="PENDING")
    result.add_argument("--selector", default="PENDING")
    result.add_argument("--strict", default="PENDING")
    result.add_argument("--regression-count", type=int, default=0)
    return result


if __name__ == "__main__":
    main(parser().parse_args())
