"""Canary-only, hash/shape/count contracts for the R1-PTR4 capability probe.

This module does not create provider clients, assemble prompts, choose routes,
or execute models.  It defines the evidence that a separately authorized,
single-use probe must produce.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import MISSING, asdict, dataclass, fields
import hashlib
import json
from pathlib import Path
import types
from typing import Any, Literal, Mapping, Sequence, get_args, get_origin, get_type_hints

from novel_flywheel.generated_artifacts import registered_business_wire_schema
from novel_flywheel.runtime_fingerprint_build import domain_sha256


SHA256_PATTERN = r"^[0-9a-f]{64}$"
PARENT_DIR = Path("docs/superpowers/reports/r1-ptr4")
PARENT_CANONICAL_SHA256 = (
    "e7806b206edbdddf21a1ea74c7d0ebbb327ccedf7216f528c281c4ac2edfdf4c"
)
SOURCE_WORKLOAD = Path("tests/fixtures/canary/short-normal-v1.json")
SOURCE_WORKLOAD_SHA256 = (
    "c2eff79242ff5a746ff263ff28639c950180ecc0565643e8ffebcdd8d16158d1"
)
EXTERNAL_ACTION_COUNTERS = {
    "credential_lookup_count": 0,
    "provider_client_creation_count": 0,
    "network_call_count": 0,
    "model_call_count": 0,
    "paid_model_call_count": 0,
}

ProbeShapeClass = Literal[
    "TEXT_TRUNCATED",
    "TOOL_ARGUMENTS_TRUNCATED",
    "TOOL_ONLY",
    "REASONING_ONLY",
    "ZERO_VISIBLE_MAX_TOKENS",
    "EMPTY_PROVIDER_RESPONSE",
    "ADAPTER_VISIBLE_CONTENT_LOSS",
    "MIXED_BLOCK_TRUNCATION",
    "OTHER_TYPED_CLASS",
    "UNKNOWN",
]

KNOWN_BLOCK_TYPES = frozenset({
    "text", "output_text", "tool_use", "tool_call", "function_call",
    "reasoning", "thinking", "redacted_thinking",
})
TEXT_TYPES = frozenset({"text", "output_text"})
TOOL_TYPES = frozenset({"tool_use", "tool_call", "function_call"})
REASONING_TYPES = frozenset({
    "reasoning", "thinking", "redacted_thinking",
})


class ProviderCapabilityProbeContractError(ValueError):
    """Stable, fail-closed contract construction error."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class _FrozenModel:
    """Small stdlib-only strict record used inside the Canary import closure."""

    @classmethod
    def model_validate(cls, value: Mapping[str, Any]):
        payload = dict(value)
        field_names = {item.name for item in fields(cls)}
        if "schema_name" in field_names and "schema" in payload:
            if "schema_name" in payload:
                raise ValueError("duplicate_schema_field")
            payload["schema_name"] = payload.pop("schema")
        extra = set(payload) - field_names
        if extra:
            raise ValueError(f"unregistered_fields:{','.join(sorted(extra))}")
        hints = get_type_hints(cls)
        for name, annotation in hints.items():
            if name in payload:
                payload[name] = _coerce_record_value(annotation, payload[name])
        return cls(**payload)

    def model_dump(self, *, mode: str = "python", by_alias: bool = False):
        payload = asdict(self)
        if by_alias and "schema_name" in payload:
            payload["schema"] = payload.pop("schema_name")
        return _json_compatible(payload) if mode == "json" else payload

    @classmethod
    def model_json_schema(cls, *, by_alias: bool = False):
        descriptors = []
        hints = get_type_hints(cls)
        for item in fields(cls):
            name = "schema" if by_alias and item.name == "schema_name" else item.name
            descriptors.append({
                "name": name,
                "type": _type_descriptor(hints[item.name]),
                "required": item.default is MISSING and item.default_factory is MISSING,
            })
        return {
            "title": cls.__name__,
            "type": "object",
            "additionalProperties": False,
            "fields": descriptors,
        }

    def __post_init__(self) -> None:
        _validate_record(self)


