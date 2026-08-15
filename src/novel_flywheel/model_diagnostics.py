"""Fail-open, hash-only model boundary diagnostics.

The records in this module are operational observations.  They never authorize
an artifact, alter a provider request, or participate in retry/fallback state.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


DIAGNOSTIC_CANONICALIZATION_VERSION = "r1-pa1-diagnostic-canonical-json-v1"
STRICT_TOOL_FLAG = "NOVEL_STRICT_TOOL_SHAPE_TRACE_V1"
BUDGET_LINEAGE_FLAG = "NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1"
MAX_OBSERVED_TOOL_CALLS = 32

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


def is_strict_tool_target(context: ModelDiagnosticContextV1 | None) -> bool:
    return bool(context and (
        context.stage == "review"
        and context.boundary == "planning_adaptation_whole_receipt"
        and context.contract_id == "planning_adaptation_whole"
        and context.contract_version == 1
        and context.role == "review"
        and context.route_kind == "configured_fallback"
    ))


_exception_snapshot: contextvars.ContextVar[
    tuple[BaseException, ProviderToolShapeSnapshotV1] | None
] = contextvars.ContextVar("r1_pa1_exception_snapshot", default=None)


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

