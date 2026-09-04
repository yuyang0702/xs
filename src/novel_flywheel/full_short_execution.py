"""Fail-closed one-shot control plane for an authorized Full Short run.

The ordinary application does not enable this boundary.  A dedicated Full
Short launcher must supply an exact, externally materialized authorization,
then create one JIT approval and one durable nonce.  The ledger is written
before the lowest HTTP transport seam so a restart can never guess that an
ambiguous provider request is safe to repeat.

The public ledger persists only hashes, route/destination identities,
counters, and typed states.  When the prospective response-capture contract
is enabled, exact Provider response bytes are stored separately in the same
worktree-external private store; credentials, request headers, request prompts,
and tool arguments remain excluded from public receipts and Git.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import time
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


_PROCESS_CAPTURE_ATTESTATION_SIGNERS_V1: dict[str, Ed25519PrivateKey] = {}

from novel_flywheel.domain.models import ModelRequest
from novel_flywheel.execution_failure_architecture import (
    AuthorityEffect,
    DispatchState,
    DURABLE_FAILURE_EVIDENCE_POLICY_SHA256,
    DURABLE_FAILURE_EVIDENCE_POLICY_V1,
    ExactRecoveryViolation,
    FAILURE_ARCHITECTURE_IDENTITY,
    FailureLayer,
    FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256,
    FULL_SHORT_EXACT_RECOVERY_REGISTRY_V1,
    FullShortExactRecoveryControllerV1,
    full_short_boundary_taxonomy_v1,
    NONCE_RESERVATION_POLICY_SHA256,
    NONCE_RESERVATION_POLICY_V1,
    OBSERVER_ISOLATION_POLICY_SHA256,
    OBSERVER_ISOLATION_POLICY_V1,
    PREDISPATCH_STATE_MACHINE_SHA256,
    PREDISPATCH_STATE_MACHINE_V1,
    RestartBehavior,
)
from novel_flywheel.full_short_runtime_kernel import (
    ExecutionState as KernelExecutionState,
    PredispatchReadinessV1,
    active_full_short_kernel_v1,
    full_short_boundary_entry,
)
from novel_flywheel.provider_payloads import anthropic_payload_v1
from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    domain_sha256,
)
from novel_flywheel.provider_response_capture import (
    CONTRACT_RUNTIME_INPUT_BYTES,
    PROVIDER_PROTOCOL_INPUT_BYTES,
    ProviderResponseCaptureError,
    ProviderResponseCaptureStoreV1,
    extract_provider_reported_actual_usage_v1,
)
from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure
from novel_flywheel.stage_capacity import (
    AdmissionStatus,
    CapacityAdmissionFailureV1,
    CapacityFailureCode,
    DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1,
    MAX_CONTEXT_LIMIT_TOKENS_V1,
    RouteContextCapabilitySourceV1,
    StageCapacityAdmissionEngineV1,
    _mint_verified_external_workload_capacity_capability_v1,
    StageCapacityPlanV1,
    capacity_recovery_overlay_sha256_v1,
    capacity_recovery_prompt_delta_sha256_v1,
    validate_capacity_attempt_delta_v1,
)


POLICY_SCHEMA = "FullShortExecutionPolicyV1"
PERMISSION_SCHEMA = "FullShortExecutionPermissionV1"
APPROVAL_SCHEMA = "FullShortJitSignedApprovalV1"
NONCE_SCHEMA = "FullShortDurableNonceV1"
LEDGER_SCHEMA = "FullShortDispatchLedgerV1"
COMPLETION_SCHEMA = "FullShortCompletionReceiptV1"
DISPATCH_READINESS_SCHEMA = "FullShortDispatchReadinessReceiptV1"
AUTHORIZATION_SCHEMA = "FullShortCanonicalAuthorizationV1"
PREFLIGHT_SCHEMA = "FullShortAuthorizationPreflightReceiptV1"
POLICY_VERSION = "full-short-trustworthy-execution-v3"
SHORT_COMPLETION_GOAL = "SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED"
REQUIRED_FINAL_BINDING_KEYS = frozenset({
    "manuscript_sha256",
    "chapter_sha256",
    "canon_sha256",
    "story_state_sha256",
    "quality_checkpoint_sha256",
    "terminal_verification_sha256",
})
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_FULL_SHORT_EGRESS_ALLOWED = (
    "system_context", "task_contract", "authority", "story_slice",
    "current_baseline_skill_context", "output_contract",
    "provider_request_metadata",
)
_FULL_SHORT_EGRESS_FORBIDDEN = (
    "credentials", "unrelated_project_data", "raw_provider_evidence",
    "retired_skill_v3_hybrid_context",
)
RESPONSE_CAPTURE_POLICY_V1 = {
    "schema": "FullShortProviderResponseCapturePolicyV1",
    "version": 1,
    "required_byte_domains": [
        PROVIDER_PROTOCOL_INPUT_BYTES,
        CONTRACT_RUNTIME_INPUT_BYTES,
    ],
    "storage": "WORKTREE_EXTERNAL_EXCLUSIVE_CREATE_CRASH_SAFE",
    "capture_before_lossy_conversion": True,
    "failed_conversion_capture_retained": True,
    "exact_replay_required": True,
    "credentials_or_request_secrets_persisted": False,
    "restart_network_redispatch_allowed": False,
}
RESPONSE_CAPTURE_POLICY_SHA256 = hashlib.sha256(
    canonical_json_bytes(RESPONSE_CAPTURE_POLICY_V1),
).hexdigest()
TRANSPORT_RECOVERY_POLICY_V1 = {
    "schema": "FullShortTransportRecoveryPolicyV1",
    "version": 1,
    "identity": "EXACT_REPLAY_ONLY",
    "ordered_outcome_matrix": [
        {
            "outcome_class": "complete_valid",
            "action": "LOCAL_EXACT_CAPTURE_REPLAY_ALLOWED",
            "response_bytes_present": True,
            "valid_completion": True,
            "explicit_error": False,
            "ambiguity": False,
            "max_retry": 0,
            "fresh_nonce": False,
            "budget_counted": True,
        },
        {
            "outcome_class": "explicit_provider_error",
            "action": "FAIL_CLOSED_NO_REDISPATCH",
            "response_bytes_present": True,
            "valid_completion": False,
            "explicit_error": True,
            "ambiguity": False,
            "max_retry": 0,
            "fresh_nonce": False,
            "budget_counted": True,
        },
        {
            "outcome_class": "proven_pre_response",
            "action": "FAIL_CLOSED_NO_REDISPATCH",
            "response_bytes_present": False,
            "valid_completion": False,
            "explicit_error": False,
            "ambiguity": False,
            "max_retry": 0,
            "fresh_nonce": False,
            "budget_counted": True,
        },
        {
            "outcome_class": "ambiguous",
            "action": "FAIL_CLOSED_NO_REDISPATCH",
            "response_bytes_present": False,
            "valid_completion": False,
            "explicit_error": False,
            "ambiguity": True,
            "max_retry": 0,
            "fresh_nonce": False,
            "budget_counted": True,
        },
    ],
    "captured_bytes_required_for_local_replay": True,
    "local_replay_creates_physical_dispatch": False,
    "max_network_retries": 0,
    "fresh_nonce_allowed": False,
    "network_redispatch_allowed": False,
    "route_switch_allowed": False,
}
TRANSPORT_RECOVERY_POLICY_SHA256 = hashlib.sha256(
    canonical_json_bytes(TRANSPORT_RECOVERY_POLICY_V1),
).hexdigest()
LOGICAL_STAGE_RECOVERY_POLICY_V1 = {
    "schema": "FullShortLogicalStageRecoveryPolicyV1",
    "version": 1,
    "identity": "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY",
    "normal_planning_reasoning_policy": "CURRENT_PROVIDER_DEFAULT",
    "planning_finalization_recovery_stage_role": (
        "PLANNING_FINAL_ARTIFACT_RECOVERY"
    ),
    "planning_finalization_recovery_reasoning_policy": (
        "DEEPSEEK_OFFICIAL_ANTHROPIC_REASONING_EFFORT_NONE"
    ),
    "reasoning_only_failure_code": (
        "reasoning_only_final_artifact_unavailable"
    ),
    "max_physical_attempts_per_logical_stage": 2,
    "max_reasoning_only_recovery_dispatches_per_logical_stage": 1,
    "recovery_output_tokens": 3724,
    "slot_2_family_selection": "FIRST_TYPED_REJECTION_OWNS_SLOT",
    "recovery_family_composition_allowed": False,
    "same_route_required": True,
    "route_switch_allowed": False,
    "fallback_allowed": False,
    "same_frozen_authority_required": True,
    "same_validation_gates_required": True,
    "attempt_2_failure_action": "TERMINAL_FAIL_CLOSED",
    "restart_network_redispatch_allowed": False,
}
LOGICAL_STAGE_RECOVERY_POLICY_SHA256 = hashlib.sha256(
    canonical_json_bytes(LOGICAL_STAGE_RECOVERY_POLICY_V1),
).hexdigest()
_LOGICAL_STAGE_PLAN_KEYS = frozenset({
    "ordinal", "stage_id", "logical_stage_base_id", "logical_stage_id",
    "role", "route_lane", "contract_name", "contract_version",
    "contract_schema_sha256",
    "contract_runtime_input_required", "requested_output_tokens",
})
_CLOSED_LOCAL_ATTEMPT_STATES = frozenset({
    "LOCAL_STAGE_COMPLETE", "LOCAL_ATTEMPT_REJECTED",
})
_PROVIDER_PROTOCOL_ADAPTER_IDS = {
    "anthropic": frozenset({"anthropic"}),
    "openai-chat": frozenset({"openai-chat", "openai_chat"}),
    "openai-responses": frozenset({
        "openai-responses", "openai_responses",
    }),
}
_LOCAL_REJECTION_RECEIPT_FIELDS = frozenset({
    "schema", "version", "contract_name", "contract_version",
    "contract_schema_sha256", "attempt_index", "route", "route_attempt",
    "failure_kind", "failure_reason_sha256", "response_text_sha256",
    "conversion_audit_sha256", "raw_content_persisted",
})
_FINAL_ARTIFACT_REJECTION_RECEIPT_FIELDS = frozenset({
    "schema", "version", "contract_name", "contract_version",
    "contract_schema_sha256", "attempt_index", "route", "route_attempt",
    "failure_kind", "failure_code", "failure_reason_sha256",
    "provider_output_shape_sha256", "contract_runtime_input_present",
    "raw_content_persisted",
})
_DISPATCH_READINESS_FIELDS_V1 = frozenset({
    "schema", "version", "execution_id", "policy_sha256",
    "logical_stage_plan_sha256", "permission_sha256",
    "signed_approval_sha256", "predispatch_ledger_sha256",
    "observer_session_sha256", "logical_stage_id", "physical_attempt_id",
    "global_physical_attempt_ordinal",
    "logical_capacity_envelope_sha256",
    "route_capability_snapshot_sha256",
    "role_binding_sha256", "route_fingerprint", "destination_sha256",
    "request_shape_sha256", "provider_payload_sha256",
    "egress_intent_sha256", "requested_output_tokens",
    "total_requested_output_tokens", "expected_stage_calls",
    "hard_max_provider_requests", "hard_max_http_posts",
    "hard_max_network_attempts", "max_physical_attempts_per_logical_stage",
    "per_call_output_token_hard_cap", "total_output_token_hard_cap",
    "maximum_elapsed_seconds", "provider_request_count_before_commit",
    "http_post_count_before_commit", "network_request_count_before_commit",
    "provider_response_count_before_commit",
    "completed_stage_count_before_commit",
    "capacity_policy_registry_sha256", "capacity_plan_sha256",
    "capacity_admission_receipt_sha256", "capacity_admission_status",
})
_DISPATCH_READINESS_HASH_FIELDS_V1 = frozenset({
    "policy_sha256", "logical_stage_plan_sha256", "permission_sha256",
    "signed_approval_sha256", "predispatch_ledger_sha256",
    "observer_session_sha256", "role_binding_sha256", "route_fingerprint",
    "destination_sha256", "request_shape_sha256", "provider_payload_sha256",
    "egress_intent_sha256",
    "capacity_policy_registry_sha256", "capacity_plan_sha256",
    "capacity_admission_receipt_sha256",
    "logical_capacity_envelope_sha256",
    "route_capability_snapshot_sha256",
})
_DISPATCH_READINESS_CAP_FIELDS_V1 = frozenset({
    "expected_stage_calls", "hard_max_provider_requests",
    "hard_max_http_posts", "hard_max_network_attempts",
    "max_physical_attempts_per_logical_stage",
    "per_call_output_token_hard_cap", "total_output_token_hard_cap",
    "maximum_elapsed_seconds",
})
_DISPATCH_READINESS_COUNTER_FIELDS_V1 = frozenset({
    "provider_request_count_before_commit", "http_post_count_before_commit",
    "network_request_count_before_commit",
    "provider_response_count_before_commit",
    "completed_stage_count_before_commit",
})
_CAPACITY_ADMISSION_RECEIPT_FIELDS_V1 = frozenset({
    "schema", "version", "execution_id", "policy_sha256",
    "capacity_policy_registry_sha256", "capacity_plan_sha256",
    "stage_id_sha256", "logical_stage_id", "physical_attempt",
    "physical_attempt_id", "global_physical_attempt_ordinal",
    "logical_capacity_envelope_sha256",
    "route_capability_snapshot_sha256",
    "external_workload_evidence_sha256",
    "contract_name_sha256", "contract_version",
    "contract_schema_sha256", "provider_route_identity_sha256",
    "stage_operational_context_ceiling_tokens",
    "route_context_capability_limit_tokens",
    "route_context_capability_source", "model_context_limit",
    "provider_wire_input_token_estimate",
    "role_sha256", "route", "rendered_request_sha256",
    "requested_output_token_cap", "final_output_reserve",
    "route_max_output_tokens", "reasoning_token_reserve",
    "reasoning_token_accounting", "reasoning_output_reservation",
    "recovery_stage_role", "reasoning_policy",
    "base_rendered_request_sha256", "recovery_overlay_kind",
    "recovery_overlay_sha256",
    "prior_rendered_request_sha256", "recovery_prompt_delta_sha256",
    "recovery_source_capture_receipt_sha256",
    "admission_status", "model_request_sha256",
    "provider_payload_sha256", "egress_intent_sha256",
    "outbound_request_bytes_sha256", "destination_sha256", "state",
    "raw_prompt_persisted", "created_at", "updated_at",
    "capacity_admission_receipt_sha256",
})
_CAPACITY_ADMISSION_RECEIPT_HASH_FIELDS_V1 = frozenset({
    "policy_sha256", "capacity_policy_registry_sha256",
    "capacity_plan_sha256", "stage_id_sha256", "contract_name_sha256",
    "contract_schema_sha256", "provider_route_identity_sha256",
    "role_sha256", "rendered_request_sha256",
    "logical_capacity_envelope_sha256",
    "route_capability_snapshot_sha256",
    "base_rendered_request_sha256", "recovery_overlay_sha256",
    "recovery_prompt_delta_sha256",
})
_CAPACITY_ADMISSION_REQUEST_HASH_FIELDS_V1 = frozenset({
    "model_request_sha256", "provider_payload_sha256",
    "egress_intent_sha256",
})
_CAPACITY_ADMISSION_DISPATCH_HASH_FIELDS_V1 = frozenset({
    "outbound_request_bytes_sha256", "destination_sha256",
})
_EXTERNAL_WORKLOAD_FAMILY_FIELDS_V1 = frozenset({
    "schema", "version", "request_family_sha256", "request_sha256",
    "evidence_sha256",
    "authorization_sha256", "final_execution_head", "case_id",
    "input_tokens", "requested_output_tokens", "actual_output_tokens",
    "proven_workload_context_lower_bound_tokens",
})
_OUTER_CAMPAIGN_USAGE_GUARD_FIELDS_V1 = frozenset({
    "schema", "version", "campaign_authorization_sha256",
    "prior_provider_request_count", "prior_input_tokens",
    "prior_output_tokens", "remaining_provider_requests",
    "remaining_input_tokens", "remaining_output_tokens",
    "remaining_elapsed_seconds", "absolute_deadline_unix_seconds",
    "guard_sha256",
})


def _validate_capacity_admission_receipt_v1(
    value: Mapping[str, Any], *, execution_id: str, plan_sha256: str,
) -> dict[str, Any]:
    """Validate the exact durable capacity receipt schema and state."""

    body = deepcopy(dict(value))
    fields = set(body)
    allowed = _CAPACITY_ADMISSION_RECEIPT_FIELDS_V1
    _require(
        fields == allowed or fields == allowed | {"consumed_at"},
        "CAPACITY_ADMISSION_RECEIPT_SCHEMA_INVALID",
    )
    _require(
        body.get("schema") == "FullShortCapacityAdmissionReceiptV1"
        and body.get("version") == 1
        and body.get("execution_id") == execution_id
        and body.get("capacity_plan_sha256") == plan_sha256
        and body.get("admission_status") == "PASS"
        and body.get("raw_prompt_persisted") is False,
        "CAPACITY_ADMISSION_RECEIPT_SCHEMA_INVALID",
    )
    _require(
        all(
            isinstance(body.get(field), str)
            and _HEX64.fullmatch(str(body[field])) is not None
            for field in (
                _CAPACITY_ADMISSION_RECEIPT_HASH_FIELDS_V1
                | {"capacity_admission_receipt_sha256"}
            )
        ),
        "CAPACITY_ADMISSION_RECEIPT_HASH_INVALID",
    )
    integer_fields = (
        "physical_attempt", "global_physical_attempt_ordinal",
        "contract_version",
        "stage_operational_context_ceiling_tokens",
        "route_context_capability_limit_tokens", "model_context_limit",
        "provider_wire_input_token_estimate",
        "requested_output_token_cap", "final_output_reserve",
        "route_max_output_tokens",
    )
    _require(
        all(type(body.get(field)) is int and body[field] > 0
            for field in integer_fields),
        "CAPACITY_ADMISSION_RECEIPT_LIMIT_INVALID",
    )
    for optional_hash_field in (
        "prior_rendered_request_sha256",
        "recovery_source_capture_receipt_sha256",
    ):
        optional_hash = body.get(optional_hash_field)
        _require(
            optional_hash is None
            or (
                isinstance(optional_hash, str)
                and _HEX64.fullmatch(optional_hash) is not None
            ),
            "CAPACITY_ADMISSION_RECEIPT_HASH_INVALID",
        )
    external_evidence_sha256 = body.get(
        "external_workload_evidence_sha256"
    )
    if body.get("route_context_capability_source") == (
        RouteContextCapabilitySourceV1
        .VERIFIED_EXTERNAL_WORKLOAD_EVIDENCE.value
    ):
        _require(
            isinstance(external_evidence_sha256, str)
            and _HEX64.fullmatch(external_evidence_sha256) is not None
            and external_evidence_sha256
            == body.get("route_capability_snapshot_sha256"),
            "CAPACITY_ADMISSION_EXTERNAL_EVIDENCE_INVALID",
        )
    else:
        _require(
            external_evidence_sha256 is None,
            "CAPACITY_ADMISSION_EXTERNAL_EVIDENCE_INVALID",
        )
    _require(
        isinstance(body.get("recovery_stage_role"), str)
        and bool(body["recovery_stage_role"])
        and isinstance(body.get("reasoning_policy"), str)
        and bool(body["reasoning_policy"])
        and body.get("recovery_overlay_kind") in {
            "NONE",
            "FINAL_ARTIFACT_COMPLETION",
            "PROTOCOL_REGENERATION",
            "DOMAIN_FINDINGS",
            "FINAL_ARTIFACT_COMPLETION+DOMAIN_FINDINGS",
            "PROTOCOL_REGENERATION+DOMAIN_FINDINGS",
            "REVIEW_COMPACT_RETRY",
            "POLISH_NO_TOOLS_RETRY",
        }
        and body.get("recovery_overlay_sha256")
        == capacity_recovery_overlay_sha256_v1(
            base_rendered_request_sha256=body["base_rendered_request_sha256"],
            rendered_request_sha256=body["rendered_request_sha256"],
            recovery_overlay_kind=body["recovery_overlay_kind"],
        ),
        "CAPACITY_ADMISSION_RECEIPT_SCHEMA_INVALID",
    )
    _require(
        body["stage_operational_context_ceiling_tokens"]
        <= MAX_CONTEXT_LIMIT_TOKENS_V1
        and body["route_context_capability_limit_tokens"]
        <= MAX_CONTEXT_LIMIT_TOKENS_V1
        and body["model_context_limit"] <= MAX_CONTEXT_LIMIT_TOKENS_V1,
        "CAPACITY_ADMISSION_RECEIPT_LIMIT_INVALID",
    )
    _require(
        body["model_context_limit"] == min(
            body["stage_operational_context_ceiling_tokens"],
            body["route_context_capability_limit_tokens"],
        )
        and body.get("route_context_capability_source") in {
            item.value for item in RouteContextCapabilitySourceV1
        },
        "CAPACITY_ADMISSION_RECEIPT_LIMIT_INVALID",
    )
    reasoning_pair = (
        body.get("reasoning_token_accounting"),
        body.get("reasoning_output_reservation"),
    )
    reasoning_reserve = body.get("reasoning_token_reserve")
    _require(
        isinstance(body.get("physical_attempt_id"), str)
        and str(body["physical_attempt_id"]).startswith("physical-")
        and type(reasoning_reserve) is int
        and (
            reasoning_pair == (
                "INCLUDED_IN_COMPLETION_CAP", "WITHIN_COMPLETION_CAP",
            ) and reasoning_reserve == 0
            or reasoning_pair == (
                "SEPARATE_IF_REPORTED",
                "SEPARATE_REPORTED_RESERVATION_REQUIRED",
            ) and reasoning_reserve > 0
        )
        and body["requested_output_token_cap"]
        <= body["route_max_output_tokens"],
        "CAPACITY_ADMISSION_RECEIPT_LIMIT_INVALID",
    )
    state = body.get("state")
    _require(
        state in {
            "PLAN_BOUND_UNCONSUMED", "REQUEST_BOUND_UNCONSUMED", "CONSUMED",
        },
        "CAPACITY_ADMISSION_RECEIPT_STATE_INVALID",
    )
    request_hashes = tuple(
        body.get(field) for field in _CAPACITY_ADMISSION_REQUEST_HASH_FIELDS_V1
    )
    dispatch_hashes = tuple(
        body.get(field) for field in _CAPACITY_ADMISSION_DISPATCH_HASH_FIELDS_V1
    )
    if state == "PLAN_BOUND_UNCONSUMED":
        _require(
            all(item is None for item in request_hashes + dispatch_hashes)
            and "consumed_at" not in body,
            "CAPACITY_ADMISSION_RECEIPT_STATE_INVALID",
        )
    elif state == "REQUEST_BOUND_UNCONSUMED":
        _require(
            all(isinstance(item, str) and _HEX64.fullmatch(item)
                for item in request_hashes)
            and all(item is None for item in dispatch_hashes)
            and "consumed_at" not in body,
            "CAPACITY_ADMISSION_RECEIPT_STATE_INVALID",
        )
    else:
        _require(
            all(isinstance(item, str) and _HEX64.fullmatch(item)
                for item in request_hashes + dispatch_hashes)
            and isinstance(body.get("consumed_at"), str),
            "CAPACITY_ADMISSION_RECEIPT_STATE_INVALID",
        )
    return body


def _capacity_recovery_source_identity_v1(
    attempt: Mapping[str, Any],
) -> str | None:
    capture = (
        attempt.get("contract_runtime_capture_receipt_sha256")
        or attempt.get("provider_protocol_capture_receipt_sha256")
    )
    if capture is None and not attempt.get("capture_enforcement_required"):
        capture = domain_sha256(
            "novel-flywheel-local-response-identity-v1",
            {key: attempt.get(key) for key in (
                "physical_attempt_id",
                "response_status_sha256",
                "local_stage_receipt_sha256",
                "state",
            )},
        )
    return str(capture) if capture is not None else None


def _logical_capacity_envelope_sha256_v1(
    *, execution_id: str, policy: Mapping[str, Any],
    logical_stage_plan_entry: Mapping[str, Any],
) -> str:
    """Derive the capacity envelope from frozen policy source truth."""

    return domain_sha256(
        "novel-flywheel-logical-stage-capacity-envelope-v1",
        {
            "execution_id": execution_id,
            "policy_sha256": policy["policy_sha256"],
            "workload_sha256": policy["workload_sha256"],
            "runtime_authority_sha256": policy[
                "runtime_authority_sha256"
            ],
            "logical_stage_plan_entry": dict(logical_stage_plan_entry),
            "logical_stage_recovery_policy_sha256": policy[
                "logical_stage_recovery_policy_sha256"
            ],
            "capacity_policy_registry_sha256": policy[
                "capacity_policy_registry_sha256"
            ],
            "route_manifest_sha256": policy["route_manifest_sha256"],
            "destination_manifest_sha256": policy[
                "destination_manifest_sha256"
            ],
        },
    )


def _validate_capacity_recovery_chain_v1(
    *, attempts: Iterable[Mapping[str, Any]],
    receipts_by_plan: Mapping[str, Mapping[str, Any]],
) -> None:
    prior_by_logical_stage: dict[
        str, tuple[Mapping[str, Any], Mapping[str, Any]]
    ] = {}
    consumed_recovery_sources: set[str] = set()
    for attempt in attempts:
        plan_sha = str(attempt.get("capacity_plan_sha256") or "")
        receipt = receipts_by_plan.get(plan_sha)
        _require(
            receipt is not None,
            "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID",
        )
        logical_stage_id = str(attempt.get("logical_stage_id") or "")
        prior = prior_by_logical_stage.get(logical_stage_id)
        if prior is None:
            expected_role = "NORMAL"
            expected_reasoning_policy = "DEFAULT"
            expected_prior_rendered = None
            expected_source = None
        else:
            prior_attempt, prior_receipt = prior
            expected_role = str(attempt.get("stage_role") or "NORMAL")
            expected_reasoning_policy = (
                "DISABLE_REASONING"
                if expected_role == "PLANNING_FINAL_ARTIFACT_RECOVERY"
                else "PRESERVE_REASONING_POLICY"
            )
            expected_prior_rendered = prior_receipt.get(
                "rendered_request_sha256"
            )
            expected_source = _capacity_recovery_source_identity_v1(
                prior_attempt
            )
            _require(
                isinstance(expected_source, str)
                and _HEX64.fullmatch(expected_source) is not None
                and expected_source not in consumed_recovery_sources,
                "COMPLETION_CAPACITY_RECOVERY_PROVENANCE_INVALID",
            )
            consumed_recovery_sources.add(expected_source)
        expected_delta = capacity_recovery_prompt_delta_sha256_v1(
            prior_rendered_request_sha256=expected_prior_rendered,
            rendered_request_sha256=str(
                receipt.get("rendered_request_sha256") or ""
            ),
            recovery_stage_role=expected_role,
            reasoning_policy=expected_reasoning_policy,
            recovery_source_capture_receipt_sha256=expected_source,
            base_rendered_request_sha256=str(
                receipt.get("base_rendered_request_sha256") or ""
            ),
            recovery_overlay_kind=str(
                receipt.get("recovery_overlay_kind") or ""
            ),
            recovery_overlay_sha256=str(
                receipt.get("recovery_overlay_sha256") or ""
            ),
        )
        _require(
            receipt.get("recovery_stage_role") == expected_role
            and receipt.get("reasoning_policy")
            == expected_reasoning_policy
            and receipt.get("prior_rendered_request_sha256")
            == expected_prior_rendered
            and receipt.get("recovery_source_capture_receipt_sha256")
            == expected_source
            and receipt.get("recovery_prompt_delta_sha256")
            == expected_delta,
            "COMPLETION_CAPACITY_RECOVERY_PROVENANCE_INVALID",
        )
        prior_by_logical_stage[logical_stage_id] = (attempt, receipt)


def _validate_completion_physical_attempt_chain_v1(
    *, execution_id: str, attempts: Iterable[Mapping[str, Any]],
) -> None:
    """Re-derive durable dispatch identity instead of trusting resealed fields."""

    logical_counts: dict[str, int] = {}
    for expected_ordinal, attempt in enumerate(attempts, 1):
        logical_stage_id = str(attempt.get("logical_stage_id") or "")
        logical_counts[logical_stage_id] = logical_counts.get(
            logical_stage_id, 0
        ) + 1
        expected_physical_id = "physical-" + domain_sha256(
            "novel-flywheel-full-short-physical-attempt-id-v1",
            {
                "execution_id": execution_id,
                "logical_stage_id": logical_stage_id,
                "ordinal": expected_ordinal,
            },
        )[:32]
        _require(
            attempt.get("ordinal") == expected_ordinal
            and attempt.get("global_physical_attempt_ordinal")
            == expected_ordinal
            and attempt.get("physical_attempt_id") == expected_physical_id,
            "COMPLETION_PHYSICAL_ATTEMPT_IDENTITY_INVALID",
        )


class FullShortExecutionBoundaryError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        normalized = re.sub(r"[^A-Z0-9]+", "_", reason_code.upper()).strip("_")
        taxonomy = full_short_boundary_taxonomy_v1(normalized)
        layer = (
            taxonomy["layer"] if taxonomy is not None
            else FailureLayer.EXECUTION_RUNTIME_BINDING
        )
        family = (
            str(taxonomy["family"]) if taxonomy is not None
            else "execution.unmapped_local_boundary"
        )
        failure_class = (
            taxonomy["failure_class"] if taxonomy is not None
            else FailureClass.STALE_AUTHORITY
        )
        self.failure_layer = layer
        self.failure_family = family
        self.dispatch_state = (
            taxonomy["dispatch_state"] if taxonomy is not None
            else DispatchState.NOT_REACHED
        )
        self.authority_effect = (
            taxonomy["authority_effect"] if taxonomy is not None
            else AuthorityEffect.BLOCKS_ACCEPTANCE
        )
        self.restart_behavior = (
            taxonomy["restart_behavior"] if taxonomy is not None
            else RestartBehavior.FRESH_AUTHORIZATION_REQUIRED
        )
        self.recovery_action = (
            str(taxonomy["recovery_action"]) if taxonomy is not None
            else "register_local_boundary_before_authorization"
        )
        self.reliability_failure = ReliabilityFailure(
            code=(
                str(taxonomy["code"]) if taxonomy is not None
                else f"unmapped_{normalized.casefold()}"
            ),
            failure_class=failure_class,
            boundary=(
                str(taxonomy["boundary"]) if taxonomy is not None
                else "full_short.execution.runtime_binding"
            ),
            retryable=False,
        )
        super().__init__(reason_code)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise FullShortExecutionBoundaryError(reason)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z",
    )


def build_full_short_outer_campaign_usage_guard_v1(
    *, campaign_authorization_sha256: str,
    prior_provider_request_count: int, prior_input_tokens: int,
    prior_output_tokens: int, remaining_provider_requests: int,
    remaining_input_tokens: int, remaining_output_tokens: int,
    remaining_elapsed_seconds: int, absolute_deadline_unix_seconds: int,
) -> dict[str, Any]:
    """Build the optional outer-campaign budget supplied by the launcher."""

    body = {
        "schema": "FullShortOuterCampaignUsageGuardV1",
        "version": 1,
        "campaign_authorization_sha256": campaign_authorization_sha256,
        "prior_provider_request_count": prior_provider_request_count,
        "prior_input_tokens": prior_input_tokens,
        "prior_output_tokens": prior_output_tokens,
        "remaining_provider_requests": remaining_provider_requests,
        "remaining_input_tokens": remaining_input_tokens,
        "remaining_output_tokens": remaining_output_tokens,
        "remaining_elapsed_seconds": remaining_elapsed_seconds,
        "absolute_deadline_unix_seconds": absolute_deadline_unix_seconds,
    }
    return {
        **body,
        "guard_sha256": domain_sha256(
            "novel-flywheel-full-short-outer-campaign-usage-guard-v1",
            body,
        ),
    }


def validate_full_short_outer_campaign_usage_guard_v1(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "OUTER_CAMPAIGN_USAGE_GUARD_INVALID")
    body = deepcopy(dict(value))
    _require(
        set(body) == _OUTER_CAMPAIGN_USAGE_GUARD_FIELDS_V1
        and body.get("schema") == "FullShortOuterCampaignUsageGuardV1"
        and body.get("version") == 1,
        "OUTER_CAMPAIGN_USAGE_GUARD_INVALID",
    )
    _require(
        isinstance(body.get("campaign_authorization_sha256"), str)
        and _HEX64.fullmatch(body["campaign_authorization_sha256"])
        is not None,
        "OUTER_CAMPAIGN_USAGE_GUARD_INVALID",
    )
    integer_fields = (
        "prior_provider_request_count", "prior_input_tokens",
        "prior_output_tokens", "remaining_provider_requests",
        "remaining_input_tokens", "remaining_output_tokens",
        "remaining_elapsed_seconds", "absolute_deadline_unix_seconds",
    )
    _require(
        all(type(body.get(field)) is int and body[field] >= 0
            for field in integer_fields),
        "OUTER_CAMPAIGN_USAGE_GUARD_INVALID",
    )
    _require(
        body["absolute_deadline_unix_seconds"] > 0,
        "OUTER_CAMPAIGN_USAGE_GUARD_INVALID",
    )
    sealed = dict(body)
    guard_sha256 = sealed.pop("guard_sha256", None)
    _require(
        guard_sha256 == domain_sha256(
            "novel-flywheel-full-short-outer-campaign-usage-guard-v1",
            sealed,
        ),
        "OUTER_CAMPAIGN_USAGE_GUARD_SHA256_MISMATCH",
    )
    return body


def _campaign_accounted_usage_debit_v1(
    *, attempt: Mapping[str, Any],
    provider_usage: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if provider_usage is None:
        basis = "CONSERVATIVE_REQUEST_BOUND"
        input_tokens = int(attempt["estimated_input_tokens"])
        output_tokens = int(attempt["requested_output_tokens"])
        provider_usage_receipt_sha256 = None
        provider_entity_sha256 = None
    else:
        basis = "PROVIDER_REPORTED_ACTUAL"
        input_tokens = int(provider_usage["input_tokens"])
        output_tokens = int(provider_usage["output_tokens"])
        provider_usage_receipt_sha256 = provider_usage[
            "usage_receipt_sha256"
        ]
        provider_entity_sha256 = provider_usage["provider_entity_sha256"]
    body = {
        "schema": "FullShortCampaignAccountedUsageDebitV1",
        "version": 1,
        "accounting_basis": basis,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_input_tokens": int(attempt["estimated_input_tokens"]),
        "requested_output_tokens": int(attempt["requested_output_tokens"]),
        "provider_protocol_capture_receipt_sha256": attempt.get(
            "provider_protocol_capture_receipt_sha256"
        ),
        "provider_usage_receipt_sha256": provider_usage_receipt_sha256,
        "provider_entity_sha256": provider_entity_sha256,
    }
    return {
        **body,
        "accounted_usage_debit_sha256": domain_sha256(
            "novel-flywheel-full-short-campaign-accounted-usage-debit-v1",
            body,
        ),
    }


def _attempt_actual_usage_receipt_v1(
    *, attempt: Mapping[str, Any], accounted_usage: Mapping[str, Any],
    guard: Mapping[str, Any], full_short_input_tokens: int,
    full_short_output_tokens: int,
) -> dict[str, Any]:
    body = {
        "schema": "FullShortAttemptActualUsageReceiptV1",
        "version": 1,
        "ordinal": attempt.get("ordinal"),
        "physical_attempt_id": attempt.get("physical_attempt_id"),
        "provider_protocol_capture_receipt_sha256": attempt.get(
            "provider_protocol_capture_receipt_sha256"
        ),
        "accounted_usage_debit_sha256": accounted_usage.get(
            "accounted_usage_debit_sha256"
        ),
        "outer_campaign_usage_guard_sha256": guard["guard_sha256"],
        "accounted_input_tokens": accounted_usage.get("input_tokens"),
        "accounted_output_tokens": accounted_usage.get("output_tokens"),
        "full_short_cumulative_input_tokens": full_short_input_tokens,
        "full_short_cumulative_output_tokens": full_short_output_tokens,
        "campaign_cumulative_provider_requests": (
            guard["prior_provider_request_count"] + int(attempt["ordinal"])
        ),
        "campaign_cumulative_input_tokens": (
            guard["prior_input_tokens"] + full_short_input_tokens
        ),
        "campaign_cumulative_output_tokens": (
            guard["prior_output_tokens"] + full_short_output_tokens
        ),
    }
    return {
        **body,
        "attempt_usage_receipt_sha256": domain_sha256(
            "novel-flywheel-full-short-attempt-actual-usage-v1", body,
        ),
    }


def verify_full_short_actual_usage_v1(
    *, ledger: Mapping[str, Any],
    durable_store: FullShortDurableExecutionStoreV1 | None = None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Verify the append-only per-attempt usage chain, optionally from bytes."""

    sealed = FullShortDurableExecutionStoreV1._verify_seal(
        ledger, domain="novel-flywheel-full-short-dispatch-ledger-v1",
        field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
    )
    attempts = list(sealed.get("attempts") or [])
    guarded = [
        item for item in attempts
        if item.get("outer_campaign_usage_guard") is not None
    ]
    if not guarded:
        _require(
            not any(
                item.get("provider_reported_actual_usage") is not None
                or item.get("campaign_accounted_usage") is not None
                or item.get("attempt_usage_receipt_sha256") is not None
                for item in attempts
            ),
            "OUTER_CAMPAIGN_USAGE_WITHOUT_GUARD",
        )
        return None
    _require(
        len(guarded) == len(attempts),
        "OUTER_CAMPAIGN_USAGE_GUARD_PARTIAL",
    )
    guard = validate_full_short_outer_campaign_usage_guard_v1(
        guarded[0]["outer_campaign_usage_guard"]
    )
    input_total = 0
    output_total = 0
    provider_receipts: list[str] = []
    accounted_debits: list[str] = []
    attempt_receipts: list[str] = []
    provider_reported_actual_complete = True
    capture_store = (
        ProviderResponseCaptureStoreV1(
            repo_root=durable_store.repo_root,
            store_root=(
                durable_store.root / "provider-response-captures-v1"
            ),
        )
        if durable_store is not None else None
    )
    if capture_store is not None:
        _require(
            isinstance(policy, Mapping),
            "PROVIDER_CAPTURE_EXTERNAL_ANCHOR_POLICY_REQUIRED",
        )
        validated_policy = durable_store._verify_store_binding(policy)
        capture_anchors = durable_store.audit_provider_response_capture_anchors(
            policy=validated_policy,
        )
        audited = capture_store.audit_all(
            expected_receipt_sha256s=[
                str(item["provider_response_capture_receipt_sha256"])
                for item in capture_anchors
            ],
        )
    else:
        audited = []
    for expected_ordinal, attempt in enumerate(attempts, 1):
        current_guard = validate_full_short_outer_campaign_usage_guard_v1(
            attempt.get("outer_campaign_usage_guard") or {}
        )
        _require(current_guard == guard, "OUTER_CAMPAIGN_USAGE_GUARD_DRIFT")
        _require(
            attempt.get("ordinal") == expected_ordinal,
            "OUTER_CAMPAIGN_USAGE_ORDINAL_INVALID",
        )
        accounted_usage = attempt.get("campaign_accounted_usage")
        _require(
            isinstance(accounted_usage, Mapping),
            "CAMPAIGN_ACCOUNTED_USAGE_NOT_DURABLE",
        )
        accounted_usage = dict(accounted_usage)
        accounted_body = dict(accounted_usage)
        accounted_sha256 = accounted_body.pop(
            "accounted_usage_debit_sha256", None,
        )
        _require(
            accounted_sha256 == domain_sha256(
                "novel-flywheel-full-short-campaign-accounted-usage-debit-v1",
                accounted_body,
            ),
            "CAMPAIGN_ACCOUNTED_USAGE_DEBIT_MISMATCH",
        )
        basis = accounted_usage.get("accounting_basis")
        provider_usage = attempt.get("provider_reported_actual_usage")
        if basis == "PROVIDER_REPORTED_ACTUAL":
            _require(
                isinstance(provider_usage, Mapping),
                "PROVIDER_REPORTED_USAGE_NOT_DURABLE",
            )
            provider_usage = dict(provider_usage)
            provider_body = dict(provider_usage)
            provider_sha256 = provider_body.pop("usage_receipt_sha256", None)
            _require(
                provider_sha256 == domain_sha256(
                    "novel-flywheel-provider-reported-actual-usage-v1",
                    provider_body,
                )
                and accounted_usage
                == _campaign_accounted_usage_debit_v1(
                    attempt=attempt, provider_usage=provider_usage,
                ),
                "PROVIDER_REPORTED_USAGE_RECEIPT_MISMATCH",
            )
        elif basis == "CONSERVATIVE_REQUEST_BOUND":
            provider_reported_actual_complete = False
            provider_sha256 = None
            _require(
                provider_usage is None
                and accounted_usage == _campaign_accounted_usage_debit_v1(
                    attempt=attempt, provider_usage=None,
                ),
                "CAMPAIGN_CONSERVATIVE_USAGE_DEBIT_INVALID",
            )
        else:
            raise FullShortExecutionBoundaryError(
                "CAMPAIGN_ACCOUNTED_USAGE_BASIS_INVALID"
            )
        if capture_store is not None:
            matches = [
                item for item in audited
                if item.get("byte_domain") == PROVIDER_PROTOCOL_INPUT_BYTES
                and item.get("execution_id") == sealed.get("execution_id")
                and item.get("call_id")
                == f"{sealed.get('execution_id')}:{expected_ordinal}"
                and item.get("ledger_receipt_sha256")
                == attempt.get("provider_protocol_capture_receipt_sha256")
            ]
            _require(
                len(matches) == 1,
                "PROVIDER_REPORTED_USAGE_CAPTURE_IDENTITY_NOT_EXACT",
            )
            data, metadata = capture_store.replay(
                byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
                expected_metadata=matches[0]["metadata"],
                expected_receipt_sha256=str(
                    attempt["provider_protocol_capture_receipt_sha256"]
                ),
            )
            if basis == "PROVIDER_REPORTED_ACTUAL":
                extracted = extract_provider_reported_actual_usage_v1(
                    data, protocol=str(metadata["protocol"]),
                    content_type=str(metadata["content_type"]),
                    encoding=str(metadata["encoding"]),
                )
                _require(
                    extracted == provider_usage,
                    "PROVIDER_REPORTED_USAGE_CAPTURE_MISMATCH",
                )
            elif (
                metadata.get("transport_complete") is True
                and metadata.get("http_success") is True
            ):
                try:
                    extract_provider_reported_actual_usage_v1(
                        data, protocol=str(metadata["protocol"]),
                        content_type=str(metadata["content_type"]),
                        encoding=str(metadata["encoding"]),
                    )
                except ProviderResponseCaptureError as exc:
                    _require(
                        str(exc) in {
                            "PROVIDER_REPORTED_USAGE_MISSING",
                            "PROVIDER_REPORTED_USAGE_INCOMPLETE",
                            "PROVIDER_REPORTED_USAGE_NOT_POSITIVE",
                        },
                        "CAMPAIGN_CONSERVATIVE_USAGE_SOURCE_INVALID",
                    )
                else:
                    raise FullShortExecutionBoundaryError(
                        "CAMPAIGN_CONSERVATIVE_USAGE_WHEN_ACTUAL_AVAILABLE"
                    )
        input_total += int(accounted_usage.get("input_tokens") or 0)
        output_total += int(accounted_usage.get("output_tokens") or 0)
        expected_receipt = _attempt_actual_usage_receipt_v1(
            attempt=attempt, accounted_usage=accounted_usage, guard=guard,
            full_short_input_tokens=input_total,
            full_short_output_tokens=output_total,
        )
        _require(
            attempt.get("attempt_usage_receipt_sha256")
            == expected_receipt["attempt_usage_receipt_sha256"],
            "OUTER_CAMPAIGN_ATTEMPT_USAGE_RECEIPT_MISMATCH",
        )
        if provider_sha256 is not None:
            provider_receipts.append(str(provider_sha256))
        accounted_debits.append(str(accounted_sha256))
        attempt_receipts.append(str(
            expected_receipt["attempt_usage_receipt_sha256"]
        ))
    body = {
        "schema": "FullShortVerifiedActualUsageV1",
        "version": 1,
        "outer_campaign_usage_guard_sha256": guard["guard_sha256"],
        "prior_provider_request_count": guard[
            "prior_provider_request_count"
        ],
        "prior_input_tokens": guard["prior_input_tokens"],
        "prior_output_tokens": guard["prior_output_tokens"],
        "full_short_provider_request_count": len(attempts),
        "full_short_input_tokens": input_total,
        "full_short_output_tokens": output_total,
        "provider_reported_actual_complete": (
            provider_reported_actual_complete
        ),
        "campaign_cumulative_provider_request_count": (
            guard["prior_provider_request_count"] + len(attempts)
        ),
        "campaign_cumulative_input_tokens": (
            guard["prior_input_tokens"] + input_total
        ),
        "campaign_cumulative_output_tokens": (
            guard["prior_output_tokens"] + output_total
        ),
        "remaining_provider_requests": (
            guard["remaining_provider_requests"] - len(attempts)
        ),
        "remaining_input_tokens": (
            guard["remaining_input_tokens"] - input_total
        ),
        "remaining_output_tokens": (
            guard["remaining_output_tokens"] - output_total
        ),
        "provider_usage_receipt_sha256s": provider_receipts,
        "accounted_usage_debit_sha256s": accounted_debits,
        "attempt_usage_receipt_sha256s": attempt_receipts,
    }
    _require(
        body["remaining_provider_requests"] >= 0
        and body["remaining_input_tokens"] >= 0
        and body["remaining_output_tokens"] >= 0,
        "OUTER_CAMPAIGN_ACTUAL_USAGE_CAP_EXCEEDED",
    )
    return {
        **body,
        "verified_usage_sha256": domain_sha256(
            "novel-flywheel-full-short-verified-actual-usage-v1", body,
        ),
    }


