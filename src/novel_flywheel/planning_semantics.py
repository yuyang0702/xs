from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Annotated, Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from novel_flywheel.generated_artifacts import (
    ArtifactConversionAudit,
    GeneratedArtifactGateway,
)
from novel_flywheel.planning_compiler import (
    PlanningDocumentExitTopologyIR,
    PlanningDocumentIR,
    PlanningSegmentIR,
    compile_planning_document_ir,
    planning_document_exit_topology,
    render_planning_segment_ir,
)


_EVENT_ID = re.compile(r"^EV-[0-9A-F]{8}$")

PlanningNarrativeText = Annotated[
    str, StringConstraints(strip_whitespace=True, strict=True, min_length=12),
]
PlanningTitleText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, strict=True, min_length=1, max_length=120,
    ),
]
PlanningStateText = Annotated[
    str, StringConstraints(strip_whitespace=True, strict=True, min_length=8),
]


class PlanningSemanticEventV2(BaseModel):
    """Creative realization keyed by a Runtime-visible ordinal, never an ID."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    formal_event_ordinal: int = Field(ge=1)
    narrative: PlanningNarrativeText


class ContinuationPlanningSegmentV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["continuation"] = "continuation"
    segment: int = Field(ge=1)
    title: PlanningTitleText
    events: list[PlanningSemanticEventV2] = Field(min_length=1)
    exit_state: PlanningStateText


class TerminalPlanningSegmentV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["terminal"] = "terminal"
    segment: int = Field(ge=1)
    title: PlanningTitleText
    events: list[PlanningSemanticEventV2] = Field(min_length=1)


PlanningSemanticSegmentV2 = Annotated[
    ContinuationPlanningSegmentV2 | TerminalPlanningSegmentV2,
    Field(discriminator="kind"),
]


class PlanningSemanticDraftV2(BaseModel):
    """Model-owned semantic payload; all control identities stay Runtime-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[2] = 2
    initial_state: PlanningStateText
    segments: list[PlanningSemanticSegmentV2] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_topology(self) -> "PlanningSemanticDraftV2":
        if tuple(item.segment for item in self.segments) != tuple(
            range(1, len(self.segments) + 1)
        ):
            raise ValueError("planning semantic segments must be contiguous")
        if not isinstance(self.segments[-1], TerminalPlanningSegmentV2):
            raise ValueError("last planning semantic segment must be terminal")
        if any(
            isinstance(item, TerminalPlanningSegmentV2)
            for item in self.segments[:-1]
        ):
            raise ValueError("only the final planning semantic segment may be terminal")
        for item in self.segments:
            ordinals = [event.formal_event_ordinal for event in item.events]
            if len(ordinals) != len(set(ordinals)):
                raise ValueError("one segment cannot repeat a formal event ordinal")
        return self


@dataclass(frozen=True)
class CompiledSemanticPlanningV2:
    semantic: PlanningSemanticDraftV2
    plan: str
    document: PlanningDocumentIR
    exit_topology: PlanningDocumentExitTopologyIR
    conversion_audit: ArtifactConversionAudit


def planning_semantic_schema_v2() -> dict[str, Any]:
    return PlanningSemanticDraftV2.model_json_schema()


def parse_planning_semantic_v2(
    raw: str,
) -> tuple[PlanningSemanticDraftV2, ArtifactConversionAudit]:
    """Use the shared tolerant syntax boundary, then strict Pydantic semantics."""

    def normalize(payload: object) -> dict[str, Any] | None:
        try:
            semantic = PlanningSemanticDraftV2.model_validate(payload)
        except ValueError:
            return None
        return semantic.model_dump(mode="json")

    result = GeneratedArtifactGateway().convert_object(
        raw, contract_name="planning_semantic_v2",
        semantic_normalizer=normalize,
    )
    return PlanningSemanticDraftV2.model_validate(result.payload), result.audit


