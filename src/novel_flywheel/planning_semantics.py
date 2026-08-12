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


def planning_semantic_packet_ownership_v2(
    *, segment_count: int, formal_event_count: int,
) -> tuple[tuple[int, ...], ...]:
    """Assign every Runtime event ordinal to contiguous semantic packets.

    When there are fewer formal events than requested writing segments, an
    event may be shared only by adjacent segments.  The document compiler
    later collapses that adjacent ownership and proves exact global coverage.
    """

    if segment_count < 1:
        raise ValueError("planning semantic packet count must be positive")
    if formal_event_count < 1:
        raise ValueError("planning semantic packets require formal events")
    if formal_event_count >= segment_count:
        groups = tuple(
            tuple(range(
                (index * formal_event_count) // segment_count + 1,
                ((index + 1) * formal_event_count) // segment_count + 1,
            ))
            for index in range(segment_count)
        )
    else:
        groups = tuple(
            (min(
                formal_event_count,
                (index * formal_event_count) // segment_count + 1,
            ),)
            for index in range(segment_count)
        )
    if any(not group for group in groups):
        raise ValueError("planning semantic packet ownership cannot be empty")
    collapsed: list[int] = []
    for group in groups:
        for ordinal in group:
            if not collapsed or collapsed[-1] != ordinal:
                collapsed.append(ordinal)
    if tuple(collapsed) != tuple(range(1, formal_event_count + 1)):
        raise ValueError("planning semantic packet ownership is not lossless")
    return groups


def _validated_packet_segment(
    packet: PlanningSemanticDraftV2, owned_ordinals: tuple[int, ...],
) -> TerminalPlanningSegmentV2:
    if len(packet.segments) != 1 or not isinstance(
        packet.segments[0], TerminalPlanningSegmentV2,
    ):
        raise ValueError("planning semantic packet must be one terminal local segment")
    if packet.segments[0].segment != 1:
        raise ValueError("planning semantic packet segment identity must be local")
    local_ordinals = tuple(
        item.formal_event_ordinal for item in packet.segments[0].events
    )
    if local_ordinals != tuple(range(1, len(owned_ordinals) + 1)):
        raise ValueError("planning semantic packet does not exactly cover its ownership")
    if any(ordinal < 1 for ordinal in owned_ordinals):
        raise ValueError("planning semantic packet ownership contains an invalid ordinal")
    return packet.segments[0]


def merge_planning_semantic_event_packets_v2(
    packets: Iterable[PlanningSemanticDraftV2],
    owned_ordinal_groups: Iterable[Iterable[int]],
) -> PlanningSemanticDraftV2:
    """Merge recursively split event packets back into one local segment."""

    packet_values = tuple(packets)
    groups = tuple(tuple(item) for item in owned_ordinal_groups)
    if not packet_values or len(packet_values) != len(groups):
        raise ValueError("planning semantic event packet merge is incomplete")
    flattened = tuple(ordinal for group in groups for ordinal in group)
    if flattened != tuple(range(1, len(flattened) + 1)):
        raise ValueError("planning semantic event packets must form one exact local range")
    merged_events: list[PlanningSemanticEventV2] = []
    for packet, group in zip(packet_values, groups, strict=True):
        segment = _validated_packet_segment(packet, group)
        merged_events.extend(
            event.model_copy(update={
                "formal_event_ordinal": group[event.formal_event_ordinal - 1],
            })
            for event in segment.events
        )
    return PlanningSemanticDraftV2(
        initial_state=packet_values[0].initial_state,
        segments=[TerminalPlanningSegmentV2(
            segment=1,
            title=packet_values[0].segments[0].title,
            events=merged_events,
        )],
    )


