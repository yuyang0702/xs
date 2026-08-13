"""Deterministic, non-authoritative canonical shadow contracts.

Phase 1A objects in this module are diagnostic values.  This module exposes no
StoryState, Canon, ProjectMutation, or projection writer and must remain safe to
remove without migrating business data.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CANONICALIZATION_VERSION = "canonical-shadow-json-v1"
UTF8 = "utf-8"
VOLATILE_KEYS = frozenset({
    "created_at", "updated_at", "timestamp", "event_id", "correlation_id",
    "run_id", "trace_id", "random_uuid",
})
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
Sha256 = str
ClaimKind = Literal[
    "character.location", "character.knowledge", "character.relationship",
]
SemanticDomain = Literal["future_normative", "occurred_current"]
Perspective = Literal["objective_world", "character_belief"]
Grounding = Literal["exact", "ambiguous", "ungrounded"]
IdentityStatus = Literal["exact", "ambiguous", "unsupported"]
MutationOperation = Literal["ASSERT", "TRANSITION", "SUPERSEDE", "RETRACT"]
Eligibility = Literal["eligible", "ineligible", "ambiguous", "no_change"]


def _normalized_path(value: str, root: Path | None) -> str:
    normalized = value.replace("\\", "/")
    if root is not None:
        root_text = str(root.resolve()).replace("\\", "/").rstrip("/")
        if normalized.casefold().startswith(root_text.casefold() + "/"):
            return "<ROOT>/" + normalized[len(root_text) + 1 :]
    if _WINDOWS_ABSOLUTE.match(normalized) or normalized.startswith("/"):
        return "<ABS>/" + normalized.rstrip("/").rsplit("/", 1)[-1]
    return normalized


def canonicalize(
    value: Any, *, root: Path | None = None,
    exclude_keys: frozenset[str] = VOLATILE_KEYS,
    field_name: str | None = None,
) -> Any:
    """Return the v1 canonical JSON value or reject unsupported Python state."""

    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str) and field_name and (
            field_name == "path" or field_name.endswith("_path")
        ):
            return _normalized_path(value, root)
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite numbers are not canonical JSON")
        return value
    if isinstance(value, Path):
        return _normalized_path(str(value), root)
    if isinstance(value, dict):
        return {
            str(key): canonicalize(
                item, root=root, exclude_keys=exclude_keys,
                field_name=str(key),
            )
            for key, item in value.items()
            if str(key) not in exclude_keys
        }
    if isinstance(value, (list, tuple)):
        return [
            canonicalize(item, root=root, exclude_keys=exclude_keys)
            for item in value
        ]
    if hasattr(value, "model_dump"):
        return canonicalize(
            value.model_dump(mode="json"), root=root,
            exclude_keys=exclude_keys,
        )
    raise TypeError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_bytes(
    schema: str, value: Any, *, root: Path | None = None,
) -> bytes:
    envelope = {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "schema": schema,
        "value": canonicalize(value, root=root),
    }
    return json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode(UTF8)


def canonical_sha256(
    schema: str, value: Any, *, root: Path | None = None,
) -> str:
    return hashlib.sha256(canonical_bytes(schema, value, root=root)).hexdigest()


def stable_id(prefix: str, schema: str, value: Any) -> str:
    return f"{prefix}-" + canonical_sha256(schema, value)[:32]


class _ShadowModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, str_strip_whitespace=True,
    )


class ProposedClaimV2(_ShadowModel):
    schema_name: Literal["ProposedClaimV2"] = Field(
        default="ProposedClaimV2", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[2] = 2
    claim_id: str = Field(min_length=8)
    claim_kind: ClaimKind
    subject_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object_id: str | None = None
    knowledge_owner_id: str | None = None
    knowledge_topic_hash: Sha256 | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )
    perspective: Perspective
    semantic_domain: SemanticDomain
    story_time: str | None = None
    value_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_kind_shape(self) -> "ProposedClaimV2":
        if self.claim_kind == "character.knowledge" and (
            not self.knowledge_owner_id or not self.knowledge_topic_hash
        ):
            raise ValueError("knowledge claim requires owner and topic")
        if self.claim_kind == "character.relationship" and not self.object_id:
            raise ValueError("relationship claim requires directed object")
        if self.claim_kind != "character.knowledge" and (
            self.knowledge_owner_id is not None
            or self.knowledge_topic_hash is not None
        ):
            raise ValueError("knowledge identity is exclusive to knowledge claims")
        if self.claim_kind != "character.relationship" and self.object_id is not None:
            raise ValueError("relationship object is exclusive to relationship claims")
        unsigned = self.model_dump(
            mode="json", by_alias=True, exclude={"claim_id"},
        )
        if self.claim_id != stable_id("claim", "ProposedClaimV2", unsigned):
            raise ValueError("claim_id is not bound to canonical claim content")
        return self


class ProposedClaimBatchV2(_ShadowModel):
    schema_name: Literal["ProposedClaimBatchV2"] = Field(
        default="ProposedClaimBatchV2", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[2] = 2
    batch_id: str = Field(min_length=8)
    base_authority_revision: int = Field(ge=1)
    base_authority_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    coverage_mode: Literal["complete_source", "window_union"]
    claims: tuple[ProposedClaimV2, ...]

    @model_validator(mode="after")
    def validate_batch_id(self) -> "ProposedClaimBatchV2":
        if len({item.claim_id for item in self.claims}) != len(self.claims):
            raise ValueError("claim batch contains duplicate canonical identities")
        unsigned = self.model_dump(
            mode="json", by_alias=True, exclude={"batch_id"},
        )
        if self.batch_id != stable_id("batch", "ProposedClaimBatchV2", unsigned):
            raise ValueError("batch_id is not bound to canonical batch content")
        return self


class EvidenceByteSpanV2(_ShadowModel):
    schema_name: Literal["EvidenceByteSpanV2"] = Field(
        default="EvidenceByteSpanV2", alias="schema",
        serialization_alias="schema",
    )
    byte_start: int = Field(ge=0)
    byte_end: int = Field(gt=0)
    byte_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def span_is_nonempty(self) -> "EvidenceByteSpanV2":
        if self.byte_end <= self.byte_start:
            raise ValueError("evidence byte span must be non-empty")
        return self


class EvidenceEnvelopeV2(_ShadowModel):
    schema_name: Literal["EvidenceEnvelopeV2"] = Field(
        default="EvidenceEnvelopeV2", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[2] = 2
    evidence_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    claim_id: str = Field(min_length=8)
    source_artifact_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    base_authority_revision: int = Field(ge=1)
    base_authority_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    extractor_contract_version: Literal["final-bytes-extractor-v1"] = (
        "final-bytes-extractor-v1"
    )
    grounding: Grounding
    spans: tuple[EvidenceByteSpanV2, ...]
    covered_ranges: tuple[tuple[int, int], ...]
    gaps: tuple[str, ...] = ()
    candidate_slot_id: str | None = None
    ambiguous: bool

    @model_validator(mode="after")
    def validate_evidence(self) -> "EvidenceEnvelopeV2":
        if self.grounding == "exact" and (len(self.spans) != 1 or self.ambiguous):
            raise ValueError("exact grounding requires one unambiguous byte span")
        if self.grounding != "exact" and not (self.ambiguous or self.gaps):
            raise ValueError("non-exact grounding requires explicit uncertainty")
        unsigned = self.model_dump(
            mode="json", by_alias=True, exclude={"evidence_hash"},
        )
        if self.evidence_hash != canonical_sha256("EvidenceEnvelopeV2", unsigned):
            raise ValueError("evidence hash is stale")
        return self


class ShadowSlotIdentityV1(_ShadowModel):
    schema_name: Literal["ShadowSlotIdentityV1"] = Field(
        default="ShadowSlotIdentityV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    slot_id: str | None
    competition_key: str | None
    status: IdentityStatus
    subject_id: str | None
    predicate: str | None
    object_id: str | None = None
    knowledge_owner_id: str | None = None
    knowledge_topic_hash: Sha256 | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )
    perspective: Perspective | None
    semantic_domain: SemanticDomain | None
    story_time: str | None
    reasons: tuple[str, ...] = ()


class CanonicalMutationV1(_ShadowModel):
    schema_name: Literal["CanonicalMutationV1"] = Field(
        default="CanonicalMutationV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    mutation_id: str = Field(min_length=8)
    operation: MutationOperation
    claim_id: str = Field(min_length=8)
    evidence_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    slot_id: str = Field(min_length=8)
    competition_key: str = Field(min_length=8)
    base_authority_revision: int = Field(ge=1)
    base_authority_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    authority_slice_hash: Sha256 | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )
    expected_current_hash: Sha256 | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )
    proposed_value_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    eligibility: Eligibility
    failure_codes: tuple[str, ...] = ()
    shadow_only: Literal[True] = True

    @model_validator(mode="after")
    def validate_mutation_id(self) -> "CanonicalMutationV1":
        if self.eligibility == "eligible" and self.failure_codes:
            raise ValueError("eligible mutation cannot carry failures")
        unsigned = self.model_dump(
            mode="json", by_alias=True, exclude={"mutation_id"},
        )
        if self.mutation_id != stable_id("mutation", "CanonicalMutationV1", unsigned):
            raise ValueError("mutation_id is not bound to canonical mutation content")
        return self


class ShadowCanonicalCommitReceiptV1(_ShadowModel):
    schema_name: Literal["ShadowCanonicalCommitReceiptV1"] = Field(
        default="ShadowCanonicalCommitReceiptV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    receipt_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    mutation_id: str = Field(min_length=8)
    base_authority_revision: int = Field(ge=1)
    base_authority_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    shadow_only: Literal[True] = True
    commit_performed: Literal[False] = False
    outcome: Literal["shadow_not_committed"] = "shadow_not_committed"
    target_revision: None = None
    target_authority_hash: None = None
    projection_effects: tuple[()] = ()
    legacy_comparison: Literal[
        "equivalent", "legacy_only", "shadow_only", "value_mismatch",
        "qualification_mismatch", "identity_false_split_candidate",
        "identity_false_merge_candidate", "uncomparable",
    ]

    @model_validator(mode="after")
    def validate_receipt_hash(self) -> "ShadowCanonicalCommitReceiptV1":
        unsigned = self.model_dump(
            mode="json", by_alias=True, exclude={"receipt_hash"},
        )
        if self.receipt_hash != canonical_sha256(
            "ShadowCanonicalCommitReceiptV1", unsigned,
        ):
            raise ValueError("shadow receipt hash is stale")
        return self


class ProjectionProvenanceV1(_ShadowModel):
    schema_name: Literal["ProjectionProvenanceV1"] = Field(
        default="ProjectionProvenanceV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    source_authority_revision: int = Field(ge=1)
    source_authority_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_id: str = Field(min_length=8)
    source_artifact_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    projection_hash: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    writer: str = Field(min_length=1)

