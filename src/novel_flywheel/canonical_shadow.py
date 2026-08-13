"""Deterministic, non-authoritative canonical shadow contracts.

Phase 1A objects in this module are diagnostic values.  This module exposes no
StoryState, Canon, ProjectMutation, or projection writer and must remain safe to
remove without migrating business data.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

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


@dataclass(frozen=True)
class ShadowClaimInput:
    claim: ProposedClaimV2
    evidence_text: str | None
    operation: MutationOperation
    requested_expected_current_hash: str | None
    raw_key_hash: str


@dataclass(frozen=True)
class ShadowObservationReport:
    enabled: bool
    workflow: str
    claim_count: int
    eligible_count: int
    no_change_count: int
    ineligible_count: int
    ambiguous_count: int
    exact_evidence_count: int
    evidence_gap_count: int
    identity_ambiguous_count: int
    comparison_counts: dict[str, int]
    receipt_hashes: tuple[str, ...]


CONTROLLED_RELATIONSHIP_PREDICATES = frozenset({
    "relationship", "trust", "hostility", "alliance", "romance", "kinship",
})


def shadow_enabled() -> bool:
    return os.environ.get("NOVEL_CANONICAL_SHADOW_V1", "0") == "1"


def story_state_authority_hash(state_data: Mapping[str, Any]) -> str:
    """Match the ProjectMutation StoryState content-addressing contract."""

    return hashlib.sha256(json.dumps(
        dict(state_data), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode(UTF8)).hexdigest()


def normalize_entity_alias(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(normalized.split()).casefold()


def entity_id(canonical_name: str) -> str:
    normalized = normalize_entity_alias(canonical_name)
    if not normalized:
        raise ValueError("canonical entity name is empty")
    return stable_id("entity", "CanonicalEntityV1", {"name": normalized})


@dataclass(frozen=True)
class EntityAliasIndex:
    aliases: dict[str, tuple[str, ...]]
    canonical_names: dict[str, str]

    def resolve(self, value: str) -> tuple[str | None, IdentityStatus]:
        candidates = self.aliases.get(normalize_entity_alias(value), ())
        if len(candidates) == 1:
            return candidates[0], "exact"
        if len(candidates) > 1:
            return None, "ambiguous"
        return None, "unsupported"


def _profile_identity(path: Path) -> tuple[str, tuple[str, ...]] | None:
    try:
        text = path.read_text(encoding=UTF8)
    except OSError:
        return None
    frontmatter = (
        text.split("---", 2)[1]
        if text.startswith("---") and text.count("---") >= 2 else ""
    )
    name_match = re.search(r"(?m)^name\s*[:：]\s*['\"]?([^\r\n'\"]+)", frontmatter)
    if not name_match:
        return None
    name = name_match.group(1).strip()
    aliases: list[str] = []
    inline = re.search(r"(?m)^aliases\s*[:：]\s*\[(.*?)\]\s*$", frontmatter)
    if inline:
        aliases.extend(
            item.strip().strip("'\"") for item in inline.group(1).split(",")
            if item.strip().strip("'\"")
        )
    block = re.search(
        r"(?ms)^aliases\s*[:：]\s*\n(?P<body>(?:[ \t]+-[^\r\n]*(?:\r?\n|$))*)",
        frontmatter,
    )
    if block:
        aliases.extend(
            item.strip().strip("'\"")
            for item in re.findall(r"(?m)^[ \t]+-[ \t]*(.+)$", block.group("body"))
            if item.strip().strip("'\"")
        )
    return name, tuple(aliases)


def build_entity_alias_index(
    project_root: Path, story_state_data: Mapping[str, Any],
) -> EntityAliasIndex:
    """Build an explicit-only alias index; collisions remain ambiguous."""

    declarations: dict[str, set[str]] = {}
    canonical_names: dict[str, str] = {}

    def add(name: str, aliases: tuple[str, ...] = ()) -> None:
        normalized_name = normalize_entity_alias(name)
        if not normalized_name:
            return
        identity = entity_id(name)
        canonical_names.setdefault(identity, name.strip())
        for alias in (name, *aliases):
            normalized = normalize_entity_alias(alias)
            if normalized:
                declarations.setdefault(normalized, set()).add(identity)

    characters = project_root / "characters"
    if characters.is_dir():
        for path in sorted(characters.glob("*.md"), key=lambda item: item.name.casefold()):
            if path.name == "_index.md":
                continue
            parsed = _profile_identity(path)
            if parsed:
                add(*parsed)
    states = story_state_data.get("character_states")
    if isinstance(states, Mapping):
        for name in sorted((str(item) for item in states), key=str.casefold):
            add(name)
    return EntityAliasIndex(
        aliases={
            alias: tuple(sorted(identities))
            for alias, identities in sorted(declarations.items())
        },
        canonical_names=dict(sorted(canonical_names.items())),
    )


def claim_value_hash(value: Any) -> str:
    return canonical_sha256("CanonicalClaimValueV1", value)


def knowledge_topic_hash(topic: Any) -> str:
    return canonical_sha256("CanonicalKnowledgeTopicV1", topic)


def make_proposed_claim(
    *, claim_kind: ClaimKind, subject_id: str, predicate: str,
    perspective: Perspective, semantic_domain: SemanticDomain,
    story_time: str | None, value: Any, source_artifact_hash: str,
    object_id: str | None = None, knowledge_owner_id: str | None = None,
    knowledge_topic: Any | None = None,
) -> ProposedClaimV2:
    payload = {
        "schema": "ProposedClaimV2", "version": 2,
        "claim_kind": claim_kind, "subject_id": subject_id,
        "predicate": predicate, "object_id": object_id,
        "knowledge_owner_id": knowledge_owner_id,
        "knowledge_topic_hash": (
            knowledge_topic_hash(knowledge_topic)
            if knowledge_topic is not None else None
        ),
        "perspective": perspective, "semantic_domain": semantic_domain,
        "story_time": story_time, "value_hash": claim_value_hash(value),
        "source_artifact_hash": source_artifact_hash,
    }
    return ProposedClaimV2.model_validate({
        **payload,
        "claim_id": stable_id("claim", "ProposedClaimV2", payload),
    })


def make_claim_batch(
    claims: tuple[ProposedClaimV2, ...], *, base_authority_revision: int,
    base_authority_hash: str, source_artifact_hash: str,
    coverage_mode: Literal["complete_source", "window_union"],
) -> ProposedClaimBatchV2:
    payload = {
        "schema": "ProposedClaimBatchV2", "version": 2,
        "base_authority_revision": base_authority_revision,
        "base_authority_hash": base_authority_hash,
        "source_artifact_hash": source_artifact_hash,
        "coverage_mode": coverage_mode,
        "claims": tuple(
            item.model_dump(mode="json", by_alias=True) for item in claims
        ),
    }
    return ProposedClaimBatchV2.model_validate({
        **payload,
        "batch_id": stable_id("batch", "ProposedClaimBatchV2", payload),
    })


def resolve_shadow_slot(claim: ProposedClaimV2) -> ShadowSlotIdentityV1:
    reasons: list[str] = []
    if claim.story_time is None:
        reasons.append("story_time_unknown")
    if claim.subject_id.startswith("ambiguous-"):
        reasons.append("subject_ambiguous")
    dimensions: dict[str, Any] = {
        "subject_id": claim.subject_id,
        "predicate": claim.predicate,
        "perspective": claim.perspective,
        "semantic_domain": claim.semantic_domain,
    }
    if claim.claim_kind == "character.knowledge":
        dimensions.update({
            "knowledge_owner_id": claim.knowledge_owner_id,
            "knowledge_topic_hash": claim.knowledge_topic_hash,
        })
    elif claim.claim_kind == "character.relationship":
        dimensions.update({
            "object_id": claim.object_id,
            "relationship_direction": (
                f"{claim.subject_id}->{claim.object_id}"
            ),
        })
    slot_id = stable_id("slot", "ShadowSlotIdentityV1", dimensions)
    competition_key = (
        stable_id("compete", "ShadowCompetitionKeyV1", {
            "slot_id": slot_id, "story_time": claim.story_time,
        })
        if claim.story_time is not None else None
    )
    return ShadowSlotIdentityV1(
        slot_id=slot_id, competition_key=competition_key,
        status="ambiguous" if reasons else "exact",
        subject_id=claim.subject_id, predicate=claim.predicate,
        object_id=claim.object_id,
        knowledge_owner_id=claim.knowledge_owner_id,
        knowledge_topic_hash=claim.knowledge_topic_hash,
        perspective=claim.perspective,
        semantic_domain=claim.semantic_domain,
        story_time=claim.story_time, reasons=tuple(reasons),
    )


def build_evidence_envelope(
    claim: ProposedClaimV2, *, final_source_bytes: bytes,
    declared_source_artifact_hash: str, evidence_text: str | None,
    base_authority_revision: int, base_authority_hash: str,
    covered_ranges: tuple[tuple[int, int], ...],
) -> EvidenceEnvelopeV2:
    actual_source_hash = hashlib.sha256(final_source_bytes).hexdigest()
    spans: tuple[EvidenceByteSpanV2, ...] = ()
    gaps: tuple[str, ...] = ()
    ambiguous = False
    grounding: Grounding
    if actual_source_hash != declared_source_artifact_hash:
        grounding, ambiguous, gaps = "ambiguous", True, ("source_hash_mismatch",)
    elif not evidence_text:
        grounding, gaps = "ungrounded", ("evidence_missing",)
    else:
        needle = evidence_text.encode(UTF8)
        offsets: list[int] = []
        cursor = 0
        while needle:
            found = final_source_bytes.find(needle, cursor)
            if found < 0:
                break
            offsets.append(found)
            cursor = found + 1
        if len(offsets) == 1:
            start = offsets[0]
            spans = (EvidenceByteSpanV2(
                byte_start=start, byte_end=start + len(needle),
                byte_sha256=hashlib.sha256(needle).hexdigest(),
            ),)
            grounding = "exact"
        elif not offsets:
            grounding, gaps = "ungrounded", ("evidence_not_in_final_bytes",)
        else:
            grounding, ambiguous, gaps = (
                "ambiguous", True, ("evidence_non_unique",),
            )
    payload = {
        "schema": "EvidenceEnvelopeV2", "version": 2,
        "claim_id": claim.claim_id,
        "source_artifact_hash": declared_source_artifact_hash,
        "base_authority_revision": base_authority_revision,
        "base_authority_hash": base_authority_hash,
        "extractor_contract_version": "final-bytes-extractor-v1",
        "grounding": grounding,
        "spans": tuple(
            item.model_dump(mode="json", by_alias=True) for item in spans
        ),
        "covered_ranges": covered_ranges, "gaps": gaps,
        "candidate_slot_id": resolve_shadow_slot(claim).slot_id,
        "ambiguous": ambiguous,
    }
    return EvidenceEnvelopeV2.model_validate({
        **payload,
        "evidence_hash": canonical_sha256("EvidenceEnvelopeV2", payload),
    })


def _story_state_values(
    state_data: Mapping[str, Any], claim: ProposedClaimV2,
    aliases: EntityAliasIndex,
) -> tuple[list[Any], list[dict[str, Any]], bool]:
    values: list[Any] = []
    evidence: list[dict[str, Any]] = []
    subject_seen = False
    states = state_data.get("character_states")
    if isinstance(states, Mapping):
        for raw_name, raw_state in states.items():
            resolved, status = aliases.resolve(str(raw_name))
            if status != "exact" or resolved != claim.subject_id:
                continue
            subject_seen = True
            if not isinstance(raw_state, Mapping):
                continue
            if claim.claim_kind == "character.location" and "location" in raw_state:
                values.append(raw_state["location"])
                evidence.append({"source": "character_states", "path": [str(raw_name), "location"]})
            elif claim.claim_kind == "character.knowledge":
                knowledge = raw_state.get("knowledge")
                if isinstance(knowledge, Mapping):
                    for topic, value in knowledge.items():
                        if knowledge_topic_hash(topic) == claim.knowledge_topic_hash:
                            values.append(value)
                            evidence.append({"source": "character_states", "path": [str(raw_name), "knowledge", str(topic)]})
                elif isinstance(knowledge, list):
                    for topic in knowledge:
                        if knowledge_topic_hash(topic) == claim.knowledge_topic_hash:
                            values.append(True)
                            evidence.append({"source": "character_states", "path": [str(raw_name), "knowledge"]})
            elif claim.claim_kind == "character.relationship":
                relationships = raw_state.get("relationships")
                if isinstance(relationships, Mapping):
                    for other, value in relationships.items():
                        other_id, other_status = aliases.resolve(str(other))
                        if other_status == "exact" and other_id == claim.object_id:
                            values.append(value)
                            evidence.append({"source": "character_states", "path": [str(raw_name), "relationships", str(other)]})
    facts = state_data.get("confirmed_facts")
    if isinstance(facts, list):
        for index, raw in enumerate(facts):
            if not isinstance(raw, Mapping):
                continue
            key = str(raw.get("key") or raw.get("fact_key") or "").strip()
            parts = [item for item in key.split(".") if item]
            if len(parts) < 2:
                continue
            fact_subject, fact_status = aliases.resolve(parts[0])
            if fact_status != "exact" or fact_subject != claim.subject_id:
                continue
            subject_seen = True
            matched = False
            if claim.claim_kind == "character.location":
                matched = parts[1] == "location"
            elif claim.claim_kind == "character.knowledge" and parts[1] == "knowledge":
                matched = (
                    len(parts) > 2
                    and knowledge_topic_hash(".".join(parts[2:]))
                    == claim.knowledge_topic_hash
                )
            elif claim.claim_kind == "character.relationship" and len(parts) > 2:
                other_id, other_status = aliases.resolve(parts[-1])
                matched = (
                    other_status == "exact" and other_id == claim.object_id
                    and parts[1] in {"relationship", claim.predicate}
                )
            if matched and "value" in raw:
                values.append(raw["value"])
                evidence.append({
                    "source": "confirmed_facts", "path": [index, "value"],
                })
    return values, evidence, subject_seen


def resolve_story_state_expected_current(
    *, state_data: Mapping[str, Any], actual_revision: int,
    actual_authority_hash: str, requested_revision: int,
    requested_authority_hash: str, claim: ProposedClaimV2,
    aliases: EntityAliasIndex,
) -> dict[str, Any]:
    """Resolve expected current from StoryState only; never consult projections."""

    computed_hash = story_state_authority_hash(state_data)
    if (
        requested_revision != actual_revision
        or requested_authority_hash != actual_authority_hash
        or computed_hash != actual_authority_hash
    ):
        return {
            "status": "unavailable", "current_hash": None,
            "authority_slice_hash": None,
            "failure_codes": ("story_state_base_mismatch",),
        }
    values, paths, subject_seen = _story_state_values(state_data, claim, aliases)
    unique = {claim_value_hash(value): value for value in values}
    authority_slice = {
        "base_revision": actual_revision,
        "base_authority_hash": actual_authority_hash,
        "claim_kind": claim.claim_kind, "subject_id": claim.subject_id,
        "object_id": claim.object_id,
        "knowledge_topic_hash": claim.knowledge_topic_hash,
        "values": sorted(unique), "paths": paths,
        "subject_seen": subject_seen,
    }
    slice_hash = canonical_sha256(
        "StoryStateCanonicalAuthoritySliceV1", authority_slice,
    )
    if len(unique) > 1:
        return {
            "status": "ambiguous", "current_hash": None,
            "authority_slice_hash": slice_hash,
            "failure_codes": ("story_state_multiple_current_values",),
        }
    if len(unique) == 1:
        return {
            "status": "exact", "current_hash": next(iter(unique)),
            "authority_slice_hash": slice_hash, "failure_codes": (),
        }
    return {
        "status": "absent", "current_hash": None,
        "authority_slice_hash": slice_hash,
        "failure_codes": () if subject_seen else ("story_state_subject_unknown",),
    }


def build_shadow_mutation(
    *, operation: MutationOperation, claim: ProposedClaimV2,
    evidence: EvidenceEnvelopeV2, slot: ShadowSlotIdentityV1,
    state_data: Mapping[str, Any], actual_revision: int,
    actual_authority_hash: str, aliases: EntityAliasIndex,
    requested_expected_current_hash: str | None = None,
) -> CanonicalMutationV1:
    current = resolve_story_state_expected_current(
        state_data=state_data, actual_revision=actual_revision,
        actual_authority_hash=actual_authority_hash,
        requested_revision=evidence.base_authority_revision,
        requested_authority_hash=evidence.base_authority_hash,
        claim=claim, aliases=aliases,
    )
    failures = list(current["failure_codes"])
    if slot.status != "exact" or not slot.slot_id or not slot.competition_key:
        failures.append("slot_identity_ambiguous")
    if evidence.grounding != "exact":
        failures.append("evidence_not_exact")
    if claim.semantic_domain != "occurred_current":
        failures.append("authority_domain_not_current")
    status = current["status"]
    eligibility: Eligibility = "ineligible"
    if status == "ambiguous":
        eligibility = "ambiguous"
    elif not failures:
        current_hash = current["current_hash"]
        if operation == "ASSERT":
            if status == "absent":
                eligibility = "eligible"
            elif current_hash == claim.value_hash:
                eligibility = "no_change"
            else:
                failures.append("assert_would_overwrite_current")
        else:
            if status != "exact":
                failures.append("expected_current_missing")
            elif requested_expected_current_hash is None:
                failures.append("expected_current_not_declared")
            elif requested_expected_current_hash != current_hash:
                failures.append("expected_current_mismatch")
            elif operation in {"TRANSITION", "SUPERSEDE"} and (
                claim.value_hash == current_hash
            ):
                eligibility = "no_change"
            else:
                eligibility = "eligible"
    payload = {
        "schema": "CanonicalMutationV1", "version": 1,
        "operation": operation, "claim_id": claim.claim_id,
        "evidence_hash": evidence.evidence_hash,
        "slot_id": slot.slot_id or "slot-unknown",
        "competition_key": slot.competition_key or "compete-unknown",
        "base_authority_revision": evidence.base_authority_revision,
        "base_authority_hash": evidence.base_authority_hash,
        "authority_slice_hash": current["authority_slice_hash"],
        "expected_current_hash": current["current_hash"],
        "proposed_value_hash": claim.value_hash,
        "eligibility": eligibility,
        "failure_codes": tuple(dict.fromkeys(failures)),
        "shadow_only": True,
    }
    return CanonicalMutationV1.model_validate({
        **payload,
        "mutation_id": stable_id("mutation", "CanonicalMutationV1", payload),
    })


def build_shadow_receipt(
    mutation: CanonicalMutationV1, *, legacy_comparison: Literal[
        "equivalent", "legacy_only", "shadow_only", "value_mismatch",
        "qualification_mismatch", "identity_false_split_candidate",
        "identity_false_merge_candidate", "uncomparable",
    ],
) -> ShadowCanonicalCommitReceiptV1:
    payload = {
        "schema": "ShadowCanonicalCommitReceiptV1", "version": 1,
        "mutation_id": mutation.mutation_id,
        "base_authority_revision": mutation.base_authority_revision,
        "base_authority_hash": mutation.base_authority_hash,
        "shadow_only": True, "commit_performed": False,
        "outcome": "shadow_not_committed", "target_revision": None,
        "target_authority_hash": None, "projection_effects": (),
        "legacy_comparison": legacy_comparison,
    }
    return ShadowCanonicalCommitReceiptV1.model_validate({
        **payload,
        "receipt_hash": canonical_sha256(
            "ShadowCanonicalCommitReceiptV1", payload,
        ),
    })


def _resolved_or_ambiguous_entity(
    aliases: EntityAliasIndex, raw: str,
) -> tuple[str, IdentityStatus]:
    resolved, status = aliases.resolve(raw)
    if resolved:
        return resolved, status
    return stable_id(
        "ambiguous", "AmbiguousShadowEntityV1",
        {"normalized_alias": normalize_entity_alias(raw), "status": status},
    ), "ambiguous"


def extract_shadow_claim_inputs(
    candidate: Mapping[str, Any], *, aliases: EntityAliasIndex,
    story_time: str | None, source_artifact_hash: str,
) -> tuple[ShadowClaimInput, ...]:
    """Project only the three Phase 1A kinds from a frozen legacy result."""

    observations: list[ShadowClaimInput] = []
    seen: dict[str, int] = {}

    def add(
        *, kind: ClaimKind, raw_subject: str, predicate: str, value: Any,
        raw_key: str, evidence_text: str | None,
        operation: MutationOperation = "ASSERT", expected: Any = None,
        raw_object: str | None = None, knowledge_topic: Any = None,
        perspective: Perspective = "objective_world",
    ) -> None:
        subject, subject_status = _resolved_or_ambiguous_entity(
            aliases, raw_subject,
        )
        object_id = None
        if raw_object is not None:
            object_id, _object_status = _resolved_or_ambiguous_entity(
                aliases, raw_object,
            )
        owner = subject if kind == "character.knowledge" else None
        claim = make_proposed_claim(
            claim_kind=kind, subject_id=subject, predicate=predicate,
            object_id=object_id, knowledge_owner_id=owner,
            knowledge_topic=knowledge_topic,
            perspective=perspective, semantic_domain="occurred_current",
            story_time=story_time, value=value,
            source_artifact_hash=source_artifact_hash,
        )
        observation = ShadowClaimInput(
            claim=claim, evidence_text=evidence_text,
            operation=operation,
            requested_expected_current_hash=(
                claim_value_hash(expected)
                if operation != "ASSERT" and expected is not None else None
            ),
            raw_key_hash=canonical_sha256("LegacyClaimKeyV1", {
                "raw_key": raw_key,
                "subject_status": subject_status,
            }),
        )
        existing = seen.get(claim.claim_id)
        if existing is not None:
            if operation != "ASSERT":
                observations[existing] = observation
            return
        seen[claim.claim_id] = len(observations)
        observations.append(observation)

    facts = candidate.get("facts")
    if isinstance(facts, list):
        for index, raw in enumerate(facts):
            if not isinstance(raw, Mapping):
                continue
            key = str(raw.get("key") or raw.get("fact_key") or "").strip()
            value = raw.get("value", raw.get("fact"))
            parts = [item for item in key.split(".") if item]
            if len(parts) < 2 or value in (None, ""):
                continue
            evidence = raw.get("evidence")
            evidence_text = (
                str(evidence.get("quote") or "").strip()
                if isinstance(evidence, Mapping) else str(evidence or value).strip()
            )
            if parts[1] == "location":
                add(
                    kind="character.location", raw_subject=parts[0],
                    predicate="location", value=value, raw_key=key,
                    evidence_text=evidence_text,
                )
            elif parts[1] == "knowledge" and len(parts) > 2:
                add(
                    kind="character.knowledge", raw_subject=parts[0],
                    predicate="knowledge", knowledge_topic=".".join(parts[2:]),
                    value=value, raw_key=key, evidence_text=evidence_text,
                    perspective="character_belief",
                )
            elif (
                len(parts) > 2
                and parts[1] in CONTROLLED_RELATIONSHIP_PREDICATES
            ):
                add(
                    kind="character.relationship", raw_subject=parts[0],
                    raw_object=parts[-1], predicate=parts[1], value=value,
                    raw_key=key, evidence_text=evidence_text,
                    perspective="character_belief",
                )

    state = candidate.get("state")
    if isinstance(state, Mapping):
        for raw_subject, raw_state in state.items():
            if not isinstance(raw_state, Mapping):
                continue
            if "location" in raw_state:
                value = raw_state["location"]
                add(
                    kind="character.location", raw_subject=str(raw_subject),
                    predicate="location", value=value,
                    raw_key=f"{raw_subject}.location",
                    evidence_text=str(value) if isinstance(value, str) else None,
                )
            knowledge = raw_state.get("knowledge")
            if isinstance(knowledge, Mapping):
                for topic, value in knowledge.items():
                    add(
                        kind="character.knowledge", raw_subject=str(raw_subject),
                        predicate="knowledge", knowledge_topic=topic, value=value,
                        raw_key=f"{raw_subject}.knowledge.{topic}",
                        evidence_text=str(topic) if isinstance(topic, str) else None,
                        perspective="character_belief",
                    )
            relationships = raw_state.get("relationships")
            if isinstance(relationships, Mapping):
                for other, value in relationships.items():
                    add(
                        kind="character.relationship", raw_subject=str(raw_subject),
                        raw_object=str(other), predicate="relationship", value=value,
                        raw_key=f"{raw_subject}.relationship.{other}",
                        evidence_text=str(value) if isinstance(value, str) else None,
                        perspective="character_belief",
                    )

    transitions = candidate.get("state_transitions")
    if isinstance(transitions, list):
        for index, raw in enumerate(transitions):
            if not isinstance(raw, Mapping):
                continue
            subject = str(raw.get("character") or "").strip()
            field = str(raw.get("field") or "").strip()
            if not subject or "from" not in raw or "to" not in raw:
                continue
            evidence = raw.get("evidence")
            evidence_text = (
                str(evidence.get("quote") or "").strip()
                if isinstance(evidence, Mapping) else str(evidence or "").strip()
            )
            if field == "location":
                add(
                    kind="character.location", raw_subject=subject,
                    predicate="location", value=raw["to"],
                    raw_key=f"transition.{index}.{subject}.{field}",
                    evidence_text=evidence_text, operation="TRANSITION",
                    expected=raw["from"],
                )
            elif field.startswith("knowledge."):
                add(
                    kind="character.knowledge", raw_subject=subject,
                    predicate="knowledge", knowledge_topic=field.split(".", 1)[1],
                    value=raw["to"], raw_key=f"transition.{index}.{subject}.{field}",
                    evidence_text=evidence_text, operation="TRANSITION",
                    expected=raw["from"], perspective="character_belief",
                )
            elif field.startswith("relationships."):
                add(
                    kind="character.relationship", raw_subject=subject,
                    raw_object=field.split(".", 1)[1], predicate="relationship",
                    value=raw["to"], raw_key=f"transition.{index}.{subject}.{field}",
                    evidence_text=evidence_text, operation="TRANSITION",
                    expected=raw["from"], perspective="character_belief",
                )
    return tuple(sorted(observations, key=lambda item: item.claim.claim_id))


def evaluate_maintenance_shadow(
    *, project_root: Path, workflow: str, legacy_candidate: Mapping[str, Any],
    final_source_bytes: bytes, story_time: str | None,
    story_state_revision: int, story_state_data: Mapping[str, Any],
    coverage_mode: Literal["complete_source", "window_union"],
) -> tuple[ShadowObservationReport, tuple[dict[str, Any], ...]]:
    """Compute a deterministic evaluation without any production writer."""

    source_hash = hashlib.sha256(final_source_bytes).hexdigest()
    authority_hash = story_state_authority_hash(story_state_data)
    aliases = build_entity_alias_index(project_root, story_state_data)
    inputs = extract_shadow_claim_inputs(
        legacy_candidate, aliases=aliases, story_time=story_time,
        source_artifact_hash=source_hash,
    )
    batch = make_claim_batch(
        tuple(item.claim for item in inputs),
        base_authority_revision=story_state_revision,
        base_authority_hash=authority_hash,
        source_artifact_hash=source_hash, coverage_mode=coverage_mode,
    )
    rows: list[dict[str, Any]] = []
    comparisons: dict[str, int] = {}
    receipts: list[str] = []
    for item in inputs:
        slot = resolve_shadow_slot(item.claim)
        evidence = build_evidence_envelope(
            item.claim, final_source_bytes=final_source_bytes,
            declared_source_artifact_hash=source_hash,
            evidence_text=item.evidence_text,
            base_authority_revision=story_state_revision,
            base_authority_hash=authority_hash,
            covered_ranges=((0, len(final_source_bytes)),),
        )
        mutation = build_shadow_mutation(
            operation=item.operation, claim=item.claim, evidence=evidence,
            slot=slot, state_data=story_state_data,
            actual_revision=story_state_revision,
            actual_authority_hash=authority_hash, aliases=aliases,
            requested_expected_current_hash=item.requested_expected_current_hash,
        )
        if slot.status != "exact":
            comparison = "identity_false_split_candidate"
        elif mutation.eligibility in {"eligible", "no_change"}:
            comparison = "equivalent"
        else:
            comparison = "qualification_mismatch"
        receipt = build_shadow_receipt(
            mutation, legacy_comparison=comparison,
        )
        comparisons[comparison] = comparisons.get(comparison, 0) + 1
        receipts.append(receipt.receipt_hash)
        rows.append({
            "workflow": workflow, "batch_id": batch.batch_id,
            "claim_id": item.claim.claim_id,
            "claim_kind": item.claim.claim_kind,
            "raw_key_hash": item.raw_key_hash,
            "slot_id": slot.slot_id,
            "competition_key": slot.competition_key,
            "identity_status": slot.status,
            "evidence_hash": evidence.evidence_hash,
            "grounding": evidence.grounding,
            "evidence_gap_count": len(evidence.gaps),
            "mutation_id": mutation.mutation_id,
            "operation": mutation.operation,
            "eligibility": mutation.eligibility,
            "failure_codes": mutation.failure_codes,
            "authority_slice_hash": mutation.authority_slice_hash,
            "expected_current_hash": mutation.expected_current_hash,
            "receipt_hash": receipt.receipt_hash,
            "legacy_comparison": comparison,
            "shadow_only": True, "commit_performed": False,
            "source_artifact_hash": source_hash,
            "base_authority_revision": story_state_revision,
            "base_authority_hash": authority_hash,
            "coverage_mode": coverage_mode,
        })
    report = ShadowObservationReport(
        enabled=True, workflow=workflow, claim_count=len(rows),
        eligible_count=sum(row["eligibility"] == "eligible" for row in rows),
        no_change_count=sum(row["eligibility"] == "no_change" for row in rows),
        ineligible_count=sum(row["eligibility"] == "ineligible" for row in rows),
        ambiguous_count=sum(row["eligibility"] == "ambiguous" for row in rows),
        exact_evidence_count=sum(row["grounding"] == "exact" for row in rows),
        evidence_gap_count=sum(int(row["evidence_gap_count"]) for row in rows),
        identity_ambiguous_count=sum(
            row["identity_status"] != "exact" for row in rows
        ),
        comparison_counts=dict(sorted(comparisons.items())),
        receipt_hashes=tuple(sorted(receipts)),
    )
    return report, tuple(rows)


def observe_maintenance_shadow(
    *, project_root: Path, workflow: str, legacy_candidate: Mapping[str, Any],
    final_source_bytes: bytes, story_time: str | None,
    story_state_revision: int, story_state_data: Mapping[str, Any],
    coverage_mode: Literal["complete_source", "window_union"],
    run_id: str | None = None,
) -> ShadowObservationReport | None:
    """Fail-open facade; disabled mode returns before alias or claim work."""

    if not shadow_enabled():
        return None
    try:
        report, rows = evaluate_maintenance_shadow(
            project_root=project_root, workflow=workflow,
            legacy_candidate=legacy_candidate,
            final_source_bytes=final_source_bytes, story_time=story_time,
            story_state_revision=story_state_revision,
            story_state_data=story_state_data, coverage_mode=coverage_mode,
        )
        from novel_flywheel.reliability_trace import emit_observation

        for row in rows:
            emit_observation(
                project_root, event_type="proposed_claim",
                source_component="canonical_shadow.observe_maintenance_shadow",
                source_writer=workflow, observation_status=(
                    "confirmed" if row["identity_status"] == "exact" else "unknown"
                ),
                payload={
                    "claim_kind": row["claim_kind"], "shadow_only": True,
                    "affects_business_decision": False,
                    "batch_id": row["batch_id"], "claim_id": row["claim_id"],
                    "slot_id": row["slot_id"],
                    "competition_key": row["competition_key"],
                    "identity_status": row["identity_status"],
                    "evidence_hash": row["evidence_hash"],
                    "grounding": row["grounding"],
                    "mutation_id": row["mutation_id"],
                    "operation": row["operation"],
                    "eligibility": row["eligibility"],
                    "failure_codes": list(row["failure_codes"]),
                    "authority_slice_hash": row["authority_slice_hash"],
                    "expected_current_hash": row["expected_current_hash"],
                    "receipt_hash": row["receipt_hash"],
                    "legacy_comparison": row["legacy_comparison"],
                    "commit_performed": False,
                    "source_artifact_hash": row["source_artifact_hash"],
                    "base_authority_revision": row["base_authority_revision"],
                    "base_authority_hash": row["base_authority_hash"],
                    "coverage_mode": row["coverage_mode"],
                },
                run_id=run_id, stage_id="maintenance_shadow",
                semantic_domain="occurred_current",
                authority_revision=story_state_revision,
                authority_hash=story_state_authority_hash(story_state_data),
            )
        emit_observation(
            project_root, event_type="proposed_claim",
            source_component="canonical_shadow.observe_maintenance_shadow",
            source_writer=workflow, observation_status="confirmed",
            payload={
                "claim_kind": "shadow_batch_summary", "shadow_only": True,
                "affects_business_decision": False,
                "workflow": report.workflow, "claim_count": report.claim_count,
                "eligible_count": report.eligible_count,
                "no_change_count": report.no_change_count,
                "ineligible_count": report.ineligible_count,
                "ambiguous_count": report.ambiguous_count,
                "exact_evidence_count": report.exact_evidence_count,
                "evidence_gap_count": report.evidence_gap_count,
                "identity_ambiguous_count": report.identity_ambiguous_count,
                "comparison_counts": report.comparison_counts,
                "receipt_set_hash": canonical_sha256(
                    "ShadowReceiptSetV1", report.receipt_hashes,
                ),
                "commit_performed": False,
            },
            run_id=run_id, stage_id="maintenance_shadow_summary",
            semantic_domain="occurred_current",
            authority_revision=story_state_revision,
            authority_hash=story_state_authority_hash(story_state_data),
        )
        return report
    except Exception:
        return None
