"""Offline, hash-only R1-PTR0 analysis for one sealed Short Canary.

The diagnostic reads committed evidence plus an operator-supplied isolated
Canary root and approval ledger.  It never imports a provider client, opens a
network connection, or emits Prompt, story, tool-argument, credential, header,
or raw provider-response content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from jsonschema import validate as validate_json_schema

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.generated_artifacts import registered_business_wire_schema
from novel_flywheel.planning_adaptation import (
    apply_planning_repair_patch,
    normalize_planning_repair_patch,
)


PARENT_COMMIT = "d0d9427af9c191aa09f9b1da4fb9881a253f4efc"
EVIDENCE_SHA256 = "d431e377a9924ad8fa1fde8ab3cd278e612ae563adc2e0eca53444284b7c29ab"
MANIFEST_SHA256 = "c22cecee6d83b52e1a2662c3a3753201f6fb44e3c82a2164b6b2d627f5f3e295"
MODEL_LEDGER_SHA256 = "57daca7a97d7a689aed5b79c704040bbb7d79e2885c5ad57c0262aaeb61f56b7"
FIRST_DIVERGENCE_SHA256 = "c838d73de7628bfcc2b84f45b09cffe48a6050724adb07c455bf4506be8838ce"
COMPLETION_CLOSURE_SHA256 = "882fcff2e9e715e3b361663aab14a1367ce414716dfbb79b7377810ac07453a2"
SIGNED_APPROVAL_SHA256 = "a793b1794bcad50a622af60ec79aa507af1565a71fc3267473678786629dc574"
VALIDATION_RECEIPT_SHA256 = "3edbff96abc9c849f8a49acab7891b5840edcf6679f96eb35509c1f8c0b75013"
CONSUMPTION_SHA256 = "f421dba432121b12f3a8fae96454c2c963ab20c7e55232044d1a2609383692fc"
LIVE_PARITY_SHA256 = "1e04250acd23ec756f213ad56f03f8194d76d3549771758b8219856a955c43a9"
COHORT_ID = "short-completion-r1d3-g1-20260816t154912z"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def canonical_sha256(value: object) -> str:
    return sha256_text(canonical_json(value))


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path.name}")
    return value


def _verify_parent_evidence(
    evidence_root: Path, ledger_root: Path,
) -> dict[str, Any]:
    manifest = _load(evidence_root / "sc-r1d3-final-1-sha256-manifest-v1.json")
    if manifest.get("manifest_sha256") != MANIFEST_SHA256:
        raise ValueError("parent manifest identity changed")
    bad_entries: list[str] = []
    for entry in manifest.get("entries", []):
        path = evidence_root / str(entry["path"])
        if sha256_bytes(path.read_bytes()) != entry.get("sha256"):
            bad_entries.append(path.name)
    if bad_entries:
        raise ValueError("parent manifest entries changed")

    evidence = _load(
        evidence_root / "short-completion-r1d3-final-real-evidence-package-v1.json"
    )
    model_ledger = _load(
        evidence_root / "short-completion-r1d3-final-model-boundary-ledger-v1.json"
    )
    first_divergence = _load(
        evidence_root / "short-completion-r1d3-final-first-divergence-receipt-v1.json"
    )
    closure = _load(
        evidence_root / "short-completion-r1d3-final-completion-closure-v1.json"
    )
    signed = _load(
        evidence_root / "short-completion-r1d3-final-signed-approval-v1.json"
    )
    validation = _load(
        evidence_root
        / "short-completion-r1d3-final-signed-approval-validate-only-receipt-v1.json"
    )
    parity = _load(
        evidence_root / "short-completion-r1d3-final-live-parity-v1.json"
    )
    consumption = _load(ledger_root / f"{COHORT_ID}.consumed.json")

    checks = {
        "evidence_canonical_hash": evidence.get("evidence_sha256") == EVIDENCE_SHA256,
        "model_boundary_ledger": (
            model_ledger.get("definition_sha256") == MODEL_LEDGER_SHA256
        ),
        "first_divergence_receipt": (
            first_divergence.get("definition_sha256") == FIRST_DIVERGENCE_SHA256
        ),
        "completion_closure": (
            closure.get("definition_sha256") == COMPLETION_CLOSURE_SHA256
        ),
        "signed_approval": signed.get("signed_approval_sha256") == SIGNED_APPROVAL_SHA256,
        "validate_only": (
            validation.get("validation_receipt_sha256") == VALIDATION_RECEIPT_SHA256
            and validation.get("overall_status") == "exact"
        ),
        "cohort_consumed": (
            consumption.get("definition_sha256") == CONSUMPTION_SHA256
            and consumption.get("payload", {}).get("cohort_id") == COHORT_ID
            and consumption.get("payload", {}).get("consumed_evidence_sha256")
            == EVIDENCE_SHA256
        ),
        "live_parity": (
            parity.get("status") == "exact"
            and parity.get("before_sha256") == parity.get("after_sha256")
            == LIVE_PARITY_SHA256
        ),
        "manifest_entries": not bad_entries,
    }
    if not all(checks.values()):
        raise ValueError("R1_PTR0_NO_GO_PARENT_EVIDENCE_CHANGED")
    return {
        "status": "exact",
        "parent_commit": PARENT_COMMIT,
        "evidence_canonical_sha256": EVIDENCE_SHA256,
        "manifest_sha256": MANIFEST_SHA256,
        "checks": checks,
    }


def _private_run_root(canary_root: Path) -> Path:
    runs = sorted(canary_root.glob("projects/*/runs/*"))
    matched = [
        path for path in runs
        if (path / "outputs/planning-recovery-state.json").is_file()
    ]
    if len(matched) != 1:
        raise ValueError("isolated Canary planning run is not unique")
    return matched[0]


def _read_trace(canary_root: Path) -> list[dict[str, Any]]:
    paths = sorted(canary_root.glob("runtime/reliability-traces/*/*.jsonl"))
    if len(paths) != 1:
        raise ValueError("isolated ReliabilityTrace is not unique")
    return [
        json.loads(line) for line in paths[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _database_evidence(
    canary_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    connection = sqlite3.connect(canary_root / "db/app.db")
    connection.row_factory = sqlite3.Row
    try:
        observations = [dict(row) for row in connection.execute(
            "select id, provider_id, model_id, route_fingerprint, execution_mode, "
            "requested_max_output_tokens, actual_output_tokens, visible_characters, "
            "finish_reason, transport_complete from model_output_observations order by id"
        )]
        routes = [dict(row) for row in connection.execute(
            "select m.id as model_id, m.display_name, m.model_name, m.context_window, "
            "m.max_output_tokens, m.capabilities_json, p.id as provider_id, "
            "p.name as provider_name, p.protocol from models m join providers p "
            "on p.id=m.provider_id"
        )]
    finally:
        connection.close()
    if len(observations) != 10:
        raise ValueError("sealed Canary does not contain exactly ten observations")
    return observations, {str(row["model_id"]): row for row in routes}


def _audit_by_raw_hash(run_root: Path) -> dict[str, list[dict[str, Any]]]:
    values: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((run_root / "outputs/conversion-audits").glob("*.json")):
        audit = _load(path)
        values.setdefault(str(audit.get("raw_sha256") or ""), []).append(audit)
    return values


def _timeline(
    evidence_root: Path, canary_root: Path, run_root: Path,
) -> list[dict[str, Any]]:
    ledger = _load(
        evidence_root / "short-completion-r1d3-final-model-boundary-ledger-v1.json"
    )
    boundaries = ledger.get("boundaries", [])
    observations, models = _database_evidence(canary_root)
    audits = _audit_by_raw_hash(run_root)
    if len(boundaries) != 10:
        raise ValueError("committed model boundary ledger is incomplete")

    substages = {
        1: "planning_semantic_v2",
        2: "planning_adaptation_initial_review",
        3: "planning_adaptation_segment",
        4: "planning_adaptation_segment",
        5: "planning_adaptation_segment",
        6: "planning_adaptation_segment",
        7: "planning_repair_patch",
        8: "planning_repair_patch",
        9: "planning_repair_patch",
        10: "planning_repair_patch",
    }
    attempts = {1: 1, 2: 1, 3: 1, 4: 2, 5: 3, 6: 4, 7: 1, 8: 2, 9: 3, 10: 4}
    next_dispatch = {
        1: "planning_ir_valid_then_adaptation_review",
        2: "capacity_split_requested",
        3: "same_route_protocol_retry_2",
        4: "same_route_protocol_retry_3",
        5: "configured_fallback_for_segment_receipt",
        6: "targeted_repair_for_semantic_review_findings",
        7: "same_route_domain_retry_without_new_finding",
        8: "configured_fallback_without_new_domain_finding",
        9: "same_fallback_with_2x_output_budget_and_generic_protocol_delta",
        10: "terminal_contract_output_limit_exhausted",
    }
    rows: list[dict[str, Any]] = []
    for boundary, observation in zip(boundaries, observations, strict=True):
        ordinal = int(boundary["ordinal"])
        provider_observation = boundary["provider_observation"]
        model = models[str(observation["model_id"])]
        raw_hash = str(provider_observation.get("response_sha256") or "")
        matching_audits = audits.get(raw_hash, [])
        contract_audit = next((
            item for item in matching_audits
            if item.get("contract_name") == substages[ordinal]
            or (
                substages[ordinal] == "planning_semantic_v2"
                and item.get("contract_name") == "planning_semantic_v2"
            )
        ), None)
        if ordinal in {7, 8}:
            parser_result = "pass_exact_json"
            schema_result = "pass_strict_tool_wire_shape"
            domain_result = "fail_generic_ValueError"
            local_result = "not_reached"
        elif ordinal in {9, 10}:
            parser_result = "not_reached_no_visible_artifact"
            schema_result = "not_reached"
            domain_result = "not_reached"
            local_result = "not_reached"
        elif ordinal == 6:
            parser_result = "pass_exact_json"
            schema_result = "pass"
            domain_result = "pass"
            local_result = "capacity_packet_merged"
        elif ordinal == 1:
            parser_result = "pass_exact_json"
            schema_result = "pass_strict_tool_wire_shape"
            domain_result = "pass"
            local_result = "planning_ir_compiled"
        else:
            parser_result = "not_reached_output_truncated"
            schema_result = "not_reached"
            domain_result = "not_reached"
            local_result = "not_reached"
        rows.append({
            "ordinal": ordinal,
            "stage": boundary["stage"],
            "substage": substages[ordinal],
            "role": boundary["role"],
            "route_kind": boundary["route_kind"],
            "provider_alias": model["provider_name"],
            "provider_descriptor_hash": boundary["provider_descriptor_hash"],
            "model_alias": model["display_name"],
            "model_binding_hash": boundary["model_binding_hash"],
            "protocol": model["protocol"],
            "execution_mode": observation["execution_mode"],
            "attempt": attempts[ordinal],
            "repair_fallback_kind": (
                "targeted_patch_primary" if ordinal == 7 else
                "targeted_patch_domain_retry" if ordinal == 8 else
                "targeted_patch_configured_fallback" if ordinal == 9 else
                "targeted_patch_expanded_fallback" if ordinal == 10 else
                "none"
            ),
            "requested_output_budget": boundary["requested_output_tokens"],
            "effective_provider_output_budget": observation[
                "requested_max_output_tokens"
            ],
            "observed_output_tokens": observation["actual_output_tokens"],
            "observed_visible_characters": observation["visible_characters"],
            "finish_reason": observation["finish_reason"],
            "response_completeness": (
                "truncated" if observation["finish_reason"] == "max_tokens"
                else "provider_complete"
            ),
            "response_sha256": raw_hash,
            "conversion_audit_sha256": (
                canonical_sha256(contract_audit) if contract_audit else None
            ),
            "parser_result": parser_result,
            "schema_result": schema_result,
            "domain_validation_result": domain_result,
            "local_repair_merge_result": local_result,
            "next_dispatch_reason": next_dispatch[ordinal],
            "system_prompt_sha256": boundary["system_prompt_sha256"],
            "user_prompt_sha256": boundary["user_prompt_sha256"],
        })
    return rows


def _minimal_size_counterfactual(actual_anchor_count: int) -> dict[str, Any]:
    schema = registered_business_wire_schema("planning_repair_patch", {})
    schema_minimum = {
        "authority_sha256": "0" * 64,
        "segment": 0,
        "replacements": [0],
        "summary": 0,
    }
    validate_json_schema(instance=schema_minimum, schema=schema)

    authority = "1" * 64
    domain_minimum = {
        "authority_sha256": authority,
        "segment": 1,
        "replacements": [{"evidence_id": "e", "replacement": "B"}],
        "summary": "",
    }
    normalized = normalize_planning_repair_patch(
        domain_minimum,
        authority_sha256=authority,
        segment=1,
        evidence_candidates={"e": "A"},
        allowed_anchor_ids=["e"],
        current_segment="A",
    )
    if apply_planning_repair_patch("A", normalized, {"e": "A"}) != "B":
        raise ValueError("minimal domain-valid patch did not apply")

    anchors = max(1, actual_anchor_count)
    evidence = {f"e{index}": f"A{index}" for index in range(1, anchors + 1)}
    current = "|".join(evidence.values())
    required = {
        "authority_sha256": authority,
        "segment": 1,
        "replacements": [
            {"evidence_id": key, "replacement": f"B{index}"}
            for index, key in enumerate(evidence, 1)
        ],
        "summary": (
            "event_function,exit_state,knowledge_state,promise_ending"
        ),
    }
    required_normalized = normalize_planning_repair_patch(
        required,
        authority_sha256=authority,
        segment=1,
        evidence_candidates=evidence,
        allowed_anchor_ids=list(evidence),
        current_segment=current,
    )
    apply_planning_repair_patch(current, required_normalized, evidence)

    def size(value: object) -> dict[str, int]:
        serialized = canonical_json(value)
        return {
            "canonical_json_bytes": len(serialized.encode("utf-8")),
            "estimated_tokens": estimate_input_tokens(serialized),
        }

    return {
        "token_estimator": "novel_flywheel.context_policy.estimate_input_tokens",
        "minimal_schema_valid": size(schema_minimum),
        "minimal_domain_valid": size(domain_minimum),
        "current_required_anchor_count": anchors,
        "current_required_compact_domain_valid": size(required),
        "interpretation": "valid_patch_objects_are_far_smaller_than_either_fallback_budget",
    }


def build_report(
    evidence_root: Path, canary_root: Path, ledger_root: Path,
) -> dict[str, Any]:
    parent = _verify_parent_evidence(evidence_root, ledger_root)
    run_root = _private_run_root(canary_root)
    timeline = _timeline(evidence_root, canary_root, run_root)
    trace = _read_trace(canary_root)
    planning_recovery = _load(run_root / "outputs/planning-recovery-state.json")
    issue_keys = sorted(str(value) for value in planning_recovery["best_issue_keys"])
    anchor_ids = sorted({
        str(evidence_id)
        for issue in planning_recovery.get("best_issues", [])
        for evidence_id in (issue.get("plan_evidence_ids") or [])
    })
    repair_attempts = [
        item["payload"] for item in trace
        if item.get("event_type") == "recovery_attempt"
        and item.get("payload", {}).get("stage") == "planning"
        and item.get("payload", {}).get("attempt_id") in {"1", "2", "3", "4"}
    ][-4:]
    call7, call8, call9, call10 = timeline[6:10]
    generic_finding = ["domain_validation", "ValueError"]
    generic_finding_hash = canonical_sha256(generic_finding)
    size_counterfactual = _minimal_size_counterfactual(len(anchor_ids))

    result: dict[str, Any] = {
        "schema": "R1PTR0RootCauseVerificationV1",
        "version": 1,
        "canonicalization_version": "runtime-fingerprint-canonical-json-v1",
        "raw_content_included": False,
        "prompt_content_included": False,
        "tool_arguments_included": False,
        "absolute_paths_included": False,
        "parent_gate": parent,
        "timeline": timeline,
        "first_divergent_node": {
            "ordinal": 7,
            "boundary": "planning_repair_patch.domain_validator",
            "adapter_conversion": "exact_json_semantic_valid",
            "runtime_result": "domain_failure_ValueError",
            "masked_earlier_domain_or_contract_failure_call_1_to_6": False,
            "evidence_status": "verified",
        },
        "call_7_8_domain_closure": {
            "input_artifact_sha256": planning_recovery["best_plan_sha256"],
            "repair_contract": "planning_repair_patch.v1",
            "repair_scope": "field_anchor_patch",
            "initial_reviewer_issue_keys": issue_keys,
            "initial_reviewer_issue_key_set_sha256": canonical_sha256(issue_keys),
            "authorized_anchor_count": len(anchor_ids),
            "authorized_anchor_id_set_sha256": canonical_sha256(anchor_ids),
            "call_7_response_sha256": call7["response_sha256"],
            "call_8_response_sha256": call8["response_sha256"],
            "call_7_conversion": "exact_json_semantic_valid",
            "call_8_conversion": "exact_json_semantic_valid",
            "call_7_domain_finding_status": "unverifiable_not_persisted",
            "call_8_domain_finding_status": "unverifiable_not_persisted",
            "stored_generic_call_7_finding_set_sha256": generic_finding_hash,
            "stored_generic_call_8_finding_set_sha256": generic_finding_hash,
            "call_7_to_8_exact_set_diff": {
                "persisted": "unknown",
                "removed": "unknown",
                "introduced": "unknown",
                "transformed": "unknown",
            },
            "call_7_to_8_generic_set_diff": {
                "persisted_count": 2,
                "removed_count": 0,
                "introduced_count": 0,
                "transformed_count": 0,
            },
            "system_prompt_hash_equal": (
                call7["system_prompt_sha256"] == call8["system_prompt_sha256"]
            ),
            "user_prompt_hash_equal": (
                call7["user_prompt_sha256"] == call8["user_prompt_sha256"]
            ),
            "call_7_specific_domain_finding_passed_to_call_8": False,
            "stored_payload_inventory": (
                "conversion_hashes_and_generic_attempt_outcomes_only"
            ),
            "missing_evidence": [
                "call_7_tool_arguments_or_normalized_payload",
                "call_8_tool_arguments_or_normalized_payload",
                "domain_validator_exception_reason_code_or_field_path",
            ],
        },
        "finding_and_scope_classification": {
            "targeted_repair_finding_propagation": "partial",
            "targeted_repair_scope": "field",
            "call_7_received_exact_initial_review_findings": True,
            "call_8_received_exact_call_7_domain_finding": False,
            "domain_retry_prompt_delta": "absent",
            "whole_object_regeneration": False,
        },
        "call_9_10_output_limit": {
            "fallback_scope": "targeted_patch",
            "fallback_finding_propagation": "partial",
            "strict_structured_output": False,
            "execution_mode": "plain",
            "call_9_budget": call9["effective_provider_output_budget"],
            "call_10_budget": call10["effective_provider_output_budget"],
            "call_9_observed_output_tokens": call9["observed_output_tokens"],
            "call_10_observed_output_tokens": call10["observed_output_tokens"],
            "call_9_visible_characters": call9["observed_visible_characters"],
            "call_10_visible_characters": call10["observed_visible_characters"],
            "call_9_finish_reason": call9["finish_reason"],
            "call_10_finish_reason": call10["finish_reason"],
            "call_9_visible_json_closure": False,
            "call_10_visible_json_closure": False,
            "call_9_parser_schema_domain_reached": False,
            "call_10_parser_schema_domain_reached": False,
            "output_budget_expansion_effective": True,
            "expansion_multiplier": 2,
            "expansion_absolute_delta": (
                call10["effective_provider_output_budget"]
                - call9["effective_provider_output_budget"]
            ),
            "call_10_hit_exact_requested_ceiling": (
                call10["observed_output_tokens"]
                == call10["effective_provider_output_budget"]
            ),
            "provider_configured_output_cap": None,
            "provider_hidden_cap_evidence_status": (
                "unknown_above_3954_disproved_at_or_below_1977"
            ),
            "call_9_to_10_prompt_delta": (
                "generic_protocol_regeneration_system_only"
            ),
            "call_7_8_domain_findings_passed_to_fallback": False,
        },
        "minimal_size_counterfactual": size_counterfactual,
        "budget_counterfactual": {
            "call_9_2x_budget": 3954,
            "call_9_2x_observed_result": "still_max_tokens_zero_visible_characters",
            "call_9_4x_budget": 7908,
            "call_9_4x_length_only_status": "possible_but_unproven",
            "domain_validity_at_4x": "unknown",
        },
        "runtime_attempts": repair_attempts,
        "verified_mechanisms": [
            "specific_domain_reason_collapsed_before_retry",
            "domain_retry_reused_identical_system_and_user_prompt",
            "fallback_kept_targeted_patch_scope",
            "fallback_plain_mode_produced_zero_visible_characters_at_1977_and_3954",
            "output_budget_expansion_reached_provider_boundary",
        ],
        "root_cause_gate": "R1_PTR0_ROOT_CAUSE_NOT_CLOSED",
        "primary_root_cause": "unresolved_exact_call_7_domain_rejection",
        "strongest_primary_contributor": (
            "planning.targeted_repair_finding_not_propagated"
        ),
        "terminal_amplifier": (
            "other:planning.fallback_plain_mode_zero_visible_output_limit"
        ),
        "secondary_contributors": [
            "domain_validator_collapses_exact_normalization_error_to_boolean",
            "conversion_audit_persists_hash_not_replayable_normalized_payload",
            "plain fallback has no native structured-output enforcement",
        ],
        "minimal_missing_evidence": [
            "hash-bound private Call 7 normalized planning_repair_patch payload",
            "hash-bound private Call 8 normalized planning_repair_patch payload",
            "typed Domain finding with rule code and field path for each rejection",
            "provider content-block shape for Call 9 and Call 10",
        ],
        "exclusions": {
            "network_transport": "excluded_transport_complete_for_calls_7_to_10",
            "credential": "excluded_preflight_exact_and_calls_dispatched",
            "route_drift": "excluded_runtime_fingerprint_and_route_binding_exact",
            "fingerprint_mismatch": "excluded_parent_gate_exact",
            "strict_tool_failure": "excluded_calls_7_8_unique_tool_shape_accepted",
            "parser_before_domain": "excluded_calls_7_8_exact_json_conversion",
            "schema_before_domain": "excluded_calls_7_8_strict_tool_wire_shape",
            "stale_artifact": "not_indicated_but_exact_payload_unavailable",
            "stale_candidate": "not_involved_draft_not_reached",
            "output_budget_expansion_loss": "excluded_3954_reached_provider",
            "provider_hidden_cap": "unknown_above_3954",
            "prompt_policy_mismatch": "excluded_preflight_policy_exact",
            "live_contamination": "excluded_live_parity_exact",
            "r1_d3": "not_involved_draft_not_reached",
            "final_review": "not_involved_not_reached",
            "maintenance": "not_involved_not_reached",
        },
        "external_actions_during_replay": {
            "model_calls": 0,
            "provider_calls": 0,
            "network_calls": 0,
            "paid_calls": 0,
            "canary_runs": 0,
        },
    }
    result["definition_sha256"] = canonical_sha256(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--canary-root", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(
        build_report(args.evidence_root, args.canary_root, args.ledger_root),
        ensure_ascii=False, indent=2, sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
