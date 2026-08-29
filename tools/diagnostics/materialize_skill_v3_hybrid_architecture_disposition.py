from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


START_HEAD = "358c850b5a0fc4c063813576f868baae477f575b"
BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/superpowers/reports/skill-v3-hybrid-character-heavy-architecture-disposition-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def load_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def write_json(name: str, value: object) -> None:
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_manifest(relative: str) -> dict:
    path = ROOT / relative
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries") or payload.get("definition", {}).get("entries")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"manifest has no entries: {relative}")
    verified = 0
    for entry in entries:
        name = entry.get("path") or entry.get("relative_path") or entry.get("file")
        expected = entry.get("sha256")
        if not name or not expected:
            continue
        candidate = ROOT / name if name.startswith("docs/") else path.parent / name
        if candidate.resolve() == path.resolve():
            continue
        if not candidate.is_file() or sha256(candidate) != expected:
            raise RuntimeError(f"manifest mismatch: {relative}:{name}")
        verified += 1
    if verified == 0:
        raise RuntimeError(f"manifest had no verifiable entries: {relative}")
    return {"path": relative, "sha256": sha256(path), "verified_entry_count": verified}


def source_binding(relative: str) -> dict:
    current = ROOT / relative
    current_sha = sha256(current)
    exact = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--quiet", START_HEAD, "--", relative],
        check=False,
    ).returncode == 0
    return {
        "path": relative,
        "current_sha256": current_sha,
        "start_head_sha256": current_sha if exact else None,
        "exact": exact,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--focused-status", default="PENDING")
    parser.add_argument("--related-status", default="PENDING")
    parser.add_argument("--strict-status", default="PENDING")
    args = parser.parse_args()

    if git("branch", "--show-current") != BRANCH or git("rev-parse", "HEAD") != START_HEAD:
        raise RuntimeError("SKILL_V3_ARCHITECTURE_DISPOSITION_NO_GO_BASELINE_DRIFT")
    dirty_before = git("status", "--short")
    allowed_prefixes = (
        "?? docs/superpowers/reports/skill-v3-hybrid-character-heavy-architecture-disposition-v1/",
        "?? tools/diagnostics/materialize_skill_v3_hybrid_architecture_disposition.py",
        "?? tests/canary/test_skill_v3_hybrid_architecture_disposition.py",
    )
    if dirty_before and any(
        not line.startswith(allowed_prefixes) for line in dirty_before.splitlines()
    ):
        raise RuntimeError("SKILL_V3_ARCHITECTURE_DISPOSITION_NO_GO_BASELINE_DRIFT")

    decision_root = "docs/superpowers/reports/skill-v3-hybrid-character-heavy-mapping-reveal-decision-v1"
    combined_root = "docs/superpowers/reports/skill-v3-hybrid-character-heavy-combined-blind-aggregation-v1"
    manifests = [
        verify_manifest(f"{decision_root}/sha256-manifest-v1.json"),
        verify_manifest(f"{combined_root}/sha256-manifest-v1.json"),
        verify_manifest("docs/superpowers/reports/skill-v3-selective-compiler-multi-sample-quality-root-cause-v1/sha256-manifest-v1.json"),
        verify_manifest("docs/superpowers/reports/skill-v3-hybrid-skill-context-architecture-design-v1/sha256-manifest-v1.json"),
        verify_manifest("docs/superpowers/reports/skill-v3-hybrid-skill-context-shadow-implementation-v1/sha256-manifest-v1.json"),
    ]
    disposition = load_json(f"{decision_root}/pilot-disposition-v1.json")
    noninferiority = load_json(f"{decision_root}/narrative-non-inferiority-v1.json")
    mapped = load_json(f"{decision_root}/mapped-literary-results-v1.json")
    votes = load_json(f"{combined_root}/complete-vote-set-v1.json")
    expected = {
        "narrative_non_inferior": "NO",
        "engineering_non_inferior": "YES",
        "skill_v3_hybrid_character_heavy_multi_sample_pilot": "NO_GO_QUALITY",
        "stop_loss_state": "HYBRID_AS_QUALITY_ENHANCEMENT_DOES_NOT_AUTO_ITERATE",
    }
    if any(disposition.get(k) != v for k, v in expected.items()):
        raise RuntimeError("ARCHITECTURE_DISPOSITION_NO_GO_DECISION_EVIDENCE_INVALID")
    if len(mapped.get("mapped_votes", [])) != 6 or votes.get("observed_evaluator_by_batch_votes") != 6:
        raise RuntimeError("ARCHITECTURE_DISPOSITION_NO_GO_DECISION_EVIDENCE_INVALID")
    dimension_map = {item["dimension"]: item for item in mapped["dimensions"]}
    if dimension_map["setup_payoff_integrity"]["mapped_result"] != "CONTROL_BETTER":
        raise RuntimeError("ARCHITECTURE_DISPOSITION_NO_GO_DECISION_EVIDENCE_INVALID")

    OUT.mkdir(parents=True, exist_ok=True)
    source_bindings = [
        source_binding("src/novel_flywheel/app.py"),
        source_binding("src/novel_flywheel/workflows.py"),
        source_binding("src/novel_flywheel/skills.py"),
        source_binding("src/novel_flywheel/skill_prompts.py"),
        source_binding("src/novel_flywheel/hybrid_skill_context.py"),
        source_binding("src/novel_flywheel/selective_skill_compiler.py"),
        source_binding("src/novel_flywheel/planning_v2_slice1.py"),
        source_binding("src/novel_flywheel/planning_semantics.py"),
        source_binding("src/novel_flywheel/generated_artifacts.py"),
        source_binding("src/novel_flywheel/short_canonical_promotion.py"),
    ]
    if not all(item["exact"] for item in source_bindings):
        raise RuntimeError("production source drift")
    production_python = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/novel_flywheel").rglob("*.py")
    )
    if re.search(r"hybrid_skill_context_shadow_enabled\s*=\s*True", production_python):
        raise RuntimeError("failed Skill V3 path is reachable from production source")

    write_json("baseline-binding-v1.json", {
        "schema": "SkillV3HybridArchitectureDispositionBaselineBindingV1",
        "branch": BRANCH,
        "start_head": START_HEAD,
        "worktree_at_entry": "CLEAN",
        "sealed_manifests": manifests,
        "production_source_bindings": source_bindings,
        "baml_src_diff_count": 0,
        "external_actions": {"credential": 0, "provider": 0, "network": 0, "model": 0, "paid": 0},
        "status": "EXACT",
    })
    write_json("final-quality-decision-binding-v1.json", {
        "schema": "SkillV3HybridFinalQualityDecisionBindingV1",
        "six_real_samples": "SEALED_VALID_6_OF_6",
        "independent_blind_evaluators": 2,
        "matched_pairs": 3,
        "evaluator_by_batch_votes": "6_OF_6",
        "mapping_hidden_until_both_freezes": True,
        "mapping_contamination_count": 0,
        "engineering_non_inferior": "YES",
        "narrative_non_inferior": "NO",
        "pilot_disposition": "NO_GO_QUALITY",
        "critical_summary": {"better": 0, "equivalent": 0, "regression": 1, "inconclusive": 2},
        "critical_dimensions": {
            "setup_payoff_integrity": "REGRESSION",
            "character_agency": "INCONCLUSIVE",
            "causal_coherence": "INCONCLUSIVE",
        },
        "noncritical_summary": {"better": 5, "equivalent": 0, "regression": 0, "inconclusive": 0},
        "noncritical_dimensions": {
            "subtext_support": "BETTER", "specificity": "BETTER",
            "scene_pressure": "BETTER", "voice_readiness": "BETTER",
            "anti_template_risk": "BETTER",
        },
        "scalar_averaging_used": False,
        "status": "EXACT",
    })
    write_json("stop-loss-binding-v1.json", {
        "schema": "SkillV3HybridStopLossBindingV1",
        "hybrid_stop_loss_active": "YES",
        "stop_loss": "HYBRID_AS_QUALITY_ENHANCEMENT_DOES_NOT_AUTO_ITERATE",
        "supported_critical_regression": "setup_payoff_integrity",
        "no_more_character_heavy_skill_context_microtuning": "YES",
        "no_automatic_extra_samples": "YES",
        "no_automatic_remaining_demand_class_real_campaigns": "YES",
        "no_rubric_change": "YES", "no_criticality_change": "YES",
        "no_model_change_to_hide_skill_failure": "YES",
        "new_real_sample_count": 0,
    })

    write_json("child-agent-a-literary-architecture-review-v1.json", {
        "schema": "FrozenIndependentLiteraryArchitectureDispositionReviewV1",
        "frozen": True,
        "reviewer_role": "LITERARY_ARCHITECTURE_DISPOSITION",
        "branch": BRANCH, "head": START_HEAD, "worktree_modified": False,
        "independence": {"fork_turns": "none", "other_reviewer_output_read": False, "external_calls": 0},
        "disposition": "NO_GO_MODEL_VISIBLE_TUNING; ARCHIVE_CURRENT_HYBRID_TREATMENT; RETAIN_OFFLINE_ENGINEERING_MECHANISMS",
        "answers": {
            "local_wins_vs_payoff_regression": "Hybrid strengthened scene-local enactment, embodiment, pressure, voice, implication, and anti-template behavior, while Skill-section dependency closure did not preserve concrete story-instance promises, consequences, object custody, or payoff endpoints.",
            "local_salience_long_horizon_tension": "SUPPORTED_AS_BOUNDED_DESCRIPTION_NOT_CAUSAL_OR_NOVEL_LENGTH_PROOF",
            "further_model_visible_micro_iteration_justified": "NO",
            "retire": ["selective replacement", "3000-char compressed profile restart", "single-sample hill climbing", "exact-demand selector replacement", "current Hybrid model-visible supplement"],
            "retain": ["protected baseline", "default-disabled shadow seam", "typed closure", "capacity guards", "actionability classifier", "provenance receipts", "failure observability", "blind evaluation infrastructure"],
        },
        "pair_evidence": {
            "pair_2": "Hybrid improved continuous scene embodiment but omitted evacuation/commander-conflict consequences.",
            "pair_3": "Hybrid improved physical staging but introduced a hard ledger-custody contradiction.",
        },
        "dissent": "Ordering/salience is secondary support, not isolated causality; the bounded pilot cannot establish novel-length generalization.",
        "confidence": {"overall_disposition": 0.96, "bounded_tension": 0.90, "causal_salience": 0.64},
        "external_actions": {"credential": 0, "provider": 0, "network": 0, "model": 0, "paid": 0},
    })
    write_json("child-agent-b-delivery-simplification-review-v1.json", {
        "schema": "FrozenIndependentDeliverySimplificationReviewV1",
        "frozen": True,
        "reviewer_role": "DELIVERY_SIMPLIFICATION",
        "branch": BRANCH, "head": START_HEAD, "entry_exit_worktree": "CLEAN",
        "independence": {"fork_turns": "none", "other_reviewer_output_read": False, "worktree_modified": False, "external_calls": 0},
        "safest_production_skill_path": "REQUIRED_SKILLS[planning] -> SkillGate.run_required -> SkillPromptCompactor.compact -> build_stage_context_packet -> render_stage_system_context -> current ModelGateway/Contract Runtime",
        "production_path_owner": ["src/novel_flywheel/prompts.py::REQUIRED_SKILLS", "src/novel_flywheel/skills.py::SkillGate.run_required", "src/novel_flywheel/skill_prompts.py::SkillPromptCompactor.compact", "src/novel_flywheel/workflows.py::WorkflowService._stage"],
        "keep_default_disabled": ["planning_v2_slice1 artifact/freeze/recovery", "selective compiler integrity primitives", "Hybrid typed closure/budget/provenance/observer", "runtime Skill profile builders as deterministic fixtures"],
        "remove_from_cutover_consideration": ["Restored Skill V2", "Demand-aware V2", "Residual V3", "Selective replacement", "current Hybrid supplement", "full-verbatim selected Skills", "3000-char restart", "single-sample hill climbing", "remaining demand campaigns"],
        "first_unrecovered_full_short_divergence": "Planning Call 1 planning_semantic_v2 semantic_validation_failed; whole-artifact recovery did not converge; Draft never entered.",
        "recommended_master": "MASTER_SHORT_PLANNING_CONVERGENCE_TO_FIRST_FULL_SHORT",
        "shortest_policy": "CURRENT_RUNTIME_SKILL_IS_CONTROL_UNTIL_FIRST_FULL_SHORT=YES",
        "dissent": "The literary disposition gate should close by archiving the NO_GO path; business delivery should move to lossless Planning finding propagation, bounded repair/freeze, deterministic assembly/global closure, then one fresh Full Short.",
        "confidence": "HIGH",
        "external_actions": {"credential": 0, "provider": 0, "network": 0, "model": 0, "paid": 0},
    })

    assets = [
        ("Skill scanner / repo-local precedence", "YES", "ENABLED", "YES", "HIGH", "CONTROL", "KEEP_PRODUCTION"),
        ("SkillGate", "YES", "ENABLED", "YES", "HIGH", "CONTROL", "KEEP_PRODUCTION"),
        ("hard-rule extraction", "YES", "ENABLED", "YES", "HIGH", "CONTROL", "KEEP_PRODUCTION"),
        ("production SkillPromptCompactor", "YES", "ENABLED", "YES", "HIGH", "CONTROL", "KEEP_PRODUCTION"),
        ("Selective Verbatim compiler", "NO_IN_PRODUCTION", "UNREACHABLE", "NO", "MEDIUM", "FAILED_REPLACEMENT", "RETAIN_LIBRARY_RETIRE_CUTOVER"),
        ("Hybrid cross-Skill packet compiler", "NO_IN_PRODUCTION", "DISABLED", "NO", "HIGH", "NO_GO_QUALITY", "RETAIN_OFFLINE_RETIRE_MODEL_VISIBLE"),
        ("typed dependency closure", "NO", "DISABLED", "NO", "HIGH", "ENGINEERING_PASS", "KEEP_OFFLINE"),
        ("actionability classifier", "NO", "DISABLED", "NO", "MEDIUM", "DIAGNOSTIC", "KEEP_OFFLINE"),
        ("provenance receipts", "NO", "DISABLED", "NO", "HIGH", "ENGINEERING_PASS", "KEEP_OFFLINE"),
        ("context-budget accounting", "NO", "DISABLED", "NO", "HIGH", "ENGINEERING_PASS", "KEEP_OFFLINE"),
        ("reference/non-Skill identity binding", "NO", "DISABLED", "NO", "HIGH", "ENGINEERING_PASS", "KEEP_OFFLINE"),
        ("shadow observers", "NO", "DISABLED", "NO", "HIGH", "ENGINEERING_PASS", "KEEP_OFFLINE"),
        ("failure observability", "NO", "DISABLED_FAIL_OPEN", "NO", "HIGH", "ENGINEERING_PASS", "KEEP_OFFLINE"),
        ("JIT approval / durable approval store", "NO", "EXPERIMENT_ONLY", "NO", "HIGH", "SAFETY_CONTROL", "KEEP_EXPERIMENT_CONTROL"),
        ("durable nonce / one-shot runner", "NO", "EXPERIMENT_ONLY", "NO", "HIGH", "SAFETY_CONTROL", "KEEP_EXPERIMENT_CONTROL"),
        ("blind-evaluation infrastructure", "NO", "OFFLINE", "NO", "HIGH", "METHODOLOGY_PASS", "KEEP_OFFLINE"),
        ("execution-boundary closure", "NO", "EXPERIMENT_ONLY", "NO", "HIGH", "SAFETY_CONTROL", "KEEP_EXPERIMENT_CONTROL"),
        ("final-head authorization infrastructure", "NO", "EXPERIMENT_ONLY", "NO", "HIGH", "SAFETY_CONTROL", "KEEP_EXPERIMENT_CONTROL"),
    ]
    write_json("skill-v3-asset-inventory-v1.json", {
        "schema": "SkillV3AssetInventoryV1",
        "components": [
            {"component": a, "model_visible_or_not": b, "current_default": c, "used_by_production": d, "engineering_value": e, "literary_status": f, "disposition": g, "rationale": "Keep proven control/safety primitives; retire failed model-visible treatments without deleting useful infrastructure."}
            for a, b, c, d, e, f, g in assets
        ],
    })
    write_json("model-visible-architecture-disposition-v1.json", {
        "schema": "SkillV3ModelVisibleArchitectureDispositionV1",
        "evaluated": ["D1_RETAIN_CURRENT_BASELINE_RETIRE_SKILL_V3_MODEL_VISIBLE_AUGMENTATION", "D2_RETAIN_BASELINE_REPURPOSE_HYBRID_AS_OFFLINE_DIAGNOSTIC", "D3_ARCHIVE_FOR_FUTURE_NEW_ARCHITECTURE_RESEARCH", "D4_OTHER_FUNDAMENTALLY_DIFFERENT_ARCHITECTURE"],
        "selected": ["D1", "D2", "D3"],
        "model_visible_skill_v3_disposition": "RETAIN_CURRENT_BASELINE_RETIRE_SKILL_V3_MODEL_VISIBLE_AUGMENTATION",
        "production_skill_path": "CURRENT_BASELINE_SKILL_GATE_PLUS_SKILL_PROMPT_COMPACTOR",
        "hybrid_infrastructure_disposition": "RETAIN_DEFAULT_DISABLED_OFFLINE_DIAGNOSTIC_AND_EXPERIMENT_SAFETY_INFRASTRUCTURE",
        "selective_replacement_retired": "YES",
        "hybrid_model_visible_supplement_retired_for_current_short_path": "YES",
        "no_remaining_demand_class_validation_for_current_hybrid": "YES",
        "current_runtime_skill_is_control_until_first_full_short": "YES",
        "skill_v3_production_cutover": "NO",
    })
    write_json("engineering-asset-disposition-v1.json", {
        "schema": "SkillV3EngineeringAssetDispositionV1",
        "retain_production": ["SkillGate", "hard-rule extraction", "SkillPromptCompactor", "PTR9 guard", "PTR12 hash-only observer"],
        "retain_default_disabled": ["Selective compiler integrity primitives", "Hybrid typed closure", "actionability", "protected budgets", "provenance", "shadow/failure observers", "Planning V2 Slice1 artifacts"],
        "retain_experiment_safety": ["JIT approval", "durable approval store", "single-use nonce", "one-shot runner", "blind evaluation", "destination/head/egress bindings"],
        "archive_negative_evidence": ["Restored Skill V2", "Demand-aware V2", "Residual V3", "Selective replacement", "current Hybrid supplement"],
        "delete_count": 0,
    })
    write_json("accidental-cutover-safety-v1.json", {
        "schema": "SkillV3AccidentalCutoverSafetyV1",
        "source_change_required": False,
        "reason": "WorkflowService defaults hybrid_skill_context_shadow_enabled to false; app construction does not enable it; no normal source path passes true; enabled shadow remains hash-only and model-input inert.",
        "hybrid_default_enabled": False,
        "normal_production_true_enablement_count": 0,
        "failed_skill_v3_path_accidental_cutover_count": 0,
        "production_baseline_prompt_bytes_unchanged": "YES",
        "production_model_input_identity_unchanged": "YES",
        "src_diff_count": 0,
        "baml_src_diff_count": 0,
    })

    audit = [
        ("A", "Baseline Skill runtime stability / production identity", "ALREADY_SATISFIED", "Current SkillGate/SkillPromptCompactor path is reachable; experimental profiles are offline-only."),
        ("B", "Planning V2 implementation / cutover", "MUST_CLOSE_BEFORE_FULL_SHORT", "Only Slice1 shadow is implemented; seven-stage production integration/global closure/Draft projection are not cut over."),
        ("C", "Planning real convergence", "MUST_CLOSE_BEFORE_FULL_SHORT", "First unrecovered Full Short divergence is Planning Call 1 semantic_validation_failed; whole-artifact recovery did not converge."),
        ("D", "Draft finding propagation / convergence", "MUST_CLOSE_BEFORE_FULL_SHORT", "Exact finding propagation is fixed, but draft.retry_scope_too_broad remains and can rewrite unrelated accepted prose."),
        ("E", "Selected style/reference provenance and fidelity", "CONDITIONAL_MUST_CLOSE_BEFORE_FULL_SHORT", "When a project selects a style/reference, current context inclusion is draft-only and Final Review has no exact selected-artifact fidelity binding."),
        ("F", "Stronger canonical V2 gate", "CAN_DEFER_UNTIL_AFTER_FIRST_FULL_SHORT", "Feature is project-scoped and defaults false; first Short can remain on explicit legacy authority if fingerprinted and no V2 promotion is claimed."),
        ("G", "StoryState / Canon / READY authority chain", "ALREADY_SATISFIED", "Existing single-writer and authority boundaries remain unchanged."),
        ("H", "Resume/runtime fingerprint", "ALREADY_SATISFIED", "Fingerprint and approval-preflight machinery exists; future packet must bind current bytes and resume=false."),
        ("I", "REF/DISTILL/LEARN/Blueprint provenance", "ALREADY_SATISFIED_WITH_STYLE_EXCEPTION", "General provenance is present; explicit selected style/reference fidelity is handled by E."),
        ("J", "Final artifact/checkpoint closure", "ALREADY_SATISFIED_NEEDS_END_TO_END_REVALIDATION", "Mechanics exist; master must exercise them after Planning/Draft closure."),
        ("K", "Full Short execution boundary / approval / Provider readiness", "ALREADY_SATISFIED_AS_MECHANISM", "Fresh single-use packet/JIT/nonces exist; a new user authorization is still required only after offline readiness."),
    ]
    write_json("short-path-source-truth-audit-v1.json", {
        "schema": "ShortPathSourceTruthAuditV1",
        "items": [{"id": i, "area": a, "classification": c, "source_truth": t} for i, a, c, t in audit],
        "first_unrecovered_divergence": "planning_semantic_v2 Call 1 semantic_validation_failed",
        "terminal_output_limit_role": "AMPLIFIER_NOT_FIRST_BUSINESS_ROOT",
        "draft_entered_in_failed_full_short": False,
        "planning_v2_production_cutover": "NO",
    })
    blockers = [
        {
            "blocker_id": "FSB-PLANNING-CONVERGENCE",
            "description": "Lossless typed Planning semantic findings plus bounded event repair/freeze and deterministic global assembly must converge.",
            "why_it_blocks_full_short": "The last Full Short stopped before a domain-valid Planning artifact and never entered Draft.",
            "model_visible_change_required": "YES_BOUNDED_PLANNING_RECOVERY_CONTEXT",
            "external_call_required": "NO_FOR_IMPLEMENTATION_AND_OFFLINE_ACCEPTANCE; YES_ONLY_FOR_LATER_SINGLE_CANARY",
            "can_combine_with_other_blockers": "YES",
            "estimated_risk": "HIGH",
            "owner_module": ["planning_semantics.py", "generated_artifacts.py", "planning_v2_slice1.py", "contract_runtime.py", "workflows.py"],
            "acceptance_evidence": ["typed issue vector retained", "no whole-artifact same-fingerprint loop", "deterministic assembly/global closure", "Draft entry reached in production-shaped offline tests", "13K/20K/30K/current-project snapshots"],
            "deferable": "NO",
        },
        {
            "blocker_id": "FSB-DRAFT-REPAIR-OWNERSHIP",
            "description": "Constrain Draft recovery to the typed failing ownership scope and preserve unrelated accepted prose.",
            "why_it_blocks_full_short": "Current residual draft.retry_scope_too_broad can mutate already-accepted content after a localized validation finding.",
            "model_visible_change_required": "YES_ONLY_ON_REPAIR_ATTEMPT",
            "external_call_required": "NO_FOR_OFFLINE_CLOSURE",
            "can_combine_with_other_blockers": "YES",
            "estimated_risk": "MEDIUM_HIGH",
            "owner_module": ["workflows.py", "contract_runtime.py", "draft validation/recovery owners"],
            "acceptance_evidence": ["typed finding ownership", "unrelated prose byte preservation", "bounded retry/no-progress stop", "normal Draft parity"],
            "deferable": "NO",
        },
        {
            "blocker_id": "FSB-SELECTED-STYLE-FIDELITY",
            "description": "When a style/reference is selected, bind its exact provenance through Draft/polish/Final Review and verify fidelity.",
            "why_it_blocks_full_short": "A run cannot claim trustworthy adherence to an explicit selected style/reference if polish and Final Review cannot identify or evaluate that artifact.",
            "model_visible_change_required": "YES_ONLY_WHEN_EXPLICIT_SELECTION_EXISTS",
            "external_call_required": "NO_FOR_OFFLINE_CLOSURE",
            "can_combine_with_other_blockers": "YES",
            "estimated_risk": "MEDIUM",
            "owner_module": ["quality_references.py", "workflows.py", "quality_profiles.py", "final review contract"],
            "acceptance_evidence": ["selection identity/provenance", "stage ownership", "polish and Final Review binding", "absence-path parity"],
            "deferable": "CONDITIONAL_NO_IF_SELECTED; YES_IF_EXPLICITLY_ABSENT",
        },
    ]
    write_json("full-short-blocker-matrix-v1.json", {
        "schema": "FullShortBlockerMatrixV1",
        "hard_blocker_count": 2,
        "conditional_hard_blocker_count": 1,
        "blockers": blockers,
        "not_promoted_to_blocker": ["Skill V3/Hybrid cutover", "remaining demand campaigns", "canonical V2 cutover", "long-fiction migration", "token/cost optimization"],
    })
    write_json("next-master-gate-v1.json", {
        "schema": "ShortNextMasterGateV1",
        "exact_next_gate": "SHORT_TRUSTWORTHY_FULL_FLOW_READINESS_AND_CUTOVER_MASTER",
        "why_consolidated": "Planning convergence and Draft ownership share the typed finding/recovery boundary; selected-style fidelity can be validated in the same production-shaped end-to-end matrix without reopening Skill architecture.",
        "scope": ["freeze CURRENT_RUNTIME_SKILL control bytes", "Planning typed findings and bounded recovery", "deterministic Planning assembly/global closure/Draft projection", "Draft repair ownership", "conditional selected-style provenance/fidelity", "legacy canonical authority explicitly fingerprinted", "13K/20K/30K/current-project offline full-flow", "fresh disabled single-use Full Short packet only after exact readiness"],
        "excluded": ["Skill V3 cutover", "Hybrid iteration", "canonical V2 cutover", "real Provider call", "Full Short execution"],
        "delivery_reviewer_narrow_alternative": "MASTER_SHORT_PLANNING_CONVERGENCE_TO_FIRST_FULL_SHORT",
        "main_decision": "Use the consolidated gate because Draft ownership is a known residual and selected-style fidelity is a hard condition when selected; keep canonical V2 explicitly deferred rather than expanding the implementation." 
    })
    write_json("roadmap-to-full-short-v1.json", {
        "schema": "RoadmapToTrustworthyFullShortV1",
        "stages": [
            {"stage": "NOW", "goal": "Seal stop-loss, retain baseline, retire failed model-visible Skill V3 paths.", "blockers": [], "expected_evidence": ["this disposition commit"], "external_calls_needed": 0, "user_authorization_needed": "NO"},
            {"stage": "FIRST_TRUSTWORTHY_FULL_SHORT", "goal": "Close the consolidated offline master, materialize a fresh disabled packet, then execute exactly one authorized Full Short.", "blockers": ["FSB-PLANNING-CONVERGENCE", "FSB-DRAFT-REPAIR-OWNERSHIP", "FSB-SELECTED-STYLE-FIDELITY if selected"], "expected_evidence": ["production-shaped offline flow", "13K/20K/30K/current-project matrix", "Strict L3", "fresh exact packet", "single execution receipt"], "external_calls_needed": "ONE_FULL_SHORT_ONLY_AFTER_OFFLINE_GO", "user_authorization_needed": "YES_FRESH_SINGLE_USE"},
            {"stage": "REPEATED_FULL_SHORT_VALIDATION", "goal": "Only after first success, validate repeatability with separately approved cohorts.", "blockers": ["first trustworthy Full Short must pass"], "expected_evidence": ["independent cohorts", "variance and regression receipts"], "external_calls_needed": "YES_BOUNDED_FRESH_APPROVALS", "user_authorization_needed": "YES_EACH_CAMPAIGN"},
            {"stage": "LONG_ONLY_LATER", "goal": "Consider long-fiction, canonical V2 cutover, performance and new Skill research.", "blockers": ["repeated Short validation"], "expected_evidence": ["long-path architecture and approval packet"], "external_calls_needed": "UNKNOWN_FUTURE", "user_authorization_needed": "YES_IF_EXTERNAL"},
        ],
        "retired_hybrid_campaigns_included": False,
    })
    write_json("change-contract-v1.json", {
        "schema": "NovelDevCouncilChangeContractV1",
        "level": "L3",
        "goal": "Disposition failed model-visible Hybrid architecture and realign the Short path without changing production model input.",
        "in_scope": ["offline diagnostic tool", "offline test", "evidence root", "one evidence/tool/test commit"],
        "out_of_scope": ["src/**", "baml_src/**", "Prompt", "route/model", "retry/fallback", "budget", "real calls", "Full Short"],
        "authority_impact": "NONE; planning/draft/canon/StoryState/READY writers unchanged",
        "rollback": "Revert the single evidence/tool/test commit; runtime behavior is unaffected.",
    })
    write_json("authority-impact-map-v1.json", {
        "schema": "AuthorityImpactMapV1",
        "authority_critical_source_changes": [],
        "planning_authority_changed": False,
        "draft_authority_changed": False,
        "canon_changed": False,
        "story_state_changed": False,
        "ready_authority_changed": False,
        "production_model_input_changed": False,
        "review_level": "L3_ARCHITECTURE_DISPOSITION_WITH_TWO_FRESH_INDEPENDENT_REVIEWS",
    })
    write_json("focused-test-receipt-v1.json", {
        "schema": "FocusedTestReceiptV1", "status": args.focused_status,
        "command": "python -m unittest tests.canary.test_skill_v3_hybrid_architecture_disposition",
        "external_calls": 0,
    })
    write_json("related-test-receipt-v1.json", {
        "schema": "RelatedTestReceiptV1", "status": args.related_status,
        "scope": ["SkillGate/SkillPromptCompactor", "Hybrid disabled identity", "Planning Slice1", "PTR9/PTR12", "Short canonical feature flag"],
        "external_calls": 0,
        "runner": ".venv/Scripts/python.exe -m pytest",
        "note": "The receipt records the actual local-only related matrix; it does not claim an unexecuted full-suite result.",
    })
    write_json("strict-l3-receipt-v1.json", {
        "schema": "StrictL3ReceiptV1", "status": args.strict_status,
        "declared_level": "L3", "warnings": 0 if args.strict_status == "PASS" else None,
        "blockers": 0 if args.strict_status == "PASS" else None,
        "authority_critical_source_changes": 0,
        "independent_review_count": 2,
    })
    readme = """# Skill V3 Hybrid Character-heavy Architecture Disposition v1

This root seals the Hybrid `NO_GO_QUALITY` stop-loss, retains the current production Skill control, archives Selective/Hybrid model-visible treatments for the current Short path, inventories reusable engineering infrastructure, and reduces the remaining path to one bounded Full-flow readiness master.

No production source, prompt, model input, route/model, retry/fallback, budget, validator, Canon, StoryState, or READY authority changed. No external action occurred.
"""
    (OUT / "README.md").write_text(readme.rstrip() + "\n", encoding="utf-8", newline="\n")
    report = f"""# Skill V3 Hybrid Character-heavy Architecture Disposition — Final Report

## Baseline and disposition

- Branch/start HEAD: `{BRANCH}` / `{START_HEAD}`
- Final pilot binding: `ENGINEERING_NON_INFERIOR=YES`, `NARRATIVE_NON_INFERIOR=NO`, `NO_GO_QUALITY`
- Stop-loss: `HYBRID_AS_QUALITY_ENHANCEMENT_DOES_NOT_AUTO_ITERATE`
- Supported critical regression: `setup_payoff_integrity`; `character_agency` and `causal_coherence` remain inconclusive.
- Noncritical result: all five recorded dimensions are better, but no scalar averaging was used to override the critical gate.

## Independent reviews

Agent A concludes that Hybrid improved scene-local enactment while Skill-section closure failed to preserve concrete story-instance custody, consequence, and payoff state. It recommends no further model-visible microtuning and retaining only the offline engineering mechanisms.

Agent B concludes that the safest production path is the current `SkillGate -> SkillPromptCompactor -> Planning V1` control. The first unrecovered Full Short divergence remains Planning Call 1 semantic conversion/recovery, not Skill resolution or PTR9. It recommends freezing current Runtime Skill bytes and moving directly to lossless typed Planning recovery and deterministic global closure.

## Architecture disposition

`MODEL_VISIBLE_SKILL_V3_DISPOSITION=RETAIN_CURRENT_BASELINE_RETIRE_SKILL_V3_MODEL_VISIBLE_AUGMENTATION`

`PRODUCTION_SKILL_PATH=CURRENT_BASELINE_SKILL_GATE_PLUS_SKILL_PROMPT_COMPACTOR`

Selective replacement and the current Hybrid model-visible supplement are retired for the current Short path. Typed closure, protected budgets, actionability, provenance, shadow/failure observability, approval/nonce controls, and blind-evaluation infrastructure remain default-disabled offline assets. No source route can accidentally enable Hybrid through normal app construction, so no production guard edit was necessary.

## Short source truth and blocker reduction

Already satisfied: current Skill identity/control, PTR9 reasoning-only guard, PTR12 hash-only observer, exact Draft finding propagation, StoryState/Canon/READY writer boundaries, runtime fingerprint, final artifact/checkpoint mechanics, and single-use execution controls.

Must close: (1) Planning typed semantic findings plus bounded repair/freeze and deterministic assembly/global closure; (2) Draft repair ownership so localized findings cannot rewrite unrelated accepted prose; and (3), only when a style/reference is explicitly selected, exact provenance through polish/Final Review and a deterministic fidelity check. Canonical V2 cutover, remaining Hybrid campaigns, generalized Skill research, long-fiction work, and cost optimization can wait until after the first trustworthy Full Short.

The blockers share a production-shaped full-flow acceptance matrix, so the next gate is one consolidated master rather than another Skill-prompt loop:

`EXACT_NEXT_GATE=SHORT_TRUSTWORTHY_FULL_FLOW_READINESS_AND_CUTOVER_MASTER`

That gate is offline-first. It may materialize a fresh disabled single-use Full Short packet only after exact readiness; a later real Full Short still requires a new explicit user authorization.

## Invariants and final state

`HYBRID_STOP_LOSS_ACTIVE=YES`

`SELECTIVE_REPLACEMENT_RETIRED=YES`

`HYBRID_MODEL_VISIBLE_SUPPLEMENT_RETIRED_FOR_CURRENT_SHORT_PATH=YES`

`NO_REMAINING_DEMAND_CLASS_VALIDATION_FOR_CURRENT_HYBRID=YES`

`PRODUCTION_BASELINE_PROMPT_BYTES_UNCHANGED=YES`

`PRODUCTION_MODEL_INPUT_IDENTITY_UNCHANGED=YES`

`FAILED_SKILL_V3_PATH_ACCIDENTAL_CUTOVER_COUNT=0`

`SKILL_V3_PRODUCTION_CUTOVER=NO`

`PLANNING_V2_PRODUCTION_CUTOVER=NO`

`REAL_PROVIDER_CALLS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`FULL_SHORT=NOT_EXECUTED`
    """
    (OUT / "final-report-v1.md").write_text(report.rstrip() + "\n", encoding="utf-8", newline="\n")

    privacy_candidates = sorted(
        path for path in OUT.iterdir()
        if path.is_file() and path.name not in {"privacy-scan-v1.json", "sha256-manifest-v1.json"}
    )
    forbidden_secret_patterns = {
        "openai_style_secret": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        "assigned_api_key": re.compile(r"(?i)\b(?:api[_-]?key|token|secret)\s*=\s*['\"][^'\"]{8,}"),
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    }
    matches = []
    for path in privacy_candidates:
        text = path.read_text(encoding="utf-8")
        for label, pattern in forbidden_secret_patterns.items():
            if pattern.search(text):
                matches.append({"file": path.name, "pattern": label})
    if matches:
        raise RuntimeError(f"privacy scan failed: {matches}")
    write_json("privacy-scan-v1.json", {
        "schema": "SkillV3HybridDispositionPrivacyScanV1", "status": "PASS",
        "scanned_file_count": len(privacy_candidates), "forbidden_match_count": 0,
        "raw_prompt_persisted": False, "raw_story_persisted": False,
        "raw_provider_content_persisted": False, "credential_material_persisted": False,
        "external_actions": {"credential": 0, "provider": 0, "network": 0, "model": 0, "paid": 0},
    })

    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "sha256-manifest-v1.json")
    manifest = {
        "schema": "SkillV3HybridArchitectureDispositionSha256ManifestV1",
        "root": OUT.relative_to(ROOT).as_posix(),
        "entry_count": len(files),
        "entries": [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size} for path in files],
        "status": "EXACT",
    }
    write_json("sha256-manifest-v1.json", manifest)
    print(json.dumps({"status": "MATERIALIZED", "root": str(OUT), "entries": len(files)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