@dataclass(frozen=True, kw_only=True)
class ProviderCapabilityProbeBoundaryIdentityV1(_FrozenModel):
    boundary: Literal[12] = 12
    role: Literal["planning"] = "planning"
    stage: Literal["planning"] = "planning"
    substage: Literal[
        "planning-semantic-v2-segment-01-packet-000001-0"
    ] = "planning-semantic-v2-segment-01-packet-000001-0"
    semantic_scope: Literal["nested_semantic_packet"] = "nested_semantic_packet"
    contract_name: Literal["planning_semantic_v2"] = "planning_semantic_v2"
    contract_version: Literal[2] = 2
    contract_sha256: str
    provider_descriptor_hash: str
    model_binding_hash: str
    route_kind: Literal["configured_fallback"] = "configured_fallback"
    route_attempt: Literal[2] = 2
    protocol: Literal["anthropic"] = "anthropic"
    execution_mode: Literal["plain"] = "plain"
    requested_max_output_tokens: Literal[8798] = 8798
    local_effective_max_output_tokens: Literal[8798] = 8798
    effective_provider_max_output_tokens: int | None = None
    system_sha256: str
    user_sha256: str
    request_wire_schema_sha256: str
    tool_schema_sha256: str
    adapter_identity_sha256: str
    parser_identity_sha256: str
    strict_tool_identity_sha256: str
    output_limit_observer_identity_sha256: str
    identity_sha256: str


@dataclass(frozen=True, kw_only=True)
class ProviderCapabilityProbeDefinitionV1(_FrozenModel):
    schema_name: Literal[
        "ProviderCapabilityProbeDefinitionV1"
    ] = "ProviderCapabilityProbeDefinitionV1"
    version: Literal[1] = 1
    parent_evidence_canonical_sha256: str
    parent_evidence_status: Literal["exact"] = "exact"
    target: ProviderCapabilityProbeBoundaryIdentityV1
    classifications: tuple[ProbeShapeClass, ...]
    pre_normalization_fields: tuple[str, ...]
    post_adapter_fields: tuple[str, ...]
    request_materialization_policy: Literal[
        "sanitized_source_reassembly_must_match_sealed_request_hashes"
    ] = "sanitized_source_reassembly_must_match_sealed_request_hashes"
    one_call_only: Literal[True] = True
    retry_allowed: Literal[False] = False
    fallback_selection_allowed: Literal[False] = False
    output_budget_mutation_allowed: Literal[False] = False
    production_behavior_changed: Literal[False] = False
    raw_prompt_omitted: Literal[True] = True
    raw_story_omitted: Literal[True] = True
    raw_tool_arguments_omitted: Literal[True] = True
    raw_provider_response_omitted: Literal[True] = True
    external_action_counters: Mapping[str, Literal[0]]
    observer_schema_sha256: str
    definition_sha256: str


@dataclass(frozen=True, kw_only=True)
class ProviderCapabilityProbeFixtureV1(_FrozenModel):
    schema_name: Literal[
        "ProviderCapabilityProbeFixtureV1"
    ] = "ProviderCapabilityProbeFixtureV1"
    version: Literal[1] = 1
    fixture_id: Literal[
        "r1-ptr4-boundary12-short-normal-v1-hash-bound"
    ] = "r1-ptr4-boundary12-short-normal-v1-hash-bound"
    source_workload_id: Literal["short-normal-v1"] = "short-normal-v1"
    source_workload_file: Literal[
        "tests/fixtures/canary/short-normal-v1.json"
    ] = "tests/fixtures/canary/short-normal-v1.json"
    source_workload_sha256: str
    request_shape_sha256: str
    contract_sha256: str
    tool_schema_sha256: str
    target_boundary_identity_sha256: str
    reassembly_system_sha256: str
    reassembly_user_sha256: str
    fixture_status: Literal["exact_hash_bound"] = "exact_hash_bound"
    input_content_embedded: Literal[False] = False
    raw_prompt_omitted: Literal[True] = True
    raw_story_omitted: Literal[True] = True
    raw_tool_arguments_omitted: Literal[True] = True
    fixture_sha256: str


@dataclass(frozen=True, kw_only=True)
class ProviderContentBlockMetadataV1(_FrozenModel):
    """Content-free metadata captured before adapter normalization."""

    block_type: str
    visible_text_characters: int = 0
    tool_arguments_present: bool = False
    tool_argument_byte_length: int = 0
    partial_tool_arguments: bool = False


