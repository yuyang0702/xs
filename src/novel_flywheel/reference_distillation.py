from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from typing import Annotated, Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from novel_flywheel.context_policy import estimate_input_tokens


class SourceUseMode(StrEnum):
    SELF_AUTHORED = "self_authored"
    LICENSED = "licensed"
    REFERENCE_MECHANISM = "reference_mechanism"
    REFERENCE_STYLE = "reference_style"
    COMPETITOR_RISK_ONLY = "competitor_risk_only"


CONTENT_TYPE_USE_MODE = {
    "reference_work": SourceUseMode.REFERENCE_MECHANISM,
    "popular_sample": SourceUseMode.REFERENCE_STYLE,
    "writing_tutorial": SourceUseMode.REFERENCE_MECHANISM,
    "competitor_work": SourceUseMode.COMPETITOR_RISK_ONLY,
    "platform_rule": SourceUseMode.LICENSED,
}

NonBlankText = Annotated[
    str, StringConstraints(strip_whitespace=True, strict=True, min_length=1),
]
DispositionReasonText = Annotated[
    str, StringConstraints(strip_whitespace=True, strict=True, min_length=8),
]
SemanticPointer = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, strict=True, pattern=r"^/(mechanisms|attraction_map|style_profile)(/.*)?$",
    ),
]


class ReferenceProvenanceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: int = 1
    source_id: NonBlankText
    version_id: NonBlankText
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    use_mode: SourceUseMode
    license_assertion: NonBlankText = "unknown"


class DistillationItemV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    item_id: NonBlankText
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    payload: dict[str, Any]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_item(self) -> "DistillationItemV1":
        if self.source_end <= self.source_start:
            raise ValueError("distillation item range must be non-empty")
        if canonical_sha256(self.payload) != self.payload_sha256:
            raise ValueError("distillation item payload hash is stale")
        return self


class DistillationRegionV1(BaseModel):
    """One resumable exact-coverage map/reduce packet."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: int = 1
    level: int = Field(ge=0)
    region_index: int = Field(ge=0)
    child_ids: list[NonBlankText] = Field(min_length=1)
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payloads: list[dict[str, Any]] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_region(self) -> "DistillationRegionV1":
        if len(self.child_ids) != len(self.payloads):
            raise ValueError("distillation region child manifest is incomplete")
        if len(self.child_ids) != len(set(self.child_ids)):
            raise ValueError("distillation region repeats a child")
        expected = canonical_sha256({
            "level": self.level,
            "child_ids": self.child_ids,
            "payloads": self.payloads,
            "source_range": [self.source_start, self.source_end],
        })
        if expected != self.input_sha256:
            raise ValueError("distillation region authority hash is stale")
        return self


class DistillationChildDispositionV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    child_id: NonBlankText
    disposition: Literal["promoted", "no_transferable_claim"]
    reason: DispositionReasonText


class DistillationChildAttributionV2(BaseModel):
    """Typed proof that a promoted child survives in the aggregate output."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    child_id: NonBlankText
    relation: Literal["claim", "uncertainty", "merged", "superseded"]
    semantic_path: SemanticPointer | None = None
    related_child_ids: list[NonBlankText] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_relation_shape(self) -> "DistillationChildAttributionV2":
        if self.relation in {"claim", "uncertainty"}:
            if self.semantic_path is None or self.related_child_ids:
                raise ValueError("claim attribution requires one semantic path only")
        elif self.semantic_path is not None or not self.related_child_ids:
            raise ValueError("merged attribution requires related child identities only")
        if self.child_id in self.related_child_ids:
            raise ValueError("distillation attribution cannot reference itself")
        return self


