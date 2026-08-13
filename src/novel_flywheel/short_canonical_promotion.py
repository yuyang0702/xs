"""Short-only canonical promotion contracts and deterministic adapters.

Phase 1B keeps model/protocol handling in the existing Maintenance runtime.
This module begins at the normalized, structurally valid proposal inventory and
never invokes a model, reads a projection as authority, or writes StoryState.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_flywheel.canonical_shadow import (
    CanonicalMutationV1,
    CONTROLLED_RELATIONSHIP_PREDICATES,
    EvidenceEnvelopeV2,
    ProposedClaimBatchV2,
    ProposedClaimV2,
    ShadowSlotIdentityV1,
    build_entity_alias_index,
    build_evidence_envelope,
    build_shadow_mutation,
    canonical_sha256,
    claim_value_hash,
    make_claim_batch,
    make_proposed_claim,
    resolve_shadow_slot,
    resolve_story_state_expected_current,
    stable_id,
    story_state_authority_hash,
)
from novel_flywheel.maintenance_authority import MaintenanceWindowEnvelopeV1


ProposalSourceMode = Literal["normal", "window"]
ProposalCategory = Literal[
    "character.location",
    "character.knowledge",
    "character.relationship",
    "legacy_only",
    "unsupported_reserved",
]
ProposalShape = Literal[
    "fact", "state_delta", "state_transition", "world_rule", "timeline",
]
LegacyDisposition = Literal[
    "pending", "legacy_accepted", "legacy_rejected", "unknown",
]
WriterOwner = Literal["legacy", "canonical_v2"]
PatchOperation = Literal["set", "remove"]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, str_strip_whitespace=True,
    )


class MaintenanceProposalUnitV1(_FrozenModel):
    schema_name: Literal["MaintenanceProposalUnitV1"] = Field(
        default="MaintenanceProposalUnitV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    unit_id: str = Field(min_length=8)
    source_mode: ProposalSourceMode
    source_locator: str = Field(min_length=1)
    source_attempt: int = Field(ge=1)
    shape: ProposalShape
    category: ProposalCategory
    raw_key: str = Field(min_length=1)
    value: Any
    expected_current: Any | None = None
    evidence_text: str | None = None
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    legacy_disposition: LegacyDisposition = "pending"

    @model_validator(mode="after")
    def validate_identity(self) -> "MaintenanceProposalUnitV1":
        payload = self.model_dump(
            mode="json", by_alias=True,
            exclude={"unit_id", "legacy_disposition"},
        )
        if canonical_sha256("MaintenanceProposalUnitPayloadV1", {
            "shape": self.shape,
            "raw_key": self.raw_key,
            "value": self.value,
            "expected_current": self.expected_current,
            "evidence_text": self.evidence_text,
        }) != self.payload_hash:
            raise ValueError("maintenance proposal unit payload hash is stale")
        if self.unit_id != stable_id(
            "proposal-unit", "MaintenanceProposalUnitV1", payload,
        ):
            raise ValueError("maintenance proposal unit identity is stale")
        return self


class MaintenanceProposalInventoryV1(_FrozenModel):
    schema_name: Literal["MaintenanceProposalInventoryV1"] = Field(
        default="MaintenanceProposalInventoryV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    inventory_id: str = Field(min_length=8)
    source_mode: ProposalSourceMode
    source_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_authority_revision: int = Field(ge=1)
    base_authority_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    structurally_valid_unit_count: int = Field(ge=0)
    units: tuple[MaintenanceProposalUnitV1, ...]
    complete: bool = True
    coverage_gaps: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_inventory(self) -> "MaintenanceProposalInventoryV1":
        if len({item.unit_id for item in self.units}) != len(self.units):
            raise ValueError("maintenance proposal inventory contains duplicate units")
        if self.structurally_valid_unit_count < len(self.units):
            raise ValueError("inventory cannot contain more than the valid source units")
        if self.complete and (
            self.structurally_valid_unit_count != len(self.units)
            or self.coverage_gaps
        ):
            raise ValueError("complete inventory has a coverage gap")
        payload = self.model_dump(
            mode="json", by_alias=True, exclude={"inventory_id"},
        )
        if self.inventory_id != stable_id(
            "proposal-inventory", "MaintenanceProposalInventoryV1", payload,
        ):
            raise ValueError("maintenance proposal inventory identity is stale")
        return self

    @property
    def lost_before_v2(self) -> int:
        return self.structurally_valid_unit_count - len(self.units)


class ShortStoryTimeV1(_FrozenModel):
    schema_name: Literal["ShortStoryTimeV1"] = Field(
        default="ShortStoryTimeV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    story_time: str = Field(min_length=8)
    project_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    edition: int = Field(ge=1)
    logical_point: Literal["publication_endpoint"] = "publication_endpoint"

    @model_validator(mode="after")
    def validate_story_time(self) -> "ShortStoryTimeV1":
        expected = stable_id("story-time", "ShortStoryTimeV1", {
            "project_identity_hash": self.project_identity_hash,
            "edition": self.edition,
            "logical_point": self.logical_point,
        })
        if self.story_time != expected:
            raise ValueError("short story time identity is stale")
        return self


class ShortCanonicalMutationCommitV1(_FrozenModel):
    schema_name: Literal["ShortCanonicalMutationCommitV1"] = Field(
        default="ShortCanonicalMutationCommitV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    commit_mutation_id: str = Field(min_length=8)
    phase1a_mutation_id: str = Field(min_length=8)
    claim_id: str = Field(min_length=8)
    operation: Literal["ASSERT", "TRANSITION", "SUPERSEDE", "RETRACT"]
    slot_id: str = Field(min_length=8)
    competition_key: str = Field(min_length=8)
    story_time: str = Field(min_length=8)
    source_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_authority_revision: int = Field(ge=1)
    base_authority_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_slice_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )
    expected_current_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )
    proposed_value_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposed_value: Any
    target_state_path: str = Field(min_length=1)
    canonical_fact_key: str = Field(min_length=1)
    no_change: bool
    policy_version: Literal["short-canonical-policy-v1"] = (
        "short-canonical-policy-v1"
    )

    @model_validator(mode="after")
    def validate_formal_mutation(self) -> "ShortCanonicalMutationCommitV1":
        if claim_value_hash(self.proposed_value) != self.proposed_value_hash:
            raise ValueError("formal mutation proposed value hash is stale")
        payload = self.model_dump(
            mode="json", by_alias=True, exclude={"commit_mutation_id"},
        )
        if self.commit_mutation_id != stable_id(
            "commit-mutation", "ShortCanonicalMutationCommitV1", payload,
        ):
            raise ValueError("formal mutation identity is stale")
        return self


class WriterLeafPatchV1(_FrozenModel):
    schema_name: Literal["WriterLeafPatchV1"] = Field(
        default="WriterLeafPatchV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    path: str = Field(pattern=r"^/(?:.*)$")
    operation: PatchOperation
    owner: WriterOwner
    mutation_id: str | None = None
    value: Any | None = None
    value_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    no_change: bool = False

    @model_validator(mode="after")
    def validate_patch(self) -> "WriterLeafPatchV1":
        if self.owner == "canonical_v2" and not self.mutation_id:
            raise ValueError("V2 writer patch lacks its mutation owner")
        if self.operation == "remove":
            if self.value is not None or self.value_hash is not None:
                raise ValueError("remove patch cannot carry a value")
        elif canonical_sha256("WriterPatchValueV1", self.value) != self.value_hash:
            raise ValueError("writer patch value hash is stale")
        return self


class ShortWriterPlanV1(_FrozenModel):
    schema_name: Literal["ShortWriterPlanV1"] = Field(
        default="ShortWriterPlanV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_authority_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_authority_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    patches: tuple[WriterLeafPatchV1, ...]
    actual_diff_paths: tuple[str, ...]
    unowned: int = Field(ge=0)
    multi_owned: int = Field(ge=0)
    parent_child_overlaps: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_plan(self) -> "ShortWriterPlanV1":
        if self.unowned or self.multi_owned or self.parent_child_overlaps:
            raise ValueError("writer plan ownership is not closed")
        payload = self.model_dump(
            mode="json", by_alias=True, exclude={"plan_hash"},
        )
        if canonical_sha256("ShortWriterPlanV1", payload) != self.plan_hash:
            raise ValueError("writer plan hash is stale")
        return self


class ShortCanonicalGateDecisionV1(_FrozenModel):
    schema_name: Literal["ShortCanonicalGateDecisionV1"] = Field(
        default="ShortCanonicalGateDecisionV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    lane: Literal["short_canonical_v2"] = "short_canonical_v2"
    outcome: Literal["hold"] = "hold"
    canonical_gate_result: Literal["eligible", "hold"]
    operational_readiness: Literal["ready", "hold"]
    hold_reasons: tuple[str, ...] = Field(min_length=1)
    inventory_id: str = Field(min_length=8)
    proposed_claim_batch_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    story_time: str = Field(min_length=8)
    source_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_authority_revision: int = Field(ge=1)
    base_authority_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_diagnostics_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    commit_performed: Literal[False] = False
    target_revision: None = None
    target_authority_hash: None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "ShortCanonicalGateDecisionV1":
        if self.canonical_gate_result == "eligible" and (
            self.operational_readiness == "ready"
        ):
            raise ValueError("hold decision lacks a held gate")
        payload = self.model_dump(
            mode="json", by_alias=True, exclude={"decision_hash"},
        )
        if canonical_sha256("ShortCanonicalGateDecisionV1", payload) != (
            self.decision_hash
        ):
            raise ValueError("canonical gate decision hash is stale")
        return self


class ShortCanonicalCommitReceiptV1(_FrozenModel):
    schema_name: Literal["ShortCanonicalCommitReceiptV1"] = Field(
        default="ShortCanonicalCommitReceiptV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    lane: Literal["short_canonical_v2"] = "short_canonical_v2"
    outcome: Literal["committed"] = "committed"
    policy_version: Literal["short-canonical-policy-v1"] = (
        "short-canonical-policy-v1"
    )
    canonical_gate_result: Literal["eligible"] = "eligible"
    operational_readiness: Literal["ready"] = "ready"
    projection_diagnostics_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    story_time: str = Field(min_length=8)
    source_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_authority_revision: int = Field(ge=1)
    base_authority_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_revision: int = Field(ge=2)
    target_authority_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposed_claim_batch_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_envelope_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    mutation_ids: tuple[str, ...]
    writer_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    journal_frozen_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    commit_performed: Literal[True] = True
    story_state_commit_count: Literal[1] = 1

    @model_validator(mode="after")
    def validate_receipt(self) -> "ShortCanonicalCommitReceiptV1":
        if self.target_revision != self.base_authority_revision + 1:
            raise ValueError("canonical receipt target revision is invalid")
        if len(set(self.mutation_ids)) != len(self.mutation_ids):
            raise ValueError("canonical receipt mutation IDs are duplicated")
        payload = self.model_dump(
            mode="json", by_alias=True, exclude={"receipt_hash"},
        )
        if canonical_sha256("ShortCanonicalCommitReceiptV1", payload) != (
            self.receipt_hash
        ):
            raise ValueError("canonical commit receipt hash is stale")
        return self


@dataclass(frozen=True)
class ShortCanonicalGateEvaluation:
    story_time: ShortStoryTimeV1
    batch: ProposedClaimBatchV2
    claims: tuple[ProposedClaimV2, ...]
    evidence: tuple[EvidenceEnvelopeV2, ...]
    phase1a_mutations: tuple[CanonicalMutationV1, ...]
    formal_mutations: tuple[ShortCanonicalMutationCommitV1, ...]
    canonical_gate_result: Literal["eligible", "hold"]
    canonical_hold_reasons: tuple[str, ...]
    operational_readiness: Literal["ready", "hold"]
    operational_hold_reasons: tuple[str, ...]
    projection_diagnostics: tuple[dict[str, Any], ...]
    replay_counts: dict[str, int]


def _evidence_text(value: object) -> str | None:
    if isinstance(value, Mapping):
        text = str(value.get("quote") or "").strip()
    else:
        text = str(value or "").strip()
    return text or None


def _category(raw_key: str, shape: ProposalShape) -> ProposalCategory:
    if shape in {"world_rule", "timeline"}:
        return "legacy_only"
    parts = [item for item in raw_key.split(".") if item]
    if len(parts) < 2:
        return "legacy_only"
    namespace = parts[1]
    if namespace == "location":
        return (
            "character.location" if len(parts) == 2
            else "unsupported_reserved"
        )
    if namespace == "knowledge":
        return (
            "character.knowledge" if len(parts) >= 3
            else "unsupported_reserved"
        )
    if namespace in {"relationships", *CONTROLLED_RELATIONSHIP_PREDICATES}:
        return (
            "character.relationship" if len(parts) == 3
            else "unsupported_reserved"
        )
    return "legacy_only"


def _make_unit(
    *, source_mode: ProposalSourceMode, source_locator: str,
    source_attempt: int, shape: ProposalShape, raw_key: str, value: Any,
    expected_current: Any | None = None, evidence_text: str | None = None,
    legacy_disposition: LegacyDisposition = "pending",
) -> MaintenanceProposalUnitV1:
    payload_hash = canonical_sha256("MaintenanceProposalUnitPayloadV1", {
        "shape": shape, "raw_key": raw_key, "value": value,
        "expected_current": expected_current,
        "evidence_text": evidence_text,
    })
    payload = {
        "schema": "MaintenanceProposalUnitV1", "version": 1,
        "source_mode": source_mode, "source_locator": source_locator,
        "source_attempt": source_attempt, "shape": shape,
        "category": _category(raw_key, shape), "raw_key": raw_key,
        "value": value, "expected_current": expected_current,
        "evidence_text": evidence_text, "payload_hash": payload_hash,
    }
    return MaintenanceProposalUnitV1.model_validate({
        **payload, "legacy_disposition": legacy_disposition,
        "unit_id": stable_id(
            "proposal-unit", "MaintenanceProposalUnitV1", payload,
        ),
    })


def _flatten_state(
    value: Mapping[str, Any], *, prefix: tuple[str, ...] = (),
) -> list[tuple[str, Any]]:
    result: list[tuple[str, Any]] = []
    for key in sorted(value, key=lambda item: str(item).casefold()):
        item = value[key]
        path = (*prefix, str(key))
        if isinstance(item, Mapping):
            result.extend(_flatten_state(item, prefix=path))
        elif item not in (None, "", [], {}):
            result.append((".".join(path), item))
    return result


def proposal_units_from_candidate(
    candidate: Mapping[str, Any], *, source_mode: ProposalSourceMode,
    source_locator: str, source_attempt: int,
) -> tuple[MaintenanceProposalUnitV1, ...]:
    """Enumerate every structurally valid unit without applying Legacy policy."""

    units: list[MaintenanceProposalUnitV1] = []
    facts = candidate.get("facts")
    if isinstance(facts, list):
        for index, raw in enumerate(facts):
            if not isinstance(raw, Mapping):
                continue
            key = str(raw.get("key") or raw.get("fact_key") or "").strip()
            value = raw.get("value", raw.get("fact"))
            if not key or value in (None, "", [], {}):
                continue
            units.append(_make_unit(
                source_mode=source_mode,
                source_locator=f"{source_locator}:facts:{index}",
                source_attempt=source_attempt, shape="fact", raw_key=key,
                value=value, evidence_text=_evidence_text(raw.get("evidence")),
            ))
    state = candidate.get("state")
    if isinstance(state, Mapping):
        for index, (key, value) in enumerate(_flatten_state(state)):
            units.append(_make_unit(
                source_mode=source_mode,
                source_locator=f"{source_locator}:state:{index}",
                source_attempt=source_attempt, shape="state_delta",
                raw_key=key, value=value,
                evidence_text=None,
            ))
    deltas = candidate.get("state_deltas")
    if isinstance(deltas, list):
        for index, raw in enumerate(deltas):
            if not isinstance(raw, Mapping):
                continue
            character = str(raw.get("character") or "").strip()
            field = str(raw.get("field") or "").strip()
            value = raw.get("value")
            if not character or not field or value in (None, "", [], {}):
                continue
            units.append(_make_unit(
                source_mode=source_mode,
                source_locator=f"{source_locator}:state_deltas:{index}",
                source_attempt=source_attempt, shape="state_delta",
                raw_key=f"{character}.{field}", value=value,
                evidence_text=_evidence_text(raw.get("evidence")),
            ))
    transitions = candidate.get("state_transitions")
    if isinstance(transitions, list):
        for index, raw in enumerate(transitions):
            if not isinstance(raw, Mapping):
                continue
            character = str(raw.get("character") or "").strip()
            field = str(raw.get("field") or "").strip()
            if (
                not character or not field or "from" not in raw or "to" not in raw
                or raw.get("from") in (None, "", [], {})
                or raw.get("to") in (None, "", [], {})
            ):
                continue
            units.append(_make_unit(
                source_mode=source_mode,
                source_locator=f"{source_locator}:state_transitions:{index}",
                source_attempt=source_attempt, shape="state_transition",
                raw_key=f"{character}.{field}", value=raw["to"],
                expected_current=raw["from"],
                evidence_text=_evidence_text(raw.get("evidence")),
            ))
    for field, shape in (("world_rules", "world_rule"), ("timeline", "timeline")):
        values = candidate.get(field)
        if field == "world_rules" and isinstance(values, str) and values.strip():
            values = [values.strip()]
        elif field == "timeline" and isinstance(values, Mapping) and values:
            values = [values]
        if not isinstance(values, list):
            continue
        for index, raw in enumerate(values):
            if isinstance(raw, Mapping):
                value = raw.get("value", raw.get("rule", raw.get("event")))
                key = str(
                    raw.get("key") or raw.get("rule_key")
                    or raw.get("event_key") or f"{field}.{index}"
                ).strip()
                evidence = _evidence_text(raw.get("evidence"))
            else:
                value, key, evidence = raw, f"{field}.{index}", None
            if not key or value in (None, "", [], {}):
                continue
            units.append(_make_unit(
                source_mode=source_mode,
                source_locator=f"{source_locator}:{field}:{index}",
                source_attempt=source_attempt, shape=shape,
                raw_key=key, value=value, evidence_text=evidence,
            ))
    return tuple(sorted(units, key=lambda item: item.unit_id))


def candidate_from_window_envelope(
    envelope: MaintenanceWindowEnvelopeV1,
) -> dict[str, Any]:
    receipt = envelope.receipt
    return {
        "facts": [{
            "key": unit.key, "value": unit.value,
            "evidence": unit.evidence.model_dump(mode="json"),
        } for unit in receipt.facts],
        "state_deltas": [{
            "character": unit.character, "field": unit.field,
            "value": unit.value,
            "evidence": unit.evidence.model_dump(mode="json"),
        } for unit in receipt.state_deltas],
        "state_transitions": [{
            "character": unit.character, "field": unit.field,
            "from": unit.from_value, "to": unit.to,
            "evidence": unit.evidence.model_dump(mode="json"),
        } for unit in receipt.state_transitions],
        "world_rules": [{
            "key": unit.key, "value": unit.value,
            "evidence": unit.evidence.model_dump(mode="json"),
        } for unit in receipt.world_rules],
        "timeline": [{
            "key": unit.key, "value": unit.value,
            "evidence": unit.evidence.model_dump(mode="json"),
        } for unit in receipt.timeline],
    }


def _semantic_signature(unit: MaintenanceProposalUnitV1) -> str:
    return canonical_sha256("MaintenanceProposalSemanticUnitV1", {
        "shape": unit.shape, "raw_key": unit.raw_key,
        "value": unit.value, "expected_current": unit.expected_current,
    })


def classify_legacy_disposition(
    source_units: Sequence[MaintenanceProposalUnitV1],
    accepted_candidate: Mapping[str, Any],
) -> tuple[MaintenanceProposalUnitV1, ...]:
    """Annotate comparison only; the annotation never filters the V2 input."""

    accepted = proposal_units_from_candidate(
        accepted_candidate, source_mode=(source_units[0].source_mode if source_units else "normal"),
        source_locator="legacy-accepted-comparison", source_attempt=1,
    )
    accepted_signatures = {_semantic_signature(item) for item in accepted}
    return tuple(
        item.model_copy(update={
            "legacy_disposition": (
                "legacy_accepted"
                if _semantic_signature(item) in accepted_signatures
                else "legacy_rejected"
            ),
        })
        for item in source_units
    )


def make_maintenance_inventory(
    *, source_mode: ProposalSourceMode, source_artifact_hash: str,
    base_authority_revision: int, base_authority_hash: str,
    units: Sequence[MaintenanceProposalUnitV1],
    structurally_valid_unit_count: int | None = None,
    complete: bool = True, coverage_gaps: Sequence[str] = (),
) -> MaintenanceProposalInventoryV1:
    ordered = tuple(sorted(units, key=lambda item: item.unit_id))
    count = len(ordered) if structurally_valid_unit_count is None else (
        structurally_valid_unit_count
    )
    payload = {
        "schema": "MaintenanceProposalInventoryV1", "version": 1,
        "source_mode": source_mode,
        "source_artifact_hash": source_artifact_hash,
        "base_authority_revision": base_authority_revision,
        "base_authority_hash": base_authority_hash,
        "structurally_valid_unit_count": count,
        "units": tuple(item.model_dump(mode="json", by_alias=True) for item in ordered),
        "complete": complete, "coverage_gaps": tuple(coverage_gaps),
    }
    return MaintenanceProposalInventoryV1.model_validate({
        **payload,
        "inventory_id": stable_id(
            "proposal-inventory", "MaintenanceProposalInventoryV1", payload,
        ),
    })


def combine_maintenance_inventories(
    inventories: Sequence[MaintenanceProposalInventoryV1],
) -> MaintenanceProposalInventoryV1:
    if not inventories:
        raise ValueError("maintenance proposal inventory is unavailable")
    first = inventories[0]
    for item in inventories[1:]:
        if (
            item.source_mode != first.source_mode
            or item.source_artifact_hash != first.source_artifact_hash
            or item.base_authority_revision != first.base_authority_revision
            or item.base_authority_hash != first.base_authority_hash
        ):
            raise ValueError("maintenance proposal inventory authority is mixed")
    units = [unit for item in inventories for unit in item.units]
    unique = {item.unit_id: item for item in units}
    gaps = tuple(sorted({gap for item in inventories for gap in item.coverage_gaps}))
    return make_maintenance_inventory(
        source_mode=first.source_mode,
        source_artifact_hash=first.source_artifact_hash,
        base_authority_revision=first.base_authority_revision,
        base_authority_hash=first.base_authority_hash,
        units=tuple(unique.values()),
        structurally_valid_unit_count=sum(
            item.structurally_valid_unit_count for item in inventories
        ),
        complete=all(item.complete for item in inventories) and not gaps,
        coverage_gaps=gaps,
    )


def inventory_as_shadow_candidate(
    inventory: MaintenanceProposalInventoryV1,
) -> dict[str, Any]:
    """Losslessly expose supported units to the Phase 1A diagnostic evaluator."""

    facts: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    for unit in inventory.units:
        if unit.category not in {
            "character.location", "character.knowledge",
            "character.relationship", "unsupported_reserved",
        }:
            continue
        if unit.shape == "state_transition":
            character, field = unit.raw_key.split(".", 1)
            transitions.append({
                "character": character, "field": field,
                "from": unit.expected_current, "to": unit.value,
                "evidence": unit.evidence_text,
            })
        else:
            facts.append({
                "key": unit.raw_key, "value": unit.value,
                "evidence": unit.evidence_text,
            })
    return {"facts": facts, "state_transitions": transitions}


def predecision_replay_counts(
    inventory: MaintenanceProposalInventoryV1,
) -> dict[str, int]:
    return {
        "proposal_total": inventory.structurally_valid_unit_count,
        "legacy_accepted": sum(
            item.legacy_disposition == "legacy_accepted" for item in inventory.units
        ),
        "legacy_rejected": sum(
            item.legacy_disposition == "legacy_rejected" for item in inventory.units
        ),
        "lost_before_v2": inventory.lost_before_v2,
    }


def short_publication_story_time(
    project_id: str, state_data: Mapping[str, Any],
) -> ShortStoryTimeV1:
    """Return a logical endpoint independent of narrative bytes and run IDs."""

    project_hash = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
    edition = int(state_data.get("manuscript_revision", 0)) + 1
    payload = {
        "project_identity_hash": project_hash,
        "edition": edition,
        "logical_point": "publication_endpoint",
    }
    return ShortStoryTimeV1(
        story_time=stable_id("story-time", "ShortStoryTimeV1", payload),
        **payload,
    )


def select_short_mutation_operation(
    *, proposed_story_time: str, current_story_time: str | None,
    current_exists: bool, explicit_transition: bool,
) -> Literal["ASSERT", "TRANSITION", "SUPERSEDE"]:
    if explicit_transition:
        return "TRANSITION"
    if current_exists and current_story_time == proposed_story_time:
        return "SUPERSEDE"
    return "ASSERT"


def _ambiguous_entity(raw: str, status: str) -> str:
    return stable_id("ambiguous", "AmbiguousShortEntityV1", {
        "raw_identity_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "status": status,
    })


def _pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _claim_for_unit(
    unit: MaintenanceProposalUnitV1, *, aliases: Any,
    story_time: str, source_artifact_hash: str,
) -> tuple[ProposedClaimV2, str, str]:
    parts = [item for item in unit.raw_key.split(".") if item]
    if unit.category == "character.location" and len(parts) == 2:
        raw_subject, predicate = parts[0], "location"
        raw_object = None
        topic = None
        perspective = "objective_world"
        target_tail = ("location",)
        fact_tail = ("location",)
    elif unit.category == "character.knowledge" and len(parts) >= 3:
        raw_subject, predicate = parts[0], "knowledge"
        raw_object = None
        topic = ".".join(parts[2:])
        perspective = "character_belief"
        target_tail = ("knowledge", topic)
        fact_tail = ("knowledge", topic)
    elif unit.category == "character.relationship" and len(parts) == 3:
        raw_subject = parts[0]
        predicate = (
            "relationship" if parts[1] == "relationships" else parts[1]
        )
        raw_object = parts[2]
        topic = None
        perspective = "character_belief"
        target_tail = ("relationships", raw_object)
        fact_tail = (predicate, raw_object)
    else:
        raise ValueError("unsupported unit cannot become a canonical claim")

    subject_id, subject_status = aliases.resolve(raw_subject)
    if subject_id is None:
        subject_id = _ambiguous_entity(raw_subject, subject_status)
    subject_name = aliases.canonical_names.get(subject_id, raw_subject)
    object_id = None
    object_name = raw_object
    if raw_object is not None:
        object_id, object_status = aliases.resolve(raw_object)
        if object_id is None:
            object_id = _ambiguous_entity(raw_object, object_status)
        object_name = aliases.canonical_names.get(object_id, raw_object)
        target_tail = ("relationships", object_name)
        fact_tail = (predicate, object_name)
    claim = make_proposed_claim(
        claim_kind=unit.category,
        subject_id=subject_id, predicate=predicate,
        object_id=object_id,
        knowledge_owner_id=(
            subject_id if unit.category == "character.knowledge" else None
        ),
        knowledge_topic=topic,
        perspective=perspective,
        semantic_domain="occurred_current",
        story_time=story_time, value=unit.value,
        source_artifact_hash=source_artifact_hash,
    )
    target_path = "/".join((
        "", "character_states", _pointer_escape(subject_name),
        *(_pointer_escape(item) for item in target_tail),
    ))
    canonical_fact_key = ".".join((subject_name, *fact_tail))
    return claim, target_path, canonical_fact_key


def _formal_mutation(
    *, mutation: CanonicalMutationV1, claim: ProposedClaimV2,
    evidence: EvidenceEnvelopeV2, unit: MaintenanceProposalUnitV1,
    target_path: str, canonical_fact_key: str,
) -> ShortCanonicalMutationCommitV1:
    payload = {
        "schema": "ShortCanonicalMutationCommitV1", "version": 1,
        "phase1a_mutation_id": mutation.mutation_id,
        "claim_id": claim.claim_id, "operation": mutation.operation,
        "slot_id": mutation.slot_id,
        "competition_key": mutation.competition_key,
        "story_time": str(claim.story_time),
        "source_artifact_hash": claim.source_artifact_hash,
        "evidence_hash": evidence.evidence_hash,
        "base_authority_revision": mutation.base_authority_revision,
        "base_authority_hash": mutation.base_authority_hash,
        "authority_slice_hash": mutation.authority_slice_hash,
        "expected_current_hash": mutation.expected_current_hash,
        "proposed_value_hash": mutation.proposed_value_hash,
        "proposed_value": unit.value,
        "target_state_path": target_path,
        "canonical_fact_key": canonical_fact_key,
        "no_change": mutation.eligibility == "no_change",
        "policy_version": "short-canonical-policy-v1",
    }
    return ShortCanonicalMutationCommitV1.model_validate({
        **payload,
        "commit_mutation_id": stable_id(
            "commit-mutation", "ShortCanonicalMutationCommitV1", payload,
        ),
    })


def evaluate_short_canonical_gate(
    *, project_root: Path, project_id: str,
    inventory: MaintenanceProposalInventoryV1,
    final_source_bytes: bytes, story_state_revision: int,
    story_state_data: Mapping[str, Any],
    current_story_times: Mapping[str, str] | None = None,
    projection_diagnostics: Sequence[Mapping[str, Any]] = (),
) -> ShortCanonicalGateEvaluation:
    """Evaluate Short canonical eligibility without consulting a projection."""

    actual_authority_hash = story_state_authority_hash(story_state_data)
    story_time = short_publication_story_time(project_id, story_state_data)
    aliases = build_entity_alias_index(project_root, story_state_data)
    current_story_times = current_story_times or {}
    canonical_reasons: list[str] = []
    if not inventory.complete or inventory.lost_before_v2:
        canonical_reasons.append("predecision_inventory_incomplete")
    if inventory.base_authority_revision != story_state_revision:
        canonical_reasons.append("stale_base_revision")
    if inventory.base_authority_hash != actual_authority_hash:
        canonical_reasons.append("stale_base_authority_hash")
    if inventory.source_artifact_hash != hashlib.sha256(
        final_source_bytes
    ).hexdigest():
        canonical_reasons.append("source_hash_mismatch")
    if any(
        item.category == "unsupported_reserved" for item in inventory.units
    ):
        canonical_reasons.append("unsupported_reserved_kind")

    provisional: list[tuple[
        MaintenanceProposalUnitV1, ProposedClaimV2,
        ShadowSlotIdentityV1, str, str,
    ]] = []
    for unit in inventory.units:
        if unit.category not in {
            "character.location", "character.knowledge",
            "character.relationship",
        }:
            continue
        claim, target_path, fact_key = _claim_for_unit(
            unit, aliases=aliases, story_time=story_time.story_time,
            source_artifact_hash=inventory.source_artifact_hash,
        )
        provisional.append((
            unit, claim, resolve_shadow_slot(claim), target_path, fact_key,
        ))

    by_slot: dict[str, list[tuple[
        MaintenanceProposalUnitV1, ProposedClaimV2,
        ShadowSlotIdentityV1, str, str,
    ]]] = {}
    for item in provisional:
        by_slot.setdefault(item[2].slot_id or "slot-unknown", []).append(item)

    claims: list[ProposedClaimV2] = []
    evidence_rows: list[EvidenceEnvelopeV2] = []
    shadow_mutations: list[CanonicalMutationV1] = []
    formal_mutations: list[ShortCanonicalMutationCommitV1] = []
    v2_eligible = 0
    v2_hold = 0
    legacy_accept_v2_reject = 0
    legacy_reject_v2_accept = 0
    for slot_id in sorted(by_slot):
        group = by_slot[slot_id]
        value_hashes = {item[1].value_hash for item in group}
        if len(value_hashes) != 1:
            canonical_reasons.append("multiple_proposed_current_values")
            v2_hold += len(group)
            continue
        expected_hashes = {
            claim_value_hash(item[0].expected_current)
            for item in group if item[0].expected_current is not None
        }
        if len(expected_hashes) > 1:
            canonical_reasons.append("writer_ownership_ambiguity")
            v2_hold += len(group)
            continue
        selected = sorted(
            group,
            key=lambda item: (
                item[0].shape != "state_transition",
                item[0].evidence_text is None,
                item[0].unit_id,
            ),
        )[0]
        unit, claim, slot, target_path, fact_key = selected
        current = resolve_story_state_expected_current(
            state_data=story_state_data,
            actual_revision=story_state_revision,
            actual_authority_hash=actual_authority_hash,
            requested_revision=inventory.base_authority_revision,
            requested_authority_hash=inventory.base_authority_hash,
            claim=claim, aliases=aliases,
        )
        operation = select_short_mutation_operation(
            proposed_story_time=story_time.story_time,
            current_story_time=current_story_times.get(slot_id),
            current_exists=current["status"] == "exact",
            explicit_transition=unit.shape == "state_transition",
        )
        requested_expected = (
            claim_value_hash(unit.expected_current)
            if unit.expected_current is not None
            else current["current_hash"] if operation == "SUPERSEDE"
            else None
        )
        evidence = build_evidence_envelope(
            claim, final_source_bytes=final_source_bytes,
            declared_source_artifact_hash=inventory.source_artifact_hash,
            evidence_text=unit.evidence_text,
            base_authority_revision=inventory.base_authority_revision,
            base_authority_hash=inventory.base_authority_hash,
            covered_ranges=((0, len(final_source_bytes)),),
        )
        mutation = build_shadow_mutation(
            operation=operation, claim=claim, evidence=evidence, slot=slot,
            state_data=story_state_data,
            actual_revision=story_state_revision,
            actual_authority_hash=actual_authority_hash,
            aliases=aliases,
            requested_expected_current_hash=requested_expected,
        )
        claims.append(claim)
        evidence_rows.append(evidence)
        shadow_mutations.append(mutation)
        accepted_by_v2 = mutation.eligibility in {"eligible", "no_change"}
        if accepted_by_v2:
            v2_eligible += len(group)
            formal_mutations.append(_formal_mutation(
                mutation=mutation, claim=claim, evidence=evidence, unit=unit,
                target_path=target_path, canonical_fact_key=fact_key,
            ))
        else:
            v2_hold += len(group)
            canonical_reasons.extend(mutation.failure_codes)
        if any(
            item[0].legacy_disposition == "legacy_accepted" for item in group
        ) and not accepted_by_v2:
            legacy_accept_v2_reject += len(group)
        if any(
            item[0].legacy_disposition == "legacy_rejected" for item in group
        ) and accepted_by_v2:
            legacy_reject_v2_accept += len(group)

    unique_claims = tuple(sorted(
        {item.claim_id: item for item in claims}.values(),
        key=lambda item: item.claim_id,
    ))
    batch = make_claim_batch(
        unique_claims,
        base_authority_revision=inventory.base_authority_revision,
        base_authority_hash=inventory.base_authority_hash,
        source_artifact_hash=inventory.source_artifact_hash,
        coverage_mode=(
            "complete_source" if inventory.source_mode == "normal"
            else "window_union"
        ),
    )
    diagnostics = tuple(dict(item) for item in projection_diagnostics)
    operational_reasons = tuple(sorted({
        "projection_environment_unreconciled"
        for item in diagnostics
        if str(item.get("freshness") or "unknown") not in {
            "fresh", "not_present",
        }
    }))
    replay = {
        **predecision_replay_counts(inventory),
        "v2_eligible": v2_eligible,
        "v2_hold": v2_hold,
        "legacy_accept_v2_reject": legacy_accept_v2_reject,
        "legacy_reject_v2_accept": legacy_reject_v2_accept,
    }
    reasons = tuple(sorted(set(canonical_reasons)))
    return ShortCanonicalGateEvaluation(
        story_time=story_time, batch=batch, claims=unique_claims,
        evidence=tuple(evidence_rows),
        phase1a_mutations=tuple(shadow_mutations),
        formal_mutations=tuple(formal_mutations),
        canonical_gate_result="hold" if reasons else "eligible",
        canonical_hold_reasons=reasons,
        operational_readiness="hold" if operational_reasons else "ready",
        operational_hold_reasons=operational_reasons,
        projection_diagnostics=diagnostics,
        replay_counts=replay,
    )


def make_writer_patch(
    *, path: str, operation: PatchOperation, owner: WriterOwner,
    value: Any | None = None, mutation_id: str | None = None,
    no_change: bool = False,
) -> WriterLeafPatchV1:
    return WriterLeafPatchV1(
        path=path, operation=operation, owner=owner,
        mutation_id=mutation_id, value=value,
        value_hash=(
            canonical_sha256("WriterPatchValueV1", value)
            if operation == "set" else None
        ),
        no_change=no_change,
    )


def proposed_claim_batch_hash(batch: ProposedClaimBatchV2) -> str:
    return canonical_sha256(
        "ProposedClaimBatchV2",
        batch.model_dump(mode="json", by_alias=True),
    )


def evidence_envelope_set_hash(
    evidence: Sequence[EvidenceEnvelopeV2],
) -> str:
    return canonical_sha256(
        "EvidenceEnvelopeSetV2",
        tuple(sorted(item.evidence_hash for item in evidence)),
    )


def build_short_hold_decision(
    *, evaluation: ShortCanonicalGateEvaluation,
    inventory: MaintenanceProposalInventoryV1, candidate_hash: str,
) -> ShortCanonicalGateDecisionV1:
    reasons = tuple(sorted(set(
        evaluation.canonical_hold_reasons
        + evaluation.operational_hold_reasons
    )))
    payload = {
        "schema": "ShortCanonicalGateDecisionV1", "version": 1,
        "lane": "short_canonical_v2", "outcome": "hold",
        "canonical_gate_result": evaluation.canonical_gate_result,
        "operational_readiness": evaluation.operational_readiness,
        "hold_reasons": reasons,
        "inventory_id": inventory.inventory_id,
        "proposed_claim_batch_hash": proposed_claim_batch_hash(
            evaluation.batch
        ),
        "story_time": evaluation.story_time.story_time,
        "source_artifact_hash": inventory.source_artifact_hash,
        "base_authority_revision": inventory.base_authority_revision,
        "base_authority_hash": inventory.base_authority_hash,
        "candidate_hash": candidate_hash,
        "projection_diagnostics_hash": canonical_sha256(
            "ProjectionDiagnosticsV1", evaluation.projection_diagnostics,
        ),
        "commit_performed": False, "target_revision": None,
        "target_authority_hash": None,
    }
    return ShortCanonicalGateDecisionV1.model_validate({
        **payload,
        "decision_hash": canonical_sha256(
            "ShortCanonicalGateDecisionV1", payload,
        ),
    })


def build_short_commit_receipt(
    *, evaluation: ShortCanonicalGateEvaluation,
    target_revision: int, target_authority_hash: str,
    candidate_hash: str, writer_plan_hash: str,
    journal_frozen_input_hash: str,
) -> ShortCanonicalCommitReceiptV1:
    if (
        evaluation.canonical_gate_result != "eligible"
        or evaluation.operational_readiness != "ready"
    ):
        raise ValueError("held canonical evaluation cannot produce a receipt")
    payload = {
        "schema": "ShortCanonicalCommitReceiptV1", "version": 1,
        "lane": "short_canonical_v2", "outcome": "committed",
        "policy_version": "short-canonical-policy-v1",
        "canonical_gate_result": "eligible",
        "operational_readiness": "ready",
        "projection_diagnostics_hash": canonical_sha256(
            "ProjectionDiagnosticsV1", evaluation.projection_diagnostics,
        ),
        "story_time": evaluation.story_time.story_time,
        "source_artifact_hash": evaluation.batch.source_artifact_hash,
        "base_authority_revision": evaluation.batch.base_authority_revision,
        "base_authority_hash": evaluation.batch.base_authority_hash,
        "target_revision": target_revision,
        "target_authority_hash": target_authority_hash,
        "candidate_hash": candidate_hash,
        "proposed_claim_batch_hash": proposed_claim_batch_hash(
            evaluation.batch
        ),
        "evidence_envelope_set_hash": evidence_envelope_set_hash(
            evaluation.evidence
        ),
        "mutation_ids": tuple(sorted(
            item.commit_mutation_id for item in evaluation.formal_mutations
        )),
        "writer_plan_hash": writer_plan_hash,
        "journal_frozen_input_hash": journal_frozen_input_hash,
        "commit_performed": True, "story_state_commit_count": 1,
    }
    return ShortCanonicalCommitReceiptV1.model_validate({
        **payload,
        "receipt_hash": canonical_sha256(
            "ShortCanonicalCommitReceiptV1", payload,
        ),
    })


def _join_pointer(path: str, token: str) -> str:
    return path + "/" + _pointer_escape(token)


def _leaf_diff(base: Any, target: Any, path: str = "") -> list[tuple[str, str, Any]]:
    if isinstance(base, Mapping) and isinstance(target, Mapping):
        result: list[tuple[str, str, Any]] = []
        keys = sorted(set(base) | set(target), key=lambda item: str(item))
        for key in keys:
            child = _join_pointer(path, str(key))
            if key not in target:
                result.append((child, "remove", None))
            elif key not in base:
                if isinstance(target[key], Mapping) and target[key]:
                    result.extend(_leaf_diff({}, target[key], child))
                elif isinstance(target[key], list) and target[key]:
                    result.extend(_leaf_diff([], target[key], child))
                else:
                    result.append((child, "set", target[key]))
            else:
                result.extend(_leaf_diff(base[key], target[key], child))
        return result
    if isinstance(base, list) and isinstance(target, list):
        result = []
        common = min(len(base), len(target))
        for index in range(common):
            result.extend(_leaf_diff(
                base[index], target[index], _join_pointer(path, str(index)),
            ))
        for index in range(common, len(target)):
            result.append((_join_pointer(path, str(index)), "set", target[index]))
        for index in range(len(base) - 1, len(target) - 1, -1):
            result.append((_join_pointer(path, str(index)), "remove", None))
        return result
    if canonical_sha256("WriterComparableValueV1", base) == canonical_sha256(
        "WriterComparableValueV1", target,
    ):
        return []
    if not path:
        raise ValueError("writer plan cannot replace the StoryState root")
    return [(path, "set", target)]


def _pointer_tokens(path: str) -> tuple[str, ...]:
    def unescape(value: str) -> str:
        return value.replace("~1", "/").replace("~0", "~")
    return tuple(unescape(item) for item in path.split("/")[1:])


def _paths_overlap(left: str, right: str) -> bool:
    a, b = _pointer_tokens(left), _pointer_tokens(right)
    return a == b or a[:len(b)] == b or b[:len(a)] == a


def _apply_patch(target: Any, patch: WriterLeafPatchV1) -> None:
    tokens = _pointer_tokens(patch.path)
    cursor = target
    for token in tokens[:-1]:
        cursor = cursor[int(token)] if isinstance(cursor, list) else cursor[token]
    leaf = tokens[-1]
    if isinstance(cursor, list):
        index = int(leaf)
        if patch.operation == "remove":
            cursor.pop(index)
        elif index == len(cursor):
            cursor.append(patch.value)
        else:
            cursor[index] = patch.value
    elif patch.operation == "remove":
        del cursor[leaf]
    else:
        cursor[leaf] = patch.value


def build_short_writer_plan(
    *, base_state: Mapping[str, Any], legacy_target: Mapping[str, Any],
    v2_patches: Sequence[WriterLeafPatchV1],
) -> tuple[ShortWriterPlanV1, dict[str, Any]]:
    """Apply Legacy and V2 leaf plans once to the exact same base authority."""

    base = json.loads(json.dumps(dict(base_state), ensure_ascii=False))
    legacy = [
        make_writer_patch(
            path=path, operation=operation, owner="legacy", value=value,
        )
        for path, operation, value in _leaf_diff(base, dict(legacy_target))
    ]
    v2_by_path: dict[str, WriterLeafPatchV1] = {}
    multi_owned = 0
    for patch in v2_patches:
        if patch.owner != "canonical_v2":
            raise ValueError("V2 patch list contains a non-V2 owner")
        if patch.path in v2_by_path:
            multi_owned += 1
        else:
            v2_by_path[patch.path] = patch
    legacy = [item for item in legacy if item.path not in v2_by_path]
    combined = [*legacy, *v2_by_path.values()]
    overlaps = 0
    for index, left in enumerate(combined):
        for right in combined[index + 1:]:
            if left.path != right.path and _paths_overlap(left.path, right.path):
                overlaps += 1
    if multi_owned or overlaps:
        raise ValueError("writer plan contains overlapping ownership")

    result = json.loads(json.dumps(base, ensure_ascii=False))
    removals = sorted(
        (item for item in combined if item.operation == "remove"),
        key=lambda item: (len(_pointer_tokens(item.path)), item.path),
        reverse=True,
    )
    setters = sorted(
        (item for item in combined if item.operation == "set"),
        key=lambda item: (len(_pointer_tokens(item.path)), item.path),
    )
    for patch in [*removals, *setters]:
        if not patch.no_change:
            _apply_patch(result, patch)
    actual_diff_paths = tuple(sorted(
        path for path, _operation, _value in _leaf_diff(base, result)
    ))
    planned_changed = {
        item.path for item in combined if not item.no_change
    }
    unowned = len(set(actual_diff_paths) ^ planned_changed)
    ordered = tuple(sorted(combined, key=lambda item: item.path))
    payload = {
        "schema": "ShortWriterPlanV1", "version": 1,
        "base_authority_hash": story_state_authority_hash(base),
        "target_authority_hash": story_state_authority_hash(result),
        "patches": tuple(
            item.model_dump(mode="json", by_alias=True) for item in ordered
        ),
        "actual_diff_paths": actual_diff_paths,
        "unowned": unowned, "multi_owned": multi_owned,
        "parent_child_overlaps": overlaps,
    }
    plan = ShortWriterPlanV1.model_validate({
        **payload, "plan_hash": canonical_sha256("ShortWriterPlanV1", payload),
    })
    return plan, result
