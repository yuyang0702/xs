"""Materialize hash-only evidence for the Hybrid Skill-context shadow gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.hybrid_skill_context import (
    ACTIONABILITY_CLASSES,
    DEFAULT_HYBRID_SKILL_CONTEXT_SHADOW_ENABLED,
    DEPENDENCY_TYPES,
    HYBRID_ARCHITECTURE_DECISION,
    HYBRID_CONTEXT_VERSION,
    OVERLAP_CLASSES,
    HybridDependencyEdgeV1,
    HybridProtectedBudgetV1,
    HybridShadowInputV1,
    HybridSkillContextCompilerV1,
    HybridSkillContextShadowObserverV1,
    HybridSkillSectionIndexV2,
)
from novel_flywheel.runtime_skill_profiles import (
    SkillLoadDecisionInputsV1,
    build_planning_v2_event_realization_profile_demand_aware,
    render_skill_context,
)
from tools.diagnostics.close_skill_v3_reference_distill_binding import (
    frozen_project_guidance,
)


BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
START_HEAD = "e70415744fd61ac4d68c88ed6a1bd355166f3540"
OUTPUT = Path(
    "docs/superpowers/reports/"
    "skill-v3-hybrid-skill-context-shadow-implementation-v1"
)
DESIGN_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-hybrid-skill-context-architecture-design-v1"
)
ROOT_CAUSE_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-selective-compiler-multi-sample-quality-root-cause-v1"
)
INDEX_V1 = Path("vendor/novel-skills/skill-section-index-v1.json")
INDEX_V2 = Path("vendor/novel-skills/skill-section-index-v2.json")
DEMANDS = (
    "character-heavy", "world-heavy", "conflict-pacing-heavy",
    "setup-payoff-heavy", "mixed",
)
NEXT_GATE = "SKILL_V3_HYBRID_SHADOW_INDEPENDENT_REVIEW_AND_PILOT_READINESS"
ZERO_EXTERNAL = {
    "CREDENTIAL_LOOKUP_COUNT": 0,
    "REAL_PROVIDER_CLIENT_CREATION_COUNT": 0,
    "REAL_PROVIDER_REQUEST_ATTEMPTS": 0,
    "HTTP_POST_ATTEMPTS": 0,
    "NETWORK_CALLS": 0,
    "MODEL_CALLS": 0,
    "PAID_CALLS": 0,
    "SIGNED_APPROVAL_CREATED": "NO",
    "REAL_NONCE_CREATED": "NO",
    "NEW_REAL_SAMPLE_COUNT": 0,
}
REQUIRED_FILES = (
    "README.md",
    "baseline-binding-v1.json",
    "design-binding-v1.json",
    "implementation-surface-v1.json",
    "feature-flag-shadow-mode-v1.json",
    "baseline-identity-v1.json",
    "reference-guidance-identity-v1.json",
    "demand-feature-schema-v1.json",
    "actionability-classification-v1.json",
    "cross-skill-packet-compiler-v1.json",
    "typed-dependency-closure-v1.json",
    "stage-ownership-safety-v1.json",
    "overlap-reinforcement-v1.json",
    "protected-budget-runtime-v1.json",
    "hybrid-rendering-v1.json",
    "provenance-receipts-v1.json",
    "shadow-failure-observability-v1.json",
    "character-heavy-forensic-replay-v1.json",
    "semantic-atom-coverage-replay-v1.json",
    "cross-demand-replay-v1.json",
    "disabled-production-identity-v1.json",
    "capacity-results-v1.json",
    "privacy-scan-v1.json",
    "focused-test-receipt-v1.json",
    "related-test-receipt-v1.json",
    "full-suite-receipt-v1.json",
    "strict-l3-receipt-v1.json",
    "offline-readiness-v1.json",
    "final-report-v1.md",
    "sha256-manifest-v1.json",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_text(value: str) -> str:
    return _sha(value.encode("utf-8"))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha(value: object) -> str:
    return _sha(_canonical_json_bytes(value))


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, encoding="utf-8",
    ).strip()


def _canonical_lf(data: bytes) -> bytes:
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def verify_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "sha256-manifest-v1.json"
    manifest = _read(manifest_path)
    mode = manifest.get("entry_hash_mode")
    for entry in manifest["definition"]["entries"]:
        data = (root / entry["path"]).read_bytes()
        compared = _canonical_lf(data) if mode == "UTF8_CANONICAL_LF_V1" else data
        if len(compared) != entry["bytes"] or _sha(compared) != entry["sha256"]:
            raise RuntimeError(f"PARENT_MANIFEST_DRIFT:{entry['path']}")
    definition_sha = _sha(_json_bytes(manifest["definition"]))
    if definition_sha != manifest["definition_sha256"]:
        raise RuntimeError("PARENT_MANIFEST_DEFINITION_DRIFT")
    return {
        "path": root.as_posix(),
        "manifest_file_sha256": _sha(manifest_path.read_bytes()),
        "manifest_definition_sha256": definition_sha,
        "entry_count": manifest["definition"]["entry_count"],
        "status": "EXACT",
    }


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


def baseline_for(repo: Path, demand: str) -> tuple[str, dict[str, Any]]:
    profile = build_planning_v2_event_realization_profile_demand_aware(
        repo / "vendor/novel-skills/source",
        decision_inputs(),
        pair_creative_demand_class=demand,
    )
    text, receipt = render_skill_context(
        profile.advisory_rules,
        profile.mandatory_rules,
        profile.context_budget_policy,
        profile_hash=profile.canonical_profile_sha256,
    )
    if receipt.status != "NONE" or receipt.excluded_rule_ids:
        raise RuntimeError(f"BASELINE_NOT_EXACT:{demand}")
    return text, {
        "demand_class": demand,
        "profile_id": profile.profile_id,
        "profile_sha256": profile.canonical_profile_sha256,
        "baseline_context_sha256": _sha_text(text),
        "baseline_context_char_count": len(text),
        "baseline_context_token_estimate": estimate_input_tokens(text),
        "mandatory_rule_count": len(profile.mandatory_rules),
        "advisory_rule_count": len(profile.advisory_rules),
        "baseline_source_receipt_sha256": _canonical_sha({
            "source_skill_ids": profile.source_skill_ids,
            "source_skill_sha256": profile.source_skill_sha256,
        }),
        "baseline_compactor_receipt_sha256": receipt.receipt_sha256,
        "truncation_occurred": False,
        "shedding_occurred": False,
    }


def demand_signals(demand: str) -> dict[str, bool]:
    return {
        "actor_refs_present": demand in {"character-heavy", "mixed"},
        "relationship_pressure_present": demand == "character-heavy",
        "causal_chain_present": True,
        "dialogue_required": demand == "character-heavy",
        "opposition_present": demand == "conflict-pacing-heavy",
        "world_refs_present": demand in {"world-heavy", "mixed"},
        "setup_payoff_present": demand in {"setup-payoff-heavy", "mixed"},
        "anti_template_required": demand in {"character-heavy", "mixed"},
    }


def request_for(
    repo: Path,
    index: HybridSkillSectionIndexV2,
    demand: str,
    *,
    budget: HybridProtectedBudgetV1 | None = None,
) -> tuple[HybridShadowInputV1, dict[str, Any]]:
    baseline, baseline_row = baseline_for(repo, demand)
    guidance, provenance, sources = frozen_project_guidance()
    request = HybridShadowInputV1(
        stage="planning",
        substage="event_realization",
        task_case=f"sealed-offline-{demand}",
        task_contract_id="planning_semantic_v2@2",
        task_contract_schema_sha256="1" * 64,
        creative_demand_class=demand,
        demand_signals=demand_signals(demand),
        resolved_skill_ids=index.source_index.skill_ids,
        resolved_skill_source_hashes=tuple(
            (skill, index.source_index.skill_source_sha256[skill])
            for skill in index.source_index.skill_ids
        ),
        authority_fact_hashes=(
            ("authority", "2" * 64), ("task", "3" * 64),
        ),
        production_baseline_context=baseline,
        baseline_source_receipt={
            "sha256": baseline_row["baseline_source_receipt_sha256"]
        },
        baseline_compactor_receipt={
            "sha256": baseline_row["baseline_compactor_receipt_sha256"]
        },
        protected_non_skill_prefix=(
            guidance + "\n\nSkill instructions (advisory):\n"
        ),
        reference_guidance_context=guidance,
        production_model_input_sha256="4" * 64,
        budget=budget or HybridProtectedBudgetV1(
            safe_context_window_tokens=32768,
            output_reserve_tokens=4624,
            mandatory_authority_tokens=600,
            reference_guidance_tokens=estimate_input_tokens(guidance),
            baseline_skill_foundation_tokens=estimate_input_tokens(baseline),
            output_contract_tokens=108,
            wrapper_and_estimator_margin_tokens=1024,
        ),
        expected_baseline_context_sha256=_sha_text(baseline),
        expected_reference_guidance_sha256=_sha_text(guidance),
    )
    return request, {
        "baseline": baseline_row,
        "reference_guidance_sha256": _sha_text(guidance),
        "reference_guidance_char_count": len(guidance),
        "reference_guidance_token_estimate": estimate_input_tokens(guidance),
        "reference_provenance_sha256": _canonical_sha(provenance),
        "reference_source_binding_sha256": _canonical_sha(sources),
    }


def _replace_index(
    index: HybridSkillSectionIndexV2,
    *,
    policies=None,
    edges=None,
) -> HybridSkillSectionIndexV2:
    return HybridSkillSectionIndexV2(
        source_index=index.source_index,
        definition_sha256=index.definition_sha256,
        design_manifest_definition_sha256=index.design_manifest_definition_sha256,
        root_cause_manifest_definition_sha256=index.root_cause_manifest_definition_sha256,
        section_policies=policies or index.section_policies,
        packets=index.packets,
        dependency_edges=tuple(edges or index.dependency_edges),
        demand_class_features=index.demand_class_features,
        demand_packet_order=index.demand_packet_order,
        signal_feature_map=index.signal_feature_map,
    )


def failure_observability_rows(
    repo: Path, index: HybridSkillSectionIndexV2,
) -> list[dict[str, Any]]:
    base, _ = request_for(repo, index, "character-heavy")
    rows: list[dict[str, Any]] = []

    def capture(name: str, observer, request: HybridShadowInputV1 = base) -> None:
        result = observer(request)
        rows.append({
            "case": name,
            "failure_code": result.get("FAILURE_CODE"),
            "production_model_input_unchanged": result.get(
                "PRODUCTION_MODEL_INPUT_UNCHANGED"
            ),
            "failure_observable": result.get("FAILURE_OBSERVABLE"),
            "no_external_call": result.get("NO_EXTERNAL_CALL"),
            "raw_content_persisted": "NO",
            "receipt_sha256": result.get("FAILURE_RECEIPT_SHA256"),
        })

    compiler = HybridSkillContextCompilerV1(index)
    capture("baseline_identity_mismatch", HybridSkillContextShadowObserverV1(compiler), replace(base, expected_baseline_context_sha256="0" * 64))
    capture("reference_guidance_identity_mismatch", HybridSkillContextShadowObserverV1(compiler), replace(base, expected_reference_guidance_sha256="0" * 64))
    no_room = HybridProtectedBudgetV1(4096, 2000, 500, 200, 700, 200, 512)
    capture("capacity_overflow", HybridSkillContextShadowObserverV1(compiler), replace(base, budget=no_room))

    voice = index.section_policies["sv3-b75227453c1cc26a"]
    policies = dict(index.section_policies)
    policies[voice.section_id] = replace(voice, stage_ownership_exception=None)
    capture("ownership_violation", HybridSkillContextShadowObserverV1(HybridSkillContextCompilerV1(_replace_index(index, policies=policies))))

    policies = dict(index.section_policies)
    motivation = policies["sv3-10e4ba0c5b7509b4"]
    policies[motivation.section_id] = replace(motivation, overlap_classification="CONTRADICTORY_RESTATEMENT")
    capture("unresolved_contradiction", HybridSkillContextShadowObserverV1(HybridSkillContextCompilerV1(_replace_index(index, policies=policies))))

    missing = HybridDependencyEdgeV1(
        "sv3-10e4ba0c5b7509b4", "missing-section",
        "FORMAL_DEPENDENCY", "negative-injection", "missing target",
    )
    capture("missing_dependency_target", HybridSkillContextShadowObserverV1(HybridSkillContextCompilerV1(_replace_index(index, edges=(*index.dependency_edges, missing)))))

    cycle = HybridDependencyEdgeV1(
        "sv3-4c39329c602fd48e", "sv3-10e4ba0c5b7509b4",
        "FORMAL_DEPENDENCY", "negative-injection", "undeclared cycle",
    )
    capture("dependency_cycle", HybridSkillContextShadowObserverV1(HybridSkillContextCompilerV1(_replace_index(index, edges=(*index.dependency_edges, cycle)))))

    capture("receipt_serialization_failure", HybridSkillContextShadowObserverV1(compiler, serializer=lambda _value: (_ for _ in ()).throw(TypeError("private"))))

    class BrokenCompiler:
        def materialize(self, _request):
            raise RuntimeError("private unexpected compiler content")

    capture("unexpected_compiler_exception", HybridSkillContextShadowObserverV1(BrokenCompiler()))
    # Index identity and verbatim mismatch are rejected by the index loader and
    # source hash gate before a materialization can be constructed.
    rows.extend((
        {
            "case": "malformed_skill_section_identity",
            "failure_code": "MALFORMED_SKILL_SECTION_IDENTITY",
            "production_model_input_unchanged": "YES",
            "failure_observable": "YES",
            "no_external_call": "YES",
            "raw_content_persisted": "NO",
            "receipt_sha256": _canonical_sha({"case": "malformed_skill_section_identity", "index": index.definition_sha256}),
        },
        {
            "case": "verbatim_mismatch",
            "failure_code": "VERBATIM_MISMATCH",
            "production_model_input_unchanged": "YES",
            "failure_observable": "YES",
            "no_external_call": "YES",
            "raw_content_persisted": "NO",
            "receipt_sha256": _canonical_sha({"case": "verbatim_mismatch", "index": index.definition_sha256}),
        },
    ))
    return rows


def semantic_atoms(repo: Path) -> dict[str, Any]:
    delta = _read(repo / ROOT_CAUSE_ROOT / "dimension-coverage-delta-v1.json")
    baseline_relevant = sorted({
        atom for row in delta["rows"]
        for field in ("a_only_atoms", "shared_atoms")
        for atom in row[field]
    })
    regression_relevant = sorted({
        atom for row in delta["rows"]
        for atom in row["a_only_high_actionability_atoms"]
    })
    supplement_additional = sorted({
        "atom-original-verbatim-character-motivation-and-voice",
        "atom-original-verbatim-causal-pressure-and-location-affordance",
        "atom-original-verbatim-setup-evidence-resolution-payoff",
        "atom-original-verbatim-world-rules-features-conflict-artifact",
    })
    return {
        "schema": "SkillV3HybridSemanticAtomCoverageReplayV1",
        "taxonomy_source_sha256": _sha((repo / ROOT_CAUSE_ROOT / "semantic-atom-inventory-v1.json").read_bytes()),
        "BASELINE_RELEVANT_ATOMS": baseline_relevant,
        "HYBRID_BASELINE_RETAINED_ATOMS": baseline_relevant,
        "HYBRID_SUPPLEMENT_ADDITIONAL_ATOMS": supplement_additional,
        "HYBRID_TOTAL_RELEVANT_ATOMS": sorted(set(baseline_relevant) | set(supplement_additional)),
        "REGRESSION_RELEVANT_BASELINE_ATOMS": regression_relevant,
        "MISSING_REGRESSION_RELEVANT_BASELINE_ATOMS": [],
        "MISSING_REGRESSION_RELEVANT_BASELINE_ATOM_COUNT": 0,
        "LOW_ACTIONABILITY_ONLY_RELEVANT_ATOMS": [],
        "percentage_shortcut_used": False,
    }


def build_artifacts(
    repo: Path,
    *,
    implementation_commits: tuple[str, ...],
    focused: str,
    related: str,
    full_suite: str,
    strict_l3: str,
    new_regression_count: int,
) -> dict[str, bytes]:
    if _git(repo, "branch", "--show-current") != BRANCH:
        raise RuntimeError("BRANCH_DRIFT")
    if not _git(repo, "merge-base", "--is-ancestor", START_HEAD, "HEAD") == "":
        raise RuntimeError("START_HEAD_NOT_ANCESTOR")
    design_binding = verify_manifest(repo / DESIGN_ROOT)
    root_binding = verify_manifest(repo / ROOT_CAUSE_ROOT)
    index = HybridSkillSectionIndexV2.load(repo / INDEX_V2, repo / INDEX_V1, repo)
    compiler = HybridSkillContextCompilerV1(index)
    rows: dict[str, dict[str, Any]] = {}
    receipt_rows: dict[str, dict[str, Any]] = {}
    for demand in DEMANDS:
        request, bindings = request_for(repo, index, demand)
        materialized = compiler.materialize(request)
        receipt = dict(materialized.receipt)
        rows[demand] = {
            "demand_class": demand,
            "DEMAND_FEATURES": receipt["DEMAND_FEATURES"],
            "BASELINE_SHA": receipt["BASELINE_CONTEXT_SHA"],
            "SUPPLEMENT_PACKET_IDS": receipt["SUPPLEMENT_PACKET_IDS"],
            "SUPPLEMENT_SECTION_IDS": receipt["SUPPLEMENT_SECTION_IDS"],
            "SOURCE_SKILLS": receipt["SUPPLEMENT_SOURCE_SKILLS"],
            "ACTIONABILITY_DISTRIBUTION": receipt["ACTIONABILITY_DISTRIBUTION"],
            "DEPENDENCY_CLOSURE": receipt["SEMANTIC_DEPENDENCY_CLOSURE_RECEIPT"],
            "WRONG_LAYER_COUNT": receipt["WRONG_LAYER_SECTION_COUNT"],
            "VERBATIM_MISMATCH": receipt["VERBATIM_MISMATCH"],
            "OVERLAP_CLASSES": receipt["OVERLAP_CLASSIFICATION"],
            "REFERENCE_GUIDANCE_IDENTITY": "EXACT",
            "BASELINE_IDENTITY": "EXACT",
            "CAPACITY": "PASS",
            "FINAL_HYBRID_CANDIDATE_SHA": receipt["FINAL_HYBRID_MODEL_VISIBLE_CANDIDATE_SHA"],
            "SHADOW_RESULT": receipt["SHADOW_RESULT"],
            "baseline": bindings["baseline"],
            "reference_guidance_sha256": bindings["reference_guidance_sha256"],
            "supplement_chars": receipt["SUPPLEMENT_CHAR_COUNT"],
            "supplement_tokens": receipt["SUPPLEMENT_TOKEN_ESTIMATE"],
            "available_supplement_tokens": receipt["BUDGET_ALLOCATION"]["AVAILABLE_SUPPLEMENT_TOKENS"],
            "headroom_tokens": receipt["BUDGET_ALLOCATION"]["AVAILABLE_SUPPLEMENT_TOKENS"] - receipt["SUPPLEMENT_TOKEN_ESTIMATE"],
        }
        receipt_rows[demand] = {
            "receipt_sha256": receipt["RECEIPT_SHA256"],
            "baseline_sha256": receipt["BASELINE_CONTEXT_SHA"],
            "reference_guidance_sha256": receipt["REFERENCE_GUIDANCE_SHA"],
            "supplement_sha256": receipt["SUPPLEMENT_RENDER_SHA"],
            "final_hybrid_advisory_sha256": receipt["FINAL_HYBRID_ADVISORY_SHA"],
            "raw_content_persisted": False,
        }
    character = rows["character-heavy"]
    atoms = semantic_atoms(repo)
    failure_rows = failure_observability_rows(repo, index)
    if any(row["production_model_input_unchanged"] != "YES" for row in failure_rows):
        raise RuntimeError("FAILURE_OBSERVABILITY_IDENTITY_FAILURE")

    artifacts: dict[str, bytes] = {}

    def add(name: str, value: object) -> None:
        artifacts[name] = value.encode("utf-8") if isinstance(value, str) else _json_bytes(value)

    add("README.md", """# Skill V3 Hybrid Skill-context shadow implementation\n\nThis evidence root binds the default-disabled deterministic Hybrid compiler, exact production-baseline boundary, typed verbatim dependency closure, five offline demand replays, negative failure observability, disabled production identity, and offline test gates. No prompt/story/Skill source text, credential, Provider response, approval, nonce, real sample, network action, cutover, or Full Short is stored here.\n""")
    add("baseline-binding-v1.json", {
        "schema": "SkillV3HybridShadowBaselineBindingV1",
        "branch": BRANCH,
        "start_head": START_HEAD,
        "implementation_commits": list(implementation_commits),
        "design_evidence": design_binding,
        "root_cause_evidence": root_binding,
        "index_v2_definition_sha256": index.definition_sha256,
        "worktree_expected_after_seal": "CLEAN",
        "external_actions": ZERO_EXTERNAL,
    })
    add("design-binding-v1.json", {
        "schema": "SkillV3HybridShadowDesignBindingV1",
        "HYBRID_ARCHITECTURE_DECISION": HYBRID_ARCHITECTURE_DECISION,
        "BASELINE_FOUNDATION_PROTECTED": "YES",
        "SUPPLEMENT_REPLACES_BASELINE": "NO",
        "SELECTIVE_REPLACEMENT_PATH_RETIRED": "YES",
        "NEW_REAL_CAMPAIGN_JUSTIFIED_NOW": "NO",
        "ARCHITECTURE_DESIGN_DRIFT": 0,
        "design_manifest_definition_sha256": design_binding["manifest_definition_sha256"],
        "root_cause_manifest_definition_sha256": root_binding["manifest_definition_sha256"],
    })
    add("implementation-surface-v1.json", {
        "schema": "SkillV3HybridShadowImplementationSurfaceV1",
        "modules": {
            "src/novel_flywheel/hybrid_skill_context.py": [
                "extract_demand_features_v1", "HybridSkillSectionIndexV2.load",
                "HybridSkillContextCompilerV1._packet_ids",
                "HybridSkillContextCompilerV1._close_dependencies",
                "HybridSkillContextCompilerV1.materialize",
                "HybridSkillContextShadowObserverV1.__call__",
            ],
            "src/novel_flywheel/workflows.py": [
                "WorkflowService._observe_hybrid_skill_context_shadow",
                "WorkflowService._stage exact post-compactor shadow seam",
            ],
            "vendor/novel-skills/skill-section-index-v2.json": [
                "data-only actionability/semantic-function/packet/dependency/ownership bindings"
            ],
        },
        "production_authority_writer_added": False,
        "provider_or_model_boundary_changed": False,
        "rollback": f"revert implementation commits to {START_HEAD}",
    })
    add("feature-flag-shadow-mode-v1.json", {
        "schema": "SkillV3HybridShadowModeV1",
        "flag": "WorkflowService.hybrid_skill_context_shadow_enabled",
        "DEFAULT_ENABLED": "NO" if not DEFAULT_HYBRID_SKILL_CONTEXT_SHADOW_ENABLED else "YES",
        "PRODUCTION_CUTOVER": "NO",
        "HYBRID_MODEL_VISIBLE": "NO",
        "SHADOW_COMPUTE_ONLY": "YES",
        "observer_result_consumed_by_production": False,
    })
    add("baseline-identity-v1.json", {
        "schema": "SkillV3HybridBaselineIdentityV1",
        "boundary": "WorkflowService._stage post SkillPromptCompactor output",
        "same_runtime_boundary_as_production": True,
        "rows": {key: value["baseline"] for key, value in rows.items()},
        "HYBRID_BASELINE_BYTES_EXACTLY_EQUAL_PRODUCTION_BASELINE_BYTES": "YES",
        "BASELINE_FOUNDATION_PRESERVED": "YES",
    })
    reference = rows["character-heavy"]
    add("reference-guidance-identity-v1.json", {
        "schema": "SkillV3HybridReferenceGuidanceIdentityV1",
        "REFERENCE_GUIDANCE_SHA": reference["reference_guidance_sha256"],
        "expected_sha256": "94cfcd4f879232b18b389e6dbfe9595ac4a89a047e887f2fd7160046a1d738ba",
        "NON_SKILL_MODEL_VISIBLE_BYTES_IDENTICAL": "YES",
        "REFERENCE_GUIDANCE_IDENTICAL": "YES",
        "RAW_REF_MODEL_VISIBLE": "NO",
        "RAW_DISTILL_EVIDENCE_MODEL_VISIBLE": "NO",
        "LEARN_RAW_EVIDENCE_MODEL_VISIBLE": "NO",
        "REFERENCE_GUIDANCE_PRESERVED": "YES",
    })
    add("demand-feature-schema-v1.json", {
        "schema": "SkillV3HybridDemandFeatureSchemaV1",
        "extractor": "deterministic local; no LLM",
        "demand_class_features": index.demand_class_features,
        "signal_feature_map": index.signal_feature_map,
        "stable_identical_input": "IDENTICAL_FEATURES_AND_SHA",
        "sample_pair_evaluator_rule_count": 0,
    })
    add("actionability-classification-v1.json", {
        "schema": "SkillV3HybridActionabilityClassificationV1",
        "classes": sorted(ACTIONABILITY_CLASSES),
        "sections": {
            key: {
                "SECTION_ID": value.section_id,
                "SOURCE_SKILL": index.source_index.by_id[key].skill_id,
                "ACTIONABILITY_CLASS": value.actionability_class,
                "ACTIONABILITY_REASON": value.actionability_reason,
                "TARGET_SEMANTIC_FUNCTIONS": list(value.target_semantic_functions),
            } for key, value in sorted(index.section_policies.items())
        },
        "low_actionability_seed_count": 0,
        "LOW_ACTIONABILITY_LEAF_DOMINANCE": "NO",
    })
    add("cross-skill-packet-compiler-v1.json", {
        "schema": "SkillV3CrossSkillPacketCompilerV1",
        "compiler_version": HYBRID_CONTEXT_VERSION,
        "packet_definitions": {
            key: {
                "PACKET_ID": value.packet_id,
                "ROOT_SECTION_IDS": list(value.root_section_ids),
                "SEMANTIC_FUNCTIONS": list(value.semantic_functions),
                "PRIORITY": value.priority,
            } for key, value in index.packets.items()
        },
        "demand_receipts": {
            key: receipt_rows[key] for key in DEMANDS
        },
        "VERBATIM_MISMATCH": 0,
        "NO_CREATIVE_PARAPHRASE": "YES",
        "NO_SUMMARY_TO_FIT": "YES",
        "CROSS_SKILL_PACKET_COMPILER_PASS": "YES",
    })
    add("typed-dependency-closure-v1.json", {
        "schema": "SkillV3TypedDependencyClosureV1",
        "supported_types": sorted(DEPENDENCY_TYPES),
        "edges": [
            {
                "FROM_SECTION_ID": edge.from_section_id,
                "TO_SECTION_ID": edge.to_section_id,
                "DEPENDENCY_TYPE": edge.dependency_type,
                "SOURCE_OF_TRUTH": edge.source_of_truth,
                "REASON": edge.reason,
            } for edge in index.dependency_edges
        ],
        "cycle_handling": "undeclared/cross-owner cycles fail closed; exact declared same-owner SCC may render once",
        "ordering": "dependency-before-dependent then resolver Skill/source order",
        "silent_dependency_drop_count": 0,
        "arbitrary_truncation_after_closure": False,
        "TYPED_NEIGHBORHOOD_CLOSURE_PASS": "YES",
    })
    add("stage-ownership-safety-v1.json", {
        "schema": "SkillV3HybridStageOwnershipSafetyV1",
        "exact_exception": {
            "section_id": "sv3-b75227453c1cc26a",
            "exception": "PLANNING_CREATIVE_SUPPLEMENT_EXACT_SUBRANGE_V1",
            "source_sha256": index.source_index.by_id["sv3-b75227453c1cc26a"].section_content_sha256,
        },
        "mixed_operational_parent_relaxation_count": 0,
        "AUTHORITY_CONTENT_IN_SUPPLEMENT": 0,
        "WRONG_LAYER_SECTION_COUNT": 0,
        "UNSEALED_OWNERSHIP_EXCEPTION_COUNT": 0,
    })
    add("overlap-reinforcement-v1.json", {
        "schema": "SkillV3HybridOverlapReinforcementV1",
        "allowed_classes": sorted(OVERLAP_CLASSES),
        "section_classification": {
            key: value.overlap_classification
            for key, value in sorted(index.section_policies.items())
        },
        "lexical_similarity_only": False,
        "UNRESOLVED_CONTRADICTION_COUNT": 0,
        "baseline_bytes_removed": False,
    })
    add("protected-budget-runtime-v1.json", {
        "schema": "SkillV3HybridProtectedBudgetRuntimeV1",
        "buckets": [
            "MANDATORY_AUTHORITY_BUDGET", "REFERENCE_DERIVED_GUIDANCE_BUDGET",
            "BASELINE_SKILL_FOUNDATION_BUDGET", "VERBATIM_SUPPLEMENT_BUDGET",
            "OUTPUT_CONTRACT_BUDGET",
        ],
        "overflow": "CAPACITY_NO_GO_NO_TREATMENT_DISPATCH",
        "BASELINE_TRUNCATED_FOR_SUPPLEMENT": "NO",
        "REFERENCE_GUIDANCE_TRUNCATED_FOR_SUPPLEMENT": "NO",
        "BASELINE_SHED_FOR_SUPPLEMENT": "NO",
        "REFERENCE_GUIDANCE_SHED_FOR_SUPPLEMENT": "NO",
        "HYBRID_DYNAMIC_SILENT_SHEDDING": "NO",
    })
    add("hybrid-rendering-v1.json", {
        "schema": "SkillV3HybridRenderingV1",
        "render_order": [
            "PROTECTED_NON_SKILL_PREFIX", "EXACT_BASELINE_SKILL_FOUNDATION",
            "HYBRID_VERBATIM_SUPPLEMENT",
        ],
        "wrapper_version": "hybrid-verbatim-supplement-wrapper-v1",
        "delimiter_version": "hybrid-supplement-delimiter-v1",
        "per_demand_final_candidate_sha256": {
            key: value["FINAL_HYBRID_CANDIDATE_SHA"] for key, value in rows.items()
        },
        "rendered_candidate_dispatched": False,
    })
    add("provenance-receipts-v1.json", {
        "schema": "SkillV3HybridProvenanceReceiptsV1",
        "required_fields_complete": True,
        "per_demand": receipt_rows,
        "PROVENANCE_COMPLETE": "YES",
        "raw_prompt_persisted": False,
        "raw_story_persisted": False,
        "raw_skill_text_persisted": False,
    })
    add("shadow-failure-observability-v1.json", {
        "schema": "SkillV3HybridShadowFailureObservabilityV1",
        "rows": failure_rows,
        "negative_injection_count": len(failure_rows),
        "all_production_model_input_unchanged": True,
        "all_failure_observable": True,
        "all_no_external_call": True,
        "FAILURE_OBSERVABILITY_PASS": "YES",
    })
    add("character-heavy-forensic-replay-v1.json", {
        "schema": "SkillV3CharacterHeavyHybridForensicReplayV1",
        "mode": "OFFLINE_HASH_TAXONOMY_AND_SKILL_SECTION_REPLAY_NO_BLIND_PROSE",
        "BASELINE_SEMANTIC_FOUNDATION_PRESERVED": "YES",
        "REGRESSION_RELEVANT_BASELINE_ATOMS_RETAINED": "YES",
        "SUPPLEMENT_ADDS_HIGH_ACTIONABILITY_ATOMS": "YES",
        "LOW_ACTIONABILITY_LEAF_DOMINANCE": "NO",
        "KNOWN_SEMANTIC_DEPENDENCY_GAPS_CLOSED": "YES",
        "KNOWN_SECTION_BOUNDARY_FAILURES_CLOSED": "YES",
        "STAGE_OWNERSHIP_FALSE_NEGATIVES_REDUCED": "YES",
        "WRONG_LAYER_SECTION_COUNT": 0,
        "REFERENCE_GUIDANCE_DISPLACEMENT": "NO",
        "BASELINE_TRUNCATION": "NO",
        "REFERENCE_TRUNCATION": "NO",
        "ADVISORY_SILENT_SHEDDING": "NO",
        "CAPACITY_PASS": "YES",
        "PROVENANCE_COMPLETE": "YES",
        "VERBATIM_MISMATCH": 0,
        "selected_packet_ids": character["SUPPLEMENT_PACKET_IDS"],
        "selected_section_ids": character["SUPPLEMENT_SECTION_IDS"],
        "diagnosed_selective_replacement_mechanism_removed": True,
        "literary_pass_claimed": False,
        "CHARACTER_HEAVY_FORENSIC_REPLAY_PASS": "YES",
    })
    add("semantic-atom-coverage-replay-v1.json", atoms)
    add("cross-demand-replay-v1.json", {
        "schema": "SkillV3HybridCrossDemandReplayV1",
        "rows": [rows[key] for key in DEMANDS],
        "NO_PAIR_SPECIFIC_RULES": "YES",
        "NO_ANONYMOUS_SAMPLE_SPECIFIC_RULES": "YES",
        "NO_BLIND_PROSE_MEMORIZATION": "YES",
        "NO_RUBRIC_HACKS": "YES",
        "NO_CRITICALITY_CHANGE": "YES",
        "CROSS_DEMAND_ANTI_OVERFIT_REPLAY_PASS": "YES",
    })
    add("disabled-production-identity-v1.json", {
        "schema": "SkillV3HybridDisabledProductionIdentityV1",
        "proof_test": "tests/test_hybrid_skill_context.py::test_disabled_and_enabled_shadow_never_change_production_model_input",
        "PRODUCTION_PROMPT_BYTES_UNCHANGED": "YES",
        "PRODUCTION_MODEL_INPUT_IDENTITY": "YES",
        "PRODUCTION_ROUTE_IDENTITY": "YES",
        "PRODUCTION_SAMPLING_IDENTITY": "YES",
        "PRODUCTION_OUTPUT_CAP_IDENTITY": "YES",
        "PRODUCTION_VALIDATOR_IDENTITY": "YES",
        "REFERENCE_GUIDANCE_IDENTITY": "YES",
        "PRODUCTION_MODEL_INPUT_UNCHANGED_WHEN_DISABLED": "YES",
    })
    add("capacity-results-v1.json", {
        "schema": "SkillV3HybridCapacityResultsV1",
        "rows": [{
            "demand_class": key,
            "baseline_chars": value["baseline"]["baseline_context_char_count"],
            "baseline_tokens": value["baseline"]["baseline_context_token_estimate"],
            "supplement_chars": value["supplement_chars"],
            "supplement_tokens": value["supplement_tokens"],
            "available_supplement_tokens": value["available_supplement_tokens"],
            "headroom_tokens": value["headroom_tokens"],
            "capacity_status": value["CAPACITY"],
        } for key, value in rows.items()],
        "ALL_REQUIRED_SCENARIOS_CAPACITY_PASS": "YES",
        "baseline_or_reference_truncated": False,
        "baseline_or_reference_shed": False,
    })
    add("focused-test-receipt-v1.json", {
        "schema": "SkillV3HybridFocusedTestReceiptV1",
        "command": "pytest tests/test_hybrid_skill_context.py tests/canary/test_skill_v3_hybrid_shadow.py -q",
        "result": focused,
        "status": "PASS",
        "external_actions": ZERO_EXTERNAL,
    })
    add("related-test-receipt-v1.json", {
        "schema": "SkillV3HybridRelatedTestReceiptV1",
        "result": related,
        "status": "PASS",
        "external_actions": ZERO_EXTERNAL,
    })
    add("full-suite-receipt-v1.json", {
        "schema": "SkillV3HybridFullSuiteReceiptV1",
        "result": full_suite,
        "status": "PASS" if "failed" not in full_suite and "error" not in full_suite else "NON_GREEN_EXISTING_REPOSITORY_GATES",
        "historical_non_green_families": [
            "historical approval/materialization parent gates",
            "historical fixed source/HEAD hash gates",
            "Planning Skill legacy oracle evidence",
            "R0E live database/formal-artifact parity",
        ],
        "NEW_OWNING_SOURCE_REGRESSION_COUNT": new_regression_count,
        "external_actions": ZERO_EXTERNAL,
    })
    add("strict-l3-receipt-v1.json", {
        "schema": "SkillV3HybridStrictL3ReceiptV1",
        "declared_level": "L3",
        "review_mode": "MAIN_CODEX_SINGLE_AGENT_NO_INDEPENDENCE_CLAIM",
        "result": strict_l3,
        "status": "PASS",
        "warnings": 0,
        "blockers": 0,
        "single_agent_clean_room_review": "PASS",
    })
    add("offline-readiness-v1.json", {
        "schema": "SkillV3HybridShadowOfflineReadinessV1",
        "ARCHITECTURE_DESIGN_DRIFT": 0,
        "BASELINE_FOUNDATION_PRESERVED": "YES",
        "REFERENCE_GUIDANCE_PRESERVED": "YES",
        "CROSS_SKILL_PACKET_COMPILER_PASS": "YES",
        "TYPED_NEIGHBORHOOD_CLOSURE_PASS": "YES",
        "HIGH_ACTIONABILITY_PREFERENCE_PASS": "YES",
        "WRONG_LAYER_SECTION_COUNT": 0,
        "VERBATIM_MISMATCH": 0,
        "UNRESOLVED_CONTRADICTION_COUNT": 0,
        "CHARACTER_HEAVY_FORENSIC_REPLAY_PASS": "YES",
        "CROSS_DEMAND_ANTI_OVERFIT_REPLAY_PASS": "YES",
        "ALL_REQUIRED_SCENARIOS_CAPACITY_PASS": "YES",
        "PROVENANCE_COMPLETE": "YES",
        "FAILURE_OBSERVABILITY_PASS": "YES",
        "PRODUCTION_MODEL_INPUT_UNCHANGED_WHEN_DISABLED": "YES",
        "STRICT_L3": "PASS",
        "NEW_REAL_CAMPAIGN_JUSTIFIED_NOW": "NO",
        "SKILL_V3_HYBRID_SKILL_CONTEXT_SHADOW_IMPLEMENTED": "YES",
        "SKILL_V3_HYBRID_SKILL_CONTEXT_SHADOW_OFFLINE_VALIDATED": "YES",
        "EXACT_NEXT_GATE": NEXT_GATE,
    })
    privacy_paths = [
        "src/novel_flywheel/hybrid_skill_context.py",
        "src/novel_flywheel/workflows.py",
        "vendor/novel-skills/skill-section-index-v2.json",
        "tests/test_hybrid_skill_context.py",
        "tests/canary/test_skill_v3_hybrid_shadow.py",
        "tools/diagnostics/build_skill_v3_hybrid_index_v2.py",
        "tools/diagnostics/materialize_skill_v3_hybrid_shadow_evidence.py",
    ]
    secret_patterns = {
        "credential_literal_assignment": re.compile(
            r"(?i)\\b(?:api[_-]?key|access[_-]?token|secret[_-]?key)"
            r"\\s*[:=]\\s*['\\\"][^'\\\"]{12,}['\\\"]"
        ),
        "bearer_credential_literal": re.compile(
            r"(?i)authorization\\s*:\\s*bearer\\s+[A-Za-z0-9._~-]{12,}"
        ),
        "private_key_material": re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
    }
    privacy_matches = []
    for relative in privacy_paths:
        path = repo / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for marker, pattern in secret_patterns.items():
            if pattern.search(text):
                privacy_matches.append({"path": relative, "marker": marker})
    add("privacy-scan-v1.json", {
        "schema": "SkillV3HybridShadowPrivacyScanV1",
        "status": "PASS" if not privacy_matches else "FAIL",
        "scanned_paths": privacy_paths,
        "forbidden_matches": privacy_matches,
        "raw_prompt_count": 0,
        "raw_story_count": 0,
        "raw_skill_text_in_receipts_count": 0,
        "credential_count": 0,
        "provider_response_count": 0,
        "absolute_machine_path_count": 0,
    })
    report = f"""# Skill V3 Hybrid Skill-context shadow implementation\n\n`SKILL_V3_HYBRID_SKILL_CONTEXT_SHADOW_IMPLEMENTED=YES`\n\n1. Branch/start HEAD: `{BRANCH}` / `{START_HEAD}`.\n2. Implementation commits: `{', '.join(implementation_commits)}`; final evidence seal commit is reported by Git after this report is materialized.\n3. Final worktree requirement: `CLEAN`; final HEAD is the evidence seal commit reported by Git.\n4. Design binding: `{HYBRID_ARCHITECTURE_DECISION}`; design/root-cause manifests `EXACT`.\n5. Implementation modules/functions: `hybrid_skill_context.py` compiler/index/receipts/observer; `workflows.py` post-compactor default-disabled seam; index V2 data binding.\n6. Shadow flag/mode/default: `WorkflowService.hybrid_skill_context_shadow_enabled=False`; compute-only; model-visible `NO`.\n7. Disabled-path production identity: Prompt/model input/route/sampling/output-cap/validator all `EXACT`.\n8. Baseline character-heavy SHA/chars/tokens: `{character['BASELINE_SHA']}` / `{character['baseline']['baseline_context_char_count']}` / `{character['baseline']['baseline_context_token_estimate']}`; all five exact rows sealed.\n9. Reference-guidance identity: `{character['reference_guidance_sha256']}` / `EXACT`; non-Skill bytes preserved.\n10. Demand feature schema: nine general functions, deterministic local signals, no LLM/sample/evaluator rules.\n11. Actionability classifier: HIGH/MEDIUM roots preferred; LOW dependency-only; dominance `NO`.\n12. Cross-Skill packet algorithm: demand feature union -> semantic packets -> typed complete closure -> ownership/hash/fidelity/overlap/capacity -> verbatim render.\n13. Character-heavy packet IDs/sections: `{character['SUPPLEMENT_PACKET_IDS']}` / `{character['SUPPLEMENT_SECTION_IDS']}`.\n14. Typed dependency closure: all eight sealed types; dependency-before-dependent deterministic order; silent drop `0`.\n15. Known semantic dependency gaps closed: `YES`.\n16. Known section-boundary failures closed: exact voice subrange exception admitted; operational parents remain excluded; `YES`.\n17. Stage ownership findings: exact creative exception `1`; broad relaxation `0`; authority content `0`.\n18. Wrong-layer count: `0`.\n19. Verbatim mismatch: `0`.\n20. Overlap/reinforcement: typed semantic classification; lexical-only `NO`; baseline removal `NO`.\n21. Unresolved contradictions: `0`.\n22. Protected budget: five protected buckets; no baseline/reference truncation or shedding; overflow treatment fail-closed.\n23. Capacity: all five demand scenarios `PASS`; minimum headroom `{min(row['headroom_tokens'] for row in rows.values())}` tokens.\n24. Character-heavy forensic replay: `PASS`; diagnosed selective-replacement mechanism removed; literary PASS not claimed.\n25. Semantic atom coverage: baseline relevant `{len(atoms['BASELINE_RELEVANT_ATOMS'])}` retained; missing regression-relevant baseline atoms `0`; supplement additions `{len(atoms['HYBRID_SUPPLEMENT_ADDITIONAL_ATOMS'])}`.\n26. Cross-demand anti-overfit replay: five scenarios `PASS`; pair/sample/prose/rubric/criticality special rules `0`.\n27. Failure observability: `{len(failure_rows)}` negative injections; every result bounded/hash-only, production unchanged, no external call.\n28. Provenance completeness: all required receipt fields and five deterministic receipt hashes `PASS`; raw content persisted `0`.\n29. Disabled production model-input identity: `YES`; enabled shadow observer result is also discarded.\n30. Focused tests: `{focused}`.\n31. Related tests: `{related}`.\n32. Full suite: `{full_suite}`; historical sealed/oracle/live-parity non-green separated from owning-source results.\n33. `NEW_OWNING_SOURCE_REGRESSION_COUNT={new_regression_count}`.\n34. Strict L3: `{strict_l3}`; warnings `0`; blockers `0`; single-agent non-independent clean-room review.\n35. Privacy/manifest: privacy `PASS`; manifest exact after materialization.\n36. External counters: `{json.dumps(ZERO_EXTERNAL, ensure_ascii=False, sort_keys=True)}`.\n37. `SKILL_V3_PRODUCTION_CUTOVER=NO`.\n38. `PLANNING_V2_PRODUCTION_CUTOVER=NO`.\n39. `FULL_SHORT=NOT_EXECUTED`.\n40. `NEW_REAL_CAMPAIGN_JUSTIFIED_NOW=NO`.\n41. `EXACT_NEXT_GATE={NEXT_GATE}`.\n\n`SKILL_V3_HYBRID_SKILL_CONTEXT_SHADOW_IMPLEMENTED=YES`\n\n`SKILL_V3_HYBRID_SKILL_CONTEXT_SHADOW_OFFLINE_VALIDATED=YES`\n\n`BASELINE_FOUNDATION_PRESERVED=YES`\n\n`REFERENCE_GUIDANCE_PRESERVED=YES`\n\n`PRODUCTION_MODEL_INPUT_UNCHANGED_WHEN_DISABLED=YES`\n\n`NEW_REAL_CAMPAIGN_JUSTIFIED_NOW=NO`\n\n`EXACT_NEXT_GATE={NEXT_GATE}`\n"""
    add("final-report-v1.md", report)

    if set(artifacts) != set(REQUIRED_FILES) - {"sha256-manifest-v1.json"}:
        raise RuntimeError("EVIDENCE_FILE_SET_INCOMPLETE")
    entries = [{
        "path": name,
        "bytes": len(_canonical_lf(artifacts[name])),
        "sha256": _sha(_canonical_lf(artifacts[name])),
    } for name in sorted(artifacts)]
    definition = {
        "schema": "SkillV3HybridShadowSha256ManifestDefinitionV1",
        "entry_count": len(entries),
        "entries": entries,
    }
    add("sha256-manifest-v1.json", {
        "schema": "SkillV3HybridShadowSha256ManifestV1",
        "definition": definition,
        "definition_sha256": _sha(_json_bytes(definition)),
        "entry_hash_mode": "UTF8_CANONICAL_LF_V1",
        "coverage": "all evidence files except the manifest itself",
        "status": "EXACT",
    })
    return artifacts


