"""Offline, non-authoritative Planning V2 Slice 1 shadow contracts.

This module deliberately exposes no workflow hook or project-state writer.
Phase A accepts deterministic fixture/replay candidates only; it cannot call a
provider or promote an artifact into Planning, Draft, READY, StoryState, or
Canon authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator,
)

from novel_flywheel.canonical_shadow import canonical_bytes, canonical_sha256, stable_id
from novel_flywheel.generated_artifacts import (
    ArtifactConversionAudit,
    ArtifactConversionError,
    GeneratedArtifactGateway,
)


SHA256_PATTERN = r"^[0-9a-f]{64}$"
ARTIFACT_SCHEMA = "EventRealizationArtifactV1"
ARTIFACT_VERSION = 1
SLICE1_STAGE = "event_realization_unit_shadow_v1"
SLICE1_CONTRACT_IDENTITY = "planning_event_realization_shadow_v1@1"

ValidationStatus = Literal["PENDING", "PASS", "REJECTED"]
FreezeState = Literal["OPEN", "FROZEN"]
ProducerKind = Literal["offline_fixture", "historical_projection", "future_model_shadow"]
RepairEligibility = Literal[
    "local_deterministic", "bounded_field_patch", "dependency_closure_patch",
    "slice1_regeneration", "not_repairable",
]
DiagnosticSeverity = Literal["error", "deferred"]
ExactnessStatus = Literal["exact", "unknown"]

SLICE1_VALIDATOR_POLICY_SHA256 = canonical_sha256(
    "Slice1ValidatorPolicyV1",
    (
        "candidate_closed_title_narrative",
        "authority_referential_exact",
        "authority_hash_binding_exact",
        "runtime_injected_event_compiler",
        "slice1_exact_coverage",
        "global_closure_deferred",
    ),
)


EVENT_REALIZATION_ARTIFACT_FIELD_PATHS: tuple[str, ...] = (
    "/schema", "/version", "/artifact_id", "/artifact_revision", "/stage",
    "/scope_id", "/shadow_only", "/parent_authority_sha256",
    "/formal_event_id", "/formal_event_ordinal", "/segment_ordinal",
    "/formal_event_contract_sha256", "/predecessor_boundary_sha256",
    "/dependency_artifact_ids", "/dependency_set_sha256", "/title",
    "/narrative", "/payload_sha256", "/provenance/producer_kind",
    "/provenance/contract_identity", "/provenance/source_candidate_sha256",
    "/validation_status", "/validation_receipt_sha256", "/freeze_state",
    "/commit_performed", "/promotion_eligible",
)


class Slice1ContractError(ValueError):
    """Typed base error for the isolated Slice 1 contract."""

    code: ClassVar[str] = "SLICE1_CONTRACT_ERROR"


class Slice1StaleParentError(Slice1ContractError):
    code = "SLICE1_STALE_PARENT"


class Slice1CandidateRejected(Slice1ContractError):
    code = "SLICE1_CANDIDATE_REJECTED"

    def __init__(self, findings: Sequence["LosslessSliceDiagnosticV1"]) -> None:
        super().__init__("Slice 1 candidate failed its closed shadow contract")
        self.findings = tuple(findings)


class _Slice1Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, populate_by_name=True,
    )


def _require_exact_text(value: str, *, label: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be non-empty and presentation-exact")
    return value


def _meaningful_character_count(value: str) -> int:
    return sum(character.isalnum() for character in value)


class EventRealizationCandidateV1(_Slice1Model):
    """The complete Phase A candidate surface: two creative fields only."""

    title: str = Field(min_length=1, max_length=120)
    narrative: str = Field(min_length=1)

    @field_validator("title", "narrative")
    @classmethod
    def validate_exact_text(cls, value: str, info: Any) -> str:
        return _require_exact_text(value, label=info.field_name)

    @field_validator("narrative")
    @classmethod
    def validate_meaningful_narrative(cls, value: str) -> str:
        if _meaningful_character_count(value) < 12:
            raise ValueError("narrative must contain at least 12 meaningful characters")
        return value


class EventRealizationInputAuthorityV1(_Slice1Model):
    """Read-only authority projection used to derive one shadow artifact."""

    parent_authority_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_event_id: str = Field(min_length=1, max_length=160)
    formal_event_contract_sha256: str = Field(pattern=SHA256_PATTERN)
    predecessor_boundary_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_event_ids: tuple[str, ...] = Field(min_length=1)
    segment_event_ids: tuple[tuple[str, ...], ...] = Field(min_length=1)
    dependency_artifact_ids: tuple[str, ...] = ()
    context_projection_sha256: str = Field(pattern=SHA256_PATTERN)
    required_obligation_ids: tuple[str, ...] = ()

    @field_validator("formal_event_id")
    @classmethod
    def validate_formal_event_id(cls, value: str) -> str:
        return _require_exact_text(value, label="formal_event_id")

    @field_validator("formal_event_ids", "dependency_artifact_ids", "required_obligation_ids")
    @classmethod
    def validate_exact_identifier_sequence(
        cls, values: tuple[str, ...], info: Any,
    ) -> tuple[str, ...]:
        for value in values:
            _require_exact_text(value, label=info.field_name)
        return values

    @model_validator(mode="after")
    def validate_exact_authority_membership(self) -> "EventRealizationInputAuthorityV1":
        if self.formal_event_ids.count(self.formal_event_id) != 1:
            raise ValueError("formal_event_id must occur exactly once in authority order")
        segment_hits = sum(
            segment.count(self.formal_event_id) for segment in self.segment_event_ids
        )
        if segment_hits != 1:
            raise ValueError("formal_event_id must occur in exactly one authority segment")
        flattened = tuple(item for segment in self.segment_event_ids for item in segment)
        if len(flattened) != len(set(flattened)):
            raise ValueError("authority segment ownership must not contain duplicates")
        if set(flattened) != set(self.formal_event_ids):
            raise ValueError("segment ownership must cover the formal event order exactly")
        return self


class EventRealizationProvenanceV1(_Slice1Model):
    producer_kind: ProducerKind
    contract_identity: Literal["planning_event_realization_shadow_v1@1"] = (
        SLICE1_CONTRACT_IDENTITY
    )
    source_candidate_sha256: str = Field(pattern=SHA256_PATTERN)


class EventRealizationArtifactV1(_Slice1Model):
    """Frozen-value shadow artifact; lifecycle changes create a new value."""

    schema_name: Literal["EventRealizationArtifactV1"] = Field(
        default=ARTIFACT_SCHEMA, alias="schema", serialization_alias="schema",
    )
    version: Literal[1] = ARTIFACT_VERSION
    artifact_id: str = Field(min_length=16, max_length=96)
    artifact_revision: int = Field(default=1, ge=1)
    stage: Literal["event_realization_unit_shadow_v1"] = SLICE1_STAGE
    scope_id: str = Field(min_length=16, max_length=96)
    shadow_only: Literal[True] = True
    parent_authority_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_event_id: str = Field(min_length=1, max_length=160)
    formal_event_ordinal: int = Field(ge=0)
    segment_ordinal: int = Field(ge=0)
    formal_event_contract_sha256: str = Field(pattern=SHA256_PATTERN)
    predecessor_boundary_sha256: str = Field(pattern=SHA256_PATTERN)
    dependency_artifact_ids: tuple[str, ...] = ()
    dependency_set_sha256: str = Field(pattern=SHA256_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    narrative: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=SHA256_PATTERN)
    provenance: EventRealizationProvenanceV1
    validation_status: ValidationStatus = "PENDING"
    validation_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    freeze_state: FreezeState = "OPEN"
    commit_performed: Literal[False] = False
    promotion_eligible: Literal[False] = False


class LosslessSliceDiagnosticV1(_Slice1Model):
    schema_name: Literal["LosslessSliceDiagnosticV1"] = Field(
        default="LosslessSliceDiagnosticV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    finding_id: str = Field(min_length=16, max_length=96)
    rule_code: str = Field(min_length=1, max_length=160)
    field_path_json_pointer: str = Field(min_length=1, max_length=256)
    invariant_id: str = Field(min_length=1, max_length=160)
    artifact_id: str = Field(min_length=16, max_length=96)
    parent_authority_sha256: str = Field(pattern=SHA256_PATTERN)
    artifact_revision: int = Field(ge=1)
    dependency_hint_ids: tuple[str, ...] = ()
    validator_id: str = Field(min_length=1, max_length=160)
    validator_version: Literal[1] = 1
    validator_policy_sha256: str = Field(pattern=SHA256_PATTERN)
    value_type: Literal[
        "null", "boolean", "integer", "number", "string", "object",
        "array", "other",
    ]
    structural_shape: str = Field(min_length=1, max_length=160)
    observed_value_sha256: str = Field(pattern=SHA256_PATTERN)
    repair_eligibility: RepairEligibility
    severity: DiagnosticSeverity
    exactness_status: ExactnessStatus
    raw_value_included: Literal[False] = False
    raw_story_included: Literal[False] = False


class Slice1ValidationReceiptV1(_Slice1Model):
    schema_name: Literal["Slice1ValidationReceiptV1"] = Field(
        default="Slice1ValidationReceiptV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    artifact_id: str = Field(min_length=16, max_length=96)
    artifact_revision: int = Field(ge=1)
    parent_authority_sha256: str = Field(pattern=SHA256_PATTERN)
    status: Literal["PASS", "REJECTED"]
    findings: tuple[LosslessSliceDiagnosticV1, ...] = ()
    deferred_global_invariant_ids: tuple[str, ...] = ()
    validator_policy_sha256: str = Field(pattern=SHA256_PATTERN)
    raw_value_included: Literal[False] = False
    raw_story_included: Literal[False] = False


def _authority_ordinals(authority: EventRealizationInputAuthorityV1) -> tuple[int, int]:
    event_ordinal = authority.formal_event_ids.index(authority.formal_event_id)
    segment_ordinal = next(
        index for index, segment in enumerate(authority.segment_event_ids)
        if authority.formal_event_id in segment
    )
    return event_ordinal, segment_ordinal


def _artifact_identity_input(
    authority: EventRealizationInputAuthorityV1,
) -> dict[str, Any]:
    return {
        "schema": ARTIFACT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "parent_authority_sha256": authority.parent_authority_sha256,
        "formal_event_id": authority.formal_event_id,
        "formal_event_contract_sha256": authority.formal_event_contract_sha256,
    }


def _planned_artifact_id(authority: EventRealizationInputAuthorityV1) -> str:
    return stable_id(
        "slice1-artifact", ARTIFACT_SCHEMA, _artifact_identity_input(authority),
    )


def _artifact_payload_projection(values: dict[str, Any]) -> dict[str, Any]:
    """Return the stable business payload, excluding validation lifecycle state."""

    excluded = {
        "payload_sha256", "validation_status", "validation_receipt_sha256",
        "freeze_state",
    }
    return {key: value for key, value in values.items() if key not in excluded}


def build_event_realization_artifact(
    authority: EventRealizationInputAuthorityV1,
    candidate: EventRealizationCandidateV1,
    *,
    artifact_revision: int = 1,
    producer_kind: ProducerKind = "offline_fixture",
) -> EventRealizationArtifactV1:
    """Derive all Runtime-owned fields without semantic inference or clocks."""

    event_ordinal, segment_ordinal = _authority_ordinals(authority)
    dependencies = tuple(sorted(set(authority.dependency_artifact_ids)))
    identity_input = _artifact_identity_input(authority)
    scope_input = {
        "parent_authority_sha256": authority.parent_authority_sha256,
        "formal_event_id": authority.formal_event_id,
        "segment_ordinal": segment_ordinal,
    }
    candidate_value = candidate.model_dump(mode="json")
    provenance = EventRealizationProvenanceV1(
        producer_kind=producer_kind,
        source_candidate_sha256=canonical_sha256(
            "EventRealizationCandidateV1", candidate_value,
        ),
    )
    values: dict[str, Any] = {
        "schema": ARTIFACT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "artifact_id": _planned_artifact_id(authority),
        "artifact_revision": artifact_revision,
        "stage": SLICE1_STAGE,
        "scope_id": stable_id("slice1-scope", "EventRealizationScopeV1", scope_input),
        "shadow_only": True,
        "parent_authority_sha256": authority.parent_authority_sha256,
        "formal_event_id": authority.formal_event_id,
        "formal_event_ordinal": event_ordinal,
        "segment_ordinal": segment_ordinal,
        "formal_event_contract_sha256": authority.formal_event_contract_sha256,
        "predecessor_boundary_sha256": authority.predecessor_boundary_sha256,
        "dependency_artifact_ids": dependencies,
        "dependency_set_sha256": canonical_sha256(
            "EventRealizationDependencySetV1", dependencies,
        ),
        "title": candidate.title,
        "narrative": candidate.narrative,
        "provenance": provenance.model_dump(mode="json"),
        "validation_status": "PENDING",
        "validation_receipt_sha256": canonical_sha256(
            "Slice1ValidationPendingV1", {
                "artifact_id": _planned_artifact_id(authority),
                "artifact_revision": artifact_revision,
            },
        ),
        "freeze_state": "OPEN",
        "commit_performed": False,
        "promotion_eligible": False,
    }
    values["payload_sha256"] = canonical_sha256(
        "EventRealizationArtifactPayloadV1", _artifact_payload_projection(values),
    )
    return EventRealizationArtifactV1.model_validate(values)


def artifact_canonical_bytes(artifact: EventRealizationArtifactV1) -> bytes:
    return canonical_bytes(
        ARTIFACT_SCHEMA, artifact.model_dump(mode="json", by_alias=True),
    )


def artifact_sha256(artifact: EventRealizationArtifactV1) -> str:
    return canonical_sha256(
        ARTIFACT_SCHEMA, artifact.model_dump(mode="json", by_alias=True),
    )


def assert_current_parent(
    artifact: EventRealizationArtifactV1, current_parent_authority_sha256: str,
) -> None:
    if artifact.parent_authority_sha256 != current_parent_authority_sha256:
        raise Slice1StaleParentError(
            "Slice 1 artifact is bound to a stale Planning authority"
        )


def _value_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "other"


def _structural_shape(value: object) -> str:
    kind = _value_type(value)
    if isinstance(value, str):
        return f"string(chars={len(value)})"
    if isinstance(value, Mapping):
        return f"object(keys={len(value)})"
    if isinstance(value, (list, tuple)):
        return f"array(items={len(value)})"
    return kind


def _json_pointer(loc: Sequence[object], *, prefix: str = "") -> str:
    if not loc:
        return prefix or "$"
    encoded = [str(item).replace("~", "~0").replace("/", "~1") for item in loc]
    path = "/" + "/".join(encoded)
    return (prefix.rstrip("/") + path) if prefix else path


def _diagnostic(
    *,
    authority: EventRealizationInputAuthorityV1,
    rule_code: str,
    field_path: str,
    invariant_id: str,
    observed_value: object,
    validator_id: str,
    repair_eligibility: RepairEligibility,
    artifact_revision: int = 1,
    dependency_hint_ids: Sequence[str] = (),
    severity: DiagnosticSeverity = "error",
    exactness_status: ExactnessStatus = "exact",
) -> LosslessSliceDiagnosticV1:
    artifact_id = _planned_artifact_id(authority)
    identity = {
        "rule_code": rule_code,
        "field_path": field_path,
        "invariant_id": invariant_id,
        "artifact_id": artifact_id,
        "artifact_revision": artifact_revision,
        "parent_authority_sha256": authority.parent_authority_sha256,
        "dependency_hint_ids": tuple(sorted(set(dependency_hint_ids))),
        "validator_id": validator_id,
    }
    return LosslessSliceDiagnosticV1(
        finding_id=stable_id("slice1-finding", "LosslessSliceDiagnosticV1", identity),
        rule_code=rule_code,
        field_path_json_pointer=field_path,
        invariant_id=invariant_id,
        artifact_id=artifact_id,
        parent_authority_sha256=authority.parent_authority_sha256,
        artifact_revision=artifact_revision,
        dependency_hint_ids=tuple(sorted(set(dependency_hint_ids))),
        validator_id=validator_id,
        validator_policy_sha256=SLICE1_VALIDATOR_POLICY_SHA256,
        value_type=_value_type(observed_value),  # type: ignore[arg-type]
        structural_shape=_structural_shape(observed_value),
        observed_value_sha256=canonical_sha256(
            "Slice1ObservedValueV1", observed_value,
        ),
        repair_eligibility=repair_eligibility,
        severity=severity,
        exactness_status=exactness_status,
    )


def _pydantic_rule(error_type: str) -> tuple[str, str, RepairEligibility]:
    if error_type == "extra_forbidden":
        return (
            "SLICE1_FIELD_OWNERSHIP_VIOLATION",
            "candidate_contains_only_title_narrative",
            "not_repairable",
        )
    if error_type == "missing":
        return (
            "SLICE1_REQUIRED_FIELD_MISSING",
            "candidate_requires_title_and_narrative",
            "bounded_field_patch",
        )
    return (
        "SLICE1_CANDIDATE_FIELD_INVALID",
        "candidate_field_shape_valid",
        "bounded_field_patch",
    )


def validate_candidate_payload(
    value: object,
    *,
    authority: EventRealizationInputAuthorityV1,
    path_prefix: str = "",
) -> EventRealizationCandidateV1:
    """Validate a candidate and retain every Pydantic path as typed evidence."""

    try:
        return EventRealizationCandidateV1.model_validate(value)
    except ValidationError as exc:
        findings: list[LosslessSliceDiagnosticV1] = []
        for error in exc.errors(include_url=False, include_context=False):
            loc = tuple(error.get("loc") or ())
            rule, invariant, repair = _pydantic_rule(str(error.get("type") or ""))
            observed: object = None
            if isinstance(value, Mapping) and loc:
                observed = value.get(str(loc[0]))
            findings.append(_diagnostic(
                authority=authority,
                rule_code=rule,
                field_path=_json_pointer(loc, prefix=path_prefix),
                invariant_id=invariant,
                observed_value=observed,
                validator_id="planning_v2_slice1.validate_candidate_structure",
                repair_eligibility=repair,
            ))
        raise Slice1CandidateRejected(findings) from exc


def normalize_slice1_candidate(value: object) -> dict[str, Any] | None:
    """GeneratedArtifact semantic normalizer for the closed shadow candidate."""

    try:
        candidate = EventRealizationCandidateV1.model_validate(value)
    except (TypeError, ValueError, ValidationError):
        return None
    return candidate.model_dump(mode="json")


def _conversion_failure_diagnostic(
    *,
    authority: EventRealizationInputAuthorityV1,
    raw: str,
    audit: ArtifactConversionAudit,
) -> LosslessSliceDiagnosticV1:
    mapping: dict[str, tuple[str, str, RepairEligibility, ExactnessStatus]] = {
        "output_truncated": (
            "SLICE1_OUTPUT_TRUNCATED", "candidate_transport_complete",
            "not_repairable", "exact",
        ),
        "json_object_unavailable": (
            "SLICE1_JSON_OBJECT_UNAVAILABLE", "one_json_object_available",
            "local_deterministic", "exact",
        ),
        "ambiguous_semantic_candidates": (
            "SLICE1_MULTIPLE_CANDIDATES", "exactly_one_candidate",
            "not_repairable", "exact",
        ),
        "contract_adaptation_failed": (
            "SLICE1_FIELD_OWNERSHIP_VIOLATION", "candidate_ownership_closed",
            "not_repairable", "exact",
        ),
    }
    rule, invariant, repair, exactness = mapping.get(
        audit.failure_code or "",
        (
            "SLICE1_CANDIDATE_SHAPE_REJECTED", "candidate_shape_complete",
            "bounded_field_patch", "unknown",
        ),
    )
    return _diagnostic(
        authority=authority,
        rule_code=rule,
        field_path="$",
        invariant_id=invariant,
        observed_value={
            "raw_sha256": audit.raw_sha256,
            "raw_character_count": len(raw),
            "candidate_count": audit.candidate_count,
            "failure_code": audit.failure_code,
        },
        validator_id="planning_v2_slice1.convert_candidate",
        repair_eligibility=repair,
        exactness_status=exactness,
    )


def convert_event_realization_candidate(
    raw: str, *, authority: EventRealizationInputAuthorityV1,
) -> tuple[EventRealizationCandidateV1, ArtifactConversionAudit]:
    """Convert one offline response through the registered contract boundary."""

    try:
        converted = GeneratedArtifactGateway().convert_object(
            raw,
            contract_name="planning_event_realization_shadow_v1",
            semantic_normalizer=normalize_slice1_candidate,
        )
    except ArtifactConversionError as exc:
        raise Slice1CandidateRejected((
            _conversion_failure_diagnostic(
                authority=authority, raw=raw, audit=exc.audit,
            ),
        )) from exc
    candidate = EventRealizationCandidateV1.model_validate(converted.payload)
    return candidate, converted.audit


def _artifact_finding(
    *,
    artifact: EventRealizationArtifactV1,
    authority: EventRealizationInputAuthorityV1,
    rule_code: str,
    field_path: str,
    invariant_id: str,
    observed_value: object,
    validator_id: str,
    repair_eligibility: RepairEligibility,
    dependency_hint_ids: Sequence[str] = (),
) -> LosslessSliceDiagnosticV1:
    return _diagnostic(
        authority=authority,
        rule_code=rule_code,
        field_path=field_path,
        invariant_id=invariant_id,
        observed_value=observed_value,
        validator_id=validator_id,
        repair_eligibility=repair_eligibility,
        artifact_revision=artifact.artifact_revision,
        dependency_hint_ids=dependency_hint_ids,
    )


def validate_event_realization_artifact(
    artifact: EventRealizationArtifactV1,
    authority: EventRealizationInputAuthorityV1,
) -> Slice1ValidationReceiptV1:
    """Run Slice1 A-D validators; global V2 closure remains explicitly deferred."""

    findings: list[LosslessSliceDiagnosticV1] = []
    expected = build_event_realization_artifact(
        authority,
        EventRealizationCandidateV1(
            title=artifact.title, narrative=artifact.narrative,
        ) if _meaningful_character_count(artifact.narrative) >= 12 else _safe_candidate_for_rebuild(artifact),
        artifact_revision=artifact.artifact_revision,
        producer_kind=artifact.provenance.producer_kind,
    )
    referential_checks = (
        ("formal_event_ordinal", "SLICE1_EVENT_ORDINAL_MISMATCH", "event_ordinal_exact"),
        ("segment_ordinal", "SLICE1_SEGMENT_ORDINAL_MISMATCH", "segment_ordinal_exact"),
        ("scope_id", "SLICE1_SCOPE_ID_MISMATCH", "scope_identity_exact"),
    )
    for field_name, rule, invariant in referential_checks:
        actual = getattr(artifact, field_name)
        if actual != getattr(expected, field_name):
            findings.append(_artifact_finding(
                artifact=artifact, authority=authority, rule_code=rule,
                field_path=f"/{field_name}", invariant_id=invariant,
                observed_value=actual,
                validator_id="planning_v2_slice1.validate_references",
                repair_eligibility="slice1_regeneration",
            ))
    authority_checks = (
        "parent_authority_sha256", "formal_event_id",
        "formal_event_contract_sha256", "predecessor_boundary_sha256",
        "dependency_artifact_ids", "dependency_set_sha256",
    )
    for field_name in authority_checks:
        actual = getattr(artifact, field_name)
        if actual != getattr(expected, field_name):
            findings.append(_artifact_finding(
                artifact=artifact, authority=authority,
                rule_code="SLICE1_AUTHORITY_BINDING_MISMATCH",
                field_path=f"/{field_name}", invariant_id="authority_binding_exact",
                observed_value=actual,
                validator_id="planning_v2_slice1.validate_authority_binding",
                repair_eligibility="not_repairable",
                dependency_hint_ids=authority.dependency_artifact_ids,
            ))
    if _meaningful_character_count(artifact.narrative) < 12:
        findings.append(_artifact_finding(
            artifact=artifact, authority=authority,
            rule_code="SLICE1_NARRATIVE_INCOMPLETE", field_path="/narrative",
            invariant_id="event_realization_meaningful",
            observed_value=artifact.narrative,
            validator_id="planning_v2_slice1.validate_local_semantics",
            repair_eligibility="bounded_field_patch",
        ))
    else:
        try:
            from novel_flywheel.planning_compiler import compile_planning_event_artifact

            compile_planning_event_artifact(
                {"events": [{
                    "event_id": authority.formal_event_id,
                    "narrative": artifact.narrative,
                }]},
                expected_event_ids=(authority.formal_event_id,),
            )
        except (TypeError, ValueError):
            findings.append(_artifact_finding(
                artifact=artifact, authority=authority,
                rule_code="SLICE1_EVENT_REALIZATION_INVALID",
                field_path="/narrative",
                invariant_id="runtime_event_compiler_accepts_realization",
                observed_value=artifact.narrative,
                validator_id="planning_v2_slice1.validate_local_semantics",
                repair_eligibility="bounded_field_patch",
            ))
    return Slice1ValidationReceiptV1(
        artifact_id=artifact.artifact_id,
        artifact_revision=artifact.artifact_revision,
        parent_authority_sha256=artifact.parent_authority_sha256,
        status="REJECTED" if findings else "PASS",
        findings=tuple(findings),
        deferred_global_invariant_ids=(
            "actor_world_global_closure", "whole_plan_time_causal_closure",
            "setup_payoff_ending_closure", "draft_executability",
        ),
        validator_policy_sha256=SLICE1_VALIDATOR_POLICY_SHA256,
    )


def _safe_candidate_for_rebuild(
    artifact: EventRealizationArtifactV1,
) -> EventRealizationCandidateV1:
    """Build expected metadata without treating invalid prose as accepted content."""

    return EventRealizationCandidateV1(
        title=artifact.title,
        narrative="invalid candidate placeholder used only for metadata comparison",
    )


def validation_receipt_sha256(receipt: Slice1ValidationReceiptV1) -> str:
    return canonical_sha256(
        "Slice1ValidationReceiptV1",
        receipt.model_dump(mode="json", by_alias=True),
    )


def project_ptr3_finding(finding: LosslessSliceDiagnosticV1) -> Any:
    """Project into PTR3's existing diagnostic vocabulary without changing it."""

    from novel_flywheel.planning_repair_diagnostics import DiagnosticDomainFindingV1

    return DiagnosticDomainFindingV1(
        rule_code=finding.rule_code,
        field_path=finding.field_path_json_pointer,
        invariant_id=finding.invariant_id,
        value_type=finding.value_type,
        structural_shape=finding.structural_shape,
    )