def compile_planning_semantic_v2(
    semantic: PlanningSemanticDraftV2,
    formal_events: Iterable[dict[str, Any]],
    *, formal_ending: dict[str, Any], expected_segment_count: int,
    retained_open_obligation_ids: Iterable[str] = (),
    conversion_audit: ArtifactConversionAudit | None = None,
) -> CompiledSemanticPlanningV2:
    """Inject IDs/boundaries and prove exact ownership before rendering Markdown."""

    events = tuple(dict(item) for item in formal_events)
    if len(semantic.segments) != expected_segment_count:
        raise ValueError("planning semantic segment count mismatch")
    if not events:
        raise ValueError("IR-first planning requires formal events")
    event_ids = tuple(
        str(item.get("id") or item.get("event_id") or "").strip().upper()
        for item in events
    )
    if any(_EVENT_ID.fullmatch(event_id) is None for event_id in event_ids):
        raise ValueError("IR-first planning received invalid formal event IDs")
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("IR-first planning formal event IDs must be unique")

    collapsed: list[int] = []
    seen: set[int] = set()
    for segment in semantic.segments:
        for event in segment.events:
            ordinal = event.formal_event_ordinal
            if ordinal > len(events):
                raise ValueError("planning semantic event ordinal is outside formal authority")
            if collapsed and collapsed[-1] == ordinal:
                continue
            if ordinal in seen:
                raise ValueError("planning semantic event ownership re-enters non-contiguously")
            collapsed.append(ordinal)
            seen.add(ordinal)
    if tuple(collapsed) != tuple(range(1, len(events) + 1)):
        raise ValueError("planning semantic segments do not exactly cover formal events")

    rendered_segments: list[str] = []
    opening = semantic.initial_state.strip()
    for segment in semantic.segments:
        owned_ordinals = tuple(item.formal_event_ordinal for item in segment.events)
        owned_events = tuple(events[index - 1] for index in owned_ordinals)
        owned_ids = tuple(event_ids[index - 1] for index in owned_ordinals)
        outline_basis = "\n\n".join(
            str(item.get("evidence") or item.get("label") or "").strip()
            for item in owned_events
        ).strip()
        if not outline_basis:
            raise ValueError("formal event evidence is required for planning authority")
        event_body = "\n\n".join(
            f"{event_ids[item.formal_event_ordinal - 1]}\n{item.narrative.strip()}"
            for item in segment.events
        )
        if isinstance(segment, ContinuationPlanningSegmentV2):
            handoff = segment.exit_state.strip()
        else:
            # Compatibility presentation for the legacy five-field reader.
            # The machine terminal authority remains the discriminated exit
            # topology built below, so this is never interpreted as a next hop.
            handoff = str(
                events[-1].get("evidence") or formal_ending.get("evidence") or ""
            ).strip()
            if not handoff:
                raise ValueError("terminal compatibility projection lacks formal evidence")
        provisional = PlanningSegmentIR(
            segment=segment.segment,
            heading=f"### Segment {segment.segment}: {segment.title.strip()}",
            event_ids=owned_ids,
            outline=outline_basis,
            opening=opening,
            event_body=event_body,
            handoff=handoff,
            source_sha256="0" * 64,
        )
        rendered = render_planning_segment_ir(provisional)
        final_ir = provisional.model_copy(update={
            "source_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        })
        rendered = render_planning_segment_ir(final_ir)
        rendered_segments.append(rendered)
        if isinstance(segment, ContinuationPlanningSegmentV2):
            opening = segment.exit_state.strip()

    plan = "\n\n".join(rendered_segments).strip()
    document = compile_planning_document_ir(plan, rendered_segments)
    topology = planning_document_exit_topology(
        document.segments, events, formal_ending=formal_ending,
        retained_open_obligation_ids=retained_open_obligation_ids,
    )
    audit = conversion_audit or ArtifactConversionAudit(
        contract_name="planning_semantic_v2", contract_version=2,
        raw_sha256=hashlib.sha256(
            semantic.model_dump_json().encode("utf-8"),
        ).hexdigest(),
        canonical_sha256=hashlib.sha256(
            semantic.model_dump_json().encode("utf-8"),
        ).hexdigest(),
        method="exact_json", semantic_valid=True, candidate_count=1,
    )
    return CompiledSemanticPlanningV2(
        semantic=semantic, plan=plan, document=document,
        exit_topology=topology, conversion_audit=audit,
    )


def semantic_planning_prompt_v2(
    *, segment_count: int, formal_events: Iterable[dict[str, Any]],
    story_brief: str,
) -> str:
    event_catalog = [{
        "ordinal": index,
        "label": str(event.get("label") or ""),
        "evidence": str(event.get("evidence") or ""),
    } for index, event in enumerate(formal_events, 1)]
    return (
        "IR_FIRST_SHORT_PLANNING_V2\n"
        "Return one JSON object matching the supplied schema. Do not return Markdown, "
        "event IDs, hashes, tool calls, or machine-control fields. Use formal_event_ordinal "
        "to claim every formal event in exact order. Adjacent segments may share one ordinal "
        "only when they split one continuous event; an ordinal may never re-enter later. "
        f"Return exactly {segment_count} contiguous segments. Segments 1 through "
        f"{max(0, segment_count - 1)} use kind=continuation and a concrete exit_state. "
        "Only the last segment uses kind=terminal and must not invent a next handoff. "
        "Each event narrative must preserve actor agency, chronology, knowledge, relationship "
        "state, promises, ending logic, and genre-specific voice while stating executable "
        "action, resistance/response, result, and state change. The Runtime binds identities, "
        "outline evidence, adjacency, and terminal authority.\n\n"
        "STORY BRIEF:\n" + story_brief + "\n\nFORMAL EVENT CATALOG:\n"
        + json.dumps(event_catalog, ensure_ascii=False, indent=2)
    )