@dataclass(frozen=True, kw_only=True)
class ProviderCapabilityProbePreNormalizationV1(_FrozenModel):
    provider_descriptor_hash: str
    model_binding_hash: str
    route_kind: Literal["configured_fallback"] = "configured_fallback"
    protocol: Literal["anthropic"] = "anthropic"
    finish_reason: Literal[
        "max_tokens", "end_turn", "length", "stop_sequence", "tool_use",
        "other", "unknown",
    ]
    finish_reason_sha256: str | None = None
    output_tokens: int
    requested_max_output_tokens: int
    effective_provider_max_output_tokens: int | None = None
    content_block_count: int
    content_block_type_sequence: tuple[str, ...]
    unknown_block_type_sha256s: tuple[str, ...]
    text_block_count: int
    visible_text_characters: int
    tool_call_count: int
    tool_arguments_present: bool
    tool_argument_byte_length: int
    partial_tool_argument_count: int
    reasoning_block_count: int
    unknown_block_count: int
    zero_visible: bool
    empty_content: bool
    max_tokens: bool
    raw_content_omitted: Literal[True] = True


@dataclass(frozen=True, kw_only=True)
class ProviderCapabilityProbePostAdapterV1(_FrozenModel):
    adapter_visible_text: bool
    adapter_visible_characters: int
    adapter_tool_arguments_present: bool
    parser_reached: bool
    strict_tool_reached: bool
    json_conversion_reached: bool
    wire_schema_reached: bool
    semantic_validation_reached: bool
    output_limit_classifier: ProbeShapeClass
    lineage_receipt_sha256: str
    raw_content_omitted: Literal[True] = True


@dataclass(frozen=True, kw_only=True)
class ProviderCapabilityProbeObservationV1(_FrozenModel):
    schema_name: Literal[
        "ProviderCapabilityProbeObservationV1"
    ] = "ProviderCapabilityProbeObservationV1"
    version: Literal[1] = 1
    definition_sha256: str
    fixture_sha256: str
    target_boundary_identity_sha256: str
    pre_normalization: ProviderCapabilityProbePreNormalizationV1
    post_adapter: ProviderCapabilityProbePostAdapterV1
    provider_capability_evidence_status: Literal[
        "fake_rehearsal_only", "real_probe_observed"
    ]
    external_action_counters: Mapping[str, Literal[0]]
    raw_prompt_omitted: Literal[True] = True
    raw_story_omitted: Literal[True] = True
    raw_tool_arguments_omitted: Literal[True] = True
    raw_provider_response_omitted: Literal[True] = True
    receipt_sha256: str


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_compatible(item) for item in value]
    return value


