from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)


MAINTENANCE_WINDOW_CONTRACT_VERSION = "maintenance-window-contract-v1"
MAINTENANCE_WINDOW_RECEIPT_VERSION = "maintenance-window-receipt-v1"
MAINTENANCE_REDUCTION_VERSION = "maintenance-reduction-v1"


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    ).encode("utf-8")).hexdigest()


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, str_strip_whitespace=True,
    )


NonEmptyText = Annotated[StrictStr, Field(min_length=1)]
Sha256Text = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class MaintenanceWindowContractV1(_StrictModel):
    version: Literal["maintenance-window-contract-v1"]
    window_id: NonEmptyText
    sequence: NonEmptyText
    manuscript_sha256: Sha256Text
    source_integrity_sha256: Sha256Text | None = None
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text_sha256: Sha256Text
    entry_state_sha256: Sha256Text

    @model_validator(mode="after")
    def span_is_nonempty(self) -> "MaintenanceWindowContractV1":
        if self.end <= self.start:
            raise ValueError("maintenance window span must be non-empty")
        return self


class MaintenanceEvidenceSpanV1(_StrictModel):
    quote: NonEmptyText
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    sha256: Sha256Text

    @model_validator(mode="after")
    def span_matches_quote(self) -> "MaintenanceEvidenceSpanV1":
        if self.end - self.start != len(self.quote):
            raise ValueError("maintenance evidence span length is stale")
        if hashlib.sha256(self.quote.encode("utf-8")).hexdigest() != self.sha256:
            raise ValueError("maintenance evidence hash is stale")
        return self


class MaintenanceFactUnitV1(_StrictModel):
    key: NonEmptyText
    value: Any
    evidence: MaintenanceEvidenceSpanV1

    @field_validator("value")
    @classmethod
    def value_is_nonempty(cls, value: object) -> object:
        if value in (None, "", [], {}):
            raise ValueError("maintenance fact value is empty")
        return value


class MaintenanceStateDeltaV1(_StrictModel):
    character: NonEmptyText
    field: NonEmptyText
    value: Any
    evidence: MaintenanceEvidenceSpanV1

    @field_validator("value")
    @classmethod
    def value_is_nonempty(cls, value: object) -> object:
        if value in (None, "", [], {}):
            raise ValueError("maintenance state delta value is empty")
        return value


class MaintenanceStateTransitionV1(_StrictModel):
    character: NonEmptyText
    field: NonEmptyText
    from_value: Any = Field(alias="from")
    to: Any
    evidence: MaintenanceEvidenceSpanV1

    @field_validator("from_value", "to")
    @classmethod
    def endpoints_are_nonempty(cls, value: object) -> object:
        if value in (None, "", [], {}):
            raise ValueError("maintenance transition endpoint is empty")
        return value


class MaintenanceNamedUnitV1(_StrictModel):
    key: NonEmptyText
    value: Any
    evidence: MaintenanceEvidenceSpanV1

    @field_validator("value")
    @classmethod
    def value_is_nonempty(cls, value: object) -> object:
        if value in (None, "", [], {}):
            raise ValueError("maintenance semantic unit value is empty")
        return value


class MaintenanceWindowReceiptV1(_StrictModel):
    version: Literal["maintenance-window-receipt-v1"]
    facts: list[MaintenanceFactUnitV1]
    state_deltas: list[MaintenanceStateDeltaV1]
    state_transitions: list[MaintenanceStateTransitionV1]
    world_rules: list[MaintenanceNamedUnitV1]
    timeline: list[MaintenanceNamedUnitV1]


class MaintenanceWindowEnvelopeV1(_StrictModel):
    contract: MaintenanceWindowContractV1
    receipt: MaintenanceWindowReceiptV1
    receipt_sha256: Sha256Text
    adapter_audit: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def receipt_hash_is_bound(self) -> "MaintenanceWindowEnvelopeV1":
        actual = canonical_sha256(self.receipt.model_dump(
            mode="json", by_alias=True,
        ))
        if actual != self.receipt_sha256:
            raise ValueError("maintenance receipt hash is stale")
        return self


