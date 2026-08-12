from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from json_repair import repair_json
from pydantic import BaseModel, ConfigDict, Field

from novel_flywheel.evidence_alignment import align_unique_evidence_span
from novel_flywheel.model_output import (
    AdditionalMalformedJSONValueError,
    MultipleJSONObjectError,
    parse_json_object,
)
from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure
from novel_flywheel.semantic_packets import canonical_sha256
from novel_flywheel.storage import atomic_write


ParserStrategy = Literal["json", "baml_sap"]
ArtifactPhase = Literal["planning", "writing", "quality", "runtime"]
RecoveryStep = Literal[
    "exact_json",
    "local_syntax_repair",
    "baml_sap",
    "semantic_protocol_retry",
    "model_fallback",
    "minimal_regeneration",
    "semantic_split",
    "checkpoint_resume",
]

EXECUTABLE_RECOVERY_STEP_OWNERS: Mapping[str, str] = {
    "exact_json": "GeneratedArtifactGateway",
    "local_syntax_repair": "GeneratedArtifactGateway",
    "baml_sap": "GeneratedArtifactGateway",
    "semantic_protocol_retry": "contract_runtime.execute_contract_runtime",
    "model_fallback": "contract_runtime.dispatch_explicit_model_route",
    "minimal_regeneration": "contract_runtime.domain_validator",
    "semantic_split": "semantic_packets.semantic_bisect",
    "checkpoint_resume": "Database.workflow_node_checkpoints",
}


class ArtifactContractRegistration(BaseModel):
    """One registry entry for a model-produced machine-readable artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    phase: ArtifactPhase
    parser_strategy: ParserStrategy = "json"
    semantic_authority: str = Field(min_length=1)
    descriptive_fields: Literal["open"] = "open"
    machine_control_fields: Literal["closed"] = "closed"
    narrative_invariants: Literal["runtime_authoritative"] = "runtime_authoritative"
    legacy_labels: tuple[str, ...] = ()
    recovery_ladder: tuple[RecoveryStep, ...] = (
        "exact_json",
        "local_syntax_repair",
        "semantic_protocol_retry",
        "model_fallback",
        "minimal_regeneration",
        "checkpoint_resume",
    )


_REGISTRATIONS = (
    ArtifactContractRegistration(
        name="planning_adaptation_segment", phase="planning",
        semantic_authority="normalize_planning_adaptation_receipt",
        legacy_labels=("Planning adaptation receipt segment",),
    ),
    ArtifactContractRegistration(
        name="planning_adaptation_facet", phase="planning",
        semantic_authority="_planning_adaptation_facet_receipt_valid",
        legacy_labels=(
            "Planning adaptation facet receipt",
            "Planning adaptation facet window receipt",
        ),
    ),
    ArtifactContractRegistration(
        name="planning_adaptation_hierarchy", phase="planning",
        semantic_authority="_normalize_planning_hierarchy_receipt",
        legacy_labels=(
            "Planning adaptation hierarchy receipt",
            "Planning adaptation regional receipt",
        ),
    ),
    ArtifactContractRegistration(
        name="planning_adaptation_whole", phase="planning",
        semantic_authority="normalize_planning_adaptation_whole_receipt",
        legacy_labels=("Whole planning adaptation receipt",),
    ),
    ArtifactContractRegistration(
        name="planning_repair_patch", phase="planning",
        semantic_authority="normalize_planning_repair_patch",
        legacy_labels=("Planning repair patch segment",),
    ),
    ArtifactContractRegistration(
        name="short_plan_packet", phase="planning",
        semantic_authority="runtime event ownership and narrative contract",
        legacy_labels=("structured payload", "JSON packet"),
    ),
    ArtifactContractRegistration(
        name="planning_event_realizations", phase="planning",
        semantic_authority="ordered Runtime-owned planning event realization IR",
        legacy_labels=("planning event realization array",),
    ),
    ArtifactContractRegistration(
        name="planning_semantic_v2", version=2, phase="planning",
        semantic_authority=(
            "PlanningSemanticDraftV2 plus Runtime-owned formal event and exit topology"
        ),
        legacy_labels=("Markdown-first short planning",),
    ),
    ArtifactContractRegistration(
        name="short_causal_chain", phase="planning", parser_strategy="baml_sap",
        semantic_authority="normalize_causal_packet_payload",
        legacy_labels=("Short causal chain", "Causal chain event packet"),
        recovery_ladder=(
            "exact_json", "local_syntax_repair", "baml_sap",
            "semantic_protocol_retry", "model_fallback",
            "minimal_regeneration", "semantic_split", "checkpoint_resume",
        ),
    ),
    ArtifactContractRegistration(
        name="embedded_causal_chain", phase="planning",
        semantic_authority="analyze_short_causal_chain after legacy plan extraction",
        legacy_labels=("Short causal chain marker",),
    ),
    ArtifactContractRegistration(
        name="execution_manifest", phase="planning",
        semantic_authority="ExecutionManifestFragment plus narrative contract",
        legacy_labels=("Execution manifest segment",),
    ),
    ArtifactContractRegistration(
        name="execution_manifest_receipt", phase="planning",
        semantic_authority="execution manifest evidence validator",
        legacy_labels=("Execution manifest receipt segment",),
    ),
    ArtifactContractRegistration(
        name="generated_narrative_artifact", phase="writing",
        semantic_authority="structured artifact contract plus event ownership",
        legacy_labels=("structured narrative payload",),
    ),
    ArtifactContractRegistration(
        name="draft_atomic_semantic_receipt", phase="writing",
        semantic_authority=(
            "atomic beat semantic receipt verifier with task and beat ownership"
        ),
    ),
    ArtifactContractRegistration(
        name="draft_segment_semantic_receipt", phase="writing",
        semantic_authority=(
            "segment event semantic receipt verifier with task ownership"
        ),
    ),
    ArtifactContractRegistration(
        name="draft_whole_semantic_receipt", phase="writing",
        semantic_authority=(
            "whole-story semantic receipt verifier over ordered segment evidence"
        ),
    ),
    ArtifactContractRegistration(
        name="draft_whole_window_receipt", phase="writing",
        semantic_authority=(
            "capacity-window semantic receipt verifier with obligation deltas"
        ),
    ),
    ArtifactContractRegistration(
        name="draft_whole_reducer_receipt", phase="writing",
        semantic_authority=(
            "global whole-story reducer over validated semantic windows"
        ),
    ),
    ArtifactContractRegistration(
        name="polish_assessment", phase="quality",
        semantic_authority="polish authority packet and protected constraints",
    ),
    ArtifactContractRegistration(
        name="revision_plan", phase="quality",
        semantic_authority="normalize_revision_plan for structural scene tasks",
    ),
    ArtifactContractRegistration(
        name="revision_patch_contract", phase="quality",
        semantic_authority=(
            "normalize_repair_contract for one Runtime-authorized semantic issue group"
        ),
    ),
    ArtifactContractRegistration(
        name="final_review", phase="quality",
        semantic_authority="typed final-review verdict and authoritative issue ledger",
    ),
    ArtifactContractRegistration(
        name="final_review_window", phase="quality",
        semantic_authority="typed manuscript-window evidence and descriptive issues",
    ),
    ArtifactContractRegistration(
        name="final_review_regional", phase="quality",
        semantic_authority="typed regional issue reduction semantic body",
    ),
    ArtifactContractRegistration(
        name="final_review_detail", phase="quality",
        semantic_authority="typed detailed ending, causality, and promise evidence",
    ),
    ArtifactContractRegistration(
        name="reader_review", phase="quality",
        semantic_authority="target-reader quality verdict plus reader signals",
    ),
    ArtifactContractRegistration(
        name="short_maintenance_facts", phase="runtime",
        semantic_authority=(
            "Runtime incremental StoryState adapter with stable fact keys, "
            "typed state transitions, and audited singleton normalization"
        ),
        legacy_labels=("short-story maintenance facts",),
    ),
    ArtifactContractRegistration(
        name="long_setup_maintenance", phase="runtime",
        semantic_authority=(
            "long-form setup facts, volume plan, and initial memory projection"
        ),
        legacy_labels=("book setup maintenance facts",),
    ),
    ArtifactContractRegistration(
        name="long_chapter_maintenance", phase="runtime",
        semantic_authority=(
            "long-form chapter fact and character-state delta projection"
        ),
        legacy_labels=("chapter maintenance facts",),
    ),
    ArtifactContractRegistration(
        name="maintenance_window_receipt", phase="runtime",
        semantic_authority=(
            "MaintenanceWindowReceiptV1 plus unique exact manuscript evidence "
            "and Runtime-owned window/StoryState authority"
        ),
        legacy_labels=("maintenance authority window",),
    ),
    ArtifactContractRegistration(
        name="material_audit", phase="quality",
        semantic_authority=(
            "MaterialAuditReceiptV1 over Runtime-owned complete manuscript-window "
            "and project-reference packet spans, with descriptive issue semantics "
            "preserved and deterministic exact-object reduction"
        ),
        legacy_labels=("materials audit",),
    ),
    ArtifactContractRegistration(
        name="material_impact_analysis", phase="runtime",
        semantic_authority=(
            "MaterialImpactOutput plus Runtime-owned project-document paths, "
            "exact old-text containment, and target content hashes"
        ),
        legacy_labels=("character material impact",),
    ),
    ArtifactContractRegistration(
        name="outline_material_manifest", phase="planning",
        semantic_authority=(
            "complete outline-material manifest plus Runtime exact-substring "
            "source-evidence validation"
        ),
        legacy_labels=("资料清单",),
    ),
    ArtifactContractRegistration(
        name="outline_semantic_review", phase="planning",
        semantic_authority=(
            "complete Runtime-owned outline change-ID decisions plus locked-fact "
            "and allowed-ID validation"
        ),
        legacy_labels=("大纲变化判断",),
    ),
    ArtifactContractRegistration(
        name="interview_planning", phase="planning",
        semantic_authority="planning interview domain validator",
        legacy_labels=("Planning model output",),
    ),
    ArtifactContractRegistration(
        name="style_analysis", phase="planning",
        semantic_authority="style profile validator",
        legacy_labels=("笔感分析",),
    ),
    ArtifactContractRegistration(
        name="learning_artifact", phase="runtime",
        semantic_authority="learning artifact domain validator",
        legacy_labels=("模型返回内容",),
    ),
    ArtifactContractRegistration(
        name="reference_analysis_window", version=2, phase="runtime",
        semantic_authority=(
            "exact Runtime-owned source-window offsets plus evidenced reference "
            "fact and interpretation lists validated by LearningSystem._window_result"
        ),
        legacy_labels=("reference window model claim",),
    ),
    ArtifactContractRegistration(
        name="capability_probe", phase="runtime",
        semantic_authority="provider capability probe validator",
        legacy_labels=("Capability probe output",),
    ),
    ArtifactContractRegistration(
        name="reference_distillation_region", version=2, phase="runtime",
        semantic_authority=(
            "DistillationReceiptV2 exact child disposition and typed semantic "
            "attribution ledgers plus LearningSystem._synthesis_result"
        ),
        legacy_labels=("truncated full-reference synthesis payload",),
    ),
)

ARTIFACT_CONTRACT_REGISTRY: Mapping[str, ArtifactContractRegistration] = {
    item.name: item for item in _REGISTRATIONS
}


def validate_executable_contract_registry() -> None:
    """Fail when a declared recovery step has no single implementation owner."""

    missing = {
        step
        for registration in ARTIFACT_CONTRACT_REGISTRY.values()
        for step in registration.recovery_ladder
        if step not in EXECUTABLE_RECOVERY_STEP_OWNERS
    }
    if missing:
        raise RuntimeError(
            "artifact recovery steps are not executable: "
            + ", ".join(sorted(missing))
        )
    invalid: list[str] = []
    for registration in ARTIFACT_CONTRACT_REGISTRY.values():
        ladder = registration.recovery_ladder
        if not ladder or ladder[0] != "exact_json":
            invalid.append(f"{registration.name}:exact_json_must_be_first")
        if len(ladder) != len(set(ladder)):
            invalid.append(f"{registration.name}:duplicate_recovery_step")
        if registration.parser_strategy == "baml_sap" and "baml_sap" not in ladder:
            invalid.append(f"{registration.name}:baml_sap_step_missing")
        ordered = [
            step for step in (
                "semantic_protocol_retry", "model_fallback",
                "minimal_regeneration", "semantic_split", "checkpoint_resume",
            ) if step in ladder
        ]
        indices = [ladder.index(step) for step in ordered]
        if indices != sorted(indices):
            invalid.append(f"{registration.name}:recovery_order_invalid")
    if invalid:
        raise RuntimeError(
            "artifact recovery ladders are invalid: "
            + ", ".join(sorted(invalid))
        )


validate_executable_contract_registry()


class ArtifactConversionAudit(BaseModel):
    """Secret-free, content-addressed evidence for one conversion attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_name: str
    contract_version: int
    raw_sha256: str
    canonical_sha256: str = ""
    method: Literal[
        "exact_json", "local_syntax_repair", "baml_sap", "rejected",
    ]
    transformations: tuple[str, ...] = ()
    quarantined_paths: tuple[str, ...] = ()
    candidate_count: int = 0
    semantic_valid: bool = False
    failure_code: str = ""


class ArtifactConversionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload: dict[str, Any]
    audit: ArtifactConversionAudit


class ContractAdapterRegistration(BaseModel):
    """Versioned proof obligation for one canonical representation adapter.

    Adapters may reconcile representation only.  They never authorize story
    semantics, choose between ambiguous candidates, or depend on a provider,
    model, genre, project, or production sample.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    version: int = Field(ge=1)
    contract_name: str = Field(min_length=1)
    source_shapes: tuple[str, ...]
    canonical_shape: str = Field(min_length=1)
    proof_obligation: str = Field(min_length=1)
    provider_agnostic: Literal[True] = True
    narrative_agnostic: Literal[True] = True
    automatic_conversion: bool = False


class ContractAdapterAudit(BaseModel):
    """Content-addressed evidence for a proved representation conversion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter_name: str
    adapter_version: int
    contract_name: str
    source_shape: str
    canonical_shape: str
    transformations: tuple[str, ...]
    input_sha256: str
    output_sha256: str
    proof_sha256: str


class ContractAdaptationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload: dict[str, Any]
    audits: tuple[ContractAdapterAudit, ...] = ()


class _PlanningFacetCanonicalShape(BaseModel):
    """Pydantic boundary for the fields owned by the facet adapter."""

    model_config = ConfigDict(extra="allow", strict=True)

    invariants: dict[str, bool]
    changed_dimensions: list[str]


class _PlanningEventCanonicalItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: str = Field(min_length=1)
    narrative: str = Field(min_length=1)