class DistillationReceiptV2(BaseModel):
    """Model semantics plus an exact Runtime-verifiable child disposition ledger."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[2] = 2
    covered_child_ids: list[NonBlankText] = Field(min_length=1)
    child_dispositions: list[DistillationChildDispositionV2] = Field(min_length=1)
    child_attributions: list[DistillationChildAttributionV2] = Field(
        default_factory=list,
    )
    semantic: dict[str, Any]


def validate_distillation_receipt(
    region: DistillationRegionV1, payload: object,
) -> dict[str, Any]:
    receipt = DistillationReceiptV2.model_validate(payload)
    if receipt.covered_child_ids != region.child_ids:
        raise ValueError("distillation receipt child coverage mismatch")
    disposition_ids = [item.child_id for item in receipt.child_dispositions]
    if disposition_ids != region.child_ids or len(disposition_ids) != len(set(disposition_ids)):
        raise ValueError("distillation receipt disposition coverage mismatch")
    promoted = [
        item.child_id for item in receipt.child_dispositions
        if item.disposition == "promoted"
    ]
    if promoted and not _has_semantic_value(receipt.semantic):
        raise ValueError("promoted distillation children require non-empty semantics")
    _validate_promoted_child_attribution(receipt, promoted)
    for child_payload, disposition in zip(
        region.payloads, receipt.child_dispositions, strict=True,
    ):
        inherited_semantic = (
            child_payload.get("semantic")
            if isinstance(child_payload, dict)
            and isinstance(child_payload.get("runtime_coverage"), dict)
            else None
        )
        if (
            _has_semantic_value(inherited_semantic)
            and disposition.disposition != "promoted"
        ):
            raise ValueError(
                "previously promoted distillation semantics cannot be discarded"
            )
    return receipt.semantic


def _validate_promoted_child_attribution(
    receipt: DistillationReceiptV2, promoted: list[str],
) -> None:
    promoted_set = set(promoted)
    attributed_ids = [item.child_id for item in receipt.child_attributions]
    if (
        len(attributed_ids) != len(promoted)
        or set(attributed_ids) != promoted_set
    ):
        raise ValueError(
            "promoted children require exact one-to-one semantic attribution"
        )

    anchors: set[str] = set()
    anchor_paths: set[str] = set()
    relationships: dict[str, set[str]] = {child_id: set() for child_id in promoted}
    for attribution in receipt.child_attributions:
        if attribution.relation in {"claim", "uncertainty"}:
            assert attribution.semantic_path is not None
            semantic_value = _resolve_semantic_pointer(
                receipt.semantic, attribution.semantic_path,
            )
            if not _has_semantic_value(semantic_value):
                raise ValueError("distillation attribution semantic path is empty")
            if (
                attribution.relation == "uncertainty"
                and "uncertaint" not in attribution.semantic_path.casefold()
            ):
                raise ValueError("uncertainty attribution must target an uncertainty path")
            if attribution.semantic_path in anchor_paths:
                raise ValueError(
                    "direct distillation attributions require unique semantic paths"
                )
            anchor_paths.add(attribution.semantic_path)
            anchors.add(attribution.child_id)
        else:
            related = set(attribution.related_child_ids)
            if not related.issubset(promoted_set):
                raise ValueError("distillation attribution references an unpromoted child")
            relationships[attribution.child_id].update(related)

    visited: set[str] = set()

    def reject_cycle(child_id: str, active: set[str]) -> None:
        if child_id in active:
            raise ValueError("distillation attribution graph cannot contain a cycle")
        if child_id in visited:
            return
        for related_id in relationships.get(child_id, set()):
            reject_cycle(related_id, active | {child_id})
        visited.add(child_id)

    for child_id in promoted:
        reject_cycle(child_id, set())

    def reaches_anchor(child_id: str, active: set[str]) -> bool:
        if child_id in anchors:
            return True
        if child_id in active:
            return False
        return any(
            reaches_anchor(related_id, active | {child_id})
            for related_id in relationships.get(child_id, set())
        )

    uncovered = [
        child_id for child_id in promoted
        if not reaches_anchor(child_id, set())
    ]
    if uncovered:
        raise ValueError("promoted distillation child lacks typed semantic attribution")


def _resolve_semantic_pointer(semantic: dict[str, Any], pointer: str) -> object:
    current: object = semantic
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdecimal() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ValueError("distillation attribution semantic path does not exist")
    return current


def _has_semantic_value(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_semantic_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_semantic_value(item) for item in value)
    return value not in {None, False}


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str,
    ).encode("utf-8")).hexdigest()


def source_use_mode(content_type: str) -> SourceUseMode:
    return CONTENT_TYPE_USE_MODE.get(
        str(content_type or "").strip(), SourceUseMode.REFERENCE_MECHANISM,
    )


def leaf_distillation_items(claims: Iterable[dict[str, Any]]) -> list[DistillationItemV1]:
    result: list[DistillationItemV1] = []
    for position, claim in enumerate(claims):
        data = dict(claim.get("data") or claim)
        index = int(data.get("window") or data.get("index") or position + 1)
        start = int(data.get("window_start") or data.get("start") or 0)
        end = int(data.get("window_end") or data.get("end") or start + 1)
        payload = dict(data.get("result") or data.get("payload") or {})
        result.append(DistillationItemV1(
            item_id=f"window:{index}", source_start=start,
            source_end=max(start + 1, end), payload=payload,
            payload_sha256=canonical_sha256(payload),
        ))
    if len({item.item_id for item in result}) != len(result):
        raise ValueError("distillation leaves must have unique window identities")
    return result


def distillation_regions(
    items: Iterable[DistillationItemV1], *, level: int = 0,
    fanout: int = 6, max_payload_characters: int = 48_000,
    max_payload_tokens: int = 18_000,
) -> list[DistillationRegionV1]:
    if fanout < 2:
        raise ValueError("distillation fanout must be at least two")
    if max_payload_characters < 1_000:
        raise ValueError("distillation payload capacity is too small")
    if max_payload_tokens < 512:
        raise ValueError("distillation token capacity is too small")
    values = list(items)
    regions: list[DistillationRegionV1] = []
    offset = 0
    while offset < len(values):
        group: list[DistillationItemV1] = []
        characters = 0
        tokens = 0
        while offset < len(values) and len(group) < fanout:
            item = values[offset]
            serialized = json.dumps(
                item.payload, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), default=str,
            )
            item_characters = len(serialized)
            item_tokens = estimate_input_tokens(serialized)
            if group and (
                characters + item_characters > max_payload_characters
                or tokens + item_tokens > max_payload_tokens
            ):
                break
            if not group and (
                item_characters > max_payload_characters
                or item_tokens > max_payload_tokens
            ):
                raise ValueError("one distillation item exceeds the regional capacity")
            group.append(item)
            characters += item_characters
            tokens += item_tokens
            offset += 1
        region_index = len(regions)
        child_ids = [item.item_id for item in group]
        payloads = [item.payload for item in group]
        start = min(item.source_start for item in group)
        end = max(item.source_end for item in group)
        authority = {
            "level": level,
            "child_ids": child_ids,
            "payloads": payloads,
            "source_range": [start, end],
        }
        regions.append(DistillationRegionV1(
            level=level, region_index=region_index,
            child_ids=child_ids, source_start=start, source_end=end,
            input_sha256=canonical_sha256(authority), payloads=payloads,
        ))
    flattened = [child for region in regions for child in region.child_ids]
    if flattened != [item.item_id for item in values]:
        raise ValueError("distillation regions do not exactly cover their children")
    return regions


def distillation_needs_reduction(
    items: Iterable[DistillationItemV1], *, fanout: int = 6,
    max_payload_characters: int = 48_000,
    max_payload_tokens: int = 18_000,
) -> bool:
    values = list(items)
    if len(values) > fanout:
        return True
    serialized = [json.dumps(
        item.payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str,
    ) for item in values]
    total_characters = sum(len(item) for item in serialized)
    total_tokens = sum(estimate_input_tokens(item) for item in serialized)
    return (
        total_characters > max_payload_characters
        or total_tokens > max_payload_tokens
    )


def promoted_distillation_items(
    regions: Iterable[DistillationRegionV1],
    results: Iterable[dict[str, Any]],
) -> list[DistillationItemV1]:
    region_values = list(regions)
    result_values = list(results)
    if len(region_values) != len(result_values):
        raise ValueError("every distillation region requires one validated result")
    promoted = []
    for region, payload in zip(region_values, result_values, strict=True):
        semantic = dict(payload)
        envelope = {
            "semantic": semantic,
            "runtime_coverage": {
                "child_ids": list(region.child_ids),
                "child_count": len(region.child_ids),
                "input_sha256": region.input_sha256,
                "source_range": [region.source_start, region.source_end],
                "semantic_sha256": canonical_sha256(semantic),
            },
        }
        promoted.append(DistillationItemV1(
            item_id=f"level:{region.level + 1}:region:{region.region_index}",
            source_start=region.source_start, source_end=region.source_end,
            payload=envelope, payload_sha256=canonical_sha256(envelope),
        ))
    return promoted


class RecipeMechanismV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_sha256: str
    structural_position: str = ""
    trigger_conditions: list[str] = Field(default_factory=list)
    state_change: str = ""
    emotional_effect: str = ""
    required_preparation: list[str] = Field(default_factory=list)
    downstream_consequence: str = ""
    transfer_guidance: str = ""
    incompatible_conditions: list[str] = Field(default_factory=list)


class RecipeStyleRuleV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_sha256: str
    field: str
    rule: str
    when_to_use: str = ""
    avoid: str = ""


class CreativeRecipeV1(BaseModel):
    """Compact abstract prompt artifact; raw excerpts never enter this model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = 1
    project_id: str
    mechanisms: list[RecipeMechanismV1] = Field(default_factory=list)
    attraction_guidance: list[dict[str, Any]] = Field(default_factory=list)
    style_rules: list[RecipeStyleRuleV1] = Field(default_factory=list)
    provenance_sha256: list[str] = Field(default_factory=list)

    @property
    def authority_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


