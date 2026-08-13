"""Short-only canonical promotion contracts and deterministic adapters.

Phase 1B keeps model/protocol handling in the existing Maintenance runtime.
This module begins at the normalized, structurally valid proposal inventory and
never invokes a model, reads a projection as authority, or writes StoryState.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_flywheel.canonical_shadow import (
    CONTROLLED_RELATIONSHIP_PREDICATES,
    canonical_sha256,
    stable_id,
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