def _type_descriptor(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is Literal:
        return "literal:" + "|".join(repr(item) for item in get_args(annotation))
    if origin in {tuple, list, Sequence}:
        return "array"
    if origin in {dict, Mapping}:
        return "object"
    if origin in {types.UnionType}:
        return "union:" + "|".join(_type_descriptor(item) for item in get_args(annotation))
    return getattr(annotation, "__name__", str(annotation))


def _coerce_record_value(annotation: Any, value: Any) -> Any:
    origin = get_origin(annotation)
    if isinstance(annotation, type) and issubclass(annotation, _FrozenModel):
        return annotation.model_validate(value) if isinstance(value, Mapping) else value
    if origin is tuple and isinstance(value, (tuple, list)):
        return tuple(value)
    if origin in {types.UnionType}:
        for candidate in get_args(annotation):
            if isinstance(candidate, type) and issubclass(candidate, _FrozenModel):
                if isinstance(value, Mapping):
                    return candidate.model_validate(value)
    return value


def _matches_literal(annotation: Any, value: Any) -> bool:
    if get_origin(annotation) is Literal:
        return value in get_args(annotation)
    return True


def _validate_record(record: _FrozenModel) -> None:
    hints = get_type_hints(type(record))
    for item in fields(record):
        value = getattr(record, item.name)
        if not _matches_literal(hints[item.name], value):
            raise ValueError(f"invalid_literal:{item.name}")
        if (
            value is not None
            and isinstance(value, str)
            and (item.name.endswith("sha256") or item.name.endswith("_hash"))
            and not (len(value) == 64 and all(ch in "0123456789abcdef" for ch in value))
        ):
            raise ValueError(f"invalid_sha256:{item.name}")
        if isinstance(value, int) and not isinstance(value, bool):
            if any(token in item.name for token in (
                "count", "characters", "length", "output_tokens",
            )) and value < 0:
                raise ValueError(f"negative_measure:{item.name}")
            if (
                "max_output_tokens" in item.name
                and value < 1
            ):
                raise ValueError(f"invalid_output_budget:{item.name}")
    if isinstance(record, ProviderContentBlockMetadataV1):
        if not record.block_type or len(record.block_type) > 64:
            raise ValueError("invalid_block_type")
    actions = getattr(record, "external_action_counters", None)
    if actions is not None and (
        dict(actions) != EXTERNAL_ACTION_COUNTERS
        or any(value != 0 for value in actions.values())
    ):
        raise ValueError("external_action_counter_nonzero")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _sealed(
    model: type[_FrozenModel], body: Mapping[str, Any], *,
    hash_field: str, domain: str,
) -> Any:
    payload = deepcopy(dict(body))
    payload[hash_field] = domain_sha256(domain, payload)
    return model.model_validate(payload)


def verify_ptr4_parent_evidence(repo_root: Path) -> dict[str, Any]:
    parent = repo_root / PARENT_DIR
    manifest_path = parent / "r1-ptr4-sha256-manifest-v1.json"
    privacy_path = parent / "r1-ptr4-privacy-scan-v1.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        privacy = json.loads(privacy_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProviderCapabilityProbeContractError(
            "ptr4_parent_evidence_unreadable"
        ) from exc
    if manifest.get("evidence_canonical_sha256") != PARENT_CANONICAL_SHA256:
        raise ProviderCapabilityProbeContractError(
            "ptr4_parent_canonical_sha256_mismatch"
        )
    rows: list[str] = []
    for entry in sorted(manifest.get("files") or (), key=lambda item: item["path"]):
        path = repo_root / entry["path"]
        if (
            not path.is_file()
            or path.stat().st_size != entry["bytes"]
            or _file_sha256(path) != entry["sha256"]
        ):
            raise ProviderCapabilityProbeContractError(
                "ptr4_parent_file_mismatch"
            )
        rows.append(f"{entry['path']}|{entry['bytes']}|{entry['sha256']}")
    canonical = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
    if canonical != PARENT_CANONICAL_SHA256:
        raise ProviderCapabilityProbeContractError(
            "ptr4_parent_manifest_recalculation_mismatch"
        )
    if privacy.get("status") != "exact" or privacy.get("violation_count") != 0:
        raise ProviderCapabilityProbeContractError("ptr4_parent_privacy_not_exact")
    return {
        "status": "exact",
        "canonical_sha256": canonical,
        "privacy_status": "exact",
        "privacy_violation_count": 0,
    }


def _boundary_12(repo_root: Path) -> dict[str, Any]:
    path = repo_root / PARENT_DIR / "r1-ptr4-boundary-reconstruction-v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    matches = [item for item in data.get("boundaries") or () if item.get("boundary") == 12]
    if len(matches) != 1:
        raise ProviderCapabilityProbeContractError("boundary_12_not_unique")
    boundary = matches[0]
    expected = {
        "stage": "planning",
        "substage": "planning-semantic-v2-segment-01-packet-000001-0",
        "semantic_scope": "nested_semantic_packet",
        "contract_name": "planning_semantic_v2",
        "contract_version": 2,
        "route_kind": "configured_fallback",
        "route_attempt": 2,
        "protocol": "anthropic",
        "execution_mode": "plain",
        "requested_max_output_tokens": 8798,
        "local_effective_max_output_tokens": 8798,
    }
    if any(boundary.get(key) != value for key, value in expected.items()):
        raise ProviderCapabilityProbeContractError("boundary_12_identity_mismatch")
    return boundary


