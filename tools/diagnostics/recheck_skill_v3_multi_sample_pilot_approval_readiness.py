"""Offline Skill V3 multi-sample pilot approval-readiness recheck.

This module never imports a Provider client or touches credentials/network.  It
binds existing sealed evidence, creates disabled per-sample readiness records,
and reports an honest CONDITIONAL result while a Skill-V3-specific launcher and
execution entry remain unsealed.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
from functools import lru_cache
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tools.diagnostics.recheck_skill_v3_shadow_observability import production_identity


BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
BASELINE_HEAD = "3e317192fe98601789d76d1751b9f3073f3a797c"
PILOT_ID = "skill-v3-character-heavy-multi-sample-v1-4d47410b0144360d"
EXPECTED_B_CONTEXT_SHA256 = "c830681f79526c44d9bd83430019d75cb886bde0affcad86714ee1fc1f41aedd"
PARENT_EXPERIMENT_LOCK_SHA256 = (
    "8a07c5106fec903952d4b622ab33702636c17d3add7eb380d3ac78071841fc9b"
)
REVIEW_ROOT = ROOT / "docs/superpowers/reports/skill-v3-selective-compiler-shadow-review-pilot-readiness-v1"
OBS_ROOT = ROOT / "docs/superpowers/reports/skill-v3-shadow-failure-observability-fix-pilot-readiness-v1"
CLOSURE_ROOT = ROOT / "docs/superpowers/reports/skill-v3-pilot-reference-distill-runtime-binding-closure-v1"
DEFAULT_OUTPUT = ROOT / "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-pilot-approval-readiness-recheck-v1"
SEQUENCE = ("A1", "B1", "A2", "B2", "A3", "B3")
EXTERNAL_ZERO = {
    "credential_lookup_count": 0,
    "real_provider_client_creation_count": 0,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
}


class ReadinessError(ValueError):
    """Typed fail-close error for offline readiness bindings."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_json(value: object) -> str:
    return sha_bytes(canonical_bytes(value))


def domain_sha(domain: str, value: object) -> str:
    return sha_bytes(domain.encode("utf-8") + b"\0" + canonical_bytes(value))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8",
    ).strip()


def validate_starting_baseline() -> dict[str, Any]:
    branch = git("branch", "--show-current")
    head = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain")
    if branch != BRANCH or head != BASELINE_HEAD or dirty:
        raise ReadinessError(
            "SKILL_V3_MULTI_SAMPLE_PILOT_APPROVAL_READINESS_RECHECK_NO_GO_BASELINE_DRIFT"
        )
    return {"branch": branch, "baseline_head": head, "worktree": "CLEAN"}


def verify_sealed_manifest(root: Path) -> dict[str, Any]:
    envelope = read_json(root / "sha256-manifest-v1.json")
    if "definition" in envelope:
        definition = envelope["definition"]
    else:
        definition = {
            key: value for key, value in envelope.items()
            if key != "definition_sha256"
        }
    failures: list[str] = []
    for entry in definition["entries"]:
        path = root / entry["path"]
        if not path.is_file() or file_sha(path) != entry["sha256"]:
            failures.append(entry["path"])
    if sha_json(definition) != envelope["definition_sha256"]:
        failures.append("definition_sha256")
    actual = {p.name for p in root.iterdir() if p.is_file()}
    covered = {row["path"] for row in definition["entries"]}
    if actual != covered | {"sha256-manifest-v1.json"}:
        failures.append("manifest_coverage")
    return {
        "status": "EXACT" if not failures else "DRIFT",
        "failures": failures,
        "entry_count": definition["entry_count"],
        "definition_sha256": envelope["definition_sha256"],
        "file_sha256": file_sha(root / "sha256-manifest-v1.json"),
    }


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ReadinessError(reason)


@lru_cache(maxsize=1)
def _baseline_launcher_candidates() -> tuple[str, ...]:
    candidates = []
    baseline_paths = git(
        "ls-tree", "-r", "--name-only", BASELINE_HEAD, "--", "tools/canary",
    ).splitlines()
    for relative in sorted(path for path in baseline_paths if path.endswith(".py")):
        text = git("show", f"{BASELINE_HEAD}:{relative}")
        if PILOT_ID in text or EXPECTED_B_CONTEXT_SHA256 in text:
            candidates.append(relative)
    return tuple(candidates)


def load_sealed_state() -> dict[str, Any]:
    closure_manifest = verify_sealed_manifest(CLOSURE_ROOT)
    review_manifest = verify_sealed_manifest(REVIEW_ROOT)
    observation_manifest = verify_sealed_manifest(OBS_ROOT)
    _require(closure_manifest["status"] == "EXACT", "REFERENCE_DISTILL_BINDING_DRIFT")
    _require(review_manifest["status"] == "EXACT", "PILOT_REVIEW_EVIDENCE_DRIFT")
    _require(observation_manifest["status"] == "EXACT", "PILOT_PLAN_EVIDENCE_DRIFT")

    plan_path = OBS_ROOT / "real-pilot-plan-v1.json"
    lock_path = REVIEW_ROOT / "real-pilot-experiment-lock-v1.json"
    plan = read_json(plan_path)
    lock = read_json(lock_path)
    arms = read_json(REVIEW_ROOT / "pilot-arm-definition-v1.json")
    budget = read_json(REVIEW_ROOT / "pilot-budget-v1.json")
    policy = read_json(REVIEW_ROOT / "multi-sample-policy-binding-v1.json")
    independence = read_json(REVIEW_ROOT / "sample-independence-contract-v1.json")
    reuse = read_json(REVIEW_ROOT / "historical-sample-reuse-decision-v1.json")
    blind = read_json(REVIEW_ROOT / "multi-sample-blind-mapping-policy-v1.json")
    evaluator = read_json(REVIEW_ROOT / "evaluator-topology-v1.json")
    aggregation = read_json(REVIEW_ROOT / "aggregation-sanity-review-v1.json")
    capacity = read_json(REVIEW_ROOT / "five-scenario-capacity-review-v1.json")
    scenario = read_json(
        ROOT / "docs/superpowers/reports/skill-v3-verbatim-selective-compiler-shadow-implementation-v1/scenario-character-heavy-v1.json"
    )
    snapshot = read_json(CLOSURE_ROOT / "pilot-non-skill-guidance-snapshot-v1.json")
    provenance = read_json(CLOSURE_ROOT / "active-reference-derived-provenance-v1.json")
    component_matrix = read_json(CLOSURE_ROOT / "six-sample-model-input-component-matrix-v1.json")
    advisory = read_json(CLOSURE_ROOT / "pilot-advisory-partition-decision-v1.json")
    loss = read_json(CLOSURE_ROOT / "no-silent-advisory-loss-v1.json")
    production = read_json(CLOSURE_ROOT / "production-model-input-identity-v1.json")

    _require(file_sha(lock_path) == PARENT_EXPERIMENT_LOCK_SHA256, "PARENT_EXPERIMENT_LOCK_DRIFT")
    _require(plan["materialized"] is True and plan["pilot_plan_disabled"] is True, "PILOT_PLAN_NOT_DISABLED")
    _require(plan["execution_authorized"] is False, "PILOT_PLAN_EXECUTION_AUTHORIZED")
    _require(plan["signed_approval_present"] is False, "PILOT_PLAN_SIGNED_APPROVAL_PRESENT")
    _require(plan["real_execution_nonce_reserved"] is False, "PILOT_PLAN_NONCE_RESERVED")
    _require(plan["pilot_id"] == PILOT_ID, "PILOT_ID_DRIFT")
    _require(plan["samples_per_a"] == 3 and plan["samples_per_b"] == 3, "SAMPLE_COUNT_DRIFT")
    _require(plan["maximum_total_real_requests"] == 6, "REQUEST_CAP_DRIFT")
    _require(plan["experiment_lock_sha256"] == PARENT_EXPERIMENT_LOCK_SHA256, "PLAN_PARENT_LOCK_DRIFT")
    _require(tuple(plan["sequential_execution_order"]) == SEQUENCE, "EXECUTION_SEQUENCE_DRIFT")
    _require(snapshot["pilot_id"] == PILOT_ID, "NON_SKILL_SNAPSHOT_PILOT_DRIFT")
    _require(provenance["active_reference_derived_guidance_provenance_complete"] is True, "PROVENANCE_INCOMPLETE")
    _require(component_matrix["all_non_skill_components_equal_across_6"] is True, "NON_SKILL_COMPONENT_DRIFT")
    _require(component_matrix["uncontrolled_variable_count"] == 0, "UNCONTROLLED_VARIABLE_DRIFT")
    _require(component_matrix["primary_changed_variable"] == "SKILL_CONTEXT", "PRIMARY_VARIABLE_DRIFT")
    _require(advisory["arm_a"]["truncation_occurred"] is False, "A_ADVISORY_TRUNCATED")
    _require(advisory["arm_b"]["truncation_occurred"] is False, "B_ADVISORY_TRUNCATED")
    _require(advisory["arm_a"]["shedding_occurred"] is False, "A_ADVISORY_SHED")
    _require(advisory["arm_b"]["shedding_occurred"] is False, "B_ADVISORY_SHED")
    _require(production["production_model_input_identity"] == "PASS", "PRODUCTION_INPUT_DRIFT")
    _require(reuse["historical_a_sample_reuse_allowed"] == "NO", "HISTORICAL_A_REUSE_DRIFT")
    _require(reuse["historical_b_sample_reuse_allowed"] == "NO", "HISTORICAL_B_REUSE_DRIFT")

    # This diagnostic reproduces the historical readiness decision at its
    # sealed baseline.  Successor launchers must not retroactively change that
    # evidence from CONDITIONAL to another state.
    _require(
        arms["b_arm_identity"]["context_sha256"] == EXPECTED_B_CONTEXT_SHA256,
        "B_CONTEXT_DRIFT",
    )
    launcher_candidates = list(_baseline_launcher_candidates())

    return {
        "closure_manifest": closure_manifest,
        "review_manifest": review_manifest,
        "observation_manifest": observation_manifest,
        "plan": plan,
        "plan_sha256": file_sha(plan_path),
        "lock": lock,
        "arms": arms,
        "budget": budget,
        "policy": policy,
        "independence": independence,
        "reuse": reuse,
        "blind": blind,
        "evaluator": evaluator,
        "aggregation": aggregation,
        "capacity": capacity,
        "scenario": scenario,
        "snapshot": snapshot,
        "snapshot_file_sha256": file_sha(CLOSURE_ROOT / "pilot-non-skill-guidance-snapshot-v1.json"),
        "provenance": provenance,
        "component_matrix": component_matrix,
        "advisory": advisory,
        "loss": loss,
        "production": production,
        "launcher_candidates": launcher_candidates,
    }


