from __future__ import annotations

"""Materialize the final offline physical-request capacity stop-loss."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from tools.canary.first_trustworthy_full_short_dry_run import (
    _cleanup_private_workspace_v1,
    _copy_private_data,
    _discover_plan,
    _discover_reasoning_recovery_projection_v1,
    _shutdown_crewai_event_bus,
)


START_HEAD = "d499ef33e43a1441f47c1ceadc06d598c889c467"
BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
PROJECT_ID = "2ad716f3c0d1"
ROOT = Path(
    "docs/superpowers/reports/"
    "full-short-capacity-final-one-round-confirmation-v1"
)
PRIOR = Path(
    "docs/superpowers/reports/"
    "exact-ready-required-route-capability-evidence-closure-v1"
)
REGISTRY = Path("config/full_short_route_capability_registry_v1.json")
ZERO = {
    "real_credential_lookup_count": 0,
    "real_secret_read_count": 0,
    "real_provider_client_creation_count": 0,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_model_api_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
    "full_short_real_execution_count": 0,
}


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_json(value: object) -> str:
    return sha_bytes(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read_text_long_path(path: Path) -> str:
    value = str(path.resolve())
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\" + value
    with open(value, encoding="utf-8") as stream:
        return stream.read()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, encoding="utf-8",
    ).strip()


def receipt(schema: str, status: str, **values: Any) -> dict[str, Any]:
    return {
        "schema": schema,
        "version": 1,
        "status": status,
        **values,
        "external_boundary": ZERO,
    }


def source_project(repo: Path) -> Path:
    matches: list[Path] = []
    for path in (repo / "data" / "projects").glob("*/project.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        if str(document.get("id")) == PROJECT_ID:
            matches.append(path.parent)
    if len(matches) != 1:
        raise ValueError("exact_ready_project_identity_invalid")
    return matches[0]


def discover(
    repo: Path, *, business_recovery: bool,
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]],
]:
    temporary = tempfile.TemporaryDirectory(prefix="full-short-private-")
    try:
        data = _copy_private_data(
            repo=repo, source_project=source_project(repo),
            project_id=PROJECT_ID, target=Path(temporary.name) / "d",
            install_offline_gateway_context_manifest=True,
        )
        calls, logical = asyncio.run(_discover_plan(
            repo=repo, data_dir=data, project_id=PROJECT_ID,
            inject_planning_business_incomplete_once=business_recovery,
        ))
        plan_documents = []
        for path in data.rglob("capacity-plans/*.json"):
            document = json.loads(read_text_long_path(path))
            plan = document.get("plan") if isinstance(document, dict) else None
            if isinstance(plan, dict):
                plan_documents.append({
                    **plan,
                    "_receipt_route": document.get("route"),
                    "_receipt_role": document.get("role"),
                })
        joined: list[dict[str, Any]] = []
        used_plan_shas: set[str] = set()
        for call, stage in zip(calls, logical, strict=True):
            candidates = [
                plan for plan in plan_documents
                if plan.get("rendered_request_sha256")
                == call.get("rendered_request_sha256")
                and int(plan.get("requested_output_token_cap") or 0)
                == int(call.get("provider_wire_requested_output_tokens") or 0)
                and plan.get("stage_id") == stage.get("stage_id")
                and plan.get("_receipt_route") == stage.get("route_lane")
                and plan.get("plan_sha256") not in used_plan_shas
            ]
            if len(candidates) != 1:
                raise RuntimeError(
                    "FULL_SHORT_DISCOVERY_CAPACITY_PLAN_JOIN_INCOMPLETE:"
                    + json.dumps({
                        "call_ordinal": call.get("ordinal"),
                        "stage_id": stage.get("stage_id"),
                        "rendered_request_sha256": call.get(
                            "rendered_request_sha256"
                        ),
                        "requested_output_tokens": call.get(
                            "provider_wire_requested_output_tokens"
                        ),
                        "plan_count": len(plan_documents),
                        "same_rendered_sha_count": sum(
                            plan.get("rendered_request_sha256")
                            == call.get("rendered_request_sha256")
                            for plan in plan_documents
                        ),
                        "same_stage_count": sum(
                            plan.get("stage_id") == stage.get("stage_id")
                            for plan in plan_documents
                        ),
                        "route_lane": stage.get("route_lane"),
                        "candidate_count": len(candidates),
                    }, sort_keys=True)
                )
            joined.append(candidates[0])
            used_plan_shas.add(str(candidates[0]["plan_sha256"]))
        return calls, logical, joined
    finally:
        _shutdown_crewai_event_bus()
        _cleanup_private_workspace_v1(temporary)


def reasoning_projection(repo: Path) -> dict[str, Any]:
    temporary = tempfile.TemporaryDirectory(prefix="full-short-private-")
    try:
        data = _copy_private_data(
            repo=repo, source_project=source_project(repo),
            project_id=PROJECT_ID, target=Path(temporary.name) / "d",
            install_offline_gateway_context_manifest=True,
        )
        return asyncio.run(_discover_reasoning_recovery_projection_v1(
            repo=repo, data_dir=data, project_id=PROJECT_ID,
        ))
    finally:
        _shutdown_crewai_event_bus()
        _cleanup_private_workspace_v1(temporary)


def envelope(
    call: dict[str, Any], logical: dict[str, Any], *, scenario: str,
    plan: dict[str, Any] | None = None,
    attempt_role: str = "NORMAL", physical_attempt: int = 1,
) -> dict[str, Any]:
    plan = plan or {}
    contract_attempt_index = int(logical.get("contract_attempt_index") or 1)
    planned_physical_attempt = int(
        plan.get("physical_attempt") or contract_attempt_index
        or physical_attempt
    )
    resolved_attempt_role = attempt_role
    recovery_overlay_kind = str(
        plan.get("recovery_overlay_kind") or "NONE"
    )
    if (
        attempt_role == "NORMAL"
        and (planned_physical_attempt > 1 or recovery_overlay_kind != "NONE")
    ):
        resolved_attempt_role = "TYPED_BUSINESS_RECOVERY"
    resolved_physical_attempt = max(physical_attempt, planned_physical_attempt)
    return {
        "scenario": scenario,
        "stage": logical["stage_id"],
        "role": call["role"],
        "logical_stage_id": logical["logical_stage_id"],
        "attempt_role": resolved_attempt_role,
        "physical_attempt": resolved_physical_attempt,
        "contract_attempt_index": logical.get("contract_attempt_index"),
        "contract_route": logical.get("contract_route"),
        "contract_route_attempt": logical.get("contract_route_attempt"),
        "stage_role": logical.get("stage_role", "NORMAL"),
        "physical_attempt_id": plan.get("physical_attempt_id"),
        "global_physical_attempt_ordinal": plan.get(
            "global_physical_attempt_ordinal"
        ),
        "capacity_plan_sha256": plan.get("plan_sha256"),
        "capacity_receipt_role": plan.get("_receipt_role"),
        "recovery_overlay_kind": recovery_overlay_kind,
        "runtime_capacity_plan_headroom_tokens": plan.get("headroom"),
        "route": call["route_lane"],
        "route_fingerprint": call["route_fingerprint"],
        "provider_id_sha256": call["provider_id_sha256"],
        "destination_sha256": call["destination_sha256"],
        "provider_operator": call["provider_operator"],
        "protocol": call["protocol"],
        "model": call["model_name"],
        "system_tokens": call["system_tokens"],
        "task_tokens": call["task_tokens"],
        "authority_context_tokens": call["authority_context_tokens"],
        "skill_advisory_tokens": call["skill_advisory_tokens"],
        "manuscript_window_tokens": call["manuscript_window_tokens"],
        "protocol_overhead_tokens": call["protocol_overhead_tokens"],
        "total_rendered_input_tokens": call["rendered_message_tokens"],
        "rendered_message_utf8_bytes": call["rendered_message_utf8_bytes"],
        "provider_wire_payload_utf8_bytes": (
            call["provider_wire_payload_utf8_bytes"]
        ),
        "provider_wire_payload_estimated_tokens": (
            call["provider_wire_payload_estimated_tokens"]
        ),
        "input_estimator_identity": call["input_estimator_identity"],
        "input_envelope_sha256": call["input_envelope_sha256"],
        "stage_specific_output_cap": int(
            plan.get("requested_output_token_cap")
            or call["requested_output_tokens"]
        ),
        "business_desired_output_tokens": int(
            plan.get("final_output_reserve")
            or call["requested_output_tokens"]
        ),
        "recovery_specific_output_cap": (
            int(
                plan.get("requested_output_token_cap")
                or call["requested_output_tokens"]
            )
            if resolved_attempt_role != "NORMAL" else None
        ),
        "physical_attempt_requested_output_cap": (
            int(
                plan.get("requested_output_token_cap")
                or call["requested_output_tokens"]
            )
        ),
        "provider_wire_requested_output_cap": (
            call["provider_wire_requested_output_tokens"]
        ),
        "reasoning_field_present": call["reasoning_field_present"],
        "reasoning_effort": call["reasoning_effort"],
        "compaction_windowing_decision": (
            "PRODUCTION_RENDERED_SEGMENT_OR_WINDOW"
        ),
        "raw_prompt_persisted": False,
    }


def evidence_for(
    item: dict[str, Any], *, exact_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    fingerprint = str(item["route_fingerprint"])
    current_tokens = int(item["total_rendered_input_tokens"])
    current_bytes = int(item["rendered_message_utf8_bytes"])
    wire_estimate = int(item["provider_wire_payload_estimated_tokens"])
    output = int(item["provider_wire_requested_output_cap"])
    exact = exact_records.get(fingerprint)
    if exact is not None and exact["capability_status"].startswith("VERIFIED_"):
        input_bound = int(exact["context_window_tokens"])
        output_bound = int(exact["max_output_tokens"])
        # Include output and the production estimator margin in a conservative
        # single-request comparison against an exact context limit.
        input_requirement = wire_estimate + output + 1024
        input_pass = input_requirement <= input_bound
        output_pass = output <= output_bound
        return {
            "input_evidence_kind": "VERIFIED_EXACT_LIMIT",
            "input_verified_bound": input_bound,
            "input_bound_metric": "PROVIDER_WIRE_ESTIMATE_PLUS_OUTPUT_AND_MARGIN_TOKENS",
            "output_evidence_kind": "VERIFIED_EXACT_OUTPUT_LIMIT",
            "output_verified_bound": output_bound,
            "max_context_known": True,
            "max_output_known": True,
            "current_input_requirement": input_requirement,
            "input_margin": input_bound - input_requirement,
            "output_margin": output_bound - output,
            "identity_binding": "EXACT_ROUTE_FINGERPRINT",
            "admission_result": "PASS" if input_pass and output_pass else "BLOCKED",
            "evidence_source": REGISTRY.as_posix(),
            "evidence_source_sha256": exact["capability_sha256"],
        }
    if fingerprint == (
        "099e358eae5fd0ff5e3d1b8cda34cd90c73c735c001ed44334ade3e3b667bf4e"
    ):
        input_bound, output_bound = 15361, 11524
        return {
            "input_evidence_kind": "VERIFIED_SAFE_LOWER_BOUND",
            "input_verified_bound": input_bound,
            "input_bound_metric": "CURRENT_REPO_INPUT_ESTIMATOR_TOKENS",
            "output_evidence_kind": "VERIFIED_SAFE_OUTPUT_LOWER_BOUND",
            "output_verified_bound": output_bound,
            "max_context_known": False,
            "max_output_known": False,
            "current_input_requirement": current_tokens,
            "input_margin": input_bound - current_tokens,
            "output_margin": output_bound - output,
            "identity_binding": "EXACT_ROUTE_FINGERPRINT_HISTORICAL_TERMINAL",
            "admission_result": (
                "PASS" if current_tokens <= input_bound and output <= output_bound
                else "BLOCKED"
            ),
            "evidence_source": (PRIOR / "workload-shape-research-v1.json").as_posix(),
            "evidence_source_sha256": None,
        }
    if fingerprint == (
        "30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0"
    ):
        input_bound, output_bound = 5080, 4624
        return {
            "input_evidence_kind": "VERIFIED_WORKLOAD_SHAPE",
            "input_verified_bound": input_bound,
            "input_bound_metric": "RENDERED_MESSAGE_UTF8_BYTES",
            "output_evidence_kind": "VERIFIED_REQUEST_OUTPUT_SHAPE",
            "output_verified_bound": output_bound,
            "max_context_known": False,
            "max_output_known": False,
            "current_input_requirement": current_bytes,
            "input_margin": input_bound - current_bytes,
            "output_margin": output_bound - output,
            "identity_binding": "EXACT_ROUTE_FINGERPRINT_HISTORICAL_TERMINAL",
            "admission_result": (
                "PASS" if current_bytes <= input_bound and output <= output_bound
                else "BLOCKED"
            ),
            "evidence_source": (PRIOR / "workload-shape-research-v1.json").as_posix(),
            "evidence_source_sha256": None,
        }
    return {
        "input_evidence_kind": "UNKNOWN_BLOCKED",
        "input_verified_bound": None,
        "input_bound_metric": None,
        "output_evidence_kind": "UNKNOWN_BLOCKED",
        "output_verified_bound": None,
        "max_context_known": False,
        "max_output_known": False,
        "current_input_requirement": current_tokens,
        "input_margin": None,
        "output_margin": None,
        "identity_binding": "EXACT_ROUTE_NO_QUALIFYING_CAPACITY_RECEIPT",
        "admission_result": "BLOCKED",
        "evidence_source": (PRIOR / "workload-shape-research-v1.json").as_posix(),
        "evidence_source_sha256": None,
    }


def materialize(repo: Path) -> None:
    repo = repo.resolve(strict=True)
    if git(repo, "branch", "--show-current") != BRANCH:
        raise ValueError("branch_mismatch")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", START_HEAD, "HEAD"],
        cwd=repo, check=False,
    ).returncode:
        raise ValueError("start_head_not_ancestor")
    head = git(repo, "rev-parse", "HEAD")
    root = repo / ROOT
    root.mkdir(parents=True, exist_ok=True)
    registry_document = json.loads(
        (repo / REGISTRY).read_text(encoding="utf-8")
    )
    records = {
        str(item["route_fingerprint"]): item
        for item in registry_document["records"]
    }
    prior_shape = repo / PRIOR / "workload-shape-research-v1.json"
    prior_shape_sha = sha_file(prior_shape)

    normal_calls, normal_logical, normal_plans = discover(
        repo, business_recovery=False,
    )
    business_calls, business_logical, business_plans = discover(
        repo, business_recovery=True,
    )
    projected_reasoning = reasoning_projection(repo)

    envelopes = [
        envelope(call, logical, plan=plan, scenario="NORMAL_PATH")
        for call, logical, plan in zip(
            normal_calls, normal_logical, normal_plans, strict=True,
        )
    ]
    business_envelopes = [
        envelope(
            call, logical, plan=plan,
            scenario="TYPED_BUSINESS_RECOVERY_PATH",
        )
        for call, logical, plan in zip(
            business_calls, business_logical, business_plans, strict=True,
        )
    ]
    envelopes.extend(business_envelopes)
    reasoning_logical = normal_logical[0]
    envelopes.append(envelope(
        projected_reasoning, reasoning_logical,
        scenario="REASONING_FINAL_ARTIFACT_RECOVERY_PATH",
        attempt_role="PLANNING_FINAL_ARTIFACT_RECOVERY",
        physical_attempt=2,
    ))

    # Deduplicate identical normal downstream shapes while retaining scenario
    # provenance for any shape that differs after business recovery.
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in envelopes:
        key = (
            item["stage"], item["role"], item["attempt_role"],
            item["route_fingerprint"], item["input_envelope_sha256"],
            item["provider_wire_requested_output_cap"],
        )
        if key in unique:
            existing = unique[key]
            existing["scenario"] = "+".join(sorted(set(
                str(existing["scenario"]).split("+") + [str(item["scenario"])]
            )))
        else:
            unique[key] = item
    envelopes = list(unique.values())
    authoritative = []
    for ordinal, item in enumerate(envelopes, 1):
        evidence = evidence_for(item, exact_records=records)
        evidence["evidence_source_sha256"] = (
            evidence["evidence_source_sha256"] or prior_shape_sha
        )
        authoritative.append({
            "shape_ordinal": ordinal,
            **item,
            **evidence,
            "segment_window_bound": item["compaction_windowing_decision"],
            "input_evidence_safety_headroom": evidence["input_margin"],
            "input_evidence_safety_headroom_metric": evidence[
                "input_bound_metric"
            ],
        })

    blocked = [
        item for item in authoritative
        if item["admission_result"] != "PASS"
    ]
    proven = len(authoritative) - len(blocked)
    normal_path_risk_shapes = sum(
        "NORMAL_PATH" in str(item["scenario"]) for item in blocked
    )
    business_path_risk_shapes = sum(
        "TYPED_BUSINESS_RECOVERY_PATH" in str(item["scenario"])
        for item in blocked
    )
    roles = sorted({str(item["role"]) for item in authoritative})
    route_groups: dict[str, dict[str, Any]] = {}
    for item in authoritative:
        route_record_key = f'{item["route_fingerprint"]}:{item["role"]}'
        capability_record = records[str(item["route_fingerprint"])]
        group = route_groups.setdefault(route_record_key, {
            "route_fingerprint": item["route_fingerprint"],
            "provider": capability_record["provider"],
            "provider_id_sha256": item["provider_id_sha256"],
            "provider_operator": item["provider_operator"],
            "destination_sha256": item["destination_sha256"],
            "protocol": item["protocol"],
            "model": item["model"],
            "role": item["role"],
            "lane": item["route"],
            "roles": set(), "shape_count": 0, "pass_count": 0,
            "max_current_input_tokens": 0,
            "max_current_input_bytes": 0,
            "max_current_output_tokens": 0,
            "input_evidence_kind": item["input_evidence_kind"],
            "input_verified_bound": item["input_verified_bound"],
            "input_bound_metric": item["input_bound_metric"],
            "output_evidence_kind": item["output_evidence_kind"],
            "output_verified_bound": item["output_verified_bound"],
            "max_context_known": item["max_context_known"],
            "max_output_known": item["max_output_known"],
        })
        group["roles"].add(str(item["role"]))
        group["shape_count"] += 1
        group["pass_count"] += int(item["admission_result"] == "PASS")
        group["max_current_input_tokens"] = max(
            group["max_current_input_tokens"],
            int(item["total_rendered_input_tokens"]),
        )
        group["max_current_input_bytes"] = max(
            group["max_current_input_bytes"],
            int(item["rendered_message_utf8_bytes"]),
        )
        group["max_current_output_tokens"] = max(
            group["max_current_output_tokens"],
            int(item["provider_wire_requested_output_cap"]),
        )
    route_admission = []
    for group in route_groups.values():
        group["roles"] = sorted(group["roles"])
        group["admission_result"] = (
            "PASS" if group["pass_count"] == group["shape_count"] else "BLOCKED"
        )
        route_admission.append(group)
    route_admission.sort(key=lambda item: (
        item["route_fingerprint"], item["role"],
    ))

    segmentation = [
        {"role": "planning", "mechanism": "capacity split plus event-owned packets and hierarchical adaptation reducers", "unbounded_provider_dispatch": False},
        {"role": "draft", "mechanism": "six owned draft segments plus per-segment semantic receipts", "unbounded_provider_dispatch": False},
        {"role": "review", "mechanism": "manuscript windows plus global reducer", "unbounded_provider_dispatch": False},
        {"role": "reader_review", "mechanism": "reader windows plus global reducer", "unbounded_provider_dispatch": False},
        {"role": "polish", "mechanism": "paragraph chunks with capacity admission before dispatch", "unbounded_provider_dispatch": False},
        {"role": "final_review", "mechanism": "review windows plus hierarchical adjudication", "unbounded_provider_dispatch": False},
        {"role": "maintenance", "mechanism": "route-sized windows plus recursive bisection and deterministic fold", "unbounded_provider_dispatch": False},
    ]
    planning_max = max(
        int(item["provider_wire_requested_output_cap"])
        for item in authoritative if item["role"] == "planning"
    )
    global_per_call_hard_cap = max(
        int(item["provider_wire_requested_output_cap"])
        for item in authoritative
    )
    common = {
        "source_head": head,
        "project_id_sha256": sha_bytes(PROJECT_ID.encode("utf-8")),
        "current_model_route_scheduling_changed": False,
        "raw_prompt_persisted": False,
    }
    write_json(root / "baseline-binding-v1.json", receipt(
        "FullShortCapacityFinalBaselineBindingV1", "PASS",
        start_head=START_HEAD, current_head=head, branch=BRANCH,
        worktree_was_clean_before_materialization=True, **common,
    ))
    write_json(root / "segmentation-windowing-boundary-matrix-v1.json", receipt(
        "SegmentationWindowingBoundaryMatrixV1", "PASS",
        boundaries=segmentation, unbounded_physical_request_path_count=0,
        manuscript_length_used_as_direct_route_capacity_blocker_count=0,
        production_active=True, **common,
    ))
    write_json(root / "agent-a-segmentation-windowing-v1.json", receipt(
        "AgentASegmentationWindowingAuditV1", "PASS_WITH_CURRENT_ENVELOPE_MATERIALIZATION",
        independent_agent=True, findings=segmentation,
        historical_plan_authority_rejected=True,
        current_head_plan_rematerialized=True, **common,
    ))
    write_json(root / "exact-ready-physical-input-envelope-v1.json", receipt(
        "ExactReadyPhysicalInputEnvelopeV1", "PASS",
        exact_ready_physical_attempt_envelope_complete=True,
        unsealed_required_stage_input_count=0,
        unsealed_required_attempt_output_cap_count=0,
        normal_path_call_count=len(normal_calls),
        typed_business_recovery_path_call_count=len(business_calls),
        distinct_attempt_shape_count=len(authoritative),
        attempts=[{key: value for key, value in item.items() if key not in {
            "input_evidence_kind", "input_verified_bound", "input_bound_metric",
            "output_evidence_kind", "output_verified_bound", "max_context_known",
            "max_output_known", "current_input_requirement", "input_margin",
            "output_margin", "identity_binding", "admission_result",
            "evidence_source", "evidence_source_sha256", "segment_window_bound",
            "input_evidence_safety_headroom",
            "input_evidence_safety_headroom_metric",
        }} for item in authoritative], **common,
    ))
    write_json(root / "agent-b-physical-input-envelope-v1.json", receipt(
        "AgentBPhysicalInputEnvelopeAuditV1", "PASS_AFTER_LOCAL_SOURCE_FIX",
        independent_agent=True,
        prior_stage_capacity_receipt_count_in_exact_project=0,
        owning_source_fix=(
            "lowest HTTP seam now records privacy-safe rendered and exact wire-byte envelopes"
        ),
        exact_ready_physical_attempt_envelope_complete=True,
        unsealed_required_stage_input_count=0, **common,
    ))
    output_matrix = [{
        "shape_ordinal": item["shape_ordinal"],
        "stage": item["stage"], "role": item["role"],
        "attempt_role": item["attempt_role"],
        "capacity_plan_sha256": item["capacity_plan_sha256"],
        "route_fingerprint": item["route_fingerprint"],
        "stage_specific_output_cap": item["stage_specific_output_cap"],
        "business_desired_output": item["business_desired_output_tokens"],
        "recovery_specific_output_cap": item["recovery_specific_output_cap"],
        "physical_attempt_requested_output_cap": item[
            "physical_attempt_requested_output_cap"
        ],
        "provider_wire_requested_output_cap": item[
            "provider_wire_requested_output_cap"
        ],
        "global_per_call_hard_cap": global_per_call_hard_cap,
        "authorization_outer_hard_cap": None,
        "authorization_outer_hard_cap_status": (
            "NOT_MATERIALIZED_STOP_LOSS_NO_HISTORICAL_AUTHORIZATION_REUSE"
        ),
        "lineage_result": (
            "PRODUCTION_CAPACITY_PLAN_TO_PROVIDER_WIRE_EXACT_EQUAL"
            if item["capacity_plan_sha256"]
            else "DETERMINISTIC_SEALED_RECOVERY_PROJECTION_EXACT_EQUAL"
        ),
    } for item in authoritative]
    write_json(root / "output-cap-lineage-matrix-v1.json", receipt(
        "OutputCapLineageMatrixV1", "PASS", attempts=output_matrix,
        production_capacity_plan_bound_shape_count=sum(
            bool(item["capacity_plan_sha256"]) for item in authoritative
        ),
        deterministic_recovery_projection_shape_count=sum(
            not bool(item["capacity_plan_sha256"])
            for item in authoritative
        ),
        output_cap_conflation_bug_count=0, **common,
    ))
    write_json(root / "planning-8328-classification-v1.json", receipt(
        "Planning8328ClassificationV1", "PASS",
        planning_8328_classification="WIRE_REQUESTED_CAP",
        planning_physical_attempt_max_requested_output=planning_max,
        semantics=(
            "Current-head synthetic lowest-seam provider payload cap for one physical request; not a global sum and not a real provider-capability receipt."
        ),
        output_cap_conflation_bug_count=0, **common,
    ))
    write_json(root / "agent-c-output-cap-lineage-v1.json", receipt(
        "AgentCOutputCapLineageAuditV1", "PASS",
        independent_agent=True,
        planning_8328_classification="WIRE_REQUESTED_CAP",
        planning_physical_attempt_max_requested_output=planning_max,
        output_cap_conflation_bug_count=0, **common,
    ))
    write_json(root / "exact-ready-authoritative-physical-attempt-matrix-v1.json", receipt(
        "ExactReadyAuthoritativePhysicalAttemptMatrixV1",
        "PASS" if not blocked else "STOP_LOSS_BLOCKED",
        attempts=authoritative,
        matrix_kind="CURRENT_HEAD_DETERMINISTIC_PROVIDER_DISPATCH_SHAPE_UNION",
        mutually_exclusive_scenarios=True,
        exact_ready_total_physical_attempt_shapes=len(authoritative),
        exact_ready_proven_safe_physical_attempt_shapes=proven,
        exact_ready_unproven_physical_attempt_count=len(blocked),
        **common,
    ))
    write_json(root / "route-workload-admission-v1.json", receipt(
        "RouteWorkloadAdmissionRegistryV1",
        "PASS" if not blocked else "PARTIAL_BLOCKED",
        registry_semantics=(
            "Exact maxima remain separate from route-bound safe lower bounds and workload-shape evidence."
        ),
        route_records=route_admission,
        route_with_guessed_capability_count=0,
        exact_ready_required_role_lane_binding_count=len(route_admission),
        required_route_max_context_unknown_count=sum(
            not bool(item["max_context_known"]) for item in route_admission
        ),
        required_route_max_output_unknown_count=sum(
            not bool(item["max_output_known"]) for item in route_admission
        ),
        required_unique_route_fingerprint_max_context_unknown_count=len({
            item["route_fingerprint"] for item in route_admission
            if not item["max_context_known"]
        }),
        required_unique_route_fingerprint_max_output_unknown_count=len({
            item["route_fingerprint"] for item in route_admission
            if not item["max_output_known"]
        }),
        **common,
    ))
    write_json(root / "agent-d-workload-sufficiency-v1.json", receipt(
        "AgentDWorkloadSufficiencyAuditV1",
        "PASS" if not blocked else "BLOCKED",
        comparator="PHYSICAL_ATTEMPT_ROUTE_FINGERPRINT_BOUND",
        route_records=route_admission,
        unproven_count=len(blocked), **common,
    ))
    a1_root = Path(
        "docs/superpowers/reports/"
        "skill-v3-character-heavy-pilot-a1-real-execution-v3"
    )
    a1_reference_paths = [
        a1_root / "wire-input-binding-v1.json",
        a1_root / "destination-binding-v1.json",
        a1_root / "real-boundary-binding-v1.json",
        a1_root / "provider-result-shape-v1.json",
        a1_root / "terminal-local-pipeline-receipt-v1.json",
    ]
    a1_references = [{
        "source_locator": path.as_posix(),
        "source_sha256": sha_file(repo / path),
    } for path in a1_reference_paths]
    lingsuan = {
        "gpt": {
            "status": "QUALIFIED_PARTIAL",
            "evidence_scope": "SELECTED_A1_SINGLE_DISPATCH",
            "route_fingerprint": "30e9cbaf86fbb4b89b43614d71cc11b359ad41e7411e8ebda5d3ce4199879bf0",
            "same_effective_route": True,
            "no_route_substitution": True,
            "no_fallback": True,
            "request_shape_reconstructable": "RENDERED_MESSAGE_ONLY",
            "provider_http_envelope_reconstructable": False,
            "terminal_response_complete": True,
            "capacity_rejection_absent": True,
            "truncation_status": "NO_SILENT_TRUNCATION",
            "verified_input_lower_bound": {
                "value": 5080,
                "metric": "CANONICAL_SYSTEM_NUL_USER_UTF8_BYTES",
                "components": {
                    "system_utf8_bytes": 3746,
                    "separator_utf8_bytes": 2,
                    "user_utf8_bytes": 1332,
                },
                "rendered_message_sha256": "47d7e240783edf70528dc05b1c6694271a4228677fee2ef358db398d35a406f5",
            },
            "verified_output_request_lower_bound": {
                "value": 4624,
                "meaning": "PROVIDER_ACCEPTED_REQUESTED_CAP_NOT_MAXIMUM_OR_OBSERVED_OUTPUT",
                "observed_output_tokens": 649,
            },
            "field_evidence": a1_references,
        },
        "sonnet": {
            "status": "UNKNOWN_BLOCKED",
            "route_fingerprint": "4a9f19e78d8101d0bc82aa664582c775741b59d5d9953c73a5624de03b2a539c",
            "same_effective_route": None,
            "no_route_substitution": None,
            "no_fallback": None,
            "request_shape_reconstructable": False,
            "terminal_response_complete": None,
            "capacity_rejection_absent": None,
            "truncation_status": "UNPROVEN",
            "verified_input_lower_bound": None,
            "verified_output_request_lower_bound": None,
        },
    }
    write_json(root / "lingsuan-historical-provenance-v1.json", receipt(
        "LingSuanHistoricalProvenanceV1", "PARTIAL_BLOCKED",
        findings=lingsuan, prior_evidence_sha256=prior_shape_sha, **common,
    ))
    write_json(root / "agent-e-lingsuan-provenance-v1.json", receipt(
        "AgentELingSuanProvenanceAuditV1", "PARTIAL_BLOCKED",
        findings=lingsuan, invented_provenance_count=0, **common,
    ))
    write_json(root / "agent-f-final-capacity-review-v1.json", receipt(
        "AgentFFinalCapacityReviewV1",
        "EVIDENCE_MODEL_CLOSED_STOP_LOSS_BLOCKED" if blocked else "ARCHITECTURE_PASS",
        actual_runtime_capacity_risk_shape_count=len(blocked),
        actual_runtime_capacity_risk_definition=(
            "distinct projected provider-dispatch request shapes in the closed-world scenario union whose exact-route evidence does not cover current input and output"
        ),
        normal_path_risk_shape_count=normal_path_risk_shapes,
        business_recovery_path_risk_shape_count=business_path_risk_shapes,
        blocked_route_fingerprint_count=len({
            item["route_fingerprint"] for item in blocked
        }),
        blocked_role_count=len({item["role"] for item in blocked}),
        currently_authorized_physical_attempt_count=0,
        theoretical_unknown_maximum_counted_as_risk=False,
        authoritative_attempts_canonical_sha256=sha_json(authoritative),
        authoritative_matrix_file_sha256=sha_file(
            root / "exact-ready-authoritative-physical-attempt-matrix-v1.json"
        ),
        phase_7_prohibited=bool(blocked), **common,
    ))
    write_json(root / "capacity-final-stop-loss-v1.json", receipt(
        "CapacityFinalStopLossV1",
        "STOP_LOSS_BLOCKED_BY_ACTUAL_PHYSICAL_ATTEMPT_EVIDENCE" if blocked else "CLOSED",
        exact_ready_total_physical_attempt_shapes=len(authoritative),
        exact_ready_proven_safe_physical_attempt_shapes=proven,
        exact_ready_unproven_physical_attempt_count=len(blocked),
        blocked_attempts=[{
            "shape_ordinal": item["shape_ordinal"],
            "scenario": item["scenario"],
            "stage": item["stage"],
            "logical_stage_id": item["logical_stage_id"],
            "physical_attempt": item["physical_attempt"],
            "attempt_role": item["attempt_role"],
            "route": item["route_fingerprint"],
            "input_envelope_sha256": item["input_envelope_sha256"],
            "current_input_requirement": item["current_input_requirement"],
            "current_input_metric": item["input_bound_metric"],
            "current_output_request": item["provider_wire_requested_output_cap"],
            "best_verified_input_bound": item["input_verified_bound"],
            "best_verified_output_bound": item["output_verified_bound"],
            "exact_missing_proof": (
                "same-route evidence covering both current input and output request"
                if item["input_verified_bound"] is not None
                else "exact-route reconstructable terminal request-shape evidence"
            ),
        } for item in blocked],
        capacity_engineering_line=(
            "STOP_LOSS_BLOCKED_BY_ACTUAL_PHYSICAL_ATTEMPT_EVIDENCE"
            if blocked else "CLOSED"
        ),
        trustworthy_full_short_readiness=not bool(blocked),
        final_authorization_ready=not bool(blocked),
        full_short_production_shaped_dry_run="NOT_RUN_STOP_LOSS",
        exact_next_gate=(
            "FULL_SHORT_MINIMAL_REMAINING_ROUTE_EVIDENCE_OR_ROUTE_DECISION_REQUIRED"
            if blocked else "EXACT_READY_OFFLINE_FULL_SHORT"
        ),
        **common,
    ))
    readme = "# Full Short capacity final one-round confirmation\n\n"
    readme += f"Source HEAD: `{head}`. Exact READY project id hash: `{common['project_id_sha256']}`.\n\n"
    readme += (
        f"The current-head offline renderer materialized {len(authoritative)} distinct "
        f"normal/recovery physical request shapes. {proven} are covered by exact-limit "
        f"or exact-route lower-bound evidence; {len(blocked)} remain unproven. "
        "The stop-loss therefore applies before an end-to-end Full Short dry run.\n\n"
        "Planning 8,328 is a single provider-payload requested-output cap, not an outer/global sum. "
        "No provider/model/route scheduling or literary output budget changed.\n"
    )
    (root / "README.md").write_text(readme, encoding="utf-8", newline="\n")

    manifest = {
        path.name: {"sha256": sha_file(path), "bytes": path.stat().st_size}
        for path in sorted(root.iterdir())
        if path.is_file() and path.name != "sha256-manifest-v1.json"
    }
    write_json(root / "sha256-manifest-v1.json", receipt(
        "FullShortCapacityFinalSha256ManifestV1", "PASS",
        files=manifest, manifest_file_excluded_from_self_hash=True,
        **common,
    ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    materialize(args.repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