def _validate_dispatch_readiness_v1(
    readiness: Mapping[str, Any], *, execution_id: str,
    policy: Mapping[str, Any], session_sha256: str,
    ledger: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one closed, non-secret readiness receipt before nonce write."""

    _require(isinstance(readiness, Mapping), "DISPATCH_READINESS_SCHEMA_INVALID")
    body = deepcopy(dict(readiness))
    _require(
        set(body) == _DISPATCH_READINESS_FIELDS_V1,
        "DISPATCH_READINESS_SCHEMA_INVALID",
    )
    _require(
        body.get("schema") == DISPATCH_READINESS_SCHEMA
        and type(body.get("version")) is int
        and body["version"] == 1,
        "DISPATCH_READINESS_SCHEMA_INVALID",
    )
    _require(
        all(
            isinstance(body.get(field), str)
            and _HEX64.fullmatch(body[field]) is not None
            for field in _DISPATCH_READINESS_HASH_FIELDS_V1
        ),
        "DISPATCH_READINESS_HASH_TYPE_INVALID",
    )
    _require(
        isinstance(body.get("execution_id"), str)
        and _ID.fullmatch(body["execution_id"]) is not None
        and isinstance(body.get("logical_stage_id"), str)
        and _ID.fullmatch(body["logical_stage_id"]) is not None
        and isinstance(body.get("physical_attempt_id"), str)
        and _ID.fullmatch(body["physical_attempt_id"]) is not None,
        "DISPATCH_READINESS_ID_TYPE_INVALID",
    )
    integer_fields = (
        _DISPATCH_READINESS_CAP_FIELDS_V1
        | _DISPATCH_READINESS_COUNTER_FIELDS_V1
        | {
            "requested_output_tokens", "total_requested_output_tokens",
            "global_physical_attempt_ordinal",
        }
    )
    _require(
        all(type(body.get(field)) is int for field in integer_fields),
        "DISPATCH_READINESS_COUNTER_TYPE_INVALID",
    )
    _require(
        body["execution_id"] == execution_id,
        "DISPATCH_READINESS_EXECUTION_MISMATCH",
    )
    _require(
        body["policy_sha256"] == policy.get("policy_sha256")
        and body["logical_stage_plan_sha256"]
        == policy.get("logical_stage_plan_sha256")
        and body["capacity_policy_registry_sha256"]
        == policy.get("capacity_policy_registry_sha256")
        and body.get("capacity_admission_status") == "PASS",
        "DISPATCH_READINESS_POLICY_MISMATCH",
    )
    _require(
        body["observer_session_sha256"] == session_sha256
        and ledger.get("observer_session_sha256") == session_sha256,
        "DISPATCH_READINESS_SESSION_MISMATCH",
    )
    _require(
        body["predispatch_ledger_sha256"] == ledger.get("ledger_sha256")
        and body["permission_sha256"] == ledger.get("permission_sha256")
        and body["signed_approval_sha256"]
        == ledger.get("signed_approval_sha256"),
        "DISPATCH_READINESS_LEDGER_MISMATCH",
    )
    expected_caps = {
        field: policy.get(field) for field in _DISPATCH_READINESS_CAP_FIELDS_V1
    }
    _require(
        all(body[field] == expected_caps[field]
            for field in _DISPATCH_READINESS_CAP_FIELDS_V1),
        "DISPATCH_READINESS_CAP_MISMATCH",
    )
    attempts = list(ledger.get("attempts") or [])
    receipts = list(ledger.get("completed_stage_receipts") or [])
    expected_counters = {
        "provider_request_count_before_commit": len(attempts),
        "http_post_count_before_commit": len(attempts),
        "network_request_count_before_commit": len(attempts),
        "provider_response_count_before_commit": sum(
            1 for item in attempts
            if item.get("response_status_sha256") is not None
        ),
        "completed_stage_count_before_commit": len(receipts),
    }
    _require(
        all(body[field] == expected_counters[field]
            for field in _DISPATCH_READINESS_COUNTER_FIELDS_V1),
        "DISPATCH_READINESS_COUNTER_MISMATCH",
    )
    _require(not attempts and not receipts, "DISPATCH_READINESS_COUNTER_MISMATCH")
    logical_stage_plan = list(policy.get("logical_stage_plan") or [])
    _require(bool(logical_stage_plan), "DISPATCH_READINESS_POLICY_MISMATCH")
    expected_stage = logical_stage_plan[0]
    expected_physical_attempt_id = "physical-" + domain_sha256(
        "novel-flywheel-full-short-physical-attempt-id-v1",
        {
            "execution_id": execution_id,
            "logical_stage_id": expected_stage.get("logical_stage_id"),
            "ordinal": 1,
        },
    )[:32]
    _require(
        body["logical_stage_id"] == expected_stage.get("logical_stage_id")
        and body["physical_attempt_id"] == expected_physical_attempt_id,
        "DISPATCH_READINESS_STAGE_MISMATCH",
    )
    _require(
        body["global_physical_attempt_ordinal"] == 1,
        "DISPATCH_READINESS_STAGE_MISMATCH",
    )
    _require(
        body["requested_output_tokens"]
        == expected_stage.get("requested_output_tokens")
        and body["total_requested_output_tokens"]
        == body["requested_output_tokens"]
        and 0 < body["requested_output_tokens"]
        <= body["per_call_output_token_hard_cap"]
        and body["total_requested_output_tokens"]
        <= body["total_output_token_hard_cap"],
        "DISPATCH_READINESS_TOKEN_BUDGET_MISMATCH",
    )
    return body


_LEDGER_STATE_TRANSITIONS_V1: dict[str, frozenset[str]] = {
    "DISPATCH_IN_FLIGHT": frozenset({
        "DISPATCH_IN_FLIGHT",
        "RESPONSE_RECEIVED_AWAITING_LOCAL_RECEIPT",
        "RECONCILIATION_REQUIRED_NO_REDISPATCH",
    }),
    "RESPONSE_RECEIVED_AWAITING_LOCAL_RECEIPT": frozenset({
        "RESPONSE_RECEIVED_AWAITING_LOCAL_RECEIPT",
        "READY_FOR_NEXT_STAGE", "READY_FOR_RECOVERY_ATTEMPT",
        "RECONCILIATION_REQUIRED_NO_REDISPATCH",
    }),
    "RECONCILIATION_REQUIRED_NO_REDISPATCH": frozenset({
        "RECONCILIATION_REQUIRED_NO_REDISPATCH",
    }),
    "READY_FOR_NEXT_STAGE": frozenset({"READY_FOR_NEXT_STAGE"}),
    "READY_FOR_RECOVERY_ATTEMPT": frozenset({"READY_FOR_RECOVERY_ATTEMPT"}),
}
_ATTEMPT_STATE_TRANSITIONS_V1: dict[str, frozenset[str]] = {
    "DISPATCH_ATTEMPTED": frozenset({
        "DISPATCH_ATTEMPTED", "RESPONSE_RECEIVED",
        "HTTP_RESPONSE_FAILED_CLOSED", "OUTCOME_UNKNOWN_FAIL_CLOSED",
        "POST_CAPTURE_TERMINAL_CLASSIFICATION_PENDING",
        "POST_CAPTURE_TERMINAL_FAILED_CLOSED",
    }),
    "RESPONSE_RECEIVED": frozenset({
        "RESPONSE_RECEIVED", "LOCAL_STAGE_COMPLETE",
        "LOCAL_ATTEMPT_REJECTED", "POST_CAPTURE_TERMINAL_FAILED_CLOSED",
    }),
    "HTTP_RESPONSE_FAILED_CLOSED": frozenset({"HTTP_RESPONSE_FAILED_CLOSED"}),
    "OUTCOME_UNKNOWN_FAIL_CLOSED": frozenset({"OUTCOME_UNKNOWN_FAIL_CLOSED"}),
    "POST_CAPTURE_TERMINAL_FAILED_CLOSED": frozenset({
        "POST_CAPTURE_TERMINAL_FAILED_CLOSED",
    }),
    "POST_CAPTURE_TERMINAL_CLASSIFICATION_PENDING": frozenset({
        "POST_CAPTURE_TERMINAL_CLASSIFICATION_PENDING",
        "POST_CAPTURE_TERMINAL_FAILED_CLOSED",
    }),
    "LOCAL_STAGE_COMPLETE": frozenset({"LOCAL_STAGE_COMPLETE"}),
    "LOCAL_ATTEMPT_REJECTED": frozenset({"LOCAL_ATTEMPT_REJECTED"}),
}
_CLOSED_ATTEMPT_STATES_V1 = frozenset({
    state for state, next_states in _ATTEMPT_STATE_TRANSITIONS_V1.items()
    if next_states == frozenset({state})
})
_CAPTURE_RECONCILIATION_FIELD_PAIRS_V1 = (
    (
        "provider_protocol_capture_receipt_sha256",
        "provider_protocol_capture_transport_complete",
    ),
    (
        "contract_runtime_capture_receipt_sha256",
        "contract_runtime_capture_transport_complete",
    ),
)
_MUTABLE_ATTEMPT_FIELDS_V1 = frozenset({
    "state", "response_status_sha256", "response_received_at",
    "provider_protocol_capture_receipt_sha256",
    "provider_protocol_capture_transport_complete",
    "provider_protocol_capture_http_success",
    "contract_runtime_capture_receipt_sha256",
    "contract_runtime_capture_transport_complete",
    "failure_kind_sha256", "adapter_failure_kind_sha256", "failure_class",
    "terminal_contract_attempt_index", "terminal_contract_route",
    "terminal_contract_route_attempt", "terminal_closed_at",
    "local_rejection_receipt_sha256", "local_rejection_failure_kind",
    "local_rejection_failure_code", "local_rejection_schema",
    "local_rejection_physical_ordinal", "local_rejection_logical_stage_id",
    "local_rejection_failure_reason_sha256", "local_rejection_stage",
    "local_stage_receipt_sha256", "output_sha256", "role",
    "contract_name", "contract_version", "contract_schema_sha256",
    "provider_reported_actual_usage", "campaign_accounted_usage",
    "attempt_usage_receipt_sha256",
})


def _validate_ledger_mutation_v1(
    before: Mapping[str, Any], after: Mapping[str, Any], *,
    mutation_kind: str = "ORDINARY",
) -> None:
    """Reject every unregistered durable transition before resealing."""

    _require(
        mutation_kind in {"ORDINARY", "CAPTURE_RECEIPT_RECONCILIATION"},
        "LEDGER_MUTATION_KIND_INVALID",
    )

    before_root = {
        key: value for key, value in before.items()
        if key not in {"state", "attempts", "completed_stage_receipts", "updated_at"}
    }
    after_root = {
        key: value for key, value in after.items()
        if key not in {"state", "attempts", "completed_stage_receipts", "updated_at"}
    }
    _require(before_root == after_root, "LEDGER_AUTHORITY_FIELDS_IMMUTABLE")
    before_state = str(before.get("state") or "")
    after_state = str(after.get("state") or "")
    _require(
        after_state in _LEDGER_STATE_TRANSITIONS_V1.get(before_state, frozenset()),
        "ILLEGAL_LEDGER_STATE_TRANSITION",
    )
    before_attempts = list(before.get("attempts") or [])
    after_attempts = list(after.get("attempts") or [])
    _require(
        len(before_attempts) == len(after_attempts),
        "LEDGER_ATTEMPT_CARDINALITY_IMMUTABLE",
    )
    changed_attempts: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    closed_attempt_rewritten = False
    for previous, current in zip(before_attempts, after_attempts, strict=True):
        previous_identity = {
            key: value for key, value in dict(previous).items()
            if key not in _MUTABLE_ATTEMPT_FIELDS_V1
        }
        current_identity = {
            key: value for key, value in dict(current).items()
            if key not in _MUTABLE_ATTEMPT_FIELDS_V1
        }
        _require(
            previous_identity == current_identity,
            "LEDGER_ATTEMPT_IDENTITY_IMMUTABLE",
        )
        previous_state = str(previous.get("state") or "")
        current_state = str(current.get("state") or "")
        _require(
            current_state in _ATTEMPT_STATE_TRANSITIONS_V1.get(
                previous_state, frozenset(),
            ),
            "ILLEGAL_ATTEMPT_STATE_TRANSITION",
        )
        if dict(previous) != dict(current):
            changed_attempts.append((previous, current))
        if (
            mutation_kind == "ORDINARY"
            and previous_state in _CLOSED_ATTEMPT_STATES_V1
            and current_state == previous_state
        ):
            closed_attempt_rewritten = (
                closed_attempt_rewritten
                or dict(previous) != dict(current)
            )
    before_receipts = list(before.get("completed_stage_receipts") or [])
    after_receipts = list(after.get("completed_stage_receipts") or [])
    _require(
        after_receipts[:len(before_receipts)] == before_receipts
        and len(after_receipts) - len(before_receipts) in {0, 1},
        "LEDGER_STAGE_RECEIPT_APPEND_ONLY",
    )
    if len(after_receipts) == len(before_receipts) + 1:
        _require(
            any(
                old.get("state") == "RESPONSE_RECEIVED"
                and new.get("state") == "LOCAL_STAGE_COMPLETE"
                for old, new in zip(before_attempts, after_attempts, strict=True)
            ),
            "LEDGER_STAGE_RECEIPT_WITHOUT_ACCEPTANCE_TRANSITION",
        )
    if mutation_kind == "ORDINARY":
        _require(
            not closed_attempt_rewritten,
            "CLOSED_ATTEMPT_IMMUTABLE",
        )
    if mutation_kind == "CAPTURE_RECEIPT_RECONCILIATION":
        _require(
            before_receipts == after_receipts
            and len(changed_attempts) == 1,
            "CAPTURE_RECONCILIATION_NOT_NARROW",
        )
        previous, current = changed_attempts[0]
        changed_fields = {
            key for key in set(previous) | set(current)
            if previous.get(key) != current.get(key)
        }
        provider_fields = {
            "provider_protocol_capture_receipt_sha256",
            "provider_protocol_capture_transport_complete",
            "provider_protocol_capture_http_success",
            "response_status_sha256",
            "state",
        }
        if current.get("provider_protocol_capture_http_success") is True:
            provider_fields.add("response_received_at")
        allowed_provider = bool(
            changed_fields == provider_fields
            and before_state == "DISPATCH_IN_FLIGHT"
            and after_state == (
                "RESPONSE_RECEIVED_AWAITING_LOCAL_RECEIPT"
                if current.get("provider_protocol_capture_http_success") is True
                else "RECONCILIATION_REQUIRED_NO_REDISPATCH"
            )
            and previous.get("state") == "DISPATCH_ATTEMPTED"
            and current.get("state") == (
                "RESPONSE_RECEIVED"
                if current.get("provider_protocol_capture_http_success") is True
                else "HTTP_RESPONSE_FAILED_CLOSED"
            )
            and previous.get("provider_protocol_capture_receipt_sha256") is None
            and previous.get("provider_protocol_capture_transport_complete") is None
            and previous.get("provider_protocol_capture_http_success") is None
            and previous.get("response_status_sha256") is None
            and isinstance(
                current.get("provider_protocol_capture_receipt_sha256"), str,
            )
            and _HEX64.fullmatch(
                current["provider_protocol_capture_receipt_sha256"]
            ) is not None
            and current.get("provider_protocol_capture_transport_complete") is True
            and type(current.get("provider_protocol_capture_http_success")) is bool
            and _HEX64.fullmatch(
                str(current.get("response_status_sha256") or "")
            ) is not None
            and (
                current.get("provider_protocol_capture_http_success") is False
                or isinstance(current.get("response_received_at"), str)
            )
        )
        allowed_contract = bool(
            before_state == after_state
            and changed_fields == {
                "contract_runtime_capture_receipt_sha256",
                "contract_runtime_capture_transport_complete",
            }
            and previous.get("contract_runtime_capture_receipt_sha256") is None
            and previous.get("contract_runtime_capture_transport_complete") is None
            and isinstance(
                current.get("contract_runtime_capture_receipt_sha256"), str,
            )
            and _HEX64.fullmatch(
                current["contract_runtime_capture_receipt_sha256"]
            ) is not None
            and current.get("contract_runtime_capture_transport_complete") is True
        )
        allowed_closed_receipt = False
        for receipt_field, complete_field in (
            _CAPTURE_RECONCILIATION_FIELD_PAIRS_V1
        ):
            allowed_closed_receipt = allowed_closed_receipt or bool(
                before_state == after_state
                and previous.get("state") in _CLOSED_ATTEMPT_STATES_V1
                and current.get("state") == previous.get("state")
                and changed_fields == {receipt_field, complete_field}
                and previous.get(receipt_field) is None
                and previous.get(complete_field) is None
                and isinstance(current.get(receipt_field), str)
                and _HEX64.fullmatch(current[receipt_field]) is not None
                and current.get(complete_field) is True
            )
        allowed = (
            allowed_provider or allowed_contract or allowed_closed_receipt
        )
        _require(allowed, "CAPTURE_RECONCILIATION_NOT_NARROW")


def _expected_provider_payload_v1(
    protocol: str, request: ModelRequest, *, destination: str,
) -> dict[str, Any]:
    """Project one typed model request into the exact adapter wire payload."""

    if protocol == "anthropic":
        return anthropic_payload_v1(request)
    if protocol == "openai-chat":
        payload = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema", "json_schema": request.response_schema,
            }
        elif request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        if request.tools:
            payload["tools"] = [{"type": "function", "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            }} for tool in request.tools]
        if request.required_tool:
            payload["tool_choice"] = {
                "type": "function",
                "function": {"name": request.required_tool},
            }
        if urlsplit(destination).hostname == "api.moonshot.cn" and (
            request.required_tool
            or request.response_schema
            or request.response_format
        ):
            payload["thinking"] = {"type": "disabled"}
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        return payload
    if protocol == "openai-responses":
        payload = {
            "model": request.model,
            "input": [message.model_dump() for message in request.messages],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_output_tokens"] = request.max_output_tokens
        if request.response_schema is not None:
            payload["text"] = {
                "format": {"type": "json_schema", **request.response_schema},
            }
        elif request.response_format == "json_object":
            payload["text"] = {"format": {"type": "json_object"}}
        if request.tools:
            payload["tools"] = [{
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            } for tool in request.tools]
        if request.required_tool:
            payload["tool_choice"] = {
                "type": "function", "name": request.required_tool,
            }
        payload["stream"] = True
        return payload
    raise FullShortExecutionBoundaryError("EGRESS_PROTOCOL_NOT_AUTHORIZED")


def _seal(domain: str, body: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {**deepcopy(dict(body)), field: domain_sha256(domain, body)}


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def full_short_logical_stage_id_v1(stage_id: str, occurrence: int) -> str:
    """Return the canonical identity for one ordered logical-stage occurrence."""

    _require(_ID.fullmatch(stage_id) is not None, "LOGICAL_STAGE_BASE_ID_INVALID")
    _require(type(occurrence) is int and occurrence > 0,
             "LOGICAL_STAGE_OCCURRENCE_INVALID")
    if occurrence == 1:
        return stage_id
    digest = hashlib.sha256(stage_id.encode("utf-8")).hexdigest()[:8]
    suffix = f".{occurrence}.{digest}"
    return f"{stage_id[:160 - len(suffix)]}{suffix}"


def validate_full_short_logical_stage_plan_v1(value: Any) -> list[dict[str, Any]]:
    """Validate the exact ordered logical plan authorized for one Full Short."""

    _require(isinstance(value, (list, tuple)) and bool(value),
             "LOGICAL_STAGE_PLAN_INVALID")
    plan: list[dict[str, Any]] = []
    occurrences: dict[str, int] = {}
    for expected_ordinal, raw in enumerate(value, 1):
        _require(isinstance(raw, Mapping), "LOGICAL_STAGE_PLAN_INVALID")
        item = dict(raw)
        _require(set(item) == _LOGICAL_STAGE_PLAN_KEYS,
                 "LOGICAL_STAGE_PLAN_KEYS_INVALID")
        _require(item.get("ordinal") == expected_ordinal,
                 "LOGICAL_STAGE_PLAN_ORDER_INVALID")
        stage_id = str(item.get("stage_id") or "")
        base_id = str(item.get("logical_stage_base_id") or "")
        _require(stage_id == base_id and _ID.fullmatch(base_id) is not None,
                 "LOGICAL_STAGE_PLAN_STAGE_INVALID")
        occurrences[base_id] = occurrences.get(base_id, 0) + 1
        _require(
            item.get("logical_stage_id") == full_short_logical_stage_id_v1(
                base_id, occurrences[base_id],
            ),
            "LOGICAL_STAGE_PLAN_IDENTITY_INVALID",
        )
        _require(_ID.fullmatch(str(item.get("role") or "")) is not None,
                 "LOGICAL_STAGE_PLAN_ROLE_INVALID")
        _require(
            item.get("route_lane") in {"primary", "configured_fallback"},
            "LOGICAL_STAGE_PLAN_ROUTE_LANE_INVALID",
        )
        _require(isinstance(item.get("contract_name"), str)
                 and bool(item["contract_name"]),
                 "LOGICAL_STAGE_PLAN_CONTRACT_INVALID")
        _require(type(item.get("contract_version")) is int
                 and int(item["contract_version"]) > 0,
                 "LOGICAL_STAGE_PLAN_CONTRACT_INVALID")
        _require(_HEX64.fullmatch(str(item.get("contract_schema_sha256")))
                 is not None, "LOGICAL_STAGE_PLAN_CONTRACT_INVALID")
        _require(type(item.get("contract_runtime_input_required")) is bool,
                 "LOGICAL_STAGE_PLAN_CONTRACT_INVALID")
        _require(type(item.get("requested_output_tokens")) is int
                 and int(item["requested_output_tokens"]) > 0,
                 "LOGICAL_STAGE_PLAN_OUTPUT_CAP_INVALID")
        plan.append(deepcopy(item))
    _require(len({item["logical_stage_id"] for item in plan}) == len(plan),
             "LOGICAL_STAGE_PLAN_IDENTITY_DUPLICATE")
    return plan


def full_short_logical_stage_plan_sha256_v1(value: Any) -> str:
    return domain_sha256(
        "novel-flywheel-full-short-logical-stage-plan-v1",
        validate_full_short_logical_stage_plan_v1(value),
    )


def full_short_workload_request_family_id_v1(
    value: Mapping[str, Any],
) -> str:
    """Return one of the eight closed-world provider workload partitions."""

    item = dict(value)
    _require(
        set(item) == _LOGICAL_STAGE_PLAN_KEYS,
        "WORKLOAD_REQUEST_FAMILY_KEYS_INVALID",
    )
    _require(
        _ID.fullmatch(str(item.get("stage_id") or "")) is not None
        and item.get("logical_stage_base_id") == item.get("stage_id")
        and _ID.fullmatch(str(item.get("role") or "")) is not None
        and item.get("route_lane") in {
            "primary", "configured_fallback",
        }
        and isinstance(item.get("contract_name"), str)
        and bool(item["contract_name"])
        and type(item.get("contract_version")) is int
        and item["contract_version"] > 0
        and _HEX64.fullmatch(
            str(item.get("contract_schema_sha256") or "")
        ) is not None
        and type(item.get("contract_runtime_input_required")) is bool
        and type(item.get("requested_output_tokens")) is int
        and item["requested_output_tokens"] > 0,
        "WORKLOAD_REQUEST_FAMILY_INVALID",
    )
    stage_id = str(item["stage_id"])
    role = str(item["role"])
    contract_name = str(item["contract_name"])
    structured = item["contract_runtime_input_required"]
    family_id: str | None = None
    if role == "draft" and stage_id.startswith("draft-part-") and not structured:
        family_id = "draft_plain"
    elif (
        role == "polish"
        and stage_id.startswith("polish-part-")
        and not structured
    ):
        family_id = "polish_plain"
    elif (
        role == "planning"
        and stage_id.startswith("planning-adaptation-segment-")
        and structured
        and contract_name == "planning_event_realizations"
    ):
        family_id = "planning_adaptation"
    elif (
        role == "planning"
        and stage_id.startswith("planning-causal-chain-packet-")
        and structured
        and contract_name == "short_causal_chain"
    ):
        family_id = "causal_chain"
    elif (
        role == "planning"
        and stage_id.startswith("planning-execution-segment-")
        and structured
        and contract_name == "execution_manifest"
    ):
        family_id = "execution_manifest"
    elif (
        role == "final_review"
        and stage_id.startswith("final_review-window-")
        and structured
        and contract_name == "final_review_window"
    ):
        family_id = "final_review_window"
    elif (
        role == "final_review"
        and stage_id == "final_review-adjudication"
        and structured
        and contract_name == "full_short_final_review"
    ):
        family_id = "final_review_adjudication"
    elif (
        role == "maintenance"
        and stage_id.startswith("maintenance-map-")
        and not structured
    ):
        family_id = "maintenance_plain"
    _require(family_id is not None, "WORKLOAD_REQUEST_FAMILY_UNKNOWN")
    return family_id


def full_short_workload_request_family_sha256_v1(
    value: Mapping[str, Any],
    *,
    provider: str,
    operator: str,
    destination: str,
    protocol: str,
    model: str,
    route_fingerprint_sha256: str,
) -> str:
    """Bind evidence to an exact route and one of eight workload families.

    Raw stage/occurrence identity and token sizes are deliberately excluded.
    Plain-text draft, polish, and maintenance calls also exclude their dynamic
    contract labels and schema placeholders.  Structured families retain the
    exact provider-visible contract version and schema.
    """

    item = dict(value)
    family_id = full_short_workload_request_family_id_v1(item)
    structured = item["contract_runtime_input_required"]
    return full_short_workload_partition_sha256_v1(
        family_id=family_id,
        provider=provider,
        operator=operator,
        destination=destination,
        protocol=protocol,
        model=model,
        route_fingerprint_sha256=route_fingerprint_sha256,
        contract_name=item["contract_name"] if structured else None,
        contract_version=item["contract_version"] if structured else None,
        contract_schema_sha256=(
            item["contract_schema_sha256"] if structured else None
        ),
    )


def full_short_workload_partition_sha256_v1(
    *,
    family_id: str,
    provider: str,
    operator: str,
    destination: str,
    protocol: str,
    model: str,
    route_fingerprint_sha256: str,
    contract_name: str | None = None,
    contract_version: int | None = None,
    contract_schema_sha256: str | None = None,
) -> str:
    """Hash the shared eight-probe/runtime workload partition contract."""

    structured_contracts = {
        "planning_adaptation": "planning_event_realizations",
        "causal_chain": "short_causal_chain",
        "execution_manifest": "execution_manifest",
        "final_review_window": "final_review_window",
        "final_review_adjudication": "full_short_final_review",
    }
    plain_families = {"draft_plain", "polish_plain", "maintenance_plain"}
    _require(
        family_id in plain_families or family_id in structured_contracts,
        "WORKLOAD_REQUEST_FAMILY_UNKNOWN",
    )
    route = {
        "provider": provider,
        "operator": operator,
        "destination": destination,
        "protocol": protocol,
        "model": model,
        "route_fingerprint_sha256": route_fingerprint_sha256,
    }
    _require(
        all(
            isinstance(route[field], str)
            and bool(route[field])
            and route[field].strip() == route[field]
            for field in (
                "provider", "operator", "destination", "protocol", "model",
            )
        )
        and _HEX64.fullmatch(route_fingerprint_sha256) is not None,
        "WORKLOAD_REQUEST_FAMILY_ROUTE_INVALID",
    )
    request_partition: dict[str, Any] = {"family_id": family_id}
    if family_id in structured_contracts:
        _require(
            contract_name == structured_contracts[family_id]
            and type(contract_version) is int
            and contract_version > 0
            and isinstance(contract_schema_sha256, str)
            and _HEX64.fullmatch(contract_schema_sha256) is not None,
            "WORKLOAD_REQUEST_FAMILY_STRUCTURED_CONTRACT_INVALID",
        )
        request_partition["structured_contract"] = {
            "name": contract_name,
            "version": contract_version,
            "schema_sha256": contract_schema_sha256,
        }
    else:
        _require(
            contract_name is None
            and contract_version is None
            and contract_schema_sha256 is None,
            "WORKLOAD_REQUEST_FAMILY_PLAIN_CONTRACT_INVALID",
        )
    return domain_sha256(
        "novel-flywheel-full-short-workload-request-family-v1",
        {
            "route": route,
            "request_partition": request_partition,
        },
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


class _ExclusiveFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "_ExclusiveFileLock":
        self.path.touch(exist_ok=True)
        self.handle = self.path.open("r+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.handle.close()
            self.handle = None
            raise FullShortExecutionBoundaryError(
                "FULL_SHORT_STORE_CONCURRENT_ACCESS",
            ) from exc
        return self

    def __exit__(self, *_args: object) -> None:
        assert self.handle is not None
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


@dataclass(frozen=True)
class FullShortExecutionPolicyV1:
    execution_head: str
    branch: str
    run_id: str
    project_id_sha256: str
    workload_sha256: str
    runtime_authority_sha256: str
    style_reference_authority_sha256: str
    route_manifest_sha256: str
    destination_manifest_sha256: str
    egress_policy_sha256: str
    store_root_sha256: str
    capture_attestation_public_key: str
    capture_attestation_public_key_sha256: str
    required_stage_roles: tuple[str, ...]
    logical_stage_plan: tuple[Mapping[str, Any], ...]
    expected_stage_calls: int
    hard_max_provider_requests: int
    hard_max_http_posts: int
    hard_max_network_attempts: int
    per_call_output_token_hard_cap: int
    total_output_token_hard_cap: int
    maximum_elapsed_seconds: int
    response_capture_policy_sha256: str = RESPONSE_CAPTURE_POLICY_SHA256
    monetary_cost_cap_state: str = "UNKNOWN_NOT_SEALED"
    logical_stage_recovery_policy_sha256: str = (
        LOGICAL_STAGE_RECOVERY_POLICY_SHA256
    )
    failure_architecture_identity: str = FAILURE_ARCHITECTURE_IDENTITY

    def document(self) -> dict[str, Any]:
        logical_stage_plan = validate_full_short_logical_stage_plan_v1(
            self.logical_stage_plan,
        )
        body = {
            "schema": POLICY_SCHEMA,
            "version": 1,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "policy_version": POLICY_VERSION,
            "execution_head": self.execution_head,
            "branch": self.branch,
            "run_id": self.run_id,
            "project_id_sha256": self.project_id_sha256,
            "workload_sha256": self.workload_sha256,
            "runtime_authority_sha256": self.runtime_authority_sha256,
            "style_reference_authority_sha256": (
                self.style_reference_authority_sha256
            ),
            "route_manifest_sha256": self.route_manifest_sha256,
            "destination_manifest_sha256": self.destination_manifest_sha256,
            "egress_policy_sha256": self.egress_policy_sha256,
            "response_capture_policy_sha256": (
                self.response_capture_policy_sha256
            ),
            "capacity_policy_registry_sha256": (
                DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
            ),
            "store_root_sha256": self.store_root_sha256,
            "capture_attestation_scheme": "ED25519_CAPTURE_ANCHOR_V1",
            "capture_attestation_public_key": (
                self.capture_attestation_public_key
            ),
            "capture_attestation_public_key_sha256": (
                self.capture_attestation_public_key_sha256
            ),
            "required_stage_roles": list(self.required_stage_roles),
            "logical_stage_plan": logical_stage_plan,
            "logical_stage_plan_sha256": (
                full_short_logical_stage_plan_sha256_v1(logical_stage_plan)
            ),
            "transport_recovery_policy": deepcopy(
                TRANSPORT_RECOVERY_POLICY_V1,
            ),
            "transport_recovery_policy_sha256": (
                TRANSPORT_RECOVERY_POLICY_SHA256
            ),
            "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
            "logical_stage_recovery_policy": deepcopy(
                LOGICAL_STAGE_RECOVERY_POLICY_V1,
            ),
            "logical_stage_recovery_policy_sha256": (
                self.logical_stage_recovery_policy_sha256
            ),
            "logical_stage_recovery_policy_identity": (
                "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY"
            ),
            "failure_architecture_identity": self.failure_architecture_identity,
            "recovery_policy_registry": deepcopy(
                FULL_SHORT_EXACT_RECOVERY_REGISTRY_V1
            ),
            "recovery_policy_registry_sha256": (
                FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256
            ),
            "predispatch_state_machine": deepcopy(PREDISPATCH_STATE_MACHINE_V1),
            "predispatch_state_machine_sha256": PREDISPATCH_STATE_MACHINE_SHA256,
            "nonce_reservation_policy": deepcopy(NONCE_RESERVATION_POLICY_V1),
            "nonce_reservation_policy_sha256": NONCE_RESERVATION_POLICY_SHA256,
            "observer_isolation_policy": deepcopy(OBSERVER_ISOLATION_POLICY_V1),
            "observer_isolation_policy_sha256": OBSERVER_ISOLATION_POLICY_SHA256,
            "durable_failure_evidence_policy": deepcopy(
                DURABLE_FAILURE_EVIDENCE_POLICY_V1
            ),
            "durable_failure_evidence_policy_sha256": (
                DURABLE_FAILURE_EVIDENCE_POLICY_SHA256
            ),
            "max_physical_attempts_per_logical_stage": 2,
            "max_reasoning_only_recovery_dispatches_per_logical_stage": 1,
            "expected_stage_calls": self.expected_stage_calls,
            "hard_max_provider_requests": self.hard_max_provider_requests,
            "hard_max_http_posts": self.hard_max_http_posts,
            "hard_max_network_attempts": self.hard_max_network_attempts,
            "per_call_output_token_hard_cap": (
                self.per_call_output_token_hard_cap
            ),
            "total_output_token_hard_cap": self.total_output_token_hard_cap,
            "maximum_elapsed_seconds": self.maximum_elapsed_seconds,
            "monetary_cost_cap_state": self.monetary_cost_cap_state,
            "single_use": True,
            "retry_policy": "existing_workflow_bounds_only",
            "transport_retry_allowed": False,
            "ambiguous_dispatch_restart_policy": "FAIL_CLOSED_NO_REDISPATCH",
            "restart_policy": "FAIL_CLOSED_NO_RESUME_OR_REDISPATCH",
            "skill_v3_production_cutover": False,
            "planning_v2_production_cutover": False,
            "full_short_count": 1,
            "long_execution_allowed": False,
        }
        validate_policy_v1(body)
        return _seal(
            "novel-flywheel-full-short-execution-policy-v1",
            body, "policy_sha256",
        )


def render_full_short_canonical_authorization_v1(
    *, policy: Mapping[str, Any], public_bindings: Mapping[str, Any],
) -> bytes:
    """Render the only byte representation accepted by the real preflight.

    This is intentionally an authorization *template*.  Creating these bytes
    never activates external actions; a fresh user message must explicitly
    activate the exact SHA-256 after the final execution HEAD is frozen.
    """

    validated = validate_policy_v1(policy)
    _require(
        isinstance(public_bindings, Mapping) and bool(public_bindings),
        "AUTHORIZATION_BINDINGS_INVALID",
    )
    _require(
        public_bindings.get("store_root_sha256")
        == validated["store_root_sha256"],
        "AUTHORIZATION_STORE_ROOT_MISMATCH",
    )
    _require(
        _canonical_sha256(public_bindings.get("routes"))
        == validated["route_manifest_sha256"],
        "AUTHORIZATION_ROUTE_MANIFEST_MISMATCH",
    )
    _require(
        _canonical_sha256(public_bindings.get("destinations"))
        == validated["destination_manifest_sha256"],
        "AUTHORIZATION_DESTINATION_MANIFEST_MISMATCH",
    )
    _require(
        _canonical_sha256(public_bindings.get("egress_policy"))
        == validated["egress_policy_sha256"],
        "AUTHORIZATION_EGRESS_POLICY_MISMATCH",
    )
    _require(
        _canonical_sha256(public_bindings.get("response_capture_policy"))
        == validated["response_capture_policy_sha256"],
        "AUTHORIZATION_RESPONSE_CAPTURE_POLICY_MISMATCH",
    )
    _require(
        public_bindings.get("capture_attestation_scheme")
        == validated["capture_attestation_scheme"]
        and public_bindings.get("capture_attestation_public_key")
        == validated["capture_attestation_public_key"]
        and public_bindings.get("capture_attestation_public_key_sha256")
        == validated["capture_attestation_public_key_sha256"],
        "AUTHORIZATION_RESPONSE_CAPTURE_POLICY_MISMATCH",
    )
    _require(
        public_bindings.get("logical_stage_plan")
        == validated["logical_stage_plan"]
        and public_bindings.get("logical_stage_plan_sha256")
        == validated["logical_stage_plan_sha256"],
        "AUTHORIZATION_LOGICAL_STAGE_PLAN_MISMATCH",
    )
    _require(
        public_bindings.get("transport_recovery_policy")
        == validated["transport_recovery_policy"]
        and public_bindings.get("transport_recovery_policy_sha256")
        == validated["transport_recovery_policy_sha256"]
        and public_bindings.get("transport_recovery_policy_identity")
        == "EXACT_REPLAY_ONLY",
        "AUTHORIZATION_TRANSPORT_RECOVERY_POLICY_MISMATCH",
    )
    _require(
        public_bindings.get("logical_stage_recovery_policy")
        == validated["logical_stage_recovery_policy"]
        and public_bindings.get("logical_stage_recovery_policy_sha256")
        == validated["logical_stage_recovery_policy_sha256"]
        and public_bindings.get("logical_stage_recovery_policy_identity")
        == "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY",
        "AUTHORIZATION_LOGICAL_STAGE_RECOVERY_POLICY_MISMATCH",
    )
    for field in (
        "failure_architecture_identity", "recovery_policy_registry",
        "recovery_policy_registry_sha256", "predispatch_state_machine",
        "predispatch_state_machine_sha256", "nonce_reservation_policy",
        "nonce_reservation_policy_sha256", "observer_isolation_policy",
        "observer_isolation_policy_sha256",
        "durable_failure_evidence_policy",
        "durable_failure_evidence_policy_sha256",
        "capacity_policy_registry_sha256",
    ):
        _require(
            public_bindings.get(field) == validated.get(field),
            "AUTHORIZATION_FAILURE_ARCHITECTURE_BINDING_MISMATCH",
        )
    body = {
        "schema": AUTHORIZATION_SCHEMA,
        "version": 1,
        "activation_rule": (
            "TEMPLATE_ONLY_UNTIL_FRESH_USER_ACTIVATES_EXACT_UTF8_BYTES"
        ),
        "authorization_scope": "ONE_TRUSTWORTHY_FULL_SHORT_ONLY",
        "policy": validated,
        "public_bindings": deepcopy(dict(public_bindings)),
        "fresh_jit_approval_required": True,
        "durable_single_use_nonce_required": True,
        "later_approval_or_nonce_precreation_allowed": False,
        "long_execution_allowed": False,
        "skill_v3_production_cutover": False,
        "planning_v2_production_cutover": False,
        "actual_fee_risk_acceptance_required": (
            validated["monetary_cost_cap_state"] == "UNKNOWN_NOT_SEALED"
        ),
        "stop_on_first_blocked_invalid_drifted_failed_privacy_or_budget_state": True,
    }
    return json.dumps(
        body, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
    ).encode("utf-8") + b"\n"


def validate_full_short_canonical_authorization_v1(
    raw: bytes, *, policy: Mapping[str, Any],
    public_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    expected = render_full_short_canonical_authorization_v1(
        policy=policy, public_bindings=public_bindings,
    )
    _require(raw == expected, "AUTHORIZATION_CANONICAL_BYTES_MISMATCH")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise FullShortExecutionBoundaryError(
            "AUTHORIZATION_UTF8_OR_JSON_INVALID",
        ) from exc
    _require(isinstance(value, dict), "AUTHORIZATION_UTF8_OR_JSON_INVALID")
    value["authorization_text_sha256"] = hashlib.sha256(raw).hexdigest()
    return value


def validate_full_short_preflight_v1(
    *, policy: Mapping[str, Any], actual: Mapping[str, Any],
    authorization_text_sha256: str, external_actions_enabled: bool,
) -> dict[str, Any]:
    """Validate every immutable binding before approval, nonce or credentials."""

    validated = validate_policy_v1(policy)
    _require(
        _HEX64.fullmatch(authorization_text_sha256) is not None,
        "AUTHORIZATION_SHA256_INVALID",
    )
    required_equal = {
        "head": validated["execution_head"],
        "branch": validated["branch"],
        "run_id": validated["run_id"],
        "project_id_sha256": validated["project_id_sha256"],
        "workload_sha256": validated["workload_sha256"],
        "runtime_authority_sha256": validated["runtime_authority_sha256"],
        "style_reference_authority_sha256": (
            validated["style_reference_authority_sha256"]
        ),
        "route_manifest_sha256": validated["route_manifest_sha256"],
        "destination_manifest_sha256": validated[
            "destination_manifest_sha256"
        ],
        "egress_policy_sha256": validated["egress_policy_sha256"],
        "response_capture_policy_sha256": validated[
            "response_capture_policy_sha256"
        ],
        "capture_attestation_scheme": validated[
            "capture_attestation_scheme"
        ],
        "capture_attestation_public_key": validated[
            "capture_attestation_public_key"
        ],
        "capture_attestation_public_key_sha256": validated[
            "capture_attestation_public_key_sha256"
        ],
        "capacity_policy_registry_sha256": validated[
            "capacity_policy_registry_sha256"
        ],
        "logical_stage_plan_sha256": validated["logical_stage_plan_sha256"],
        "transport_recovery_policy_sha256": validated[
            "transport_recovery_policy_sha256"
        ],
        "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
        "logical_stage_recovery_policy_sha256": validated[
            "logical_stage_recovery_policy_sha256"
        ],
        "logical_stage_recovery_policy_identity": (
            "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY"
        ),
        "store_root_sha256": validated["store_root_sha256"],
        "failure_architecture_identity": FAILURE_ARCHITECTURE_IDENTITY,
        "recovery_policy_registry_sha256": (
            FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256
        ),
        "predispatch_state_machine_sha256": PREDISPATCH_STATE_MACHINE_SHA256,
        "nonce_reservation_policy_sha256": NONCE_RESERVATION_POLICY_SHA256,
        "observer_isolation_policy_sha256": OBSERVER_ISOLATION_POLICY_SHA256,
        "durable_failure_evidence_policy_sha256": (
            DURABLE_FAILURE_EVIDENCE_POLICY_SHA256
        ),
    }
    for field, expected in required_equal.items():
        _require(actual.get(field) == expected, f"{field.upper()}_DRIFT")
    _require(actual.get("worktree_clean") is True, "WORKTREE_DRIFT")
    _require(
        actual.get("skill_v3_production_cutover") is False,
        "SKILL_V3_CUTOVER_DRIFT",
    )
    _require(
        actual.get("planning_v2_production_cutover") is False,
        "PLANNING_V2_CUTOVER_DRIFT",
    )
    counters = dict(actual.get("external_action_counters") or {})
    for field in (
        "credential_lookup", "provider_client_creation", "provider_request",
        "http_post", "network", "model", "paid",
    ):
        _require(counters.get(field) == 0, "PREFLIGHT_EXTERNAL_ACTION_OCCURRED")
    body = {
        "schema": PREFLIGHT_SCHEMA,
        "version": 1,
        "policy_sha256": validated["policy_sha256"],
        "logical_stage_plan_sha256": validated["logical_stage_plan_sha256"],
        "transport_recovery_policy_sha256": validated[
            "transport_recovery_policy_sha256"
        ],
        "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
        "logical_stage_recovery_policy_sha256": validated[
            "logical_stage_recovery_policy_sha256"
        ],
        "logical_stage_recovery_policy_identity": (
            "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY"
        ),
        "failure_architecture_identity": FAILURE_ARCHITECTURE_IDENTITY,
        "recovery_policy_registry_sha256": (
            FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256
        ),
        "predispatch_state_machine_sha256": PREDISPATCH_STATE_MACHINE_SHA256,
        "nonce_reservation_policy_sha256": NONCE_RESERVATION_POLICY_SHA256,
        "observer_isolation_policy_sha256": OBSERVER_ISOLATION_POLICY_SHA256,
        "durable_failure_evidence_policy_sha256": (
            DURABLE_FAILURE_EVIDENCE_POLICY_SHA256
        ),
        "capacity_policy_registry_sha256": validated[
            "capacity_policy_registry_sha256"
        ],
        "authorization_text_sha256": authorization_text_sha256,
        "binding_status": "exact",
        "external_actions_enabled": bool(external_actions_enabled),
        "external_action_counters": counters,
        "approval_state": "NOT_CREATED",
        "nonce_state": "NOT_CREATED",
        "credential_state": "NOT_ACCESSED",
        "provider_client_state": "NOT_CREATED",
        "network_state": "NOT_ACCESSED",
        "created_at": _now(),
    }
    return _seal(
        "novel-flywheel-full-short-authorization-preflight-v1", body,
        "preflight_receipt_sha256",
    )


def validate_policy_v1(value: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(value)
    digest = body.pop("policy_sha256", None)
    _require(body.get("schema") == POLICY_SCHEMA, "POLICY_SCHEMA_MISMATCH")
    _require(body.get("version") == 1, "POLICY_SCHEMA_MISMATCH")
    _require(body.get("policy_version") == POLICY_VERSION, "POLICY_VERSION_MISMATCH")
    _require(_HEX40.fullmatch(str(body.get("execution_head"))) is not None, "HEAD_INVALID")
    _require(_ID.fullmatch(str(body.get("run_id"))) is not None, "RUN_ID_INVALID")
    for field in (
        "project_id_sha256", "workload_sha256", "runtime_authority_sha256",
        "style_reference_authority_sha256", "route_manifest_sha256",
        "destination_manifest_sha256", "egress_policy_sha256",
        "response_capture_policy_sha256",
        "logical_stage_plan_sha256", "transport_recovery_policy_sha256",
        "logical_stage_recovery_policy_sha256",
        "recovery_policy_registry_sha256",
        "predispatch_state_machine_sha256",
        "nonce_reservation_policy_sha256",
        "observer_isolation_policy_sha256",
        "durable_failure_evidence_policy_sha256",
        "store_root_sha256",
        "capture_attestation_public_key_sha256",
    ):
        _require(_HEX64.fullmatch(str(body.get(field))) is not None, f"{field.upper()}_INVALID")
    _require(
        body["response_capture_policy_sha256"]
        == RESPONSE_CAPTURE_POLICY_SHA256,
        "RESPONSE_CAPTURE_POLICY_NOT_ENFORCED",
    )
    capture_attestation_public_key = str(
        body.get("capture_attestation_public_key") or ""
    )
    _require(
        body.get("capture_attestation_scheme")
        == "ED25519_CAPTURE_ANCHOR_V1"
        and len(capture_attestation_public_key) == 64
        and _HEX64.fullmatch(capture_attestation_public_key) is not None
        and hashlib.sha256(
            bytes.fromhex(capture_attestation_public_key)
        ).hexdigest()
        == body["capture_attestation_public_key_sha256"],
        "RESPONSE_CAPTURE_ATTESTATION_AUTHORITY_INVALID",
    )
    _require(
        body["capacity_policy_registry_sha256"]
        == DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256,
        "CAPACITY_POLICY_REGISTRY_NOT_ENFORCED",
    )
    logical_stage_plan = validate_full_short_logical_stage_plan_v1(
        body.get("logical_stage_plan"),
    )
    _require(
        body["logical_stage_plan_sha256"]
        == full_short_logical_stage_plan_sha256_v1(logical_stage_plan),
        "LOGICAL_STAGE_PLAN_SHA256_MISMATCH",
    )
    _require(
        body.get("transport_recovery_policy")
        == TRANSPORT_RECOVERY_POLICY_V1
        and body["transport_recovery_policy_sha256"]
        == TRANSPORT_RECOVERY_POLICY_SHA256
        and body.get("transport_recovery_policy_identity")
        == "EXACT_REPLAY_ONLY",
        "TRANSPORT_RECOVERY_POLICY_NOT_EXACT_REPLAY_ONLY",
    )
    _require(
        body.get("logical_stage_recovery_policy")
        == LOGICAL_STAGE_RECOVERY_POLICY_V1
        and body["logical_stage_recovery_policy_sha256"]
        == LOGICAL_STAGE_RECOVERY_POLICY_SHA256
        and body.get("logical_stage_recovery_policy_identity")
        == "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY",
        "LOGICAL_STAGE_RECOVERY_POLICY_INVALID",
    )
    _require(
        body.get("failure_architecture_identity")
        == FAILURE_ARCHITECTURE_IDENTITY,
        "FAILURE_ARCHITECTURE_IDENTITY_INVALID",
    )
    for field, definition, expected_digest, reason in (
        (
            "recovery_policy_registry", FULL_SHORT_EXACT_RECOVERY_REGISTRY_V1,
            FULL_SHORT_EXACT_RECOVERY_REGISTRY_SHA256,
            "RECOVERY_POLICY_REGISTRY_INVALID",
        ),
        (
            "predispatch_state_machine", PREDISPATCH_STATE_MACHINE_V1,
            PREDISPATCH_STATE_MACHINE_SHA256,
            "PREDISPATCH_STATE_MACHINE_INVALID",
        ),
        (
            "nonce_reservation_policy", NONCE_RESERVATION_POLICY_V1,
            NONCE_RESERVATION_POLICY_SHA256,
            "NONCE_RESERVATION_POLICY_INVALID",
        ),
        (
            "observer_isolation_policy", OBSERVER_ISOLATION_POLICY_V1,
            OBSERVER_ISOLATION_POLICY_SHA256,
            "OBSERVER_ISOLATION_POLICY_INVALID",
        ),
        (
            "durable_failure_evidence_policy",
            DURABLE_FAILURE_EVIDENCE_POLICY_V1,
            DURABLE_FAILURE_EVIDENCE_POLICY_SHA256,
            "DURABLE_FAILURE_EVIDENCE_POLICY_INVALID",
        ),
    ):
        _require(
            body.get(field) == definition
            and body.get(f"{field}_sha256") == expected_digest,
            reason,
        )
    for field in (
        "expected_stage_calls", "hard_max_provider_requests",
        "hard_max_http_posts", "hard_max_network_attempts",
        "per_call_output_token_hard_cap",
        "total_output_token_hard_cap", "maximum_elapsed_seconds",
        "max_physical_attempts_per_logical_stage",
        "max_reasoning_only_recovery_dispatches_per_logical_stage",
    ):
        _require(type(body.get(field)) is int and int(body[field]) > 0, "CAPS_INVALID")
    _require(
        body["expected_stage_calls"] <= body["hard_max_provider_requests"]
        == body["hard_max_http_posts"] == body["hard_max_network_attempts"],
        "CAPS_INVALID",
    )
    _require(
        body["max_physical_attempts_per_logical_stage"] == 2
        and body[
            "max_reasoning_only_recovery_dispatches_per_logical_stage"
        ] == 1,
        "LOGICAL_STAGE_RECOVERY_CAP_INVALID",
    )
    _require(
        body["expected_stage_calls"] == len(logical_stage_plan)
        and max(item["requested_output_tokens"] for item in logical_stage_plan)
        <= body["per_call_output_token_hard_cap"]
        and sum(item["requested_output_tokens"] for item in logical_stage_plan)
        + int(LOGICAL_STAGE_RECOVERY_POLICY_V1["recovery_output_tokens"])
        <= body["total_output_token_hard_cap"],
        "LOGICAL_STAGE_PLAN_CAPS_MISMATCH",
    )
    _require(
        body["hard_max_provider_requests"]
        >= body["expected_stage_calls"] + 1,
        "LOGICAL_STAGE_RECOVERY_PHYSICAL_RESERVE_MISSING",
    )
    _require(body.get("single_use") is True, "POLICY_NOT_SINGLE_USE")
    _require(body.get("transport_retry_allowed") is False, "TRANSPORT_RETRY_ENABLED")
    _require(body.get("full_short_count") == 1, "FULL_SHORT_COUNT_INVALID")
    roles = body.get("required_stage_roles")
    _require(
        isinstance(roles, list) and bool(roles)
        and all(isinstance(role, str) and _ID.fullmatch(role) for role in roles)
        and len(roles) == len(set(roles)),
        "REQUIRED_STAGE_ROLES_INVALID",
    )
    _require(
        set(roles) == {item["role"] for item in logical_stage_plan},
        "REQUIRED_STAGE_ROLE_PLAN_MISMATCH",
    )
    _require(
        body.get("restart_policy") == "FAIL_CLOSED_NO_RESUME_OR_REDISPATCH",
        "RESTART_POLICY_NOT_FAIL_CLOSED",
    )
    if digest is not None:
        _require(
            digest == domain_sha256(
                "novel-flywheel-full-short-execution-policy-v1", body,
            ),
            "POLICY_SHA256_MISMATCH",
        )
        body["policy_sha256"] = digest
    return body


class FullShortDurableExecutionStoreV1:
    """External receipts with a process-confined capture attestation signer."""

    def __init__(self, *, repo_root: Path, store_root: Path) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        requested = Path(os.path.abspath(store_root))
        _require(not _inside(requested, self.repo_root), "STORE_INSIDE_GIT_WORKTREE")
        requested.mkdir(parents=True, exist_ok=True)
        self.root = requested.resolve(strict=True)
        _require(
            os.path.normcase(str(self.root)) == os.path.normcase(str(requested)),
            "STORE_PATH_NOT_EXACT",
        )
        self.lock_path = self.root / ".full-short-execution.lock"
        self.capacity_receipt_root = self.root / "capacity-v1"
        self.capacity_receipt_root.mkdir(parents=False, exist_ok=True)
        self.capture_anchor_root = self.root / "capture-anchor-v1"
        self.capture_anchor_root.mkdir(parents=False, exist_ok=True)
        self.store_root_sha256 = hashlib.sha256(
            str(self.root).encode("utf-8"),
        ).hexdigest()
        signer_key = os.path.normcase(str(self.root))
        private_key = _PROCESS_CAPTURE_ATTESTATION_SIGNERS_V1.get(signer_key)
        if private_key is None:
            private_key = Ed25519PrivateKey.generate()
            _PROCESS_CAPTURE_ATTESTATION_SIGNERS_V1[signer_key] = private_key
        self._capture_attestation_private_key: Ed25519PrivateKey | None = (
            private_key
        )
        self._set_capture_attestation_public_key(private_key.public_key())

    def _set_capture_attestation_public_key(
        self, public_key: Ed25519PublicKey,
    ) -> None:
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.capture_attestation_public_key = public_bytes.hex()
        self.capture_attestation_public_key_sha256 = hashlib.sha256(
            public_bytes
        ).hexdigest()

    def _verify_store_binding(self, policy: Mapping[str, Any]) -> dict[str, Any]:
        validated = validate_policy_v1(policy)
        _require(
            validated["store_root_sha256"] == self.store_root_sha256,
            "STORE_ROOT_POLICY_MISMATCH",
        )
        if (
            self.capture_attestation_public_key
            != validated["capture_attestation_public_key"]
        ):
            # A restarted process may verify and replay prior signed captures,
            # but cannot mint new anchors for the old single-use authority.
            self._capture_attestation_private_key = None
            self._set_capture_attestation_public_key(
                Ed25519PublicKey.from_public_bytes(bytes.fromhex(
                    str(validated["capture_attestation_public_key"])
                ))
            )
        return validated

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with _ExclusiveFileLock(self.lock_path):
            yield

    @staticmethod
    def _exclusive_write(path: Path, value: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            payload = canonical_json_bytes(value) + b"\n"
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                _require(written > 0, "DURABLE_WRITE_NO_PROGRESS")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise FullShortExecutionBoundaryError("SINGLE_USE_REPLAY") from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @classmethod
    def _replace(cls, path: Path, value: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(
            os, "O_BINARY", 0,
        )
        descriptor = os.open(temporary, flags, 0o600)
        try:
            payload = canonical_json_bytes(value) + b"\n"
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                _require(written > 0, "DURABLE_WRITE_NO_PROGRESS")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)

    def _key(self, execution_id: str) -> str:
        _require(_ID.fullmatch(execution_id) is not None, "EXECUTION_ID_INVALID")
        return domain_sha256("full-short-execution-storage-key-v1", execution_id)

    def _path(self, execution_id: str, kind: str) -> Path:
        return self.root / f"{self._key(execution_id)}.{kind}.json"

    def _capacity_path(self, execution_id: str, plan_sha256: str) -> Path:
        _require(_HEX64.fullmatch(plan_sha256) is not None,
                 "CAPACITY_PLAN_SHA256_INVALID")
        key = domain_sha256(
            "full-short-capacity-admission-storage-key-v1",
            {"execution_id": execution_id, "plan_sha256": plan_sha256},
        )
        return self.capacity_receipt_root / f"{key}.json"

    def _capture_anchor_path(
        self, execution_id: str, ordinal: int, byte_domain: str,
    ) -> Path:
        _require(type(ordinal) is int and ordinal > 0,
                 "CAPTURE_ANCHOR_IDENTITY_INVALID")
        _require(byte_domain in {
            PROVIDER_PROTOCOL_INPUT_BYTES, CONTRACT_RUNTIME_INPUT_BYTES,
        }, "CAPTURE_ANCHOR_IDENTITY_INVALID")
        key = domain_sha256(
            "full-short-provider-response-capture-anchor-storage-key-v1",
            {
                "execution_id": execution_id,
                "ordinal": ordinal,
                "byte_domain": byte_domain,
            },
        )
        return self.capture_anchor_root / f"{key}.json"

    def create_provider_response_capture_anchor(
        self, *, execution_id: str, ordinal: int, byte_domain: str,
        provider_response_capture_receipt_sha256: str,
    ) -> dict[str, Any]:
        """Bind a published capture to its immutable pre-response attempt."""

        _require(
            isinstance(provider_response_capture_receipt_sha256, str)
            and _HEX64.fullmatch(
                provider_response_capture_receipt_sha256
            ) is not None,
            "CAPTURE_ANCHOR_IDENTITY_INVALID",
        )
        with self._locked():
            ledger = self._verify_seal(
                self._read(execution_id, "ledger"),
                domain="novel-flywheel-full-short-dispatch-ledger-v1",
                field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
            )
            attempts = list(ledger.get("attempts") or [])
            _require(
                ordinal <= len(attempts)
                and attempts[ordinal - 1].get("ordinal") == ordinal,
                "CAPTURE_ANCHOR_IDENTITY_INVALID",
            )
            attempt = attempts[ordinal - 1]
            identity = {
                "schema": "FullShortProviderResponseCaptureAnchorV1",
                "version": 1,
                "execution_id": execution_id,
                "ordinal": ordinal,
                "byte_domain": byte_domain,
                "physical_attempt_id": attempt.get("physical_attempt_id"),
                "capacity_plan_sha256": attempt.get(
                    "capacity_plan_sha256"
                ),
                "capacity_admission_receipt_sha256": attempt.get(
                    "capacity_admission_receipt_sha256"
                ),
                "provider_response_capture_receipt_sha256": (
                    provider_response_capture_receipt_sha256
                ),
                "capture_attestation_public_key_sha256": (
                    self.capture_attestation_public_key_sha256
                ),
            }
            path = self._capture_anchor_path(
                execution_id, ordinal, byte_domain,
            )
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise FullShortExecutionBoundaryError(
                        "CAPTURE_ANCHOR_IDENTITY_INVALID"
                    ) from exc
                verified = self._verify_seal(
                    existing,
                    domain=(
                        "novel-flywheel-provider-response-capture-anchor-v1"
                    ),
                    field="capture_anchor_sha256",
                    reason="CAPTURE_ANCHOR_IDENTITY_INVALID",
                )
                _require(
                    all(verified.get(key) == value for key, value in identity.items())
                    and isinstance(verified.get("created_at"), str)
                    and isinstance(
                        verified.get("capture_attestation_signature"), str
                    ),
                    "CAPTURE_ANCHOR_IDENTITY_INVALID",
                )
                signed_body = dict(verified)
                signed_body.pop("capture_anchor_sha256", None)
                try:
                    signature = bytes.fromhex(str(
                        signed_body.pop("capture_attestation_signature")
                    ))
                    Ed25519PublicKey.from_public_bytes(bytes.fromhex(
                        self.capture_attestation_public_key
                    )).verify(signature, canonical_json_bytes(signed_body))
                except (InvalidSignature, ValueError, TypeError) as exc:
                    raise FullShortExecutionBoundaryError(
                        "CAPTURE_ANCHOR_IDENTITY_INVALID"
                    ) from exc
                return verified
            _require(
                self._capture_attestation_private_key is not None,
                "CAPTURE_ATTESTATION_SIGNER_UNAVAILABLE_AFTER_RESTART",
            )
            body = {**identity, "created_at": _now()}
            body["capture_attestation_signature"] = (
                self._capture_attestation_private_key.sign(
                    canonical_json_bytes(body)
                ).hex()
            )
            value = _seal(
                "novel-flywheel-provider-response-capture-anchor-v1",
                body, "capture_anchor_sha256",
            )
            self._exclusive_write(path, value)
            return value

    def audit_provider_response_capture_anchors(
        self, *, policy: Mapping[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        """Audit every exclusive capture anchor and its storage identity."""

        audited: list[dict[str, Any]] = []
        try:
            for path in sorted(self.capture_anchor_root.glob("*.json")):
                value = json.loads(path.read_text(encoding="utf-8"))
                _require(isinstance(value, dict),
                         "COMPLETION_CAPTURE_PROVENANCE_INVALID")
                sealed = self._verify_seal(
                    value,
                    domain=(
                        "novel-flywheel-provider-response-capture-anchor-v1"
                    ),
                    field="capture_anchor_sha256",
                    reason="COMPLETION_CAPTURE_PROVENANCE_INVALID",
                )
                _require(
                    set(sealed) == {
                        "schema", "version", "execution_id", "ordinal",
                        "byte_domain", "physical_attempt_id",
                        "capacity_plan_sha256",
                        "capacity_admission_receipt_sha256",
                        "provider_response_capture_receipt_sha256",
                        "capture_attestation_public_key_sha256",
                        "capture_attestation_signature",
                        "created_at", "capture_anchor_sha256",
                    }
                    and sealed.get("schema")
                    == "FullShortProviderResponseCaptureAnchorV1"
                    and sealed.get("version") == 1
                    and all(
                        isinstance(sealed.get(field), str)
                        and _HEX64.fullmatch(str(sealed[field])) is not None
                        for field in {
                            "capacity_plan_sha256",
                            "capacity_admission_receipt_sha256",
                            "provider_response_capture_receipt_sha256",
                            "capture_attestation_public_key_sha256",
                            "capture_anchor_sha256",
                        }
                    )
                    and isinstance(sealed.get("physical_attempt_id"), str)
                    and isinstance(
                        sealed.get("capture_attestation_signature"), str
                    )
                    and len(sealed["capture_attestation_signature"]) == 128,
                    "COMPLETION_CAPTURE_PROVENANCE_INVALID",
                )
                _require(
                    sealed["capture_attestation_public_key_sha256"]
                    == policy["capture_attestation_public_key_sha256"],
                    "COMPLETION_CAPTURE_PROVENANCE_INVALID",
                )
                signed_body = dict(sealed)
                signed_body.pop("capture_anchor_sha256", None)
                signature = bytes.fromhex(
                    str(signed_body.pop("capture_attestation_signature"))
                )
                try:
                    Ed25519PublicKey.from_public_bytes(bytes.fromhex(
                        str(policy["capture_attestation_public_key"])
                    )).verify(signature, canonical_json_bytes(signed_body))
                except (InvalidSignature, ValueError, TypeError) as exc:
                    raise FullShortExecutionBoundaryError(
                        "COMPLETION_CAPTURE_PROVENANCE_INVALID"
                    ) from exc
                expected_path = self._capture_anchor_path(
                    str(sealed.get("execution_id") or ""),
                    int(sealed.get("ordinal") or 0),
                    str(sealed.get("byte_domain") or ""),
                )
                _require(
                    os.path.normcase(str(path.resolve(strict=True)))
                    == os.path.normcase(str(expected_path.resolve(strict=True))),
                    "COMPLETION_CAPTURE_PROVENANCE_INVALID",
                )
                audited.append(sealed)
        except Exception as exc:
            if (
                isinstance(exc, FullShortExecutionBoundaryError)
                and exc.reason_code
                == "COMPLETION_CAPTURE_PROVENANCE_INVALID"
            ):
                raise
            raise FullShortExecutionBoundaryError(
                "COMPLETION_CAPTURE_PROVENANCE_INVALID"
            ) from exc
        return tuple(audited)

    def _read(self, execution_id: str, kind: str) -> dict[str, Any]:
        try:
            value = json.loads(
                self._path(execution_id, kind).read_text(encoding="utf-8"),
            )
        except (OSError, ValueError) as exc:
            raise FullShortExecutionBoundaryError(
                f"{kind.upper()}_NOT_FOUND_OR_CORRUPT",
            ) from exc
        _require(isinstance(value, dict), f"{kind.upper()}_NOT_FOUND_OR_CORRUPT")
        return value

    def create_permission(
        self, *, execution_id: str, authorization_text_sha256: str,
        policy: Mapping[str, Any], external_actions_enabled: bool,
    ) -> dict[str, Any]:
        validated = self._verify_store_binding(policy)
        _require(
            _HEX64.fullmatch(authorization_text_sha256) is not None,
            "AUTHORIZATION_SHA256_INVALID",
        )
        body = {
            "schema": PERMISSION_SCHEMA, "version": 1,
            "execution_id": execution_id,
            "authorization_text_sha256": authorization_text_sha256,
            "policy_sha256": validated["policy_sha256"],
            "logical_stage_plan_sha256": validated[
                "logical_stage_plan_sha256"
            ],
            "transport_recovery_policy_sha256": validated[
                "transport_recovery_policy_sha256"
            ],
            "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
            "logical_stage_recovery_policy_sha256": validated[
                "logical_stage_recovery_policy_sha256"
            ],
            "execution_head": validated["execution_head"],
            "store_root_sha256": self.store_root_sha256,
            "external_actions_enabled": external_actions_enabled,
            "state": "ACTIVE", "created_at": _now(), "single_use": True,
        }
        value = _seal(
            "novel-flywheel-full-short-permission-v1", body,
            "permission_sha256",
        )
        with self._locked():
            self._exclusive_write(self._path(execution_id, "permission"), value)
        return value

    def create_jit_approval(
        self, *, execution_id: str, policy: Mapping[str, Any],
        permission: Mapping[str, Any], external_actions_enabled: bool,
    ) -> dict[str, Any]:
        validated = self._verify_store_binding(policy)
        _require(permission.get("state") == "ACTIVE", "PERMISSION_NOT_ACTIVE")
        _require(
            permission.get("policy_sha256") == validated["policy_sha256"],
            "APPROVAL_POLICY_MISMATCH",
        )
        body = {
            "schema": APPROVAL_SCHEMA, "version": 1,
            "approval_id": f"fsa-{secrets.token_hex(16)}",
            "execution_id": execution_id,
            "permission_sha256": permission["permission_sha256"],
            "policy_sha256": validated["policy_sha256"],
            "logical_stage_plan_sha256": validated[
                "logical_stage_plan_sha256"
            ],
            "transport_recovery_policy_sha256": validated[
                "transport_recovery_policy_sha256"
            ],
            "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
            "logical_stage_recovery_policy_sha256": validated[
                "logical_stage_recovery_policy_sha256"
            ],
            "execution_head": validated["execution_head"],
            "store_root_sha256": self.store_root_sha256,
            "external_actions_enabled": external_actions_enabled,
            "nonce_state": "NOT_CREATED", "state": "SIGNED",
            "created_at": _now(), "single_use": True,
        }
        value = _seal(
            "novel-flywheel-full-short-jit-approval-v1", body,
            "signed_approval_sha256",
        )
        with self._locked():
            self._exclusive_write(self._path(execution_id, "approval"), value)
        return value

    def reserve_nonce(
        self, *, execution_id: str, policy: Mapping[str, Any],
        approval: Mapping[str, Any], external_actions_enabled: bool,
    ) -> dict[str, Any]:
        _require(
            external_actions_enabled is False,
            "LEGACY_NONCE_RESERVATION_LIVE_FORBIDDEN",
        )
        validated = self._verify_store_binding(policy)
        _require(approval.get("state") == "SIGNED", "APPROVAL_NOT_SIGNED")
        _require(
            approval.get("policy_sha256") == validated["policy_sha256"],
            "NONCE_POLICY_MISMATCH",
        )
        reservation_body = {
            "schema": NONCE_SCHEMA, "version": 1,
            "nonce_id": f"fsn-{secrets.token_hex(16)}",
            "execution_id": execution_id,
            "signed_approval_sha256": approval["signed_approval_sha256"],
            "policy_sha256": validated["policy_sha256"],
            "logical_stage_plan_sha256": validated[
                "logical_stage_plan_sha256"
            ],
            "transport_recovery_policy_sha256": validated[
                "transport_recovery_policy_sha256"
            ],
            "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
            "logical_stage_recovery_policy_sha256": validated[
                "logical_stage_recovery_policy_sha256"
            ],
            "execution_head": validated["execution_head"],
            "store_root_sha256": self.store_root_sha256,
            "external_actions_enabled": external_actions_enabled,
            "created_at": _now(), "single_use": True,
        }
        reservation = _seal(
            "novel-flywheel-full-short-nonce-v1", reservation_body,
            "nonce_sha256",
        )
        value = _seal(
            "novel-flywheel-full-short-nonce-record-v1",
            {
                **reservation,
                "state": "RESERVED",
                "dispatch_attempt_count": 0,
                "consumed_at": None,
                "consumed_session_sha256": None,
                "observer_session_sha256": None,
            },
            "nonce_record_sha256",
        )
        ledger_body = {
            "schema": LEDGER_SCHEMA, "version": 1,
            "execution_id": execution_id,
            "nonce_sha256": reservation["nonce_sha256"],
            "policy_sha256": validated["policy_sha256"],
            "logical_stage_plan_sha256": validated[
                "logical_stage_plan_sha256"
            ],
            "transport_recovery_policy_sha256": validated[
                "transport_recovery_policy_sha256"
            ],
            "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
            "logical_stage_recovery_policy_sha256": validated[
                "logical_stage_recovery_policy_sha256"
            ],
            "capacity_policy_registry_sha256": validated[
                "capacity_policy_registry_sha256"
            ],
            "store_root_sha256": self.store_root_sha256,
            "state": "READY", "attempts": [], "completed_stage_receipts": [],
            "created_at": _now(), "updated_at": _now(),
        }
        ledger = _seal(
            "novel-flywheel-full-short-dispatch-ledger-v1", ledger_body,
            "ledger_sha256",
        )
        with self._locked():
            self._exclusive_write(self._path(execution_id, "nonce"), value)
            self._exclusive_write(self._path(execution_id, "ledger"), ledger)
        return value

    @full_short_boundary_entry("FS.CHECKPOINT.TRANSITION")
    def prepare_predispatch_ledger(
        self, *, execution_id: str, policy: Mapping[str, Any],
        permission: Mapping[str, Any], approval: Mapping[str, Any],
        external_actions_enabled: bool,
    ) -> dict[str, Any]:
        """Create the durable local-readiness ledger without creating a nonce."""

        validated = self._verify_store_binding(policy)
        _require(permission.get("state") == "ACTIVE", "PERMISSION_NOT_ACTIVE")
        _require(approval.get("state") == "SIGNED", "APPROVAL_NOT_SIGNED")
        _require(
            approval.get("permission_sha256") == permission.get("permission_sha256"),
            "APPROVAL_PERMISSION_MISMATCH",
        )
        for value in (permission, approval):
            _require(
                value.get("execution_id") == execution_id
                and value.get("policy_sha256") == validated["policy_sha256"]
                and value.get("store_root_sha256") == self.store_root_sha256
                and value.get("external_actions_enabled")
                is external_actions_enabled,
                "PREDISPATCH_AUTHORITY_CHAIN_MISMATCH",
            )
        body = {
            "schema": LEDGER_SCHEMA, "version": 1,
            "execution_id": execution_id,
            "nonce_sha256": None,
            "policy_sha256": validated["policy_sha256"],
            "logical_stage_plan_sha256": validated[
                "logical_stage_plan_sha256"
            ],
            "transport_recovery_policy_sha256": validated[
                "transport_recovery_policy_sha256"
            ],
            "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
            "logical_stage_recovery_policy_sha256": validated[
                "logical_stage_recovery_policy_sha256"
            ],
            "capacity_policy_registry_sha256": validated[
                "capacity_policy_registry_sha256"
            ],
            "store_root_sha256": self.store_root_sha256,
            "permission_sha256": permission["permission_sha256"],
            "signed_approval_sha256": approval["signed_approval_sha256"],
            "observer_session_sha256": None,
            "dispatch_readiness_receipt_sha256": None,
            "nonce_disposition": "ABSENT_LOCAL_READINESS",
            "state": "PREDISPATCH_LOCAL_READINESS",
            "attempts": [], "completed_stage_receipts": [],
            "created_at": _now(), "updated_at": _now(),
        }
        value = _seal(
            "novel-flywheel-full-short-dispatch-ledger-v1", body,
            "ledger_sha256",
        )
        with self._locked():
            _require(
                not self._path(execution_id, "nonce").exists(),
                "PREMATURE_NONCE_ALREADY_EXISTS",
            )
            self._exclusive_write(self._path(execution_id, "ledger"), value)
        return value

    def verify_predispatch_chain(
        self, *, execution_id: str, policy: Mapping[str, Any],
        external_actions_enabled: bool,
    ) -> dict[str, dict[str, Any]]:
        validated = self._verify_store_binding(policy)
        permission = self._verify_seal(
            self._read(execution_id, "permission"),
            domain="novel-flywheel-full-short-permission-v1",
            field="permission_sha256", reason="PERMISSION_SHA256_MISMATCH",
        )
        approval = self._verify_seal(
            self._read(execution_id, "approval"),
            domain="novel-flywheel-full-short-jit-approval-v1",
            field="signed_approval_sha256", reason="APPROVAL_SHA256_MISMATCH",
        )
        ledger = self._verify_seal(
            self._read(execution_id, "ledger"),
            domain="novel-flywheel-full-short-dispatch-ledger-v1",
            field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
        )
        _require(
            ledger.get("capacity_policy_registry_sha256")
            == validated["capacity_policy_registry_sha256"],
            "EXECUTION_CHAIN_CAPACITY_POLICY_MISMATCH",
        )
        _require(permission.get("state") == "ACTIVE", "PERMISSION_NOT_ACTIVE")
        _require(approval.get("state") == "SIGNED", "APPROVAL_NOT_SIGNED")
        _require(
            ledger.get("state") == "PREDISPATCH_LOCAL_READINESS"
            and ledger.get("nonce_sha256") is None
            and ledger.get("nonce_disposition") == "ABSENT_LOCAL_READINESS",
            "PREDISPATCH_LEDGER_STATE_INVALID",
        )
        for value in (permission, approval, ledger):
            _require(
                value.get("execution_id") == execution_id
                and value.get("policy_sha256") == validated["policy_sha256"]
                and value.get("store_root_sha256") == self.store_root_sha256
                and value.get("logical_stage_plan_sha256")
                == validated["logical_stage_plan_sha256"]
                and value.get("transport_recovery_policy_sha256")
                == validated["transport_recovery_policy_sha256"]
                and value.get("transport_recovery_policy_identity")
                == "EXACT_REPLAY_ONLY"
                and value.get("logical_stage_recovery_policy_sha256")
                == validated["logical_stage_recovery_policy_sha256"],
                "PREDISPATCH_CHAIN_MISMATCH",
            )
        _require(
            approval.get("permission_sha256") == permission.get("permission_sha256")
            and ledger.get("permission_sha256") == permission.get("permission_sha256")
            and ledger.get("signed_approval_sha256")
            == approval.get("signed_approval_sha256"),
            "PREDISPATCH_CHAIN_LINK_MISMATCH",
        )
        for value in (permission, approval):
            _require(
                value.get("external_actions_enabled")
                is external_actions_enabled,
                "EXTERNAL_ACTION_AUTHORITY_MISMATCH",
            )
        return {"permission": permission, "approval": approval, "ledger": ledger}

    def claim_predispatch_observer_session(
        self, *, execution_id: str, policy: Mapping[str, Any], session_id: str,
        external_actions_enabled: bool,
    ) -> None:
        self.verify_predispatch_chain(
            execution_id=execution_id, policy=policy,
            external_actions_enabled=external_actions_enabled,
        )
        session_sha256 = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        with self._locked():
            ledger = self._verify_seal(
                self._read(execution_id, "ledger"),
                domain="novel-flywheel-full-short-dispatch-ledger-v1",
                field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
            )
            _require(
                ledger.get("state") == "PREDISPATCH_LOCAL_READINESS"
                and ledger.get("observer_session_sha256") is None,
                "OBSERVER_ALREADY_CLAIMED_NO_RESTART",
            )
            body = dict(ledger)
            body.pop("ledger_sha256", None)
            body["observer_session_sha256"] = session_sha256
            body["updated_at"] = _now()
            self._replace(
                self._path(execution_id, "ledger"),
                _seal(
                    "novel-flywheel-full-short-dispatch-ledger-v1", body,
                    "ledger_sha256",
                ),
            )

    def nonce_exists(self, execution_id: str) -> bool:
        return self._path(execution_id, "nonce").exists()

    def load_nonce(self, execution_id: str) -> dict[str, Any]:
        return self._read(execution_id, "nonce")

    @full_short_boundary_entry("FS.DISPATCH.MODEL")
    def reserve_nonce_from_dispatch_readiness(
        self, *, execution_id: str, policy: Mapping[str, Any],
        external_actions_enabled: bool, session_id: str,
        readiness: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Create the nonce only after every knowable request check has passed.

        The first write is an explicit non-restartable pending state.  A crash
        between nonce and ledger replacement therefore cannot redispatch.
        """

        chain = self.verify_predispatch_chain(
            execution_id=execution_id, policy=policy,
            external_actions_enabled=external_actions_enabled,
        )
        validated = self._verify_store_binding(policy)
        session_sha256 = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        with self._locked():
            _require(
                not self._path(execution_id, "nonce").exists(),
                "NONCE_ALREADY_EXISTS_NO_RESTART",
            )
            ledger = self._verify_seal(
                self._read(execution_id, "ledger"),
                domain="novel-flywheel-full-short-dispatch-ledger-v1",
                field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
            )
            _require(
                ledger.get("state") == "PREDISPATCH_LOCAL_READINESS"
                and ledger.get("observer_session_sha256") == session_sha256
                and not ledger.get("attempts"),
                "PREDISPATCH_SESSION_OR_STATE_DRIFT",
            )
            readiness_body = _validate_dispatch_readiness_v1(
                readiness, execution_id=execution_id, policy=validated,
                session_sha256=session_sha256, ledger=ledger,
            )
            readiness_sha256 = domain_sha256(
                "novel-flywheel-full-short-dispatch-readiness-v1",
                readiness_body,
            )
            approval = chain["approval"]
            reservation_body = {
                "schema": NONCE_SCHEMA, "version": 1,
                "nonce_id": f"fsn-{secrets.token_hex(16)}",
                "execution_id": execution_id,
                "signed_approval_sha256": approval["signed_approval_sha256"],
                "policy_sha256": validated["policy_sha256"],
                "logical_stage_plan_sha256": validated["logical_stage_plan_sha256"],
                "transport_recovery_policy_sha256": validated[
                    "transport_recovery_policy_sha256"
                ],
                "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
                "logical_stage_recovery_policy_sha256": validated[
                    "logical_stage_recovery_policy_sha256"
                ],
                "execution_head": validated["execution_head"],
                "store_root_sha256": self.store_root_sha256,
                "external_actions_enabled": external_actions_enabled,
                "created_at": _now(), "single_use": True,
            }
            reservation = _seal(
                "novel-flywheel-full-short-nonce-v1", reservation_body,
                "nonce_sha256",
            )
            nonce = _seal(
                "novel-flywheel-full-short-nonce-record-v1",
                {
                    **reservation,
                    "state": "CONSUMED_DISPATCH_COMMIT_PENDING",
                    "dispatch_attempt_count": 0,
                    "consumed_at": None,
                    "consumed_session_sha256": session_sha256,
                    "observer_session_sha256": session_sha256,
                    "dispatch_readiness_receipt_sha256": readiness_sha256,
                    "dispatch_readiness": readiness_body,
                },
                "nonce_record_sha256",
            )
            self._exclusive_write(self._path(execution_id, "nonce"), nonce)
            ledger_body = dict(ledger)
            ledger_body.pop("ledger_sha256", None)
            ledger_body.update({
                "nonce_sha256": reservation["nonce_sha256"],
                "dispatch_readiness_receipt_sha256": readiness_sha256,
                "nonce_disposition": "CONSUMED_DISPATCH_COMMIT_PENDING",
                "state": "DISPATCH_COMMIT_PENDING",
                "updated_at": _now(),
            })
            self._replace(
                self._path(execution_id, "ledger"),
                _seal(
                    "novel-flywheel-full-short-dispatch-ledger-v1", ledger_body,
                    "ledger_sha256",
                ),
            )
        return nonce

    def load_ledger(self, execution_id: str) -> dict[str, Any]:
        return self._read(execution_id, "ledger")

    def create_capacity_admission_receipt(
        self, *, execution_id: str, plan_sha256: str,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist one hash-only, unconsumed capacity admission receipt."""

        _require(_HEX64.fullmatch(plan_sha256) is not None,
                 "CAPACITY_PLAN_SHA256_INVALID")
        value = _seal(
            "novel-flywheel-capacity-admission-receipt-v1",
            dict(body), "capacity_admission_receipt_sha256",
        )
        value = _validate_capacity_admission_receipt_v1(
            value, execution_id=execution_id, plan_sha256=plan_sha256,
        )
        with self._locked():
            self._exclusive_write(
                self._capacity_path(execution_id, plan_sha256),
                value,
            )
        return value

    def load_capacity_admission_receipt(
        self, *, execution_id: str, plan_sha256: str,
    ) -> dict[str, Any]:
        _require(_HEX64.fullmatch(plan_sha256) is not None,
                 "CAPACITY_PLAN_SHA256_INVALID")
        try:
            value = json.loads(
                self._capacity_path(execution_id, plan_sha256).read_text(
                    encoding="utf-8",
                )
            )
        except (OSError, ValueError) as exc:
            raise FullShortExecutionBoundaryError(
                "CAPACITY_ADMISSION_RECEIPT_NOT_FOUND_OR_CORRUPT"
            ) from exc
        sealed = self._verify_seal(
            value,
            domain="novel-flywheel-capacity-admission-receipt-v1",
            field="capacity_admission_receipt_sha256",
            reason="CAPACITY_ADMISSION_RECEIPT_TAMPERED",
        )
        return _validate_capacity_admission_receipt_v1(
            sealed, execution_id=execution_id, plan_sha256=plan_sha256,
        )

    def transition_capacity_admission_receipt(
        self, *, execution_id: str, plan_sha256: str,
        expected_receipt_sha256: str, expected_state: str,
        updates: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Crash-safely advance exactly one capacity receipt state."""

        with self._locked():
            current = self.load_capacity_admission_receipt(
                execution_id=execution_id, plan_sha256=plan_sha256,
            )
            _require(
                current["capacity_admission_receipt_sha256"]
                == expected_receipt_sha256,
                "CAPACITY_ADMISSION_RECEIPT_STALE",
            )
            _require(current.get("state") == expected_state,
                     "CAPACITY_ADMISSION_RECEIPT_STATE_INVALID")
            body = dict(current)
            body.pop("capacity_admission_receipt_sha256", None)
            body.update(deepcopy(dict(updates)))
            value = _seal(
                "novel-flywheel-capacity-admission-receipt-v1",
                body, "capacity_admission_receipt_sha256",
            )
            value = _validate_capacity_admission_receipt_v1(
                value, execution_id=execution_id, plan_sha256=plan_sha256,
            )
            self._replace(
                self._capacity_path(execution_id, plan_sha256),
                value,
            )
            return value

    def audit_capacity_admission_receipts(self) -> tuple[dict[str, Any], ...]:
        """Validate every durable capacity receipt and its storage identity."""

        audited: list[dict[str, Any]] = []
        try:
            paths = sorted(self.capacity_receipt_root.iterdir())
            for path in paths:
                _require(
                    path.is_file() and path.suffix == ".json",
                    "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID",
                )
                value = json.loads(path.read_text(encoding="utf-8"))
                _require(
                    isinstance(value, dict),
                    "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID",
                )
                execution_id = str(value.get("execution_id") or "")
                plan_sha256 = str(value.get("capacity_plan_sha256") or "")
                expected_path = self._capacity_path(
                    execution_id, plan_sha256,
                )
                _require(
                    os.path.normcase(str(path.resolve(strict=True)))
                    == os.path.normcase(str(expected_path.resolve(strict=True))),
                    "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID",
                )
                sealed = self._verify_seal(
                    value,
                    domain="novel-flywheel-capacity-admission-receipt-v1",
                    field="capacity_admission_receipt_sha256",
                    reason="COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID",
                )
                audited.append(_validate_capacity_admission_receipt_v1(
                    sealed,
                    execution_id=execution_id,
                    plan_sha256=plan_sha256,
                ))
        except Exception as exc:
            if (
                isinstance(exc, FullShortExecutionBoundaryError)
                and exc.reason_code
                == "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID"
            ):
                raise
            raise FullShortExecutionBoundaryError(
                "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID"
            ) from exc
        return tuple(audited)

    def verify_completion_capacity_receipts(
        self, *, execution_id: str, policy: Mapping[str, Any],
        ledger: Mapping[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        """Re-read every consumed receipt before terminal completion."""

        validated = self._verify_store_binding(policy)
        attempts = list(ledger.get("attempts") or [])
        _validate_completion_physical_attempt_chain_v1(
            execution_id=execution_id, attempts=attempts,
        )
        audited = self.audit_capacity_admission_receipts()
        actual = [
            item for item in audited
            if item.get("execution_id") == execution_id
        ]
        expected_plans = [
            str(item.get("capacity_plan_sha256") or "")
            for item in attempts
        ]
        _require(
            len(expected_plans) == len(set(expected_plans))
            and len(actual) == len(expected_plans)
            and {item["capacity_plan_sha256"] for item in actual}
            == set(expected_plans),
            "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID",
        )
        actual_by_plan = {
            item["capacity_plan_sha256"]: item for item in actual
        }
        plan_by_logical_stage = {
            str(item["logical_stage_id"]): item
            for item in validated["logical_stage_plan"]
        }
        receipts: list[dict[str, Any]] = []
        logical_attempt_counts: dict[str, int] = {}
        for attempt in attempts:
            logical_stage_id = str(attempt.get("logical_stage_id") or "")
            expected_plan_entry = plan_by_logical_stage.get(logical_stage_id)
            _require(
                expected_plan_entry is not None,
                "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID",
            )
            expected_capacity_envelope_sha256 = (
                _logical_capacity_envelope_sha256_v1(
                    execution_id=execution_id,
                    policy=validated,
                    logical_stage_plan_entry=expected_plan_entry,
                )
            )
            logical_attempt_counts[logical_stage_id] = (
                logical_attempt_counts.get(logical_stage_id, 0) + 1
            )
            plan_sha256 = str(attempt.get("capacity_plan_sha256") or "")
            receipt = actual_by_plan[plan_sha256]
            _require(
                receipt.get("state") == "CONSUMED"
                and receipt.get("capacity_admission_receipt_sha256")
                == attempt.get("capacity_admission_receipt_sha256")
                and receipt.get("capacity_policy_registry_sha256")
                == validated["capacity_policy_registry_sha256"]
                and receipt.get("logical_stage_id")
                == logical_stage_id
                and receipt.get("physical_attempt")
                == logical_attempt_counts[logical_stage_id]
                and receipt.get("physical_attempt_id")
                == attempt.get("physical_attempt_id")
                and receipt.get("global_physical_attempt_ordinal")
                == attempt.get("global_physical_attempt_ordinal")
                and receipt.get("logical_capacity_envelope_sha256")
                == attempt.get("logical_capacity_envelope_sha256")
                == expected_capacity_envelope_sha256
                and receipt.get("route_capability_snapshot_sha256")
                == attempt.get("route_capability_snapshot_sha256")
                and receipt.get("provider_route_identity_sha256")
                == attempt.get("role_binding_sha256")
                and receipt.get("rendered_request_sha256")
                == attempt.get("rendered_request_sha256")
                and receipt.get("recovery_stage_role")
                == attempt.get("recovery_stage_role")
                and receipt.get("reasoning_policy")
                == attempt.get("reasoning_policy")
                and receipt.get("base_rendered_request_sha256")
                == attempt.get("base_rendered_request_sha256")
                and receipt.get("recovery_overlay_kind")
                == attempt.get("recovery_overlay_kind")
                and receipt.get("recovery_overlay_sha256")
                == attempt.get("recovery_overlay_sha256")
                and receipt.get("recovery_prompt_delta_sha256")
                == attempt.get("recovery_prompt_delta_sha256")
                and receipt.get("recovery_source_capture_receipt_sha256")
                == attempt.get("recovery_source_capture_receipt_sha256"),
                "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID",
            )
            receipts.append(receipt)
        _validate_capacity_recovery_chain_v1(
            attempts=attempts,
            receipts_by_plan={
                item["capacity_plan_sha256"]: item for item in receipts
            },
        )
        _require(
            len(receipts) == len(attempts)
            and len({
                item["capacity_admission_receipt_sha256"] for item in receipts
            }) == len(receipts),
            "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID",
        )
        self.verify_completion_capture_receipts(
            execution_id=execution_id, policy=validated, ledger=ledger,
        )
        return tuple(receipts)

    def verify_completion_capture_receipts(
        self, *, execution_id: str, policy: Mapping[str, Any],
        ledger: Mapping[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        """Anchor every ledger capture hash to the immutable capture store."""

        attempts = list(ledger.get("attempts") or [])
        _validate_completion_physical_attempt_chain_v1(
            execution_id=execution_id, attempts=attempts,
        )
        capture_store = ProviderResponseCaptureStoreV1(
            repo_root=self.repo_root,
            store_root=self.root / "provider-response-captures-v1",
        )
        try:
            anchors = [
                item for item in self.audit_provider_response_capture_anchors(
                    policy=policy,
                )
                if item.get("execution_id") == execution_id
            ]
            all_anchors = self.audit_provider_response_capture_anchors(
                policy=policy,
            )
            audited = capture_store.audit_all(
                expected_receipt_sha256s=[
                    str(item["provider_response_capture_receipt_sha256"])
                    for item in all_anchors
                ],
            )
        except Exception as exc:
            raise FullShortExecutionBoundaryError(
                "COMPLETION_CAPTURE_PROVENANCE_INVALID"
            ) from exc
        actual = [
            item for item in audited
            if item.get("execution_id") == execution_id
        ]
        expected: list[tuple[int, str, str]] = []
        for ordinal, attempt in enumerate(attempts, 1):
            for field, byte_domain in (
                (
                    "provider_protocol_capture_receipt_sha256",
                    PROVIDER_PROTOCOL_INPUT_BYTES,
                ),
                (
                    "contract_runtime_capture_receipt_sha256",
                    CONTRACT_RUNTIME_INPUT_BYTES,
                ),
            ):
                receipt_sha256 = attempt.get(field)
                if receipt_sha256 is None:
                    _require(
                        not (
                            field
                            == "provider_protocol_capture_receipt_sha256"
                            and attempt.get("capture_enforcement_required")
                        ),
                        "COMPLETION_CAPTURE_PROVENANCE_INVALID",
                    )
                    continue
                _require(
                    isinstance(receipt_sha256, str)
                    and _HEX64.fullmatch(receipt_sha256) is not None,
                    "COMPLETION_CAPTURE_PROVENANCE_INVALID",
                )
                matches = [
                    item for item in actual
                    if item.get("byte_domain") == byte_domain
                    and item.get("call_id")
                    == f"{execution_id}:{ordinal}"
                    and item.get("ledger_receipt_sha256")
                    == receipt_sha256
                ]
                _require(
                    len(matches) == 1,
                    "COMPLETION_CAPTURE_PROVENANCE_INVALID",
                )
                metadata = matches[0].get("metadata") or {}
                _require(
                    metadata.get("stage_id") == attempt.get("stage")
                    and metadata.get("provider_id_sha256")
                    == attempt.get("provider_id_sha256")
                    and metadata.get("model_id_sha256")
                    == attempt.get("model_id_sha256")
                    and metadata.get("route_fingerprint")
                    == attempt.get("route_fingerprint")
                    and attempt.get("protocol_schema_id")
                    == f"{metadata.get('protocol')}-wire-v1"
                    and metadata.get("contract_name")
                    == attempt.get("contract_name")
                    and metadata.get("contract_version")
                    == attempt.get("contract_version")
                    and metadata.get("contract_schema_sha256")
                    == attempt.get("contract_schema_sha256")
                    and metadata.get("transport_complete") is True
                    and (
                        byte_domain != PROVIDER_PROTOCOL_INPUT_BYTES
                        or (
                            metadata.get("http_success")
                            == attempt.get(
                                "provider_protocol_capture_http_success"
                            )
                            and metadata.get("response_status_sha256")
                            == attempt.get("response_status_sha256")
                        )
                    ),
                    "COMPLETION_CAPTURE_PROVENANCE_INVALID",
                )
                protocol = str(metadata.get("protocol") or "")
                _require(
                    (
                        byte_domain == CONTRACT_RUNTIME_INPUT_BYTES
                        or metadata.get("adapter_id")
                        in _PROVIDER_PROTOCOL_ADAPTER_IDS.get(
                            protocol, frozenset(),
                        )
                    )
                    and type(metadata.get("adapter_version")) is int
                    and int(metadata["adapter_version"]) > 0,
                    "COMPLETION_CAPTURE_PROVENANCE_INVALID",
                )
                anchor_matches = [
                    item for item in anchors
                    if item.get("ordinal") == ordinal
                    and item.get("byte_domain") == byte_domain
                    and item.get("physical_attempt_id")
                    == attempt.get("physical_attempt_id")
                    and item.get("capacity_plan_sha256")
                    == attempt.get("capacity_plan_sha256")
                    and item.get("capacity_admission_receipt_sha256")
                    == attempt.get("capacity_admission_receipt_sha256")
                    and item.get(
                        "provider_response_capture_receipt_sha256"
                    ) == receipt_sha256
                ]
                _require(
                    len(anchor_matches) == 1,
                    "COMPLETION_CAPTURE_PROVENANCE_INVALID",
                )
                expected.append((ordinal, byte_domain, receipt_sha256))
        _require(
            len(actual) == len(expected) == len(anchors),
            "COMPLETION_CAPTURE_PROVENANCE_INVALID",
        )
        return tuple(actual)

    @staticmethod
    def _verify_seal(
        value: Mapping[str, Any], *, domain: str, field: str, reason: str,
    ) -> dict[str, Any]:
        body = dict(value)
        digest = body.pop(field, None)
        _require(
            isinstance(digest, str) and digest == domain_sha256(domain, body),
            reason,
        )
        body[field] = digest
        return body

    def verify_ready_chain(
        self, *, execution_id: str, policy: Mapping[str, Any],
        external_actions_enabled: bool,
    ) -> dict[str, dict[str, Any]]:
        """Re-read the complete durable authority chain before dispatch."""

        validated = self._verify_store_binding(policy)
        permission = self._verify_seal(
            self._read(execution_id, "permission"),
            domain="novel-flywheel-full-short-permission-v1",
            field="permission_sha256", reason="PERMISSION_SHA256_MISMATCH",
        )
        approval = self._verify_seal(
            self._read(execution_id, "approval"),
            domain="novel-flywheel-full-short-jit-approval-v1",
            field="signed_approval_sha256", reason="APPROVAL_SHA256_MISMATCH",
        )
        nonce = self._verify_seal(
            self._read(execution_id, "nonce"),
            domain="novel-flywheel-full-short-nonce-record-v1",
            field="nonce_record_sha256", reason="NONCE_SHA256_MISMATCH",
        )
        nonce_identity = self._verify_seal(
            {key: value for key, value in nonce.items() if key not in {
                "state", "dispatch_attempt_count", "consumed_at",
                "consumed_session_sha256", "observer_session_sha256",
                "dispatch_readiness_receipt_sha256",
                "dispatch_readiness",
                "nonce_record_sha256",
            }},
            domain="novel-flywheel-full-short-nonce-v1",
            field="nonce_sha256", reason="NONCE_SHA256_MISMATCH",
        )
        ledger = self._verify_seal(
            self._read(execution_id, "ledger"),
            domain="novel-flywheel-full-short-dispatch-ledger-v1",
            field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
        )
        _require(
            ledger.get("capacity_policy_registry_sha256")
            == validated["capacity_policy_registry_sha256"],
            "EXECUTION_CHAIN_CAPACITY_POLICY_MISMATCH",
        )
        _require(permission.get("state") == "ACTIVE", "PERMISSION_NOT_ACTIVE")
        _require(approval.get("state") == "SIGNED", "APPROVAL_NOT_SIGNED")
        if nonce.get("state") == "CONSUMED":
            raise FullShortExecutionBoundaryError(
                "NONCE_ALREADY_CONSUMED_NO_RESTART",
            )
        _require(nonce.get("state") == "RESERVED", "NONCE_NOT_RESERVED")
        for value in (permission, approval, nonce, ledger):
            _require(
                value.get("execution_id") == execution_id,
                "EXECUTION_CHAIN_ID_MISMATCH",
            )
            _require(
                value.get("policy_sha256") == validated["policy_sha256"],
                "EXECUTION_CHAIN_POLICY_MISMATCH",
            )
            _require(
                value.get("store_root_sha256") == self.store_root_sha256,
                "EXECUTION_CHAIN_STORE_ROOT_MISMATCH",
            )
            _require(
                value.get("logical_stage_plan_sha256")
                == validated["logical_stage_plan_sha256"],
                "EXECUTION_CHAIN_LOGICAL_STAGE_PLAN_MISMATCH",
            )
            _require(
                value.get("transport_recovery_policy_sha256")
                == validated["transport_recovery_policy_sha256"]
                and value.get("transport_recovery_policy_identity")
                == "EXACT_REPLAY_ONLY",
                "EXECUTION_CHAIN_TRANSPORT_RECOVERY_POLICY_MISMATCH",
            )
            _require(
                value.get("logical_stage_recovery_policy_sha256")
                == validated["logical_stage_recovery_policy_sha256"],
                "EXECUTION_CHAIN_LOGICAL_RECOVERY_POLICY_MISMATCH",
            )
        _require(
            approval.get("permission_sha256") == permission["permission_sha256"],
            "APPROVAL_PERMISSION_MISMATCH",
        )
        _require(
            nonce.get("signed_approval_sha256")
            == approval["signed_approval_sha256"],
            "NONCE_APPROVAL_MISMATCH",
        )
        _require(
            ledger.get("nonce_sha256") == nonce_identity["nonce_sha256"],
            "LEDGER_NONCE_MISMATCH",
        )
        for value in (permission, approval, nonce):
            _require(
                value.get("external_actions_enabled")
                is external_actions_enabled,
                "EXTERNAL_ACTION_AUTHORITY_MISMATCH",
            )
        context = {
            "permission": permission, "approval": approval,
            "nonce": nonce, "ledger": ledger,
        }
        return context

    def claim_observer_session(
        self, *, execution_id: str, policy: Mapping[str, Any], session_id: str,
    ) -> None:
        """Claim the reserved execution once; construction is not resumable."""

        validated = self._verify_store_binding(policy)
        session_sha256 = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        with self._locked():
            nonce = self._verify_seal(
                self._read(execution_id, "nonce"),
                domain="novel-flywheel-full-short-nonce-record-v1",
                field="nonce_record_sha256", reason="NONCE_SHA256_MISMATCH",
            )
            _require(nonce.get("state") == "RESERVED", "NONCE_NOT_RESERVED")
            _require(
                nonce.get("policy_sha256") == validated["policy_sha256"],
                "EXECUTION_CHAIN_POLICY_MISMATCH",
            )
            _require(
                nonce.get("logical_stage_plan_sha256")
                == validated["logical_stage_plan_sha256"]
                and nonce.get("transport_recovery_policy_sha256")
                == validated["transport_recovery_policy_sha256"]
                and nonce.get("transport_recovery_policy_identity")
                == "EXACT_REPLAY_ONLY",
                "EXECUTION_CHAIN_PLAN_OR_RECOVERY_POLICY_MISMATCH",
            )
            _require(
                nonce.get("logical_stage_recovery_policy_sha256")
                == validated["logical_stage_recovery_policy_sha256"],
                "EXECUTION_CHAIN_LOGICAL_RECOVERY_POLICY_MISMATCH",
            )
            _require(
                nonce.get("observer_session_sha256") is None,
                "OBSERVER_ALREADY_CLAIMED_NO_RESTART",
            )
            body = dict(nonce)
            body.pop("nonce_record_sha256", None)
            body["observer_session_sha256"] = session_sha256
            self._replace(
                self._path(execution_id, "nonce"),
                _seal(
                    "novel-flywheel-full-short-nonce-record-v1", body,
                    "nonce_record_sha256",
                ),
            )

    def consume_nonce_and_record_dispatch(
        self, *, execution_id: str, policy: Mapping[str, Any],
        external_actions_enabled: bool, session_id: str,
        attempt: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Permanently consume once, then record before outbound HTTP.

        The nonce file is replaced first while holding the exclusive lock. If
        the process stops before the ledger replacement, the durable consumed
        nonce still makes every restart fail closed.
        """

        validated = self._verify_store_binding(policy)
        session_sha256 = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        with self._locked():
            _require(
                not self._path(execution_id, "completion").exists(),
                "EXECUTION_ALREADY_COMPLETED",
            )
            permission = self._verify_seal(
                self._read(execution_id, "permission"),
                domain="novel-flywheel-full-short-permission-v1",
                field="permission_sha256", reason="PERMISSION_SHA256_MISMATCH",
            )
            approval = self._verify_seal(
                self._read(execution_id, "approval"),
                domain="novel-flywheel-full-short-jit-approval-v1",
                field="signed_approval_sha256", reason="APPROVAL_SHA256_MISMATCH",
            )
            nonce = self._verify_seal(
                self._read(execution_id, "nonce"),
                domain="novel-flywheel-full-short-nonce-record-v1",
                field="nonce_record_sha256", reason="NONCE_SHA256_MISMATCH",
            )
            ledger = self._verify_seal(
                self._read(execution_id, "ledger"),
                domain="novel-flywheel-full-short-dispatch-ledger-v1",
                field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
            )
            _require(
                ledger.get("capacity_policy_registry_sha256")
                == validated["capacity_policy_registry_sha256"],
                "EXECUTION_CHAIN_CAPACITY_POLICY_MISMATCH",
            )
            attempts = list(ledger.get("attempts") or [])
            for value in (permission, approval, nonce, ledger):
                _require(
                    value.get("execution_id") == execution_id
                    and value.get("policy_sha256") == validated["policy_sha256"]
                    and value.get("store_root_sha256") == self.store_root_sha256
                    and value.get("logical_stage_plan_sha256")
                    == validated["logical_stage_plan_sha256"]
                    and value.get("transport_recovery_policy_sha256")
                    == validated["transport_recovery_policy_sha256"]
                    and value.get("transport_recovery_policy_identity")
                    == "EXACT_REPLAY_ONLY",
                    "EXECUTION_CHAIN_MISMATCH",
                )
                _require(
                    value.get("logical_stage_recovery_policy_sha256")
                    == validated["logical_stage_recovery_policy_sha256"],
                    "EXECUTION_CHAIN_LOGICAL_RECOVERY_POLICY_MISMATCH",
                )
            _require(
                permission.get("state") == "ACTIVE"
                and approval.get("state") == "SIGNED"
                and approval.get("permission_sha256")
                == permission.get("permission_sha256")
                and nonce.get("signed_approval_sha256")
                == approval.get("signed_approval_sha256")
                and ledger.get("nonce_sha256") == nonce.get("nonce_sha256"),
                "EXECUTION_CHAIN_LINK_MISMATCH",
            )
            for value in (permission, approval, nonce):
                _require(
                    value.get("external_actions_enabled")
                    is external_actions_enabled,
                    "EXTERNAL_ACTION_AUTHORITY_MISMATCH",
                )
            _require(
                attempt.get("ordinal") == len(attempts) + 1,
                "DUPLICATE_OR_RACING_DISPATCH",
            )
            _require(
                len(attempts) < validated["hard_max_provider_requests"],
                "PROVIDER_REQUEST_CAP_EXHAUSTED",
            )
            logical_stage_id = str(attempt.get("logical_stage_id") or "")
            prior_logical_attempts = [
                item for item in attempts
                if item.get("logical_stage_id", item.get("stage"))
                == logical_stage_id
            ]
            _require(
                len(prior_logical_attempts)
                < validated["max_physical_attempts_per_logical_stage"],
                "LOGICAL_STAGE_PHYSICAL_ATTEMPT_CAP_EXHAUSTED",
            )
            _require(
                str(attempt.get("physical_attempt_id") or "")
                not in {
                    str(item.get("physical_attempt_id") or "")
                    for item in attempts
                },
                "DUPLICATE_PHYSICAL_ATTEMPT_ID",
            )
            if attempt.get("stage_role") == (
                "PLANNING_FINAL_ARTIFACT_RECOVERY"
            ):
                _require(
                    sum(
                        1 for item in prior_logical_attempts
                        if item.get("stage_role")
                        == "PLANNING_FINAL_ARTIFACT_RECOVERY"
                    )
                    < validated[
                        "max_reasoning_only_recovery_dispatches_per_logical_stage"
                    ],
                    "REASONING_ONLY_RECOVERY_CAP_EXHAUSTED",
                )
            if attempts:
                _require(
                    attempts[-1].get("state") in _CLOSED_LOCAL_ATTEMPT_STATES
                    and attempts[-1].get("session_id") == session_id,
                    "AMBIGUOUS_OR_UNCLOSED_DISPATCH_NO_RESTART",
                )
            requested_tokens = int(attempt.get("requested_output_tokens") or 0)
            _require(
                0 < requested_tokens
                <= validated["per_call_output_token_hard_cap"],
                "PER_CALL_OUTPUT_TOKEN_CAP_EXHAUSTED",
            )
            _require(
                sum(int(item.get("requested_output_tokens") or 0)
                    for item in attempts) + requested_tokens
                <= validated["total_output_token_hard_cap"],
                "TOTAL_OUTPUT_TOKEN_CAP_EXHAUSTED",
            )
            if not attempts:
                _require(
                    nonce.get("state") in {
                        "RESERVED", "CONSUMED_DISPATCH_COMMIT_PENDING",
                    },
                    "NONCE_NOT_DISPATCH_READY",
                )
                _require(
                    nonce.get("observer_session_sha256") == session_sha256,
                    "OBSERVER_SESSION_MISMATCH",
                )
                if nonce.get("state") == "CONSUMED_DISPATCH_COMMIT_PENDING":
                    readiness = nonce.get("dispatch_readiness")
                    _require(
                        isinstance(readiness, Mapping)
                        and domain_sha256(
                            "novel-flywheel-full-short-dispatch-readiness-v1",
                            readiness,
                        ) == nonce.get("dispatch_readiness_receipt_sha256")
                        == ledger.get("dispatch_readiness_receipt_sha256"),
                        "DISPATCH_READINESS_RECEIPT_MISMATCH",
                    )
                    readiness_attempt_fields = {
                        "logical_stage_id", "physical_attempt_id",
                        "role_binding_sha256", "route_fingerprint",
                        "destination_sha256", "request_shape_sha256",
                        "provider_payload_sha256", "egress_intent_sha256",
                        "capacity_policy_registry_sha256",
                        "capacity_plan_sha256",
                        "capacity_admission_receipt_sha256",
                        "capacity_admission_status",
                        "requested_output_tokens",
                    }
                    _require(
                        all(
                            readiness.get(field) == attempt.get(field)
                            for field in readiness_attempt_fields
                        )
                        and readiness.get("observer_session_sha256")
                        == session_sha256
                        and readiness.get(
                            "provider_request_count_before_commit"
                        ) == 0,
                        "DISPATCH_ATTEMPT_READINESS_MISMATCH",
                    )
                consumed_body = dict(nonce)
                consumed_body.pop("nonce_record_sha256", None)
                consumed_body.update({
                    "state": "CONSUMED",
                    "dispatch_attempt_count": 1,
                    "consumed_at": _now(),
                    "consumed_session_sha256": session_sha256,
                })
                self._replace(
                    self._path(execution_id, "nonce"),
                    _seal(
                        "novel-flywheel-full-short-nonce-record-v1",
                        consumed_body, "nonce_record_sha256",
                    ),
                )
            else:
                _require(nonce.get("state") == "CONSUMED", "NONCE_NOT_CONSUMED")
                _require(
                    nonce.get("consumed_session_sha256") == session_sha256,
                    "NONCE_ALREADY_CONSUMED_NO_RESTART",
                )
                nonce_body = dict(nonce)
                nonce_body.pop("nonce_record_sha256", None)
                nonce_body["dispatch_attempt_count"] = len(attempts) + 1
                self._replace(
                    self._path(execution_id, "nonce"),
                    _seal(
                        "novel-flywheel-full-short-nonce-record-v1",
                        nonce_body, "nonce_record_sha256",
                    ),
                )
            _require(
                ledger.get("policy_sha256") == validated["policy_sha256"],
                "EXECUTION_CHAIN_POLICY_MISMATCH",
            )
            attempts.append(deepcopy(dict(attempt)))
            ledger_body = dict(ledger)
            ledger_body.pop("ledger_sha256", None)
            ledger_body["attempts"] = attempts
            ledger_body["total_requested_output_tokens"] = sum(
                int(item["requested_output_tokens"]) for item in attempts
            )
            ledger_body["state"] = "DISPATCH_IN_FLIGHT"
            ledger_body["nonce_disposition"] = "CONSUMED"
            ledger_body["updated_at"] = _now()
            sealed = _seal(
                "novel-flywheel-full-short-dispatch-ledger-v1",
                ledger_body, "ledger_sha256",
            )
            self._replace(self._path(execution_id, "ledger"), sealed)
            return sealed

    def _update_ledger(
        self, execution_id: str, mutator: Any,
    ) -> dict[str, Any]:
        with self._locked():
            _require(
                not self._path(execution_id, "completion").exists(),
                "EXECUTION_ALREADY_COMPLETED",
            )
            current = self._read(execution_id, "ledger")
            body = dict(current)
            digest = body.pop("ledger_sha256", None)
            _require(
                digest == domain_sha256(
                    "novel-flywheel-full-short-dispatch-ledger-v1", body,
                ),
                "LEDGER_SHA256_MISMATCH",
            )
            changed = mutator(deepcopy(body))
            _require(isinstance(changed, dict), "LEDGER_MUTATION_INVALID")
            if changed == body:
                body["ledger_sha256"] = digest
                return body
            _validate_ledger_mutation_v1(
                body, changed, mutation_kind="ORDINARY",
            )
            changed["updated_at"] = _now()
            value = _seal(
                "novel-flywheel-full-short-dispatch-ledger-v1", changed,
                "ledger_sha256",
            )
            self._replace(self._path(execution_id, "ledger"), value)
            return value

    def update_ledger(
        self, execution_id: str, mutator: Any,
    ) -> dict[str, Any]:
        """Apply an ordinary ledger transition; reconciliation is not public."""

        return self._update_ledger(
            execution_id, mutator,
        )

    @full_short_boundary_entry("FS.TERMINAL.VERIFY_COMMIT")
    def commit_completion(
        self, *, execution_id: str, policy: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Durably close the single-use execution before returning success."""

        value = self._verify_seal(
            receipt, domain="novel-flywheel-full-short-completion-receipt-v1",
            field="completion_receipt_sha256",
            reason="COMPLETION_RECEIPT_SHA256_MISMATCH",
        )
        _require(value.get("schema") == COMPLETION_SCHEMA, "COMPLETION_SCHEMA_MISMATCH")
        _require(value.get("execution_id") == execution_id, "EXECUTION_CHAIN_ID_MISMATCH")
        validated = self._verify_store_binding(policy)
        _require(
            value.get("policy_sha256") == validated["policy_sha256"],
            "EXECUTION_CHAIN_POLICY_MISMATCH",
        )
        with self._locked():
            permission = self._verify_seal(
                self._read(execution_id, "permission"),
                domain="novel-flywheel-full-short-permission-v1",
                field="permission_sha256", reason="PERMISSION_SHA256_MISMATCH",
            )
            approval = self._verify_seal(
                self._read(execution_id, "approval"),
                domain="novel-flywheel-full-short-jit-approval-v1",
                field="signed_approval_sha256", reason="APPROVAL_SHA256_MISMATCH",
            )
            nonce = self._verify_seal(
                self._read(execution_id, "nonce"),
                domain="novel-flywheel-full-short-nonce-record-v1",
                field="nonce_record_sha256", reason="NONCE_SHA256_MISMATCH",
            )
            ledger = self._verify_seal(
                self._read(execution_id, "ledger"),
                domain="novel-flywheel-full-short-dispatch-ledger-v1",
                field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
            )
            _require(nonce.get("state") == "CONSUMED", "NONCE_NOT_CONSUMED")
            for chain_value in (permission, approval, nonce, ledger):
                _require(
                    chain_value.get("execution_id") == execution_id
                    and chain_value.get("policy_sha256")
                    == validated["policy_sha256"]
                    and chain_value.get("store_root_sha256")
                    == self.store_root_sha256
                    and chain_value.get("logical_stage_plan_sha256")
                    == validated["logical_stage_plan_sha256"]
                    and chain_value.get("transport_recovery_policy_sha256")
                    == validated["transport_recovery_policy_sha256"]
                    and chain_value.get("transport_recovery_policy_identity")
                    == "EXACT_REPLAY_ONLY",
                    "EXECUTION_CHAIN_MISMATCH",
                )
                _require(
                    chain_value.get("logical_stage_recovery_policy_sha256")
                    == validated["logical_stage_recovery_policy_sha256"],
                    "EXECUTION_CHAIN_LOGICAL_RECOVERY_POLICY_MISMATCH",
                )
            _require(
                approval.get("permission_sha256") == permission.get("permission_sha256")
                and nonce.get("signed_approval_sha256")
                == approval.get("signed_approval_sha256")
                and ledger.get("nonce_sha256") == nonce.get("nonce_sha256"),
                "EXECUTION_CHAIN_LINK_MISMATCH",
            )
            _require(
                value.get("permission_sha256") == permission.get("permission_sha256")
                and value.get("signed_approval_sha256")
                == approval.get("signed_approval_sha256")
                and value.get("nonce_sha256") == nonce.get("nonce_sha256")
                and value.get("dispatch_ledger_sha256") == ledger.get("ledger_sha256"),
                "COMPLETION_CHAIN_MISMATCH",
            )
            capacity_receipts = self.verify_completion_capacity_receipts(
                execution_id=execution_id, policy=validated, ledger=ledger,
            )
            _require(
                value.get("capacity_admission_receipt_sha256s")
                == [
                    item["capacity_admission_receipt_sha256"]
                    for item in capacity_receipts
                ],
                "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID",
            )
            attempts = ledger.get("attempts")
            _require(
                ledger.get("state") == "READY_FOR_NEXT_STAGE"
                and isinstance(attempts, list)
                and bool(attempts)
                and all(item.get("state") in _CLOSED_LOCAL_ATTEMPT_STATES
                        for item in attempts)
                and value.get("provider_request_count") == len(attempts),
                "COMPLETION_LEDGER_NOT_EXACT",
            )
            self._exclusive_write(self._path(execution_id, "completion"), value)
        runtime_kernel = active_full_short_kernel_v1()
        if runtime_kernel is not None:
            runtime_kernel.mark_completed(
                completion_receipt_sha256=str(
                    value["completion_receipt_sha256"]
                ),
            )
        return value

    def completion_exists(self, execution_id: str) -> bool:
        """Cheap preflight only; the locked dispatch mutation rechecks it."""

        return self._path(execution_id, "completion").exists()


class FullShortDispatchLedgerObserverV1:
    """Durable observer attached to the production ``HttpProvider`` seam."""

    exact_full_short_execution = True

    def __init__(
        self, *, store: FullShortDurableExecutionStoreV1,
        execution_id: str, policy: Mapping[str, Any],
        authorized_routes: tuple[Mapping[str, Any], ...],
        egress_policy: Mapping[str, Any], session_id: str | None = None,
        external_actions_enabled: bool = False,
        live_authority_recheck: Callable[[], None] | None = None,
        outer_campaign_usage_guard: Mapping[str, Any] | None = None,
        external_workload_capacity_issuer: object | None = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.execution_id = execution_id
        self.policy = validate_policy_v1(policy)
        _require(bool(authorized_routes), "OBSERVER_ROUTE_BINDINGS_REQUIRED")
        self.authorized_routes = tuple(deepcopy(dict(item)) for item in authorized_routes)
        _require(
            _canonical_sha256(list(self.authorized_routes))
            == self.policy["route_manifest_sha256"],
            "ROUTE_MANIFEST_DRIFT",
        )
        destinations = sorted({str(item.get("destination") or "").rstrip("/")
                               for item in self.authorized_routes})
        _require(
            all(destination.startswith("https://") for destination in destinations),
            "DESTINATION_BINDING_INVALID",
        )
        _require(
            _canonical_sha256(destinations)
            == self.policy["destination_manifest_sha256"],
            "DESTINATION_MANIFEST_DRIFT",
        )
        _require(
            _canonical_sha256(egress_policy) == self.policy["egress_policy_sha256"],
            "EGRESS_POLICY_DRIFT",
        )
        _require(
            set(egress_policy) == {"allowed", "forbidden"}
            and tuple(egress_policy.get("allowed") or ())
            == _FULL_SHORT_EGRESS_ALLOWED
            and tuple(egress_policy.get("forbidden") or ())
            == _FULL_SHORT_EGRESS_FORBIDDEN,
            "EGRESS_POLICY_NOT_CLOSED",
        )
        self.egress_policy_sha256 = self.policy["egress_policy_sha256"]
        self.session_id = session_id or secrets.token_hex(16)
        self.external_actions_enabled = external_actions_enabled
        self.live_authority_recheck = live_authority_recheck
        self.outer_campaign_usage_guard = (
            validate_full_short_outer_campaign_usage_guard_v1(
                outer_campaign_usage_guard
            )
            if outer_campaign_usage_guard is not None else None
        )
        self.wall_clock = wall_clock
        self.external_workload_capacity_issuer = external_workload_capacity_issuer
        self.pending_ordinal: int | None = None
        self.bound_route: dict[str, Any] | None = None
        self.expected_provider_payload: dict[str, Any] | None = None
        self.egress_intent_sha256: str | None = None
        self.pending_stage_context: dict[str, Any] | None = None
        self.pending_capacity_plan_sha256: str | None = None
        self.pending_capacity_receipt: dict[str, Any] | None = None
        self.capacity_dispatch_token_authorized = False
        self.capture_store = ProviderResponseCaptureStoreV1(
            repo_root=self.store.repo_root,
            store_root=self.store.root / "provider-response-captures-v1",
        )
        if self.store.nonce_exists(execution_id):
            # Compatibility for already-materialized offline fixtures.  The
            # production runner uses the nonce-absent branch below.
            _require(
                external_actions_enabled is False,
                "READINESS_LESS_NONCE_LIVE_DISPATCH_FORBIDDEN",
            )
            ready_chain = self.store.verify_ready_chain(
                execution_id=execution_id, policy=self.policy,
                external_actions_enabled=external_actions_enabled,
            )
            _require(
                isinstance(ready_chain, Mapping)
                and set(ready_chain) == {
                    "permission", "approval", "nonce", "ledger",
                }
                and all(
                    isinstance(ready_chain[field], Mapping)
                    for field in ready_chain
                ),
                "EXECUTION_CHAIN_CONTEXT_INVALID",
            )
            self.store.claim_observer_session(
                execution_id=execution_id, policy=self.policy,
                session_id=self.session_id,
            )
        else:
            self.store.verify_predispatch_chain(
                execution_id=execution_id, policy=self.policy,
                external_actions_enabled=external_actions_enabled,
            )
            self.store.claim_predispatch_observer_session(
                execution_id=execution_id, policy=self.policy,
                session_id=self.session_id,
                external_actions_enabled=external_actions_enabled,
            )

    def _sealed_route_binding(self, *, route: str, role: str) -> dict[str, Any]:
        lane = "fallback" if route == "configured_fallback" else route
        _require(lane in {"primary", "fallback"},
                 "CAPACITY_ROUTE_IDENTITY_INVALID")
        matches = [
            deepcopy(dict(item)) for item in self.authorized_routes
            if item.get("role") == role and item.get("lane") == lane
        ]
        _require(len(matches) == 1, "CAPACITY_ROUTE_BINDING_DRIFT")
        sealed = matches[0]
        route_source = sealed.get("route_context_capability_source")
        if route_source == (
            RouteContextCapabilitySourceV1
            .VERIFIED_EXTERNAL_WORKLOAD_EVIDENCE.value
        ):
            expected = (
                self._validate_pending_logical_stage_plan()
                if self.pending_stage_context is not None
                else self._next_logical_stage_plan_entry()
            )
            request_family_sha256 = (
                full_short_workload_request_family_sha256_v1(
                    expected,
                    provider=str(sealed.get("provider_name") or ""),
                    operator=str(sealed.get("provider_operator") or ""),
                    destination=str(sealed.get("destination") or ""),
                    protocol=str(sealed.get("protocol") or ""),
                    model=str(sealed.get("model_name") or ""),
                    route_fingerprint_sha256=str(
                        sealed.get("route_fingerprint") or ""
                    ),
                )
            )
            families = sealed.get("external_workload_evidence_families")
            _require(
                isinstance(families, list)
                and all(
                    isinstance(item, Mapping)
                    and set(item) == _EXTERNAL_WORKLOAD_FAMILY_FIELDS_V1
                    for item in families
                ),
                "EXTERNAL_WORKLOAD_EVIDENCE_FAMILY_INVALID",
            )
            selected = [
                dict(item) for item in families
                if item.get("request_family_sha256")
                == request_family_sha256
            ]
            _require(
                len(selected) == 1,
                "EXTERNAL_WORKLOAD_EVIDENCE_FAMILY_MISSING",
            )
            family = selected[0]
            _require(
                _HEX64.fullmatch(str(family.get("request_sha256") or ""))
                is not None
                and _HEX64.fullmatch(
                    str(family.get("evidence_sha256") or "")
                )
                is not None
                and _HEX64.fullmatch(str(
                    family.get("authorization_sha256") or ""
                )) is not None
                and family.get("final_execution_head")
                == self.policy["execution_head"]
                and type(family.get("input_tokens")) is int
                and family["input_tokens"] > 0
                and type(family.get("requested_output_tokens")) is int
                and family["requested_output_tokens"]
                >= expected["requested_output_tokens"]
                and type(family.get(
                    "proven_workload_context_lower_bound_tokens"
                )) is int
                and family[
                    "proven_workload_context_lower_bound_tokens"
                ] == family["input_tokens"]
                + family["requested_output_tokens"],
                "EXTERNAL_WORKLOAD_EVIDENCE_FAMILY_INVALID",
            )
            sealed["route_context_capability_limit_tokens"] = family[
                "proven_workload_context_lower_bound_tokens"
            ]
            sealed["max_output_tokens"] = family[
                "requested_output_tokens"
            ]
            sealed["route_capability_sha256"] = family[
                "evidence_sha256"
            ]
            sealed["external_workload_evidence_sha256"] = family[
                "evidence_sha256"
            ]
            sealed["external_workload_request_family_sha256"] = (
                request_family_sha256
            )
        route_limit = sealed.get("route_context_capability_limit_tokens")
        route_max_output = sealed.get("max_output_tokens")
        reasoning_accounting = str(
            sealed.get("reasoning_token_accounting")
            or "INCLUDED_IN_COMPLETION_CAP"
        )
        reasoning_reservation = str(
            sealed.get("reasoning_output_reservation")
            or "WITHIN_COMPLETION_CAP"
        )
        reasoning_reserve = sealed.get(
            "reasoning_token_reserve",
            0 if reasoning_accounting == "INCLUDED_IN_COMPLETION_CAP" else None,
        )
        _require(
            type(route_limit) is int
            and route_limit > 0
            and route_limit <= MAX_CONTEXT_LIMIT_TOKENS_V1
            and route_source in {
                item.value for item in RouteContextCapabilitySourceV1
            },
            "CAPACITY_ROUTE_CONTEXT_LIMIT_INVALID",
        )
        _require(
            type(route_max_output) is int and route_max_output > 0,
            "CAPACITY_ROUTE_CONTEXT_LIMIT_INVALID",
        )
        _require(
            type(reasoning_reserve) is int
            and (
                reasoning_accounting == "INCLUDED_IN_COMPLETION_CAP"
                and reasoning_reservation == "WITHIN_COMPLETION_CAP"
                and reasoning_reserve == 0
                or reasoning_accounting == "SEPARATE_IF_REPORTED"
                and reasoning_reservation
                == "SEPARATE_REPORTED_RESERVATION_REQUIRED"
                and reasoning_reserve > 0
            ),
            "CAPACITY_ROUTE_CONTEXT_LIMIT_INVALID",
        )
        sealed["reasoning_token_accounting"] = reasoning_accounting
        sealed["reasoning_output_reservation"] = reasoning_reservation
        sealed["reasoning_token_reserve"] = reasoning_reserve
        _require(
            not (
                self.external_actions_enabled
                and route_source
                == (
                    RouteContextCapabilitySourceV1
                    .OFFLINE_DETERMINISTIC_GATEWAY_MANIFEST.value
                )
            ),
            "OFFLINE_CONTEXT_CAPABILITY_LIVE_DISPATCH_FORBIDDEN",
        )
        role_binding = {key: sealed.get(key) for key in (
                "role", "lane", "provider_id_sha256", "model_id_sha256",
                "model_name", "protocol", "route_fingerprint", "destination",
                "route_context_capability_limit_tokens",
                "route_context_capability_source",
                "max_output_tokens", "reasoning_token_accounting",
                "reasoning_output_reservation", "reasoning_token_reserve",
                "route_capability_sha256",
                "route_capability_status",
            )}
        if route_source == (
            RouteContextCapabilitySourceV1
            .VERIFIED_EXTERNAL_WORKLOAD_EVIDENCE.value
        ):
            role_binding.update({
                "external_workload_evidence_sha256": sealed[
                    "external_workload_evidence_sha256"
                ],
                "external_workload_request_family_sha256": sealed[
                    "external_workload_request_family_sha256"
                ],
            })
        sealed["role_binding_sha256"] = domain_sha256(
            "novel-flywheel-full-short-role-binding-v1",
            role_binding,
        )
        capability_sha = sealed.get("route_capability_sha256")
        sealed["route_capability_snapshot_sha256"] = (
            capability_sha
            if isinstance(capability_sha, str)
            and _HEX64.fullmatch(capability_sha) is not None
            else domain_sha256(
                "novel-flywheel-offline-route-capability-snapshot-v1",
                {key: sealed.get(key) for key in (
                    "role", "lane", "provider_id_sha256",
                    "model_id_sha256", "model_name", "protocol",
                    "route_fingerprint", "destination",
                    "route_context_capability_limit_tokens",
                    "route_context_capability_source", "max_output_tokens",
                    "reasoning_token_accounting",
                    "reasoning_output_reservation", "reasoning_token_reserve",
                )},
            )
        )
        return sealed

    @full_short_boundary_entry("FS.CAPACITY.ADMIT")
    def capacity_admission_context(
        self, *, route: str, role: str, physical_attempt: int | None = None,
    ) -> dict[str, Any]:
        """Allocate the canonical physical ordinal for capacity planning.

        ``physical_attempt`` is a compatibility assertion only.  Contract
        Runtime schedule slots are not dispatch ordinals: skipped or locally
        denied slots consume no physical attempt.  New callers therefore omit
        it and accept the durable observer's allocation.
        """

        _require(self.pending_ordinal is None, "PRIOR_DISPATCH_STILL_PENDING")
        expected = (
            self._validate_pending_logical_stage_plan()
            if self.pending_stage_context is not None
            else self._next_logical_stage_plan_entry()
        )
        _require(role == expected["role"], "LOGICAL_STAGE_PLAN_ROLE_DRIFT")
        expected_route = str(expected["route_lane"])
        _require(route == expected_route, "CAPACITY_ROUTE_BINDING_DRIFT")
        logical_stage_id = str(expected["logical_stage_id"])
        attempts = list(
            self.store.load_ledger(self.execution_id).get("attempts") or []
        )
        expected_physical_attempt = 1 + sum(
            1 for item in attempts
            if item.get("logical_stage_id") == logical_stage_id
        )
        if (
            expected_physical_attempt
            > self.policy["max_physical_attempts_per_logical_stage"]
        ):
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.PHYSICAL_ATTEMPT_CAP_EXHAUSTED
            )
        if physical_attempt is not None:
            if type(physical_attempt) is not int or physical_attempt < 1:
                raise CapacityAdmissionFailureV1(
                    CapacityFailureCode.INVALID_ATTEMPT_DELTA
                )
            if physical_attempt != expected_physical_attempt:
                raise CapacityAdmissionFailureV1(
                    CapacityFailureCode.PHYSICAL_ATTEMPT_DRIFT
                )
        sealed = self._sealed_route_binding(route=route, role=role)
        logical_capacity_envelope_sha256 = (
            _logical_capacity_envelope_sha256_v1(
                execution_id=self.execution_id,
                policy=self.policy,
                logical_stage_plan_entry=expected,
            )
        )
        physical_attempt_id = "physical-" + domain_sha256(
            "novel-flywheel-full-short-physical-attempt-id-v1",
            {
                "execution_id": self.execution_id,
                "logical_stage_id": logical_stage_id,
                # Global ordinal counts durable dispatches only.  It is not a
                # Contract Runtime recovery-schedule slot.
                "ordinal": len(attempts) + 1,
            },
        )[:32]
        prior_logical_attempts = [
            item for item in attempts
            if item.get("logical_stage_id") == logical_stage_id
        ]
        recovery_stage_role = str(
            (self.pending_stage_context or {}).get("stage_role") or "NORMAL"
        )
        prior_rendered_request_sha256 = None
        recovery_source_capture_receipt_sha256 = None
        if prior_logical_attempts:
            prior_attempt = prior_logical_attempts[-1]
            prior_capacity_receipt = self.store.load_capacity_admission_receipt(
                execution_id=self.execution_id,
                plan_sha256=str(prior_attempt["capacity_plan_sha256"]),
            )
            prior_rendered_request_sha256 = str(
                prior_capacity_receipt["rendered_request_sha256"]
            )
            recovery_source_capture_receipt_sha256 = (
                _capacity_recovery_source_identity_v1(prior_attempt)
            )
            if not isinstance(
                recovery_source_capture_receipt_sha256, str
            ) or _HEX64.fullmatch(
                recovery_source_capture_receipt_sha256
            ) is None:
                raise CapacityAdmissionFailureV1(
                    CapacityFailureCode.INVALID_ATTEMPT_DELTA
                )
            reasoning_policy = (
                "DISABLE_REASONING"
                if recovery_stage_role
                == "PLANNING_FINAL_ARTIFACT_RECOVERY"
                else "PRESERVE_REASONING_POLICY"
            )
        else:
            reasoning_policy = "DEFAULT"
        context = {
            "logical_stage_id": logical_stage_id,
            "physical_attempt": expected_physical_attempt,
            "physical_attempt_id": physical_attempt_id,
            "global_physical_attempt_ordinal": len(attempts) + 1,
            "logical_capacity_envelope_sha256": (
                logical_capacity_envelope_sha256
            ),
            "provider_route_identity_sha256": sealed[
                "role_binding_sha256"
            ],
            "route_context_capability_limit_tokens": sealed[
                "route_context_capability_limit_tokens"
            ],
            "route_context_capability_source": sealed[
                "route_context_capability_source"
            ],
            "route_capability_snapshot_sha256": sealed[
                "route_capability_snapshot_sha256"
            ],
            "route_max_output_tokens": sealed["max_output_tokens"],
            "reasoning_token_accounting": sealed[
                "reasoning_token_accounting"
            ],
            "reasoning_token_reserve": sealed["reasoning_token_reserve"],
            "recovery_stage_role": recovery_stage_role,
            "reasoning_output_reservation": sealed[
                "reasoning_output_reservation"
            ],
            "reasoning_policy": reasoning_policy,
            "prior_rendered_request_sha256": (
                prior_rendered_request_sha256
            ),
            "recovery_source_capture_receipt_sha256": (
                recovery_source_capture_receipt_sha256
            ),
        }
        if sealed["route_context_capability_source"] == (
            RouteContextCapabilitySourceV1
            .VERIFIED_EXTERNAL_WORKLOAD_EVIDENCE.value
        ):
            context["external_workload_capacity_capability"] = (
                _mint_verified_external_workload_capacity_capability_v1(
                    issuer=self.external_workload_capacity_issuer,
                    route_context_capability_limit_tokens=int(
                        sealed["route_context_capability_limit_tokens"]
                    ),
                    route_capability_snapshot_sha256=str(
                        sealed["route_capability_snapshot_sha256"]
                    ),
                    physical_attempt_id=physical_attempt_id,
                    global_physical_attempt_ordinal=len(attempts) + 1,
                    logical_capacity_envelope_sha256=logical_capacity_envelope_sha256,
                    provider_route_identity_sha256=str(sealed["role_binding_sha256"]),
                    requested_output_token_cap=int(expected["requested_output_tokens"]),
                )
            )
        return context

    @full_short_boundary_entry("FS.CAPACITY.ADMIT")
    def bind_capacity_plan(
        self, *, plan: StageCapacityPlanV1, route: str, role: str,
    ) -> str:
        """Durably bind one PASS plan before route/provider resolution."""

        _require(self.pending_capacity_plan_sha256 is None,
                 "CAPACITY_PLAN_ALREADY_PENDING")
        plan.require_pass()
        _require(
            plan.policy_registry_sha256
            == self.policy["capacity_policy_registry_sha256"],
            "CAPACITY_PLAN_POLICY_OR_ADMISSION_DRIFT",
        )
        StageCapacityAdmissionEngineV1.enforce(plan)
        expected = (
            self._validate_pending_logical_stage_plan()
            if self.pending_stage_context is not None
            else self._next_logical_stage_plan_entry()
        )
        context = self.capacity_admission_context(
            route=route, role=role, physical_attempt=plan.physical_attempt,
        )
        _require(
            plan.stage_id == expected["stage_id"]
            and plan.logical_stage_id == context["logical_stage_id"]
            and plan.contract_name == expected["contract_name"]
            and plan.contract_version == expected["contract_version"]
            and plan.contract_schema_sha256
            == expected["contract_schema_sha256"],
            "CAPACITY_PLAN_CONTRACT_OR_STAGE_DRIFT",
        )
        if plan.requested_output_token_cap != expected[
            "requested_output_tokens"
        ]:
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.INVALID_ATTEMPT_DELTA
            )
        _require(
            plan.provider_route_identity_sha256
            == context["provider_route_identity_sha256"]
            and plan.route_context_capability_limit_tokens
            == context["route_context_capability_limit_tokens"]
            and plan.route_context_capability_source.value
            == context["route_context_capability_source"],
            "CAPACITY_PLAN_ROUTE_DRIFT",
        )
        if not (
            plan.physical_attempt_id == context["physical_attempt_id"]
            and plan.global_physical_attempt_ordinal
            == context["global_physical_attempt_ordinal"]
            and plan.logical_capacity_envelope_sha256
            == context["logical_capacity_envelope_sha256"]
            and plan.route_capability_snapshot_sha256
            == context["route_capability_snapshot_sha256"]
            and plan.route_max_output_tokens
            == context["route_max_output_tokens"]
            and plan.reasoning_token_reserve
            == context["reasoning_token_reserve"]
            and plan.reasoning_token_accounting
            == context["reasoning_token_accounting"]
            and plan.reasoning_output_reservation
            == context["reasoning_output_reservation"]
            and plan.recovery_stage_role == context["recovery_stage_role"]
            and plan.reasoning_policy == context["reasoning_policy"]
            and plan.prior_rendered_request_sha256
            == context["prior_rendered_request_sha256"]
            and plan.recovery_source_capture_receipt_sha256
            == context["recovery_source_capture_receipt_sha256"]
            and plan.recovery_prompt_delta_sha256
            == capacity_recovery_prompt_delta_sha256_v1(
                prior_rendered_request_sha256=context[
                    "prior_rendered_request_sha256"
                ],
                rendered_request_sha256=plan.rendered_request_sha256,
                recovery_stage_role=context["recovery_stage_role"],
                reasoning_policy=context["reasoning_policy"],
                recovery_source_capture_receipt_sha256=context[
                    "recovery_source_capture_receipt_sha256"
                ],
                base_rendered_request_sha256=(
                    plan.base_rendered_request_sha256
                ),
                recovery_overlay_kind=plan.recovery_overlay_kind,
                recovery_overlay_sha256=plan.recovery_overlay_sha256,
            )
        ):
            raise CapacityAdmissionFailureV1(
                CapacityFailureCode.INVALID_ATTEMPT_DELTA
            )
        ledger = self.store.load_ledger(self.execution_id)
        prior_attempts = [
            item for item in ledger.get("attempts", [])
            if item.get("logical_stage_id") == plan.logical_stage_id
        ]
        if prior_attempts:
            prior = prior_attempts[-1]
            prior_receipt = self.store.load_capacity_admission_receipt(
                execution_id=self.execution_id,
                plan_sha256=str(prior["capacity_plan_sha256"]),
            )
            validate_capacity_attempt_delta_v1(prior_receipt, plan)
            immutable_delta_fields = (
                "route_capability_snapshot_sha256",
                "external_workload_evidence_sha256",
                "provider_route_identity_sha256",
                "route_context_capability_limit_tokens",
                "route_context_capability_source",
                "route_max_output_tokens",
                "reasoning_token_reserve",
                "reasoning_token_accounting",
                "reasoning_output_reservation",
                "requested_output_token_cap",
                "final_output_reserve",
                "base_rendered_request_sha256",
                "role_sha256",
                "route",
            )
            candidate_delta = {
                "logical_capacity_envelope_sha256": (
                    plan.logical_capacity_envelope_sha256
                ),
                "route_capability_snapshot_sha256": (
                    plan.route_capability_snapshot_sha256
                ),
                "external_workload_evidence_sha256": (
                    plan.route_capability_snapshot_sha256
                    if plan.route_context_capability_source is
                    RouteContextCapabilitySourceV1
                    .VERIFIED_EXTERNAL_WORKLOAD_EVIDENCE
                    else None
                ),
                "provider_route_identity_sha256": (
                    plan.provider_route_identity_sha256
                ),
                "route_context_capability_limit_tokens": (
                    plan.route_context_capability_limit_tokens
                ),
                "route_context_capability_source": (
                    plan.route_context_capability_source.value
                ),
                "route_max_output_tokens": plan.route_max_output_tokens,
                "reasoning_token_reserve": plan.reasoning_token_reserve,
                "reasoning_token_accounting": (
                    plan.reasoning_token_accounting
                ),
                "reasoning_output_reservation": (
                    plan.reasoning_output_reservation
                ),
                "requested_output_token_cap": (
                    plan.requested_output_token_cap
                ),
                "final_output_reserve": plan.final_output_reserve,
                "base_rendered_request_sha256": (
                    plan.base_rendered_request_sha256
                ),
                "role_sha256": hashlib.sha256(
                    role.encode("utf-8")
                ).hexdigest(),
                "route": route,
            }
            if any(
                prior_receipt.get(field) != candidate_delta[field]
                for field in immutable_delta_fields
            ):
                raise CapacityAdmissionFailureV1(
                    CapacityFailureCode.INVALID_ATTEMPT_DELTA
                )
        _require(
            plan.policy_registry_sha256
            == self.policy["capacity_policy_registry_sha256"]
            and plan.admission_status is AdmissionStatus.PASS,
            "CAPACITY_PLAN_POLICY_OR_ADMISSION_DRIFT",
        )
        body = {
            "schema": "FullShortCapacityAdmissionReceiptV1",
            "version": 1,
            "execution_id": self.execution_id,
            "policy_sha256": self.policy["policy_sha256"],
            "capacity_policy_registry_sha256": plan.policy_registry_sha256,
            "capacity_plan_sha256": plan.plan_sha256,
            "stage_id_sha256": hashlib.sha256(
                plan.stage_id.encode("utf-8")
            ).hexdigest(),
            "logical_stage_id": plan.logical_stage_id,
            "physical_attempt": plan.physical_attempt,
            "physical_attempt_id": plan.physical_attempt_id,
            "global_physical_attempt_ordinal": (
                plan.global_physical_attempt_ordinal
            ),
            "logical_capacity_envelope_sha256": (
                plan.logical_capacity_envelope_sha256
            ),
            "route_capability_snapshot_sha256": (
                plan.route_capability_snapshot_sha256
            ),
            "external_workload_evidence_sha256": (
                plan.route_capability_snapshot_sha256
                if plan.route_context_capability_source is
                RouteContextCapabilitySourceV1
                .VERIFIED_EXTERNAL_WORKLOAD_EVIDENCE
                else None
            ),
            "contract_name_sha256": hashlib.sha256(
                plan.contract_name.encode("utf-8")
            ).hexdigest(),
            "contract_version": plan.contract_version,
            "contract_schema_sha256": plan.contract_schema_sha256,
            "provider_route_identity_sha256": (
                plan.provider_route_identity_sha256
            ),
            "stage_operational_context_ceiling_tokens": (
                plan.stage_operational_context_ceiling_tokens
            ),
            "route_context_capability_limit_tokens": (
                plan.route_context_capability_limit_tokens
            ),
            "route_context_capability_source": (
                plan.route_context_capability_source.value
            ),
            "model_context_limit": plan.model_context_limit,
            "provider_wire_input_token_estimate": (
                plan.expected_rendered_input
                + plan.provider_envelope_tokens
                + plan.wrapper_and_estimator_margin_tokens
            ),
            "role_sha256": hashlib.sha256(role.encode("utf-8")).hexdigest(),
            "route": route,
            "rendered_request_sha256": plan.rendered_request_sha256,
            "requested_output_token_cap": plan.requested_output_token_cap,
            "route_max_output_tokens": plan.route_max_output_tokens,
            "final_output_reserve": plan.final_output_reserve,
            "reasoning_token_reserve": plan.reasoning_token_reserve,
            "reasoning_token_accounting": plan.reasoning_token_accounting,
            "reasoning_output_reservation": (
                plan.reasoning_output_reservation
            ),
            "recovery_stage_role": plan.recovery_stage_role,
            "reasoning_policy": plan.reasoning_policy,
            "base_rendered_request_sha256": (
                plan.base_rendered_request_sha256
            ),
            "recovery_overlay_kind": plan.recovery_overlay_kind,
            "recovery_overlay_sha256": plan.recovery_overlay_sha256,
            "prior_rendered_request_sha256": (
                plan.prior_rendered_request_sha256
            ),
            "recovery_prompt_delta_sha256": (
                plan.recovery_prompt_delta_sha256
            ),
            "recovery_source_capture_receipt_sha256": (
                plan.recovery_source_capture_receipt_sha256
            ),
            "admission_status": "PASS",
            "model_request_sha256": None,
            "provider_payload_sha256": None,
            "egress_intent_sha256": None,
            "outbound_request_bytes_sha256": None,
            "destination_sha256": None,
            "state": "PLAN_BOUND_UNCONSUMED",
            "raw_prompt_persisted": False,
            "created_at": _now(),
            "updated_at": _now(),
        }
        capacity_path = self.store._capacity_path(
            self.execution_id, plan.plan_sha256,
        )
        if capacity_path.exists():
            receipt = self.store.load_capacity_admission_receipt(
                execution_id=self.execution_id,
                plan_sha256=plan.plan_sha256,
            )
            immutable_fields = set(body) - {"created_at", "updated_at"}
            _require(
                receipt.get("state") == "PLAN_BOUND_UNCONSUMED"
                and all(receipt.get(field) == body.get(field)
                        for field in immutable_fields),
                "CAPACITY_ADMISSION_RECEIPT_REPLAY_DRIFT",
            )
        else:
            receipt = self.store.create_capacity_admission_receipt(
                execution_id=self.execution_id,
                plan_sha256=plan.plan_sha256,
                body=body,
            )
        self.pending_capacity_plan_sha256 = plan.plan_sha256
        self.pending_capacity_receipt = receipt
        self.capacity_dispatch_token_authorized = False
        return plan.plan_sha256

    def authorize_capacity_dispatch_token(self, token: str) -> None:
        """Authorize the exact capacity token before provider route resolution."""

        _require(
            token == self.pending_capacity_plan_sha256,
            "CAPACITY_DISPATCH_TOKEN_MISSING_OR_STALE",
        )
        receipt = self.store.load_capacity_admission_receipt(
            execution_id=self.execution_id, plan_sha256=token,
        )
        _require(
            receipt == self.pending_capacity_receipt
            and receipt.get("state") == "PLAN_BOUND_UNCONSUMED",
            "CAPACITY_ADMISSION_RECEIPT_STALE",
        )
        self.capacity_dispatch_token_authorized = True

    def _next_logical_stage_plan_entry(self) -> dict[str, Any]:
        ledger = self.store.load_ledger(self.execution_id)
        completed = list(ledger.get("completed_stage_receipts") or [])
        plan = self.policy["logical_stage_plan"]
        _require(len(completed) < len(plan),
                 "LOGICAL_STAGE_PLAN_EXHAUSTED")
        return deepcopy(plan[len(completed)])

    def sealed_route_for_next_logical_stage(
        self, *, stage_id: str, role: str,
    ) -> str:
        """Project the authorized lane before route or credential resolution."""

        expected = self._next_logical_stage_plan_entry()
        _require(
            stage_id == expected["stage_id"]
            and role == expected["role"],
            "LOGICAL_STAGE_PLAN_CONTEXT_DRIFT",
        )
        lane = str(expected["route_lane"])
        _require(
            lane in {"primary", "configured_fallback"},
            "LOGICAL_STAGE_PLAN_ROUTE_LANE_INVALID",
        )
        return lane

    def _validate_pending_logical_stage_plan(self) -> dict[str, Any]:
        pending = self.pending_stage_context
        _require(isinstance(pending, dict),
                 "PREDISPATCH_STAGE_CONTEXT_NOT_BOUND")
        expected = self._next_logical_stage_plan_entry()
        _require(
            pending.get("stage_id") == expected["stage_id"]
            and pending.get("logical_stage_base_id")
            == expected["logical_stage_base_id"]
            and pending.get("logical_stage_id") == expected["logical_stage_id"]
            and pending.get("contract_name") == expected["contract_name"]
            and pending.get("contract_version") == expected["contract_version"]
            and pending.get("contract_schema_sha256")
            == expected["contract_schema_sha256"]
            and pending.get("contract_runtime_input_required")
            is expected["contract_runtime_input_required"],
            "LOGICAL_STAGE_PLAN_CONTEXT_DRIFT",
        )
        pending["logical_stage_ordinal"] = expected["ordinal"]
        return expected

    def bind_stage_context(
        self, *, stage_id: str, contract_name: str, contract_version: int,
        contract_schema_sha256: str,
        contract_runtime_input_required: bool = False,
        contract_attempt_index: int | None = None,
        contract_route: str | None = None,
        contract_route_attempt: int | None = None,
        stage_role: str = "NORMAL",
    ) -> None:
        """Bind the exact local stage/contract before any route resolution."""

        _require(self.pending_ordinal is None, "PRIOR_DISPATCH_STILL_PENDING")
        _require(_ID.fullmatch(stage_id) is not None, "CAPTURE_STAGE_ID_INVALID")
        _require(bool(contract_name), "CAPTURE_CONTRACT_NAME_INVALID")
        _require(type(contract_version) is int and contract_version > 0,
                 "CAPTURE_CONTRACT_VERSION_INVALID")
        _require(_HEX64.fullmatch(contract_schema_sha256) is not None,
                 "CAPTURE_CONTRACT_SCHEMA_INVALID")
        _require(type(contract_runtime_input_required) is bool,
                 "CAPTURE_CONTRACT_INPUT_POLICY_INVALID")
        _require(_ID.fullmatch(stage_role) is not None, "STAGE_ROLE_INVALID")
        contract_identity = (
            contract_attempt_index, contract_route, contract_route_attempt,
        )
        _require(
            all(value is None for value in contract_identity)
            or (
                type(contract_attempt_index) is int
                and contract_attempt_index > 0
                and contract_route in {"primary", "configured_fallback"}
                and type(contract_route_attempt) is int
                and contract_route_attempt > 0
                and contract_route_attempt <= contract_attempt_index
            ),
            "CONTRACT_ATTEMPT_IDENTITY_INVALID",
        )
        logical_stage_id = self._logical_stage_identity(stage_id)
        self.pending_stage_context = {
            "stage_id": stage_id,
            "logical_stage_base_id": stage_id,
            "logical_stage_id": logical_stage_id,
            "contract_name": contract_name,
            "contract_version": contract_version,
            "contract_schema_sha256": contract_schema_sha256,
            "contract_runtime_input_required": contract_runtime_input_required,
            "contract_attempt_index": contract_attempt_index,
            "contract_route": contract_route,
            "contract_route_attempt": contract_route_attempt,
            "capture_enforcement_required": True,
            "stage_role": stage_role,
        }
        self._validate_pending_logical_stage_plan()

    def _logical_stage_identity(self, stage_id: str) -> str:
        """Allocate one durable logical occurrence, reusing only a rejection."""

        attempts = list(
            self.store.load_ledger(self.execution_id).get("attempts") or []
        )
        matching = [
            item for item in attempts
            if item.get("logical_stage_base_id", item.get("logical_stage_id"))
            == stage_id
        ]
        if matching and matching[-1].get("state") == "LOCAL_ATTEMPT_REJECTED":
            logical_stage_id = str(matching[-1].get("logical_stage_id") or "")
            _require(
                _ID.fullmatch(logical_stage_id) is not None,
                "LOGICAL_STAGE_ID_INVALID",
            )
            return logical_stage_id
        occurrence = len({
            str(item.get("logical_stage_id") or "") for item in matching
        }) + 1
        return full_short_logical_stage_id_v1(stage_id, occurrence)

    def bind_route(
        self, *, role: str, lane: str, provider_id: str, model_id: str,
        route_fingerprint: str,
    ) -> None:
        """Bind the next route before ProviderRegistry reads a credential."""

        if self.live_authority_recheck is not None:
            self.live_authority_recheck()
        _require(self.pending_ordinal is None, "PRIOR_DISPATCH_STILL_PENDING")
        _require(
            self.pending_capacity_plan_sha256 is not None
            and self.capacity_dispatch_token_authorized,
            "CAPACITY_DISPATCH_TOKEN_NOT_AUTHORIZED",
        )
        capacity_receipt = self.store.load_capacity_admission_receipt(
            execution_id=self.execution_id,
            plan_sha256=self.pending_capacity_plan_sha256,
        )
        _require(
            capacity_receipt == self.pending_capacity_receipt
            and capacity_receipt.get("state") == "PLAN_BOUND_UNCONSUMED"
            and capacity_receipt.get("route")
            == ("configured_fallback" if lane == "fallback" else lane)
            and capacity_receipt.get("role_sha256")
            == hashlib.sha256(role.encode("utf-8")).hexdigest(),
            "CAPACITY_ADMISSION_ROUTE_OR_ROLE_DRIFT",
        )
        expected_stage = self._next_logical_stage_plan_entry()
        _require(role == expected_stage["role"],
                 "LOGICAL_STAGE_PLAN_ROLE_DRIFT")
        expected_manifest_lane = (
            "fallback"
            if expected_stage["route_lane"] == "configured_fallback"
            else expected_stage["route_lane"]
        )
        _require(lane == expected_manifest_lane,
                 "ROUTE_SWITCH_OR_FALLBACK_FORBIDDEN")
        provider_hash = hashlib.sha256(provider_id.encode("utf-8")).hexdigest()
        model_hash = hashlib.sha256(model_id.encode("utf-8")).hexdigest()
        matches = [item for item in self.authorized_routes if (
            item.get("role") == role
            and item.get("lane") == lane
            and item.get("provider_id_sha256") == provider_hash
            and item.get("model_id_sha256") == model_hash
            and item.get("route_fingerprint") == route_fingerprint
        )]
        _require(len(matches) == 1, "ROUTE_BINDING_DRIFT")
        if self.pending_stage_context is not None:
            expected_stage = self._validate_pending_logical_stage_plan()
            _require(role == expected_stage["role"],
                     "LOGICAL_STAGE_PLAN_ROLE_DRIFT")
        route = self._sealed_route_binding(route=lane, role=role)
        _require(
            route.get("provider_id_sha256") == provider_hash
            and route.get("model_id_sha256") == model_hash
            and route.get("route_fingerprint") == route_fingerprint,
            "ROUTE_BINDING_DRIFT",
        )
        _require(
            route["role_binding_sha256"]
            == capacity_receipt.get("provider_route_identity_sha256"),
            "CAPACITY_ADMISSION_ROUTE_OR_ROLE_DRIFT",
        )
        if self.bound_route is not None:
            _require(
                self.expected_provider_payload is None
                and self.egress_intent_sha256 is None,
                "ROUTE_ALREADY_BOUND",
            )
            # Capacity preflight may resolve more than one already-authorized
            # lane before constructing any model request.  The latest exact
            # manifest member becomes the candidate; wire binding below still
            # makes the eventual dispatch lane/destination immutable.
        self.bound_route = route
        # This observer hook returns directly to ProviderRegistry.resolve,
        # whose next authority boundary is ``secrets.get``.  Check after every
        # potentially slow live-authority and durable-receipt read above.
        self._require_outer_campaign_absolute_deadline_v1()

    def bind_model_request(
        self, *, protocol: str, request: ModelRequest,
    ) -> None:
        """Bind typed model intent before an adapter constructs wire bytes."""

        route = self.bound_route
        _require(route is not None, "ROUTE_NOT_BOUND_BEFORE_MODEL_REQUEST")
        _require(
            self.pending_capacity_plan_sha256 is not None
            and self.pending_capacity_receipt is not None
            and self.capacity_dispatch_token_authorized,
            "CAPACITY_ADMISSION_NOT_BOUND_BEFORE_MODEL_REQUEST",
        )
        _require(self.pending_ordinal is None, "PRIOR_DISPATCH_STILL_PENDING")
        _require(
            self.expected_provider_payload is None,
            "MODEL_REQUEST_ALREADY_BOUND",
        )
        if self.pending_stage_context is None:
            response_schema = request.response_schema or {}
            schema_value = response_schema.get("schema", response_schema)
            stage_id = str(route.get("role") or "model")
            self.pending_stage_context = {
                "stage_id": stage_id,
                "logical_stage_base_id": stage_id,
                "logical_stage_id": self._logical_stage_identity(stage_id),
                "contract_name": str(
                    response_schema.get("name") or "unstructured_text"
                ),
                "contract_version": 1,
                "contract_schema_sha256": _canonical_sha256(schema_value),
                "contract_runtime_input_required": bool(request.response_schema),
                "contract_attempt_index": None,
                "contract_route": None,
                "contract_route_attempt": None,
                "capture_enforcement_required": False,
            }
        expected_stage = self._validate_pending_logical_stage_plan()
        _require(route.get("role") == expected_stage["role"],
                 "LOGICAL_STAGE_PLAN_ROLE_DRIFT")
        _require(
            int(request.max_output_tokens or 8192)
            == expected_stage["requested_output_tokens"],
            "LOGICAL_STAGE_PLAN_OUTPUT_CAP_DRIFT",
        )
        _require(
            request.stage_role
            == self.pending_stage_context.get("stage_role", "NORMAL"),
            "MODEL_REQUEST_STAGE_ROLE_DRIFT",
        )
        expected_reasoning_policy = str(
            self.pending_capacity_receipt.get("reasoning_policy")
        )
        if expected_reasoning_policy == "DISABLE_REASONING":
            _require(
                request.reasoning_directive == "disable_reasoning",
                "MODEL_REQUEST_REASONING_POLICY_DRIFT",
            )
        else:
            _require(
                request.reasoning_directive != "disable_reasoning",
                "MODEL_REQUEST_REASONING_POLICY_DRIFT",
            )
        _require(protocol == route.get("protocol"), "EGRESS_PROTOCOL_DRIFT")
        expected = _expected_provider_payload_v1(
            protocol, request, destination=str(route["destination"]),
        )
        self.expected_provider_payload = expected
        self.egress_intent_sha256 = domain_sha256(
            "novel-flywheel-full-short-egress-intent-v1",
            {
                "protocol": protocol,
                "role_binding_sha256": route["role_binding_sha256"],
                "provider_payload_sha256": _canonical_sha256(expected),
            },
        )
        current_capacity = self.pending_capacity_receipt
        _require(
            len(request.messages) == 2
            and request.messages[0].role == "system"
            and request.messages[1].role == "user",
            "CAPACITY_MODEL_REQUEST_MESSAGE_TOPOLOGY_DRIFT",
        )
        rendered_request_sha256 = hashlib.sha256(
            (
                request.messages[0].content
                + "\n\0"
                + request.messages[1].content
            ).encode("utf-8")
        ).hexdigest()
        _require(
            current_capacity.get("logical_stage_id")
            == self.pending_stage_context.get("logical_stage_id")
            and current_capacity.get("provider_route_identity_sha256")
            == route.get("role_binding_sha256")
            and current_capacity.get(
                "route_context_capability_limit_tokens"
            ) == route.get("route_context_capability_limit_tokens")
            and current_capacity.get("route_context_capability_source")
            == route.get("route_context_capability_source")
            and current_capacity.get("contract_schema_sha256")
            == self.pending_stage_context.get("contract_schema_sha256")
            and current_capacity.get("rendered_request_sha256")
            == rendered_request_sha256
            and current_capacity.get("requested_output_token_cap")
            == int(request.max_output_tokens or 8192)
            and current_capacity.get("final_output_reserve")
            == int(request.max_output_tokens or 8192),
            "CAPACITY_ADMISSION_REQUEST_CONTEXT_DRIFT",
        )
        self.pending_capacity_receipt = (
            self.store.transition_capacity_admission_receipt(
                execution_id=self.execution_id,
                plan_sha256=self.pending_capacity_plan_sha256,
                expected_receipt_sha256=current_capacity[
                    "capacity_admission_receipt_sha256"
                ],
                expected_state="PLAN_BOUND_UNCONSUMED",
                updates={
                    "model_request_sha256": _canonical_sha256(
                        request.model_dump(mode="json")
                    ),
                    "provider_payload_sha256": _canonical_sha256(expected),
                    "egress_intent_sha256": self.egress_intent_sha256,
                    "state": "REQUEST_BOUND_UNCONSUMED",
                    "updated_at": _now(),
                },
            )
        )

    def _enforce_outer_campaign_predispatch_v1(
        self, *, ledger: Mapping[str, Any], requested_output_tokens: int,
    ) -> None:
        guard = self.outer_campaign_usage_guard
        if guard is None:
            _require(
                not any(
                    item.get("outer_campaign_usage_guard") is not None
                    for item in ledger.get("attempts") or []
                ),
                "OUTER_CAMPAIGN_USAGE_GUARD_MISSING_ON_CONTINUATION",
            )
            return
        self._require_outer_campaign_absolute_deadline_v1()
        attempts = list(ledger.get("attempts") or [])
        if attempts:
            usage = verify_full_short_actual_usage_v1(
                ledger=ledger, durable_store=self.store, policy=self.policy,
            )
            _require(isinstance(usage, Mapping), "OUTER_CAMPAIGN_USAGE_MISSING")
            used_input = int(usage["full_short_input_tokens"])
            used_output = int(usage["full_short_output_tokens"])
        else:
            used_input = 0
            used_output = 0
        capacity_receipt = self.pending_capacity_receipt
        _require(
            isinstance(capacity_receipt, Mapping)
            and type(capacity_receipt.get(
                "provider_wire_input_token_estimate"
            )) is int
            and capacity_receipt["provider_wire_input_token_estimate"] > 0,
            "OUTER_CAMPAIGN_NEXT_INPUT_ESTIMATE_NOT_BOUND",
        )
        estimated_next_input = int(
            capacity_receipt["provider_wire_input_token_estimate"]
        )
        try:
            created_at = datetime.fromisoformat(
                str(ledger["created_at"]).replace("Z", "+00:00"),
            )
        except (KeyError, ValueError) as exc:
            raise FullShortExecutionBoundaryError(
                "OUTER_CAMPAIGN_LEDGER_CREATED_AT_INVALID"
            ) from exc
        elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()
        _require(
            elapsed <= guard["remaining_elapsed_seconds"],
            "OUTER_CAMPAIGN_ELAPSED_CAP_EXHAUSTED",
        )
        _require(
            len(attempts) < guard["remaining_provider_requests"],
            "OUTER_CAMPAIGN_PROVIDER_REQUEST_CAP_EXHAUSTED",
        )
        _require(
            used_input + estimated_next_input
            <= guard["remaining_input_tokens"],
            "OUTER_CAMPAIGN_INPUT_TOKEN_CAP_EXHAUSTED",
        )
        _require(
            used_output + requested_output_tokens
            <= guard["remaining_output_tokens"],
            "OUTER_CAMPAIGN_OUTPUT_TOKEN_CAP_EXHAUSTED",
        )

    def _require_outer_campaign_absolute_deadline_v1(self) -> None:
        """Fail closed against the outer campaign's immutable wall deadline."""

        guard = self.outer_campaign_usage_guard
        if guard is None:
            return
        now = self.wall_clock()
        _require(
            isinstance(now, (int, float))
            and not isinstance(now, bool)
            and math.isfinite(float(now)),
            "OUTER_CAMPAIGN_ABSOLUTE_DEADLINE_CLOCK_INVALID",
        )
        _require(
            float(now) < float(guard["absolute_deadline_unix_seconds"]),
            "OUTER_CAMPAIGN_ABSOLUTE_DEADLINE_EXPIRED",
        )

    @full_short_boundary_entry("FS.CONTROL.PREFLIGHT")
    def before_http_dispatch(
        self, *, method: str, url: str, payload: Mapping[str, Any],
        request_bytes: bytes | None = None,
    ) -> None:
        if self.live_authority_recheck is not None:
            self.live_authority_recheck()
        # The live source-truth read above may itself cross the deadline.
        self._require_outer_campaign_absolute_deadline_v1()
        target = urlsplit(url)
        normalized = f"{target.scheme}://{target.hostname}:{target.port or 443}{target.path}"
        _require(method == "POST", "HTTP_METHOD_NOT_AUTHORIZED")
        _require(
            target.scheme == "https" and target.hostname is not None
            and target.username is None and target.password is None
            and not target.query and not target.fragment,
            "DESTINATION_URL_NOT_EXACT",
        )
        route = self.bound_route
        _require(route is not None, "ROUTE_NOT_BOUND_BEFORE_CREDENTIAL_OR_HTTP")
        _require(
            isinstance(self.pending_stage_context, dict),
            "PREDISPATCH_STAGE_CONTEXT_NOT_BOUND",
        )
        _require(normalized == route.get("destination"), "DESTINATION_DRIFT")
        expected_payload = self.expected_provider_payload
        _require(
            expected_payload is not None
            and self.egress_intent_sha256 is not None,
            "MODEL_REQUEST_EGRESS_INTENT_NOT_BOUND",
        )
        _require(
            dict(payload) == expected_payload,
            "EGRESS_PAYLOAD_SCHEMA_OR_CONTENT_DRIFT",
        )
        _require(
            request_bytes is not None or not self.external_actions_enabled,
            "MATERIALIZED_REQUEST_BYTES_REQUIRED",
        )
        if request_bytes is not None:
            _require(
                isinstance(request_bytes, bytes)
                and json.loads(request_bytes.decode("utf-8")) == dict(payload),
                "MATERIALIZED_REQUEST_BYTES_DRIFT",
            )
        _require(
            str(payload.get("model") or "") == route.get("model_name"),
            "MODEL_BINDING_DRIFT",
        )
        request_shape = {
            "method": method,
            "destination": normalized,
            "model_sha256": hashlib.sha256(
                str(payload.get("model") or "").encode("utf-8"),
            ).hexdigest(),
            "payload_key_sequence": sorted(str(key) for key in payload),
            "requested_output_tokens": int(
                payload.get("max_tokens") or payload.get("max_output_tokens") or 0,
            ),
            "provider_payload_sha256": _canonical_sha256(payload),
            "message_count": len(
                payload.get("messages") or payload.get("input") or [],
            ),
            "tool_count": len(payload.get("tools") or []),
        }
        request_shape_sha256 = domain_sha256(
            "novel-flywheel-full-short-request-shape-v1", request_shape,
        )
        ledger = self.store.load_ledger(self.execution_id)
        attempts = list(ledger.get("attempts") or [])
        try:
            created_at = datetime.fromisoformat(
                str(ledger["created_at"]).replace("Z", "+00:00"),
            )
        except (KeyError, ValueError) as exc:
            raise FullShortExecutionBoundaryError(
                "PREDISPATCH_LEDGER_CREATED_AT_INVALID"
            ) from exc
        _require(
            (datetime.now(timezone.utc) - created_at).total_seconds()
            <= self.policy["maximum_elapsed_seconds"],
            "PREDISPATCH_MAXIMUM_ELAPSED_EXPIRED",
        )
        _require(
            len(attempts) < self.policy["hard_max_provider_requests"],
            "PROVIDER_REQUEST_CAP_EXHAUSTED",
        )
        _require(
            not self.store.completion_exists(self.execution_id),
            "EXECUTION_ALREADY_COMPLETED",
        )
        if attempts:
            previous = attempts[-1]
            _require(
                previous.get("state") in _CLOSED_LOCAL_ATTEMPT_STATES
                and previous.get("session_id") == self.session_id,
                "AMBIGUOUS_OR_UNCLOSED_DISPATCH_NO_RESTART",
            )
        ordinal = len(attempts) + 1
        requested_tokens = request_shape["requested_output_tokens"]
        _require(requested_tokens > 0, "OUTPUT_TOKEN_CAP_INVALID")
        self._enforce_outer_campaign_predispatch_v1(
            ledger=ledger, requested_output_tokens=requested_tokens,
        )
        _require(
            requested_tokens <= self.policy["per_call_output_token_hard_cap"],
            "PER_CALL_OUTPUT_TOKEN_CAP_EXHAUSTED",
        )
        total_requested = sum(
            int(item.get("requested_output_tokens") or 0) for item in attempts
        ) + requested_tokens
        _require(
            total_requested <= self.policy["total_output_token_hard_cap"],
            "TOTAL_OUTPUT_TOKEN_CAP_EXHAUSTED",
        )
        logical_stage_id = str(self.pending_stage_context["logical_stage_id"])
        prior_logical_attempts = [
            item for item in attempts
            if item.get("logical_stage_id", item.get("stage"))
            == logical_stage_id
        ]
        distinct_logical_stage_ids = {
            str(item.get("logical_stage_id", item.get("stage")) or "")
            for item in attempts
        }
        stage_role = str(
            self.pending_stage_context.get("stage_role") or "NORMAL"
        )
        if not prior_logical_attempts:
            _require(
                len(distinct_logical_stage_ids)
                < self.policy["expected_stage_calls"],
                "LOGICAL_STAGE_CALL_CAP_EXHAUSTED",
            )
        else:
            _require(
                len(prior_logical_attempts)
                < self.policy["max_physical_attempts_per_logical_stage"]
                and
                prior_logical_attempts[-1].get("state")
                == "LOCAL_ATTEMPT_REJECTED"
                and not any(
                    item.get("state") == "LOCAL_STAGE_COMPLETE"
                    for item in prior_logical_attempts
                ),
                "LOGICAL_STAGE_REDISPATCH_NOT_AUTHORIZED",
            )
            _require(
                sum(
                    1 for item in prior_logical_attempts
                    if item.get("stage_role")
                    == "PLANNING_FINAL_ARTIFACT_RECOVERY"
                )
                < self.policy[
                    "max_reasoning_only_recovery_dispatches_per_logical_stage"
                ],
                "REASONING_ONLY_RECOVERY_CAP_EXHAUSTED",
            )
            prior_failure_code = prior_logical_attempts[-1].get(
                "local_rejection_failure_code"
            )
            recovery_kind = (
                "reasoning_finalization"
                if stage_role == "PLANNING_FINAL_ARTIFACT_RECOVERY"
                else "business_recovery"
            )
            controller = FullShortExactRecoveryControllerV1()
            controller.record_initial_attempt(logical_stage_id)
            try:
                controller.authorize_shared_second_slot(
                    logical_stage_id,
                    typed_rejection_code=str(
                        prior_failure_code
                        or prior_logical_attempts[-1].get(
                            "local_rejection_failure_kind"
                        )
                        or ""
                    ),
                    recovery_kind=recovery_kind,
                    route_switch=False,
                )
            except ExactRecoveryViolation as exc:
                raise FullShortExecutionBoundaryError(
                    "RECOVERY_REGISTRY_REJECTED_SECOND_SLOT"
                ) from exc
            if prior_failure_code == (
                "reasoning_only_final_artifact_unavailable"
            ):
                _require(
                    stage_role == "PLANNING_FINAL_ARTIFACT_RECOVERY",
                    "REASONING_ONLY_RECOVERY_STAGE_ROLE_REQUIRED",
                )
            else:
                _require(
                    stage_role != "PLANNING_FINAL_ARTIFACT_RECOVERY",
                    "FINALIZATION_RECOVERY_WITHOUT_TYPED_REJECTION",
                )
        expected_capacity_context = self.capacity_admission_context(
            route=str(
                "configured_fallback"
                if route.get("lane") == "fallback"
                else route.get("lane")
            ),
            role=str(route.get("role") or ""),
        )
        physical_attempt_id = str(
            expected_capacity_context["physical_attempt_id"]
        )
        outbound_request_bytes_sha256 = hashlib.sha256(
            request_bytes
            if request_bytes is not None
            else canonical_json_bytes(dict(payload))
        ).hexdigest()
        capacity_plan_sha256 = self.pending_capacity_plan_sha256
        capacity_receipt = self.pending_capacity_receipt
        _require(
            capacity_plan_sha256 is not None
            and capacity_receipt is not None
            and self.capacity_dispatch_token_authorized,
            "CAPACITY_ADMISSION_NOT_READY",
        )
        durable_capacity_receipt = self.store.load_capacity_admission_receipt(
            execution_id=self.execution_id,
            plan_sha256=capacity_plan_sha256,
        )
        _require(
            durable_capacity_receipt == capacity_receipt
            and capacity_receipt.get("state")
            == "REQUEST_BOUND_UNCONSUMED"
            and capacity_receipt.get("admission_status") == "PASS"
            and capacity_receipt.get("capacity_policy_registry_sha256")
            == self.policy["capacity_policy_registry_sha256"]
            and capacity_receipt.get("logical_stage_id") == logical_stage_id
            and capacity_receipt.get("physical_attempt")
            == len(prior_logical_attempts) + 1
            and capacity_receipt.get("physical_attempt_id")
            == expected_capacity_context["physical_attempt_id"]
            and capacity_receipt.get("global_physical_attempt_ordinal")
            == expected_capacity_context[
                "global_physical_attempt_ordinal"
            ]
            and capacity_receipt.get(
                "logical_capacity_envelope_sha256"
            ) == expected_capacity_context[
                "logical_capacity_envelope_sha256"
            ]
            and capacity_receipt.get(
                "route_capability_snapshot_sha256"
            ) == expected_capacity_context[
                "route_capability_snapshot_sha256"
            ]
            and capacity_receipt.get("provider_route_identity_sha256")
            == route.get("role_binding_sha256")
            and capacity_receipt.get(
                "route_context_capability_limit_tokens"
            ) == route.get("route_context_capability_limit_tokens")
            and capacity_receipt.get("route_context_capability_source")
            == route.get("route_context_capability_source")
            and capacity_receipt.get("provider_payload_sha256")
            == request_shape["provider_payload_sha256"]
            and capacity_receipt.get("egress_intent_sha256")
            == self.egress_intent_sha256,
            "CAPACITY_ADMISSION_BINDING_DRIFT",
        )
        capacity_receipt = self.store.transition_capacity_admission_receipt(
            execution_id=self.execution_id,
            plan_sha256=capacity_plan_sha256,
            expected_receipt_sha256=capacity_receipt[
                "capacity_admission_receipt_sha256"
            ],
            expected_state="REQUEST_BOUND_UNCONSUMED",
            updates={
                "outbound_request_bytes_sha256": (
                    outbound_request_bytes_sha256
                ),
                "destination_sha256": hashlib.sha256(
                    normalized.encode("utf-8")
                ).hexdigest(),
                "state": "CONSUMED",
                "consumed_at": _now(),
                "updated_at": _now(),
            },
        )
        self.pending_capacity_receipt = capacity_receipt
        runtime_kernel = active_full_short_kernel_v1()
        if runtime_kernel is not None:
            runtime_kernel.mark_predispatch_ready(PredispatchReadinessV1(
                route_configured=True,
                provider_configured=True,
                model_configured=True,
                endpoint_configured=True,
                capability_sealed=True,
                credential_source_configured=True,
                authorized_credential_readiness=True,
                network_free_request_constructable=True,
                reasoning_policy_projected=True,
                capacity_admission_passed=True,
                request_bytes_sha256=outbound_request_bytes_sha256,
                route_policy_sha256=domain_sha256(
                    "novel-flywheel-full-short-route-policy-v1",
                    {
                        "route_fingerprint": route["route_fingerprint"],
                        "role_binding_sha256": route[
                            "role_binding_sha256"
                        ],
                        "egress_policy_sha256": self.egress_policy_sha256,
                        "egress_intent_sha256": self.egress_intent_sha256,
                    },
                ),
                capacity_policy_registry_sha256=self.policy[
                    "capacity_policy_registry_sha256"
                ],
                capacity_plan_sha256=capacity_plan_sha256,
                capacity_admission_receipt_sha256=capacity_receipt[
                    "capacity_admission_receipt_sha256"
                ],
                logical_capacity_envelope_sha256=capacity_receipt[
                    "logical_capacity_envelope_sha256"
                ],
                route_capability_snapshot_sha256=capacity_receipt[
                    "route_capability_snapshot_sha256"
                ],
                global_physical_attempt_ordinal=capacity_receipt[
                    "global_physical_attempt_ordinal"
                ],
            ))
            runtime_kernel.reserve_dispatch_token(
                logical_stage_id=logical_stage_id,
                physical_attempt=len(prior_logical_attempts) + 1,
                physical_attempt_id=physical_attempt_id,
                request_bytes_sha256=outbound_request_bytes_sha256,
            )
        attempt = {
            "ordinal": ordinal,
            "session_id": self.session_id,
            "request_shape_sha256": request_shape_sha256,
            "requested_output_tokens": requested_tokens,
            "estimated_input_tokens": capacity_receipt[
                "provider_wire_input_token_estimate"
            ],
            "provider_id_sha256": route["provider_id_sha256"],
            "model_id_sha256": route["model_id_sha256"],
            "model_name_sha256": request_shape["model_sha256"],
            "route_fingerprint": route["route_fingerprint"],
            "destination": normalized,
            "destination_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "egress_policy_sha256": self.egress_policy_sha256,
            "egress_intent_sha256": self.egress_intent_sha256,
            "provider_payload_sha256": request_shape[
                "provider_payload_sha256"
            ],
            "protocol_schema_id": f"{route['protocol']}-wire-v1",
            "message_count": request_shape["message_count"],
            "tool_count": request_shape["tool_count"],
            "role_binding_sha256": route["role_binding_sha256"],
            "bound_role": route["role"],
            "bound_lane": route["lane"],
            "stage": self.pending_stage_context["stage_id"],
            "logical_stage_base_id": self.pending_stage_context[
                "logical_stage_base_id"
            ],
            "logical_stage_id": logical_stage_id,
            "physical_attempt_id": physical_attempt_id,
            "global_physical_attempt_ordinal": expected_capacity_context[
                "global_physical_attempt_ordinal"
            ],
            "logical_capacity_envelope_sha256": (
                expected_capacity_context[
                    "logical_capacity_envelope_sha256"
                ]
            ),
            "route_capability_snapshot_sha256": (
                expected_capacity_context[
                    "route_capability_snapshot_sha256"
                ]
            ),
            "rendered_request_sha256": capacity_receipt[
                "rendered_request_sha256"
            ],
            "recovery_stage_role": capacity_receipt[
                "recovery_stage_role"
            ],
            "reasoning_policy": capacity_receipt["reasoning_policy"],
            "base_rendered_request_sha256": capacity_receipt[
                "base_rendered_request_sha256"
            ],
            "recovery_overlay_kind": capacity_receipt[
                "recovery_overlay_kind"
            ],
            "recovery_overlay_sha256": capacity_receipt[
                "recovery_overlay_sha256"
            ],
            "prior_rendered_request_sha256": capacity_receipt[
                "prior_rendered_request_sha256"
            ],
            "recovery_prompt_delta_sha256": capacity_receipt[
                "recovery_prompt_delta_sha256"
            ],
            "recovery_source_capture_receipt_sha256": capacity_receipt[
                "recovery_source_capture_receipt_sha256"
            ],
            "outbound_request_bytes_sha256": (
                outbound_request_bytes_sha256
            ),
            "capacity_policy_registry_sha256": self.policy[
                "capacity_policy_registry_sha256"
            ],
            "capacity_plan_sha256": capacity_plan_sha256,
            "capacity_admission_receipt_sha256": capacity_receipt[
                "capacity_admission_receipt_sha256"
            ],
            "capacity_admission_status": "PASS",
            "stage_role": stage_role,
            "recovery_family": (
                "REASONING_ONLY_FINALIZATION"
                if stage_role == "PLANNING_FINAL_ARTIFACT_RECOVERY"
                else "BUSINESS_OR_PROTOCOL"
                if prior_logical_attempts
                else "NORMAL"
            ),
            "logical_stage_ordinal": self.pending_stage_context[
                "logical_stage_ordinal"
            ],
            "contract_name": self.pending_stage_context["contract_name"],
            "contract_version": self.pending_stage_context["contract_version"],
            "contract_schema_sha256": self.pending_stage_context[
                "contract_schema_sha256"
            ],
            "contract_runtime_input_required": self.pending_stage_context[
                "contract_runtime_input_required"
            ],
            "contract_attempt_index": self.pending_stage_context[
                "contract_attempt_index"
            ],
            "contract_route": self.pending_stage_context["contract_route"],
            "contract_route_attempt": self.pending_stage_context[
                "contract_route_attempt"
            ],
            "capture_enforcement_required": self.pending_stage_context[
                "capture_enforcement_required"
            ],
            "state": "DISPATCH_ATTEMPTED",
            "attempted_at": _now(),
            "response_status_sha256": None,
            "local_stage_receipt_sha256": None,
            "provider_protocol_capture_receipt_sha256": None,
            "provider_protocol_capture_transport_complete": None,
            "provider_protocol_capture_http_success": None,
            "contract_runtime_capture_receipt_sha256": None,
            "contract_runtime_capture_transport_complete": None,
        }
        if self.outer_campaign_usage_guard is not None:
            attempt.update({
                "outer_campaign_usage_guard": deepcopy(
                    self.outer_campaign_usage_guard
                ),
                "provider_reported_actual_usage": None,
                "campaign_accounted_usage": None,
                "attempt_usage_receipt_sha256": None,
            })
        # All local route, capacity, wire, and ledger validation is complete.
        # Recheck immediately before the durable nonce reservation.
        self._require_outer_campaign_absolute_deadline_v1()
        if not self.store.nonce_exists(self.execution_id):
            self.store.reserve_nonce_from_dispatch_readiness(
                execution_id=self.execution_id, policy=self.policy,
                external_actions_enabled=self.external_actions_enabled,
                session_id=self.session_id,
                readiness={
                    "schema": DISPATCH_READINESS_SCHEMA,
                    "version": 1,
                    "execution_id": self.execution_id,
                    "policy_sha256": self.policy["policy_sha256"],
                    "logical_stage_plan_sha256": self.policy[
                        "logical_stage_plan_sha256"
                    ],
                    "permission_sha256": ledger["permission_sha256"],
                    "signed_approval_sha256": ledger[
                        "signed_approval_sha256"
                    ],
                    "predispatch_ledger_sha256": ledger["ledger_sha256"],
                    "observer_session_sha256": hashlib.sha256(
                        self.session_id.encode("utf-8"),
                    ).hexdigest(),
                    "logical_stage_id": logical_stage_id,
                    "physical_attempt_id": physical_attempt_id,
                    "global_physical_attempt_ordinal": (
                        expected_capacity_context[
                            "global_physical_attempt_ordinal"
                        ]
                    ),
                    "logical_capacity_envelope_sha256": (
                        expected_capacity_context[
                            "logical_capacity_envelope_sha256"
                        ]
                    ),
                    "route_capability_snapshot_sha256": (
                        expected_capacity_context[
                            "route_capability_snapshot_sha256"
                        ]
                    ),
                    "role_binding_sha256": route["role_binding_sha256"],
                    "route_fingerprint": route["route_fingerprint"],
                    "destination_sha256": attempt["destination_sha256"],
                    "request_shape_sha256": request_shape_sha256,
                    "provider_payload_sha256": attempt[
                        "provider_payload_sha256"
                    ],
                    "egress_intent_sha256": self.egress_intent_sha256,
                    "capacity_policy_registry_sha256": self.policy[
                        "capacity_policy_registry_sha256"
                    ],
                    "capacity_plan_sha256": capacity_plan_sha256,
                    "capacity_admission_receipt_sha256": capacity_receipt[
                        "capacity_admission_receipt_sha256"
                    ],
                    "capacity_admission_status": "PASS",
                    "requested_output_tokens": requested_tokens,
                    "total_requested_output_tokens": total_requested,
                    "hard_max_provider_requests": self.policy[
                        "hard_max_provider_requests"
                    ],
                    "hard_max_http_posts": self.policy[
                        "hard_max_http_posts"
                    ],
                    "hard_max_network_attempts": self.policy[
                        "hard_max_network_attempts"
                    ],
                    "max_physical_attempts_per_logical_stage": self.policy[
                        "max_physical_attempts_per_logical_stage"
                    ],
                    "expected_stage_calls": self.policy[
                        "expected_stage_calls"
                    ],
                    "per_call_output_token_hard_cap": self.policy[
                        "per_call_output_token_hard_cap"
                    ],
                    "total_output_token_hard_cap": self.policy[
                        "total_output_token_hard_cap"
                    ],
                    "maximum_elapsed_seconds": self.policy[
                        "maximum_elapsed_seconds"
                    ],
                    "provider_request_count_before_commit": len(attempts),
                    "http_post_count_before_commit": len(attempts),
                    "network_request_count_before_commit": 0,
                    "provider_response_count_before_commit": 0,
                    "completed_stage_count_before_commit": len(
                        ledger.get("completed_stage_receipts") or []
                    ),
                },
            )
        self.store.consume_nonce_and_record_dispatch(
            execution_id=self.execution_id, policy=self.policy,
            external_actions_enabled=self.external_actions_enabled,
            session_id=self.session_id, attempt=attempt,
        )
        self.pending_ordinal = ordinal
        if runtime_kernel is not None:
            runtime_kernel.journal.transition(
                KernelExecutionState.DISPATCHING,
                transition_id="provider-dispatching:" + physical_attempt_id,
                boundary_id="FS.DISPATCH.MODEL",
            )

    def before_http_post(self) -> None:
        # Backward-compatible observer hook; the exact dispatch is already
        # durably recorded by ``before_http_dispatch``.
        self._require_outer_campaign_absolute_deadline_v1()
        _require(self.pending_ordinal is not None, "DISPATCH_NOT_DURABLY_RECORDED")

    def before_network_request(self) -> None:
        self._require_outer_campaign_absolute_deadline_v1()
        _require(self.pending_ordinal is not None, "DISPATCH_NOT_DURABLY_RECORDED")

    def _capture_metadata(
        self, *, adapter_id: str, adapter_version: int,
        content_type: str, encoding: str, transport_complete: bool,
        status_code: int | None = None,
        http_success: bool | None = None,
    ) -> dict[str, Any]:
        ordinal = self.pending_ordinal
        route = self.bound_route
        context = self.pending_stage_context
        _require(ordinal is not None, "DISPATCH_NOT_DURABLY_RECORDED")
        _require(isinstance(route, dict), "CAPTURE_ROUTE_NOT_BOUND")
        _require(isinstance(context, dict), "CAPTURE_STAGE_CONTEXT_NOT_BOUND")
        return {
            "execution_id": self.execution_id,
            "call_id": f"{self.execution_id}:{ordinal}",
            "stage_id": context["stage_id"],
            "provider_id_sha256": route["provider_id_sha256"],
            "model_id_sha256": route["model_id_sha256"],
            "route_fingerprint": route["route_fingerprint"],
            "protocol": route["protocol"],
            "contract_name": context["contract_name"],
            "contract_version": context["contract_version"],
            "contract_schema_sha256": context["contract_schema_sha256"],
            "adapter_id": adapter_id,
            "adapter_version": adapter_version,
            "content_type": content_type,
            "encoding": encoding,
            "transport_complete": transport_complete,
            "status_code": status_code,
            "http_success": http_success,
            "response_status_sha256": (
                hashlib.sha256(str(status_code).encode("ascii")).hexdigest()
                if status_code is not None else None
            ),
        }

    def _record_capture_receipt(
        self, *, field: str, receipt_sha256: str,
        transport_complete: bool, http_success: bool | None = None,
        status_code: int | None = None,
        provider_reported_usage: Mapping[str, Any] | None = None,
    ) -> None:
        ordinal = self.pending_ordinal
        _require(ordinal is not None, "DISPATCH_NOT_DURABLY_RECORDED")

        def mutate(body: dict[str, Any]) -> dict[str, Any]:
            attempts = list(body["attempts"])
            current = dict(attempts[ordinal - 1])
            _require(
                current.get("state") in {
                    "DISPATCH_ATTEMPTED", "RESPONSE_RECEIVED",
                },
                "CAPTURE_LEDGER_STATE_INVALID",
            )
            _require(current.get(field) is None, "CAPTURE_RECEIPT_DUPLICATE")
            current[field] = receipt_sha256
            current[
                field.replace("_receipt_sha256", "_transport_complete")
            ] = transport_complete
            if field == "provider_protocol_capture_receipt_sha256":
                _require(
                    type(http_success) is bool,
                    "CAPTURE_HTTP_SUCCESS_CLASSIFICATION_REQUIRED",
                )
                current["provider_protocol_capture_http_success"] = http_success
                _require(
                    type(status_code) is int and 100 <= status_code <= 599,
                    "CAPTURE_HTTP_STATUS_INVALID",
                )
                current["response_status_sha256"] = hashlib.sha256(
                    str(status_code).encode("ascii"),
                ).hexdigest()
                if self.outer_campaign_usage_guard is not None:
                    _require(
                        current.get("outer_campaign_usage_guard")
                        == self.outer_campaign_usage_guard,
                        "OUTER_CAMPAIGN_USAGE_GUARD_DRIFT",
                    )
                    usage = (
                        deepcopy(dict(provider_reported_usage))
                        if provider_reported_usage is not None else None
                    )
                    if usage is not None:
                        _require(
                            int(usage.get("output_tokens") or 0)
                            <= int(current.get("requested_output_tokens") or 0),
                            "PROVIDER_REPORTED_OUTPUT_EXCEEDS_REQUEST_CAP",
                        )
                    accounted_usage = _campaign_accounted_usage_debit_v1(
                        attempt=current, provider_usage=usage,
                    )
                    prior_usage = [
                        item.get("campaign_accounted_usage")
                        for item in attempts[: ordinal - 1]
                    ]
                    _require(
                        all(isinstance(item, Mapping) for item in prior_usage),
                        "PRIOR_CAMPAIGN_ACCOUNTED_USAGE_NOT_DURABLE",
                    )
                    input_total = sum(
                        int(item.get("input_tokens") or 0)
                        for item in prior_usage
                    ) + int(accounted_usage["input_tokens"])
                    output_total = sum(
                        int(item.get("output_tokens") or 0)
                        for item in prior_usage
                    ) + int(accounted_usage["output_tokens"])
                    current["provider_reported_actual_usage"] = usage
                    current["campaign_accounted_usage"] = accounted_usage
                    current["attempt_usage_receipt_sha256"] = (
                        _attempt_actual_usage_receipt_v1(
                            attempt=current,
                            accounted_usage=accounted_usage,
                            guard=self.outer_campaign_usage_guard,
                            full_short_input_tokens=input_total,
                            full_short_output_tokens=output_total,
                        )["attempt_usage_receipt_sha256"]
                    )
            attempts[ordinal - 1] = current
            body["attempts"] = attempts
            return body

        self.store.update_ledger(self.execution_id, mutate)

    def capture_provider_protocol_input(
        self, *, data: bytes, status_code: int, content_type: str,
        encoding: str, transport_complete: bool,
    ) -> None:
        _require(100 <= status_code <= 599, "CAPTURE_HTTP_STATUS_INVALID")
        route = self.bound_route
        _require(isinstance(route, dict), "CAPTURE_ROUTE_NOT_BOUND")
        metadata = self._capture_metadata(
            adapter_id=str(route["protocol"]), adapter_version=1,
            content_type=content_type, encoding=encoding,
            transport_complete=transport_complete,
            status_code=status_code,
            http_success=200 <= status_code < 300,
        )
        receipt = self.capture_store.capture(
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            data=data,
            metadata=metadata,
        )
        receipt_sha256 = domain_sha256(
            "novel-flywheel-provider-response-capture-receipt-v1",
            receipt.document(),
        )
        self.store.create_provider_response_capture_anchor(
            execution_id=self.execution_id,
            ordinal=int(self.pending_ordinal or 0),
            byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
            provider_response_capture_receipt_sha256=receipt_sha256,
        )
        provider_usage: dict[str, Any] | None = None
        usage_error: ProviderResponseCaptureError | None = None
        if self.outer_campaign_usage_guard is not None and 200 <= status_code < 300:
            if transport_complete:
                try:
                    provider_usage = extract_provider_reported_actual_usage_v1(
                        data, protocol=str(route["protocol"]),
                        content_type=content_type, encoding=encoding,
                    )
                except ProviderResponseCaptureError as exc:
                    if str(exc) not in {
                        "PROVIDER_REPORTED_USAGE_MISSING",
                        "PROVIDER_REPORTED_USAGE_INCOMPLETE",
                        "PROVIDER_REPORTED_USAGE_NOT_POSITIVE",
                    }:
                        usage_error = exc
        self._record_capture_receipt(
            field="provider_protocol_capture_receipt_sha256",
            receipt_sha256=receipt_sha256,
            transport_complete=transport_complete,
            http_success=200 <= status_code < 300,
            status_code=status_code,
            provider_reported_usage=provider_usage,
        )
        if usage_error is not None:
            raise usage_error
        if provider_usage is not None:
            usage = verify_full_short_actual_usage_v1(
                ledger=self.store.load_ledger(self.execution_id),
                durable_store=self.store, policy=self.policy,
            )
            _require(
                isinstance(usage, Mapping),
                "OUTER_CAMPAIGN_USAGE_NOT_VERIFIABLE",
            )
        runtime_kernel = active_full_short_kernel_v1()
        if (
            runtime_kernel is not None
            and runtime_kernel.journal.state
            == KernelExecutionState.DISPATCHING
        ):
            runtime_kernel.journal.transition(
                KernelExecutionState.RESPONSE_CAPTURED,
                transition_id="provider-response-captured:" + domain_sha256(
                    "novel-flywheel-provider-response-capture-receipt-v1",
                    receipt.document(),
                ),
                boundary_id="FS.DISPATCH.MODEL",
            )

    def capture_contract_runtime_input(
        self, *, data: bytes, adapter_id: str, adapter_version: int,
        finish_reason: str | None, transport_complete: bool,
    ) -> None:
        metadata = self._capture_metadata(
            adapter_id=adapter_id, adapter_version=adapter_version,
            content_type="text/plain; purpose=contract-runtime-input",
            encoding="utf-8", transport_complete=transport_complete,
        )
        receipt = self.capture_store.capture(
            byte_domain=CONTRACT_RUNTIME_INPUT_BYTES,
            data=data,
            metadata=metadata,
        )
        receipt_sha256 = domain_sha256(
            "novel-flywheel-provider-response-capture-receipt-v1",
            receipt.document(),
        )
        self.store.create_provider_response_capture_anchor(
            execution_id=self.execution_id,
            ordinal=int(self.pending_ordinal or 0),
            byte_domain=CONTRACT_RUNTIME_INPUT_BYTES,
            provider_response_capture_receipt_sha256=receipt_sha256,
        )
        self._record_capture_receipt(
            field="contract_runtime_capture_receipt_sha256",
            receipt_sha256=receipt_sha256,
            transport_complete=transport_complete,
        )

    def provider_protocol_capture_complete(self) -> bool:
        """Return whether the pending attempt has an anchored complete entity."""

        if self.pending_ordinal is None:
            return False
        ledger = self.store.load_ledger(self.execution_id)
        attempts = list(ledger.get("attempts") or [])
        if len(attempts) < self.pending_ordinal:
            return False
        current = attempts[self.pending_ordinal - 1]
        return bool(
            _HEX64.fullmatch(str(current.get(
                "provider_protocol_capture_receipt_sha256"
            )))
            and current.get(
                "provider_protocol_capture_transport_complete"
            ) is True
        )

    def contract_runtime_capture_present(self) -> bool:
        if self.pending_ordinal is None:
            return False
        ledger = self.store.load_ledger(self.execution_id)
        attempts = list(ledger.get("attempts") or [])
        return bool(
            len(attempts) >= self.pending_ordinal
            and attempts[self.pending_ordinal - 1].get(
                "contract_runtime_capture_receipt_sha256"
            )
        )

    def after_http_response(self, *, status_code: int) -> None:
        ordinal = self.pending_ordinal
        _require(ordinal is not None, "DISPATCH_NOT_DURABLY_RECORDED")
        _require(type(status_code) is int, "HTTP_STATUS_INVALID")

        def mutate(body: dict[str, Any]) -> dict[str, Any]:
            attempts = list(body["attempts"])
            current = dict(attempts[ordinal - 1])
            status_sha256 = hashlib.sha256(
                str(status_code).encode("ascii"),
            ).hexdigest()
            if current.get("state") == "HTTP_RESPONSE_FAILED_CLOSED":
                _require(
                    current.get("response_status_sha256") == status_sha256,
                    "HTTP_RESPONSE_STATUS_DRIFT",
                )
                return body
            _require(current.get("state") == "DISPATCH_ATTEMPTED", "DISPATCH_STATE_INVALID")
            if not 200 <= status_code < 300:
                current["state"] = "HTTP_RESPONSE_FAILED_CLOSED"
                current["response_status_sha256"] = status_sha256
                attempts[ordinal - 1] = current
                body["attempts"] = attempts
                body["state"] = "RECONCILIATION_REQUIRED_NO_REDISPATCH"
                return body
            current["state"] = "RESPONSE_RECEIVED"
            current["response_status_sha256"] = status_sha256
            current["response_received_at"] = _now()
            attempts[ordinal - 1] = current
            body["attempts"] = attempts
            body["state"] = "RESPONSE_RECEIVED_AWAITING_LOCAL_RECEIPT"
            return body

        self.store.update_ledger(self.execution_id, mutate)
        _require(200 <= status_code < 300, "HTTP_RESPONSE_NOT_SUCCESSFUL")

    def after_http_failure(
        self, *, failure_kind: str, failure_class: str | None = None,
    ) -> None:
        ordinal = self.pending_ordinal
        if ordinal is None:
            # A local authorization/cap failure before the durable dispatch
            # seam cannot leave request identity attached to a later route.
            # No external completion is possible because no attempt ordinal
            # was recorded.
            if (
                self.pending_capacity_plan_sha256 is not None
                and self.pending_capacity_receipt is not None
                and self.pending_capacity_receipt.get("state")
                == "REQUEST_BOUND_UNCONSUMED"
            ):
                self.store.transition_capacity_admission_receipt(
                    execution_id=self.execution_id,
                    plan_sha256=self.pending_capacity_plan_sha256,
                    expected_receipt_sha256=self.pending_capacity_receipt[
                        "capacity_admission_receipt_sha256"
                    ],
                    expected_state="REQUEST_BOUND_UNCONSUMED",
                    updates={
                        "model_request_sha256": None,
                        "provider_payload_sha256": None,
                        "egress_intent_sha256": None,
                        "state": "PLAN_BOUND_UNCONSUMED",
                        "updated_at": _now(),
                    },
                )
            self.bound_route = None
            self.expected_provider_payload = None
            self.egress_intent_sha256 = None
            self.pending_stage_context = None
            self.pending_capacity_plan_sha256 = None
            self.pending_capacity_receipt = None
            self.capacity_dispatch_token_authorized = False
            return

        def mutate(body: dict[str, Any]) -> dict[str, Any]:
            attempts = list(body["attempts"])
            current = dict(attempts[ordinal - 1])
            if current.get("state") == "HTTP_RESPONSE_FAILED_CLOSED":
                # ``raise_for_status`` and adapter error paths may report the
                # same already-closed response.  Never weaken exact HTTP
                # evidence into an ambiguous transport outcome.
                return body
            complete_capture = bool(
                _HEX64.fullmatch(str(current.get(
                    "provider_protocol_capture_receipt_sha256"
                )))
                and current.get(
                    "provider_protocol_capture_transport_complete"
                ) is True
            )
            if complete_capture:
                http_failed = current.get(
                    "provider_protocol_capture_http_success"
                ) is False
                current["state"] = (
                    "HTTP_RESPONSE_FAILED_CLOSED"
                    if http_failed
                    else "POST_CAPTURE_TERMINAL_CLASSIFICATION_PENDING"
                )
                current[
                    "failure_kind_sha256"
                    if http_failed else "adapter_failure_kind_sha256"
                ] = hashlib.sha256(
                    failure_kind.encode("utf-8"),
                ).hexdigest()
                if http_failed:
                    current["failure_class"] = (
                        failure_class or "http_response_terminal"
                    )
                attempts[ordinal - 1] = current
                body["attempts"] = attempts
                body["state"] = "RECONCILIATION_REQUIRED_NO_REDISPATCH"
                return body
            _require(
                current.get("state") == "DISPATCH_ATTEMPTED",
                "SUCCESSFUL_RESPONSE_CANNOT_BE_REWRITTEN_AS_FAILURE",
            )
            current["state"] = "OUTCOME_UNKNOWN_FAIL_CLOSED"
            current["failure_kind_sha256"] = hashlib.sha256(
                failure_kind.encode("utf-8"),
            ).hexdigest()
            attempts[ordinal - 1] = current
            body["attempts"] = attempts
            body["state"] = "RECONCILIATION_REQUIRED_NO_REDISPATCH"
            return body

        self.store.update_ledger(self.execution_id, mutate)

    def mark_post_capture_terminal_failure(
        self, *, failure_kind: str, failure_class: str,
        contract_attempt_index: int, contract_route: str,
        contract_route_attempt: int,
    ) -> None:
        """Durably type a terminal exception after a complete response.

        This close is deliberately not a recoverable local rejection: the
        provider entity completed, but the provider protocol/adapter boundary
        raised before it could yield a Contract Runtime value.  No later
        network attempt may replace that exact outcome.
        """

        ordinal = self.pending_ordinal
        _require(ordinal is not None, "NO_CAPTURED_RESPONSE_TO_CLOSE")
        _require(bool(failure_kind), "POST_CAPTURE_FAILURE_KIND_INVALID")
        _require(bool(failure_class), "POST_CAPTURE_FAILURE_CLASS_INVALID")

        def mutate(body: dict[str, Any]) -> dict[str, Any]:
            attempts = list(body["attempts"])
            _require(0 < ordinal <= len(attempts), "PENDING_ORDINAL_INVALID")
            current = dict(attempts[ordinal - 1])
            _require(
                current.get("state") in {
                    "DISPATCH_ATTEMPTED", "RESPONSE_RECEIVED",
                    "HTTP_RESPONSE_FAILED_CLOSED",
                    "POST_CAPTURE_TERMINAL_CLASSIFICATION_PENDING",
                    "POST_CAPTURE_TERMINAL_FAILED_CLOSED",
                },
                "POST_CAPTURE_TERMINAL_STATE_INVALID",
            )
            _require(
                _HEX64.fullmatch(str(current.get(
                    "provider_protocol_capture_receipt_sha256"
                ))) is not None
                and current.get(
                    "provider_protocol_capture_transport_complete"
                ) is True,
                "COMPLETE_PROVIDER_CAPTURE_REQUIRED",
            )
            if current.get("state") == "HTTP_RESPONSE_FAILED_CLOSED":
                # The HTTP close is already more exact than a generic adapter
                # terminal classification.  Preserve it byte-for-byte.
                return body
            if current.get("contract_attempt_index") is not None:
                _require(
                    int(current["contract_attempt_index"])
                    == contract_attempt_index
                    and current.get("contract_route") == contract_route
                    and int(current["contract_route_attempt"])
                    == contract_route_attempt,
                    "POST_CAPTURE_ATTEMPT_IDENTITY_MISMATCH",
                )
            failure_kind_sha256 = hashlib.sha256(
                failure_kind.encode("utf-8"),
            ).hexdigest()
            if current.get("state") == "POST_CAPTURE_TERMINAL_FAILED_CLOSED":
                _require(
                    current.get("failure_kind_sha256") == failure_kind_sha256,
                    "POST_CAPTURE_TERMINAL_FAILURE_DRIFT",
                )
                _require(
                    current.get("failure_class") == failure_class
                    and int(current.get("terminal_contract_attempt_index") or 0)
                    == contract_attempt_index
                    and current.get("terminal_contract_route") == contract_route
                    and int(current.get("terminal_contract_route_attempt") or 0)
                    == contract_route_attempt,
                    "POST_CAPTURE_TERMINAL_CLASSIFICATION_DRIFT",
                )
                return body
            current.update({
                "state": "POST_CAPTURE_TERMINAL_FAILED_CLOSED",
                "failure_kind_sha256": failure_kind_sha256,
                "failure_class": failure_class,
                "terminal_contract_attempt_index": contract_attempt_index,
                "terminal_contract_route": contract_route,
                "terminal_contract_route_attempt": contract_route_attempt,
                "terminal_closed_at": _now(),
            })
            attempts[ordinal - 1] = current
            body["attempts"] = attempts
            body["state"] = "RECONCILIATION_REQUIRED_NO_REDISPATCH"
            return body

        self.store.update_ledger(self.execution_id, mutate)

    def mark_local_stage_complete(
        self, *, stage: str, role: str, role_binding_sha256: str,
        output_sha256: str, receipt_sha256: str,
    ) -> None:
        ordinal = self.pending_ordinal
        _require(ordinal is not None, "NO_RESPONSE_TO_COMPLETE")
        _require(_HEX64.fullmatch(output_sha256) is not None, "OUTPUT_SHA256_INVALID")
        _require(_HEX64.fullmatch(receipt_sha256) is not None, "RECEIPT_SHA256_INVALID")
        _require(
            _HEX64.fullmatch(role_binding_sha256) is not None,
            "ROLE_BINDING_SHA256_INVALID",
        )

        def mutate(body: dict[str, Any]) -> dict[str, Any]:
            attempts = list(body["attempts"])
            receipts = list(body.get("completed_stage_receipts") or [])
            _require(0 < ordinal <= len(attempts), "PENDING_ORDINAL_INVALID")
            current = dict(attempts[ordinal - 1])
            _require(
                current.get("ordinal") == ordinal
                and current.get("session_id") == self.session_id
                and current.get("state") == "RESPONSE_RECEIVED",
                "RESPONSE_NOT_RECEIVED",
            )
            if current.get("capture_enforcement_required"):
                _require(
                    _HEX64.fullmatch(str(current.get(
                        "provider_protocol_capture_receipt_sha256"
                    ))) is not None,
                    "PROVIDER_RESPONSE_CAPTURE_REQUIRED",
                )
                if current.get("contract_runtime_input_required"):
                    _require(
                        _HEX64.fullmatch(str(current.get(
                            "contract_runtime_capture_receipt_sha256"
                        ))) is not None,
                        "CONTRACT_RUNTIME_INPUT_CAPTURE_REQUIRED",
                    )
            _require(current.get("bound_role") == role, "STAGE_ROLE_DRIFT")
            _require(current.get("stage") == stage, "STAGE_ID_DRIFT")
            _require(
                current.get("role_binding_sha256") == role_binding_sha256,
                "ROLE_BINDING_DRIFT",
            )
            logical_stage_id = str(current["logical_stage_id"])
            _require(
                not any(
                    item.get("logical_stage_id") == logical_stage_id
                    for item in receipts
                )
                and not any(
                    item.get("logical_stage_id") == logical_stage_id
                    and item.get("state") == "LOCAL_STAGE_COMPLETE"
                    for item in attempts
                ),
                "DUPLICATE_LOGICAL_STAGE_ACCEPTANCE",
            )
            rejected_attempts = [
                item for item in attempts[: ordinal - 1]
                if item.get("logical_stage_id") == logical_stage_id
                and item.get("state") == "LOCAL_ATTEMPT_REJECTED"
            ]
            _require(
                len(rejected_attempts) <= 1,
                "LOGICAL_STAGE_REJECTION_PROVENANCE_INVALID",
            )
            rejected_provenance = [
                {
                    "physical_attempt_id": item["physical_attempt_id"],
                    "ordinal": item["ordinal"],
                    "local_rejection_receipt_sha256": item[
                        "local_rejection_receipt_sha256"
                    ],
                    "failure_kind": item["local_rejection_failure_kind"],
                    "failure_code": item.get(
                        "local_rejection_failure_code"
                    ),
                }
                for item in rejected_attempts
            ]
            current.update({
                "state": "LOCAL_STAGE_COMPLETE",
                "local_stage_receipt_sha256": receipt_sha256,
                "output_sha256": output_sha256,
                "stage": stage,
                "role": role,
            })
            attempts[ordinal - 1] = current
            receipts.append({
                "ordinal": ordinal,
                "logical_stage_ordinal": current["logical_stage_ordinal"],
                "logical_stage_id": current["logical_stage_id"],
                "logical_stage_base_id": current["logical_stage_base_id"],
                "stage": stage,
                "role": role,
                "role_binding_sha256": role_binding_sha256,
                "output_sha256": output_sha256,
                "receipt_sha256": receipt_sha256,
                "accepted_physical_attempt_id": current[
                    "physical_attempt_id"
                ],
                "accepted_stage_role": current.get("stage_role", "NORMAL"),
                "rejected_attempt_provenance": rejected_provenance,
                "accepted_artifact_count": 1,
            })
            body["attempts"] = attempts
            body["completed_stage_receipts"] = receipts
            body["state"] = "READY_FOR_NEXT_STAGE"
            return body

        runtime_kernel = active_full_short_kernel_v1()
        if runtime_kernel is not None:
            _require(
                runtime_kernel.journal.state
                == KernelExecutionState.RESPONSE_CAPTURED,
                "RUNTIME_KERNEL_RESPONSE_CAPTURE_REQUIRED",
            )
            runtime_kernel.journal.transition(
                KernelExecutionState.VALIDATING,
                transition_id="contract-validating:" + receipt_sha256,
                boundary_id="FS.CONTRACT.VALIDATE",
            )
        self.store.update_ledger(self.execution_id, mutate)
        if runtime_kernel is not None:
            runtime_kernel.journal.transition(
                KernelExecutionState.STAGE_ACCEPTED,
                transition_id="stage-accepted:" + receipt_sha256,
                boundary_id="FS.CONTRACT.VALIDATE",
            )
        self.pending_ordinal = None
        self.bound_route = None
        self.expected_provider_payload = None
        self.egress_intent_sha256 = None
        self.pending_stage_context = None
        self.pending_capacity_plan_sha256 = None
        self.pending_capacity_receipt = None
        self.capacity_dispatch_token_authorized = False

    def mark_local_attempt_rejected(
        self, *, stage: str, role: str, role_binding_sha256: str,
        rejection: Mapping[str, Any],
    ) -> None:
        """Durably close one 2xx response rejected by local contract logic.

        The state authorizes only the already-sealed next attempt in this same
        observer session.  It is not a stage receipt and cannot satisfy the
        logical Full Short completion matrix.
        """

        ordinal = self.pending_ordinal
        _require(ordinal is not None, "NO_RESPONSE_TO_REJECT")
        value = dict(rejection)
        runtime_kernel = active_full_short_kernel_v1()
        kernel_rejection_preclosed = bool(
            runtime_kernel is not None
            and value.get("failure_code")
            == "reasoning_only_final_artifact_unavailable"
            and runtime_kernel.recoverable_failure_already_recorded(
                boundary_id="FS.DISPATCH.MODEL",
                failure_code="planning.reasoning_only_no_final",
            )
        )
        if runtime_kernel is not None:
            if not kernel_rejection_preclosed:
                _require(
                    runtime_kernel.journal.state
                    == KernelExecutionState.RESPONSE_CAPTURED,
                    "RUNTIME_KERNEL_RESPONSE_CAPTURE_REQUIRED",
                )
                runtime_kernel.journal.transition(
                    KernelExecutionState.VALIDATING,
                    transition_id=(
                        "contract-validating-rejection:"
                        + hashlib.sha256(
                            canonical_json_bytes(value)
                        ).hexdigest()
                    ),
                    boundary_id="FS.CONTRACT.VALIDATE",
                )
        pre_contract_final_artifact = (
            value.get("schema") == "ProviderFinalArtifactRejectionReceiptV1"
        )
        _require(
            set(value) == (
                _FINAL_ARTIFACT_REJECTION_RECEIPT_FIELDS
                if pre_contract_final_artifact
                else _LOCAL_REJECTION_RECEIPT_FIELDS
            ),
            "LOCAL_REJECTION_RECEIPT_SHAPE_INVALID",
        )
        _require(
            value.get("schema") in {
                "ContractLocalRejectionReceiptV1",
                "ProviderFinalArtifactRejectionReceiptV1",
            }
            and value.get("version") == 1
            and isinstance(value.get("contract_name"), str)
            and bool(value.get("contract_name"))
            and type(value.get("contract_version")) is int
            and int(value["contract_version"]) > 0
            and type(value.get("attempt_index")) is int
            and int(value["attempt_index"]) > 0
            and type(value.get("route_attempt")) is int
            and int(value["route_attempt"]) > 0
            and value.get("failure_kind") in (
                {"final_artifact_unavailable"}
                if pre_contract_final_artifact
                else {
                    "artifact_conversion", "business_incomplete",
                    "domain_validation",
                }
            )
            and type(value.get("raw_content_persisted")) is bool,
            "LOCAL_REJECTION_RECEIPT_INVALID",
        )
        if pre_contract_final_artifact:
            _require(
                isinstance(value.get("failure_code"), str)
                and bool(value.get("failure_code"))
                and value.get("contract_runtime_input_present") is False
                and value.get("raw_content_persisted") is False,
                "FINAL_ARTIFACT_REJECTION_RECEIPT_INVALID",
            )
        for field in ((
            "contract_schema_sha256", "failure_reason_sha256",
            "provider_output_shape_sha256",
        ) if pre_contract_final_artifact else (
            "contract_schema_sha256", "failure_reason_sha256",
            "response_text_sha256", "conversion_audit_sha256",
        )):
            _require(
                _HEX64.fullmatch(str(value.get(field))) is not None,
                "LOCAL_REJECTION_RECEIPT_HASH_INVALID",
            )
        _require(
            _HEX64.fullmatch(role_binding_sha256) is not None,
            "ROLE_BINDING_SHA256_INVALID",
        )
        def mutate(body: dict[str, Any]) -> dict[str, Any]:
            attempts = list(body["attempts"])
            _require(0 < ordinal <= len(attempts), "PENDING_ORDINAL_INVALID")
            current = dict(attempts[ordinal - 1])
            _require(
                current.get("ordinal") == ordinal
                and current.get("session_id") == self.session_id
                and current.get("state") == "RESPONSE_RECEIVED",
                "RESPONSE_NOT_RECEIVED",
            )
            if current.get("capture_enforcement_required"):
                _require(
                    _HEX64.fullmatch(str(current.get(
                        "provider_protocol_capture_receipt_sha256"
                    ))) is not None,
                    "PROVIDER_RESPONSE_CAPTURE_REQUIRED",
                )
                if (
                    current.get("contract_runtime_input_required")
                    and not pre_contract_final_artifact
                ):
                    _require(
                        _HEX64.fullmatch(str(current.get(
                            "contract_runtime_capture_receipt_sha256"
                        ))) is not None,
                        "CONTRACT_RUNTIME_INPUT_CAPTURE_REQUIRED",
                    )
                if pre_contract_final_artifact:
                    _require(
                        current.get(
                            "contract_runtime_capture_receipt_sha256"
                        ) is None,
                        "FINAL_ARTIFACT_REJECTION_AFTER_CONTRACT_INPUT",
                    )
            _require(current.get("bound_role") == role, "STAGE_ROLE_DRIFT")
            _require(current.get("stage") == stage, "STAGE_ID_DRIFT")
            _require(
                current.get("role_binding_sha256") == role_binding_sha256,
                "ROLE_BINDING_DRIFT",
            )
            _require(
                current.get("contract_name") == value["contract_name"]
                and int(current.get("contract_version") or 0)
                == int(value["contract_version"])
                and current.get("contract_schema_sha256")
                == value["contract_schema_sha256"],
                "LOCAL_REJECTION_CONTRACT_IDENTITY_DRIFT",
            )
            contract_route = value.get("route")
            manifest_lane = (
                "fallback"
                if contract_route == "configured_fallback"
                else contract_route
            )
            _require(
                self.bound_route is not None
                and manifest_lane == self.bound_route.get("lane"),
                "LOCAL_REJECTION_ROUTE_DRIFT",
            )
            _require(
                int(value["route_attempt"]) <= int(value["attempt_index"]),
                "LOCAL_REJECTION_ATTEMPT_IDENTITY_INVALID",
            )
            if current.get("contract_attempt_index") is not None:
                _require(
                    int(value["attempt_index"])
                    == int(current["contract_attempt_index"])
                    and value.get("route") == current.get("contract_route")
                    and int(value["route_attempt"])
                    == int(current["contract_route_attempt"]),
                    "LOCAL_REJECTION_ATTEMPT_IDENTITY_INVALID",
                )
            bound_rejection = {
                **value,
                "physical_ordinal": ordinal,
                "logical_stage_id": str(current["logical_stage_id"]),
                "nonce_sha256": str(body["nonce_sha256"]),
                "session_id_sha256": hashlib.sha256(
                    self.session_id.encode("utf-8"),
                ).hexdigest(),
                "request_shape_sha256": str(current["request_shape_sha256"]),
                "provider_protocol_capture_receipt_sha256": str(
                    current["provider_protocol_capture_receipt_sha256"]
                ),
            }
            rejection_receipt_sha256 = domain_sha256(
                (
                    "novel-flywheel-provider-final-artifact-rejection-receipt-v2"
                    if pre_contract_final_artifact
                    else "novel-flywheel-contract-local-rejection-receipt-v2"
                ),
                bound_rejection,
            )
            current.update({
                "state": "LOCAL_ATTEMPT_REJECTED",
                "local_rejection_receipt_sha256": rejection_receipt_sha256,
                "local_rejection_failure_kind": value["failure_kind"],
                "local_rejection_failure_code": value.get("failure_code"),
                "local_rejection_schema": value["schema"],
                "local_rejection_physical_ordinal": ordinal,
                "local_rejection_logical_stage_id": str(
                    current["logical_stage_id"]
                ),
                "local_rejection_failure_reason_sha256": value[
                    "failure_reason_sha256"
                ],
                "contract_name": value["contract_name"],
                "contract_version": value["contract_version"],
                "contract_schema_sha256": value["contract_schema_sha256"],
                "local_rejection_stage": stage,
                "role": role,
            })
            attempts[ordinal - 1] = current
            body["attempts"] = attempts
            body["state"] = "READY_FOR_RECOVERY_ATTEMPT"
            return body

        self.store.update_ledger(self.execution_id, mutate)
        if runtime_kernel is not None and not kernel_rejection_preclosed:
            runtime_kernel.journal.transition(
                KernelExecutionState.STAGE_REJECTED_RECOVERABLE,
                transition_id="stage-rejected:" + hashlib.sha256(
                    canonical_json_bytes(value)
                ).hexdigest(),
                boundary_id="FS.CONTRACT.VALIDATE",
            )
        self.pending_ordinal = None
        self.bound_route = None
        self.expected_provider_payload = None
        self.egress_intent_sha256 = None
        self.pending_stage_context = None
        self.pending_capacity_plan_sha256 = None
        self.pending_capacity_receipt = None
        self.capacity_dispatch_token_authorized = False


def validate_full_short_dispatch_accounting_v1(
    *, logical_stage_count: int, physical_dispatch_count: int,
    expected_stage_calls: int, physical_dispatch_hard_cap: int,
    exact_replay_physical_dispatch_delta: int = 0,
) -> dict[str, int]:
    """Validate physical/logical/replay counts through one closed boundary."""

    values = (
        logical_stage_count, physical_dispatch_count, expected_stage_calls,
        physical_dispatch_hard_cap, exact_replay_physical_dispatch_delta,
    )
    _require(all(type(value) is int for value in values),
             "DISPATCH_ACCOUNTING_TYPE_INVALID")
    _require(
        logical_stage_count == expected_stage_calls,
        "EXPECTED_STAGE_CALL_COUNT_MISMATCH",
    )
    _require(
        logical_stage_count <= physical_dispatch_count
        <= physical_dispatch_hard_cap,
        "COMPLETION_CALL_CAP_EXCEEDED",
    )
    _require(
        exact_replay_physical_dispatch_delta == 0,
        "EXACT_REPLAY_CREATED_PHYSICAL_DISPATCH",
    )
    return {
        "logical_stage_count": logical_stage_count,
        "physical_dispatch_count": physical_dispatch_count,
        "physical_dispatch_hard_cap": physical_dispatch_hard_cap,
        "exact_replay_physical_dispatch_delta": 0,
    }


def build_full_short_completion_receipt_v1(
    *, execution_id: str, policy: Mapping[str, Any],
    durable_store: FullShortDurableExecutionStoreV1,
    permission_sha256: str, signed_approval_sha256: str, nonce_sha256: str,
    ledger: Mapping[str, Any], final_bindings: Mapping[str, str],
    terminal_verification: Mapping[str, Any],
    capacity_admission_receipts: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    validated = validate_policy_v1(policy)
    _require(
        isinstance(durable_store, FullShortDurableExecutionStoreV1)
        and durable_store.store_root_sha256
        == validated["store_root_sha256"],
        "COMPLETION_DURABLE_STORE_BINDING_INVALID",
    )
    persisted_ledger = durable_store.load_ledger(execution_id)
    sealed_ledger = FullShortDurableExecutionStoreV1._verify_seal(
        ledger, domain="novel-flywheel-full-short-dispatch-ledger-v1",
        field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
    )
    _require(
        sealed_ledger.get("execution_id") == execution_id
        and sealed_ledger.get("policy_sha256") == validated["policy_sha256"]
        and sealed_ledger.get("store_root_sha256")
        == validated["store_root_sha256"]
        and sealed_ledger.get("nonce_sha256") == nonce_sha256,
        "COMPLETION_LEDGER_CHAIN_MISMATCH",
    )
    _require(sealed_ledger.get("state") == "READY_FOR_NEXT_STAGE", "LEDGER_NOT_CLOSED")
    attempts = sealed_ledger.get("attempts")
    _require(isinstance(attempts, list) and attempts, "LEDGER_HAS_NO_DISPATCH")
    _validate_completion_physical_attempt_chain_v1(
        execution_id=execution_id, attempts=attempts,
    )
    durable_capacity_receipts = (
        durable_store.verify_completion_capacity_receipts(
            execution_id=execution_id, policy=validated,
            ledger=sealed_ledger,
        )
    )
    _require(
        dict(persisted_ledger) == dict(sealed_ledger),
        "COMPLETION_LEDGER_CHAIN_MISMATCH",
    )
    validated_capacity_receipts = tuple(
        _validate_capacity_admission_receipt_v1(
            item,
            execution_id=execution_id,
            plan_sha256=str(item.get("capacity_plan_sha256") or ""),
        )
        for item in capacity_admission_receipts
    )
    _require(
        validated_capacity_receipts == durable_capacity_receipts,
        "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID",
    )
    receipts_by_plan = {
        item["capacity_plan_sha256"]: item
        for item in validated_capacity_receipts
    }
    _require(
        all(item.get("state") in _CLOSED_LOCAL_ATTEMPT_STATES for item in attempts),
        "LEDGER_HAS_UNCLOSED_DISPATCH",
    )
    _require(
        sealed_ledger.get("capacity_policy_registry_sha256")
        == validated["capacity_policy_registry_sha256"]
        and all(
            item.get("capacity_policy_registry_sha256")
            == validated["capacity_policy_registry_sha256"]
            and _HEX64.fullmatch(str(
                item.get("capacity_plan_sha256") or ""
            )) is not None
            and _HEX64.fullmatch(str(
                item.get("capacity_admission_receipt_sha256") or ""
            )) is not None
            and item.get("capacity_admission_status") == "PASS"
            for item in attempts
        )
        and len(validated_capacity_receipts) == len(attempts)
        and len(receipts_by_plan) == len(attempts)
        and all(
            (
                receipt := receipts_by_plan.get(
                    item.get("capacity_plan_sha256")
                )
            ) is not None
            and receipt.get("state") == "CONSUMED"
            and receipt.get("capacity_admission_receipt_sha256")
            == item.get("capacity_admission_receipt_sha256")
            and receipt.get("physical_attempt_id")
            == item.get("physical_attempt_id")
            and receipt.get("global_physical_attempt_ordinal")
            == item.get("global_physical_attempt_ordinal")
            and receipt.get("logical_capacity_envelope_sha256")
            == item.get("logical_capacity_envelope_sha256")
            and receipt.get("route_capability_snapshot_sha256")
            == item.get("route_capability_snapshot_sha256")
            and receipt.get("rendered_request_sha256")
            == item.get("rendered_request_sha256")
            and receipt.get("base_rendered_request_sha256")
            == item.get("base_rendered_request_sha256")
            and receipt.get("recovery_overlay_kind")
            == item.get("recovery_overlay_kind")
            and receipt.get("recovery_overlay_sha256")
            == item.get("recovery_overlay_sha256")
            and receipt.get("recovery_prompt_delta_sha256")
            == item.get("recovery_prompt_delta_sha256")
            and receipt.get("recovery_source_capture_receipt_sha256")
            == item.get("recovery_source_capture_receipt_sha256")
            for item in attempts
        )
        and len({
            item.get("capacity_plan_sha256") for item in attempts
        }) == len(attempts)
        and len({
            item.get("capacity_admission_receipt_sha256") for item in attempts
        }) == len(attempts),
        "COMPLETION_CAPACITY_ADMISSION_PROVENANCE_INVALID",
    )
    _validate_capacity_recovery_chain_v1(
        attempts=attempts,
        receipts_by_plan=receipts_by_plan,
    )
    _require(
        [item.get("ordinal") for item in attempts]
        == list(range(1, len(attempts) + 1)),
        "LEDGER_ORDINALS_INVALID",
    )
    logical_stage_ids = {
        str(item.get("logical_stage_id") or "") for item in attempts
    }
    _require(
        all(
            sum(
                1 for item in attempts
                if item.get("logical_stage_id") == logical_stage_id
            )
            <= validated["max_physical_attempts_per_logical_stage"]
            for logical_stage_id in logical_stage_ids
        ),
        "COMPLETION_LOGICAL_STAGE_ATTEMPT_CAP_EXCEEDED",
    )
    completed_stage_receipts = list(
        sealed_ledger.get("completed_stage_receipts") or []
    )
    _require(
        len({
            item.get("logical_stage_id") for item in completed_stage_receipts
        }) == len(completed_stage_receipts)
        and all(
            item.get("accepted_artifact_count") == 1
            and _ID.fullmatch(str(
                item.get("accepted_physical_attempt_id") or ""
            )) is not None
            for item in completed_stage_receipts
        ),
        "COMPLETION_ACCEPTED_ARTIFACT_PROVENANCE_INVALID",
    )
    _require(
        sealed_ledger.get("logical_stage_plan_sha256")
        == validated["logical_stage_plan_sha256"]
        and sealed_ledger.get("transport_recovery_policy_sha256")
        == validated["transport_recovery_policy_sha256"]
        and sealed_ledger.get("transport_recovery_policy_identity")
        == "EXACT_REPLAY_ONLY",
        "COMPLETION_PLAN_OR_RECOVERY_POLICY_MISMATCH",
    )
    _require(
        sealed_ledger.get("logical_stage_recovery_policy_sha256")
        == validated["logical_stage_recovery_policy_sha256"],
        "COMPLETION_LOGICAL_RECOVERY_POLICY_MISMATCH",
    )
    validate_full_short_dispatch_accounting_v1(
        logical_stage_count=len(completed_stage_receipts),
        physical_dispatch_count=len(attempts),
        expected_stage_calls=validated["expected_stage_calls"],
        physical_dispatch_hard_cap=validated["hard_max_provider_requests"],
    )
    _require(
        len(attempts) <= validated["hard_max_provider_requests"]
        and len(attempts) <= validated["hard_max_http_posts"]
        and len(attempts) <= validated["hard_max_network_attempts"],
        "COMPLETION_CALL_CAP_EXCEEDED",
    )
    requested_total = sum(int(item.get("requested_output_tokens") or 0)
                          for item in attempts)
    _require(
        all(0 < int(item.get("requested_output_tokens") or 0)
            <= validated["per_call_output_token_hard_cap"] for item in attempts),
        "COMPLETION_PER_CALL_CAP_INVALID",
    )
    _require(
        requested_total == sealed_ledger.get("total_requested_output_tokens")
        and requested_total <= validated["total_output_token_hard_cap"],
        "COMPLETION_TOTAL_OUTPUT_CAP_INVALID",
    )
    try:
        created_at = datetime.fromisoformat(
            str(sealed_ledger["created_at"]).replace("Z", "+00:00"),
        )
    except (KeyError, ValueError) as exc:
        raise FullShortExecutionBoundaryError(
            "COMPLETION_LEDGER_CREATED_AT_INVALID"
        ) from exc
    _require(
        (datetime.now(timezone.utc) - created_at).total_seconds()
        <= validated["maximum_elapsed_seconds"],
        "COMPLETION_MAXIMUM_ELAPSED_EXPIRED",
    )
    receipts = completed_stage_receipts
    _require(
        isinstance(receipts, list)
        and len(receipts) == validated["expected_stage_calls"]
        and all(type(item.get("ordinal")) is int for item in receipts)
        and [item.get("ordinal") for item in receipts]
        == sorted({item.get("ordinal") for item in receipts})
        and all(0 < item["ordinal"] <= len(attempts) for item in receipts),
        "STAGE_MATRIX_INVALID",
    )
    _require(
        len({
            str(attempts[item["ordinal"] - 1].get(
                "logical_stage_id", attempts[item["ordinal"] - 1].get("stage")
            ))
            for item in receipts
        }) == validated["expected_stage_calls"],
        "LOGICAL_STAGE_MATRIX_DUPLICATE",
    )
    completed_plan = []
    for stage_receipt in receipts:
        attempt = attempts[stage_receipt["ordinal"] - 1]
        completed_plan.append({
            "ordinal": stage_receipt.get("logical_stage_ordinal"),
            "stage_id": attempt.get("stage"),
            "logical_stage_base_id": attempt.get("logical_stage_base_id"),
            "logical_stage_id": attempt.get("logical_stage_id"),
            "role": attempt.get("bound_role"),
            "route_lane": (
                "configured_fallback"
                if attempt.get("bound_lane") == "fallback"
                else attempt.get("bound_lane")
            ),
            "contract_name": attempt.get("contract_name"),
            "contract_version": attempt.get("contract_version"),
            "contract_schema_sha256": attempt.get("contract_schema_sha256"),
            "contract_runtime_input_required": attempt.get(
                "contract_runtime_input_required"
            ),
            "requested_output_tokens": attempt.get("requested_output_tokens"),
        })
    _require(
        completed_plan == validated["logical_stage_plan"]
        and full_short_logical_stage_plan_sha256_v1(completed_plan)
        == validated["logical_stage_plan_sha256"],
        "COMPLETION_LOGICAL_STAGE_PLAN_MISMATCH",
    )
    required_roles = set(validated["required_stage_roles"])
    _require(
        {item.get("role") for item in receipts} == required_roles,
        "REQUIRED_STAGE_ROLE_MATRIX_INCOMPLETE",
    )
    receipt_by_ordinal = {item["ordinal"]: item for item in receipts}
    _require(
        all(
            (attempt.get("ordinal") in receipt_by_ordinal)
            == (attempt.get("state") == "LOCAL_STAGE_COMPLETE")
            for attempt in attempts
        ),
        "STAGE_MATRIX_INVALID",
    )
    for stage_receipt in receipts:
        attempt = attempts[stage_receipt["ordinal"] - 1]
        rejected_attempts = [
            item for item in attempts[: stage_receipt["ordinal"] - 1]
            if item.get("logical_stage_id")
            == attempt.get("logical_stage_id")
            and item.get("state") == "LOCAL_ATTEMPT_REJECTED"
        ]
        expected_rejected_provenance = [
            {
                "physical_attempt_id": item.get("physical_attempt_id"),
                "ordinal": item.get("ordinal"),
                "local_rejection_receipt_sha256": item.get(
                    "local_rejection_receipt_sha256"
                ),
                "failure_kind": item.get("local_rejection_failure_kind"),
                "failure_code": item.get("local_rejection_failure_code"),
            }
            for item in rejected_attempts
        ]
        _require(
            attempt.get("stage") == stage_receipt.get("stage")
            and attempt.get("role") == stage_receipt.get("role")
            and attempt.get("role_binding_sha256")
            == stage_receipt.get("role_binding_sha256")
            and attempt.get("output_sha256") == stage_receipt.get("output_sha256")
            and attempt.get("local_stage_receipt_sha256")
            == stage_receipt.get("receipt_sha256"),
            "STAGE_MATRIX_BINDING_MISMATCH",
        )
        _require(
            stage_receipt.get("accepted_physical_attempt_id")
            == attempt.get("physical_attempt_id")
            and stage_receipt.get("accepted_stage_role")
            == attempt.get("stage_role", "NORMAL")
            and stage_receipt.get("rejected_attempt_provenance")
            == expected_rejected_provenance,
            "STAGE_ACCEPTANCE_PROVENANCE_MISMATCH",
        )
        exact_reasoning_rejections = [
            item for item in rejected_attempts
            if item.get("local_rejection_schema")
            == "ProviderFinalArtifactRejectionReceiptV1"
            and item.get("local_rejection_failure_kind")
            == "final_artifact_unavailable"
            and item.get("local_rejection_failure_code")
            == "reasoning_only_final_artifact_unavailable"
        ]
        recovery_accepted = (
            attempt.get("stage_role")
            == "PLANNING_FINAL_ARTIFACT_RECOVERY"
        )
        _require(
            recovery_accepted
            == (
                len(rejected_attempts) == 1
                and len(exact_reasoning_rejections) == 1
            ),
            "COMPLETION_TYPED_RECOVERY_TRANSITION_INVALID",
        )
        if any(
            item.get("local_rejection_failure_code")
            == "reasoning_only_final_artifact_unavailable"
            for item in rejected_attempts
        ):
            _require(
                attempt.get("stage_role")
                == "PLANNING_FINAL_ARTIFACT_RECOVERY",
                "COMPLETION_REASONING_RECOVERY_STAGE_ROLE_INVALID",
            )
    _require(
        set(final_bindings) == REQUIRED_FINAL_BINDING_KEYS,
        "COMPLETION_BINDING_KEYS_MISMATCH",
    )
    terminal = FullShortDurableExecutionStoreV1._verify_seal(
        terminal_verification,
        domain="novel-flywheel-short-completion-verification-v1",
        field="verification_receipt_sha256",
        reason="TERMINAL_VERIFICATION_SHA256_MISMATCH",
    )
    _require(
        terminal.get("schema") == "ShortCompletionVerificationV1"
        and terminal.get("version") == 1
        and terminal.get("workflow_final_status") == "completed"
        and terminal.get("unresolved_terminal_status") == "none"
        and terminal.get("live_parity_status") == "exact"
        and terminal.get("completion_goal_outcome") == SHORT_COMPLETION_GOAL
        and terminal.get("final_manuscript_binding_status") == "exact"
        and (terminal.get("final_review") or {}).get("accepted_status") == "accepted"
        and (terminal.get("final_review") or {}).get("binding_status") == "exact"
        and (terminal.get("maintenance") or {}).get("closure_status") == "exact"
        and (terminal.get("final_artifact") or {}).get("binding_status") == "exact"
        and (terminal.get("final_checkpoint") or {}).get("closure_status") == "exact",
        "TERMINAL_VERIFICATION_NOT_SUCCESSFUL",
    )
    _require(
        final_bindings["terminal_verification_sha256"]
        == terminal_verification.get("verification_receipt_sha256"),
        "TERMINAL_VERIFICATION_BINDING_MISMATCH",
    )
    _require(
        final_bindings["manuscript_sha256"]
        == terminal.get("final_manuscript_sha256"),
        "TERMINAL_MANUSCRIPT_BINDING_MISMATCH",
    )
    for value in (
        permission_sha256, signed_approval_sha256, nonce_sha256,
        *final_bindings.values(),
    ):
        _require(_HEX64.fullmatch(str(value)) is not None, "COMPLETION_BINDING_INVALID")
    verified_actual_usage = verify_full_short_actual_usage_v1(
        ledger=sealed_ledger, durable_store=durable_store, policy=validated,
    )
    body = {
        "schema": COMPLETION_SCHEMA, "version": 1,
        "execution_id": execution_id,
        "policy_sha256": validated["policy_sha256"],
        "permission_sha256": permission_sha256,
        "signed_approval_sha256": signed_approval_sha256,
        "nonce_sha256": nonce_sha256,
        "dispatch_ledger_sha256": sealed_ledger["ledger_sha256"],
        "capacity_policy_registry_sha256": validated[
            "capacity_policy_registry_sha256"
        ],
        "capacity_admission_receipt_sha256s": [
            item["capacity_admission_receipt_sha256"] for item in attempts
        ],
        "provider_request_count": len(attempts),
        "http_post_count": len(attempts),
        "network_attempt_count": len(attempts),
        "completed_stage_count": len(receipts),
        "requested_output_tokens": requested_total,
        "required_stage_roles": sorted(required_roles),
        "final_bindings": dict(sorted(final_bindings.items())),
        "outcome": "FULL_SHORT_COMPLETED_EXACT",
        "created_at": _now(),
    }
    if verified_actual_usage is not None:
        body["verified_actual_usage"] = verified_actual_usage
    return _seal(
        "novel-flywheel-full-short-completion-receipt-v1", body,
        "completion_receipt_sha256",
    )


def reconcile_full_short_capture_anchor_v1(
    *, store: FullShortDurableExecutionStoreV1, execution_id: str,
    ordinal: int, policy: Mapping[str, Any],
    byte_domain: str = PROVIDER_PROTOCOL_INPUT_BYTES,
) -> dict[str, Any]:
    """Reconcile one externally anchored capture without network access.

    Publication intentionally precedes the ledger mutation.  If the process
    stops in that interval, this routine accepts exactly one envelope whose
    immutable call/route/contract identity matches the already-recorded
    dispatch and whose length and byte hashes pass the capture-store audit.
    Any extra, mismatched, partial, or tampered candidate fails closed.
    """

    _require(type(ordinal) is int and ordinal > 0,
             "CAPTURE_RECONCILIATION_ORDINAL_INVALID")
    _require(
        byte_domain in {
            PROVIDER_PROTOCOL_INPUT_BYTES, CONTRACT_RUNTIME_INPUT_BYTES,
        },
        "CAPTURE_RECONCILIATION_DOMAIN_INVALID",
    )
    sealed = FullShortDurableExecutionStoreV1._verify_seal(
        store.load_ledger(execution_id),
        domain="novel-flywheel-full-short-dispatch-ledger-v1",
        field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
    )
    attempts = list(sealed.get("attempts") or [])
    _require(ordinal <= len(attempts), "CAPTURE_RECONCILIATION_ATTEMPT_MISSING")
    attempt = attempts[ordinal - 1]
    _require(
        attempt.get("ordinal") == ordinal,
        "CAPTURE_RECONCILIATION_ATTEMPT_IDENTITY_INVALID",
    )
    validated_policy = store._verify_store_binding(policy)
    external_anchors = store.audit_provider_response_capture_anchors(
        policy=validated_policy,
    )
    capture_store = ProviderResponseCaptureStoreV1(
        repo_root=store.repo_root,
        store_root=store.root / "provider-response-captures-v1",
    )
    candidates = [
        item for item in capture_store.audit_all(
            expected_receipt_sha256s=[
                str(item["provider_response_capture_receipt_sha256"])
                for item in external_anchors
            ],
        )
        if item["byte_domain"] == byte_domain
        and item["execution_id"] == execution_id
        and item["call_id"] == f"{execution_id}:{ordinal}"
    ]

    def identity_matches(item: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
        metadata = item.get("metadata")
        if not isinstance(metadata, Mapping):
            return False
        exact = (
            metadata.get("execution_id") == execution_id
            and metadata.get("call_id") == f"{execution_id}:{ordinal}"
            and metadata.get("stage_id") == current.get("stage")
            and metadata.get("provider_id_sha256")
            == current.get("provider_id_sha256")
            and metadata.get("model_id_sha256")
            == current.get("model_id_sha256")
            and metadata.get("route_fingerprint")
            == current.get("route_fingerprint")
            and current.get("protocol_schema_id")
            == f"{metadata.get('protocol')}-wire-v1"
            and metadata.get("contract_name") == current.get("contract_name")
            and metadata.get("contract_version")
            == current.get("contract_version")
            and metadata.get("contract_schema_sha256")
            == current.get("contract_schema_sha256")
            and metadata.get("transport_complete") is True
        )
        protocol = str(metadata.get("protocol") or "")
        exact = exact and (
            metadata.get("adapter_id")
            in _PROVIDER_PROTOCOL_ADAPTER_IDS.get(protocol, frozenset())
            and metadata.get("adapter_version") == 1
        )
        return bool(exact)

    matches = [item for item in candidates if identity_matches(item, attempt)]
    _require(
        len(candidates) == 1 and len(matches) == 1,
        "CAPTURE_RECONCILIATION_IDENTITY_NOT_EXACT",
    )
    capture = matches[0]
    receipt_sha256 = str(capture.get("ledger_receipt_sha256") or "")
    _require(
        _HEX64.fullmatch(receipt_sha256) is not None,
        "CAPTURE_RECONCILIATION_RECEIPT_INVALID",
    )
    # Replay performs a second independent envelope/hash/path check using the
    # exact audited metadata before any ledger write is attempted.
    capture_store.replay(
        byte_domain=byte_domain,
        expected_metadata=capture["metadata"],
        expected_receipt_sha256=receipt_sha256,
    )
    _require(
        any(
            item.get("execution_id") == execution_id
            and item.get("ordinal") == ordinal
            and item.get("byte_domain") == byte_domain
            and item.get("provider_response_capture_receipt_sha256")
            == receipt_sha256
            for item in external_anchors
        ),
        "CAPTURE_RECONCILIATION_EXTERNAL_ANCHOR_MISSING",
    )
    field = (
        "provider_protocol_capture_receipt_sha256"
        if byte_domain == PROVIDER_PROTOCOL_INPUT_BYTES
        else "contract_runtime_capture_receipt_sha256"
    )
    complete_field = field.replace(
        "_receipt_sha256", "_transport_complete",
    )
    capture_metadata = capture["metadata"]
    capture_http_success = capture_metadata.get("http_success")
    capture_status_sha256 = capture_metadata.get("response_status_sha256")

    def mutate(body: dict[str, Any]) -> dict[str, Any]:
        current_attempts = list(body.get("attempts") or [])
        _require(
            ordinal <= len(current_attempts),
            "CAPTURE_RECONCILIATION_ATTEMPT_MISSING",
        )
        current = dict(current_attempts[ordinal - 1])
        _require(
            identity_matches(capture, current),
            "CAPTURE_RECONCILIATION_LEDGER_IDENTITY_DRIFT",
        )
        existing = current.get(field)
        _require(
            existing in {None, receipt_sha256},
            "CAPTURE_RECONCILIATION_RECEIPT_DRIFT",
        )
        if existing == receipt_sha256:
            _require(
                current.get(complete_field) is True,
                "CAPTURE_RECONCILIATION_COMPLETENESS_DRIFT",
            )
            return body
        _require(
            current.get("state") in _ATTEMPT_STATE_TRANSITIONS_V1,
            "CAPTURE_RECONCILIATION_LEDGER_STATE_INVALID",
        )
        current[field] = receipt_sha256
        current[complete_field] = True
        if (
            byte_domain == PROVIDER_PROTOCOL_INPUT_BYTES
            and current.get("state") == "DISPATCH_ATTEMPTED"
        ):
            _require(
                type(capture_http_success) is bool
                and _HEX64.fullmatch(str(capture_status_sha256 or ""))
                is not None,
                "CAPTURE_RECONCILIATION_HTTP_CLASSIFICATION_INVALID",
            )
            current["provider_protocol_capture_http_success"] = (
                capture_http_success
            )
            current["response_status_sha256"] = capture_status_sha256
            if capture_http_success:
                current["state"] = "RESPONSE_RECEIVED"
                current["response_received_at"] = _now()
                body["state"] = "RESPONSE_RECEIVED_AWAITING_LOCAL_RECEIPT"
            else:
                current["state"] = "HTTP_RESPONSE_FAILED_CLOSED"
                body["state"] = "RECONCILIATION_REQUIRED_NO_REDISPATCH"
        current_attempts[ordinal - 1] = current
        body["attempts"] = current_attempts
        return body

    # The special mutation is performed only inside the audit/replay owner.
    # The generic store update API has no reconciliation mode to request.
    with store._locked():
        before = store._verify_seal(
            store._read(execution_id, "ledger"),
            domain="novel-flywheel-full-short-dispatch-ledger-v1",
            field="ledger_sha256", reason="LEDGER_SHA256_MISMATCH",
        )
        body = dict(before)
        body.pop("ledger_sha256", None)
        changed = mutate(deepcopy(body))
        _require(isinstance(changed, dict), "LEDGER_MUTATION_INVALID")
        if changed == body:
            return before
        _validate_ledger_mutation_v1(
            body, changed,
            mutation_kind="CAPTURE_RECEIPT_RECONCILIATION",
        )
        changed["updated_at"] = _now()
        value = _seal(
            "novel-flywheel-full-short-dispatch-ledger-v1",
            changed, "ledger_sha256",
        )
        store._replace(store._path(execution_id, "ledger"), value)
        return value


def replay_full_short_provider_attempt_v1(
    *, store: FullShortDurableExecutionStoreV1, execution_id: str,
    ordinal: int, policy: Mapping[str, Any],
):
    """Read-only replay of one receipt-anchored captured provider entity.

    This function deliberately has no provider registry, credential, client,
    nonce mutation, or network path.  An orphan capture without an exact
    ledger receipt fails closed and therefore cannot silently authorize a
    restart or redispatch.
    """

    _require(type(ordinal) is int and ordinal > 0, "REPLAY_ORDINAL_INVALID")
    ledger = store.load_ledger(execution_id)
    attempts = list(ledger.get("attempts") or [])
    _require(ordinal <= len(attempts), "REPLAY_ATTEMPT_MISSING")
    attempt = attempts[ordinal - 1]
    receipt_sha256 = attempt.get(
        "provider_protocol_capture_receipt_sha256"
    )
    if receipt_sha256 is None:
        # The only recovery from the ledger-publication crash window is an
        # exact local reconciliation from a separately signed capture anchor.
        # A raw/self-consistent capture alone is never authority.
        validated_policy = store._verify_store_binding(policy)
        anchored = store.audit_provider_response_capture_anchors(
            policy=validated_policy,
        )
        _require(
            any(
                item.get("execution_id") == execution_id
                and item.get("ordinal") == ordinal
                and item.get("byte_domain")
                == PROVIDER_PROTOCOL_INPUT_BYTES
                for item in anchored
            ),
            "REPLAY_LEDGER_CAPTURE_RECEIPT_MISSING",
        )
        reconcile_full_short_capture_anchor_v1(
            store=store, execution_id=execution_id, ordinal=ordinal,
            policy=policy,
        )
        ledger = store.load_ledger(execution_id)
        attempt = list(ledger.get("attempts") or [])[ordinal - 1]
        receipt_sha256 = attempt.get(
            "provider_protocol_capture_receipt_sha256"
        )
    _require(
        isinstance(receipt_sha256, str)
        and _HEX64.fullmatch(receipt_sha256) is not None,
        "REPLAY_LEDGER_CAPTURE_RECEIPT_MISSING",
    )
    capture_store = ProviderResponseCaptureStoreV1(
        repo_root=store.repo_root,
        store_root=store.root / "provider-response-captures-v1",
    )
    validated_policy = store._verify_store_binding(policy)
    external_anchors = store.audit_provider_response_capture_anchors(
        policy=validated_policy,
    )
    matches = [
        item for item in capture_store.audit_all(
            expected_receipt_sha256s=[
                str(item["provider_response_capture_receipt_sha256"])
                for item in external_anchors
            ],
        )
        if item["byte_domain"] == PROVIDER_PROTOCOL_INPUT_BYTES
        and item["execution_id"] == execution_id
        and item["call_id"] == f"{execution_id}:{ordinal}"
        and item["ledger_receipt_sha256"] == receipt_sha256
    ]
    _require(len(matches) == 1, "REPLAY_CAPTURE_IDENTITY_NOT_EXACT")
    capture = matches[0]
    data, metadata = capture_store.replay(
        byte_domain=PROVIDER_PROTOCOL_INPUT_BYTES,
        expected_metadata=capture["metadata"],
        expected_receipt_sha256=receipt_sha256,
    )
    _require(
        metadata.get("transport_complete") is True,
        "REPLAY_CAPTURE_TRANSPORT_INCOMPLETE",
    )
    _require(
        metadata.get("http_success") is True
        and type(metadata.get("status_code")) is int
        and 200 <= metadata["status_code"] < 300,
        "REPLAY_HTTP_RESPONSE_NOT_SUCCESSFUL",
    )
    _require(
        attempt.get("provider_protocol_capture_http_success") is True
        and attempt.get("response_status_sha256")
        == metadata.get("response_status_sha256"),
        "REPLAY_LEDGER_HTTP_CLASSIFICATION_MISMATCH",
    )
    protocol = str(metadata.get("protocol") or "")
    _require(
        metadata.get("adapter_id")
        in _PROVIDER_PROTOCOL_ADAPTER_IDS.get(protocol, frozenset()),
        "REPLAY_ADAPTER_IDENTITY_INVALID",
    )
    if attempt.get("outer_campaign_usage_guard") is not None:
        extracted_usage = extract_provider_reported_actual_usage_v1(
            data, protocol=protocol,
            content_type=str(metadata["content_type"]),
            encoding=str(metadata["encoding"]),
        )
        _require(
            extracted_usage == attempt.get("provider_reported_actual_usage"),
            "REPLAY_PROVIDER_REPORTED_USAGE_MISMATCH",
        )
        verify_full_short_actual_usage_v1(
            ledger=ledger, durable_store=store, policy=validated_policy,
        )
    if protocol == "anthropic":
        from novel_flywheel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter
    elif protocol == "openai-chat":
        from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
        adapter = OpenAIChatAdapter
    elif protocol == "openai-responses":
        from novel_flywheel.providers.openai_responses import (
            OpenAIResponsesAdapter,
        )
        adapter = OpenAIResponsesAdapter
    else:
        raise FullShortExecutionBoundaryError("REPLAY_PROTOCOL_UNSUPPORTED")

    return adapter.replay_protocol_input_bytes_v1(
        data, content_type=metadata["content_type"],
        encoding=metadata["encoding"],
    )