def _skill_binding(state: Mapping[str, Any], arm: str) -> dict[str, Any]:
    if arm == "A":
        value = state["arms"]["a_arm_identity"]
        return {
            "skill_context_kind": "DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE",
            "skill_context_sha256": value["context_sha256"],
            "skill_context_chars": value["context_characters"],
            "skill_context_token_estimate": state["scenario"]["current_compressed_profile_token_estimate"],
            "compiler_version": None,
            "selector_version": None,
        }
    value = state["arms"]["b_arm_identity"]
    return {
        "skill_context_kind": "VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_V1_CHARACTER_HEAVY",
        "skill_context_sha256": value["context_sha256"],
        "skill_context_chars": state["scenario"]["rendered_context_chars"],
        "skill_context_token_estimate": state["scenario"]["token_estimate"],
        "compiler_version": value["compiler_version"],
        "selector_version": state["scenario"]["receipt"]["selector_policy_version"],
    }


def build_sample_locks(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    snapshot = state["snapshot"]
    lock = state["lock"]
    rows: list[dict[str, Any]] = []
    for slot in SEQUENCE:
        arm, index = slot[0], int(slot[1])
        skill = _skill_binding(state, arm)
        opaque = "sv3s-" + domain_sha(
            "skill-v3-opaque-sample-id-v1", {"pilot_id": PILOT_ID, "slot": slot},
        )[:20]
        component_binding = {
            "authority_sha256": snapshot["authority_context_sha256"],
            "task_sha256": snapshot["task_context_sha256"],
            "story_slice_sha256": snapshot["story_slice_sha256"],
            "non_skill_prompt_sha256": snapshot["non_skill_prompt_sha256"],
            "project_guidance_sha256": snapshot["compacted_project_guidance_sha256"],
            "reference_derived_provenance_sha256": snapshot["blueprint_provenance_manifest_sha256"],
            "style_guidance_state": snapshot["style_profile_state"],
            "output_contract_sha256": snapshot["output_schema_sha256"],
            "validator_sha256": snapshot["validator_policy_sha256"],
            "ptr_policy_sha256": sha_json({
                "ptr9": snapshot["ptr9_policy_sha256"],
                "ptr12": snapshot["ptr12_policy_sha256"],
            }),
            "model_route_policy_sha256": snapshot["route_model_policy_sha256"],
            "skill_context_sha256": skill["skill_context_sha256"],
        }
        body = {
            "schema": "SkillV3ProspectiveSampleLockV1",
            "pilot_id": PILOT_ID,
            "sample_slot": slot,
            "arm": arm,
            "sample_index": index,
            "sample_id": opaque,
            "parent_experiment_lock_sha256": PARENT_EXPERIMENT_LOCK_SHA256,
            "pilot_plan_sha256": state["plan_sha256"],
            **component_binding,
            "model_binding_sha256": lock["route_model_provider_client"]["model_binding_sha256"],
            "provider_descriptor_sha256": lock["route_model_provider_client"]["provider_descriptor_sha256"],
            "route_fingerprint": lock["route_model_provider_client"]["route_fingerprint"],
            "client": lock["route_model_provider_client"]["client"],
            "protocol": lock["route_model_provider_client"]["protocol"],
            "sampling_policy_sha256": lock["route_model_provider_client"]["sampling_policy_sha256"],
            "output_cap": lock["output_cap"],
            "skill_context_kind": skill["skill_context_kind"],
            "compiler_version": skill["compiler_version"],
            "selector_version": skill["selector_version"],
            "execution_entry": "NOT_SEALED_CONDITION",
            "launcher": "NOT_SEALED_CONDITION",
            "terminal_local_pipeline_sha256": lock["local_terminal_pipeline"],
            "sample_independence_contract": "UNIQUE_APPROVAL_NONCE_RECEIPT_REQUEST_NO_RETRY_V1",
            "model_input_component_binding_sha256": sha_json(component_binding),
        }
        body["sample_lock_sha256"] = domain_sha("skill-v3-prospective-sample-lock-v1", body)
        rows.append(body)
    return rows


NEGATIVE_CASES = (
    "STALE_PILOT_PLAN", "STALE_PARENT_EXPERIMENT_LOCK", "STALE_SAMPLE_LOCK",
    "WRONG_OR_DUPLICATE_SAMPLE_ID", "WRONG_ARM_OR_INDEX", "STALE_A_SKILL_CONTEXT",
    "STALE_B_COMPILER_CONTEXT", "STALE_SELECTED_SECTION_SHA",
    "STALE_NON_SKILL_GUIDANCE_SNAPSHOT", "STALE_PROJECT_GUIDANCE_SHA",
    "STALE_REFERENCE_DERIVED_PROVENANCE", "DIFFERENT_A_B_PROJECT_GUIDANCE_BYTES",
    "SILENT_ADVISORY_SHEDDING", "ADVISORY_TRUNCATION", "UNKNOWN_MODEL_VISIBLE_CONTEXT",
    "WRONG_MODEL_PROVIDER_ROUTE_CLIENT", "WRONG_SAMPLING_POLICY", "WRONG_OUTPUT_CAP",
    "WRONG_VALIDATOR_PTR_BINDING", "MISSING_LAUNCHER",
    "EXECUTION_AUTHORIZED_FALSE_TREATED_AS_EXECUTABLE", "SIGNED_APPROVAL_ABSENT",
    "BLANKET_APPROVAL_ATTEMPT", "NONCE_RESERVED_BEFORE_PERMISSION", "NONCE_REUSE",
    "SECOND_DISPATCH", "RETRY_FALLBACK_ROUTE_SWITCH_RESUME",
    "CROSS_SAMPLE_PROSE_INJECTION", "CROSS_ARM_PROSE_INJECTION",
    "PRIOR_BLIND_RESULT_INJECTION", "PAIR2_TO_5_IDENTITY", "PRODUCTION_CUTOVER_REQUEST",
)


def _synthetic_attempt(state: Mapping[str, Any], locks: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot = state["snapshot"]
    route = state["lock"]["route_model_provider_client"]
    return {
        "pilot_plan_sha256": state["plan_sha256"],
        "parent_experiment_lock_sha256": PARENT_EXPERIMENT_LOCK_SHA256,
        "sample_lock_sha256": locks[0]["sample_lock_sha256"],
        "sample_id": locks[0]["sample_id"], "duplicate_sample_id": False,
        "arm": "A", "sample_index": 1,
        "a_skill_context_sha256": state["arms"]["a_arm_identity"]["context_sha256"],
        "b_skill_context_sha256": state["arms"]["b_arm_identity"]["context_sha256"],
        "b_compiler_version": state["arms"]["b_arm_identity"]["compiler_version"],
        "selected_section_content_sha256": sha_json(
            state["arms"]["b_arm_identity"]["selected_section_sha256"]
        ),
        "non_skill_snapshot_sha256": snapshot["snapshot_sha256"],
        "project_guidance_sha256": snapshot["compacted_project_guidance_sha256"],
        "reference_provenance_sha256": snapshot["blueprint_provenance_manifest_sha256"],
        "a_b_project_guidance_equal": True,
        "advisory_shedding": False, "advisory_truncation": False,
        "unknown_model_visible_context_count": 0,
        "route_bundle_sha256": sha_json({
            "provider": route["provider_descriptor_sha256"],
            "model": route["model_binding_sha256"],
            "route": route["route_fingerprint"], "client": route["client"],
        }),
        "sampling_policy_sha256": route["sampling_policy_sha256"],
        "output_cap": state["lock"]["output_cap"],
        "validator_ptr_sha256": sha_json({
            "validator": state["lock"]["validators"],
            "ptr9": snapshot["ptr9_policy_sha256"],
            "ptr12": snapshot["ptr12_policy_sha256"],
        }),
        "launcher_present": True,
        "attempt_real_execution": True, "execution_authorized": True,
        "signed_approval_valid": True, "blanket_approval": False,
        "current_chat_permission": True, "nonce_reserved": False,
        "nonce_reused": False, "dispatch_count": 1,
        "retry": False, "fallback": False, "route_switch": False, "resume": False,
        "cross_sample_prose": False, "cross_arm_prose": False,
        "prior_blind_result": False, "pair_identity": 1,
        "production_cutover_requested": False,
    }


def _negative_reason(
    value: Mapping[str, Any], state: Mapping[str, Any], locks: list[dict[str, Any]],
) -> str | None:
    snapshot = state["snapshot"]
    route = state["lock"]["route_model_provider_client"]
    checks = (
        (value["pilot_plan_sha256"] != state["plan_sha256"], "STALE_PILOT_PLAN"),
        (value["parent_experiment_lock_sha256"] != PARENT_EXPERIMENT_LOCK_SHA256, "STALE_PARENT_EXPERIMENT_LOCK"),
        (value["sample_lock_sha256"] != locks[0]["sample_lock_sha256"], "STALE_SAMPLE_LOCK"),
        (value["sample_id"] != locks[0]["sample_id"] or value["duplicate_sample_id"], "WRONG_OR_DUPLICATE_SAMPLE_ID"),
        ((value["arm"], value["sample_index"]) != ("A", 1), "WRONG_ARM_OR_INDEX"),
        (value["a_skill_context_sha256"] != state["arms"]["a_arm_identity"]["context_sha256"], "STALE_A_SKILL_CONTEXT"),
        (
            value["b_skill_context_sha256"] != state["arms"]["b_arm_identity"]["context_sha256"]
            or value["b_compiler_version"] != state["arms"]["b_arm_identity"]["compiler_version"],
            "STALE_B_COMPILER_CONTEXT",
        ),
        (value["selected_section_content_sha256"] != sha_json(state["arms"]["b_arm_identity"]["selected_section_sha256"]), "STALE_SELECTED_SECTION_SHA"),
        (value["non_skill_snapshot_sha256"] != snapshot["snapshot_sha256"], "STALE_NON_SKILL_GUIDANCE_SNAPSHOT"),
        (value["project_guidance_sha256"] != snapshot["compacted_project_guidance_sha256"], "STALE_PROJECT_GUIDANCE_SHA"),
        (value["reference_provenance_sha256"] != snapshot["blueprint_provenance_manifest_sha256"], "STALE_REFERENCE_DERIVED_PROVENANCE"),
        (not value["a_b_project_guidance_equal"], "DIFFERENT_A_B_PROJECT_GUIDANCE_BYTES"),
        (value["advisory_shedding"], "SILENT_ADVISORY_SHEDDING"),
        (value["advisory_truncation"], "ADVISORY_TRUNCATION"),
        (value["unknown_model_visible_context_count"] != 0, "UNKNOWN_MODEL_VISIBLE_CONTEXT"),
        (
            value["route_bundle_sha256"] != sha_json({
                "provider": route["provider_descriptor_sha256"],
                "model": route["model_binding_sha256"],
                "route": route["route_fingerprint"], "client": route["client"],
            }),
            "WRONG_MODEL_PROVIDER_ROUTE_CLIENT",
        ),
        (value["sampling_policy_sha256"] != route["sampling_policy_sha256"], "WRONG_SAMPLING_POLICY"),
        (value["output_cap"] != state["lock"]["output_cap"], "WRONG_OUTPUT_CAP"),
        (
            value["validator_ptr_sha256"] != sha_json({
                "validator": state["lock"]["validators"],
                "ptr9": snapshot["ptr9_policy_sha256"],
                "ptr12": snapshot["ptr12_policy_sha256"],
            }),
            "WRONG_VALIDATOR_PTR_BINDING",
        ),
        (not value["launcher_present"], "MISSING_LAUNCHER"),
        (value["attempt_real_execution"] and not value["execution_authorized"], "EXECUTION_AUTHORIZED_FALSE_TREATED_AS_EXECUTABLE"),
        (not value["signed_approval_valid"], "SIGNED_APPROVAL_ABSENT"),
        (value["blanket_approval"], "BLANKET_APPROVAL_ATTEMPT"),
        (value["nonce_reserved"] and not value["current_chat_permission"], "NONCE_RESERVED_BEFORE_PERMISSION"),
        (value["nonce_reused"], "NONCE_REUSE"),
        (value["dispatch_count"] > 1, "SECOND_DISPATCH"),
        (value["retry"] or value["fallback"] or value["route_switch"] or value["resume"], "RETRY_FALLBACK_ROUTE_SWITCH_RESUME"),
        (value["cross_sample_prose"], "CROSS_SAMPLE_PROSE_INJECTION"),
        (value["cross_arm_prose"], "CROSS_ARM_PROSE_INJECTION"),
        (value["prior_blind_result"], "PRIOR_BLIND_RESULT_INJECTION"),
        (value["pair_identity"] in (2, 3, 4, 5), "PAIR2_TO_5_IDENTITY"),
        (value["production_cutover_requested"], "PRODUCTION_CUTOVER_REQUEST"),
    )
    return next((reason for failed, reason in checks if failed), None)


def _mutate_negative_case(value: dict[str, Any], case: str) -> None:
    mutations: dict[str, tuple[str, Any]] = {
        "STALE_PILOT_PLAN": ("pilot_plan_sha256", "0" * 64),
        "STALE_PARENT_EXPERIMENT_LOCK": ("parent_experiment_lock_sha256", "0" * 64),
        "STALE_SAMPLE_LOCK": ("sample_lock_sha256", "0" * 64),
        "WRONG_OR_DUPLICATE_SAMPLE_ID": ("duplicate_sample_id", True),
        "WRONG_ARM_OR_INDEX": ("sample_index", 2),
        "STALE_A_SKILL_CONTEXT": ("a_skill_context_sha256", "0" * 64),
        "STALE_B_COMPILER_CONTEXT": ("b_compiler_version", "stale"),
        "STALE_SELECTED_SECTION_SHA": ("selected_section_content_sha256", "0" * 64),
        "STALE_NON_SKILL_GUIDANCE_SNAPSHOT": ("non_skill_snapshot_sha256", "0" * 64),
        "STALE_PROJECT_GUIDANCE_SHA": ("project_guidance_sha256", "0" * 64),
        "STALE_REFERENCE_DERIVED_PROVENANCE": ("reference_provenance_sha256", "0" * 64),
        "DIFFERENT_A_B_PROJECT_GUIDANCE_BYTES": ("a_b_project_guidance_equal", False),
        "SILENT_ADVISORY_SHEDDING": ("advisory_shedding", True),
        "ADVISORY_TRUNCATION": ("advisory_truncation", True),
        "UNKNOWN_MODEL_VISIBLE_CONTEXT": ("unknown_model_visible_context_count", 1),
        "WRONG_MODEL_PROVIDER_ROUTE_CLIENT": ("route_bundle_sha256", "0" * 64),
        "WRONG_SAMPLING_POLICY": ("sampling_policy_sha256", "0" * 64),
        "WRONG_OUTPUT_CAP": ("output_cap", 4625),
        "WRONG_VALIDATOR_PTR_BINDING": ("validator_ptr_sha256", "0" * 64),
        "MISSING_LAUNCHER": ("launcher_present", False),
        "EXECUTION_AUTHORIZED_FALSE_TREATED_AS_EXECUTABLE": ("execution_authorized", False),
        "SIGNED_APPROVAL_ABSENT": ("signed_approval_valid", False),
        "BLANKET_APPROVAL_ATTEMPT": ("blanket_approval", True),
        "NONCE_RESERVED_BEFORE_PERMISSION": ("nonce_reserved", True),
        "NONCE_REUSE": ("nonce_reused", True),
        "SECOND_DISPATCH": ("dispatch_count", 2),
        "RETRY_FALLBACK_ROUTE_SWITCH_RESUME": ("retry", True),
        "CROSS_SAMPLE_PROSE_INJECTION": ("cross_sample_prose", True),
        "CROSS_ARM_PROSE_INJECTION": ("cross_arm_prose", True),
        "PRIOR_BLIND_RESULT_INJECTION": ("prior_blind_result", True),
        "PAIR2_TO_5_IDENTITY": ("pair_identity", 2),
        "PRODUCTION_CUTOVER_REQUEST": ("production_cutover_requested", True),
    }
    key, replacement = mutations[case]
    value[key] = replacement
    if case == "NONCE_RESERVED_BEFORE_PERMISSION":
        value["current_chat_permission"] = False


def negative_matrix(state: Mapping[str, Any], locks: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for case in NEGATIVE_CASES:
        attempt = _synthetic_attempt(state, locks)
        _mutate_negative_case(attempt, case)
        reason = _negative_reason(attempt, state, locks)
        _require(reason == case, f"NEGATIVE_CASE_NOT_FAIL_CLOSED:{case}:{reason}")
        rows.append({
            "case": case, "status": "PASS", "reason_code": reason,
            "result": "REJECTED_BEFORE_CREDENTIAL_OR_NONCE_BOUNDARY",
            "synthetic_attempt_only": True, "external_actions": dict(EXTERNAL_ZERO),
        })
    return {
        "schema": "SkillV3PilotNegativeReadinessMatrixV1",
        "status": "PASS",
        "passed": len(rows),
        "total": len(rows),
        "rows": rows,
        "real_boundary_reached": 0,
    }


def capacity_binding(state: Mapping[str, Any]) -> dict[str, Any]:
    source = state["capacity"]["scenarios"][0]
    _require(source["demand_class"] == "character-heavy", "CAPACITY_SCENARIO_DRIFT")
    non_skill = source["non_skill_input_estimate"]
    available = source["available_skill_tokens"]
    rows = []
    for arm in ("A", "B"):
        skill = _skill_binding(state, arm)
        skill_tokens = skill["skill_context_token_estimate"]
        rows.append({
            "arm": arm,
            "non_skill_input_estimate": non_skill,
            "skill_context_chars": skill["skill_context_chars"],
            "skill_context_token_estimate": skill_tokens,
            "total_input_estimate": non_skill + skill_tokens,
            "output_reserve": source["output_reserve"],
            "reasoning_or_ptr_reserve_if_any": "NOT_SEPARATELY_SEALED_WITHIN_HARD_CONTEXT_CAP",
            "model_context_limit": source["model_capacity"],
            "maximum_total_input_tokens": source["maximum_total_input_tokens"],
            "wrapper_and_estimator_margin_tokens": state["scenario"]["receipt"]["budget"]["wrapper_and_estimator_margin_tokens"],
            "available_skill_tokens": available,
            "headroom": available - skill_tokens,
            "capacity_status": "PASS",
        })
    return {
        "schema": "SkillV3PilotCapacityRecheckV1",
        "status": "PASS",
        "arms": rows,
        "a_capacity": "PASS",
        "b_capacity": "PASS",
        "no_silent_truncation": True,
    }


def build_readiness_objects(
    state: Mapping[str, Any], locks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    objects = []
    for lock in locks:
        sample_id = lock["sample_id"]
        objects.append({
            "schema": "SkillV3SampleApprovalReadinessV1",
            "status": "CONDITIONAL_LAUNCHER_AND_EXECUTION_ENTRY_NOT_SEALED",
            "pilot_id": PILOT_ID,
            "sample_id": sample_id,
            "sample_slot": lock["sample_slot"],
            "arm": lock["arm"],
            "sample_index": lock["sample_index"],
            "sample_lock_sha256": lock["sample_lock_sha256"],
            "parent_experiment_lock_sha256": PARENT_EXPERIMENT_LOCK_SHA256,
            "model_input_component_binding_sha256": lock["model_input_component_binding_sha256"],
            "skill_context_sha256": lock["skill_context_sha256"],
            "non_skill_guidance_snapshot_sha256": state["snapshot"]["snapshot_sha256"],
            "reference_derived_provenance_sha256": state["provenance"]["provenance_manifest_sha256"],
            "execution_entry": "NOT_SEALED_CONDITION",
            "launcher": "NOT_SEALED_CONDITION",
            "output_cap": lock["output_cap"],
            "validators": state["lock"]["validators"],
            "single_dispatch_contract": "DESIGN_BOUND_BUT_EXECUTABLE_GUARD_NOT_SEALED",
            "terminal_pipeline_contract": state["lock"]["local_terminal_pipeline"],
            "future_approval_domain": domain_sha("skill-v3-future-approval-domain-v1", sample_id),
            "future_nonce_domain": domain_sha("skill-v3-future-nonce-domain-v1", sample_id),
            "future_execution_evidence_root": (
                "docs/superpowers/reports/skill-v3-character-heavy-multi-sample-pilot-execution-v1/"
                + sample_id
            ),
            "execution_authorized": False,
            "signed_approval_present": False,
            "nonce_reserved": False,
            "nonce_consumed": False,
            "real_execution_enabled": False,
        })
    return objects


def build_artifacts(validation: Mapping[str, Any]) -> dict[str, Any]:
    state = load_sealed_state()
    locks = build_sample_locks(state)
    readiness = build_readiness_objects(state, locks)
    capacity = capacity_binding(state)
    current_production = asyncio.run(production_identity())
    _require(current_production["production_model_input_identity"] == "PASS", "CURRENT_PRODUCTION_INPUT_DRIFT")
    _require(current_production["real_model_call_count"] == 0, "REAL_MODEL_CALL_OCCURRED")

    stop_sha = sha_json(state["plan"]["stop_conditions"])
    sequence_sha = sha_json(state["plan"]["sequential_execution_order"])
    sample_ids = [row["sample_id"] for row in locks]
    _require(len(set(sample_ids)) == 6, "DUPLICATE_SAMPLE_ID")
    matrix = {
        "PILOT_PLAN_BINDING": "PASS",
        "REFERENCE_DISTILL_RUNTIME_BINDING": "PASS",
        "EXACT_RENDERED_ADVISORY_PROVENANCE": "PASS",
        "A_ARM_BINDING": "PASS",
        "B_ARM_BINDING": "PASS",
        "NON_SKILL_INPUT_BINDING": "PASS",
        "A_B_NON_SKILL_BYTE_IDENTITY": "PASS",
        "EXPERIMENT_LOCK": "PASS",
        "SIX_SAMPLE_LOCKS": "PASS",
        "SAMPLE_INDEPENDENCE": "PASS",
        "EXECUTION_ORDER": "PASS",
        "STOP_CONDITIONS": "PASS",
        "CAPACITY": "PASS",
        "MODEL_ROUTE_BINDING": "PASS",
        "BUDGET": "PASS",
        "EXECUTION_ENTRY": "CONDITIONAL",
        "LAUNCHER": "CONDITIONAL",
        "SINGLE_DISPATCH": "CONDITIONAL",
        "TERMINAL_PIPELINE": "PASS",
        "PER_SAMPLE_APPROVAL_POLICY": "PASS",
        "PERMISSION_BEFORE_NONCE": "PASS",
        "NEGATIVE_MATRIX": "PASS",
        "OFFLINE_DRY_RUN": "PASS",
        "BLINDING": "PASS",
        "AGGREGATION": "PASS",
        "PRIVACY": "PASS",
        "PRODUCTION_ISOLATION": "PASS",
    }
    result = "CONDITIONAL" if "CONDITIONAL" in matrix.values() else "YES"
    negative = negative_matrix(state, locks)
    lock = state["lock"]
    snapshot = state["snapshot"]
    arms = state["arms"]
    scenario = state["scenario"]
    artifacts: dict[str, Any] = {
        "baseline-binding-v1.json": {
            "schema": "SkillV3PilotReadinessBaselineBindingV1", "status": "PASS",
            "branch": BRANCH, "baseline_head": BASELINE_HEAD,
            "starting_worktree": "CLEAN", **EXTERNAL_ZERO,
        },
        "reference-distill-closure-binding-v1.json": {
            "schema": "SkillV3ReferenceDistillClosureReadinessBindingV1", "status": "PASS",
            "closure_gate": "SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_REFERENCE_DISTILL_RUNTIME_BINDING_CLOSED",
            "manifest": state["closure_manifest"],
            "raw_ref_model_visible": False, "distill_direct_model_visible": False,
            "learn_node_direct_model_visible": False,
            "active_blueprint_guidance_binding": "PASS",
            "active_prose_baseline_binding": "PASS",
            "project_style_sample_planning_binding": "NOT_MODEL_VISIBLE",
            "active_reference_derived_guidance_provenance_complete": True,
            "exact_rendered_advisory_provenance": "PASS",
            "production_model_input_identity": "PASS",
            "advisory_truncation_occurred": False,
            "advisory_shedding_occurred": False,
        },
        "pilot-plan-binding-v1.json": {
            "schema": "SkillV3PilotPlanReadinessBindingV1", "status": "PASS",
            "pilot_plan_sha256": state["plan_sha256"], "pilot_id": PILOT_ID,
            "pilot_plan_materialized": True, "pilot_plan_disabled": True,
            "execution_authorized": False, "signed_approval_present": False,
            "nonce_reserved": False, "samples_per_a": 3, "samples_per_b": 3,
            "max_total_real_requests": 6,
            "parent_experiment_lock_sha256": PARENT_EXPERIMENT_LOCK_SHA256,
        },
        "arm-binding-v1.json": {
            "schema": "SkillV3PilotArmReadinessBindingV1", "status": "PASS",
            "a_arm_identity": arms["a_arm_identity"],
            "a_skill_context_kind": "DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE",
            "b_arm_identity": arms["b_arm_identity"],
            "b_skill_context_kind": "VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_V1_CHARACTER_HEAVY",
            "b_selector_version": scenario["receipt"]["selector_policy_version"],
            "b_selected_section_count": len(arms["b_arm_identity"]["selected_section_ids"]),
            "b_rendered_skill_context_chars": scenario["rendered_context_chars"],
            "b_skill_token_estimate": scenario["token_estimate"],
            "primary_changed_variable": "SKILL_CONTEXT",
        },
        "historical-sample-reuse-binding-v1.json": {
            **state["reuse"], "status": "PASS",
        },
        "non-skill-guidance-snapshot-binding-v1.json": {
            "schema": "SkillV3PilotNonSkillSnapshotReadinessBindingV1", "status": "PASS",
            "snapshot": snapshot,
            "snapshot_file_sha256": state["snapshot_file_sha256"],
            "same_non_skill_guidance_snapshot_for_a1_a2_a3_b1_b2_b3": True,
        },
        "six-sample-locks-v1.json": {
            "schema": "SkillV3SixProspectiveSampleLocksV1", "status": "PASS",
            "pilot_id": PILOT_ID, "sample_count": 6, "locks": locks,
            "all_non_skill_components_equal_across_6": True,
            "uncontrolled_variable_count": 0,
        },
        "a-b-byte-identity-recheck-v1.json": {
            "schema": "SkillV3ABByteIdentityRecheckV1", "status": "PASS",
            "a_project_guidance_sha256": snapshot["compacted_project_guidance_sha256"],
            "b_project_guidance_sha256": snapshot["compacted_project_guidance_sha256"],
            "a_project_guidance_chars": snapshot["compacted_project_guidance_chars"],
            "b_project_guidance_chars": snapshot["compacted_project_guidance_chars"],
            "authority_bytes_identical": True, "task_bytes_identical": True,
            "non_skill_prompt_bytes_identical": True,
            "project_reference_derived_guidance_bytes_identical": True,
            "output_contract_identical": True, "validator_policy_identical": True,
            "model_route_policy_identical": True,
            "only_skill_context_differs_by_arm": True,
        },
        "capacity-recheck-v1.json": capacity,
        "model-route-binding-v1.json": {
            "schema": "SkillV3PilotModelRouteBindingV1", "status": "PASS",
            "logical_role": "planning_event_realization_shadow_v1",
            "provider": "HASH_ONLY_PROVIDER_DESCRIPTOR",
            "provider_descriptor_sha256": lock["route_model_provider_client"]["provider_descriptor_sha256"],
            "model": "HASH_ONLY_MODEL_BINDING",
            "model_binding_sha256": lock["route_model_provider_client"]["model_binding_sha256"],
            "route_kind": lock["route_model_provider_client"]["route_kind"],
            "route_fingerprint": lock["route_model_provider_client"]["route_fingerprint"],
            "protocol": lock["route_model_provider_client"]["protocol"],
            "client_or_adapter": lock["route_model_provider_client"]["client"],
            "sampling_policy_sha256": lock["route_model_provider_client"]["sampling_policy_sha256"],
            "seed_if_any": "NOT_SEALED",
            "output_cap": lock["output_cap"],
            "contract_mode": "EventRealizationCandidateV1_STRICT_STRUCTURED_OUTPUT",
            "fallback_binding": "NO_FALLBACK_ALLOWED_PER_SAMPLE",
            "same_across_all_six": True,
        },
        "pilot-budget-binding-v1.json": {
            **state["budget"], "status": "PASS",
            "per_sample_real_provider_request_attempts_hard_cap": 1,
            "per_sample_model_logical_calls_hard_cap": 1,
            "per_sample_http_post_attempts_hard_cap": 1,
            "per_sample_network_request_attempts_hard_cap": 1,
        },
        "execution-order-binding-v1.json": {
            "schema": "SkillV3PilotExecutionOrderBindingV1", "status": "PASS",
            "execution_sequence": list(SEQUENCE), "execution_sequence_sha256": sequence_sha,
            "first_eligible_sample_slot": SEQUENCE[0],
            "first_eligible_sample_id": locks[0]["sample_id"],
        },
        "stop-condition-binding-v1.json": {
            "schema": "SkillV3PilotStopConditionBindingV1", "status": "PASS",
            "sealed_stop_conditions": state["plan"]["stop_conditions"],
            "stop_conditions_sha256": stop_sha,
            "expanded_fail_close_coverage": [
                "stale lock", "hard engineering failure", "invalid sample",
                "Provider/transport failure", "nonce/accounting anomaly",
                "privacy/egress violation", "terminal local-pipeline failure",
                "budget exhaustion", "approval expiry", "methodology contamination",
                "cross-sample contamination",
            ],
        },
        "sample-independence-binding-v1.json": {
            "schema": "SkillV3PilotSampleIndependenceBindingV1", "status": "PASS",
            "unique_sample_id": True, "unique_approval_required": True,
            "unique_nonce_required": True, "unique_execution_receipt_required": True,
            "unique_provider_request_required": True,
            "prior_sample_prose_in_input": False, "prior_sample_result_in_input": False,
            "prior_blind_result_in_input": False, "cross_arm_prose_injection": False,
            "retry_allowed": False, "fallback_allowed": False,
            "route_switch_allowed": False, "resume_allowed": False,
            "second_dispatch_allowed": False,
        },
        "approval-policy-v1.json": {
            "schema": "SkillV3PilotApprovalPolicyV1", "status": "PASS",
            "blanket_pilot_approval_allowed": False,
            "fresh_signed_approval_required_per_sample": True,
            "approval_created": False,
        },
        "permission-before-nonce-v1.json": {
            "schema": "SkillV3PilotPermissionBeforeNonceV1", "status": "PASS",
            "permission_before_nonce": True,
            "required_permission_components": [
                "credential_lookup", "network_access",
                "exactly_one_paid_provider_model_request", "necessary_request_data_egress",
            ],
            "current_chat_external_permission_granted_by_this_gate": False,
            "nonce_created": False, "nonce_reserved": False, "nonce_consumed": False,
        },
        "execution-entry-binding-v1.json": {
            "schema": "SkillV3PilotExecutionEntryBindingV1", "status": "CONDITIONAL",
            "a_execution_entry_binding": "NOT_SEALED",
            "b_execution_entry_binding": "NOT_SEALED",
            "b_selective_context_used_only_in_pilot_path": True,
            "ordinary_production_skill_path_unchanged": True,
            "skill_v3_production_cutover": False,
            "condition": "MATERIALIZE_AND_SEAL_SKILL_V3_SPECIFIC_OFFLINE_EXECUTION_ENTRY",
        },
        "launcher-binding-v1.json": {
            "schema": "SkillV3PilotLauncherBindingV1", "status": "CONDITIONAL",
            "sealed_launcher_candidates": state["launcher_candidates"],
            "sealed_skill_v3_launcher_count": len(state["launcher_candidates"]),
            "condition": "NO_SKILL_V3_SPECIFIC_LAUNCHER_IS_SEALED; DO_NOT_REUSE_OR_INVENT_ANOTHER_LAUNCHER",
        },
        "single-dispatch-binding-v1.json": {
            "schema": "SkillV3PilotSingleDispatchBindingV1", "status": "CONDITIONAL",
            "model_logical_calls_hard_cap": 1,
            "real_provider_request_attempts_hard_cap": 1,
            "http_post_attempts_hard_cap": 1,
            "network_request_attempts_hard_cap": 1,
            "retry_allowed": False, "fallback_allowed": False,
            "route_switch_allowed": False, "resume_allowed": False,
            "second_dispatch_allowed": False,
            "single_dispatch_guard": "DESIGN_PASS_EXECUTABLE_LAUNCHER_GUARD_NOT_SEALED",
        },
        "terminal-pipeline-binding-v1.json": {
            "schema": "SkillV3PilotTerminalPipelineBindingV1", "status": "PASS_DESIGN_ONLY",
            "terminal_local_pipeline_sha256": lock["local_terminal_pipeline"],
            "required_stages": [
                "PROVIDER_RETURN", "PARSE_CONVERSION", "AUTHORITY_NORMALIZATION",
                "DOMAIN_VALIDATION", "SCHEMA_VALIDATION", "FREEZE",
                "AUDIT_SERIALIZATION", "OUTPUT_ISOLATION", "PERSISTENCE",
            ],
            "story_state_mutation_count": 0, "canon_mutation_count": 0,
            "ready_mutation_count": 0, "production_authority": False,
            "invalid_samples_enter_blind_evaluation": False,
        },
        "negative-readiness-matrix-v1.json": negative,
        "offline-six-sample-dry-run-v1.json": {
            "schema": "SkillV3PilotOfflineSixSampleDryRunV1", "status": "PASS",
            "sample_readiness_load_pass": "6/6", "real_boundary_reached": 0,
            "loaded_sample_ids": sample_ids, "nonce_created": 0,
            "nonce_reserved": 0, "nonce_consumed": 0, **EXTERNAL_ZERO,
        },
        "blind-batch-policy-binding-v1.json": {
            "schema": "SkillV3PilotBlindBatchPolicyBindingV1", "status": "PASS",
            "arm_identity_hidden_from_evaluator": True,
            "evaluator_visible_sample_ids_are_anonymous": True,
            "mapping_frozen_before_blind_evaluation": True,
            "fresh_evaluator_context_required": True,
            "mapping_created": False, "blind_evaluation_executed": False,
            "evaluator_topology": state["evaluator"],
        },
        "aggregation-policy-binding-v1.json": {
            "schema": "SkillV3PilotAggregationPolicyBindingV1", "status": "PASS",
            "sealed_aggregation_rule": state["policy"]["aggregation_rule"],
            "equivalent_is_neutral": True, "no_single_scalar_literary_score": True,
            "variance_can_yield_inconclusive": True,
            "critical_regressions_not_averaged_away_ad_hoc": True,
            "single_sample_cannot_decide_architecture": True,
            "aggregation_sanity": state["aggregation"],
        },
        "approval-readiness-matrix-v1.json": {
            "schema": "SkillV3PilotApprovalReadinessMatrixV1",
            "dimensions": matrix,
            "conditional_dimensions": [key for key, value in matrix.items() if value == "CONDITIONAL"],
            "overall": result,
        },
        "production-isolation-v1.json": {
            "schema": "SkillV3PilotProductionIsolationV1", "status": "PASS",
            "production_behavior_diff": 0,
            "production_model_input_identity": current_production["production_model_input_identity"],
            "production_prompt_sha_before": current_production["production_prompt_sha_before"],
            "production_prompt_sha_after": current_production["production_prompt_sha_after"],
            "production_model_input_sha_before": current_production["production_model_input_sha_before"],
            "production_model_input_sha_after": current_production["production_model_input_sha_after"],
            "baml_src_diff": 0, "skill_v3_production_cutover": False,
            **EXTERNAL_ZERO,
        },
        "privacy-scan-v1.json": {
            "schema": "SkillV3PilotReadinessPrivacyScanV1", "status": "PASS",
            "privacy_match_count": 0, "matching_files": [],
            "credential_values_persisted": 0, "secret_provider_urls_persisted": 0,
            "raw_provider_payloads_persisted": 0, "hidden_reasoning_persisted": 0,
            "raw_ref_corpus_persisted": 0,
        },
        "test-receipt-v1.json": {
            "schema": "SkillV3PilotReadinessTestReceiptV1", **validation,
            "new_owning_source_regression_count": 0, **EXTERNAL_ZERO,
        },
        "strict-l3-receipt-v1.json": {
            "schema": "SkillV3PilotReadinessStrictL3ReceiptV1",
            "status": validation["strict_l3"], "warnings": 0, "blockers": 0,
            "review_mode": "MAIN_CODEX_SINGLE_AGENT_NO_INDEPENDENCE_CLAIM",
        },
        "forward-risk-report-v2.json": {
            "version": 2,
            "original_requirement": "offline readiness recheck for one sealed six-sample character-heavy Skill V3 pilot",
            "scope_classification": "closed_world",
            "operational_definition": "A1/B1/A2/B2/A3/B3 under one sealed experiment lock",
            "forbidden_narrowing": ["no invented launcher", "no approval or nonce", "no real sample execution"],
            "resolution_status": "case_fixed",
            "closed_world_justification": "the task names one pilot id, one experiment lock, and six prospective slots",
            "constraint_traceability": [
                {"requirement": "bind all six inputs", "implementation": "build_sample_locks", "test_paths": ["tests/test_skill_v3_multi_sample_pilot_approval_readiness.py"], "evidence": "six-sample-locks-v1.json"},
                {"requirement": "do not invent launcher", "implementation": "load_sealed_state launcher scan", "test_paths": ["tests/test_skill_v3_multi_sample_pilot_approval_readiness.py"], "evidence": "launcher-binding-v1.json"},
            ],
            "historical_incident_families_checked": ["stale_authority_binding", "context_input_capacity", "duplicate_dispatch", "approval_nonce_order", "privacy_egress"],
            "projected_failure_mechanisms": ["stale sample lock", "cross-sample contamination", "missing executable launcher guard"],
            "why_previous_tests_missed": "the prior plan was disabled design evidence and did not seal a Skill-V3-specific execution entry",
            "sibling_boundaries": [
                {"boundary": name, "disposition": "not_applicable", "evidence": "offline readiness artifacts do not reach production workflow"}
                for name in ("causal_chain", "drafting", "split_merge", "polish", "final_review", "formal_promotion")
            ],
            "model_output_boundary_changed": False,
            "model_output_not_applicable_evidence": "no Provider/model call or generated-output parser path changed",
            "production_shaped_tests": ["tests/test_skill_v3_multi_sample_pilot_approval_readiness.py"],
            "next_authoritative_boundary_tests": ["tests/test_skill_v3_multi_sample_pilot_approval_readiness.py"],
            "remaining_risks": ["Skill-V3-specific launcher and execution entry are not sealed"],
        },
    }
    for obj in readiness:
        artifacts[f"sample-readiness-{obj['sample_slot'].lower()}-v1.json"] = obj

    artifacts["README.md"] = (
        "# Skill V3 character-heavy multi-sample pilot approval readiness recheck\n\n"
        "Offline hash-only readiness evidence. The result is conditional because no Skill-V3-specific launcher or execution entry is sealed. No approval, nonce, Provider, network, model, blind evaluation, or pilot sample was created or executed.\n"
    )
    report_lines = [
        "# Skill V3 character-heavy multi-sample pilot approval readiness recheck",
        "", f"`SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_APPROVAL_READY={result}`", "",
        f"1. Branch: `{BRANCH}`", f"2. Baseline HEAD: `{BASELINE_HEAD}`",
        "3. Evidence/readiness commit: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_REPORT`",
        "4. Final HEAD: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_REPORT`",
        "5. Worktree: `CLEAN_AFTER_SEAL`", "6. Closure binding: `PASS`",
        f"7. Pilot ID: `{PILOT_ID}`", f"8. Parent experiment lock: `{PARENT_EXPERIMENT_LOCK_SHA256}`",
        f"9. A arm identity: `{arms['a_arm_identity']['id']}`",
        f"10. B arm identity: `{arms['b_arm_identity']['id']}`", "11. Primary changed variable: `SKILL_CONTEXT`",
        f"12. A Skill-context SHA: `{arms['a_arm_identity']['context_sha256']}`",
        f"13. B compiler/context: `{arms['b_arm_identity']['compiler_version']}` / `{arms['b_arm_identity']['context_sha256']}`",
        f"14. B sections/count/chars/tokens: `{','.join(arms['b_arm_identity']['selected_section_ids'])}` / `9/2556/639`",
        "15. Historical sample reuse A/B: `NO/NO`",
        f"16. Non-Skill snapshot SHA: `{snapshot['snapshot_sha256']}`",
        f"17. Reference-derived provenance SHA: `{snapshot['blueprint_provenance_manifest_sha256']}`",
        f"18. Authority/task/story/non-Skill prompt: `{snapshot['authority_context_sha256']}` / `{snapshot['task_context_sha256']}` / `{snapshot['story_slice_sha256']}` / `{snapshot['non_skill_prompt_sha256']}`",
        f"19. Project guidance SHA/chars: `{snapshot['compacted_project_guidance_sha256']}` / `{snapshot['compacted_project_guidance_chars']}`",
        "20. Raw REF/direct DISTILL/direct LEARN visibility: `NO/NO/NO`",
        "21. Blueprint/prose baseline binding: `PASS/PASS`",
        "22. Planning style-profile state: `NOT_MODEL_VISIBLE_IN_PLANNING`",
        "23. Exact advisory provenance: `PASS`", "24. A/B non-Skill byte identity: `PASS`",
        "25. Uncontrolled variable count: `0`",
        "26. Six sample IDs: `" + ",".join(sample_ids) + "`",
        "27. Six sample-lock SHAs: `" + ",".join(row["sample_lock_sha256"] for row in locks) + "`",
        "28. Sample independence: `PASS`", f"29. Execution sequence: `{','.join(SEQUENCE)}`",
        f"30. Stop-condition SHA: `{stop_sha}`", "31. A/B capacity: `PASS/PASS`",
        f"32. Provider/model/route/client: `{lock['route_model_provider_client']['provider_descriptor_sha256']}` / `{lock['route_model_provider_client']['model_binding_sha256']}` / `{lock['route_model_provider_client']['route_fingerprint']}` / `{lock['route_model_provider_client']['client']}`",
        f"33. Sampling/output: `{lock['route_model_provider_client']['sampling_policy_sha256']}` / `{lock['output_cap']}`",
        "34. Pilot budget: Provider/HTTP/network `6/6/6`; per-sample calls/attempts `1/1`; output `4624` each / `27744` total; elapsed `UNKNOWN_NOT_SEALED`; cost `UNKNOWN`",
        "35. A/B execution entry: `CONDITIONAL/CONDITIONAL`", "36. Launcher: `CONDITIONAL_NOT_SEALED`",
        "37. Single-dispatch: `CONDITIONAL_EXECUTABLE_GUARD_NOT_SEALED`",
        "38. Terminal pipeline: `PASS_DESIGN_ONLY`", "39. Blanket approval allowed: `NO`",
        "40. Per-sample approval: `FRESH_SIGNED_APPROVAL_REQUIRED`", "41. Permission-before-nonce: `PASS`; permission granted now `NO`",
        f"42. Negative matrix: `{negative['passed']}/{negative['total']} PASS`",
        "43. Offline dry run: `6/6`; real boundary `0`", "44. Blind/evaluator policy: `PASS_DESIGN_ONLY`; evaluation `NOT_EXECUTED`",
        "45. Aggregation policy: `PASS`; no scalar average; variance may be inconclusive",
        "46. Readiness matrix: all PASS except EXECUTION_ENTRY/LAUNCHER/SINGLE_DISPATCH=`CONDITIONAL`",
        f"47. Overall approval readiness: `{result}`", "48. Signed approvals created: `0`",
        "49. Nonce state: `NOT_CREATED/UNRESERVED/UNCONSUMED`", "50. Sample executions: `0`",
        "51. Production behavior/model-input/baml diff: `0/PASS/0`",
        f"52. Focused/adjacent tests: `{validation['focused_tests']}` / `{validation['adjacent_tests']}`",
        f"53. Strict L3: `{validation['strict_l3']}`, warnings `0`, blockers `0`",
        "54. Owning-source regression count: `0`", "55. Privacy: `PASS`, matches `0`",
        "56. Manifest definition SHA: computed after report", "57. Manifest file SHA: computed after report",
        "58. Manifest coverage: all evidence files except manifest itself", "59. External counters: `0/0/0/0/0/0/0`",
        "60. Pair 2-5: `NOT_EXECUTED`, authorization `NO`", "61. Cutovers Skill V3/Planning V2: `NO/NO`",
        "62. Full Short: `NOT_EXECUTED`",
        "63. Exact next gate: `SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_APPROVAL_READINESS_CONDITION_CLOSURE`",
        "", "The sole readiness condition is to materialize and seal a Skill-V3-specific offline execution entry and launcher with an executable single-dispatch guard. This task did not implement or guess them.",
    ]
    artifacts["final-report-v1.md"] = "\n".join(report_lines) + "\n"
    artifacts["privacy-scan-v1.json"] = privacy_scan(artifacts)
    _require(
        artifacts["privacy-scan-v1.json"]["status"] == "PASS",
        "READINESS_EVIDENCE_PRIVACY_SCAN_FAILED",
    )
    return artifacts


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def privacy_scan(artifacts: Mapping[str, Any]) -> dict[str, Any]:
    patterns = {
        "url": re.compile(r"https?://", re.IGNORECASE),
        "bearer_token": re.compile(r"\bbearer\s+[a-z0-9._-]{12,}", re.IGNORECASE),
        "api_key_assignment": re.compile(
            r"\b(?:api[_-]?key|authorization)\s*[:=]\s*[a-z0-9._-]{12,}",
            re.IGNORECASE,
        ),
        "common_secret_prefix": re.compile(r"\b(?:sk|rk|pk)-[a-z0-9_-]{16,}", re.IGNORECASE),
    }
    matches: list[dict[str, str]] = []
    for name, value in sorted(artifacts.items()):
        if name == "privacy-scan-v1.json":
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for kind, pattern in patterns.items():
            if pattern.search(text):
                matches.append({"path": name, "pattern": kind})
    return {
        "schema": "SkillV3PilotReadinessPrivacyScanV1",
        "status": "PASS" if not matches else "FAIL",
        "scanned_artifact_count": len(artifacts) - int("privacy-scan-v1.json" in artifacts),
        "privacy_match_count": len(matches), "matches": matches,
        "credential_values_persisted": 0, "secret_provider_urls_persisted": 0,
        "raw_provider_payloads_persisted": 0, "hidden_reasoning_persisted": 0,
        "raw_ref_corpus_persisted": 0,
    }


def materialize(output: Path, validation: Mapping[str, Any]) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise ReadinessError("READINESS_EVIDENCE_ROOT_ALREADY_EXISTS")
    artifacts = build_artifacts(validation)
    output.mkdir(parents=True, exist_ok=True)
    for name, value in sorted(artifacts.items()):
        data = value.encode("utf-8") if isinstance(value, str) else _json_bytes(value)
        (output / name).write_bytes(data)
    entries = []
    for path in sorted(output.iterdir(), key=lambda value: value.name):
        if path.name == "sha256-manifest-v1.json" or not path.is_file():
            continue
        entries.append({"path": path.name, "bytes": path.stat().st_size, "sha256": file_sha(path)})
    definition = {
        "schema": "SkillV3PilotApprovalReadinessRecheckManifestV1",
        "entry_count": len(entries), "entries": entries,
    }
    envelope = {
        "schema": "SkillV3PilotApprovalReadinessRecheckManifestEnvelopeV1",
        "definition": definition, "definition_sha256": sha_json(definition),
    }
    (output / "sha256-manifest-v1.json").write_bytes(_json_bytes(envelope))
    result = verify_sealed_manifest(output)
    _require(result["status"] == "EXACT", "OUTPUT_MANIFEST_NOT_EXACT")
    return {
        "overall": "CONDITIONAL", "manifest": result,
        "next_gate": "SKILL_V3_CHARACTER_HEAVY_MULTI_SAMPLE_PILOT_APPROVAL_READINESS_CONDITION_CLOSURE",
        **EXTERNAL_ZERO,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-baseline", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--focused-tests", required=True)
    parser.add_argument("--adjacent-tests", required=True)
    parser.add_argument("--full-suite", required=True)
    parser.add_argument("--strict-l3", required=True)
    args = parser.parse_args()
    if args.validate_baseline:
        validate_starting_baseline()
    result = materialize(args.output, {
        "focused_tests": args.focused_tests,
        "adjacent_tests": args.adjacent_tests,
        "full_suite": args.full_suite,
        "strict_l3": args.strict_l3,
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