class MaintenanceReductionV1(_StrictModel):
    version: Literal["maintenance-reduction-v1"]
    manuscript_sha256: Sha256Text
    source_state_sha256: Sha256Text
    window_envelopes: list[MaintenanceWindowEnvelopeV1] = Field(min_length=1)
    window_receipt_sha256: list[Sha256Text] = Field(min_length=1)
    coverage_spans: list[list[int]] = Field(min_length=1)
    canon: dict[str, Any]
    confirmed_facts: list[dict[str, Any]]
    reduction_sha256: Sha256Text

    @model_validator(mode="after")
    def reduction_hash_is_bound(self) -> "MaintenanceReductionV1":
        if any(
            len(span) != 2
            or not all(isinstance(value, int) and not isinstance(value, bool) for value in span)
            for span in self.coverage_spans
        ):
            raise ValueError("maintenance reduction coverage shape is invalid")
        unsigned = self.model_dump(
            mode="json", by_alias=True, exclude={"reduction_sha256"},
        )
        if canonical_sha256(unsigned) != self.reduction_sha256:
            raise ValueError("maintenance reduction hash is stale")
        return self


class MaintenanceWindowBundleV1(_StrictModel):
    """Runtime-only recursive split result; model routes never author it."""

    version: Literal["maintenance-window-bundle-v1"]
    parent_contract: MaintenanceWindowContractV1
    source_state_sha256: Sha256Text
    envelopes: list[MaintenanceWindowEnvelopeV1] = Field(min_length=1)
    canon: dict[str, Any]
    confirmed_facts: list[dict[str, Any]]
    bundle_sha256: Sha256Text

    @model_validator(mode="after")
    def bundle_hash_is_bound(self) -> "MaintenanceWindowBundleV1":
        unsigned = self.model_dump(
            mode="json", by_alias=True, exclude={"bundle_sha256"},
        )
        if canonical_sha256(unsigned) != self.bundle_sha256:
            raise ValueError("maintenance window bundle hash is stale")
        return self


def _window_id(manuscript_sha256: str, start: int, end: int) -> str:
    return "MW-" + hashlib.sha256(
        f"{manuscript_sha256}:{start}:{end}".encode("ascii"),
    ).hexdigest()[:16]