class _PlanningEventCanonicalShape(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    events: list[_PlanningEventCanonicalItem]


PLANNING_FACET_CLOSED_TRUTH_ADAPTER = ContractAdapterRegistration(
    name="planning_facet_closed_truth",
    version=1,
    contract_name="planning_adaptation_facet",
    source_shapes=(
        "complete invariant truth set",
        "complete reviewed-dimension echo",
    ),
    canonical_shape="exact invariant boolean map plus effective dimensions",
    proof_obligation=(
        "Every requested invariant occurs exactly once, no unknown invariant "
        "exists, and protected changed dimensions are either absent or the "
        "same complete requested review scope."
    ),
)


PLANNING_FACET_UNIQUE_EVIDENCE_ADAPTER = ContractAdapterRegistration(
    name="planning_facet_unique_evidence_quote",
    version=2,
    contract_name="planning_adaptation_facet",
    source_shapes=(
        "unique fuzzy evidence quote",
        "unique exact evidence quote with detached reason",
    ),
    canonical_shape="exact extractive quote bound to selected Runtime evidence",
    proof_obligation=(
        "A negative verdict selects only known unique evidence IDs; its fuzzy "
        "quote aligns to one sufficiently informative exact span at exactly "
        "one location across the selected Runtime-owned evidence, while the "
        "independent descriptive reason remains non-empty."
    ),
)


PLANNING_EVENT_TOPOLOGY_ADAPTER = ContractAdapterRegistration(
    name="planning_event_topology",
    version=1,
    contract_name="planning_event_realizations",
    source_shapes=(
        "canonical ordered event array",
        "nested ordered event record array",
        "event identity keyed mapping",
        "tool arguments or unseen nested envelope",
    ),
    canonical_shape="ordered events array with event_id and opaque narrative",
    proof_obligation=(
        "Exactly one narrative is bound to every expected Runtime event ID in "
        "the same order; no duplicate identity, conflicting candidate, partial "
        "coverage, or machine-control field exists. Narrative bytes remain opaque."
    ),
    automatic_conversion=True,
)


PLANNING_SEMANTIC_ENVELOPE_ADAPTER = ContractAdapterRegistration(
    name="planning_semantic_unique_envelope",
    version=1,
    contract_name="planning_semantic_v2",
    source_shapes=(
        "canonical semantic object",
        "single nested data/result/payload envelope",
        "single unseen nested object envelope",
    ),
    canonical_shape="PlanningSemanticDraftV2 object",
    proof_obligation=(
        "Exactly one nested object satisfies the complete semantic contract; "
        "no second candidate or machine-control field exists. Wrapper scalars "
        "are descriptive only and Runtime authority is injected afterwards."
    ),
    automatic_conversion=True,
)


PLANNING_SEMANTIC_ROOT_PROJECTION_ADAPTER = ContractAdapterRegistration(
    name="planning_semantic_root_projection",
    version=1,
    contract_name="planning_semantic_v2",
    source_shapes=(
        "complete canonical semantic core plus descriptive packet-root echoes",
    ),
    canonical_shape="PlanningSemanticDraftV2 object",
    proof_obligation=(
        "After removing only non-control packet-root fields, the complete canonical "
        "semantic core validates exactly once. No removed subtree may contain a second "
        "complete semantic candidate and no machine-control field may occur anywhere."
    ),
    automatic_conversion=True,
)


REFERENCE_DISTILLATION_LEDGER_ADAPTER = ContractAdapterRegistration(
    name="reference_distillation_v2_ledger_alignment",
    version=1,
    contract_name="reference_distillation_region",
    source_shapes=(
        "V2 promoted disposition without descriptive reason",
        "V2 merged disposition carrying related child identities",
        "V2 attribution_type alias and semantic-root JSON pointer",
    ),
    canonical_shape=(
        "DistillationReceiptV2 exact dispositions and typed child attribution graph"
    ),
    proof_obligation=(
        "Every transformed child identity is unique and unchanged; merged ownership "
        "declares a non-empty unique related-child set and cannot conflict with a direct "
        "claim. Only the redundant semantic JSON-pointer root is removed. Runtime later "
        "proves exact child coverage, graph reachability, and referenced semantic values."
    ),
    automatic_conversion=True,
)


EXECUTION_MANIFEST_EVIDENCE_REFERENCE_ADAPTER = ContractAdapterRegistration(
    name="execution_manifest_evidence_reference",
    version=1,
    contract_name="execution_manifest",
    source_shapes=(
        "Runtime evidence ID references",
        "legacy exact Runtime evidence echo",
        "unique presentation-normalized extractive Runtime evidence echo",
        "omitted evidence with one Runtime candidate",
    ),
    canonical_shape=(
        "atomic beat proposals with ordered Runtime-owned source_evidence_ids"
    ),
    proof_obligation=(
        "Every evidence reference belongs to the beat's Runtime source event and "
        "forms one unique contiguous ordered span of that event's evidence catalog. "
        "Legacy text is accepted only when it is one uniquely located extractive span; "
        "unknown, non-extractive, cross-event, duplicate, conflicting, or ambiguous "
        "inputs fail closed."
    ),
)


CONTRACT_ADAPTER_REGISTRY: Mapping[str, tuple[ContractAdapterRegistration, ...]] = {
    "planning_adaptation_facet": (
        PLANNING_FACET_CLOSED_TRUTH_ADAPTER,
        PLANNING_FACET_UNIQUE_EVIDENCE_ADAPTER,
    ),
    "planning_event_realizations": (
        PLANNING_EVENT_TOPOLOGY_ADAPTER,
    ),
    "planning_semantic_v2": (
        PLANNING_SEMANTIC_ENVELOPE_ADAPTER,
        PLANNING_SEMANTIC_ROOT_PROJECTION_ADAPTER,
    ),
    "execution_manifest": (
        EXECUTION_MANIFEST_EVIDENCE_REFERENCE_ADAPTER,
    ),
    "reference_distillation_region": (
        REFERENCE_DISTILLATION_LEDGER_ADAPTER,
    ),
}


def _try_semantic_normalizer(
    semantic_normalizer: SemanticNormalizer, value: object,
) -> dict[str, Any] | None:
    """Treat domain validation errors as a representation miss, not a crash."""

    try:
        normalized = semantic_normalizer(value)
    except (TypeError, ValueError):
        return None
    return normalized if isinstance(normalized, dict) else None


def _unique_semantic_envelope(
    payload: dict[str, Any], semantic_normalizer: SemanticNormalizer,
) -> tuple[dict[str, Any], tuple[str, ...], int] | None:
    """Prove a single complete semantic object inside descriptive wrappers."""

    if _try_semantic_normalizer(semantic_normalizer, payload) is not None:
        return None
    unsafe = _unsafe_machine_control_keys(payload)
    if unsafe:
        raise ValueError(
            "semantic envelope contains unknown machine controls: "
            + ", ".join(sorted(set(unsafe)))
        )
    candidates: list[tuple[str, dict[str, Any]]] = []
    for path, child in _walk(payload):
        if path == "$" or not isinstance(child, dict):
            continue
        normalized = _try_semantic_normalizer(semantic_normalizer, child)
        if normalized is not None:
            candidates.append((path, normalized))
    if len(candidates) > 1:
        raise AmbiguousSemanticEnvelopeError(
            "semantic envelope contains multiple complete candidates"
        )
    if not candidates:
        return None
    path, canonical = candidates[0]
    return canonical, ("planning_semantic_unique_envelope", f"source:{path}"), 1


def _adapt_planning_semantic_root_projection(
    payload: dict[str, Any], *, semantic_normalizer: SemanticNormalizer | None,
) -> tuple[dict[str, Any], ContractAdapterAudit] | None:
    """Project a complete semantic core away from packet-level descriptions."""

    if semantic_normalizer is None:
        return None
    if _try_semantic_normalizer(semantic_normalizer, payload) is not None:
        return None
    canonical_keys = ("version", "initial_state", "segments")
    if any(key not in payload for key in canonical_keys):
        return None
    extra_keys = [key for key in payload if key not in canonical_keys]
    if not extra_keys:
        return None
    unsafe = _unsafe_machine_control_keys(payload)
    if unsafe:
        raise ValueError(
            "planning semantic root projection contains unknown machine controls: "
            + ", ".join(sorted(set(unsafe)))
        )
    canonical_input = {key: payload[key] for key in canonical_keys}
    canonical = _try_semantic_normalizer(semantic_normalizer, canonical_input)
    if canonical is None:
        return None
    nested_candidates: list[str] = []
    for key in extra_keys:
        for path, child in _walk(payload[key], f"$.{key}"):
            if not isinstance(child, dict):
                continue
            if _try_semantic_normalizer(semantic_normalizer, child) is not None:
                nested_candidates.append(path)
    if nested_candidates:
        raise AmbiguousSemanticEnvelopeError(
            "planning semantic root projection contains a second complete candidate"
        )
    descriptor = PLANNING_SEMANTIC_ROOT_PROJECTION_ADAPTER
    return canonical, ContractAdapterAudit(
        adapter_name=descriptor.name,
        adapter_version=descriptor.version,
        contract_name=descriptor.contract_name,
        source_shape=descriptor.source_shapes[0],
        canonical_shape=descriptor.canonical_shape,
        transformations=(descriptor.name,),
        input_sha256=canonical_sha256(payload),
        output_sha256=canonical_sha256(canonical),
        proof_sha256=canonical_sha256({
            "canonical_keys": canonical_keys,
            "quarantined_root_keys": sorted(extra_keys),
            "candidate_count": 1,
        }),
    )


def _adapt_reference_distillation_v2_ledger(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], ContractAdapterAudit] | None:
    """Align one provably equivalent V2 disposition/attribution ledger."""

    dispositions_value = payload.get("child_dispositions")
    attributions_value = payload.get("child_attributions", [])
    if not isinstance(dispositions_value, list) or not isinstance(
        attributions_value, list,
    ):
        return None
    alternate = any(
        isinstance(item, dict)
        and (
            item.get("disposition") == "merged"
            or "related_child_ids" in item
            or (
                item.get("disposition") == "promoted"
                and not isinstance(item.get("reason"), str)
            )
        )
        for item in dispositions_value
    ) or any(
        isinstance(item, dict)
        and (
            "attribution_type" in item
            or str(item.get("semantic_path") or "").startswith("/semantic/")
        )
        for item in attributions_value
    )
    if not alternate:
        return None

    canonical = dict(payload)
    canonical_dispositions: list[dict[str, Any]] = []
    canonical_attributions: list[dict[str, Any]] = []
    child_ids: set[str] = set()
    attribution_by_child: dict[str, dict[str, Any]] = {}
    transformations: set[str] = set()

    for raw in attributions_value:
        if not isinstance(raw, dict):
            raise ValueError("distillation attribution must be an object")
        item = dict(raw)
        child_id = item.get("child_id")
        if not isinstance(child_id, str) or not child_id.strip():
            raise ValueError("distillation attribution has no child identity")
        child_id = child_id.strip()
        relation = item.get("relation")
        alias = item.pop("attribution_type", None)
        if alias is not None:
            if relation is not None and relation != alias:
                raise ValueError("distillation attribution aliases conflict")
            relation = alias
            item["relation"] = relation
            transformations.add("attribution_type_renamed")
        path = item.get("semantic_path")
        if isinstance(path, str) and path.startswith("/semantic/"):
            item["semantic_path"] = path[len("/semantic"):]
            transformations.add("semantic_pointer_root_removed")
        if child_id in attribution_by_child:
            raise ValueError("distillation attribution repeats a child identity")
        item["child_id"] = child_id
        attribution_by_child[child_id] = item
        canonical_attributions.append(item)

    for raw in dispositions_value:
        if not isinstance(raw, dict):
            raise ValueError("distillation disposition must be an object")
        item = dict(raw)
        child_id = item.get("child_id")
        if not isinstance(child_id, str) or not child_id.strip():
            raise ValueError("distillation disposition has no child identity")
        child_id = child_id.strip()
        if child_id in child_ids:
            raise ValueError("distillation disposition repeats a child identity")
        child_ids.add(child_id)
        disposition = item.get("disposition")
        related = item.pop("related_child_ids", None)
        if disposition == "merged":
            if not (
                isinstance(related, list)
                and related
                and all(isinstance(value, str) and value.strip() for value in related)
            ):
                raise ValueError("merged disposition lacks related child identities")
            related_ids = [value.strip() for value in related]
            if len(related_ids) != len(set(related_ids)) or child_id in related_ids:
                raise ValueError("merged disposition has ambiguous child ownership")
            existing = attribution_by_child.get(child_id)
            if existing is not None:
                if not (
                    existing.get("relation") == "merged"
                    and existing.get("related_child_ids") == related_ids
                    and existing.get("semantic_path") is None
                ):
                    raise ValueError("merged disposition conflicts with child attribution")
            else:
                merged_attribution = {
                    "child_id": child_id,
                    "relation": "merged",
                    "semantic_path": None,
                    "related_child_ids": related_ids,
                }
                attribution_by_child[child_id] = merged_attribution
                canonical_attributions.append(merged_attribution)
            item["disposition"] = "promoted"
            item["reason"] = "Runtime proved the declared merged-child attribution."
            transformations.add("merged_disposition_projected")
        elif disposition == "promoted":
            if related is not None:
                raise ValueError("promoted disposition carries ambiguous related children")
            if not isinstance(item.get("reason"), str):
                item["reason"] = "Runtime proved the declared promoted-child attribution."
                transformations.add("promoted_reason_derived_from_structure")
        elif disposition == "no_transferable_claim":
            if related is not None or not isinstance(item.get("reason"), str):
                return None
        else:
            return None
        item["child_id"] = child_id
        canonical_dispositions.append(item)

    canonical["child_dispositions"] = canonical_dispositions
    canonical["child_attributions"] = canonical_attributions
    descriptor = REFERENCE_DISTILLATION_LEDGER_ADAPTER
    transformations.add(descriptor.name)
    return canonical, ContractAdapterAudit(
        adapter_name=descriptor.name,
        adapter_version=descriptor.version,
        contract_name=descriptor.contract_name,
        source_shape="; ".join(descriptor.source_shapes),
        canonical_shape=descriptor.canonical_shape,
        transformations=tuple(sorted(transformations)),
        input_sha256=canonical_sha256(payload),
        output_sha256=canonical_sha256(canonical),
        proof_sha256=canonical_sha256({
            "covered_child_sha256": canonical_sha256(
                canonical.get("covered_child_ids") or [],
            ),
            "disposition_child_sha256": canonical_sha256(
                [item["child_id"] for item in canonical_dispositions],
            ),
            "attribution_child_sha256": canonical_sha256(
                [item["child_id"] for item in canonical_attributions],
            ),
        }),
    )


