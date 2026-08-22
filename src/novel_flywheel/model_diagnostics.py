"""Fail-open, hash-only model boundary diagnostics.

The records in this module are operational observations.  They never authorize
an artifact, alter a provider request, or participate in retry/fallback state.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


DIAGNOSTIC_CANONICALIZATION_VERSION = "r1-pa1-diagnostic-canonical-json-v1"
STRICT_TOOL_FLAG = "NOVEL_STRICT_TOOL_SHAPE_TRACE_V1"
BUDGET_LINEAGE_FLAG = "NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1"
PTR12_OBSERVER_FLAG = "NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1"
MAX_OBSERVED_TOOL_CALLS = 32
MAX_PTR12_BLOCK_SEQUENCE = 128
MAX_PTR12_UNKNOWN_HASHES = 32

SHA256_PATTERN = r"^[0-9a-f]{64}$"
SnapshotStatus = Literal[
    "snapshot_exact",
    "snapshot_partial",
    "snapshot_unavailable",
    "adapter_exception_with_snapshot",
    "adapter_exception_without_snapshot",
]
ArgumentShape = Literal["object", "string", "array", "null", "missing", "other"]
ArgumentParseStatus = Literal[
    "parsed", "malformed", "native_object", "not_applicable", "not_attempted", "unknown",
]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def domain_sha256(domain: str, value: Any) -> str:
    return hashlib.sha256(
        domain.encode("utf-8") + b"\0" + _canonical_bytes(value)
    ).hexdigest()


def bytes_sha256(domain: str, value: bytes) -> str:
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + value).hexdigest()


def diagnostic_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "0") == "1"


def controlled_finish_reason(value: object) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    normalized = str(value).strip().casefold()
    controlled = {
        "stop", "tool_use", "end_turn", "max_tokens", "length", "completed",
        "incomplete", "failed", "cancelled", "content_filter", "function_call",
    }
    if normalized in controlled:
        return normalized, None
    return "provider_specific", domain_sha256("r1-pa1-finish-reason-v1", normalized)


class ToolCallShapeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int = Field(ge=0)
    registered_tool_id: str | None = Field(default=None, max_length=128)
    unknown_tool_name_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    tool_call_id_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    arguments_present: bool
    argument_shape: ArgumentShape
    argument_json_parse_status: ArgumentParseStatus
    argument_byte_length: int | None = Field(default=None, ge=0)
    argument_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    partial: bool = False


class ProviderToolShapeSnapshotV1(BaseModel):
    """Sanitized provider-visible topology captured before normalization."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_name: Literal["ProviderToolShapeSnapshotV1"] = Field(
        default="ProviderToolShapeSnapshotV1", alias="schema", serialization_alias="schema",
    )
    version: Literal[1] = 1
    canonicalization_version: Literal[
        "r1-pa1-diagnostic-canonical-json-v1"
    ] = DIAGNOSTIC_CANONICALIZATION_VERSION
    adapter_id: str = Field(min_length=1, max_length=64)
    adapter_version: int = Field(ge=1)
    adapter_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    snapshot_status: SnapshotStatus
    shape_correlation_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    provider_response_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    provider_request_id_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    raw_content_block_count: int | None = Field(default=None, ge=0)
    raw_tool_call_count: int | None = Field(default=None, ge=0)
    raw_text_present: bool | None = None
    raw_tool_use_present: bool | None = None
    raw_finish_reason_code: str | None = Field(default=None, max_length=64)
    raw_finish_reason_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    tool_calls: tuple[ToolCallShapeV1, ...] = ()
    overflow_tool_call_count: int = Field(default=0, ge=0)
    overflow_tool_calls_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    snapshot_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_snapshot_claim(self) -> "ProviderToolShapeSnapshotV1":
        if self.snapshot_status in {"snapshot_exact", "adapter_exception_with_snapshot"} \
                and self.raw_tool_call_count is None:
            raise ValueError("an exact provider snapshot requires a raw tool-call count")
        return self


class StrictToolShapeObservationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_name: Literal["StrictToolShapeObservationV1"] = Field(
        default="StrictToolShapeObservationV1", alias="schema", serialization_alias="schema",
    )
    version: Literal[1] = 1
    canonicalization_version: Literal[
        "r1-pa1-diagnostic-canonical-json-v1"
    ] = DIAGNOSTIC_CANONICALIZATION_VERSION
    observation_sha256: str = Field(pattern=SHA256_PATTERN)
    shape_correlation_sha256: str = Field(pattern=SHA256_PATTERN)
    run_sha256: str = Field(pattern=SHA256_PATTERN)
    stage: str = Field(min_length=1, max_length=64)
    boundary: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=64)
    route_kind: Literal["primary", "configured_fallback"]
    provider_alias: str = Field(min_length=1, max_length=128)
    provider_alias_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    model_alias: str = Field(min_length=1, max_length=128)
    model_alias_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    outer_retry_id: str = Field(min_length=1, max_length=128)
    contract_runtime_instance_id: str = Field(min_length=1, max_length=128)
    attempt_id: str = Field(min_length=1, max_length=128)
    parent_attempt_id: str | None = Field(default=None, max_length=128)
    expected_tool_contract: str = Field(min_length=1, max_length=128)
    expected_tool_contract_version: int = Field(ge=1)
    requested_expected_tool_id: str = Field(min_length=1, max_length=128)
    request_declared_tool_count: int = Field(ge=0)
    request_tool_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    expected_tool_schema_sha256: str = Field(pattern=SHA256_PATTERN)
    tool_choice_policy: Literal[
        "required", "forced_exact_tool", "auto", "none", "provider_specific",
    ]
    request_protocol: str = Field(min_length=1, max_length=64)
    adapter_version: int = Field(ge=1)
    adapter_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    expected_tool_call_count: Literal[1] = 1
    provider_shape: ProviderToolShapeSnapshotV1
    normalized_tool_call_count: int = Field(ge=0)
    normalized_unique_tool_identity_count: int = Field(ge=0)
    normalized_tool_calls: tuple[ToolCallShapeV1, ...] = ()
    normalized_tool_call_id_hashes: tuple[str, ...] = ()
    duplicate_call_id_count: int = Field(ge=0)
    duplicate_identity_count: int = Field(ge=0)
    adapter_projection_status: Literal[
        "exact", "dropped", "duplicated", "changed", "unavailable",
    ]
    gateway_matching_count: int | None = Field(default=None, ge=0)
    exact_expected_tool_match_count: int | None = Field(default=None, ge=0)
    observed_unique_tool_identity_count: int | None = Field(default=None, ge=0)
    unknown_tool_name_count: int | None = Field(default=None, ge=0)
    observed_registered_tool_ids: tuple[str, ...] = ()
    unknown_tool_name_hashes: tuple[str, ...] = ()
    content_block_count: int | None = Field(default=None, ge=0)
    text_content_present: bool | None = None
    tool_use_content_present: bool | None = None
    tool_arguments_present: bool | None = None
    response_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    finish_reason: str | None = Field(default=None, max_length=64)
    request_max_output_tokens: int | None = Field(default=None, ge=1)
    provider_request_id_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    strict_tool_decision: Literal[
        "accept_unique_expected", "reject_current_uniqueness_rule",
        "adapter_exception_before_uniqueness", "unknown",
    ]
    strict_tool_failure_code: str | None = Field(default=None, max_length=96)
    observation_status: Literal["exact", "partial", "unavailable"]
    target_status: Literal["target"] = "target"

    @model_validator(mode="after")
    def do_not_infer_zero_without_snapshot(self) -> "StrictToolShapeObservationV1":
        if self.strict_tool_failure_code == "zero_tool_calls" and not (
            self.provider_shape.snapshot_status in {
                "snapshot_exact", "adapter_exception_with_snapshot",
            }
            and self.provider_shape.raw_tool_call_count == 0
        ):
            raise ValueError("zero tool calls require an exact provider/adapter count")
        return self