def build_maintenance_window_contracts(
    manuscript: str,
    *,
    entry_state_sha256: str,
    target_characters: int,
    overlap_characters: int = 240,
    source_integrity_sha256: str | None = None,
) -> list[MaintenanceWindowContractV1]:
    """Build paragraph-aligned windows whose union covers every source byte."""

    if not manuscript:
        raise ValueError("maintenance manuscript is empty")
    if target_characters < 400:
        raise ValueError("maintenance window target is too small")
    overlap = max(0, min(overlap_characters, target_characters // 4))
    manuscript_sha256 = hashlib.sha256(manuscript.encode("utf-8")).hexdigest()
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(manuscript):
        wanted = min(len(manuscript), start + target_characters)
        end = wanted
        if wanted < len(manuscript):
            lower = start + max(1, target_characters // 2)
            candidates = [
                manuscript.rfind("\n\n", lower, wanted + 1),
                manuscript.rfind("。", lower, wanted + 1),
                manuscript.rfind("！", lower, wanted + 1),
                manuscript.rfind("？", lower, wanted + 1),
                manuscript.rfind(".", lower, wanted + 1),
            ]
            boundary = max(candidates)
            if boundary >= lower:
                end = boundary + (2 if manuscript.startswith("\n\n", boundary) else 1)
        if end <= start:
            end = wanted
        spans.append((start, end))
        if end >= len(manuscript):
            break
        start = max(start + 1, end - overlap)

    contracts = [
        MaintenanceWindowContractV1(
            version=MAINTENANCE_WINDOW_CONTRACT_VERSION,
            window_id=_window_id(manuscript_sha256, start, end),
            sequence=f"{index:06d}",
            manuscript_sha256=manuscript_sha256,
            source_integrity_sha256=source_integrity_sha256,
            start=start,
            end=end,
            text_sha256=hashlib.sha256(
                manuscript[start:end].encode("utf-8"),
            ).hexdigest(),
            entry_state_sha256=entry_state_sha256,
        )
        for index, (start, end) in enumerate(spans, 1)
    ]
    validate_maintenance_window_coverage(contracts, manuscript)
    return contracts


def bisect_maintenance_window_contract(
    contract: MaintenanceWindowContractV1,
    manuscript: str,
    *,
    entry_state_sha256: str,
) -> tuple[MaintenanceWindowContractV1, MaintenanceWindowContractV1]:
    """Split one indivisible request without dropping or inventing source text."""

    validate_maintenance_window_contract(contract, manuscript)
    if contract.end - contract.start < 2:
        raise ValueError("maintenance authority window cannot be split further")
    midpoint = (contract.start + contract.end) // 2
    search_start = max(contract.start + 1, midpoint - 240)
    search_end = min(contract.end - 1, midpoint + 240)
    boundaries = [
        manuscript.find(marker, search_start, search_end)
        for marker in ("\n\n", "。", "！", "？", ".")
    ]
    valid = [value for value in boundaries if search_start <= value < search_end]
    split = min(valid, key=lambda value: abs(value - midpoint)) + 1 if valid else midpoint
    if split <= contract.start or split >= contract.end:
        raise ValueError("maintenance authority window has no safe split point")

    def make(start: int, end: int, branch: int) -> MaintenanceWindowContractV1:
        return MaintenanceWindowContractV1(
            version=MAINTENANCE_WINDOW_CONTRACT_VERSION,
            window_id=_window_id(contract.manuscript_sha256, start, end),
            sequence=f"{contract.sequence}.{branch}",
            manuscript_sha256=contract.manuscript_sha256,
            source_integrity_sha256=contract.source_integrity_sha256,
            start=start,
            end=end,
            text_sha256=hashlib.sha256(
                manuscript[start:end].encode("utf-8"),
            ).hexdigest(),
            entry_state_sha256=entry_state_sha256,
        )

    return make(contract.start, split, 0), make(split, contract.end, 1)


def validate_maintenance_window_contract(
    contract: MaintenanceWindowContractV1,
    manuscript: str,
) -> None:
    manuscript_sha256 = hashlib.sha256(manuscript.encode("utf-8")).hexdigest()
    if contract.manuscript_sha256 != manuscript_sha256:
        raise ValueError("maintenance window manuscript authority is stale")
    if contract.end > len(manuscript):
        raise ValueError("maintenance window span exceeds manuscript")
    text = manuscript[contract.start:contract.end]
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != contract.text_sha256:
        raise ValueError("maintenance window text authority is stale")
    if contract.window_id != _window_id(
        manuscript_sha256, contract.start, contract.end,
    ):
        raise ValueError("maintenance window identity is stale")


def validate_maintenance_window_coverage(
    contracts: Sequence[MaintenanceWindowContractV1],
    manuscript: str,
) -> None:
    if not contracts:
        raise ValueError("maintenance window coverage is empty")
    ordered = sorted(contracts, key=lambda item: (item.start, item.end, item.window_id))
    covered_end = 0
    for contract in ordered:
        validate_maintenance_window_contract(contract, manuscript)
        if contract.start > covered_end:
            raise ValueError("maintenance window coverage contains a gap")
        covered_end = max(covered_end, contract.end)
    if ordered[0].start != 0 or covered_end != len(manuscript):
        raise ValueError("maintenance windows do not cover the complete manuscript")


def _evidence_from_value(
    value: object,
    *,
    contract: MaintenanceWindowContractV1,
    manuscript: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if isinstance(value, Mapping):
        quote = str(value.get("quote") or "").strip()
        if quote and all(key in value for key in ("start", "end", "sha256")):
            evidence = MaintenanceEvidenceSpanV1.model_validate(value)
            _validate_evidence(evidence, contract, manuscript)
            return evidence.model_dump(mode="json"), None
    else:
        quote = str(value or "").strip()
    if not quote:
        raise ValueError("maintenance evidence quote is empty")
    window_text = manuscript[contract.start:contract.end]
    first = window_text.find(quote)
    if first < 0 or window_text.find(quote, first + 1) >= 0:
        raise ValueError("maintenance evidence must be a unique exact window quote")
    start = contract.start + first
    evidence = MaintenanceEvidenceSpanV1(
        quote=quote,
        start=start,
        end=start + len(quote),
        sha256=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
    )
    return evidence.model_dump(mode="json"), {
        "adapter": "unique-exact-quote-to-evidence-span-v1",
        "window_id": contract.window_id,
        "quote_sha256": evidence.sha256,
    }


def _validate_evidence(
    evidence: MaintenanceEvidenceSpanV1,
    contract: MaintenanceWindowContractV1,
    manuscript: str,
) -> None:
    if evidence.start < contract.start or evidence.end > contract.end:
        raise ValueError("maintenance evidence is outside its authority window")
    if manuscript[evidence.start:evidence.end] != evidence.quote:
        raise ValueError("maintenance evidence does not match manuscript bytes")


def _semantic_unit(
    raw: object,
    *,
    kind: str,
    contract: MaintenanceWindowContractV1,
    manuscript: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if isinstance(raw, str):
        key = f"{kind}." + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        evidence, audit = _evidence_from_value(
            raw, contract=contract, manuscript=manuscript,
        )
        return {"key": key, "value": raw, "evidence": evidence}, audit
    if not isinstance(raw, Mapping):
        raise ValueError(f"maintenance {kind} unit must be text or an object")
    value = raw.get("value", raw.get("fact", raw.get("event", raw.get("rule"))))
    key = str(
        raw.get("key") or raw.get("fact_key") or raw.get("event_key")
        or raw.get("rule_key") or ""
    ).strip()
    if not key and value not in (None, "", [], {}):
        key = f"{kind}." + canonical_sha256(value)[:16]
    evidence_source = raw.get("evidence")
    if evidence_source in (None, "") and isinstance(value, str):
        evidence_source = value
    evidence, audit = _evidence_from_value(
        evidence_source, contract=contract, manuscript=manuscript,
    )
    return {"key": key, "value": value, "evidence": evidence}, audit


def adapt_maintenance_window_payload(
    payload: object,
    *,
    contract: MaintenanceWindowContractV1,
    manuscript: str,
) -> MaintenanceWindowEnvelopeV1:
    """Normalize only provably unique legacy evidence into the v1 receipt."""

    validate_maintenance_window_contract(contract, manuscript)
    if not isinstance(payload, Mapping):
        raise ValueError("maintenance window receipt must be an object")
    allowed = {
        "version", "facts", "state_deltas", "state_transitions",
        "world_rules", "timeline",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            "maintenance window receipt contains unknown fields: "
            + ",".join(sorted(str(item) for item in unknown))
        )
    audits: list[dict[str, Any]] = []
    normalized: dict[str, Any] = {
        "version": MAINTENANCE_WINDOW_RECEIPT_VERSION,
        "facts": [], "state_deltas": [], "state_transitions": [],
        "world_rules": [], "timeline": [],
    }
    for raw in payload.get("facts", []) or []:
        unit, audit = _semantic_unit(
            raw, kind="fact", contract=contract, manuscript=manuscript,
        )
        normalized["facts"].append(unit)
        if audit:
            audits.append(audit)
    for raw in payload.get("world_rules", []) or []:
        unit, audit = _semantic_unit(
            raw, kind="world-rule", contract=contract, manuscript=manuscript,
        )
        normalized["world_rules"].append(unit)
        if audit:
            audits.append(audit)
    for raw in payload.get("timeline", []) or []:
        unit, audit = _semantic_unit(
            raw, kind="timeline", contract=contract, manuscript=manuscript,
        )
        normalized["timeline"].append(unit)
        if audit:
            audits.append(audit)
    for field in ("state_deltas", "state_transitions"):
        values = payload.get(field, []) or []
        if not isinstance(values, list):
            raise ValueError(f"maintenance {field} must be an array")
        for raw in values:
            if not isinstance(raw, Mapping):
                raise ValueError(f"maintenance {field} unit must be an object")
            evidence, audit = _evidence_from_value(
                raw.get("evidence"), contract=contract, manuscript=manuscript,
            )
            unit = {
                "character": raw.get("character"),
                "field": raw.get("field"),
                "evidence": evidence,
            }
            if field == "state_deltas":
                unit["value"] = raw.get("value")
            else:
                unit["from"] = raw.get("from")
                unit["to"] = raw.get("to")
            normalized[field].append(unit)
            if audit:
                audits.append(audit)
    receipt = MaintenanceWindowReceiptV1.model_validate(normalized)
    for collection in (
        receipt.facts, receipt.state_deltas, receipt.state_transitions,
        receipt.world_rules, receipt.timeline,
    ):
        for unit in collection:
            _validate_evidence(unit.evidence, contract, manuscript)
    receipt_payload = receipt.model_dump(mode="json", by_alias=True)
    return MaintenanceWindowEnvelopeV1(
        contract=contract,
        receipt=receipt,
        receipt_sha256=canonical_sha256(receipt_payload),
        adapter_audit=audits,
    )


def maintenance_window_prompt(
    contract: MaintenanceWindowContractV1,
    manuscript: str,
    *,
    entry_authority: Mapping[str, object],
    repair: Mapping[str, object] | None = None,
) -> str:
    validate_maintenance_window_contract(contract, manuscript)
    payload = {
        "schema": "maintenance-window-request-v1",
        "contract": contract.model_dump(mode="json"),
        "entry_authority": dict(entry_authority),
        "window_text": manuscript[contract.start:contract.end],
        "output_contract": {
            "version": MAINTENANCE_WINDOW_RECEIPT_VERSION,
            "facts": [{"key": "stable key", "value": "durable fact", "evidence": "unique exact quote"}],
            "state_deltas": [{"character": "name", "field": "dotted.new.path", "value": "final value", "evidence": "unique exact quote"}],
            "state_transitions": [{"character": "name", "field": "dotted.existing.path", "from": "entry value", "to": "final value", "evidence": "unique exact quote"}],
            "world_rules": [{"key": "stable key", "value": "rule", "evidence": "unique exact quote"}],
            "timeline": [{"key": "stable key", "value": "event", "evidence": "unique exact quote"}],
        },
        "rules": [
            "Return exactly one JSON object and no prose.",
            "Report only semantic units proved by this complete window.",
            "Every evidence quote must occur exactly once in window_text.",
            "Omission never deletes entry authority; do not echo unchanged state.",
            "Use state_transitions for an existing scalar and state_deltas only for a new path.",
        ],
        **({"repair": dict(repair)} if repair else {}),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def receipt_to_maintenance_candidate(
    envelope: MaintenanceWindowEnvelopeV1,
) -> dict[str, Any]:
    """Project a validated semantic receipt into the shared canonical adapter."""

    state: dict[str, Any] = {}

    def set_path(character: str, field: str, value: object) -> None:
        cursor = state.setdefault(character, {})
        parts = [part for part in field.split(".") if part]
        if not parts:
            raise ValueError("maintenance state path is empty")
        for part in parts[:-1]:
            child = cursor.setdefault(part, {})
            if not isinstance(child, dict):
                raise ValueError("maintenance state path collides with a scalar")
            cursor = child
        existing = cursor.get(parts[-1])
        if existing is not None and canonical_sha256(existing) != canonical_sha256(value):
            raise ValueError("maintenance receipt contains divergent state values")
        cursor[parts[-1]] = value

    for unit in envelope.receipt.state_deltas:
        set_path(unit.character, unit.field, unit.value)
    for unit in envelope.receipt.state_transitions:
        set_path(unit.character, unit.field, unit.to)
    return {
        "facts": [
            {"key": unit.key, "value": unit.value}
            for unit in envelope.receipt.facts
        ],
        "state": state,
        "state_transitions": [
            {
                "character": unit.character,
                "field": unit.field,
                "from": unit.from_value,
                "to": unit.to,
                "evidence": unit.evidence.quote,
            }
            for unit in envelope.receipt.state_transitions
        ],
        "world_rules": [unit.value for unit in envelope.receipt.world_rules],
        "timeline": [unit.value for unit in envelope.receipt.timeline],
    }


def project_accepted_maintenance_envelope(
    envelope: MaintenanceWindowEnvelopeV1,
    safe_candidate: Mapping[str, object],
    *,
    conflicts: Sequence[Mapping[str, object]] = (),
) -> MaintenanceWindowEnvelopeV1:
    """Bind only Runtime-accepted units while retaining rejection provenance."""

    safe_facts = {
        (str(item.get("key") or item.get("fact_key") or ""), canonical_sha256(
            item.get("value", item.get("fact")),
        ))
        for item in (safe_candidate.get("facts") or [])
        if isinstance(item, Mapping)
    }
    safe_transitions = {
        (
            str(item.get("character") or ""), str(item.get("field") or ""),
            canonical_sha256(item.get("from")), canonical_sha256(item.get("to")),
        )
        for item in (safe_candidate.get("state_transitions") or [])
        if isinstance(item, Mapping)
    }
    safe_world = {
        canonical_sha256(item) for item in (safe_candidate.get("world_rules") or [])
    }
    safe_timeline = {
        canonical_sha256(item) for item in (safe_candidate.get("timeline") or [])
    }
    safe_state = safe_candidate.get("state")
    safe_state = safe_state if isinstance(safe_state, Mapping) else {}

    def state_value(character: str, field: str) -> tuple[bool, object]:
        cursor: object = safe_state.get(character)
        if cursor is None:
            return False, None
        for part in [item for item in field.split(".") if item]:
            if not isinstance(cursor, Mapping) or part not in cursor:
                return False, None
            cursor = cursor[part]
        return True, cursor

    receipt = envelope.receipt
    projected = MaintenanceWindowReceiptV1(
        version=MAINTENANCE_WINDOW_RECEIPT_VERSION,
        facts=[
            unit for unit in receipt.facts
            if (unit.key, canonical_sha256(unit.value)) in safe_facts
        ],
        state_deltas=[
            unit for unit in receipt.state_deltas
            if (
                (resolved := state_value(unit.character, unit.field))[0]
                and canonical_sha256(resolved[1]) == canonical_sha256(unit.value)
            )
        ],
        state_transitions=[
            unit for unit in receipt.state_transitions
            if (
                unit.character, unit.field,
                canonical_sha256(unit.from_value), canonical_sha256(unit.to),
            ) in safe_transitions
        ],
        world_rules=[
            unit for unit in receipt.world_rules
            if canonical_sha256(unit.value) in safe_world
        ],
        timeline=[
            unit for unit in receipt.timeline
            if canonical_sha256(unit.value) in safe_timeline
        ],
    )
    projected_payload = projected.model_dump(mode="json", by_alias=True)
    audit = list(envelope.adapter_audit)
    if conflicts:
        audit.append({
            "adapter": "runtime-accepted-unit-projection-v1",
            "rejected_receipt_sha256": envelope.receipt_sha256,
            "rejected_unit_count": len(conflicts),
            "conflict_sha256": canonical_sha256([dict(item) for item in conflicts]),
        })
    return MaintenanceWindowEnvelopeV1(
        contract=envelope.contract,
        receipt=projected,
        receipt_sha256=canonical_sha256(projected_payload),
        adapter_audit=audit,
    )


def build_maintenance_reduction(
    *,
    manuscript: str,
    source_state_sha256: str,
    envelopes: Sequence[MaintenanceWindowEnvelopeV1],
    canon: Mapping[str, object],
    confirmed_facts: Sequence[Mapping[str, object]],
) -> MaintenanceReductionV1:
    contracts = [item.contract for item in envelopes]
    validate_maintenance_window_coverage(contracts, manuscript)
    payload = {
        "version": MAINTENANCE_REDUCTION_VERSION,
        "manuscript_sha256": hashlib.sha256(
            manuscript.encode("utf-8"),
        ).hexdigest(),
        "source_state_sha256": source_state_sha256,
        "window_envelopes": [
            item.model_dump(mode="json", by_alias=True)
            for item in sorted(envelopes, key=lambda item: item.contract.sequence)
        ],
        "window_receipt_sha256": [
            item.receipt_sha256 for item in sorted(
                envelopes, key=lambda item: item.contract.sequence,
            )
        ],
        "coverage_spans": [
            [item.start, item.end] for item in sorted(
                contracts, key=lambda item: item.sequence,
            )
        ],
        "canon": dict(canon),
        "confirmed_facts": [dict(item) for item in confirmed_facts],
    }
    return MaintenanceReductionV1(
        **payload,
        reduction_sha256=canonical_sha256(payload),
    )


def build_maintenance_window_bundle(
    *,
    parent_contract: MaintenanceWindowContractV1,
    source_state_sha256: str,
    envelopes: Sequence[MaintenanceWindowEnvelopeV1],
    canon: Mapping[str, object],
    confirmed_facts: Sequence[Mapping[str, object]],
    manuscript: str,
) -> MaintenanceWindowBundleV1:
    validate_maintenance_window_contract(parent_contract, manuscript)
    ordered = sorted(envelopes, key=lambda item: item.contract.sequence)
    covered_end = parent_contract.start
    for envelope in ordered:
        validate_maintenance_window_contract(envelope.contract, manuscript)
        if envelope.contract.start > covered_end:
            raise ValueError("maintenance split bundle contains a coverage gap")
        if (
            envelope.contract.start < parent_contract.start
            or envelope.contract.end > parent_contract.end
        ):
            raise ValueError("maintenance split child escapes parent authority")
        covered_end = max(covered_end, envelope.contract.end)
    if not ordered or ordered[0].contract.start != parent_contract.start or (
        covered_end != parent_contract.end
    ):
        raise ValueError("maintenance split bundle does not cover its parent")
    payload = {
        "version": "maintenance-window-bundle-v1",
        "parent_contract": parent_contract.model_dump(mode="json"),
        "source_state_sha256": source_state_sha256,
        "envelopes": [item.model_dump(mode="json", by_alias=True) for item in ordered],
        "canon": dict(canon),
        "confirmed_facts": [dict(item) for item in confirmed_facts],
    }
    return MaintenanceWindowBundleV1(
        **payload,
        bundle_sha256=canonical_sha256(payload),
    )


def validate_maintenance_window_bundle(
    payload: object,
    *,
    parent_contract: MaintenanceWindowContractV1,
    manuscript: str,
    source_state_sha256: str,
) -> MaintenanceWindowBundleV1:
    bundle = MaintenanceWindowBundleV1.model_validate(payload)
    if bundle.parent_contract != parent_contract:
        raise ValueError("maintenance split bundle parent authority is stale")
    if bundle.source_state_sha256 != source_state_sha256:
        raise ValueError("maintenance split bundle StoryState authority is stale")
    # Rebuilding proves both the recursive coverage and the canonical bundle hash.
    build_maintenance_window_bundle(
        parent_contract=parent_contract,
        source_state_sha256=source_state_sha256,
        envelopes=bundle.envelopes,
        canon=bundle.canon,
        confirmed_facts=bundle.confirmed_facts,
        manuscript=manuscript,
    )
    return bundle


def validate_maintenance_reduction(
    payload: object,
    *,
    manuscript: str,
    source_state_sha256: str,
) -> MaintenanceReductionV1:
    reduction = MaintenanceReductionV1.model_validate(payload)
    if reduction.manuscript_sha256 != hashlib.sha256(
        manuscript.encode("utf-8"),
    ).hexdigest():
        raise ValueError("maintenance reduction manuscript authority is stale")
    if reduction.source_state_sha256 != source_state_sha256:
        raise ValueError("maintenance reduction StoryState authority is stale")
    ordered_envelopes = sorted(
        reduction.window_envelopes, key=lambda item: item.contract.sequence,
    )
    expected_hashes = [item.receipt_sha256 for item in ordered_envelopes]
    if reduction.window_receipt_sha256 != expected_hashes:
        raise ValueError("maintenance reduction receipt ledger is stale")
    if reduction.coverage_spans != [
        [item.contract.start, item.contract.end] for item in ordered_envelopes
    ]:
        raise ValueError("maintenance reduction span ledger is stale")
    for envelope in ordered_envelopes:
        validate_maintenance_window_contract(envelope.contract, manuscript)
    covered_end = 0
    for start, end in sorted(reduction.coverage_spans):
        if start > covered_end or end <= start or end > len(manuscript):
            raise ValueError("maintenance reduction coverage is invalid")
        covered_end = max(covered_end, end)
    if not reduction.coverage_spans or min(
        start for start, _end in reduction.coverage_spans
    ) != 0 or covered_end != len(manuscript):
        raise ValueError("maintenance reduction does not cover the manuscript")
    return reduction