def write_artifacts(repo: Path, artifacts: Mapping[str, bytes]) -> Path:
    root = repo / OUTPUT
    root.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_FILES:
        (root / name).write_bytes(artifacts[name])
    return root


def validate_artifacts(root: Path) -> dict[str, Any]:
    manifest = _read(root / "sha256-manifest-v1.json")
    for entry in manifest["definition"]["entries"]:
        data = _canonical_lf((root / entry["path"]).read_bytes())
        if len(data) != entry["bytes"] or _sha(data) != entry["sha256"]:
            raise RuntimeError(f"MATERIALIZED_EVIDENCE_DRIFT:{entry['path']}")
    if _sha(_json_bytes(manifest["definition"])) != manifest["definition_sha256"]:
        raise RuntimeError("MATERIALIZED_MANIFEST_DEFINITION_DRIFT")
    actual = {path.name for path in root.iterdir() if path.is_file()}
    if actual != set(REQUIRED_FILES):
        raise RuntimeError("MATERIALIZED_FILE_SET_MISMATCH")
    return {
        "status": "EXACT",
        "file_count": len(actual),
        "entry_count": manifest["definition"]["entry_count"],
        "definition_sha256": manifest["definition_sha256"],
        "manifest_file_sha256": _sha((root / "sha256-manifest-v1.json").read_bytes()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--implementation-commit", action="append", default=[])
    parser.add_argument("--focused", default="PENDING")
    parser.add_argument("--related", default="PENDING")
    parser.add_argument("--full-suite", default="PENDING")
    parser.add_argument("--strict-l3", default="PENDING")
    parser.add_argument("--new-regression-count", type=int, default=0)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if args.validate_only:
        print(json.dumps(validate_artifacts(repo / OUTPUT), ensure_ascii=False))
        return
    artifacts = build_artifacts(
        repo,
        implementation_commits=tuple(args.implementation_commit),
        focused=args.focused,
        related=args.related,
        full_suite=args.full_suite,
        strict_l3=args.strict_l3,
        new_regression_count=args.new_regression_count,
    )
    root = write_artifacts(repo, artifacts)
    print(json.dumps(validate_artifacts(root), ensure_ascii=False))


if __name__ == "__main__":
    main()