def build_provider_capability_probe_definition_v1(
    repo_root: Path,
) -> ProviderCapabilityProbeDefinitionV1:
    repo_root = repo_root.resolve()
    verify_ptr4_parent_evidence(repo_root)
    boundary = _boundary_12(repo_root)
    wire_schema_sha256 = _json_sha256(
        registered_business_wire_schema("planning_semantic_v2")
    )
    tool_schema_sha256 = domain_sha256(
        "r1-ptr4-v1-plain-tool-schema-v1",
        {"tools": [], "required_tool": None, "execution_mode": "plain"},
    )
    adapter_identity_sha256 = domain_sha256(
        "r1-ptr4-v1-adapter-identity-v1",
        {
            "adapter": "AnthropicAdapter.complete",
            "adapter_id": "anthropic",
            "adapter_version": 1,
            "source_sha256": _file_sha256(
                repo_root / "src/novel_flywheel/providers/anthropic.py"
            ),
        },
    )
    parser_identity_sha256 = domain_sha256(
        "r1-ptr4-v1-parser-identity-v1",
        {
            "parser": "novel_flywheel.model_output.parse_json_object",
            "source_sha256": _file_sha256(
                repo_root / "src/novel_flywheel/model_output.py"
            ),
        },
    )
    strict_tool_identity_sha256 = domain_sha256(
        "r1-ptr4-v1-strict-tool-identity-v1",
        {
            "execution_mode": "plain",
            "strict_tool_reached": False,
            "tools": [],
            "required_tool": None,
            "model_gateway_source_sha256": _file_sha256(
                repo_root / "src/novel_flywheel/models.py"
            ),
        },
    )
    output_limit_observer_identity_sha256 = domain_sha256(
        "r1-ptr4-v1-output-limit-observer-identity-v1",
        {
            "observer": "ProviderCapabilityProbeObservationV1",
            "parent_observer": "PlanningRepairOutputLimitObservationV1",
            "parent_observer_source_sha256": _file_sha256(
                repo_root / "src/novel_flywheel/planning_repair_diagnostics.py"
            ),
            "classification_is_canary_only": True,
        },
    )
    identity_body = {
        "boundary": 12,
        "role": "planning",
        "stage": boundary["stage"],
        "substage": boundary["substage"],
        "semantic_scope": boundary["semantic_scope"],
        "contract_name": boundary["contract_name"],
        "contract_version": boundary["contract_version"],
        "contract_sha256": boundary["contract_sha256"],
        "provider_descriptor_hash": boundary["provider_descriptor_hash"],
        "model_binding_hash": boundary["model_binding_hash"],
        "route_kind": boundary["route_kind"],
        "route_attempt": boundary["route_attempt"],
        "protocol": boundary["protocol"],
        "execution_mode": boundary["execution_mode"],
        "requested_max_output_tokens": boundary["requested_max_output_tokens"],
        "local_effective_max_output_tokens": boundary[
            "local_effective_max_output_tokens"
        ],
        "effective_provider_max_output_tokens": boundary[
            "effective_provider_max_output_tokens"
        ],
        "system_sha256": boundary["system_sha256"],
        "user_sha256": boundary["user_sha256"],
        "request_wire_schema_sha256": wire_schema_sha256,
        "tool_schema_sha256": tool_schema_sha256,
        "adapter_identity_sha256": adapter_identity_sha256,
        "parser_identity_sha256": parser_identity_sha256,
        "strict_tool_identity_sha256": strict_tool_identity_sha256,
        "output_limit_observer_identity_sha256": (
            output_limit_observer_identity_sha256
        ),
    }
    identity = ProviderCapabilityProbeBoundaryIdentityV1.model_validate({
        **identity_body,
        "identity_sha256": domain_sha256(
            "r1-ptr4-v1-boundary-12-identity-v1", identity_body,
        ),
    })
    observer_schema_sha256 = _json_sha256(
        ProviderCapabilityProbeObservationV1.model_json_schema(by_alias=True)
    )
    body = {
        "schema": "ProviderCapabilityProbeDefinitionV1",
        "version": 1,
        "parent_evidence_canonical_sha256": PARENT_CANONICAL_SHA256,
        "parent_evidence_status": "exact",
        "target": identity.model_dump(mode="json"),
        "classifications": tuple(ProbeShapeClass.__args__),
        "pre_normalization_fields": tuple(
            item.name for item in fields(ProviderCapabilityProbePreNormalizationV1)
        ),
        "post_adapter_fields": tuple(
            item.name for item in fields(ProviderCapabilityProbePostAdapterV1)
        ),
        "request_materialization_policy": (
            "sanitized_source_reassembly_must_match_sealed_request_hashes"
        ),
        "one_call_only": True,
        "retry_allowed": False,
        "fallback_selection_allowed": False,
        "output_budget_mutation_allowed": False,
        "production_behavior_changed": False,
        "raw_prompt_omitted": True,
        "raw_story_omitted": True,
        "raw_tool_arguments_omitted": True,
        "raw_provider_response_omitted": True,
        "external_action_counters": EXTERNAL_ACTION_COUNTERS,
        "observer_schema_sha256": observer_schema_sha256,
    }
    return _sealed(
        ProviderCapabilityProbeDefinitionV1, body,
        hash_field="definition_sha256",
        domain="r1-ptr4-v1-provider-capability-probe-definition-v1",
    )