def _closed_name(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _adapt_planning_facet_closed_truth(
    payload: dict[str, Any], *, invariant_fields: Sequence[str],
) -> tuple[dict[str, Any], ContractAdapterAudit] | None:
    """Prove and canonicalize the one registered planning-facet equivalence."""

    requested_fields = [str(field) for field in invariant_fields]
    requested = [_closed_name(field) for field in requested_fields]
    if (
        not requested
        or any(not field for field in requested)
        or len(set(requested)) != len(requested)
    ):
        raise ValueError("planning facet adapter received an invalid invariant contract")

    normalized = dict(payload)
    transformations: list[str] = []
    source_shapes: list[str] = []
    invariants = normalized.get("invariants")
    dimensions_value = normalized.get("changed_dimensions")
    if isinstance(invariants, list):
        if (
            not all(isinstance(item, str) for item in invariants)
            or not isinstance(dimensions_value, list)
            or not all(isinstance(item, str) for item in dimensions_value)
        ):
            return None
        truth_set = [_closed_name(item) for item in invariants]
        dimensions = [_closed_name(item) for item in dimensions_value]
        requested_set = set(requested)
        protected_dimensions = [
            item for item in dimensions if item in requested_set
        ]
        dimension_scope_is_safe = (
            not protected_dimensions
            or (
                len(dimensions) == len(requested)
                and len(set(dimensions)) == len(requested)
                and set(dimensions) == requested_set
            )
        )
        if not (
            len(truth_set) == len(requested)
            and len(set(truth_set)) == len(requested)
            and set(truth_set) == requested_set
            and dimension_scope_is_safe
        ):
            return None
        normalized["invariants"] = {
            field: True for field in requested_fields
        }
        invariants = normalized["invariants"]
        transformations.append("invariant_truth_set_expanded")
        source_shapes.append("complete invariant truth set")

    if not (
        isinstance(invariants, dict)
        and set(invariants) == set(requested_fields)
        and all(invariants.get(field) is True for field in requested_fields)
    ):
        return None

    dimensions_value = normalized.get("changed_dimensions")
    if isinstance(dimensions_value, list) and all(
        isinstance(item, str) and bool(_closed_name(item))
        for item in dimensions_value
    ):
        dimensions = [_closed_name(item) for item in dimensions_value]
        if (
            len(dimensions) == len(requested)
            and len(set(dimensions)) == len(requested)
            and set(dimensions) == set(requested)
        ):
            normalized["changed_dimensions"] = []
            transformations.append("reviewed_dimensions_reclassified")
            source_shapes.append("complete reviewed-dimension echo")

    if not transformations:
        return None

    canonical = _PlanningFacetCanonicalShape.model_validate(normalized)
    canonical_payload = canonical.model_dump(mode="python")
    if set(canonical_payload["invariants"]) != set(requested_fields):
        raise ValueError("planning facet adapter produced an invalid invariant map")
    proof = {
        "requested_invariants": requested,
        "canonical_invariants": sorted(
            _closed_name(field) for field in canonical_payload["invariants"]
        ),
        "transformations": transformations,
        "protected_dimensions": sorted(
            item for item in (
                _closed_name(value)
                for value in (payload.get("changed_dimensions") or [])
                if isinstance(value, str)
            )
            if item in set(requested)
        ),
    }
    descriptor = PLANNING_FACET_CLOSED_TRUTH_ADAPTER
    return canonical_payload, ContractAdapterAudit(
        adapter_name=descriptor.name,
        adapter_version=descriptor.version,
        contract_name=descriptor.contract_name,
        source_shape=" + ".join(source_shapes),
        canonical_shape=descriptor.canonical_shape,
        transformations=tuple(transformations),
        input_sha256=canonical_sha256(payload),
        output_sha256=canonical_sha256(canonical_payload),
        proof_sha256=canonical_sha256(proof),
    )


def _adapt_planning_facet_unique_evidence(
    payload: dict[str, Any], *, invariant_fields: Sequence[str],
    evidence_candidates: Mapping[str, str],
) -> tuple[dict[str, Any], ContractAdapterAudit] | None:
    """Prove one fuzzy negative quote is an extractive representation."""

    requested_fields = [str(field) for field in invariant_fields]
    invariants = payload.get("invariants")
    dimensions = payload.get("changed_dimensions")
    evidence_ids = payload.get("plan_evidence_ids")
    quote = str(payload.get("plan_evidence_quote") or "").strip()
    reason = payload.get("reason")
    if not (
        requested_fields
        and isinstance(invariants, dict)
        and set(invariants) == set(requested_fields)
        and all(isinstance(invariants.get(field), bool) for field in requested_fields)
        and any(invariants.get(field) is False for field in requested_fields)
        and isinstance(dimensions, list)
        and all(isinstance(item, str) for item in dimensions)
        and isinstance(evidence_ids, list)
        and bool(evidence_ids)
        and all(isinstance(item, str) and item in evidence_candidates for item in evidence_ids)
        and len(set(evidence_ids)) == len(evidence_ids)
        and quote
        and isinstance(reason, str)
        and bool(reason.strip())
    ):
        return None
    selected_sources = [str(evidence_candidates[item]) for item in evidence_ids]
    aligned = [
        (evidence_id, span)
        for evidence_id, source in zip(evidence_ids, selected_sources, strict=True)
        if (span := align_unique_evidence_span(source, quote))
    ]
    if len(aligned) != 1:
        return None
    evidence_id, exact_span = aligned[0]
    normalized = dict(payload)
    normalized["plan_evidence_quote"] = exact_span
    transformations = []
    source_shape = (
        "unique exact evidence quote with detached reason"
        if exact_span == quote else "unique fuzzy evidence quote"
    )
    if exact_span != quote:
        transformations.append("unique_evidence_quote_aligned")
    if exact_span not in reason:
        normalized["reason"] = (
            reason.rstrip() + "\n\nRuntime evidence: " + exact_span
        )
        transformations.append("runtime_evidence_binding_attached")
    if not transformations:
        return None
    canonical = _PlanningFacetCanonicalShape.model_validate(normalized)
    canonical_payload = canonical.model_dump(mode="python")
    if canonical_payload["plan_evidence_quote"] not in str(
        evidence_candidates[evidence_id]
    ) or canonical_payload["plan_evidence_quote"] not in canonical_payload["reason"]:
        raise ValueError("planning facet adapter produced an unbound evidence quote")
    descriptor = PLANNING_FACET_UNIQUE_EVIDENCE_ADAPTER
    proof = {
        "selected_evidence_ids_sha256": canonical_sha256(evidence_ids),
        "selected_evidence_sha256": canonical_sha256(selected_sources),
        "source_quote_sha256": canonical_sha256(quote),
        "canonical_quote_sha256": canonical_sha256(exact_span),
        "reason_sha256": canonical_sha256(reason),
        "unique_alignment_count": len(aligned),
    }
    return canonical_payload, ContractAdapterAudit(
        adapter_name=descriptor.name,
        adapter_version=descriptor.version,
        contract_name=descriptor.contract_name,
        source_shape=source_shape,
        canonical_shape=descriptor.canonical_shape,
        transformations=tuple(transformations),
        input_sha256=canonical_sha256(payload),
        output_sha256=canonical_sha256(canonical_payload),
        proof_sha256=canonical_sha256(proof),
    )


def _planning_event_id(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = normalized.strip().replace("－", "-").upper()
    match = re.fullmatch(r"(EV-[0-9A-F]{8})(?:-[A-Z0-9_-]+)?", normalized)
    return match.group(1) if match else ""


def _planning_event_key(value: object) -> str:
    return re.sub(
        r"[^0-9a-z_]+", "_",
        unicodedata.normalize("NFKC", str(value or ""))
        .strip().casefold().replace("-", "_").replace(" ", "_"),
    ).strip("_")


def _adapt_planning_event_topology(
    payload: dict[str, Any], *, expected_event_ids: Sequence[str],
) -> tuple[dict[str, Any], ContractAdapterAudit] | None:
    """Align provider-independent container topology to the event IR."""

    expected = [_planning_event_id(value) for value in expected_event_ids]
    if not expected or any(not value for value in expected):
        raise ValueError("planning event adapter received invalid expected ownership")
    narrative_fields = (
        "narrative", "narrative_summary", "event_body", "description",
        "summary", "causal_plan", "resolution", "realization",
    )
    identity_fields = frozenset({"event_id", "id"})
    control_fields = frozenset({
        "command", "commands", "control", "control_action", "mutation", "op",
        "operation", "operations", "patch", "patches", "repair_operation",
        "review_decision",
    })
    wrapper_scalar_fields = frozenset({"name", "type", "role", "status"})
    records: list[dict[str, str]] = []
    paths: list[tuple[str, ...]] = []
    unsafe: list[str] = []

    def visit(node: object, path: tuple[str, ...], inherited_id: str = "") -> None:
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, path + (str(index),))
            return
        if not isinstance(node, dict):
            return
        normalized: dict[str, tuple[str, object]] = {}
        for raw_key, child in node.items():
            key = _planning_event_key(raw_key)
            if not key:
                raise ValueError("planning event adapter found an empty field name")
            if key in normalized:
                raise ValueError(
                    "planning event adapter found a Unicode-normalized key collision"
                )
            normalized[key] = (str(raw_key), child)
        for key in normalized:
            if key in control_fields:
                unsafe.append(".".join(path + (normalized[key][0],)))
        direct_ids = {
            _planning_event_id(normalized[key][1])
            for key in identity_fields if key in normalized
        } - {""}
        if len(direct_ids) > 1:
            raise ValueError("planning event adapter found conflicting identities")
        direct_id = next(iter(direct_ids), "")
        if inherited_id and direct_id and inherited_id != direct_id:
            raise ValueError("planning event mapping conflicts with child identity")
        owner = inherited_id or direct_id
        narrative_values = [
            str(normalized[field][1]).strip()
            for field in narrative_fields
            if field in normalized
            and isinstance(normalized[field][1], str)
            and str(normalized[field][1]).strip()
        ]
        if len(set(narrative_values)) > 1:
            raise ValueError(
                "planning event adapter found conflicting narrative aliases"
            )
        narrative = narrative_values[0] if narrative_values else ""
        if owner and narrative:
            unknown = set(normalized) - identity_fields - set(narrative_fields)
            if unknown:
                raise ValueError(
                    "planning event adapter found unknown event-record fields: "
                    + ", ".join(sorted(unknown))
                )
            records.append({"event_id": owner, "narrative": narrative})
            paths.append(path)
            return
        for raw_key, child in node.items():
            mapped_id = _planning_event_id(raw_key)
            if (
                mapped_id
                and isinstance(child, str)
                and child.strip()
            ):
                records.append({
                    "event_id": mapped_id,
                    "narrative": child.strip(),
                })
                paths.append(path + (str(raw_key),))
                continue
            normalized_key = _planning_event_key(raw_key)
            if not isinstance(child, (dict, list)) and child is not None:
                if normalized_key not in wrapper_scalar_fields:
                    raise ValueError(
                        "planning event adapter found an unknown wrapper scalar: "
                        + str(raw_key)
                    )
                if (
                    normalized_key == "name"
                    and str(child).strip()
                    and _planning_event_key(child) != "planning_event_realizations"
                ):
                    raise ValueError(
                        "planning event adapter found a conflicting tool name"
                    )
            visit(child, path + (str(raw_key),), inherited_id=mapped_id)

    visit(payload, ())
    if unsafe:
        raise ValueError(
            "planning event adapter found unknown machine controls: "
            + ", ".join(sorted(set(unsafe)))
        )
    actual = [item["event_id"] for item in records]
    if actual != expected or len(actual) != len(set(actual)):
        return None
    canonical = _PlanningEventCanonicalShape.model_validate({
        "events": records,
    }).model_dump(mode="python")
    if payload == canonical:
        return None
    path_text = [".".join(path) for path in paths]
    if any(_planning_event_key(part) in {"tool_call", "arguments"} for path in paths for part in path):
        source_shape = "tool arguments or unseen nested envelope"
    elif any(path and _planning_event_id(path[-1]) for path in paths):
        source_shape = "event identity keyed mapping"
    elif all(len(path) <= 2 for path in paths):
        source_shape = "nested ordered event record array"
    else:
        source_shape = "tool arguments or unseen nested envelope"
    descriptor = PLANNING_EVENT_TOPOLOGY_ADAPTER
    proof = {
        "expected_event_ids_sha256": canonical_sha256(expected),
        "actual_event_ids_sha256": canonical_sha256(actual),
        "source_paths_sha256": canonical_sha256(path_text),
        "event_count": len(actual),
    }
    return canonical, ContractAdapterAudit(
        adapter_name=descriptor.name,
        adapter_version=descriptor.version,
        contract_name=descriptor.contract_name,
        source_shape=source_shape,
        canonical_shape=descriptor.canonical_shape,
        transformations=("planning_event_topology_aligned",),
        input_sha256=canonical_sha256(payload),
        output_sha256=canonical_sha256(canonical),
        proof_sha256=canonical_sha256(proof),
    )


def _evidence_reference_key(value: object) -> str:
    """Normalize presentation only; never infer or summarize narrative meaning."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _execution_event_evidence_catalog(
    expected_events: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[tuple[str, str], ...]]:
    catalog: dict[str, tuple[tuple[str, str], ...]] = {}
    globally_bound: dict[str, str] = {}
    for raw_event in expected_events:
        event_id = str(raw_event.get("id") or "").strip().upper()
        if not event_id:
            continue
        entries: list[tuple[str, str]] = []
        raw_entries = raw_event.get("evidence_catalog")
        if isinstance(raw_entries, list):
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, Mapping):
                    raise ValueError("execution evidence catalog entry must be an object")
                evidence_id = str(raw_entry.get("evidence_id") or "").strip()
                evidence = str(raw_entry.get("text") or "").strip()
                if not evidence_id or not evidence:
                    raise ValueError("execution evidence catalog entry is incomplete")
                entries.append((evidence_id, evidence))
        if not entries:
            evidence = str(raw_event.get("evidence") or "").strip()
            if evidence:
                digest = hashlib.sha256(
                    (event_id + "\0" + evidence).encode("utf-8")
                ).hexdigest().upper()
                entries.append((f"EXEC-{digest[:24]}", evidence))
        if not entries:
            raise ValueError("execution event has no Runtime evidence catalog")
        ids = [evidence_id for evidence_id, _ in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("execution event evidence IDs must be unique")
        for evidence_id, evidence in entries:
            previous = globally_bound.get(evidence_id)
            if previous is not None and previous != evidence:
                raise ValueError("execution evidence ID has conflicting Runtime text")
            globally_bound[evidence_id] = evidence
        catalog[event_id] = tuple(entries)
    return catalog


def _unique_contiguous_evidence_ids(
    evidence: str, candidates: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    key = _evidence_reference_key(evidence)
    if not key:
        return ()
    atom_keys = tuple(_evidence_reference_key(text) for _, text in candidates)
    joined = "".join(atom_keys)
    boundaries: list[tuple[int, int]] = []
    cursor = 0
    for atom_key in atom_keys:
        boundaries.append((cursor, cursor + len(atom_key)))
        cursor += len(atom_key)
    matches: list[tuple[str, ...]] = []
    offset = 0
    while True:
        start = joined.find(key, offset)
        if start < 0:
            break
        end = start + len(key)
        owned = tuple(
            evidence_id
            for (evidence_id, _), (atom_start, atom_end)
            in zip(candidates, boundaries, strict=True)
            if atom_start < end and atom_end > start
        )
        if owned:
            matches.append(owned)
        offset = start + 1
    unique = list(dict.fromkeys(matches))
    if len(unique) > 1:
        raise ValueError("execution source evidence has multiple Runtime mappings")
    return unique[0] if unique else ()


def _adapt_execution_manifest_evidence_references(
    payload: dict[str, Any], *, expected_events: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ContractAdapterAudit] | None:
    raw_beats = payload.get("beats")
    if not isinstance(raw_beats, list):
        return None
    catalog = _execution_event_evidence_catalog(expected_events)
    canonical = dict(payload)
    canonical_beats: list[Any] = []
    transformations: set[str] = set()
    proof_rows: list[dict[str, Any]] = []
    changed = False
    for raw_beat in raw_beats:
        if not isinstance(raw_beat, Mapping):
            canonical_beats.append(raw_beat)
            continue
        beat = dict(raw_beat)
        event_id = str(beat.get("source_event_id") or "").strip().upper()
        candidates = catalog.get(event_id)
        if candidates is None:
            raise ValueError("execution beat references an unknown Runtime event")
        candidate_ids = tuple(item[0] for item in candidates)
        raw_ids = beat.get("source_evidence_ids")
        selected: tuple[str, ...] = ()
        source_shape = "Runtime evidence ID references"
        if raw_ids is not None:
            if (
                not isinstance(raw_ids, list)
                or not raw_ids
                or any(not isinstance(value, str) or not value.strip() for value in raw_ids)
            ):
                raise ValueError("source_evidence_ids must be a non-empty string list")
            selected = tuple(value.strip() for value in raw_ids)
            if len(selected) != len(set(selected)):
                raise ValueError("source_evidence_ids must not contain duplicates")
            start_indexes = [
                index for index in range(len(candidate_ids))
                if candidate_ids[index:index + len(selected)] == selected
            ]
            if len(start_indexes) != 1:
                raise ValueError(
                    "source_evidence_ids are unknown, cross-event, or non-contiguous"
                )
            transformations.add("execution_evidence_ids_verified")
        else:
            legacy = str(beat.get("source_evidence") or "").strip()
            if legacy:
                selected = _unique_contiguous_evidence_ids(legacy, candidates)
                if not selected:
                    raise ValueError(
                        "legacy source evidence has no exact Runtime mapping"
                    )
                canonical_text = "\n\n".join(
                    text for evidence_id, text in candidates
                    if evidence_id in selected
                )
                source_shape = (
                    "legacy exact Runtime evidence echo"
                    if legacy == canonical_text else
                    "unique presentation-normalized extractive Runtime evidence echo"
                )
                transformations.add("execution_legacy_evidence_mapped")
            elif len(candidates) == 1:
                selected = (candidates[0][0],)
                source_shape = "omitted evidence with one Runtime candidate"
                transformations.add("execution_single_evidence_bound")
            else:
                raise ValueError(
                    "execution beat omitted evidence with multiple Runtime candidates"
                )
        legacy = str(beat.get("source_evidence") or "").strip()
        if legacy and raw_ids is not None:
            legacy_ids = _unique_contiguous_evidence_ids(legacy, candidates)
            if legacy_ids != selected:
                raise ValueError("execution evidence text conflicts with evidence IDs")
        if beat.get("source_evidence_ids") != list(selected) or "source_evidence" in beat:
            changed = True
        beat["source_evidence_ids"] = list(selected)
        beat.pop("source_evidence", None)
        canonical_beats.append(beat)
        proof_rows.append({
            "event_authority_sha256": canonical_sha256(candidates),
            "selected_sha256": canonical_sha256(selected),
            "candidate_count": len(candidates),
            "reference_count": len(selected),
            "source_shape": source_shape,
        })
    if not changed:
        return None
    canonical["beats"] = canonical_beats
    descriptor = EXECUTION_MANIFEST_EVIDENCE_REFERENCE_ADAPTER
    return canonical, ContractAdapterAudit(
        adapter_name=descriptor.name,
        adapter_version=descriptor.version,
        contract_name=descriptor.contract_name,
        source_shape="; ".join(sorted({row["source_shape"] for row in proof_rows})),
        canonical_shape=descriptor.canonical_shape,
        transformations=tuple(sorted(transformations)),
        input_sha256=canonical_sha256(payload),
        output_sha256=canonical_sha256(canonical),
        proof_sha256=canonical_sha256({
            "rows": proof_rows,
            "beat_count": len(proof_rows),
        }),
    )


def _apply_registered_adapter(
    payload: dict[str, Any], descriptor: ContractAdapterRegistration,
    *, context: Mapping[str, Any],
) -> tuple[dict[str, Any], ContractAdapterAudit] | None:
    """Dispatch one registry descriptor; the registry is executable authority."""

    if descriptor.name == PLANNING_FACET_CLOSED_TRUTH_ADAPTER.name:
        return _adapt_planning_facet_closed_truth(
            payload,
            invariant_fields=tuple(context.get("invariant_fields") or ()),
        )
    if descriptor.name == PLANNING_FACET_UNIQUE_EVIDENCE_ADAPTER.name:
        return _adapt_planning_facet_unique_evidence(
            payload,
            invariant_fields=tuple(context.get("invariant_fields") or ()),
            evidence_candidates=dict(context.get("evidence_candidates") or {}),
        )
    if descriptor.name == PLANNING_EVENT_TOPOLOGY_ADAPTER.name:
        return _adapt_planning_event_topology(
            payload,
            expected_event_ids=tuple(context.get("expected_event_ids") or ()),
        )
    if descriptor.name == PLANNING_SEMANTIC_ENVELOPE_ADAPTER.name:
        semantic_normalizer = context.get("semantic_normalizer")
        if not callable(semantic_normalizer):
            return None
        adapted = _unique_semantic_envelope(payload, semantic_normalizer)
        if adapted is None:
            return None
        canonical, transformations, candidate_count = adapted
        return canonical, ContractAdapterAudit(
            adapter_name=descriptor.name,
            adapter_version=descriptor.version,
            contract_name=descriptor.contract_name,
            source_shape=descriptor.source_shapes[-1],
            canonical_shape=descriptor.canonical_shape,
            transformations=transformations,
            input_sha256=canonical_sha256(payload),
            output_sha256=canonical_sha256(canonical),
            proof_sha256=canonical_sha256({
                "candidate_count": candidate_count,
                "source_path_sha256": canonical_sha256(transformations[1:]),
            }),
        )
    if descriptor.name == PLANNING_SEMANTIC_ROOT_PROJECTION_ADAPTER.name:
        semantic_normalizer = context.get("semantic_normalizer")
        return _adapt_planning_semantic_root_projection(
            payload,
            semantic_normalizer=(
                semantic_normalizer if callable(semantic_normalizer) else None
            ),
        )
    if descriptor.name == EXECUTION_MANIFEST_EVIDENCE_REFERENCE_ADAPTER.name:
        expected_events = tuple(
            item for item in context.get("expected_events", ())
            if isinstance(item, Mapping)
        )
        return _adapt_execution_manifest_evidence_references(
            payload, expected_events=expected_events,
        )
    if descriptor.name == REFERENCE_DISTILLATION_LEDGER_ADAPTER.name:
        return _adapt_reference_distillation_v2_ledger(payload)
    raise RuntimeError(f"contract adapter has no implementation: {descriptor.name}")


def adapt_registered_contract(
    payload: Mapping[str, Any], *, contract_name: str,
    context: Mapping[str, Any] | None = None,
    automatic_only: bool = False,
) -> ContractAdaptationResult:
    """Apply registered, proved adapters before authoritative domain validation."""

    if contract_name not in ARTIFACT_CONTRACT_REGISTRY:
        raise KeyError(f"unregistered generated artifact contract: {contract_name}")
    current = dict(payload)
    audits: list[ContractAdapterAudit] = []
    adapter_context = dict(context or {})
    for descriptor in CONTRACT_ADAPTER_REGISTRY.get(contract_name, ()):
        if automatic_only and not descriptor.automatic_conversion:
            continue
        adapted = _apply_registered_adapter(
            current, descriptor, context=adapter_context,
        )
        if adapted is None:
            continue
        current, audit = adapted
        audits.append(audit)
    return ContractAdaptationResult(payload=current, audits=tuple(audits))


class AmbiguousSemanticEnvelopeError(ValueError):
    """More than one complete semantic candidate survived local proof."""


class StructurallyTruncatedArtifactError(ValueError):
    """The response ended before its top-level JSON object was closed."""


class ArtifactConversionError(ValueError):
    def __init__(self, message: str, *, audit: ArtifactConversionAudit) -> None:
        super().__init__(message)
        self.audit = audit
        failure_class = (
            FailureClass.OUTPUT_TRUNCATION
            if audit.failure_code == "output_truncated"
            else
            FailureClass.OWNERSHIP_EVIDENCE
            if audit.failure_code in {
                "event_ownership_mismatch", "unknown_machine_control",
            }
            else FailureClass.SYNTAX_PROTOCOL
        )
        self.reliability_failure = ReliabilityFailure(
            audit.failure_code or "generated_artifact_conversion",
            failure_class,
            "generated_artifact_gateway",
            protocol_only=failure_class == FailureClass.SYNTAX_PROTOCOL,
        )


SemanticNormalizer = Callable[[object], dict[str, Any] | None]


def _raw_sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def _walk(value: object, path: str = "$") -> Iterator[tuple[str, object]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _cycle_array_candidates(value: object) -> list[tuple[str, list[dict[str, Any]]]]:
    """Locate cycle-like arrays by topology, never by provider-specific aliases."""

    candidates: list[tuple[str, list[dict[str, Any]]]] = []
    for path, child in _walk(value):
        if not isinstance(child, list) or not child:
            continue
        if not all(isinstance(item, dict) for item in child):
            continue
        if all(sum(_has_value(v) for v in item.values()) >= 4 for item in child):
            candidates.append((path, child))
    return candidates


def _has_closed_json_object(raw: str) -> bool:
    """Prove container closure before syntax repair; never heal truncation."""

    stack: list[str] = []
    in_string = False
    quote = ""
    escaped = False
    started = False
    for character in raw:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                in_string = False
            continue
        if character in {'"', "'"} and stack:
            in_string = True
            quote = character
            continue
        if character in "{[":
            started = True
            stack.append(character)
            continue
        if character not in "}]" or not stack:
            continue
        expected = "{" if character == "}" else "["
        if stack[-1] != expected:
            return False
        stack.pop()
    return started and not stack and not in_string


def _json_candidate(
    raw: str, *, allow_syntax_repair: bool,
) -> tuple[dict[str, Any], str, tuple[str, ...]]:
    try:
        return parse_json_object(raw, label="Generated artifact"), "exact_json", ()
    except (TypeError, ValueError, json.JSONDecodeError) as exact_error:
        if isinstance(
            exact_error,
            (MultipleJSONObjectError, AdditionalMalformedJSONValueError),
        ):
            raise ValueError(str(exact_error)) from exact_error
        if not allow_syntax_repair:
            raise ValueError(str(exact_error)) from exact_error
        if not _has_closed_json_object(raw):
            raise StructurallyTruncatedArtifactError(
                "generated artifact is structurally truncated"
            ) from exact_error
        try:
            repaired = repair_json(raw, return_objects=True)
        except Exception as repair_error:  # library errors are an input boundary
            raise ValueError(str(repair_error)) from exact_error
        if not isinstance(repaired, dict):
            raise ValueError("repaired output is not one unambiguous JSON object") from exact_error
        return repaired, "local_syntax_repair", ("json_syntax_repaired",)


def _baml_causal_cycles(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Import lazily so non-structured/text-only workflows do not pay the BAML
    # runtime startup cost and packaging failures remain isolated to this rung.
    from novel_flywheel.baml_client.baml_client.sync_client import b

    parsed = b.parse.ParseCausalCycles(json.dumps(
        value, ensure_ascii=False, separators=(",", ":"),
    ))
    cycles = [item.model_dump(mode="python") for item in parsed]
    if len(cycles) != len(value) or not cycles:
        raise ValueError("BAML did not align every causal-cycle element")
    return cycles


def _has_expected_ownership(value: object, expected_event_ids: Sequence[str]) -> bool:
    expected = [str(item or "").strip().upper() for item in expected_event_ids]
    if not expected:
        return True
    return any(
        isinstance(child, list)
        and [str(item or "").strip().upper() for item in child] == expected
        for _, child in _walk(value)
        if isinstance(child, list) and all(isinstance(item, str) for item in child)
    )


def _unsafe_machine_control_keys(value: Mapping[str, Any]) -> list[str]:
    terms = (
        "skip", "override", "authorize", "operation", "patch", "tool_call",
        "machine_control", "bypass", "promote",
    )
    unsafe: list[str] = []
    for path, child in _walk(dict(value)):
        if path == "$" or "." not in path:
            continue
        key = path.rsplit(".", 1)[-1].split("[", 1)[0]
        normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold())
        if any(term in normalized for term in terms):
            unsafe.append(path)
    return unsafe


class GeneratedArtifactGateway:
    """Single tolerant conversion boundary with strict semantic authority."""

    def convert_object(
        self,
        raw: str,
        *,
        contract_name: str,
        semantic_normalizer: SemanticNormalizer | None = None,
        expected_event_ids: Sequence[str] = (),
        owns_opening: bool = True,
        owns_ending: bool = True,
    ) -> ArtifactConversionResult:
        registration = ARTIFACT_CONTRACT_REGISTRY.get(contract_name)
        if registration is None:
            raise KeyError(f"unregistered generated artifact contract: {contract_name}")
        raw_digest = _raw_sha256(raw)
        try:
            payload, method, transformations = _json_candidate(
                raw,
                allow_syntax_repair=(
                    "local_syntax_repair" in registration.recovery_ladder
                ),
            )
        except ValueError as exc:
            failure_code = (
                "output_truncated"
                if isinstance(exc, StructurallyTruncatedArtifactError)
                else "json_object_unavailable"
            )
            audit = ArtifactConversionAudit(
                contract_name=contract_name,
                contract_version=registration.version,
                raw_sha256=raw_digest,
                method="rejected",
                failure_code=failure_code,
            )
            raise ArtifactConversionError(str(exc), audit=audit) from exc

        quarantined: list[str] = []
        candidate_count = 1
        if (
            registration.parser_strategy == "baml_sap"
            and "baml_sap" in registration.recovery_ladder
        ):
            canonical_fast_path = isinstance(payload.get("cycles"), list)
            candidates = (
                [("$.cycles", payload["cycles"])]
                if canonical_fast_path else _cycle_array_candidates(payload)
            )
            candidate_count = len(candidates)
            if candidate_count != 1:
                audit = ArtifactConversionAudit(
                    contract_name=contract_name,
                    contract_version=registration.version,
                    raw_sha256=raw_digest,
                    method="rejected",
                    transformations=transformations,
                    candidate_count=candidate_count,
                    failure_code="ambiguous_structural_candidates",
                )
                raise ArtifactConversionError(
                    "causal artifact does not contain exactly one cycle topology",
                    audit=audit,
                )
            candidate_path, cycle_candidate = candidates[0]
            if not canonical_fast_path:
                if not _has_expected_ownership(payload, expected_event_ids):
                    audit = ArtifactConversionAudit(
                        contract_name=contract_name,
                        contract_version=registration.version,
                        raw_sha256=raw_digest,
                        method="rejected",
                        transformations=transformations,
                        candidate_count=candidate_count,
                        failure_code="event_ownership_mismatch",
                    )
                    raise ArtifactConversionError(
                        "causal artifact did not preserve ordered event ownership",
                        audit=audit,
                    )
                try:
                    cycles = _baml_causal_cycles(cycle_candidate)
                except Exception as exc:
                    audit = ArtifactConversionAudit(
                        contract_name=contract_name,
                        contract_version=registration.version,
                        raw_sha256=raw_digest,
                        method="rejected",
                        transformations=transformations,
                        candidate_count=candidate_count,
                        failure_code="baml_alignment_failed",
                    )
                    raise ArtifactConversionError(str(exc), audit=audit) from exc
                expected = [str(item or "").strip().upper()
                            for item in expected_event_ids]
                payload["cycles"] = cycles
                payload["covered_event_ids"] = expected
                transformations += ("baml_structural_alignment",)
                quarantined.append(candidate_path)
                method = "baml_sap"

            if not owns_opening:
                for key in ("core_goal", "opening"):
                    if _has_value(payload.get(key)):
                        quarantined.append(f"$.{key}")
                    payload[key] = "" if key == "core_goal" else {}
            if not owns_ending and _has_value(payload.get("ending")):
                quarantined.append("$.ending")
                payload["ending"] = ""

        unsafe = (
            _unsafe_machine_control_keys(payload)
            if registration.parser_strategy == "baml_sap" else []
        )
        if unsafe:
            audit = ArtifactConversionAudit(
                contract_name=contract_name,
                contract_version=registration.version,
                raw_sha256=raw_digest,
                method="rejected",
                transformations=transformations,
                quarantined_paths=tuple(sorted(set(quarantined))),
                candidate_count=candidate_count,
                failure_code="unknown_machine_control",
            )
            raise ArtifactConversionError(
                "generated artifact contains unknown machine-control fields",
                audit=audit,
            )

        source_root_keys = set(payload)
        try:
            adaptation = adapt_registered_contract(
                payload,
                contract_name=contract_name,
                context={
                    "semantic_normalizer": semantic_normalizer,
                    "expected_event_ids": tuple(expected_event_ids),
                },
                automatic_only=True,
            )
        except ValueError as exc:
            ambiguous = isinstance(exc, AmbiguousSemanticEnvelopeError)
            audit = ArtifactConversionAudit(
                contract_name=contract_name,
                contract_version=registration.version,
                raw_sha256=raw_digest,
                method="rejected",
                transformations=transformations,
                quarantined_paths=tuple(sorted(set(quarantined))),
                candidate_count=(2 if ambiguous else candidate_count),
                failure_code=(
                    "ambiguous_semantic_candidates"
                    if ambiguous else "contract_adaptation_failed"
                ),
            )
            raise ArtifactConversionError(str(exc), audit=audit) from exc
        if adaptation.audits:
            payload = adaptation.payload
            transformations += tuple(
                transformation
                for adapter_audit in adaptation.audits
                for transformation in adapter_audit.transformations
            )
            quarantined.extend(
                f"$.{key}" for key in sorted(source_root_keys - set(payload))
            )
            if any(
                audit.adapter_name == PLANNING_SEMANTIC_ENVELOPE_ADAPTER.name
                for audit in adaptation.audits
            ):
                candidate_count = 1
            method = "baml_sap"

        normalized = (
            _try_semantic_normalizer(semantic_normalizer, payload)
            if semantic_normalizer is not None else payload
        )
        if not isinstance(normalized, dict):
            audit = ArtifactConversionAudit(
                contract_name=contract_name,
                contract_version=registration.version,
                raw_sha256=raw_digest,
                method="rejected",
                transformations=transformations,
                quarantined_paths=tuple(sorted(set(quarantined))),
                candidate_count=candidate_count,
                failure_code="semantic_validation_failed",
            )
            raise ArtifactConversionError(
                "generated artifact failed its authoritative semantic contract",
                audit=audit,
            )
        audit = ArtifactConversionAudit(
            contract_name=contract_name,
            contract_version=registration.version,
            raw_sha256=raw_digest,
            canonical_sha256=canonical_sha256(normalized),
            method=method,
            transformations=transformations,
            quarantined_paths=tuple(sorted(set(quarantined))),
            candidate_count=candidate_count,
            semantic_valid=True,
        )
        return ArtifactConversionResult(payload=normalized, audit=audit)


def write_conversion_audit(root: Path, audit: ArtifactConversionAudit) -> Path:
    """Persist an immutable audit without ever storing raw output or secrets."""

    root.mkdir(parents=True, exist_ok=True)
    identity = canonical_sha256(audit.model_dump(mode="json"))
    path = root / f"{audit.contract_name}-{identity[:20]}.json"
    atomic_write(path, audit.model_dump_json(indent=2))
    return path