class PlanningAdaptationOutputBudgetLineageV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_name: Literal["PlanningAdaptationOutputBudgetLineageV1"] = Field(
        default="PlanningAdaptationOutputBudgetLineageV1",
        alias="schema", serialization_alias="schema",
    )
    version: Literal[1] = 1
    canonicalization_version: Literal[
        "r1-pa1-diagnostic-canonical-json-v1"
    ] = DIAGNOSTIC_CANONICALIZATION_VERSION
    lineage_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    lineage_event: Literal[
        "runtime_created", "request_dispatched", "expansion_decided",
        "runtime_closed", "outer_runtime_reconstructed",
    ]
    run_sha256: str = Field(pattern=SHA256_PATTERN)
    stage: str = Field(min_length=1, max_length=64)
    boundary: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=64)
    contract_id: str = Field(min_length=1, max_length=128)
    contract_version: int = Field(ge=1)
    outer_retry_id: str = Field(min_length=1, max_length=128)
    contract_runtime_instance_id: str = Field(min_length=1, max_length=128)
    previous_contract_runtime_instance_id: str | None = Field(
        default=None, max_length=128,
    )
    inner_attempt_id: str | None = Field(default=None, max_length=128)
    parent_attempt_id: str | None = Field(default=None, max_length=128)
    original_requested_output_budget: int | None = Field(default=None, ge=1)
    current_requested_output_budget: int | None = Field(default=None, ge=1)
    previous_attempt_budget: int | None = Field(default=None, ge=1)
    expansion_policy: str = Field(min_length=1, max_length=128)
    expansion_policy_version: int = Field(ge=1)
    expansion_trigger: str | None = Field(default=None, max_length=96)
    expansion_requested: bool
    expansion_target: int | None = Field(default=None, ge=1)
    expansion_target_before_cap: int | None = Field(default=None, ge=1)
    effective_budget_after_policy: int | None = Field(default=None, ge=1)
    effective_budget_after_provider_cap: int | None = Field(default=None, ge=1)
    effective_budget_after_canary_cap: int | None = Field(default=None, ge=1)
    expansion_applied: bool
    retained_expansion_state: bool
    runtime_reconstructed: bool
    reconstruction_reason: str | None = Field(default=None, max_length=128)
    retry_owner: Literal["workflow_outer_receipt_schedule", "contract_runtime_inner"]
    route_kind: Literal["primary", "configured_fallback"] | None = None
    finish_reason: str | None = Field(default=None, max_length=64)
    typed_failure: str | None = Field(default=None, max_length=128)
    cap_applied: bool
    cap_source: Literal[
        "none", "contract", "provider", "model", "canary", "runtime_global",
    ]
    cap_sources: tuple[str, ...] = ()
    provider_declared_output_limit: int | None = Field(default=None, ge=1)
    provider_limit_status: Literal["verified", "unknown", "not_applicable"]
    request_parameter_name: Literal[
        "max_tokens", "max_output_tokens", "max_completion_tokens", "provider_specific",
    ]
    prompt_system_sha256: str = Field(pattern=SHA256_PATTERN)
    prompt_user_sha256: str = Field(pattern=SHA256_PATTERN)
    contract_sha256: str = Field(pattern=SHA256_PATTERN)
    provider_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    model_binding_sha256: str = Field(pattern=SHA256_PATTERN)


@dataclass(frozen=True)
class ModelDiagnosticContextV1:
    project_root: Path
    run_id: str
    stage: str
    boundary: str
    role: str
    route_kind: str
    contract_id: str
    contract_version: int
    outer_retry_ordinal: int
    runtime_ordinal: int = 1
    inner_attempt_ordinal: int = 1
    parent_attempt_ordinal: int | None = None
    provider_declared_output_limit: int | None = None
    provider_limit_status: str = "unknown"
    canary_output_limit: int | None = None
    provider_binding_sha256: str = "0" * 64
    model_binding_sha256: str = "0" * 64
    request_parameter_name: str = "provider_specific"

    @property
    def run_sha256(self) -> str:
        return domain_sha256("r1-pa1-run-id-v1", self.run_id)

    def logical_id(self, kind: str, ordinal: int) -> str:
        digest = domain_sha256("r1-pa1-logical-lineage-id-v1", {
            "kind": kind,
            "run_sha256": self.run_sha256,
            "stage": self.stage,
            "boundary": self.boundary,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "outer_retry_ordinal": self.outer_retry_ordinal,
            "runtime_ordinal": self.runtime_ordinal,
            "ordinal": ordinal,
        })
        return f"{kind}-{digest[:32]}"

    @property
    def outer_retry_id(self) -> str:
        return self.logical_id("outer", self.outer_retry_ordinal)

    @property
    def runtime_instance_id(self) -> str:
        return self.logical_id("runtime", self.runtime_ordinal)

    @property
    def inner_attempt_id(self) -> str:
        return self.logical_id("inner", self.inner_attempt_ordinal)

    @property
    def parent_attempt_id(self) -> str | None:
        if self.parent_attempt_ordinal is None:
            return None
        return self.logical_id("inner", self.parent_attempt_ordinal)


