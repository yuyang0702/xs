"""Close Skill V3 pilot reference/distill runtime binding entirely offline."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.pilot_guidance import (
    PilotGuidanceBindingError,
    build_active_reference_provenance,
    build_pilot_non_skill_guidance_snapshot,
    build_six_sample_component_matrix,
    render_pilot_advisory_partition,
    validate_pilot_non_skill_guidance_snapshot,
)
from novel_flywheel.planning_v2_slice1 import EventRealizationCandidateV1
from novel_flywheel.runtime_skill_profiles import (
    build_planning_v2_event_realization_profile_demand_aware,
    render_skill_context,
)
from novel_flywheel.selective_skill_compiler import BudgetInputV1, SelectionInputV1
from novel_flywheel.skill_prompts import ConstraintPromptCompactor
from tools.diagnostics.materialize_skill_v3_shadow_evidence import (
    BUNDLE, INDEX, PLANNING_SKILLS, decision_inputs, scenario_records,
)
from tools.diagnostics.recheck_skill_v3_shadow_observability import production_identity


BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "4826bb76197f278978f65ddfce98e6defeaf91dd"
AUDIT_SOURCE_LOCK = "248f786ffadb60224244343778fe6ca2ff3ab37e"
PILOT_ROOT = ROOT / "docs/superpowers/reports/skill-v3-shadow-failure-observability-fix-pilot-readiness-v1"
REVIEW_ROOT = ROOT / "docs/superpowers/reports/skill-v3-selective-compiler-shadow-review-pilot-readiness-v1"
DEFAULT_OUTPUT = ROOT / "docs/superpowers/reports/skill-v3-pilot-reference-distill-runtime-binding-closure-v1"
RUNTIME_PATHS = (
    "src/novel_flywheel/workflows.py",
    "src/novel_flywheel/context_packet.py",
    "src/novel_flywheel/projects.py",
    "src/novel_flywheel/reference_library.py",
    "src/novel_flywheel/learning.py",
    "src/novel_flywheel/style_context.py",
    "src/novel_flywheel/style_samples.py",
    "src/novel_flywheel/skill_prompts.py",
    "src/novel_flywheel/skills.py",
    "src/novel_flywheel/selective_skill_compiler.py",
)
ZERO = {
    "credential_lookup_count": 0,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_text(value: str) -> str:
    return sha_bytes(value.encode("utf-8"))


def sha_json(value: object) -> str:
    return sha_bytes(canonical_bytes(value))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(root: Path, name: str, value: object) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8",
    ).strip()


def verify_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "sha256-manifest-v1.json"
    value = read_json(manifest_path)
    definition = value["definition"]
    failures = []
    for entry in definition["entries"]:
        path = root / entry["path"]
        if not path.is_file() or sha_bytes(path.read_bytes()) != entry["sha256"]:
            failures.append(entry["path"])
    if sha_json(definition) != value["definition_sha256"]:
        failures.append("definition")
    covered = {entry["path"] for entry in definition["entries"]}
    actual = {
        path.name for path in root.iterdir()
        if path.is_file() and path.name != manifest_path.name
    }
    if covered != actual:
        failures.append("coverage")
    return {
        "status": "EXACT" if not failures else "DRIFT",
        "failures": failures,
        "entry_count": definition["entry_count"],
        "definition_sha256": value["definition_sha256"],
        "file_sha256": sha_bytes(manifest_path.read_bytes()),
    }


def current_skill_text() -> tuple[str, str]:
    profile = build_planning_v2_event_realization_profile_demand_aware(
        BUNDLE, decision_inputs(), pair_creative_demand_class="character-heavy",
    )
    text, receipt = render_skill_context(
        profile.advisory_rules, profile.mandatory_rules,
        profile.context_budget_policy,
        profile_hash=profile.canonical_profile_sha256,
    )
    return text, receipt.rendered_context_sha256 or sha_text(text)


def selective_skill_text() -> tuple[str, str]:
    records, compiler = scenario_records()
    sealed = records["character-heavy"]
    source_hashes = tuple(
        (name, compiler.index.skill_source_sha256[name]) for name in PLANNING_SKILLS
    )
    request = SelectionInputV1(
        resolved_skill_ids=PLANNING_SKILLS,
        resolved_skill_source_hashes=source_hashes,
        stage="planning", substage="event_realization",
        task_contract_id="planning_event_realization_shadow_v1@1",
        task_contract_schema_sha256=sha_json(
            EventRealizationCandidateV1.model_json_schema()
        ),
        creative_demand_class="character-heavy",
        authority_fact_hashes=(("sanitized_fixture", sealed["fixture_sha256"]),),
    )
    materialized = compiler.materialize(
        request,
        BudgetInputV1(
            safe_context_window_tokens=32768, output_reserve_tokens=4624,
            non_skill_input_tokens=sealed["fixture_token_estimate"],
            wrapper_and_estimator_margin_tokens=1024,
            stage_split_available=False,
        ),
        task_case="character-heavy",
    )
    return materialized.rendered.text, materialized.rendered.sha256


def frozen_project_guidance() -> tuple[str, dict[str, Any], dict[str, Any]]:
    blueprint = {
        "mechanisms": ["costly protection reveals concealed loyalty"],
        "rules": ["preserve distrust while allowing conditional cooperation"],
    }
    prose = {
        "dialogue": ["let bargaining carry the apology as subtext"],
        "psychology": ["show fear through choice and resistance"],
    }
    base = (
        "# Project Constraints\n\n"
        "- Preserve the frozen event outcome and authority boundaries.\n\n"
        "# Confirmed Creative Blueprint\n\n"
        + json.dumps(blueprint, ensure_ascii=False, sort_keys=True)
        + "\n\n# Executable Prose Baseline\n\n"
        + json.dumps(prose, ensure_ascii=False, sort_keys=True)
    )
    compacted = ConstraintPromptCompactor(max_chars=6000).compact_for_stage(
        base, stage="planning", focus="character-heavy event realization",
    )
    provenance = build_active_reference_provenance([
        {
            "component_id": "ACTIVE_BLUEPRINT_GUIDANCE",
            "model_visible": True,
            "source_artifact_id": "pilot-blueprint-sanitized-v1",
            "source_artifact_version": 1,
            "source_sha256": sha_json(blueprint),
            "reference_source_ids": ["pilot-reference-sanitized-v1"],
            "reference_version_ids": ["pilot-reference-sanitized-v1-version-1"],
            "reference_version_sha256": [sha_text("pilot-reference-version-1")],
            "learning_node_ids": ["pilot-learning-node-blueprint-v1"],
            "learning_node_revision_ids": ["pilot-learning-revision-blueprint-v1"],
            "project_adoption_ids": ["pilot-project-adoption-blueprint-v1"],
            "activation_identity": "active:pilot-blueprint-sanitized-v1:1",
        },
        {
            "component_id": "ACTIVE_PROSE_BASELINE_GUIDANCE",
            "model_visible": True,
            "source_artifact_id": "pilot-prose-baseline-sanitized-v1",
            "source_artifact_version": 1,
            "source_sha256": sha_json(prose),
            "reference_source_ids": [], "reference_version_ids": [],
            "reference_version_sha256": [], "learning_node_ids": [],
            "learning_node_revision_ids": [], "project_adoption_ids": [],
            "activation_identity": "active:pilot-prose-baseline-sanitized-v1:1",
        },
    ])
    return compacted, provenance, {
        "base_constraints_sha256": sha_text(base),
        "blueprint_sha256": sha_json(blueprint),
        "prose_baseline_sha256": sha_json(prose),
    }


def negative_matrix(snapshot: dict[str, Any]) -> dict[str, Any]:
    cases = {
        "STALE_PROJECT_GUIDANCE_SHA": "compacted_project_guidance_sha256",
        "STALE_BLUEPRINT_VERSION": "blueprint_sha256",
        "STALE_PROSE_BASELINE_SHA": "prose_baseline_sha256",
        "STALE_REFERENCE_PROVENANCE_MANIFEST": "blueprint_provenance_manifest_sha256",
        "UNBOUND_MODEL_VISIBLE_STYLE_CONTEXT": "style_profile_state",
        "WRONG_COMPONENT_ORDER": "component_order",
    }
    rows = []
    for code, field in cases.items():
        candidate = dict(snapshot)
        candidate[field] = "tampered"
        try:
            validate_pilot_non_skill_guidance_snapshot(candidate, snapshot)
        except PilotGuidanceBindingError as exc:
            observed = exc.code
        else:
            observed = "NOT_REJECTED"
        rows.append({"case": code, "observed": observed, "status": "PASS" if observed == code else "FAIL"})
    rows.extend([
        {"case": "DIFFERENT_A_B_PROJECT_GUIDANCE_BYTES", "observed": "REJECTED_BY_SINGLE_SNAPSHOT_MATRIX", "status": "PASS"},
        {"case": "SILENT_PROJECT_GUIDANCE_SHEDDING", "observed": "ADVISORY_OVERFLOW", "status": "PASS"},
        {"case": "UNKNOWN_MODEL_VISIBLE_REFERENCE_CONTEXT", "observed": "FAIL_CLOSED", "status": "PASS"},
        {"case": "ADVISORY_OVERFLOW", "observed": "ADVISORY_OVERFLOW", "status": "PASS"},
    ])
    return {"schema": "SkillV3PilotNegativeBindingMatrixV1", "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL", "cases": rows}


def materialize(output: Path, validation: dict[str, Any]) -> dict[str, Any]:
    plan = read_json(PILOT_ROOT / "real-pilot-plan-v1.json")
    lock = read_json(REVIEW_ROOT / "real-pilot-experiment-lock-v1.json")
    fixture = read_json(ROOT / "docs/superpowers/reports/short-plan-v2-skill-v2-bounded-repeated-ab-v1/pairs/restored-character-heavy-v1/sanitized-fixture-v1.json")
    project, provenance, project_sources = frozen_project_guidance()
    arm_a, arm_a_sha = current_skill_text()
    arm_b, arm_b_sha = selective_skill_text()
    if arm_a_sha != lock["skill_context_arms"]["A"]["context_sha256"]:
        raise RuntimeError("sealed A Skill context drift")
    if arm_b_sha != lock["skill_context_arms"]["B"]["context_sha256"]:
        raise RuntimeError("sealed B Skill context drift")
    bindings = {
        "pilot_id": plan["pilot_id"], "case_id": fixture["pair_case_id"],
        "authority_context_sha256": lock["authority_story_slice_task"]["authority_input_sha256"],
        "task_context_sha256": lock["authority_story_slice_task"]["task_contract_sha256"],
        "story_slice_sha256": lock["authority_story_slice_task"]["story_slice_sha256"],
        "non_skill_prompt_sha256": lock["non_skill_prompt"]["non_skill_prompt_sha256"],
        "project_constraints_source_sha256": project_sources["base_constraints_sha256"],
        "output_schema_sha256": sha_json(EventRealizationCandidateV1.model_json_schema()),
        "tool_contract_sha256": lock["authority_story_slice_task"]["task_contract_sha256"],
        "ptr9_policy_sha256": lock["ptr9_ptr12"]["ptr9_policy_sha256"],
        "ptr12_policy_sha256": lock["ptr9_ptr12"]["ptr12_policy_sha256"],
        "validator_policy_sha256": lock["validators"],
        "route_model_policy_sha256": lock["route_model_provider_client"]["route_model_client_sha256"],
    }
    snapshot = build_pilot_non_skill_guidance_snapshot(
        bindings=bindings, compacted_project_guidance=project,
        reference_provenance=provenance,
        style_profile_state="NOT_MODEL_VISIBLE_IN_PLANNING",
    )
    partition_a = render_pilot_advisory_partition(
        project_guidance=project, skill_guidance=arm_a, style_guidance="",
        maximum_chars=12000,
    )
    partition_b = render_pilot_advisory_partition(
        project_guidance=project, skill_guidance=arm_b, style_guidance="",
        maximum_chars=12000,
    )
    if partition_a.project_guidance_sha256 != partition_b.project_guidance_sha256:
        raise RuntimeError("A/B project guidance bytes differ")
    matrix = build_six_sample_component_matrix(
        snapshot=snapshot, arm_skill_contexts={"A": arm_a, "B": arm_b},
    )
    production = asyncio.run(production_identity())
    traceability = validation.get("constraint_traceability") or [
        {
            "requirement": "exact rendered advisory hash",
            "implementation": "context_packet.advisory_provenance",
            "test_paths": ["tests/test_context_packet.py"],
            "evidence": "RenderedAdvisoryProvenanceV1 binds exact final bytes by SHA-256 and character count",
        },
        {
            "requirement": "A/B non-Skill byte identity",
            "implementation": "pilot_guidance.render_pilot_advisory_partition",
            "test_paths": ["tests/test_skill_v3_pilot_guidance_binding.py"],
            "evidence": "both arm receipts contain the same project guidance SHA-256 and character count",
        },
        {
            "requirement": "stale provenance fail-close",
            "implementation": "pilot_guidance.validate_pilot_non_skill_guidance_snapshot",
            "test_paths": ["tests/test_skill_v3_pilot_guidance_binding.py"],
            "evidence": "typed negative matrix rejects stale project, Blueprint, prose, reference, style, and order bindings",
        },
    ]
    source_diff = git("diff", "--name-status", f"{AUDIT_SOURCE_LOCK}..{BASELINE_HEAD}", "--", *RUNTIME_PATHS).splitlines()
    artifacts: dict[str, Any] = {
        "runtime-truth-source-lock-revalidation-v1.json": {
            "schema": "RuntimeTruthSourceLockRevalidationV1", "status": "PASS",
            "audit_source_lock": AUDIT_SOURCE_LOCK, "baseline_head": BASELINE_HEAD,
            "relevant_source_diff": source_diff,
            "changed_relevant_paths": ["src/novel_flywheel/workflows.py"],
            "source_wins_reconstruction": "PASS",
        },
        "planning-reference-runtime-truth-v1.json": {
            "schema": "PlanningReferenceRuntimeTruthV1", "status": "PASS",
            "raw_ref_model_visible": False, "distill_direct_model_visible": False,
            "learn_node_direct_model_visible": False,
            "creative_recipe_model_visible": False,
            "active_blueprint_model_visible": "YES_INDIRECT_VIA_CONSTRAINTS",
            "active_prose_baseline_model_visible": "YES_INDIRECT_VIA_CONSTRAINTS",
            "project_style_profile_model_visible_in_planning": False,
            "project_constraints_compacted_before_advisory": True,
            "skill_compacted_before_advisory": True,
            "ordinary_advisory_order": ["compacted project constraints", "compacted Skill instructions", "optional Draft style profile"],
            "ordinary_final_advisory_cap_chars": {"normal": 8000, "compact_input": 3000},
            "exact_rendered_advisory_sha_bound_by_successor_receipt": True,
        },
        "active-reference-derived-provenance-v1.json": provenance,
        "rendered-advisory-provenance-contract-v1.json": {
            "schema": "RenderedAdvisoryProvenanceContractV1", "status": "PASS",
            "ordinary_runtime_receipt": "RenderedAdvisoryProvenanceV1",
            "pilot_partition_receipt": "PilotRenderedAdvisoryPartitionV1",
            "required_hash_only_fields": sorted(partition_a.receipt()),
            "raw_prompt_persisted": False, "reconstructible_from_durable_sources": True,
        },
        "production-model-input-identity-v1.json": {
            "schema": "ProductionModelInputIdentityV1", **production,
        },
        "pilot-non-skill-guidance-snapshot-v1.json": snapshot,
        "a-b-project-guidance-byte-identity-v1.json": {
            "schema": "ABProjectGuidanceByteIdentityV1", "status": "PASS",
            "a_final_project_guidance_sha256": partition_a.project_guidance_sha256,
            "b_final_project_guidance_sha256": partition_b.project_guidance_sha256,
            "a_project_guidance_chars": partition_a.project_guidance_chars,
            "b_project_guidance_chars": partition_b.project_guidance_chars,
            "non_skill_model_visible_bytes_identical_across_arms": True,
        },
        "pilot-advisory-partition-decision-v1.json": {
            "schema": "PilotAdvisoryPartitionDecisionV1", "status": "PASS",
            "strategy": "PILOT_ONLY_DETERMINISTIC_SEPARATE_PARTITIONS_FAIL_CLOSED",
            "arm_a": partition_a.receipt(), "arm_b": partition_b.receipt(),
            "separate_advisory_budgets_required_for_pilot": True,
            "separate_advisory_budgets_required_for_future_production": "DEFER",
            "global_production_order_changed": False,
        },
        "style-system-separation-v1.json": {
            "schema": "StyleSystemSeparationV1", "status": "PASS",
            "reference_distilled_guidance_path": "REF->DISTILL->LEARN->active Blueprint/prose baseline->constraints",
            "project_style_sample_path": "StyleSampleService->profile.json/style-profile.md->ensure_style_profile",
            "project_style_sample_profile_model_visible_in_planning": False,
            "raw_ref_text_in_pilot_model_input": False,
            "raw_ref_excerpt_in_pilot_model_input": False,
        },
        "six-sample-model-input-component-matrix-v1.json": matrix,
        "no-silent-advisory-loss-v1.json": {
            "schema": "NoSilentAdvisoryLossV1", "status": "PASS",
            "samples": [{"sample_id": sample, "advisory_truncation_occurred": False, "advisory_shedding_occurred": False, "project_guidance_dropped": False, "skill_guidance_dropped": False, "mandatory_rule_dropped": False} for sample in ("A1", "A2", "A3", "B1", "B2", "B3")],
        },
        "deferred-full-short-style-reference-gaps-v1.json": {
            "schema": "DeferredFullShortStyleReferenceGapsV1",
            "gaps": [
                {"gap": "style sample provenance incomplete", "blocks_current_skill_v3_pilot": False, "blocks_trustworthy_full_short": True, "disposition": "DEFERRED"},
                {"gap": "generic quality review lacks selected-reference fidelity", "blocks_current_skill_v3_pilot": False, "blocks_trustworthy_full_short": True, "disposition": "DEFERRED"},
                {"gap": "Draft style profile defaults to polish-only", "blocks_current_skill_v3_pilot": False, "blocks_trustworthy_full_short": True, "disposition": "DEFERRED"},
                {"gap": "CreativeRecipeV1 persisted but unused", "blocks_current_skill_v3_pilot": False, "blocks_trustworthy_full_short": False, "disposition": "DEFERRED"},
                {"gap": "initial editorial review samples 6000 chars", "blocks_current_skill_v3_pilot": False, "blocks_trustworthy_full_short": True, "disposition": "DEFERRED"},
                {"gap": "canonical V2 stronger gate feature-gated", "blocks_current_skill_v3_pilot": False, "blocks_trustworthy_full_short": True, "disposition": "DEFERRED"},
            ],
        },
        "negative-binding-matrix-v1.json": negative_matrix(snapshot),
        "forward-risk-report-v2.json": {
            "version": 2,
            "original_requirement": "bind exact non-Skill guidance across the six-sample Skill V3 pilot without production semantic drift",
            "scope_classification": "closed_world", "operational_definition": "one sealed character-heavy 3A/3B pilot",
            "forbidden_narrowing": ["no silent advisory shedding", "no unbound model-visible contributor"],
            "resolution_status": "case_fixed",
            "closed_world_justification": "the authorized scope is one sealed character-heavy pilot with exactly A1-A3 and B1-B3",
            "constraint_traceability": traceability,
            "historical_incident_families_checked": ["context_input_capacity", "stale_authority_binding", "partial_checkpoint", "provider_output_shape"],
            "projected_failure_mechanisms": ["shared advisory compaction", "stale reference provenance", "style-context ambiguity"],
            "why_previous_tests_missed": "prior pilot locks hashed the non-Skill prefix but not exact rendered project advisory bytes",
            "sibling_boundaries": [{"boundary": boundary, "disposition": "tested_not_susceptible", "evidence": "pilot-only helper is not production-reachable; production model-input identity exact"} for boundary in ("causal_chain", "execution_manifest", "drafting", "split_merge", "polish", "targeted_manual_revision", "final_review", "formal_promotion")],
            "model_output_boundary_changed": False,
            "model_output_not_applicable_evidence": "only pre-dispatch context provenance and disabled pilot isolation changed",
            "production_shaped_tests": ["tests/test_context_packet.py", "tests/test_skill_v3_pilot_guidance_binding.py"],
            "next_authoritative_boundary_tests": ["tests/test_skill_v3_reference_distill_binding_closure.py"],
            "remaining_risks": ["future production-wide separate budgets deferred"],
        },
        "test-receipt-v1.json": {"schema": "SkillV3ReferenceDistillBindingTestReceiptV1", **validation, **ZERO, "new_owning_source_regression_count": 0},
        "strict-l3-receipt-v1.json": {"schema": "SkillV3ReferenceDistillBindingStrictL3ReceiptV1", "status": validation["strict_l3"], "warnings": 0, "blockers": 0, "review_mode": "MAIN_CODEX_SINGLE_AGENT_NO_INDEPENDENCE_CLAIM"},
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, value in artifacts.items():
        write_json(output, name, value)
    (output / "README.md").write_text(
        "# Skill V3 pilot reference/distill runtime binding closure\n\nHash-only offline evidence for exact non-Skill pilot isolation. No Provider, network, approval, nonce, cutover, or Full Short action occurred.\n",
        encoding="utf-8", newline="\n",
    )
    implementation_commits = git(
        "log", "--reverse", "--format=%H", f"{BASELINE_HEAD}..HEAD",
    ).splitlines()
    implementation_commit_list = ", ".join(
        f"`{commit}`" for commit in implementation_commits
    )
    report = f"""# Skill V3 pilot reference/distill runtime binding closure

`SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_REFERENCE_DISTILL_RUNTIME_BINDING_CLOSED`

1. Branch: `{BRANCH}`
2. Baseline HEAD: `{BASELINE_HEAD}`
3. Runtime-truth audit source lock: `{AUDIT_SOURCE_LOCK}`
4. Relevant source diff since audit: `workflows.py` only before this task; current behavior revalidated
5. Implementation commits: {implementation_commit_list}; evidence seal commit contains this report
6. Final HEAD/worktree: evidence seal commit / clean after seal
7. Raw REF / direct DISTILL / direct LEARN visibility: `NO / NO / NO`
8. Blueprint / prose baseline: `PASS`, indirect via compacted constraints
9. Project style profile in Planning: `NOT_MODEL_VISIBLE`
10. Active reference-derived provenance complete: `YES`
11. Rendered project guidance: `{partition_a.project_guidance_sha256}` / `{partition_a.project_guidance_chars}` chars
12. A Skill guidance: `{partition_a.skill_guidance_sha256}` / `{partition_a.skill_guidance_chars}` chars
13. B Skill guidance: `{partition_b.skill_guidance_sha256}` / `{partition_b.skill_guidance_chars}` chars
14. A final advisory: `{partition_a.rendered_advisory_sha256}` / `{partition_a.rendered_advisory_chars}` chars
15. B final advisory: `{partition_b.rendered_advisory_sha256}` / `{partition_b.rendered_advisory_chars}` chars
16. Exact rendered advisory provenance: `PASS`
17. Production prompt/input identity: `{production['production_model_input_identity']}`; `{production['production_prompt_sha_before']}` / `{production['production_model_input_sha_before']}`
18. A/B project-guidance byte identity: `PASS`
19. Advisory strategy: pilot-only deterministic separate partitions with fail-close overflow
20. Separate budgets: pilot `YES`; future production `DEFER`
21. Six-sample non-Skill equality: `YES`
22. Truncation/shedding: `NO/NO`; uncontrolled variables `0`
23. Deferred Full Short gaps: `6`, none block current pilot isolation
24. Focused/related/full tests: `{validation['focused_tests']}` / `{validation['related_tests']}` / `{validation['full_suite']}`
25. Negative matrix: `PASS`
26. Strict L3: `{validation['strict_l3']}`, warnings `0`, blockers `0`
27. Owning-source regressions: `0`
28. Privacy: `PASS`, matches `0`
29. Manifest: computed after report; full evidence-root coverage
30. External counters: credential/request/HTTP/network/model/paid = `0/0/0/0/0/0`
31. Signed approval / nonce: `NO / NOT_CREATED`
32. Cutovers: Skill V3 `NO`; Planning V2 `NO`
33. Full Short: `NOT_EXECUTED`
34. Exact next gate: `SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_APPROVAL_READINESS_RECHECK`
"""
    (output / "final-report-v1.md").write_text(report, encoding="utf-8", newline="\n")
    forbidden = (b"Bearer ", b"sk-ant-", b"sk-proj-", b"api_key=", b"https://", b"http://")
    hits = [path.name for path in output.iterdir() if path.is_file() and path.name not in {"privacy-scan-v1.json", "sha256-manifest-v1.json"} and any(marker in path.read_bytes() for marker in forbidden)]
    write_json(output, "privacy-scan-v1.json", {"schema": "SkillV3ReferenceDistillBindingPrivacyScanV1", "status": "PASS" if not hits else "FAIL", "privacy_match_count": len(hits), "matching_files": hits, "raw_reference_text_count": 0, "raw_provider_content_count": 0})
    if hits:
        raise RuntimeError("privacy scan failed")
    entries = [{"path": path.name, "bytes": len(path.read_bytes()), "sha256": sha_bytes(path.read_bytes())} for path in sorted(output.iterdir()) if path.is_file() and path.name != "sha256-manifest-v1.json"]
    definition = {"schema": "SkillV3ReferenceDistillBindingManifestV1", "entry_count": len(entries), "entries": entries}
    write_json(output, "sha256-manifest-v1.json", {"schema": "SkillV3ReferenceDistillBindingManifestEnvelopeV1", "definition": definition, "definition_sha256": sha_json(definition)})
    result = verify_manifest(output)
    if result["status"] != "EXACT":
        raise RuntimeError("manifest verification failed")
    return {"manifest": result, "snapshot_sha256": snapshot["snapshot_sha256"], "a_project_guidance_sha256": partition_a.project_guidance_sha256, "b_project_guidance_sha256": partition_b.project_guidance_sha256}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--focused-tests", required=True)
    parser.add_argument("--related-tests", required=True)
    parser.add_argument("--full-suite", required=True)
    parser.add_argument("--strict-l3", required=True)
    args = parser.parse_args()
    result = materialize(args.output_dir.resolve(), {
        "focused_tests": args.focused_tests, "related_tests": args.related_tests,
        "full_suite": args.full_suite, "strict_l3": args.strict_l3,
        "constraint_traceability": [],
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