def merge_planning_semantic_document_packets_v2(
    packets: Iterable[PlanningSemanticDraftV2],
    owned_ordinal_groups: Iterable[Iterable[int]],
    *, formal_event_count: int,
) -> PlanningSemanticDraftV2:
    """Reduce segment-local canonical documents into one canonical document."""

    packet_values = tuple(packets)
    groups = tuple(tuple(item) for item in owned_ordinal_groups)
    if not packet_values or len(packet_values) != len(groups):
        raise ValueError("planning semantic document packet merge is incomplete")
    collapsed: list[int] = []
    seen: set[int] = set()
    for group in groups:
        for ordinal in group:
            if collapsed and collapsed[-1] == ordinal:
                continue
            if ordinal in seen:
                raise ValueError(
                    "planning semantic document packet ownership re-enters non-contiguously"
                )
            collapsed.append(ordinal)
            seen.add(ordinal)
    if tuple(collapsed) != tuple(range(1, formal_event_count + 1)):
        raise ValueError("planning semantic document packets do not exactly cover authority")

    segments: list[PlanningSemanticSegmentV2] = []
    for index, (packet, group) in enumerate(
        zip(packet_values, groups, strict=True), 1,
    ):
        packet_segment = _validated_packet_segment(packet, group)
        events = [
            event.model_copy(update={
                "formal_event_ordinal": group[event.formal_event_ordinal - 1],
            })
            for event in packet_segment.events
        ]
        if index < len(packet_values):
            segments.append(ContinuationPlanningSegmentV2(
                segment=index,
                title=packet_segment.title,
                events=events,
                exit_state=packet_values[index].initial_state,
            ))
        else:
            segments.append(TerminalPlanningSegmentV2(
                segment=index,
                title=packet_segment.title,
                events=events,
            ))
    return PlanningSemanticDraftV2(
        initial_state=packet_values[0].initial_state,
        segments=segments,
    )


def semantic_planning_packet_prompt_v2(
    *, global_segment: int, segment_count: int,
    global_event_ordinals: Iterable[int], formal_events: Iterable[dict[str, Any]],
    story_brief_projection: str, parent_brief_sha256: str,
    predecessor_semantic_sha256: str = "",
    predecessor_projection: str = "",
) -> str:
    """Render one ownership-bounded request using the canonical v2 schema."""

    ordinals = tuple(global_event_ordinals)
    events = tuple(dict(item) for item in formal_events)
    if not ordinals or len(ordinals) != len(events):
        raise ValueError("planning semantic packet event authority is incomplete")
    packet_contract = {
        "version": 2,
        "global_segment": global_segment,
        "segment_count": segment_count,
        "global_event_ordinals": list(ordinals),
        "parent_brief_sha256": parent_brief_sha256,
        "predecessor_semantic_sha256": predecessor_semantic_sha256,
    }
    event_catalog = [{
        "formal_event_ordinal": index,
        "label": str(event.get("label") or ""),
        "evidence": str(event.get("evidence") or ""),
    } for index, event in enumerate(events, 1)]
    return (
        "IR_FIRST_SHORT_PLANNING_PACKET_V2\n"
        "This is one Runtime-owned semantic packet of the complete short-story plan. "
        "Return one canonical PlanningSemanticDraftV2 JSON object with exactly one local "
        "segment: kind=terminal, segment=1. Use the packet-local formal_event_ordinal "
        "values 1..N exactly once and in order. Do not return global event IDs, hashes, "
        "packet controls, Markdown, tools, or a next-handoff field. The Runtime injects "
        "global segment identity, adjacent exit topology, and terminal authority, then "
        "revalidates the complete merged plan. Preserve actor agency, chronology, knowledge, "
        "relationships, promises, setup/payoff, genre voice, and confirmed ending logic.\n"
        "PACKET CONTRACT:\n"
        + json.dumps(packet_contract, ensure_ascii=False, sort_keys=True)
        + "\n\nSTORY BRIEF PROJECTION:\n" + story_brief_projection
        + "\n\nPACKET FORMAL EVENT CATALOG:\n"
        + json.dumps(event_catalog, ensure_ascii=False, indent=2)
        + ("\n\nACCEPTED PREDECESSOR PROJECTION:\n" + predecessor_projection
           if predecessor_projection else "")
    )


def normalize_planning_semantic_v2_payload(
    payload: object,
) -> dict[str, Any] | None:
    """Canonical Pydantic boundary shared by parsing and model recovery."""

    try:
        semantic = PlanningSemanticDraftV2.model_validate(payload)
    except ValueError:
        return None
    return semantic.model_dump(mode="json")


def parse_planning_semantic_v2(
    raw: str,
) -> tuple[PlanningSemanticDraftV2, ArtifactConversionAudit]:
    """Use the shared tolerant syntax boundary, then strict Pydantic semantics."""

    result = GeneratedArtifactGateway().convert_object(
        raw, contract_name="planning_semantic_v2",
        semantic_normalizer=normalize_planning_semantic_v2_payload,
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
