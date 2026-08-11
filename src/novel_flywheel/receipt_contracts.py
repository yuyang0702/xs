from __future__ import annotations

import json
import hashlib
import copy
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)


FINAL_REVIEW_VERDICT_CONTRACT_VERSION = "final-review-verdict/v1"
WHOLE_STORY_OBLIGATION_CATALOG_VERSION = "whole-story-obligation-catalog-v2"
RECEIPT_SEMANTIC_AUTHORITY_VERSION = "receipt-semantic-authority/v1"


class _StrictReceipt(BaseModel):
    """Closed machine-control envelope for independent model receipts."""

    model_config = ConfigDict(
        extra="forbid", strict=True, str_strip_whitespace=True,
    )


NonEmptyStrictString = Annotated[StrictStr, Field(min_length=1)]
Sha256String = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
BeatIdString = Annotated[StrictStr, Field(pattern=r"^EV-[0-9A-F]{8}/[0-9]{2}$")]
EventIdString = Annotated[StrictStr, Field(pattern=r"^EV-[0-9A-F]{8}$")]


@dataclass(frozen=True)
class ReceiptSemanticCollectionSpec:
    field: str
    identity_field: str
    expected_identities: tuple[str | int, ...]
    semantic_paths: tuple[tuple[str, ...], ...]


class ReceiptSemanticAuthorityV1(_StrictReceipt):
    version: Literal["receipt-semantic-authority/v1"] = (
        RECEIPT_SEMANTIC_AUTHORITY_VERSION
    )
    boundary: NonEmptyStrictString
    semantic_sha256: Sha256String
    payload: dict[str, Any]

    @model_validator(mode="after")
    def semantic_hash_is_bound(self) -> "ReceiptSemanticAuthorityV1":
        expected = hashlib.sha256(json.dumps(
            self.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        if self.semantic_sha256 != expected:
            raise ValueError("receipt semantic authority hash is stale")
        return self


def _semantic_path_get(value: dict[str, Any], path: Sequence[str]) -> tuple[bool, Any]:
    current: Any = value
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _semantic_path_set(value: dict[str, Any], path: Sequence[str], item: Any) -> None:
    current = value
    for part in path[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[path[-1]] = copy.deepcopy(item)


def freeze_receipt_semantics(
    receipt: object, *, boundary: str,
    scalar_paths: Sequence[Sequence[str]],
    collections: Sequence[ReceiptSemanticCollectionSpec] = (),
) -> ReceiptSemanticAuthorityV1 | None:
    """Freeze a complete semantic verdict independently from its protocol envelope."""

    if not isinstance(receipt, dict):
        return None
    payload: dict[str, Any] = {"scalars": {}, "collections": {}}
    for path in scalar_paths:
        exists, value = _semantic_path_get(receipt, path)
        if not exists:
            return None
        payload["scalars"][".".join(path)] = copy.deepcopy(value)
    for spec in collections:
        rows = receipt.get(spec.field)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            return None
        by_identity: dict[str | int, dict[str, Any]] = {}
        for row in rows:
            identity = row.get(spec.identity_field)
            if identity not in spec.expected_identities:
                continue
            semantic: dict[str, Any] = {}
            for path in spec.semantic_paths:
                exists, value = _semantic_path_get(row, path)
                if not exists:
                    return None
                semantic[".".join(path)] = copy.deepcopy(value)
            existing = by_identity.get(identity)
            if existing is not None and existing != semantic:
                return None
            by_identity[identity] = semantic
        if tuple(identity for identity in spec.expected_identities if identity in by_identity) != (
            spec.expected_identities
        ):
            return None
        payload["collections"][spec.field] = [
            {"identity": identity, "semantic": by_identity[identity]}
            for identity in spec.expected_identities
        ]
    semantic_sha256 = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return ReceiptSemanticAuthorityV1(
        boundary=boundary,
        semantic_sha256=semantic_sha256,
        payload=payload,
    )


def apply_frozen_receipt_semantics(
    receipt: object, authority: ReceiptSemanticAuthorityV1, *,
    scalar_paths: Sequence[Sequence[str]],
    collections: Sequence[ReceiptSemanticCollectionSpec] = (),
) -> tuple[object, bool]:
    """Restore frozen verdict fields while leaving protocol/evidence fields repairable."""

    if not isinstance(receipt, dict):
        return receipt, False
    result = copy.deepcopy(receipt)
    drifted = False
    frozen_scalars = authority.payload.get("scalars")
    if not isinstance(frozen_scalars, dict):
        raise ValueError("receipt semantic authority scalars are invalid")
    for path in scalar_paths:
        key = ".".join(path)
        if key not in frozen_scalars:
            raise ValueError("receipt semantic authority scalar is incomplete")
        exists, current = _semantic_path_get(result, path)
        frozen = frozen_scalars[key]
        if exists and current != frozen:
            drifted = True
        _semantic_path_set(result, path, frozen)
    frozen_collections = authority.payload.get("collections")
    if not isinstance(frozen_collections, dict):
        raise ValueError("receipt semantic authority collections are invalid")
    for spec in collections:
        frozen_rows = frozen_collections.get(spec.field)
        if not isinstance(frozen_rows, list):
            raise ValueError("receipt semantic authority collection is incomplete")
        frozen_by_identity = {
            item.get("identity"): item.get("semantic")
            for item in frozen_rows if isinstance(item, dict)
        }
        rows = result.get(spec.field)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            semantic = frozen_by_identity.get(row.get(spec.identity_field))
            if not isinstance(semantic, dict):
                continue
            for path in spec.semantic_paths:
                key = ".".join(path)
                if key not in semantic:
                    raise ValueError(
                        "receipt semantic authority collection row is incomplete"
                    )
                exists, current = _semantic_path_get(row, path)
                frozen = semantic[key]
                if exists and current != frozen:
                    drifted = True
                _semantic_path_set(row, path, frozen)
    return result, drifted


class WholeStoryPlanningBindingV2(_StrictReceipt):
    segment: int = Field(ge=1)
    planning_segment_sha256: Sha256String
    handoff: NonEmptyStrictString


class WholeStoryBeatObligationV2(_StrictReceipt):
    obligation_id: NonEmptyStrictString
    kind: Literal["atomic_beat_realization"]
    beat_id: BeatIdString
    source_event_id: EventIdString
    action: NonEmptyStrictString
    postconditions: list[NonEmptyStrictString] = Field(min_length=1)
    knowledge_delta: list[NonEmptyStrictString]
    relationship_delta: list[NonEmptyStrictString]

    @model_validator(mode="after")
    def identity_is_runtime_derived(self) -> "WholeStoryBeatObligationV2":
        if self.obligation_id != f"beat:{self.beat_id}":
            raise ValueError("beat obligation identity is stale")
        if self.beat_id.split("/", 1)[0] != self.source_event_id:
            raise ValueError("beat obligation source event is stale")
        return self


class WholeStoryEventObligationV2(_StrictReceipt):
    obligation_id: NonEmptyStrictString
    kind: Literal["planning_event_realization"]
    source_event_id: EventIdString
    beat_ids: list[BeatIdString] = Field(min_length=1)
    planning_bindings: list[WholeStoryPlanningBindingV2] = Field(min_length=1)

    @model_validator(mode="after")
    def identity_is_runtime_derived(self) -> "WholeStoryEventObligationV2":
        if self.obligation_id != f"event:{self.source_event_id}":
            raise ValueError("event obligation identity is stale")
        return self


SemanticObligationValue = StrictStr | dict[str, Any] | list[Any]


class WholeStoryGlobalObligationsV2(_StrictReceipt):
    core_goal: SemanticObligationValue | None = None
    reversal: SemanticObligationValue | None = None
    ending: SemanticObligationValue
    question_chain: SemanticObligationValue | None = None
    relationship_arc: SemanticObligationValue | None = None

    @field_validator("ending")
    @classmethod
    def ending_is_semantically_nonempty(cls, value: object) -> object:
        if value in (None, "", [], {}):
            raise ValueError("confirmed ending is empty")
        if isinstance(value, str) and not value.strip():
            raise ValueError("confirmed ending is empty")
        return value


class WholeStoryObligationCatalogV2(_StrictReceipt):
    version: Literal["whole-story-obligation-catalog-v2"]
    beat_ids: list[BeatIdString] = Field(min_length=1)
    source_event_ids: list[EventIdString] = Field(min_length=1)
    execution_manifest_authority_sha256: Sha256String
    execution_manifest_sha256: Sha256String
    causal_chain_sha256: Sha256String
    planning_ir_authority_sha256: Sha256String
    planning_topology_sha256: Sha256String
    beat_obligations: list[WholeStoryBeatObligationV2] = Field(min_length=1)
    event_obligations: list[WholeStoryEventObligationV2] = Field(min_length=1)
    global_obligations: WholeStoryGlobalObligationsV2
    catalog_sha256: Sha256String

    @model_validator(mode="after")
    def authority_graph_is_exact(self) -> "WholeStoryObligationCatalogV2":
        if self.beat_ids != [item.beat_id for item in self.beat_obligations]:
            raise ValueError("catalog beat coverage is stale")
        derived_source_ids = list(dict.fromkeys(
            item.source_event_id for item in self.beat_obligations
        ))
        if self.source_event_ids != derived_source_ids:
            raise ValueError("catalog source-event coverage is stale")
        if [item.source_event_id for item in self.event_obligations] != derived_source_ids:
            raise ValueError("catalog event obligations are stale")
        for event in self.event_obligations:
            expected = [
                beat.beat_id for beat in self.beat_obligations
                if beat.source_event_id == event.source_event_id
            ]
            if event.beat_ids != expected:
                raise ValueError("catalog event-to-beat ownership is stale")
        unsigned = self.model_dump(
            mode="json", exclude={"catalog_sha256"}, exclude_none=True,
        )
        actual = hashlib.sha256(json.dumps(
            unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        if self.catalog_sha256 != actual:
            raise ValueError("catalog content hash is stale")
        return self


class DescriptiveReviewIssueV1(_StrictReceipt):
    """Model-authored issue facts; identity and lifecycle belong to Runtime."""

    category: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    action: str = Field(min_length=1)
    location: str = ""
    effect: str = ""


class FinalReviewReconciliationV1(_StrictReceipt):
    """A verdict about one Runtime-issued ledger identity."""

    issue_id: str = Field(min_length=1)
    status: Literal[
        "resolved", "partially_resolved", "unresolved", "uncertain", "preserved",
    ]
    evidence: str = Field(min_length=1)
    severity: str = ""


class FinalReviewWindowReceipt(_StrictReceipt):
    summary: str | dict[str, Any] | list[Any]
    issues: list[DescriptiveReviewIssueV1]
    # V1 providers were instructed to return these detail arrays together
    # with the window summary.  They are typed, known representation fields;
    # the runtime quarantines them from the compact cross-window view.
    events: list[Any] = Field(default_factory=list)
    promises: list[Any] = Field(default_factory=list)
    character_states: list[Any] | dict[str, Any] = Field(default_factory=list)
    timeline: list[Any] = Field(default_factory=list)


FinalReviewDetailItem = Annotated[str, Field(min_length=1)] | dict[str, Any]


class FinalReviewDetailReceipt(_StrictReceipt):
    events: list[FinalReviewDetailItem]
    promises: list[FinalReviewDetailItem]
    character_states: list[FinalReviewDetailItem]
    timeline: list[FinalReviewDetailItem]


class FinalReviewRegionalSemanticBody(_StrictReceipt):
    """Only the semantic body may be authored by a regional reviewer."""

    summary: str = Field(min_length=1)
    issues: list[DescriptiveReviewIssueV1]


class FinalReviewRegionalRuntimeEnvelope(_StrictReceipt):
    """Provenance fields computed and bound by Runtime, never by the model."""

    covered_windows: list[int]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_issue_ids: list[str]


class FinalReviewRegionalReceipt(
    FinalReviewRegionalSemanticBody, FinalReviewRegionalRuntimeEnvelope,
):
    """V1 compatibility shape while callers migrate to body/envelope binding."""


ReviewScore = Annotated[int | float, Field(ge=0, le=100, allow_inf_nan=False)]


class FinalReviewDimensionsV1(_StrictReceipt):
    commercial: ReviewScore
    story: ReviewScore
    prose: ReviewScore


class FinalReviewCriterionEvidenceV1(_StrictReceipt):
    location: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    effect: str = Field(min_length=1)


class _FinalReviewVerdictBodyV1(_StrictReceipt):
    hard_fail: bool = False
    decision: Literal["pass", "revise", "rewrite"] = "revise"
    issues: list[DescriptiveReviewIssueV1]
    reconciliations: list[FinalReviewReconciliationV1] = Field(default_factory=list)
    request_full_review: bool = False


class FinalReviewDimensionsVerdictV1(_FinalReviewVerdictBodyV1):
    dimensions: FinalReviewDimensionsV1


class FinalReviewCriteriaVerdictV1(_FinalReviewVerdictBodyV1):
    criteria: dict[str, ReviewScore] = Field(min_length=1)
    criterion_evidence: dict[str, FinalReviewCriterionEvidenceV1] = Field(
        min_length=1,
    )

    @model_validator(mode="after")
    def evidence_keys_match_criteria(self) -> "FinalReviewCriteriaVerdictV1":
        if set(self.criteria) != set(self.criterion_evidence):
            raise ValueError("criterion_evidence keys must exactly match criteria")
        if any(not key.strip() for key in self.criteria):
            raise ValueError("criteria keys must be non-empty")
        return self


class FinalReviewFlatDimensionsVerdictV1(_FinalReviewVerdictBodyV1):
    commercial: ReviewScore
    story: ReviewScore
    prose: ReviewScore


class FinalReviewLegacyScoreVerdictV1(_FinalReviewVerdictBodyV1):
    score: ReviewScore


FinalReviewVerdictPayloadV1 = (
    FinalReviewDimensionsVerdictV1
    | FinalReviewCriteriaVerdictV1
    | FinalReviewFlatDimensionsVerdictV1
    | FinalReviewLegacyScoreVerdictV1
)


class FinalReviewVerdictReceipt(RootModel[FinalReviewVerdictPayloadV1]):
    """Versioned typed union of every explicitly supported verdict topology."""

    contract_version: ClassVar[str] = FINAL_REVIEW_VERDICT_CONTRACT_VERSION


def _validated_payload(model: type[BaseModel], payload: object, label: str) -> dict:
    try:
        value = model.model_validate(payload)
    except ValidationError as exc:
        paths = [
            ".".join(map(str, item["loc"]))
            or str(item.get("msg") or "root").removeprefix("Value error, ")
            for item in exc.errors()
        ]
        raise ValueError(f"{label} receipt shape is invalid: {', '.join(paths)}") from exc
    return value.model_dump(mode="python")


def validate_whole_story_obligation_catalog_v2(
    payload: object, *, expected_beat_ids: list[str],
    expected_manifest_sha256: str = "",
) -> dict:
    result = _validated_payload(
        WholeStoryObligationCatalogV2, payload, "whole-story obligation catalog",
    )
    if result["beat_ids"] != expected_beat_ids:
        raise ValueError("whole-story obligation catalog beat coverage is stale")
    if (
        expected_manifest_sha256
        and result["execution_manifest_sha256"] != expected_manifest_sha256
    ):
        raise ValueError("whole-story obligation catalog manifest is stale")
    return result


def validate_final_review_window_receipt(payload: object) -> dict:
    result = _validated_payload(
        FinalReviewWindowReceipt, payload, "final-review window",
    )
    if not isinstance(result["summary"], str):
        result["summary"] = json.dumps(
            result["summary"], ensure_ascii=False, separators=(",", ":"),
        )
    if not result["summary"].strip():
        raise ValueError("final-review window receipt shape is invalid: summary")
    return result


def validate_final_review_detail_receipt(payload: object) -> dict:
    return _validated_payload(
        FinalReviewDetailReceipt, payload, "final-review detail",
    )


def validate_final_review_regional_semantic_body(payload: object) -> dict:
    return _validated_payload(
        FinalReviewRegionalSemanticBody, payload, "final-review regional body",
    )


def validate_final_review_regional_runtime_envelope(payload: object) -> dict:
    return _validated_payload(
        FinalReviewRegionalRuntimeEnvelope, payload,
        "final-review regional runtime envelope",
    )


def validate_final_review_regional_receipt(payload: object) -> dict:
    return _validated_payload(
        FinalReviewRegionalReceipt, payload, "final-review regional",
    )


def _final_review_verdict_model(payload: object) -> type[_FinalReviewVerdictBodyV1]:
    if not isinstance(payload, dict):
        raise ValueError("final-review verdict receipt shape is invalid: root")
    topologies: list[type[_FinalReviewVerdictBodyV1]] = []
    if "dimensions" in payload:
        topologies.append(FinalReviewDimensionsVerdictV1)
    if "criteria" in payload or "criterion_evidence" in payload:
        topologies.append(FinalReviewCriteriaVerdictV1)
    if any(name in payload for name in ("commercial", "story", "prose")):
        topologies.append(FinalReviewFlatDimensionsVerdictV1)
    if "score" in payload:
        topologies.append(FinalReviewLegacyScoreVerdictV1)
    if len(topologies) != 1:
        raise ValueError(
            "final-review verdict receipt shape is invalid: score_topology",
        )
    return topologies[0]


def validate_final_review_verdict_receipt_v1(payload: object) -> dict:
    """Validate one and only one supported V1 score representation."""

    return _validated_payload(
        _final_review_verdict_model(payload), payload, "final-review verdict",
    )


def validate_final_review_verdict_receipt(payload: object) -> dict:
    """Stable compatibility entry point for the current verdict contract."""

    return validate_final_review_verdict_receipt_v1(payload)