AdoptionAuthorityKind = Literal[
    "mechanism", "causal_structure", "attraction_guidance", "style_rule",
]


def adoption_authority_kind(adoption: dict[str, Any]) -> AdoptionAuthorityKind:
    """Classify an adoption only from its immutable learning-node authority.

    ``data_json`` is model/user-editable and therefore cannot decide which
    downstream prompt bucket receives an adoption.  ``mechanism_type`` is only
    a subtype after the persisted node type has proved that this is a mechanism.
    """

    node_type = str(adoption.get("node_type") or "").strip()
    data = adoption.get("data")
    if not isinstance(data, dict):
        raise ValueError("adoption data must be an object")
    if node_type == "mechanism":
        return (
            "causal_structure"
            if data.get("mechanism_type") == "causal_structure"
            else "mechanism"
        )
    if node_type == "attraction_map":
        return "attraction_guidance"
    if node_type == "style_rule":
        return "style_rule"
    raise ValueError("adoption is missing a supported immutable node type")


def compile_creative_recipe(
    project_id: str, adoptions: Iterable[dict[str, Any]],
) -> CreativeRecipeV1:
    mechanisms: list[RecipeMechanismV1] = []
    attraction: list[dict[str, Any]] = []
    styles: list[RecipeStyleRuleV1] = []
    provenance: list[str] = []
    for adoption in adoptions:
        data = dict(adoption.get("data") or {})
        authority_kind = adoption_authority_kind({**adoption, "data": data})
        source = dict(data.get("provenance") or {})
        node_hash = canonical_sha256({
            "node_id": adoption.get("node_id") or source.get("node_id"),
            "source_id": source.get("source_id"),
        })
        provenance.append(node_hash)
        if authority_kind == "attraction_guidance":
            attraction.append({
                key: value for key, value in data.items()
                if key in {
                    "opening_rule", "cycle_rules", "question_rules",
                    "relationship_rules", "reversal_rule", "ending_rule",
                }
            })
        elif authority_kind == "style_rule":
            styles.append(RecipeStyleRuleV1(
                node_sha256=node_hash, field=str(data["field"]),
                rule=str(data["rule"]),
                when_to_use=str(data.get("when_to_use") or ""),
                avoid=str(data.get("avoid") or ""),
            ))
        else:
            mechanisms.append(RecipeMechanismV1(
                node_sha256=node_hash,
                structural_position=str(data.get("structural_position") or ""),
                trigger_conditions=_string_list(data.get("trigger_conditions")),
                state_change=str(data.get("state_change") or ""),
                emotional_effect=str(data.get("emotional_effect") or ""),
                required_preparation=_string_list(data.get("required_preparation")),
                downstream_consequence=str(data.get("downstream_consequence") or ""),
                transfer_guidance=str(data.get("transfer_guidance") or ""),
                incompatible_conditions=_string_list(data.get("incompatible_conditions")),
            ))
    return CreativeRecipeV1(
        project_id=project_id, mechanisms=mechanisms,
        attraction_guidance=attraction, style_rules=styles,
        provenance_sha256=list(dict.fromkeys(provenance)),
    )


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []
