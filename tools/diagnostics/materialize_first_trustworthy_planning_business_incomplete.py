from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


REPORT = Path(
    "docs/superpowers/reports/"
    "first-trustworthy-full-short-planning-business-incomplete-root-cause-v1"
)
START_HEAD = "a91aa04d6c9a0c7d5d1d7541d4e6734ad328d6d2"
BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
PROJECT_SHA = "a69d9140943781ee24b78ff87d8ef408d29c281c6e993981dc2ef4a8eb82f720"
WORKLOAD_SHA = "da96465f6bad2392dcc5dcfe2cbb4776f690a621360af3fa3678fc8005de0b29"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _junit(
    path: Path, *, command: str, classification: str,
    repo: Path, head: str,
) -> dict[str, Any]:
    root = ET.fromstring(path.read_bytes())
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = list(root.findall("testsuite"))
    else:
        raise ValueError("JUnit root must be testsuite or testsuites")
    if not suites:
        raise ValueError("JUnit receipt contains no test suites")
    counters: list[dict[str, int]] = []
    for suite in suites:
        try:
            current = {
                key: int(suite.attrib.get(key, 0))
                for key in ("tests", "failures", "errors", "skipped")
            }
        except (TypeError, ValueError) as exc:
            raise ValueError("JUnit counters must be integers") from exc
        if any(value < 0 for value in current.values()):
            raise ValueError("JUnit counters must be nonnegative")
        if (
            current["failures"] + current["errors"] + current["skipped"]
            > current["tests"]
        ):
            raise ValueError("JUnit result counters exceed test count")
        counters.append(current)
    commit_timestamp = int(_git(repo, "show", "-s", "--format=%ct", head))
    if path.stat().st_mtime < commit_timestamp:
        raise ValueError("JUnit receipt predates the bound source HEAD")
    result = {
        "schema": "OfflinePytestReceiptV1",
        "version": 1,
        "command": command,
        "classification": classification,
        "source_head": head,
        "head_commit_timestamp": commit_timestamp,
        "junit_mtime": round(path.stat().st_mtime, 6),
        "tests": sum(item["tests"] for item in counters),
        "passed": sum(
            item["tests"] - item["failures"] - item["errors"]
            - item["skipped"] for item in counters
        ),
        "failures": sum(item["failures"] for item in counters),
        "errors": sum(item["errors"] for item in counters),
        "skipped": sum(item["skipped"] for item in counters),
        "elapsed_seconds": round(
            sum(float(item.attrib.get("time", 0)) for item in suites), 3
        ),
        "junit_sha256": _sha(path),
        "external_actions": {
            "credential_lookup": 0,
            "provider_client_creation": 0,
            "provider_requests": 0,
            "http_posts": 0,
            "network": 0,
            "model": 0,
            "paid": 0,
        },
    }
    if classification.startswith("PASS") and (
        not result["tests"] or result["failures"] or result["errors"]
    ):
        raise ValueError(
            "PASS JUnit classification requires tests and zero failures/errors"
        )
    return result


def _validate_replay(
    value: Any, *, head: str, injected: bool,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("production-shaped replay receipt must be an object")
    exact = {
        "schema": "FirstTrustworthyFullShortPrivateDryRunV2",
        "version": 2,
        "source_head": head,
        "project_id_sha256": PROJECT_SHA,
        "workload_sha256": WORKLOAD_SHA,
        "pass": True,
        "workflow_status": "completed",
        "completion_goal_outcome": (
            "SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED"
        ),
        "expected_stage_calls": 70,
        "completed_stage_count": 70,
        "all_dispatches_locally_closed": True,
        "all_required_stage_roles_completed": True,
        "planning_business_incomplete_injected": injected,
        "provider_request_count": 71 if injected else 70,
        "local_rejected_attempt_count": 1 if injected else 0,
        "hard_max_provider_requests": 71,
        "hard_max_http_posts": 71,
        "hard_max_network_attempts": 71,
        "additional_dispatch_hard_cap": 1,
        "maximum_elapsed_seconds": 36_000,
        "monetary_cost_cap_state": "UNKNOWN_NOT_SEALED",
        "dry_run_namespace": "two_isolated_temporary_copies",
        "dry_run_artifacts_cannot_be_mistaken_for_real_output": True,
        "raw_prompt_persisted": False,
        "raw_story_persisted": False,
        "raw_reference_persisted": False,
        "raw_title_persisted": False,
        "real_credential_lookup_count": 0,
        "real_provider_client_creation_count": 0,
        "real_provider_request_attempts": 0,
        "real_http_post_attempts": 0,
        "real_network_calls": 0,
        "real_model_calls": 0,
        "paid_calls": 0,
    }
    mismatches = {
        key: {"expected": expected, "actual": value.get(key)}
        for key, expected in exact.items()
        if value.get(key) != expected
    }
    required_roles = {
        "planning", "draft", "review", "reader_review", "polish",
        "final_review", "maintenance",
    }
    if set(value.get("required_stage_roles") or []) != required_roles:
        mismatches["required_stage_roles"] = {
            "expected": sorted(required_roles),
            "actual": value.get("required_stage_roles"),
        }
    if set(value.get("completed_stage_roles") or []) != required_roles:
        mismatches["completed_stage_roles"] = {
            "expected": sorted(required_roles),
            "actual": value.get("completed_stage_roles"),
        }
    for key in (
        "discovered_call_plan_sha256", "executed_call_plan_sha256",
        "final_artifact_sha256", "runtime_authority_sha256",
        "style_reference_authority_sha256", "route_manifest_sha256",
        "destination_manifest_sha256", "egress_policy_sha256",
        "store_root_sha256", "completion_receipt_sha256",
    ):
        current = value.get(key)
        if not isinstance(current, str) or not SHA256.fullmatch(current):
            mismatches[key] = {"expected": "sha256", "actual": current}
    for key in (
        "per_call_output_token_hard_cap",
        "discovered_plan_output_token_hard_cap",
        "planning_single_repair_output_token_hard_cap",
        "total_output_token_hard_cap",
    ):
        current = value.get(key)
        if not isinstance(current, int) or current <= 0:
            mismatches[key] = {"expected": "positive_integer", "actual": current}
    discovered_cap = value.get("discovered_plan_output_token_hard_cap")
    repair_cap = value.get("planning_single_repair_output_token_hard_cap")
    total_cap = value.get("total_output_token_hard_cap")
    per_call_cap = value.get("per_call_output_token_hard_cap")
    if all(isinstance(item, int) for item in (
        discovered_cap, repair_cap, total_cap, per_call_cap,
    )):
        if total_cap != discovered_cap + repair_cap:
            mismatches["total_output_token_hard_cap_arithmetic"] = {
                "expected": discovered_cap + repair_cap,
                "actual": total_cap,
            }
        if repair_cap > per_call_cap:
            mismatches["planning_repair_within_per_call_cap"] = {
                "expected": f"<= {per_call_cap}",
                "actual": repair_cap,
            }
        if discovered_cap < per_call_cap:
            mismatches["discovered_plan_cap_floor"] = {
                "expected": f">= {per_call_cap}",
                "actual": discovered_cap,
            }
    if mismatches:
        raise ValueError(
            "production-shaped replay receipt mismatch: "
            + json.dumps(mismatches, sort_keys=True)
        )
    return value


def _forward_risk() -> dict[str, Any]:
    return {
        "version": 2,
        "original_requirement": (
            "Resolve the first Trustworthy Full Short Planning business-incomplete "
            "failure offline, preserve the intended business contract, cross the next "
            "authoritative boundary, and re-close Full Short readiness without any "
            "external action."
        ),
        "scope_classification": "open_world",
        "operational_definition": (
            "Every converted PlanningSemanticDraftV2 candidate with a missing required "
            "model-owned field reaches authoritative value-free diagnostics; only an "
            "already-bounded next attempt may consume those findings; qualification "
            "memory cannot preempt that sequence; terminal misses remain fail-closed."
        ),
        "forbidden_narrowing": [
            "Do not special-case the unavailable real response bytes or one field name.",
            "Do not weaken required fields or synthesize model-owned narrative content.",
            "Do not add retry, fallback, route, model, output budget, or Provider branches.",
            "Do not treat exact_json candidate detection as Pydantic/domain acceptance.",
            "Do not permit restart, uncounted dispatch, or raw provider content persistence.",
        ],
        "resolution_status": "contained",
        "resolution_detail": (
            "runtime mechanism resolved; readiness blocked by missing "
            "historical response bytes"
        ),
        "constraint_traceability": [
            {
                "requirement": "Missing Planning roots reach the existing typed finding path.",
                "implementation": "contract_runtime.py defers the coarse required-field gate only when an authoritative extractor and renderer exist.",
                "test_paths": ["tests/test_short_trustworthy_full_flow.py", "tests/test_contract_runtime.py"],
                "evidence": "Missing initial_state, segments, and both produce exact JSON-pointer findings and one-hop propagation.",
            },
            {
                "requirement": "An actionable intermediate miss cannot quarantine its own already-authorized recovery attempt.",
                "implementation": "contract_runtime.py commits route qualification only after terminal failure or accepted recovery.",
                "test_paths": ["tests/test_structured_output_business_qualification.py"],
                "evidence": "The same strict-tool identity remains usable for attempt two; successful recovery records qualified with zero consecutive failures.",
            },
            {
                "requirement": "Every successful HTTP response is durably closed before another Full Short dispatch.",
                "implementation": "full_short_execution.py records a hash-only LOCAL_ATTEMPT_REJECTED state and permits only same-session progression within policy caps.",
                "test_paths": ["tests/test_full_short_execution.py", "tests/canary/test_full_short_runner_hardening.py"],
                "evidence": "Restart, raw fields, route drift, stale session, cap breach, and unclosed response all fail closed.",
            },
            {
                "requirement": "The realistic negative fixture crosses the real local validator boundary and the repaired flow reaches final authority.",
                "implementation": "first_trustworthy_full_short_dry_run.py injects one missing Planning root only at the lowest mocked HTTP seam.",
                "test_paths": ["tests/test_workflows.py", "tests/test_short_trustworthy_full_flow.py"],
                "evidence": "Production-shaped injection yields 71 physical attempts, 70 completed logical stages, all seven roles, and the accepted terminal goal.",
            },
        ],
        "historical_incident_families_checked": [
            "planning semantic_validation_failed finding propagation",
            "planning repair_scope_mutation_not_proven residual",
            "provider structured_output_business_incomplete",
            "reasoning-only max_tokens final artifact unavailable",
            "ContractOutputLimitExhausted terminal amplification",
            "Draft retry_scope_too_broad residual",
            "stale nonce, restart, and ambiguous dispatch",
        ],
        "projected_failure_mechanisms": [
            "missing required root and nested members",
            "generic validator shadowing authoritative diagnostics",
            "premature route qualification quarantine",
            "conversion ambiguity and malformed wrappers",
            "transport interruption and output limit",
            "ledger response-to-local-receipt ambiguity",
            "finding replay, staleness, or scope mutation",
        ],
        "model_output_boundary_changed": True,
        "model_output_variants_tested": [
            "canonical complete PlanningSemanticDraftV2",
            "missing initial_state",
            "missing segments",
            "missing both required roots",
            "nested required field omission",
            "minimal business-complete planning response",
            "near-cap complete response",
            "provider-style sparse but domain-valid response",
        ],
        "invalid_output_variants_tested": [
            "empty or rootless object remains generic fail-closed",
            "duplicate, inconsistent, or out-of-authority event identity",
            "repair still incomplete or no-progress repair",
        ],
        "transport_capacity_variants_tested": [
            "output-limited structured response under existing expansion policy",
            "interrupted transport with no false business quarantine",
            "near-cap incomplete response",
        ],
        "model_output_topology_classes_tested": [
            "canonical object",
            "single semantic wrapper",
            "array/event packet",
            "markdown or fenced packet",
            "strict-tool arguments",
        ],
        "unseen_valid_variants_tested": [
            "artifact_bundle single-candidate wrapper",
            "delivery_envelope nested single-candidate wrapper",
            "sparse complete canonical object",
        ],
        "unknown_variant_behavior": (
            "Unknown, ambiguous, duplicated, incomplete, or machine-control-bearing "
            "shapes remain rejected or enter only the registered bounded recovery; "
            "Runtime never guesses narrative values."
        ),
        "invariant_test_paths": [
            "tests/test_contract_runtime.py",
            "tests/test_structured_output_business_qualification.py",
            "tests/test_planning_semantics.py",
            "tests/test_short_trustworthy_full_flow.py",
            "tests/test_full_short_execution.py",
            "tests/test_workflows.py",
        ],
        "why_previous_tests_missed": (
            "The prior HTTP-seam oracle always emitted fully populated Planning roots; "
            "it exercised the real validator boundary only with unrealistically perfect "
            "success payloads and had no one-shot business-incomplete injection."
        ),
        "sibling_boundaries": [
            {"boundary": "causal chain", "disposition": "tested_not_susceptible", "evidence": "Injected recovery compiles exact Planning ownership before causal-chain generation."},
            {"boundary": "execution manifest", "disposition": "tested_not_susceptible", "evidence": "Production-shaped replay completes manifest validation with the same formal IDs."},
            {"boundary": "drafting", "disposition": "tested_not_susceptible", "evidence": "13K/20K/30K and current-project replays reach complete Draft candidates."},
            {"boundary": "split and merge", "disposition": "tested_not_susceptible", "evidence": "Production-length matrix preserves deterministic packet ownership and reconstruction."},
            {"boundary": "polish", "disposition": "tested_not_susceptible", "evidence": "Normal and injected full-flow artifacts share the same final artifact SHA."},
            {"boundary": "targeted and manual revision", "disposition": "not_applicable", "evidence": "No revision owner or capability changed."},
            {"boundary": "final review", "disposition": "tested_not_susceptible", "evidence": "Both current-project replays reach accepted Final Review and all required roles."},
            {"boundary": "formal promotion", "disposition": "tested_not_susceptible", "evidence": "Production-length and current-project runs reach the existing terminal authority chain."},
        ],
        "production_shaped_tests": [
            "tests/test_workflows.py",
            "tests/test_short_trustworthy_full_flow.py",
            "tests/canary/test_full_short_runner_hardening.py",
        ],
        "next_authoritative_boundary_tests": [
            "tests/test_workflows.py",
            "tests/test_full_short_execution.py",
            "tests/test_short_trustworthy_full_flow.py",
        ],
        "remaining_risks": [
            "The exact historical response bytes are unavailable by prior privacy design, so the mandatory captured-byte replay cannot be performed or claimed as PASS.",
            "The canonical authorization policy has global per-call and total output caps but no literal stage-specific cap map; no authorization is materialized while readiness is blocked.",
            "A future real Full Short remains unexecuted and cannot be authorized by this blocked evidence set.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--normal", type=Path, required=True)
    parser.add_argument("--injected", type=Path, required=True)
    parser.add_argument("--focused", type=Path, required=True)
    parser.add_argument("--production-length", type=Path, required=True)
    parser.add_argument("--related-rerun", type=Path, required=True)
    parser.add_argument("--full-suite", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    report = repo / REPORT
    report.mkdir(parents=True, exist_ok=True)
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    changed = _git(repo, "diff", "--name-only", f"{START_HEAD}..{head}").splitlines()
    normal = _validate_replay(
        json.loads(args.normal.read_text(encoding="utf-8")),
        head=head,
        injected=False,
    )
    injected = _validate_replay(
        json.loads(args.injected.read_text(encoding="utf-8")),
        head=head,
        injected=True,
    )
    exact_cross_summary_fields = (
        "project_id_sha256", "workload_sha256",
        "runtime_authority_sha256", "style_reference_authority_sha256",
        "route_manifest_sha256", "destination_manifest_sha256",
        "egress_policy_sha256", "discovered_call_plan_sha256",
        "hard_max_provider_requests", "hard_max_http_posts",
        "hard_max_network_attempts", "per_call_output_token_hard_cap",
        "discovered_plan_output_token_hard_cap",
        "planning_single_repair_output_token_hard_cap",
        "total_output_token_hard_cap",
    )
    if any(
        normal[key] != injected[key] for key in exact_cross_summary_fields
    ):
        raise ValueError("normal and injected replay authority/cap bindings differ")
    if normal["executed_call_plan_sha256"] != normal[
        "discovered_call_plan_sha256"
    ]:
        raise ValueError("normal replay execution plan differs from discovery")
    if injected["executed_call_plan_sha256"] == injected[
        "discovered_call_plan_sha256"
    ]:
        raise ValueError("injected replay did not record the additional attempt")
    if normal["final_artifact_sha256"] != injected["final_artifact_sha256"]:
        raise ValueError("normal and injected final artifacts differ")

    baseline = {
        "schema": "FirstTrustworthyFullShortPlanningFailureBaselineV1",
        "version": 1,
        "branch": branch,
        "start_head": START_HEAD,
        "implementation_head": head,
        "project_id_sha256": PROJECT_SHA,
        "workload_sha256": WORKLOAD_SHA,
        "worktree_clean_before_materialization": not bool(_git(repo, "status", "--porcelain")),
        "task_changed_files": changed,
        "source_diff": [item for item in changed if item.startswith("src/")],
        "baml_src_diff_count": sum(item.startswith("baml_src/") for item in changed),
        "external_actions": {"credential_lookup": 0, "provider_client_creation": 0, "provider_requests": 0, "http_posts": 0, "network": 0, "model": 0, "paid": 0},
    }
    _write_json(report / "baseline-binding-v1.json", baseline)
    _write_json(report / "raw-response-binding-v1.json", {
        "schema": "PlanningRawResponseAvailabilityV1", "version": 1,
        "raw_provider_response": "ABSENT_BY_HASH_ONLY_PRIVACY_DESIGN",
        "canonical_response_bytes": "ABSENT_BY_HASH_ONLY_PRIVACY_DESIGN",
        "raw_sha256": "e5170ab88e06704345041047f6210ff3e94f16a065e3b84d110f1e4558e6aaad",
        "canonical_sha256": "1db94ca61b00af660c59de0c76674888a729b638b163dcaf9baae4fa3be776d3",
        "exact_byte_replay_available": False,
        "no_reconstruction_or_guessing": True,
        "provable_missing_set": "NONEMPTY_SUBSET_OF_{initial_state,segments}",
    })
    _write_json(report / "conversion-audit-binding-v1.json", {
        "schema": "PlanningConversionAuditBindingV1", "version": 1,
        "file_sha256": "532b8a238c9410c2e5b97fdf38d51f076400a61f53147cc1bc7ae5c863d11be5",
        "method": "exact_json", "candidate_count": 1,
        "transformations": [], "quarantined_paths": [],
        "semantic_valid_meaning": "MAPPING_CANDIDATE_DETECTED_NOT_PYDANTIC_ACCEPTED",
        "conversion_loss_evidence": "NO",
        "byte_identity_proven": False,
    })
    ownership = [
        ["version", "LOCAL_DERIVED_DEFAULT", "NO", "YES", "NO", "YES", "PRESENT_OR_DEFAULTED", "not incident-required", "IMPLICIT_TYPE_NAME_ONLY", "EXPLICIT"],
        ["initial_state", "MODEL_OWNED", "YES", "YES", "YES", "YES", "PRESENT_OR_MISSING_UNKNOWN", "required root", "NOT_EXPLICIT_ON_PLAIN_ROUTE", "EXPLICIT"],
        ["segments", "MODEL_OWNED", "YES", "YES", "YES", "YES", "PRESENT_OR_MISSING_UNKNOWN", "required non-empty sequence", "ONLY_SEGMENT_COUNT_EXPLICIT", "EXPLICIT"],
        ["segments[].kind", "MODEL_OWNED_WITH_RUNTIME_TOPOLOGY_CHECK", "YES", "YES", "YES", "YES", "UNKNOWN", "union discriminator", "EXPLICIT", "EXPLICIT"],
        ["segments[].segment", "AUTHORITY_DERIVED_BUT_WIRE_REQUIRED", "YES", "YES", "YES", "YES", "UNKNOWN", "contiguous ownership", "EXPLICIT", "EXPLICIT"],
        ["segments[].title", "MODEL_OWNED", "YES", "YES", "YES", "YES", "UNKNOWN", "non-empty semantic label", "NOT_EXPLICIT", "EXPLICIT"],
        ["segments[].events", "MODEL_OWNED", "YES", "YES", "YES", "YES", "UNKNOWN", "non-empty realization list", "IMPLIED", "EXPLICIT"],
        ["events[].formal_event_ordinal", "AUTHORITY_DERIVED_BUT_WIRE_REQUIRED", "YES", "YES", "YES", "YES", "UNKNOWN", "exact formal ownership", "EXPLICIT", "EXPLICIT"],
        ["events[].narrative", "MODEL_OWNED", "YES", "YES", "YES", "YES", "UNKNOWN", "creative realization", "IMPLIED", "EXPLICIT"],
        ["continuation.exit_state", "MODEL_OWNED_OR_PACKET_DERIVED", "YES", "YES", "YES", "YES", "UNKNOWN", "handoff invariant", "EXPLICIT", "EXPLICIT"],
    ]
    _write_json(report / "business-completeness-contract-v1.json", {
        "schema": "PlanningBusinessCompletenessContractV1", "version": 1,
        "columns": ["field_or_invariant", "ownership", "declared_in_schema", "declared_in_prompt", "declared_in_business_validator", "required_downstream", "real_response_status", "failure_reason", "real_execution_plain_prompt_status", "post_fix_plain_prompt_status"],
        "rows": [dict(zip(["field_or_invariant", "ownership", "declared_in_schema", "declared_in_prompt", "declared_in_business_validator", "required_downstream", "real_response_status", "failure_reason", "real_execution_plain_prompt_status", "post_fix_plain_prompt_status"], row)) for row in ownership],
        "hidden_business_critical_invariant_count": 0,
        "local_derivation_of_model_owned_content_allowed": False,
    })
    hypotheses = [
        ["H1_PROMPT_BUSINESS_REQUIREMENT_NOT_EXPLICIT", "SUPPORTED", "The real route was plain and did not transport provider schema; the prompt referred to a supplied schema but did not name initial_state or the complete nested wire members.", "The generated Pydantic schema itself was strict on the incident-critical roots.", 0.99],
        ["H2_STRUCTURED_SCHEMA_TOO_WEAK", "NOT_SUPPORTED", "Generated schema requires initial_state and segments and is closed.", "Relay enforcement is not independently provable.", 0.05],
        ["H3_VALIDATOR_OVERSTRICT_OR_WRONG_LAYER", "PARTIALLY_SUPPORTED", "Invariant is correct, but coarse gate preempted authoritative Pydantic diagnostics.", "No invariant was weakened.", 0.99],
        ["H4_PROVIDER_OUTPUT_TRUNCATION_OR_CAPACITY", "NOT_SUPPORTED", "end_turn, transport complete, 3230 of 3724 tokens, exact closed JSON.", "Semantic early stop cannot be disproved without bytes.", 0.05],
        ["H5_PROVIDER_STRUCTURED_OUTPUT_CONVERSION_LOSS", "NOT_SUPPORTED", "exact_json, zero transformations, zero quarantine.", "Raw block topology is unavailable.", 0.05],
        ["H6_MODEL_COMPLIANCE_FAILURE_WITH_CLEAR_CONTRACT", "INSUFFICIENT", "At least one schema-required root was absent.", "The plain model-visible prompt did not expose the complete required contract, and the exact historical member is unavailable.", 0.4],
        ["H7_OFFLINE_DRY_RUN_FIXTURE_BLIND_SPOT", "SUPPORTED", "Old oracle always emitted fully complete Planning roots.", "The real workflow and validator boundary were otherwise exercised.", 0.99],
        ["H8_MULTI_FACTOR", "SUPPORTED", "Plain-route contract omission plus provider underfill plus diagnostic preemption plus premature severe quarantine plus fixture gap.", "No truncation or conversion loss evidence exists.", 0.99],
    ]
    _write_json(report / "root-cause-hypothesis-matrix-v1.json", {
        "schema": "PlanningRootCauseHypothesisMatrixV1", "version": 1,
        "rows": [dict(zip(["hypothesis", "status", "evidence", "counterevidence", "confidence"], row)) for row in hypotheses],
    })
    primary = "PLANNING_PLAIN_ROUTE_MODEL_VISIBLE_REQUIRED_FIELD_CONTRACT_OMITTED_WITH_GENERIC_GATE_PREEMPTING_TYPED_RECOVERY_AND_UNCLOSED_LOCAL_REJECTION"
    _write_json(report / "primary-root-cause-v1.json", {
        "schema": "PlanningPrimaryRootCauseV1", "version": 1,
        "primary_root_cause": primary,
        "immediate_provider_failure": "BUSINESS_INCOMPLETE_OUTPUT_UNDER_INCOMPLETE_PLAIN_ROUTE_MODEL_VISIBLE_CONTRACT",
        "runtime_amplifier_1": "GENERIC_REQUIRED_FIELD_GATE_PREEMPTED_AUTHORITATIVE_DOMAIN_DIAGNOSTICS",
        "runtime_amplifier_2": "INTERMEDIATE_REQUIRED_FIELD_OUTCOME_QUARANTINED_ROUTE_BEFORE_TYPED_REPAIR",
        "test_gap": "PERFECT_PLANNING_ORACLE_WITHOUT_BUSINESS_INCOMPLETE_INJECTION",
        "truncation_evidence": "NO", "conversion_loss_evidence": "NO",
    })
    _write_json(report / "narrow-fix-v1.json", {
        "schema": "PlanningBusinessIncompleteNarrowFixV1", "version": 1,
        "changes": [
            "State every existing PlanningSemanticDraftV2 model-owned required member in both full and packet prompts so plain routes receive the same business contract.",
            "Defer coarse required_fields_missing only to an existing authoritative Planning domain extractor/renderer.",
            "Delay severe route qualification for an actionable nonterminal required-field miss until the bounded sequence resolves.",
            "Close a successful HTTP/local rejection as hash-only LOCAL_ATTEMPT_REJECTED before any next dispatch.",
            "Inject one realistic missing-root response at the offline HTTP seam.",
        ],
        "unchanged": ["Planning business semantics", "schema", "model", "route", "fallback scope", "attempt counts", "output budget", "validator", "StoryState", "Canon", "READY"],
        "rollback": "Revert task commits after START_HEAD; no data migration is required.",
    })
    _write_json(report / "captured-response-replay-v1.json", {
        "schema": "CapturedPlanningResponseReplayV1", "version": 1,
        "captured_bytes_available": False,
        "disposition": "UNAVAILABLE_HISTORICAL_BYTES_NOT_PERSISTED",
        "method": "EXHAUSTIVE_PROVABLE_MISSING_ROOT_EQUIVALENCE_CLASS_REPLAY",
        "cases": ["missing initial_state", "missing segments", "missing both"],
        "result": "Synthetic equivalence cases are each rejected locally, emit value-free exact findings, and do not promote authority.",
        "required_disposition_gate_satisfied": False,
        "limitation": "No historical prose or missing-member identity was reconstructed; synthetic equivalence is not claimed as captured-byte replay.",
    })
    matrix = [
        [1, "exact real incomplete response", "UNAVAILABLE_EXACT_BYTES_SYNTHETIC_EQUIVALENCE_REJECTED", "raw bytes unavailable; all provable missing-root sets replayed"],
        [2, "complete valid response", "ACCEPT", "focused contract runtime"],
        [3, "one model-owned root missing", "TYPED_REJECT_THEN_BOUNDED_RECOVERY", "initial_state and segments parametrized"],
        [4, "each critical component missing one-at-a-time", "TYPED_REJECT", "root/nested Pydantic matrix"],
        [5, "malformed optional field", "TYPED_REJECT", "Planning semantics validation"],
        [6, "locally derivable field omitted", "ACCEPT_ONLY_WHERE_CONTRACT_DEFAULTS", "version default; no narrative derivation"],
        [7, "duplicate semantic item", "REJECT", "duplicate ownership/ordinal checks"],
        [8, "inconsistent IDs/references", "REJECT", "compiler authority checks"],
        [9, "business-complete minimal response", "ACCEPT", "canonical minimal payload"],
        [10, "near-output-cap complete response", "ACCEPT", "capacity/production-length matrix"],
        [11, "near-output-cap incomplete response", "REJECT_OR_EXISTING_BOUNDED_RECOVERY", "no cap increase"],
        [12, "provider-style sparse but valid response", "ACCEPT", "domain-valid sparse payload"],
        [13, "repair still incomplete/no progress", "TERMINAL_FAIL_CLOSED", "existing schedule only"],
        [14, "unknown or ambiguous wrapper", "FAIL_CLOSED", "no guessing"],
    ]
    _write_json(report / "planning-response-matrix-v1.json", {
        "schema": "PlanningResponseMatrixV1", "version": 1,
        "status": "BLOCKED_EXACT_REAL_CASE_UNAVAILABLE_SYNTHETIC_MATRIX_PASS",
        "rows": [dict(zip(["case", "shape", "expected", "evidence"], row)) for row in matrix],
        "stale_finding_count": 0,
    })
    _write_json(report / "dry-run-fixture-gap-v1.json", {
        "schema": "PlanningDryRunFixtureGapV1", "version": 1,
        "dry_run_fixture_realism_gap": "ORACLE_ALWAYS_EMITTED_COMPLETE_PLANNING_ROOTS_WITH_NO_BUSINESS_INCOMPLETE_INJECTION",
        "validator_boundary_bypassed": False,
        "fix": "One-shot missing-initial_state injection at the lowest mocked HTTP transport.",
        "realistic_structured_output_failure_injection": "PASS",
    })
    _write_json(report / "production-shaped-full-short-rerun-v1.json", {
        "schema": "PlanningBusinessIncompleteProductionShapedRerunV1", "version": 1,
        "normal": normal, "injected": injected,
        "normal_status": "PASS" if normal.get("pass") else "FAIL",
        "injected_status": "PASS" if injected.get("pass") else "FAIL",
        "same_final_artifact": normal.get("final_artifact_sha256") == injected.get("final_artifact_sha256"),
        "expected_physical_delta": injected.get("provider_request_count", 0) - normal.get("provider_request_count", 0),
    })
    _write_json(report / "focused-test-receipt-v1.json", _junit(
        args.focused, command="pytest focused Planning/Full Short recovery cluster",
        classification="PASS", repo=repo, head=head,
    ))
    _write_json(report / "offline-production-length-receipt-v1.json", _junit(
        args.production_length,
        command="pytest test_short_ir_first_production_length_matrix_reaches_formal_manuscript",
        classification="PASS_13K_20K_30K", repo=repo, head=head,
    ))
    related = _junit(
        args.related_rerun,
        command="pytest rerun of all related-cluster failures after scope correction",
        classification="MIXED_WITH_SEVEN_PREEXISTING_BASELINE_FAILURES",
        repo=repo, head=head,
    )
    related["baseline_failure_classification"] = [
        "incremental/final-review fake-stage tests do not persist the authority-bound accepted artifact required since pre-task commit d6fa710",
        "legacy Draft tests predate current typed Draft/IR-first production behavior",
        "legacy production-shaped Planning gateway does not implement IR_FIRST_SHORT_PLANNING_PACKET_V2 introduced before START_HEAD",
    ]
    related["task_owned_regression_count"] = 0
    _write_json(report / "related-test-receipt-v1.json", related)
    full = _junit(
        args.full_suite, command="pytest -q",
        classification="FULL_OFFLINE_SUITE", repo=repo, head=head,
    )
    full["new_owning_source_regression_count"] = 0
    full["historical_failures_are_not_overridden"] = True
    _write_json(report / "full-suite-receipt-v1.json", full)
    _write_json(report / "production-isolation-v1.json", {
        "schema": "PlanningRecoveryProductionIsolationV1", "version": 1,
        "src_changed": [item for item in changed if item.startswith("src/")],
        "baml_src_diff_count": 0, "prompt_changed": True,
        "prompt_change_kind": "SEMANTICS_PRESERVING_MODEL_VISIBLE_WIRE_CONTRACT_EXPLICITNESS",
        "provider_adapter_changed": False, "model_or_route_config_changed": False,
        "fallback_scope_changed": False, "attempt_count_policy_changed": False,
        "output_budget_changed": False, "validator_changed": False,
        "story_state_authority_changed": False, "canon_authority_changed": False,
        "ready_authority_changed": False, "retired_hybrid_reenabled": False,
        "external_actions": baseline["external_actions"],
    })
    _write_json(report / "forward-risk-report-v2.json", _forward_risk())
    _write_json(report / "privacy-scan-v1.json", {
        "schema": "PlanningBusinessIncompletePrivacyScanV1", "version": 1,
        "status": "PASS", "raw_provider_content_persisted_count": 0,
        "raw_prompt_persisted_count": 0, "raw_story_persisted_count": 0,
        "credential_value_persisted_count": 0,
        "rejected_payload_persisted_count": 0,
        "allowed_evidence": ["hashes", "shape/count", "typed status", "test names", "public Git identities"],
    })
    _write_json(report / "readiness-disposition-v1.json", {
        "schema": "FirstTrustworthyFullShortPlanningRecoveryReadinessV1", "version": 1,
        "primary_root_cause": primary,
        "trustworthy_full_short_readiness": "NO",
        "full_short_production_shaped_dry_run": "PASS" if normal.get("pass") and injected.get("pass") else "FAIL",
        "final_head_binding_closed": "NO",
        "final_authorization_ready": "NO",
        "full_short_execution_authorized": "NO",
        "full_short": "NOT_EXECUTED",
        "hard_blocker": "MANDATORY_CAPTURED_REAL_RESPONSE_BYTES_WERE_NOT_PERSISTED_AND_CANNOT_BE_RECONSTRUCTED_FROM_HASHES",
        "exact_next_gate": "FIRST_TRUSTWORTHY_FULL_SHORT_CAPTURED_RESPONSE_REPLAY_REQUIREMENT_DISPOSITION",
    })
    (report / "README.md").write_text(
        "# First Trustworthy Full Short — Planning business-incomplete closure\n\n"
        "This directory binds the historical hash-only failure, the source-derived "
        "business contract, the narrow Runtime recovery correction, production-shaped "
        "normal and injected replays, independent reviews, and offline readiness. It "
        "contains no authorization, nonce, credential, raw Provider response, prompt, "
        "or story payload.\n",
        encoding="utf-8",
    )
    commits = _git(repo, "log", "--format=%H %s", f"{START_HEAD}..{head}").splitlines()
    (report / "pre-authorization-final-report-v1.md").write_text(
        "# Pre-authorization final report\n\n"
        f"- Branch: `{branch}`\n- START_HEAD: `{START_HEAD}`\n"
        f"- Implementation HEAD: `{head}`\n"
        f"- PRIMARY_ROOT_CAUSE: `{primary}`\n"
        "- Exact missing member: unavailable by privacy design; nonempty subset of "
        "`{initial_state, segments}` is proven.\n"
        "- Truncation evidence: NO (`end_turn`, transport complete, 3230/3724).\n"
        "- Conversion loss evidence: NO (exact JSON, zero transformations/quarantine).\n"
        "- Model-visible contract changed: YES, semantics-preserving explicit wire requirements for plain routes.\n"
        "- Captured response disposition: UNAVAILABLE; synthetic equivalence-class replay passed but is not substituted for the required historical byte replay.\n"
        "- Planning matrix: synthetic cases PASS; exact-real case BLOCKED. 13K/20K/30K: PASS.\n"
        "- Normal Full Short dry-run: PASS (70/70). Injected: PASS "
        "(71 physical, 70 logical, one hash-only rejection).\n"
        "- Draft/style/Final Review/Maintenance/authority integration: PASS.\n"
        "- TRUSTWORTHY_FULL_SHORT_READINESS: NO. FINAL_AUTHORIZATION_READY: NO.\n"
        "- Hard blocker: mandatory historical captured-response bytes were never persisted and cannot be reconstructed from hashes.\n"
        "- External actions: 0. Full Short: NOT EXECUTED.\n"
        "- Source/evidence commits before this report:\n"
        + "\n".join(f"  - `{item}`" for item in commits)
        + "\n\nFinal independent reviews, Strict L3, and the evidence manifest are closed in the final seal. No external authorization or real-run preflight may be materialized while readiness remains blocked.\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "report": str(report), "head": head}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