def build_provider_capability_probe_fixture_v1(
    repo_root: Path,
    definition: ProviderCapabilityProbeDefinitionV1,
) -> ProviderCapabilityProbeFixtureV1:
    source = repo_root.resolve() / SOURCE_WORKLOAD
    if not source.is_file() or _file_sha256(source) != SOURCE_WORKLOAD_SHA256:
        raise ProviderCapabilityProbeContractError(
            "R1_PTR4_V1_PROBE_FIXTURE_NOT_AVAILABLE"
        )
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProviderCapabilityProbeContractError(
            "R1_PTR4_V1_PROBE_FIXTURE_NOT_AVAILABLE"
        ) from exc
    if (
        payload.get("schema") != "SanitizedCanaryShortWorkloadV1"
        or payload.get("workload_id") != "short-normal-v1"
    ):
        raise ProviderCapabilityProbeContractError(
            "R1_PTR4_V1_PROBE_FIXTURE_NOT_AVAILABLE"
        )
    target = definition.target
    request_shape_body = {
        "source_workload_sha256": SOURCE_WORKLOAD_SHA256,
        "target_boundary_identity_sha256": target.identity_sha256,
        "system_sha256": target.system_sha256,
        "user_sha256": target.user_sha256,
        "contract_sha256": target.contract_sha256,
        "request_wire_schema_sha256": target.request_wire_schema_sha256,
        "tool_schema_sha256": target.tool_schema_sha256,
        "execution_mode": target.execution_mode,
        "requested_max_output_tokens": target.requested_max_output_tokens,
        "raw_input_embedded": False,
    }
    body = {
        "schema": "ProviderCapabilityProbeFixtureV1",
        "version": 1,
        "fixture_id": "r1-ptr4-boundary12-short-normal-v1-hash-bound",
        "source_workload_id": "short-normal-v1",
        "source_workload_file": SOURCE_WORKLOAD.as_posix(),
        "source_workload_sha256": SOURCE_WORKLOAD_SHA256,
        "request_shape_sha256": domain_sha256(
            "r1-ptr4-v1-request-shape-v1", request_shape_body,
        ),
        "contract_sha256": target.contract_sha256,
        "tool_schema_sha256": target.tool_schema_sha256,
        "target_boundary_identity_sha256": target.identity_sha256,
        "reassembly_system_sha256": target.system_sha256,
        "reassembly_user_sha256": target.user_sha256,
        "fixture_status": "exact_hash_bound",
        "input_content_embedded": False,
        "raw_prompt_omitted": True,
        "raw_story_omitted": True,
        "raw_tool_arguments_omitted": True,
    }
    return _sealed(
        ProviderCapabilityProbeFixtureV1, body,
        hash_field="fixture_sha256",
        domain="r1-ptr4-v1-provider-capability-probe-fixture-v1",
    )


def _finish_reason(value: object) -> tuple[str, str | None]:
    normalized = str(value or "unknown").strip().casefold() or "unknown"
    aliases = {"length": "length", "max_tokens": "max_tokens"}
    if normalized in {"end_turn", "stop_sequence", "tool_use", "unknown"}:
        return normalized, None
    if normalized in aliases:
        return aliases[normalized], None
    return "other", domain_sha256("r1-ptr4-v1-finish-reason-v1", normalized)


def _block_type(value: str) -> tuple[str, str | None]:
    normalized = str(value or "unknown").strip().casefold() or "unknown"
    if normalized in KNOWN_BLOCK_TYPES:
        return normalized, None
    return "unknown", domain_sha256(
        "r1-ptr4-v1-unknown-content-block-type-v1", normalized,
    )


