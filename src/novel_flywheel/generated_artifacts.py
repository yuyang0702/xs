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
from novel_flywheel.model_output import parse_json_object
from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure
from novel_flywheel.semantic_packets import canonical_sha256
from novel_flywheel.storage import atomic_write


ParserStrategy = Literal["json", "baml_sap"]
ArtifactPhase = Literal["planning", "writing", "quality", "runtime"]


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
    recovery_ladder: tuple[str, ...] = (
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
        name="draft_semantic_receipt", phase="writing",
        semantic_authority="atomic semantic receipt verifier",
    ),
    ArtifactContractRegistration(
        name="polish_assessment", phase="quality",
        semantic_authority="polish authority packet and protected constraints",
    ),
    ArtifactContractRegistration(
        name="revision_plan", phase="quality",
        semantic_authority="normalize_revision_plan",
    ),
    ArtifactContractRegistration(
        name="final_review", phase="quality",
        semantic_authority="review ledger and final review gate",
    ),
    ArtifactContractRegistration(
        name="maintenance_facts", phase="runtime",
        semantic_authority="StoryState maintenance fact validator",
        legacy_labels=("maintenance facts",),
    ),
    ArtifactContractRegistration(
        name="material_audit", phase="quality",
        semantic_authority="material impact and evidence validator",
        legacy_labels=("material impact", "materials audit"),
    ),
    ArtifactContractRegistration(
        name="outline_analysis", phase="planning",
        semantic_authority="outline change and source evidence validator",
        legacy_labels=("资料清单", "大纲变化判断"),
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
        name="capability_probe", phase="runtime",
        semantic_authority="provider capability probe validator",
        legacy_labels=("Capability probe output",),
    ),
)

ARTIFACT_CONTRACT_REGISTRY: Mapping[str, ArtifactContractRegistration] = {
    item.name: item for item in _REGISTRATIONS
}


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


CONTRACT_ADAPTER_REGISTRY: Mapping[str, tuple[ContractAdapterRegistration, ...]] = {
    "planning_adaptation_facet": (
        PLANNING_FACET_CLOSED_TRUTH_ADAPTER,
        PLANNING_FACET_UNIQUE_EVIDENCE_ADAPTER,
    ),
}


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


def adapt_registered_contract(
    payload: Mapping[str, Any], *, contract_name: str,
    context: Mapping[str, Any] | None = None,
) -> ContractAdaptationResult:
    """Apply registered, proved adapters before authoritative domain validation."""

    if contract_name not in ARTIFACT_CONTRACT_REGISTRY:
        raise KeyError(f"unregistered generated artifact contract: {contract_name}")
    current = dict(payload)
    audits: list[ContractAdapterAudit] = []
    for descriptor in CONTRACT_ADAPTER_REGISTRY.get(contract_name, ()):
        if descriptor.name == PLANNING_FACET_CLOSED_TRUTH_ADAPTER.name:
            invariant_fields = tuple((context or {}).get("invariant_fields") or ())
            adapted = _adapt_planning_facet_closed_truth(
                current, invariant_fields=invariant_fields,
            )
        elif descriptor.name == PLANNING_FACET_UNIQUE_EVIDENCE_ADAPTER.name:
            invariant_fields = tuple((context or {}).get("invariant_fields") or ())
            evidence_candidates = dict(
                (context or {}).get("evidence_candidates") or {},
            )
            adapted = _adapt_planning_facet_unique_evidence(
                current,
                invariant_fields=invariant_fields,
                evidence_candidates=evidence_candidates,
            )
        else:  # pragma: no cover - registry construction rejects unowned adapters
            raise RuntimeError(f"contract adapter has no implementation: {descriptor.name}")
        if adapted is None:
            continue
        current, audit = adapted
        audits.append(audit)
    return ContractAdaptationResult(payload=current, audits=tuple(audits))


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
            else FailureClass.SEMANTIC_INVARIANT
            if audit.failure_code == "semantic_validation_failed"
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


def _json_candidate(raw: str) -> tuple[dict[str, Any], str, tuple[str, ...]]:
    try:
        return parse_json_object(raw, label="Generated artifact"), "exact_json", ()
    except (TypeError, ValueError, json.JSONDecodeError) as exact_error:
        if (
            "multiple JSON objects" in str(exact_error)
            or "additional malformed JSON value" in str(exact_error)
        ):
            raise ValueError(str(exact_error)) from exact_error
        if not _has_closed_json_object(raw):
            raise ValueError("generated artifact is structurally truncated") from exact_error
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
            payload, method, transformations = _json_candidate(raw)
        except ValueError as exc:
            failure_code = (
                "output_truncated"
                if "structurally truncated" in str(exc)
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
        if registration.parser_strategy == "baml_sap":
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

        normalized = semantic_normalizer(payload) if semantic_normalizer else payload
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