class ProviderRawShapeObservationV1(BaseModel):
    """PTR12 content-free provider topology bound to one Runtime attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_name: Literal["ProviderRawShapeObservationV1"] = Field(
        default="ProviderRawShapeObservationV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    correlation_id: str = Field(min_length=1, max_length=128)
    external_call_number: int | None = Field(default=None, ge=1)
    run_sha256: str = Field(pattern=SHA256_PATTERN)
    stage: str = Field(min_length=1, max_length=64)
    boundary: str = Field(min_length=1, max_length=128)
    contract_id: str = Field(min_length=1, max_length=128)
    contract_version: int = Field(ge=1)
    schema_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    provider_fingerprint: str = Field(pattern=SHA256_PATTERN)
    model_fingerprint: str = Field(pattern=SHA256_PATTERN)
    route_fingerprint: str = Field(pattern=SHA256_PATTERN)
    route_kind: Literal["primary", "configured_fallback", "other"]
    request_mode: Literal["plain", "structured", "tool", "unknown"]
    outer_retry_ordinal: int = Field(ge=1)
    runtime_instance_ordinal: int = Field(ge=1)
    inner_attempt_ordinal: int = Field(ge=1)
    observation_point: Literal[
        "transport_body_pre_normalization", "stream_event_shape_pre_aggregation",
    ]
    provider_protocol: Literal[
        "anthropic", "openai-chat", "openai-responses", "unknown",
    ]
    raw_response_class: Literal["response_body", "stream_event_sequence", "unknown"]
    unknown_response_class_sha256: str | None = Field(
        default=None, pattern=SHA256_PATTERN,
    )
    raw_block_count: int = Field(ge=0)
    raw_block_type_sequence: tuple[str, ...]
    raw_block_type_sequence_sha256: str = Field(pattern=SHA256_PATTERN)
    raw_block_type_multiset: dict[str, int]
    sequence_omitted_after_limit: bool
    reasoning_block_count: int = Field(ge=0)
    text_or_final_block_count: int = Field(ge=0)
    tool_block_count: int = Field(ge=0)
    unknown_block_count: int = Field(ge=0)
    unknown_block_type_hashes: tuple[str, ...]
    raw_visible_char_count: int | None = Field(default=None, ge=0)
    raw_visible_chars_zero: bool | None
    raw_final_text_present: bool | None
    raw_tool_call_present: bool | None
    finish_reason_raw_class: str = Field(min_length=1, max_length=64)
    finish_reason_unknown_sha256: str | None = Field(
        default=None, pattern=SHA256_PATTERN,
    )
    output_token_count: int | None = Field(default=None, ge=0)
    requested_output_cap: int | None = Field(default=None, ge=1)
    effective_output_cap: int | None = Field(default=None, ge=1)
    provider_accepted_cap_status: Literal["KNOWN", "NOT_EXPOSED", "UNKNOWN", "NOT_APPLICABLE"]
    provider_exposed_reasoning_usage_status: Literal["KNOWN", "NOT_EXPOSED", "UNKNOWN", "NOT_APPLICABLE"]
    provider_exposed_reasoning_usage: int | None = Field(default=None, ge=0)
    provider_exposed_final_usage_status: Literal["KNOWN", "NOT_EXPOSED", "UNKNOWN", "NOT_APPLICABLE"]
    provider_exposed_final_usage: int | None = Field(default=None, ge=0)
    transport_complete: bool | None
    capture_completeness: Literal["exact", "partial", "unavailable"]
    raw_shape_fingerprint: str = Field(pattern=SHA256_PATTERN)
    content_omitted: Literal[True] = True
    reasoning_content_omitted: Literal[True] = True
    tool_arguments_omitted: Literal[True] = True


class RawToNormalizedShapeDeltaV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    schema_name: Literal["RawToNormalizedShapeDeltaV1"] = Field(
        default="RawToNormalizedShapeDeltaV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    correlation_id: str = Field(min_length=1, max_length=128)
    raw_shape_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    normalized_shape_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    representation_changed: Literal["YES", "NO", "UNKNOWN"]
    changed_dimensions: tuple[str, ...]
    unavailable_dimensions: tuple[str, ...]
    comparison_completeness: Literal["exact", "partial", "unavailable"]
    delta_sha256: str = Field(pattern=SHA256_PATTERN)


class PTR9GuardDecisionObserverV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    schema_name: Literal["PTR9GuardDecisionObserverV1"] = Field(
        default="PTR9GuardDecisionObserverV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    phase: Literal["guard_evaluation", "recovery_disposition"]
    correlation_id: str = Field(min_length=1, max_length=128)
    decision_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    guard_scope_eligible: bool
    guard_reached: bool
    shape_available: bool
    reasoning_block_exists: bool | None
    finish_reason_max_tokens: bool | None
    raw_visible_chars_zero: bool | None
    normalized_visible_chars_zero: bool | None
    final_text_absent: bool | None
    tool_call_absent: bool | None
    unknown_block_absent: bool | None
    content_all_reasoning: bool | None
    projection_exact: bool | None
    transport_complete: bool | None
    predicate_all_true: bool | None
    guard_triggered: bool
    negative_capability_write_attempted: bool
    negative_capability_written: bool
    negative_capability_write_status: Literal[
        "RECORDED", "WRITE_FAILED", "NOT_REQUIRED", "NOT_REACHED",
    ]
    alternate_route_considered: bool | None
    alternate_route_selected: bool | None
    fail_close_selected: bool | None
    primary_guard_miss_reason: str | None = Field(default=None, max_length=64)
    guard_miss_reasons: tuple[str, ...]
    recovery_status: Literal[
        "NOT_APPLICABLE", "NORMAL_RETURN", "ALTERNATE_ROUTE_SELECTED",
        "TYPED_FAIL_CLOSE", "RUNTIME_CONTINUED_EXISTING_POLICY", "UNKNOWN",
    ]
    raw_shape_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    normalized_shape_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    representation_delta_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    provider_fingerprint: str = Field(pattern=SHA256_PATTERN)
    model_fingerprint: str = Field(pattern=SHA256_PATTERN)
    route_fingerprint: str = Field(pattern=SHA256_PATTERN)
    contract_identity: str = Field(min_length=1, max_length=128)
    schema_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)


class ContractOutputLimitClassificationObservationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    schema_name: Literal[
        "ContractOutputLimitClassificationObservationV1"
    ] = Field(
        default="ContractOutputLimitClassificationObservationV1",
        alias="schema", serialization_alias="schema",
    )
    version: Literal[1] = 1
    correlation_id: str = Field(min_length=1, max_length=128)
    output_limit_seen: bool
    finish_reason_class: str | None = Field(default=None, max_length=64)
    aggregate_output_usage: int | None = Field(default=None, ge=0)
    terminal_classification: Literal[
        "CONTRACT_OUTPUT_LIMIT_EXHAUSTED", "RUNTIME_CONTINUED_EXISTING_POLICY",
    ]
    classification_sha256: str = Field(pattern=SHA256_PATTERN)


def is_strict_tool_target(context: ModelDiagnosticContextV1 | None) -> bool:
    return bool(context and (
        context.stage == "review"
        and context.boundary == "planning_adaptation_whole_receipt"
        and context.contract_id == "planning_adaptation_whole"
        and context.contract_version == 1
        and context.role == "review"
        and context.route_kind == "configured_fallback"
    ))


@dataclass
class ModelDiagnosticMetrics:
    strict_tool_target_attempted: int = 0
    strict_tool_written: int = 0
    strict_tool_dropped: int = 0
    strict_tool_excluded_not_target: int = 0
    budget_attempted: int = 0
    budget_written: int = 0
    budget_dropped: int = 0


_metrics = ModelDiagnosticMetrics()
_metrics_lock = threading.Lock()


def diagnostic_metrics_snapshot() -> dict[str, int]:
    with _metrics_lock:
        return dict(_metrics.__dict__)


def reset_diagnostic_metrics_for_tests() -> None:
    with _metrics_lock:
        for key in _metrics.__dict__:
            setattr(_metrics, key, 0)


_exception_snapshot: contextvars.ContextVar[
    tuple[BaseException, ProviderToolShapeSnapshotV1] | None
] = contextvars.ContextVar("r1_pa1_exception_snapshot", default=None)
_active_diagnostic_context: contextvars.ContextVar[
    ModelDiagnosticContextV1 | None
] = contextvars.ContextVar("r1_pa1_active_diagnostic_context", default=None)
_ptr12_raw_shape_capture: contextvars.ContextVar[
    Mapping[str, Any] | None
] = contextvars.ContextVar("r1_ptr12_raw_shape_capture", default=None)
_ptr12_external_call_number: contextvars.ContextVar[int | None] = (
    contextvars.ContextVar("r1_ptr12_external_call_number", default=None)
)
_ptr12_guard_decision_capture: contextvars.ContextVar[
    PTR9GuardDecisionObserverV1 | None
] = contextvars.ContextVar("r1_ptr12_guard_decision_capture", default=None)


def bind_diagnostic_context(
    context: ModelDiagnosticContextV1 | None,
) -> contextvars.Token[ModelDiagnosticContextV1 | None]:
    return _active_diagnostic_context.set(context)


def reset_bound_diagnostic_context(
    token: contextvars.Token[ModelDiagnosticContextV1 | None],
) -> None:
    _active_diagnostic_context.reset(token)


def active_diagnostic_context() -> ModelDiagnosticContextV1 | None:
    """Expose the immutable diagnostic context to provider-side observers."""

    return _active_diagnostic_context.get()


def ptr12_observer_enabled() -> bool:
    return diagnostic_flag_enabled(PTR12_OBSERVER_FLAG)


def open_ptr12_raw_shape_capture() -> contextvars.Token[Mapping[str, Any] | None] | None:
    """Open one execution-local slot; disabled mode allocates no capture state."""

    if not ptr12_observer_enabled():
        return None
    return _ptr12_raw_shape_capture.set(None)


def reset_ptr12_raw_shape_capture(
    token: contextvars.Token[Mapping[str, Any] | None] | None,
) -> None:
    if token is not None:
        _ptr12_raw_shape_capture.reset(token)


def record_ptr12_raw_shape(snapshot: Mapping[str, Any]) -> None:
    """Deposit metadata only; adapters ignore all errors and return values."""

    if ptr12_observer_enabled():
        try:
            _ptr12_raw_shape_capture.set(dict(snapshot))
        except Exception:
            pass


def current_ptr12_raw_shape() -> Mapping[str, Any] | None:
    value = _ptr12_raw_shape_capture.get()
    return dict(value) if value is not None else None


def bind_ptr12_external_call_number(
    ordinal: int,
) -> contextvars.Token[int | None]:
    return _ptr12_external_call_number.set(ordinal)


def reset_ptr12_external_call_number(
    token: contextvars.Token[int | None],
) -> None:
    _ptr12_external_call_number.reset(token)


def current_ptr12_external_call_number() -> int | None:
    return _ptr12_external_call_number.get()


def clear_ptr12_guard_decision_capture() -> None:
    _ptr12_guard_decision_capture.set(None)


def current_ptr12_guard_decision() -> PTR9GuardDecisionObserverV1 | None:
    return _ptr12_guard_decision_capture.get()


def strict_snapshot_capture_requested() -> bool:
    return diagnostic_flag_enabled(STRICT_TOOL_FLAG) and is_strict_tool_target(
        _active_diagnostic_context.get()
    )


def attach_exception_snapshot(
    exc: BaseException, snapshot: ProviderToolShapeSnapshotV1,
) -> None:
    """Attach diagnostics without wrapping or raising a replacement exception."""
    try:
        setattr(exc, "_r1_pa1_tool_shape_snapshot", snapshot)
    except Exception:
        _exception_snapshot.set((exc, snapshot))


def exception_snapshot(exc: BaseException) -> ProviderToolShapeSnapshotV1 | None:
    value = getattr(exc, "_r1_pa1_tool_shape_snapshot", None)
    if isinstance(value, ProviderToolShapeSnapshotV1):
        return value
    side_channel = _exception_snapshot.get()
    if side_channel is not None and side_channel[0] is exc:
        return side_channel[1]
    return None


def sealed_payload(payload: Mapping[str, Any], *, hash_field: str, domain: str) -> dict[str, Any]:
    result = dict(payload)
    result[hash_field] = domain_sha256(domain, {
        key: value for key, value in result.items() if key != hash_field
    })
    return result


def adapter_manifest_sha256(adapter_id: str, adapter_version: int) -> str:
    return domain_sha256("r1-pa1-provider-adapter-manifest-v1", {
        "adapter_id": adapter_id,
        "adapter_version": adapter_version,
        "snapshot_schema": "ProviderToolShapeSnapshotV1",
    })


def argument_shape(value: Any, *, present: bool = True) -> tuple[
    ArgumentShape, ArgumentParseStatus, int | None, str | None
]:
    if not present:
        return "missing", "not_attempted", None, None
    if value is None:
        encoded = b"null"
        return "null", "not_applicable", len(encoded), bytes_sha256("r1-pa1-argument-v1", encoded)
    if isinstance(value, dict):
        encoded = _canonical_bytes(value)
        return "object", "native_object", len(encoded), bytes_sha256("r1-pa1-argument-v1", encoded)
    if isinstance(value, list):
        encoded = _canonical_bytes(value)
        return "array", "not_applicable", len(encoded), bytes_sha256("r1-pa1-argument-v1", encoded)
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        try:
            json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            status: ArgumentParseStatus = "malformed"
        else:
            status = "parsed"
        return "string", status, len(encoded), bytes_sha256("r1-pa1-argument-v1", encoded)
    encoded = _canonical_bytes(str(type(value).__name__))
    return "other", "unknown", len(encoded), bytes_sha256("r1-pa1-argument-v1", encoded)


def tool_call_shape(
    *, ordinal: int, name: object, call_id: object, arguments: Any,
    arguments_present: bool, expected_registered_tool: str | None = None,
    partial: bool = False,
) -> ToolCallShapeV1:
    name_text = str(name or "")
    registered = (
        expected_registered_tool
        if expected_registered_tool and name_text == expected_registered_tool else None
    )
    shape, parse_status, byte_length, digest = argument_shape(
        arguments, present=arguments_present,
    )
    return ToolCallShapeV1(
        ordinal=ordinal,
        registered_tool_id=registered,
        unknown_tool_name_sha256=(
            None if registered else domain_sha256("r1-pa1-unknown-tool-name-v1", name_text)
        ),
        tool_call_id_sha256=(
            domain_sha256("r1-pa1-tool-call-id-v1", str(call_id)) if call_id else None
        ),
        arguments_present=arguments_present,
        argument_shape=shape,
        argument_json_parse_status=parse_status,
        argument_byte_length=byte_length,
        argument_sha256=digest,
        partial=partial,
    )


def provider_tool_shape_snapshot(
    *,
    adapter_id: str,
    adapter_version: int,
    provider_body: Any,
    provider_request_id: object,
    content_block_count: int | None,
    text_present: bool | None,
    tool_use_present: bool | None,
    finish_reason: object,
    calls: Sequence[Mapping[str, Any]],
    snapshot_status: SnapshotStatus = "snapshot_exact",
) -> ProviderToolShapeSnapshotV1:
    """Build a bounded snapshot without retaining names, IDs, or arguments."""
    call_shapes = [
        tool_call_shape(
            ordinal=index,
            name=item.get("name"),
            call_id=item.get("call_id"),
            arguments=item.get("arguments"),
            arguments_present=bool(item.get("arguments_present")),
            partial=bool(item.get("partial")),
        )
        for index, item in enumerate(calls[:MAX_OBSERVED_TOOL_CALLS])
    ]
    overflow = list(calls[MAX_OBSERVED_TOOL_CALLS:])
    finish_code, finish_hash = controlled_finish_reason(finish_reason)
    payload = {
        "schema": "ProviderToolShapeSnapshotV1",
        "version": 1,
        "canonicalization_version": DIAGNOSTIC_CANONICALIZATION_VERSION,
        "adapter_id": adapter_id,
        "adapter_version": adapter_version,
        "adapter_manifest_sha256": adapter_manifest_sha256(adapter_id, adapter_version),
        "snapshot_status": snapshot_status,
        "provider_response_sha256": domain_sha256(
            "r1-pa1-provider-response-v1", provider_body,
        ),
        "provider_request_id_sha256": (
            domain_sha256("r1-pa1-provider-request-id-v1", str(provider_request_id))
            if provider_request_id else None
        ),
        "raw_content_block_count": content_block_count,
        "raw_tool_call_count": len(calls),
        "raw_text_present": text_present,
        "raw_tool_use_present": tool_use_present,
        "raw_finish_reason_code": finish_code,
        "raw_finish_reason_sha256": finish_hash,
        "tool_calls": [item.model_dump(mode="json") for item in call_shapes],
        "overflow_tool_call_count": len(overflow),
        "overflow_tool_calls_sha256": (
            domain_sha256("r1-pa1-overflow-tool-shapes-v1", [
                {
                    "name_sha256": domain_sha256(
                        "r1-pa1-unknown-tool-name-v1", str(item.get("name") or ""),
                    ),
                    "call_id_sha256": domain_sha256(
                        "r1-pa1-tool-call-id-v1", str(item.get("call_id") or ""),
                    ),
                    "arguments_present": bool(item.get("arguments_present")),
                }
                for item in overflow
            ]) if overflow else None
        ),
    }
    return ProviderToolShapeSnapshotV1.model_validate(sealed_payload(
        payload,
        hash_field="snapshot_sha256",
        domain="r1-pa1-provider-snapshot-v1",
    ))


def unavailable_provider_snapshot(
    *, adapter_id: str, adapter_version: int, status: SnapshotStatus,
) -> ProviderToolShapeSnapshotV1:
    payload = {
        "schema": "ProviderToolShapeSnapshotV1",
        "version": 1,
        "canonicalization_version": DIAGNOSTIC_CANONICALIZATION_VERSION,
        "adapter_id": adapter_id,
        "adapter_version": adapter_version,
        "adapter_manifest_sha256": adapter_manifest_sha256(adapter_id, adapter_version),
        "snapshot_status": status,
        "raw_content_block_count": None,
        "raw_tool_call_count": None,
        "raw_text_present": None,
        "raw_tool_use_present": None,
        "tool_calls": [],
        "overflow_tool_call_count": 0,
    }
    return ProviderToolShapeSnapshotV1.model_validate(sealed_payload(
        payload,
        hash_field="snapshot_sha256",
        domain="r1-pa1-provider-snapshot-v1",
    ))


def provider_snapshot_with_status(
    snapshot: ProviderToolShapeSnapshotV1, status: SnapshotStatus,
) -> ProviderToolShapeSnapshotV1:
    payload = snapshot.model_dump(mode="json", by_alias=True)
    payload["snapshot_status"] = status
    return ProviderToolShapeSnapshotV1.model_validate(sealed_payload(
        payload,
        hash_field="snapshot_sha256",
        domain="r1-pa1-provider-snapshot-v1",
    ))


def _snapshot_with_correlation(
    snapshot: ProviderToolShapeSnapshotV1, correlation: str,
) -> ProviderToolShapeSnapshotV1:
    payload = snapshot.model_dump(mode="json", by_alias=True)
    payload["shape_correlation_sha256"] = correlation
    return ProviderToolShapeSnapshotV1.model_validate(sealed_payload(
        payload,
        hash_field="snapshot_sha256",
        domain="r1-pa1-provider-snapshot-v1",
    ))


def _adapter_identity(adapter: object) -> tuple[str, int]:
    adapter_id = str(getattr(adapter, "DIAGNOSTIC_ADAPTER_ID", "unknown_adapter"))
    version = int(getattr(adapter, "DIAGNOSTIC_ADAPTER_VERSION", 1))
    return adapter_id, version


def _request_tool_manifest(request: Any, expected_tool: str) -> tuple[int, str, str, str]:
    tools = list(getattr(request, "tools", ()) or ())
    manifest = []
    expected_schema_sha256 = domain_sha256("r1-pa1-tool-schema-v1", {})
    for tool in tools:
        name = str(getattr(tool, "name", ""))
        schema = getattr(tool, "input_schema", {}) or {}
        schema_hash = domain_sha256("r1-pa1-tool-schema-v1", schema)
        if name == expected_tool:
            expected_schema_sha256 = schema_hash
        manifest.append({
            "registered_tool_id": expected_tool if name == expected_tool else None,
            "unknown_tool_name_sha256": (
                None if name == expected_tool else domain_sha256(
                    "r1-pa1-unknown-request-tool-v1", name,
                )
            ),
            "schema_sha256": schema_hash,
            "description_sha256": domain_sha256(
                "r1-pa1-tool-description-v1", str(getattr(tool, "description", "")),
            ),
        })
    required = getattr(request, "required_tool", None)
    policy = (
        "forced_exact_tool" if required == expected_tool
        else "required" if required
        else "auto" if tools
        else "none"
    )
    return (
        len(tools),
        domain_sha256("r1-pa1-request-tool-manifest-v1", manifest),
        expected_schema_sha256,
        policy,
    )


def _snapshot_from_response_or_exception(
    *, response: Any | None, exc: BaseException | None, adapter: object,
) -> ProviderToolShapeSnapshotV1:
    candidate: Any = None
    if response is not None:
        provider_state = getattr(response, "provider_state", {}) or {}
        candidate = provider_state.get("_r1_pa1_tool_shape_snapshot")
    if candidate is None and exc is not None:
        candidate = exception_snapshot(exc)
    if isinstance(candidate, ProviderToolShapeSnapshotV1):
        return candidate
    if isinstance(candidate, Mapping):
        try:
            return ProviderToolShapeSnapshotV1.model_validate(candidate)
        except Exception:
            pass
    adapter_id, adapter_version = _adapter_identity(adapter)
    return unavailable_provider_snapshot(
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        status=(
            "adapter_exception_without_snapshot" if exc is not None
            else "snapshot_unavailable"
        ),
    )


def _normalized_shapes(
    response: Any | None, expected_tool: str,
) -> tuple[tuple[ToolCallShapeV1, ...], tuple[str, ...]]:
    calls = list(getattr(response, "tool_calls", ()) or ()) if response is not None else []
    shapes = tuple(
        tool_call_shape(
            ordinal=index,
            name=getattr(call, "name", ""),
            call_id=getattr(call, "id", None),
            arguments=getattr(call, "arguments", None),
            arguments_present=hasattr(call, "arguments"),
            expected_registered_tool=expected_tool,
        )
        for index, call in enumerate(calls[:MAX_OBSERVED_TOOL_CALLS])
    )
    call_ids = tuple(
        shape.tool_call_id_sha256 for shape in shapes if shape.tool_call_id_sha256
    )
    return shapes, call_ids


def _emit_ptr12_record(
    context: ModelDiagnosticContextV1,
    *,
    event_type: str,
    source_component: str,
    source_writer: str,
    payload: BaseModel,
) -> bool:
    if not ptr12_observer_enabled():
        return False
    try:
        from novel_flywheel.reliability_trace import emit_observation
        return emit_observation(
            context.project_root,
            event_type=event_type,
            source_component=source_component,
            source_writer=source_writer,
            observation_status="confirmed",
            correlation_id=context.inner_attempt_id,
            stage_id=context.boundary,
            payload=payload.model_dump(mode="json", by_alias=True),
        )
    except Exception:
        return False


def bind_ptr12_raw_shape_observation(
    context: ModelDiagnosticContextV1 | None,
    *,
    snapshot: Mapping[str, Any] | None,
    provider_id: str,
    model_id: str,
    route_fingerprint: str,
    schema_sha256: str | None,
    request_mode: str,
) -> ProviderRawShapeObservationV1 | None:
    """Bind an adapter snapshot to the canonical attempt and emit event A."""

    if not ptr12_observer_enabled() or context is None or snapshot is None:
        return None
    try:
        payload = {
            "schema": "ProviderRawShapeObservationV1",
            "version": 1,
            "correlation_id": context.inner_attempt_id,
            "external_call_number": _ptr12_external_call_number.get(),
            "run_sha256": context.run_sha256,
            "stage": context.stage,
            "boundary": context.boundary,
            "contract_id": context.contract_id,
            "contract_version": context.contract_version,
            "schema_sha256": schema_sha256 or None,
            "provider_fingerprint": domain_sha256(
                "r1-ptr12-provider-fingerprint-v1", provider_id,
            ),
            "model_fingerprint": domain_sha256(
                "r1-ptr12-model-fingerprint-v1", model_id,
            ),
            "route_fingerprint": route_fingerprint,
            "route_kind": (
                context.route_kind
                if context.route_kind in {"primary", "configured_fallback"}
                else "other"
            ),
            "request_mode": (
                "tool" if request_mode == "strict_tool"
                else "plain" if request_mode == "plain"
                else "structured" if request_mode in {
                    "strict_json_schema", "json_object",
                }
                else "unknown"
            ),
            "outer_retry_ordinal": context.outer_retry_ordinal,
            "runtime_instance_ordinal": context.runtime_ordinal,
            "inner_attempt_ordinal": context.inner_attempt_ordinal,
            **dict(snapshot),
        }
        record = ProviderRawShapeObservationV1.model_validate(payload)
        _emit_ptr12_record(
            context,
            event_type="diagnostic_provider_raw_shape_v1",
            source_component="models.ModelGateway._complete_resolved",
            source_writer="ProviderRawShapeObservationV1",
            payload=record,
        )
        return record
    except Exception:
        return None


_DELTA_DIMENSIONS = (
    ("BLOCK_TYPE_SEQUENCE", "raw_block_type_sequence", "content_block_type_sequence"),
    ("REASONING_COUNT", "reasoning_block_count", "reasoning_block_count"),
    ("TEXT_COUNT", "text_or_final_block_count", "text_block_count"),
    ("TOOL_COUNT", "tool_block_count", "tool_call_count"),
    ("VISIBLE_CHAR_COUNT", "raw_visible_char_count", "normalized_visible_text_chars"),
    ("TRANSPORT_COMPLETENESS", "transport_complete", "transport_complete"),
)


def observe_ptr12_shape_delta(
    context: ModelDiagnosticContextV1 | None,
    *,
    raw_shape: ProviderRawShapeObservationV1 | None,
    normalized_shape: Any | None,
    normalized_finish_reason: str | None,
) -> RawToNormalizedShapeDeltaV1 | None:
    """Compare two immutable observations without touching ModelResponse."""

    if not ptr12_observer_enabled() or context is None:
        return None
    try:
        changed: list[str] = []
        unavailable: list[str] = []
        if raw_shape is None:
            unavailable.append("RAW_SHAPE_UNAVAILABLE")
        if normalized_shape is None:
            unavailable.append("NORMALIZED_SHAPE_UNAVAILABLE")
        if raw_shape is not None and normalized_shape is not None:
            raw_payload = raw_shape.model_dump(mode="python")
            normalized_payload = normalized_shape.model_dump(mode="python")
            for dimension, raw_key, normalized_key in _DELTA_DIMENSIONS:
                left = raw_payload.get(raw_key)
                right = normalized_payload.get(normalized_key)
                if left is None or right is None:
                    unavailable.append(dimension)
                elif tuple(left) != tuple(right) if isinstance(left, (list, tuple)) else left != right:
                    changed.append(dimension)
            raw_finish = raw_shape.finish_reason_raw_class
            normalized_finish = normalized_finish_reason or "missing"
            finish_equivalent = (
                raw_finish == normalized_finish
                or {raw_finish, normalized_finish} <= {"length", "max_tokens", "max_output_tokens"}
            )
            if not finish_equivalent:
                changed.append("FINISH_REASON")
        state = "YES" if changed else "UNKNOWN" if unavailable else "NO"
        completeness = (
            "unavailable" if raw_shape is None or normalized_shape is None
            else "partial" if unavailable else "exact"
        )
        payload = {
            "schema": "RawToNormalizedShapeDeltaV1",
            "version": 1,
            "correlation_id": context.inner_attempt_id,
            "raw_shape_fingerprint": (
                raw_shape.raw_shape_fingerprint if raw_shape else None
            ),
            "normalized_shape_fingerprint": (
                normalized_shape.shape_sha256 if normalized_shape else None
            ),
            "representation_changed": state,
            "changed_dimensions": tuple(changed),
            "unavailable_dimensions": tuple(unavailable),
            "comparison_completeness": completeness,
        }
        record = RawToNormalizedShapeDeltaV1.model_validate(sealed_payload(
            payload, hash_field="delta_sha256", domain="r1-ptr12-shape-delta-v1",
        ))
        _emit_ptr12_record(
            context,
            event_type="diagnostic_provider_shape_delta_v1",
            source_component="models.ModelGateway._complete_resolved",
            source_writer="RawToNormalizedShapeDeltaV1",
            payload=record,
        )
        return record
    except Exception:
        return None


_PTR12_GUARD_REASON_ORDER = (
    ("SCOPE_INELIGIBLE", "guard_scope_eligible"),
    ("GUARD_NOT_REACHED", "guard_reached"),
    ("SHAPE_UNAVAILABLE", "shape_available"),
    ("REASONING_BLOCK_ABSENT", "reasoning_block_exists"),
    ("FINISH_REASON_NOT_MAX_TOKENS", "finish_reason_max_tokens"),
    ("RAW_VISIBLE_NONZERO", "raw_visible_chars_zero"),
    ("NORMALIZED_VISIBLE_NONZERO", "normalized_visible_chars_zero"),
    ("FINAL_TEXT_PRESENT", "final_text_absent"),
    ("TOOL_CALL_PRESENT", "tool_call_absent"),
    ("UNKNOWN_BLOCK_PRESENT", "unknown_block_absent"),
    ("CONTENT_NOT_ALL_REASONING", "content_all_reasoning"),
    ("PROJECTION_NOT_EXACT", "projection_exact"),
    ("TRANSPORT_INCOMPLETE", "transport_complete"),
)


def build_ptr12_guard_decision(
    context: ModelDiagnosticContextV1 | None,
    *,
    shape: Any | None,
    raw_shape: ProviderRawShapeObservationV1 | None,
    delta: RawToNormalizedShapeDeltaV1 | None,
    finish_reason: str | None,
    scope_eligible: bool,
    guard_reached: bool = True,
    guard_triggered: bool,
    provider_id: str,
    model_id: str,
    route_fingerprint: str,
    contract_identity: str,
    schema_sha256: str | None,
    negative_write_status: str = "NOT_REQUIRED",
    phase: str = "guard_evaluation",
    alternate_route_considered: bool | None = None,
    alternate_route_selected: bool | None = None,
    fail_close_selected: bool | None = None,
    recovery_status: str = "NOT_APPLICABLE",
    decision_receipt_sha256: str | None = None,
) -> PTR9GuardDecisionObserverV1 | None:
    if not ptr12_observer_enabled() or context is None:
        return None
    try:
        available = shape is not None
        values: dict[str, bool | None] = {
            "reasoning_block_exists": shape.reasoning_block_count > 0 if available else None,
            "finish_reason_max_tokens": (
                finish_reason in {"length", "max_output_tokens", "max_tokens", "model_length"}
            ) if finish_reason is not None else None,
            "raw_visible_chars_zero": (
                shape.provider_visible_text_chars == 0 if available else None
            ),
            "normalized_visible_chars_zero": (
                shape.normalized_visible_text_chars == 0 if available else None
            ),
            "final_text_absent": shape.text_block_count == 0 if available else None,
            "tool_call_absent": (
                shape.tool_call_count == 0 and shape.normalized_tool_call_count == 0
                if available else None
            ),
            "unknown_block_absent": shape.unknown_block_count == 0 if available else None,
            "content_all_reasoning": (
                shape.content_block_count == shape.reasoning_block_count
                if available else None
            ),
            "projection_exact": shape.adapter_projection_status == "exact" if available else None,
            "transport_complete": bool(shape.transport_complete) if available else None,
        }
        predicate = all(value is True for value in values.values()) if available else None
        base = {
            "correlation_id": context.inner_attempt_id,
            "guard_scope_eligible": scope_eligible,
            "guard_reached": guard_reached,
            "shape_available": available,
            **values,
            "predicate_all_true": predicate,
            "guard_triggered": guard_triggered,
            "raw_shape_fingerprint": raw_shape.raw_shape_fingerprint if raw_shape else None,
            "normalized_shape_fingerprint": shape.shape_sha256 if available else None,
            "representation_delta_sha256": delta.delta_sha256 if delta else None,
            "provider_fingerprint": domain_sha256("r1-ptr12-provider-fingerprint-v1", provider_id),
            "model_fingerprint": domain_sha256("r1-ptr12-model-fingerprint-v1", model_id),
            "route_fingerprint": route_fingerprint,
            "contract_identity": contract_identity or "unbound",
            "schema_sha256": schema_sha256 or None,
        }
        reasons = [
            reason for reason, key in _PTR12_GUARD_REASON_ORDER
            if base.get(key) is not True
        ]
        if delta is not None and delta.representation_changed == "YES":
            insertion = sum(
                reason in reasons for reason in (
                    "SCOPE_INELIGIBLE", "GUARD_NOT_REACHED", "SHAPE_UNAVAILABLE",
                )
            )
            reasons.insert(insertion, "REPRESENTATION_CHANGED")
        digest = decision_receipt_sha256 or domain_sha256(
            "r1-ptr12-guard-decision-v1", base,
        )
        status = negative_write_status if guard_triggered else "NOT_REQUIRED"
        payload = {
            "schema": "PTR9GuardDecisionObserverV1",
            "version": 1,
            "phase": phase,
            "decision_receipt_sha256": digest,
            **base,
            "negative_capability_write_attempted": guard_triggered,
            "negative_capability_written": status == "RECORDED",
            "negative_capability_write_status": status,
            "alternate_route_considered": alternate_route_considered,
            "alternate_route_selected": alternate_route_selected,
            "fail_close_selected": fail_close_selected,
            "primary_guard_miss_reason": reasons[0] if reasons and not guard_triggered else None,
            "guard_miss_reasons": tuple(reasons if not guard_triggered else ()),
            "recovery_status": recovery_status,
        }
        record = PTR9GuardDecisionObserverV1.model_validate(payload)
        if phase == "guard_evaluation":
            _ptr12_guard_decision_capture.set(record)
        _emit_ptr12_record(
            context,
            event_type="diagnostic_ptr9_guard_decision_v1",
            source_component=(
                "contract_runtime.execute_contract_runtime"
                if phase == "recovery_disposition"
                else "models.ModelGateway._complete_resolved"
            ),
            source_writer="PTR9GuardDecisionObserverV1",
            payload=record,
        )
        return record
    except Exception:
        return None


def emit_ptr12_guard_recovery(
    context: ModelDiagnosticContextV1 | None,
    decision: PTR9GuardDecisionObserverV1 | None,
    *,
    alternate_route_considered: bool,
    alternate_route_selected: bool,
    fail_close_selected: bool,
    recovery_status: str,
) -> bool:
    if not ptr12_observer_enabled() or context is None or decision is None:
        return False
    try:
        payload = decision.model_dump(mode="json", by_alias=True)
        payload.update({
            "phase": "recovery_disposition",
            "alternate_route_considered": alternate_route_considered,
            "alternate_route_selected": alternate_route_selected,
            "fail_close_selected": fail_close_selected,
            "recovery_status": recovery_status,
        })
        record = PTR9GuardDecisionObserverV1.model_validate(payload)
        return _emit_ptr12_record(
            context,
            event_type="diagnostic_ptr9_guard_decision_v1",
            source_component="contract_runtime.execute_contract_runtime",
            source_writer="PTR9GuardDecisionObserverV1",
            payload=record,
        )
    except Exception:
        return False


def emit_ptr12_output_limit_classification(
    context: ModelDiagnosticContextV1 | None,
    *,
    output_limit_seen: bool,
    receipt: Mapping[str, Any] | None,
    terminal: bool,
) -> bool:
    if not ptr12_observer_enabled() or context is None:
        return False
    try:
        source = dict(receipt or {})
        payload = {
            "schema": "ContractOutputLimitClassificationObservationV1",
            "version": 1,
            "correlation_id": context.inner_attempt_id,
            "output_limit_seen": output_limit_seen,
            "finish_reason_class": controlled_finish_reason(
                source.get("finish_reason")
            )[0],
            "aggregate_output_usage": (
                source.get("output_tokens")
                if isinstance(source.get("output_tokens"), int)
                and source.get("output_tokens") >= 0 else None
            ),
            "terminal_classification": (
                "CONTRACT_OUTPUT_LIMIT_EXHAUSTED"
                if terminal else "RUNTIME_CONTINUED_EXISTING_POLICY"
            ),
        }
        record = ContractOutputLimitClassificationObservationV1.model_validate(
            sealed_payload(
                payload, hash_field="classification_sha256",
                domain="r1-ptr12-output-limit-classification-v1",
            )
        )
        return _emit_ptr12_record(
            context,
            event_type="diagnostic_contract_output_limit_classification_v1",
            source_component="contract_runtime.execute_contract_runtime",
            source_writer="ContractOutputLimitClassificationObservationV1",
            payload=record,
        )
    except Exception:
        return False


def observe_strict_tool_shape(
    *,
    context: ModelDiagnosticContextV1 | None,
    adapter: object,
    provider_id: str,
    model_id: str,
    request: Any,
    expected_tool: str,
    response: Any | None = None,
    exc: BaseException | None = None,
) -> bool:
    """Emit a target-only observation; every failure is swallowed."""
    if not diagnostic_flag_enabled(STRICT_TOOL_FLAG):
        return False
    if not is_strict_tool_target(context):
        with _metrics_lock:
            _metrics.strict_tool_excluded_not_target += 1
        return False
    assert context is not None
    with _metrics_lock:
        _metrics.strict_tool_target_attempted += 1
    try:
        snapshot = _snapshot_from_response_or_exception(
            response=response, exc=exc, adapter=adapter,
        )
        declared_count, manifest_hash, schema_hash, tool_policy = (
            _request_tool_manifest(request, expected_tool)
        )
        correlation = domain_sha256("r1-pa1-shape-correlation-v1", {
            "run_sha256": context.run_sha256,
            "stage": context.stage,
            "boundary": context.boundary,
            "contract_id": context.contract_id,
            "contract_version": context.contract_version,
            "outer_retry_id": context.outer_retry_id,
            "runtime_instance_id": context.runtime_instance_id,
            "attempt_id": context.inner_attempt_id,
            "request_tool_manifest_sha256": manifest_hash,
            "adapter_manifest_sha256": snapshot.adapter_manifest_sha256,
        })
        snapshot = _snapshot_with_correlation(snapshot, correlation)
        normalized, normalized_ids = _normalized_shapes(response, expected_tool)
        normalized_count = len(getattr(response, "tool_calls", ()) or ()) \
            if response is not None else 0
        normalized_names = [
            str(getattr(call, "name", ""))
            for call in (getattr(response, "tool_calls", ()) or ())
        ] if response is not None else []
        unique_names = set(normalized_names)
        matching_count = normalized_names.count(expected_tool) if response is not None else None
        duplicate_call_ids = len(normalized_ids) - len(set(normalized_ids))
        duplicate_identities = len(normalized_names) - len(unique_names)
        if snapshot.raw_tool_call_count is None:
            projection = "unavailable"
        elif snapshot.raw_tool_call_count > normalized_count:
            projection = "dropped"
        elif snapshot.raw_tool_call_count < normalized_count:
            projection = "duplicated"
        else:
            projection = "exact"
        accepted = response is not None and matching_count == 1 and normalized_count == 1
        if exc is not None:
            failure_code = (
                "adapter_exception_with_snapshot"
                if snapshot.snapshot_status == "adapter_exception_with_snapshot"
                else "adapter_exception_without_snapshot"
            )
            decision = "adapter_exception_before_uniqueness"
        elif accepted:
            failure_code = None
            decision = "accept_unique_expected"
        elif snapshot.snapshot_status not in {
            "snapshot_exact", "adapter_exception_with_snapshot",
        }:
            failure_code = "snapshot_unavailable_or_partial"
            decision = "reject_current_uniqueness_rule"
        elif snapshot.raw_tool_call_count == 0:
            failure_code = "zero_tool_calls"
            decision = "reject_current_uniqueness_rule"
        elif projection == "dropped":
            failure_code = "adapter_tool_drop"
            decision = "reject_current_uniqueness_rule"
        elif projection == "duplicated" or duplicate_call_ids:
            failure_code = "adapter_tool_duplicate"
            decision = "reject_current_uniqueness_rule"
        elif normalized_count > 1 and matching_count and matching_count > 1:
            failure_code = "duplicate_expected_tool"
            decision = "reject_current_uniqueness_rule"
        elif normalized_count > 1:
            failure_code = "multiple_tool_calls"
            decision = "reject_current_uniqueness_rule"
        elif normalized_count == 1 and matching_count == 0:
            failure_code = "wrong_tool_identity"
            decision = "reject_current_uniqueness_rule"
        else:
            failure_code = "no_unique_artifact"
            decision = "reject_current_uniqueness_rule"
        status = (
            "exact" if snapshot.snapshot_status in {
                "snapshot_exact", "adapter_exception_with_snapshot",
            }
            else "partial" if snapshot.snapshot_status == "snapshot_partial"
            else "unavailable"
        )
        registered = tuple(sorted({
            shape.registered_tool_id for shape in normalized
            if shape.registered_tool_id is not None
        }))
        unknown_hashes = tuple(sorted({
            shape.unknown_tool_name_sha256 for shape in normalized
            if shape.unknown_tool_name_sha256 is not None
        }))
        payload = {
            "schema": "StrictToolShapeObservationV1",
            "version": 1,
            "canonicalization_version": DIAGNOSTIC_CANONICALIZATION_VERSION,
            "shape_correlation_sha256": correlation,
            "run_sha256": context.run_sha256,
            "stage": context.stage,
            "boundary": context.boundary,
            "role": context.role,
            "route_kind": context.route_kind,
            "provider_alias": snapshot.adapter_id,
            "provider_alias_sha256": domain_sha256(
                "r1-pa1-provider-binding-v1", provider_id,
            ),
            "model_alias": "registered_model",
            "model_alias_sha256": domain_sha256(
                "r1-pa1-model-binding-v1", model_id,
            ),
            "outer_retry_id": context.outer_retry_id,
            "contract_runtime_instance_id": context.runtime_instance_id,
            "attempt_id": context.inner_attempt_id,
            "parent_attempt_id": context.parent_attempt_id,
            "expected_tool_contract": context.contract_id,
            "expected_tool_contract_version": context.contract_version,
            "requested_expected_tool_id": expected_tool,
            "request_declared_tool_count": declared_count,
            "request_tool_manifest_sha256": manifest_hash,
            "expected_tool_schema_sha256": schema_hash,
            "tool_choice_policy": tool_policy,
            "request_protocol": snapshot.adapter_id,
            "adapter_version": snapshot.adapter_version,
            "adapter_manifest_sha256": snapshot.adapter_manifest_sha256,
            "expected_tool_call_count": 1,
            "provider_shape": snapshot.model_dump(mode="json", by_alias=True),
            "normalized_tool_call_count": normalized_count,
            "normalized_unique_tool_identity_count": len(unique_names),
            "normalized_tool_calls": [item.model_dump(mode="json") for item in normalized],
            "normalized_tool_call_id_hashes": normalized_ids,
            "duplicate_call_id_count": duplicate_call_ids,
            "duplicate_identity_count": duplicate_identities,
            "adapter_projection_status": projection,
            "gateway_matching_count": matching_count,
            "exact_expected_tool_match_count": matching_count,
            "observed_unique_tool_identity_count": len(unique_names) if response is not None else None,
            "unknown_tool_name_count": len(unknown_hashes) if response is not None else None,
            "observed_registered_tool_ids": registered,
            "unknown_tool_name_hashes": unknown_hashes,
            "content_block_count": snapshot.raw_content_block_count,
            "text_content_present": snapshot.raw_text_present,
            "tool_use_content_present": snapshot.raw_tool_use_present,
            "tool_arguments_present": (
                any(item.arguments_present for item in snapshot.tool_calls)
                if snapshot.raw_tool_call_count is not None else None
            ),
            "response_sha256": snapshot.provider_response_sha256,
            "finish_reason": snapshot.raw_finish_reason_code,
            "request_max_output_tokens": getattr(request, "max_output_tokens", None),
            "provider_request_id_sha256": snapshot.provider_request_id_sha256,
            "strict_tool_decision": decision,
            "strict_tool_failure_code": failure_code,
            "observation_status": status,
            "target_status": "target",
        }
        observation = StrictToolShapeObservationV1.model_validate(sealed_payload(
            payload,
            hash_field="observation_sha256",
            domain="r1-pa1-strict-observation-v1",
        ))
        from novel_flywheel.reliability_trace import emit_observation
        written = emit_observation(
            context.project_root,
            event_type="diagnostic_strict_tool_shape",
            source_component="ModelGateway._complete_resolved",
            source_writer="StrictToolShapeObserverV1",
            observation_status="confirmed" if status == "exact" else "unknown",
            correlation_id=correlation,
            stage_id=context.boundary,
            payload=observation.model_dump(mode="json", by_alias=True),
        )
        with _metrics_lock:
            if written:
                _metrics.strict_tool_written += 1
            else:
                _metrics.strict_tool_dropped += 1
        return written
    except Exception:
        with _metrics_lock:
            _metrics.strict_tool_dropped += 1
        return False


def build_budget_lineage_record(
    context: ModelDiagnosticContextV1,
    **values: Any,
) -> PlanningAdaptationOutputBudgetLineageV1:
    system = str(values.pop("system", ""))
    user = str(values.pop("user", ""))
    contract_schema = values.pop("contract_schema", {})
    payload = {
        "schema": "PlanningAdaptationOutputBudgetLineageV1",
        "version": 1,
        "canonicalization_version": DIAGNOSTIC_CANONICALIZATION_VERSION,
        "run_sha256": context.run_sha256,
        "stage": context.stage,
        "boundary": context.boundary,
        "role": context.role,
        "contract_id": context.contract_id,
        "contract_version": context.contract_version,
        "outer_retry_id": context.outer_retry_id,
        "contract_runtime_instance_id": context.runtime_instance_id,
        "previous_contract_runtime_instance_id": values.pop(
            "previous_contract_runtime_instance_id", None,
        ),
        "inner_attempt_id": context.inner_attempt_id,
        "parent_attempt_id": context.parent_attempt_id,
        "expansion_policy": "context_policy.expanded_output_budget",
        "expansion_policy_version": 1,
        "provider_declared_output_limit": context.provider_declared_output_limit,
        "provider_limit_status": context.provider_limit_status,
        "request_parameter_name": context.request_parameter_name,
        "prompt_system_sha256": domain_sha256("r1-pa1-system-prompt-v1", system),
        "prompt_user_sha256": domain_sha256("r1-pa1-user-prompt-v1", user),
        "contract_sha256": domain_sha256("r1-pa1-contract-v1", {
            "id": context.contract_id,
            "version": context.contract_version,
            "schema": contract_schema,
        }),
        "provider_binding_sha256": context.provider_binding_sha256,
        "model_binding_sha256": context.model_binding_sha256,
        **values,
    }
    return PlanningAdaptationOutputBudgetLineageV1.model_validate(sealed_payload(
        payload,
        hash_field="lineage_receipt_sha256",
        domain="r1-pa1-budget-lineage-v1",
    ))


def emit_budget_lineage(
    context: ModelDiagnosticContextV1 | None,
    **values: Any,
) -> bool:
    if not diagnostic_flag_enabled(BUDGET_LINEAGE_FLAG) or context is None:
        return False
    with _metrics_lock:
        _metrics.budget_attempted += 1
    try:
        record = build_budget_lineage_record(context, **values)
        from novel_flywheel.reliability_trace import emit_observation
        written = emit_observation(
            context.project_root,
            event_type="diagnostic_output_budget_lineage",
            source_component="contract_runtime.execute_contract_runtime",
            source_writer="PlanningAdaptationOutputBudgetObserverV1",
            observation_status="confirmed",
            correlation_id=context.runtime_instance_id,
            stage_id=context.boundary,
            payload=record.model_dump(mode="json", by_alias=True),
        )
        with _metrics_lock:
            if written:
                _metrics.budget_written += 1
            else:
                _metrics.budget_dropped += 1
        return written
    except Exception:
        with _metrics_lock:
            _metrics.budget_dropped += 1
        return False
