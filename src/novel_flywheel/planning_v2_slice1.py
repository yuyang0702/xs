"""Offline, non-authoritative Planning V2 Slice 1 shadow contracts.

This module deliberately exposes no workflow hook or project-state writer.
Phase A accepts deterministic fixture/replay candidates only; it cannot call a
provider or promote an artifact into Planning, Draft, READY, StoryState, or
Canon authority.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from novel_flywheel.canonical_shadow import canonical_bytes, canonical_sha256, stable_id


SHA256_PATTERN = r"^[0-9a-f]{64}$"
ARTIFACT_SCHEMA = "EventRealizationArtifactV1"
ARTIFACT_VERSION = 1
SLICE1_STAGE = "event_realization_unit_shadow_v1"
SLICE1_CONTRACT_IDENTITY = "planning_event_realization_shadow_v1@1"

ValidationStatus = Literal["PENDING", "PASS", "REJECTED"]
FreezeState = Literal["OPEN", "FROZEN"]
ProducerKind = Literal["offline_fixture", "historical_projection", "future_model_shadow"]


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


def _authority_ordinals(authority: EventRealizationInputAuthorityV1) -> tuple[int, int]:
    event_ordinal = authority.formal_event_ids.index(authority.formal_event_id)
    segment_ordinal = next(
        index for index, segment in enumerate(authority.segment_event_ids)
        if authority.formal_event_id in segment
    )
    return event_ordinal, segment_ordinal


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
    identity_input = {
        "schema": ARTIFACT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "parent_authority_sha256": authority.parent_authority_sha256,
        "formal_event_id": authority.formal_event_id,
        "formal_event_contract_sha256": authority.formal_event_contract_sha256,
    }
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
        "artifact_id": stable_id("slice1-artifact", ARTIFACT_SCHEMA, identity_input),
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
                "artifact_id": stable_id(
                    "slice1-artifact", ARTIFACT_SCHEMA, identity_input,
                ),
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