def _classify(
    *, pre: Mapping[str, Any], adapter_visible_characters: int,
    adapter_tool_arguments_present: bool,
) -> ProbeShapeClass:
    if pre["unknown_block_count"]:
        return "UNKNOWN"
    if (
        adapter_visible_characters < pre["visible_text_characters"]
        or (
            pre["tool_arguments_present"]
            and not adapter_tool_arguments_present
        )
    ):
        return "ADAPTER_VISIBLE_CONTENT_LOSS"
    if pre["empty_content"]:
        return (
            "ZERO_VISIBLE_MAX_TOKENS"
            if pre["max_tokens"] else "EMPTY_PROVIDER_RESPONSE"
        )
    topology_classes = sum(bool(pre[field]) for field in (
        "text_block_count", "tool_call_count", "reasoning_block_count",
    ))
    if pre["max_tokens"] and topology_classes > 1:
        return "MIXED_BLOCK_TRUNCATION"
    if (
        pre["max_tokens"]
        and pre["tool_call_count"]
        and pre["partial_tool_argument_count"]
    ):
        return "TOOL_ARGUMENTS_TRUNCATED"
    if (
        pre["reasoning_block_count"]
        and not pre["text_block_count"]
        and not pre["tool_call_count"]
    ):
        return "REASONING_ONLY"
    if pre["tool_call_count"] and not pre["text_block_count"]:
        return "TOOL_ONLY"
    if pre["max_tokens"] and pre["visible_text_characters"]:
        return "TEXT_TRUNCATED"
    if pre["max_tokens"] and pre["zero_visible"]:
        return "ZERO_VISIBLE_MAX_TOKENS"
    return "OTHER_TYPED_CLASS"


