from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


NARRATIVE_GRAPH_VERSION = 1


class ClaimStatus(StrEnum):
    KNOWN = "known"
    FALSE = "false"
    UNKNOWN = "unknown"


class ClaimTransition(StrEnum):
    ASSERT = "assert"
    REVEAL = "reveal"
    REVISE = "revise"
    RETRACT = "retract"
    FORGET = "forget"
    QUESTION = "question"


class ClaimAuthority(StrEnum):
    FORMAL = "formal"
    CONFIRMED = "confirmed"
    DERIVED = "derived"
    CANDIDATE = "candidate"


class StoryClaim(BaseModel):
    """One perspective-bound narrative fact or state transition."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim_id: str = Field(min_length=1, max_length=160)
    subject: str = Field(min_length=1, max_length=240)
    predicate: str = Field(min_length=1, max_length=160)
    value: str | int | float | bool | None = None
    perspective: str = Field(default="world", min_length=1, max_length=160)
    status: ClaimStatus = ClaimStatus.KNOWN
    transition: ClaimTransition = ClaimTransition.ASSERT
    authority: ClaimAuthority = ClaimAuthority.DERIVED
    event_id: str = ""
    event_order: int = Field(default=0, ge=0)
    evidence: str = ""
    source_artifact: str = ""
    source_sha256: str = ""
    depends_on: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("source_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if value and (len(value) != 64 or any(char not in "0123456789abcdef" for char in value)):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        return value


class IdentityState(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    entity: str = Field(min_length=1, max_length=240)
    actual_identity: str = ""
    claimed_identity: str = ""
    public_belief: str = ""
    known_by: dict[str, ClaimStatus] = Field(default_factory=dict)
    source_claim_ids: list[str] = Field(default_factory=list)


class RelationshipState(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    participants: tuple[str, str]
    stage: str = Field(min_length=1, max_length=120)
    since_event: str = ""
    evidence: str = ""
    source_claim_ids: list[str] = Field(default_factory=list)


class PromiseState(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    promise_id: str = Field(min_length=1, max_length=160)
    promisor: str = Field(min_length=1, max_length=240)
    promisee: str = Field(min_length=1, max_length=240)
    commitment: str = Field(min_length=1)
    status: str = Field(default="open", pattern=r"^(open|fulfilled|broken|released)$")
    created_event: str = ""
    resolved_event: str = ""
    evidence: str = ""


class NarrativeFactGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = NARRATIVE_GRAPH_VERSION
    claims: list[StoryClaim] = Field(default_factory=list)
    identities: list[IdentityState] = Field(default_factory=list)
    relationships: list[RelationshipState] = Field(default_factory=list)
    promises: list[PromiseState] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: int) -> int:
        if value != NARRATIVE_GRAPH_VERSION:
            raise ValueError("unsupported narrative graph version")
        return value

    @property
    def sha256(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()


def empty_narrative_graph() -> dict[str, Any]:
    return NarrativeFactGraph().model_dump(mode="json")


def parse_narrative_graph(value: object) -> NarrativeFactGraph:
    if value in (None, {}):
        return NarrativeFactGraph()
    return NarrativeFactGraph.model_validate(value)


def migrate_narrative_graph(value: object) -> dict[str, Any]:
    """Idempotently canonicalize the additive StoryState graph."""
    return parse_narrative_graph(value).model_dump(mode="json")