def build_provider_capability_probe_observation_v1(
    *,
    definition: ProviderCapabilityProbeDefinitionV1,
    fixture: ProviderCapabilityProbeFixtureV1,
    blocks: Sequence[ProviderContentBlockMetadataV1 | Mapping[str, Any]],
    finish_reason: object,
    output_tokens: int,
    effective_provider_max_output_tokens: int | None,
    adapter_visible_characters: int,
    adapter_tool_arguments_present: bool,
    parser_reached: bool,
    strict_tool_reached: bool,
    json_conversion_reached: bool,
    wire_schema_reached: bool,
    semantic_validation_reached: bool,
    provider_capability_evidence_status: Literal[
        "fake_rehearsal_only", "real_probe_observed"
    ] = "fake_rehearsal_only",
) -> ProviderCapabilityProbeObservationV1:
    if fixture.target_boundary_identity_sha256 != definition.target.identity_sha256:
        raise ProviderCapabilityProbeContractError("fixture_target_mismatch")
    typed = [
        item if isinstance(item, ProviderContentBlockMetadataV1)
        else ProviderContentBlockMetadataV1.model_validate(item)
        for item in blocks
    ]
    controlled: list[str] = []
    unknown_hashes: list[str] = []
    for block in typed:
        name, unknown_hash = _block_type(block.block_type)
        controlled.append(name)
        if unknown_hash is not None:
            unknown_hashes.append(unknown_hash)
    finish, finish_hash = _finish_reason(finish_reason)
    pre_body = {
        "provider_descriptor_hash": definition.target.provider_descriptor_hash,
        "model_binding_hash": definition.target.model_binding_hash,
        "route_kind": "configured_fallback",
        "protocol": "anthropic",
        "finish_reason": finish,
        "finish_reason_sha256": finish_hash,
        "output_tokens": max(0, int(output_tokens)),
        "requested_max_output_tokens": (
            definition.target.requested_max_output_tokens
        ),
        "effective_provider_max_output_tokens": (
            effective_provider_max_output_tokens
        ),
        "content_block_count": len(typed),
        "content_block_type_sequence": tuple(controlled),
        "unknown_block_type_sha256s": tuple(unknown_hashes),
        "text_block_count": sum(name in TEXT_TYPES for name in controlled),
        "visible_text_characters": sum(
            block.visible_text_characters for block in typed
            if _block_type(block.block_type)[0] in TEXT_TYPES
        ),
        "tool_call_count": sum(name in TOOL_TYPES for name in controlled),
        "tool_arguments_present": any(
            block.tool_arguments_present for block in typed
            if _block_type(block.block_type)[0] in TOOL_TYPES
        ),
        "tool_argument_byte_length": sum(
            block.tool_argument_byte_length for block in typed
            if _block_type(block.block_type)[0] in TOOL_TYPES
        ),
        "partial_tool_argument_count": sum(
            block.partial_tool_arguments for block in typed
            if _block_type(block.block_type)[0] in TOOL_TYPES
        ),
        "reasoning_block_count": sum(
            name in REASONING_TYPES for name in controlled
        ),
        "unknown_block_count": len(unknown_hashes),
        "zero_visible": not any(
            block.visible_text_characters for block in typed
            if _block_type(block.block_type)[0] in TEXT_TYPES
        ),
        "empty_content": not typed,
        "max_tokens": finish in {"max_tokens", "length"},
        "raw_content_omitted": True,
    }
    pre = ProviderCapabilityProbePreNormalizationV1.model_validate(pre_body)
    classification = _classify(
        pre=pre.model_dump(mode="json"),
        adapter_visible_characters=adapter_visible_characters,
        adapter_tool_arguments_present=adapter_tool_arguments_present,
    )
    lineage_body = {
        "definition_sha256": definition.definition_sha256,
        "fixture_sha256": fixture.fixture_sha256,
        "target_boundary_identity_sha256": definition.target.identity_sha256,
        "pre_normalization": pre.model_dump(mode="json"),
        "adapter_visible_text": adapter_visible_characters > 0,
        "adapter_visible_characters": adapter_visible_characters,
        "adapter_tool_arguments_present": adapter_tool_arguments_present,
        "parser_reached": parser_reached,
        "strict_tool_reached": strict_tool_reached,
        "json_conversion_reached": json_conversion_reached,
        "wire_schema_reached": wire_schema_reached,
        "semantic_validation_reached": semantic_validation_reached,
        "output_limit_classifier": classification,
        "raw_content_omitted": True,
    }
    lineage_sha256 = domain_sha256(
        "r1-ptr4-v1-adapter-lineage-v1", lineage_body,
    )
    post = ProviderCapabilityProbePostAdapterV1.model_validate({
        **{key: value for key, value in lineage_body.items()
           if key in {
               item.name for item in fields(ProviderCapabilityProbePostAdapterV1)
           }},
        "lineage_receipt_sha256": lineage_sha256,
    })
    body = {
        "schema": "ProviderCapabilityProbeObservationV1",
        "version": 1,
        "definition_sha256": definition.definition_sha256,
        "fixture_sha256": fixture.fixture_sha256,
        "target_boundary_identity_sha256": definition.target.identity_sha256,
        "pre_normalization": pre.model_dump(mode="json"),
        "post_adapter": post.model_dump(mode="json"),
        "provider_capability_evidence_status": (
            provider_capability_evidence_status
        ),
        "external_action_counters": EXTERNAL_ACTION_COUNTERS,
        "raw_prompt_omitted": True,
        "raw_story_omitted": True,
        "raw_tool_arguments_omitted": True,
        "raw_provider_response_omitted": True,
    }
    return _sealed(
        ProviderCapabilityProbeObservationV1, body,
        hash_field="receipt_sha256",
        domain="r1-ptr4-v1-provider-capability-probe-observation-v1",
    )


def contract_artifacts_v1(repo_root: Path) -> dict[str, Any]:
    """Build the inert definition/fixture/schema bundle without external I/O."""

    definition = build_provider_capability_probe_definition_v1(repo_root)
    fixture = build_provider_capability_probe_fixture_v1(repo_root, definition)
    schema_bundle = {
        "schema": "ProviderCapabilityProbeObserverSchemaBundleV1",
        "version": 1,
        "definition_schema": ProviderCapabilityProbeDefinitionV1.model_json_schema(
            by_alias=True
        ),
        "fixture_schema": ProviderCapabilityProbeFixtureV1.model_json_schema(
            by_alias=True
        ),
        "observation_schema": ProviderCapabilityProbeObservationV1.model_json_schema(
            by_alias=True
        ),
        "external_action_counters": EXTERNAL_ACTION_COUNTERS,
        "raw_content_allowed": False,
    }
    schema_bundle["bundle_sha256"] = domain_sha256(
        "r1-ptr4-v1-provider-capability-probe-schema-bundle-v1",
        schema_bundle,
    )
    return {
        "definition": definition.model_dump(mode="json", by_alias=True),
        "fixture": fixture.model_dump(mode="json", by_alias=True),
        "observer_schema_bundle": schema_bundle,
    }
