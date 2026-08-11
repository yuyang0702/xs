from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata
from typing import Annotated, Any, Iterable, Literal

from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_flywheel.generated_artifacts import adapt_registered_contract


PLAN_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "event_id": ("事件ID", "正式事件ID"),
    "outline": ("大纲依据", "正式大纲依据"),
    "opening": ("段首承接", "开场承接"),
    "event": ("本段事件", "本段子事件", "核心事件", "负责事件"),
    "handoff": ("段末交接", "交接状态", "段末状态"),
}

_OWNED_FIELD_START = re.compile(
    r"(?m)^<!-- NOVEL_FLYWHEEL_PLANNING_FIELD_V1_START "
    r"role=(?P<role>event_id|outline|opening|event|handoff) "
    r"token=(?P<token>[0-9a-f]{24}) sha256=(?P<sha256>[0-9a-f]{64}) -->\r?\n"
)
_OWNED_FIELD_BLOCK = re.compile(
    r"(?ms)^<!-- NOVEL_FLYWHEEL_PLANNING_FIELD_V1_START "
    r"role=(?P<role>event_id|outline|opening|event|handoff) "
    r"token=(?P<token>[0-9a-f]{24}) sha256=(?P<sha256>[0-9a-f]{64}) -->\r?\n"
    r"(?P<body>.*?)\r?\n"
    r"<!-- NOVEL_FLYWHEEL_PLANNING_FIELD_V1_END "
    r"role=(?P=role) token=(?P=token) -->[ \t]*(?=\r?$)"
)
_FORMAL_EVENT_ID = re.compile(
    r"^(EV-[0-9A-F]{8})(?:-[A-Z0-9_-]+)?$", re.IGNORECASE,
)


def _canonical_owned_value(value: object) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _owned_field_envelope(role: str, value: object) -> str:
    if role not in PLAN_FIELD_ALIASES:
        raise KeyError(f"unknown planning field role: {role}")
    body = _canonical_owned_value(value)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    token = digest[:24]
    return (
        "<!-- NOVEL_FLYWHEEL_PLANNING_FIELD_V1_START "
        f"role={role} token={token} sha256={digest} -->\n"
        f"{body}\n"
        "<!-- NOVEL_FLYWHEEL_PLANNING_FIELD_V1_END "
        f"role={role} token={token} -->"
    )


def _normalize_label(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"</?(?:strong|b|em|i)>|[*_`#]", "", normalized)
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", normalized)


_NORMALIZED_ALIASES = {
    role: {_normalize_label(alias) for alias in aliases}
    for role, aliases in PLAN_FIELD_ALIASES.items()
}


def canonical_plan_field_role(label: object) -> str | None:
    """Map an open presentation label onto one closed planning role.

    The visible label is descriptive presentation.  Only the returned role is
    machine control; free-form prose is never normalized by this function.
    """
    compact = _normalize_label(label)
    if not compact:
        return None
    for role, aliases in _NORMALIZED_ALIASES.items():
        if compact in aliases:
            return role
    if (
        ("event" in compact or "事件" in compact)
        and any(value in compact for value in (
            "id", "identity", "ownership", "owned", "coverage", "covered",
            "scope", "所有权", "归属", "覆盖", "负责",
        ))
    ):
        return "event_id"
    if (
        ("outline" in compact or "大纲" in compact)
        and any(value in compact for value in ("basis", "evidence", "依据", "权威"))
    ):
        return "outline"
    if (
        any(value in compact for value in ("段首", "段前", "入口", "entry", "opening"))
        and any(value in compact for value in (
            "承接", "接续", "状态", "要件", "完整", "handoff", "state",
            "condition", "requirements", "prerequisites", "context",
        ))
    ):
        return "opening"
    if any(value in compact for value in (
        "至下一段", "下一事件", "后续事件", "tonextsegment",
        "nextevent", "laterevent", "neighbour", "neighbor",
    )):
        # Adjacent-event references are narrative guidance. They must never
        # become a second machine-owned handoff field merely because their
        # visible label contains the words 段末 or 交接.
        return None
    if (
        any(value in compact for value in ("段末", "出口", "exit", "handoff"))
        and any(value in compact for value in (
            "交接", "状态", "下一段", "entry", "state", "preserve",
        ))
    ):
        return "handoff"
    if any(value in compact for value in (
        "约束", "核验", "自检", "检查", "禁止", "人物声纹", "设定",
        "constraint", "validation", "checklist", "selfcheck", "character",
    )):
        return None
    if (
        any(value in compact for value in (
            "本段事件", "段内事件", "本包事件", "叙事推进", "剧情推进", "因果链",
            "segmentevent", "narrativeprogression", "causalchain",
        ))
        or (
            any(value in compact for value in ("节拍", "beat", "事件序列", "eventsequence"))
            and any(value in compact for value in (
                "因果", "时间轴", "顺序", "causal", "timeline", "sequence",
            ))
        )
        or (
            any(value in compact for value in ("段结构", "segmentstructure"))
            and any(value in compact for value in ("事件", "event", "beat", "节拍"))
        )
    ):
        return "event"
    return None


class PlanningSourceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start_line: int = Field(ge=0)
    end_line: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    source_sha256: str


class PlanningFieldValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    value: str
    presentation: str
    label: str
    span: PlanningSourceSpan


class PlanningEventRealization(BaseModel):
    """One structured event body whose identity is Runtime-verifiable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    narrative: str
    source_path: tuple[str, ...]
    source_sha256: str


class CompiledPlanningEventArtifact(BaseModel):
    """Provider-wrapper-independent event realization IR."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transport: str
    source_sha256: str
    events: tuple[PlanningEventRealization, ...]
    adapter_audits: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class CompiledPlanningSegment:
    source: str
    fields: dict[str, tuple[PlanningFieldValue, ...]]
    protocol_issues: tuple[str, ...] = ()

    def values(self, role: str) -> tuple[PlanningFieldValue, ...]:
        return self.fields.get(role, ())

    def field(self, role: str) -> str:
        """Return one unambiguous semantic value, never first/last wins."""
        values = self.values(role)
        distinct: dict[str, str] = {}
        for item in values:
            key = re.sub(r"\s+", " ", item.value).strip()
            if key:
                distinct.setdefault(key, item.value.strip())
        return next(iter(distinct.values())) if len(distinct) == 1 else ""

    def is_ambiguous(self, role: str) -> bool:
        return len({
            re.sub(r"\s+", " ", item.value).strip()
            for item in self.values(role) if item.value.strip()
        }) > 1


@dataclass(frozen=True)
class _Marker:
    role: str
    label: str
    presentation: str
    start_line: int
    end_line: int
    inline_value: str
    heading_level: int = 0


class PlanningSegmentIR(BaseModel):
    """Canonical Runtime-owned planning segment used by downstream stages.

    Free-form event prose is intentionally opaque.  Its Markdown headings,
    labels, dialogue and genre-specific structure never gain machine-control
    authority.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(default=1, ge=1)
    source_kind: Literal["structured_v1"] = "structured_v1"
    segment: int = Field(ge=1)
    heading: str = Field(min_length=1)
    event_ids: tuple[str, ...]
    outline: str = Field(min_length=1)
    opening: str = Field(min_length=1)
    event_body: str = Field(min_length=1)
    handoff: str = Field(min_length=1)
    source_sha256: str = Field(min_length=64, max_length=64)

    @property
    def authority_sha256(self) -> str:
        return hashlib.sha256(json.dumps(
            self.model_dump(mode="json", exclude={"source_sha256"}),
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()


class PlanningDocumentIR(BaseModel):
    """Content-addressed planning authority persisted beside display Markdown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(default=1, ge=1)
    plan_sha256: str = Field(min_length=64, max_length=64)
    segments: tuple[PlanningSegmentIR, ...]

    @property
    def authority_sha256(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()


class AdjacentHandoffIR(BaseModel):
    """A non-terminal segment exit bound to one exact successor opening."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    kind: Literal["adjacent_handoff"] = "adjacent_handoff"
    segment: int = Field(ge=1)
    successor_segment: int = Field(ge=2)
    established_state: str = Field(min_length=1)
    successor_opening_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
    )
    source_segment_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def _validate_successor(self) -> "AdjacentHandoffIR":
        if self.successor_segment != self.segment + 1:
            raise ValueError("adjacent handoff must target the next segment")
        if self.established_state != _canonical_owned_value(self.established_state):
            raise ValueError("adjacent handoff state must be canonical non-empty text")
        return self


class TerminalClosureIR(BaseModel):
    """A terminal exit proven by formal ending and last-event authority.

    An intentionally open promise is not a missing ending.  Its stable
    obligation ID is retained here so later stages can preserve it while still
    proving the surface and inner closure described by ``ending_sha256``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    kind: Literal["terminal_closure"] = "terminal_closure"
    segment: int = Field(ge=1)
    terminal_event_ids: tuple[str, ...]
    formal_last_event_id: str = Field(min_length=1)
    formal_last_event_evidence: str = Field(min_length=1)
    formal_last_event_evidence_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
    )
    ending_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
    )
    retained_open_obligation_ids: tuple[str, ...] = ()
    source_segment_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def _validate_terminal_proof(self) -> "TerminalClosureIR":
        if not self.terminal_event_ids:
            raise ValueError("terminal closure must own at least one event")
        if len(self.terminal_event_ids) != len(set(self.terminal_event_ids)):
            raise ValueError("terminal closure event IDs must be unique")
        if any(
            _FORMAL_EVENT_ID.fullmatch(event_id) is None
            or event_id != event_id.upper()
            for event_id in self.terminal_event_ids
        ):
            raise ValueError("terminal closure event IDs must be canonical")
        if (
            _FORMAL_EVENT_ID.fullmatch(self.formal_last_event_id) is None
            or self.formal_last_event_id != self.formal_last_event_id.upper()
        ):
            raise ValueError("formal last event ID must be canonical")
        if self.formal_last_event_id not in self.terminal_event_ids:
            raise ValueError("terminal segment does not own the formal last event")
        evidence = _canonical_owned_value(self.formal_last_event_evidence)
        if evidence != self.formal_last_event_evidence:
            raise ValueError("formal last-event evidence must be canonical")
        if hashlib.sha256(evidence.encode("utf-8")).hexdigest() != (
            self.formal_last_event_evidence_sha256
        ):
            raise ValueError("formal last-event evidence hash is stale")
        obligations = tuple(
            str(value or "").strip()
            for value in self.retained_open_obligation_ids
        )
        if any(not value for value in obligations):
            raise ValueError("retained-open obligation IDs must not be empty")
        if obligations != self.retained_open_obligation_ids:
            raise ValueError("retained-open obligation IDs must be canonical")
        if len(obligations) != len(set(obligations)):
            raise ValueError("retained-open obligation IDs must be unique")
        return self


PlanningSegmentExitIR = Annotated[
    AdjacentHandoffIR | TerminalClosureIR,
    Field(discriminator="kind"),
]


class PlanningDocumentExitTopologyIR(BaseModel):
    """Versioned, content-addressed exit topology for one planning document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    source_kind: Literal["planning_exit_topology_v1"] = (
        "planning_exit_topology_v1"
    )
    segment_source_sha256: tuple[str, ...]
    segment_opening_sha256: tuple[str, ...]
    segment_event_ids: tuple[tuple[str, ...], ...]
    formal_event_ids: tuple[str, ...]
    ending_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
    )
    exits: tuple[PlanningSegmentExitIR, ...]

    @model_validator(mode="after")
    def _validate_document_topology(self) -> "PlanningDocumentExitTopologyIR":
        count = len(self.segment_event_ids)
        if count < 1:
            raise ValueError("planning exit topology must contain a segment")
        if not (
            len(self.segment_source_sha256)
            == len(self.segment_opening_sha256)
            == len(self.exits)
            == count
        ):
            raise ValueError("planning exit topology manifests must have equal length")
        if not self.formal_event_ids:
            raise ValueError("planning exit topology requires formal events")
        if len(self.formal_event_ids) != len(set(self.formal_event_ids)):
            raise ValueError("formal event IDs must be unique")
        hashes = self.segment_source_sha256 + self.segment_opening_sha256
        if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in hashes):
            raise ValueError("planning exit topology contains an invalid hash")
        if any(
            _FORMAL_EVENT_ID.fullmatch(event_id) is None
            or event_id != event_id.upper()
            for event_id in self.formal_event_ids
        ):
            raise ValueError("formal event IDs must be canonical")

        collapsed: list[str] = []
        seen: set[str] = set()
        for group in self.segment_event_ids:
            if not group or len(group) != len(set(group)):
                raise ValueError("each planning segment must own unique events")
            for event_id in group:
                if (
                    _FORMAL_EVENT_ID.fullmatch(event_id) is None
                    or event_id != event_id.upper()
                ):
                    raise ValueError("planning segment event IDs must be canonical")
                if collapsed and collapsed[-1] == event_id:
                    continue
                if event_id in seen:
                    raise ValueError("formal event ownership re-enters non-contiguously")
                collapsed.append(event_id)
                seen.add(event_id)
        if tuple(collapsed) != self.formal_event_ids:
            raise ValueError("planning segments do not cover formal event order")

        for index, exit_contract in enumerate(self.exits, 1):
            if exit_contract.segment != index:
                raise ValueError("planning exit segment numbers must be contiguous")
            if exit_contract.source_segment_sha256 != self.segment_source_sha256[index - 1]:
                raise ValueError("planning exit is bound to a stale segment")
            if index < count:
                if not isinstance(exit_contract, AdjacentHandoffIR):
                    raise ValueError("non-terminal segment requires adjacent handoff")
                if exit_contract.successor_segment != index + 1:
                    raise ValueError("adjacent handoff targets the wrong successor")
                if exit_contract.successor_opening_sha256 != (
                    self.segment_opening_sha256[index]
                ):
                    raise ValueError("adjacent handoff is not bound to successor opening")
            elif not isinstance(exit_contract, TerminalClosureIR):
                raise ValueError("last segment requires terminal closure")

        terminal = self.exits[-1]
        assert isinstance(terminal, TerminalClosureIR)
        if terminal.ending_sha256 != self.ending_sha256:
            raise ValueError("terminal closure is bound to a stale ending")
        if terminal.terminal_event_ids != self.segment_event_ids[-1]:
            raise ValueError("terminal closure event ownership is stale")
        if terminal.formal_last_event_id != self.formal_event_ids[-1]:
            raise ValueError("terminal closure does not prove the formal last event")
        return self

    @property
    def authority_sha256(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()


class PlanningOwnershipTopology(BaseModel):
    """Closed event/segment topology shared by every Runtime consumer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = 1
    event_ids: tuple[str, ...]
    segment_event_ids: tuple[tuple[str, ...], ...]
    owner_segments: tuple[tuple[int, ...], ...]


def planning_ownership_topology(
    document: PlanningDocumentIR,
    *, expected_event_ids: Iterable[str] = (),
) -> PlanningOwnershipTopology:
    """Compile adjacent shared ownership into one canonical event topology.

    One event may span adjacent writing segments. Re-entering that event after
    another event has begun is ambiguous and therefore rejected everywhere.
    """

    groups = tuple(tuple(segment.event_ids) for segment in document.segments)
    if not groups or any(not group for group in groups):
        raise ValueError("ownership_empty_segment")
    canonical: list[str] = []
    seen: set[str] = set()
    owners: dict[str, list[int]] = {}
    for segment_number, group in enumerate(groups, 1):
        if len(group) != len(set(group)):
            raise ValueError("ownership_duplicate_within_segment")
        for raw_event_id in group:
            event_id = _exact_formal_event_id(raw_event_id)
            if not event_id:
                raise ValueError("ownership_invalid_event_id")
            event_owners = owners.setdefault(event_id, [])
            if not event_owners or event_owners[-1] != segment_number:
                event_owners.append(segment_number)
            if canonical and canonical[-1] == event_id:
                continue
            if event_id in seen:
                raise ValueError("ownership_non_contiguous_repeat")
            canonical.append(event_id)
            seen.add(event_id)
    expected = tuple(
        event_id for event_id in (
            _exact_formal_event_id(item) for item in expected_event_ids
        ) if event_id
    )
    if expected and tuple(canonical) != expected:
        raise ValueError("ownership_sequence_mismatch")
    return PlanningOwnershipTopology(
        event_ids=tuple(canonical),
        segment_event_ids=groups,
        owner_segments=tuple(tuple(owners[event_id]) for event_id in canonical),
    )


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    for index, character in enumerate(source):
        if character == "\n":
            offsets.append(index + 1)
    offsets.append(len(source))
    return offsets


def _source_span(
    source: str, offsets: list[int], start_line: int, end_line: int,
) -> PlanningSourceSpan:
    safe_start = min(max(0, start_line), len(offsets) - 1)
    safe_end = min(max(safe_start, end_line), len(offsets) - 1)
    start, end = offsets[safe_start], offsets[safe_end]
    return PlanningSourceSpan(
        start_line=safe_start,
        end_line=safe_end,
        start=start,
        end=end,
        source_sha256=hashlib.sha256(source[start:end].encode("utf-8")).hexdigest(),
    )


def _owned_fields(
    source: str, offsets: list[int],
) -> tuple[list[PlanningFieldValue], str, frozenset[str], tuple[str, ...]]:
    """Extract Runtime-owned fields before parsing visible Markdown.

    The content-addressed envelope is a compiler boundary, not a provider
    format.  Its body is masked from the Markdown parser so headings inside
    creative event prose cannot become sibling machine-control fields.
    """

    matches = list(_OWNED_FIELD_BLOCK.finditer(source))
    covered = [(match.start(), match.end()) for match in matches]

    def contained(position: int) -> bool:
        return any(start <= position < end for start, end in covered)

    invalid_roles: set[str] = set()
    issues: list[str] = []
    for start in _OWNED_FIELD_START.finditer(source):
        if not any(match.start() == start.start() for match in matches) and not contained(
            start.start()
        ):
            role = start.group("role")
            invalid_roles.add(role)
            issues.append(f"owned planning field {role} is incomplete")
    end_pattern = re.compile(
        r"(?m)^<!-- NOVEL_FLYWHEEL_PLANNING_FIELD_V1_END "
        r"role=(?P<role>event_id|outline|opening|event|handoff) "
        r"token=[0-9a-f]{24} -->$"
    )
    for end in end_pattern.finditer(source):
        if not contained(end.start()):
            role = end.group("role")
            invalid_roles.add(role)
            issues.append(f"owned planning field {role} has an unmatched terminator")

    results: list[PlanningFieldValue] = []
    valid_ranges: list[tuple[int, int]] = []
    for match in matches:
        role = match.group("role")
        body = match.group("body")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if digest != match.group("sha256") or digest[:24] != match.group("token"):
            invalid_roles.add(role)
            issues.append(f"owned planning field {role} failed its content hash")
            continue
        start_line = source.count("\n", 0, match.start())
        end_line = source.count("\n", 0, match.end()) + 1
        results.append(PlanningFieldValue(
            role=role,
            value=body,
            presentation="runtime_owned_v1",
            label=role,
            span=_source_span(source, offsets, start_line, end_line),
        ))
        valid_ranges.append((match.start(), match.end()))

    characters = list(source)
    for start, end in covered:
        for index in range(start, end):
            if characters[index] not in "\r\n":
                characters[index] = " "
    return results, "".join(characters), frozenset(invalid_roles), tuple(issues)


def planning_markdown_presentation_view(value: object) -> str:
    """Mask complete Runtime-owned envelopes before Markdown boundary scans.

    The returned text preserves source offsets and line endings. Owned bodies
    may contain arbitrary Markdown, including headings that resemble segment
    boundaries; presentation scanners must never reinterpret those bytes as
    sibling machine-control structure. Hash and role validation remains the
    responsibility of :func:`compile_planning_segment`.
    """

    source = str(value or "")
    if not source:
        return ""
    _owned, visible, _invalid_roles, _issues = _owned_fields(
        source, _line_offsets(source),
    )
    return visible


def _split_label_value(value: str) -> tuple[str, str, bool]:
    visible = str(value or "").strip()
    match = re.match(
        r"^(?P<open>\*{1,2}|_{1,2}|`|<strong>|<b>)?\s*"
        r"(?P<label>.*?)(?:[:：﹕])\s*"
        r"(?P<close>\*{1,2}|_{1,2}|`|</strong>|</b>)?\s*"
        r"(?P<value>.*)$",
        visible,
        re.I | re.S,
    )
    if match:
        return match.group("label").strip(), match.group("value").strip(), True
    undecorated = re.sub(
        r"^(?:\*{1,2}|_{1,2}|`|<strong>|<b>)\s*|"
        r"\s*(?:\*{1,2}|_{1,2}|`|</strong>|</b>)$",
        "",
        visible,
        flags=re.I,
    ).strip()
    return undecorated, "", False


def _table_fields(tokens: list, source: str, offsets: list[int]) -> list[PlanningFieldValue]:
    results: list[PlanningFieldValue] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type != "tr_open" or token.map is None:
            index += 1
            continue
        row_end = index + 1
        cells: list[str] = []
        cell_kind = ""
        while row_end < len(tokens) and tokens[row_end].type != "tr_close":
            current = tokens[row_end]
            if current.type in {"td_open", "th_open"}:
                cell_kind = current.type
            elif current.type == "inline" and cell_kind:
                cells.append(current.content.strip())
                cell_kind = ""
            row_end += 1
        if len(cells) >= 2:
            role = canonical_plan_field_role(cells[0])
            value = " | ".join(cells[1:]).strip()
            if role and value:
                start_line, end_line = map(int, token.map)
                results.append(PlanningFieldValue(
                    role=role,
                    value=value,
                    presentation="table",
                    label=cells[0],
                    span=_source_span(source, offsets, start_line, end_line),
                ))
        index = row_end + 1
    return results


def _structural_markers(tokens: list) -> tuple[list[_Marker], list[tuple[int, int]]]:
    markers: list[_Marker] = []
    table_ranges: list[tuple[int, int]] = []
    excluded_ranges: list[tuple[int, int]] = []
    for token in tokens:
        if token.map is None:
            continue
        start, end = map(int, token.map)
        if token.type == "table_open":
            table_ranges.append((start, end))
        elif token.type in {"fence", "code_block", "html_block"}:
            excluded_ranges.append((start, end))

    def hidden(start: int) -> bool:
        return any(left <= start < right for left, right in (*table_ranges, *excluded_ranges))

    for index, token in enumerate(tokens):
        if token.type != "inline" or token.map is None:
            continue
        start_line, end_line = map(int, token.map)
        if hidden(start_line):
            continue
        parent = tokens[index - 1] if index else None
        presentation = "paragraph"
        heading_level = 0
        if parent and parent.type == "heading_open":
            presentation = "heading"
            heading_level = int(parent.tag[1:]) if parent.tag.startswith("h") else 0
        elif any(
            prior.type == "list_item_open" and prior.map is not None
            and int(prior.map[0]) <= start_line < int(prior.map[1])
            for prior in tokens[:index]
        ):
            presentation = "list"
        content_lines = token.content.splitlines() or [token.content]
        for line_offset, content_line in enumerate(content_lines):
            line_start = start_line + line_offset
            if line_start >= end_line:
                line_start = start_line
            line_end = min(max(line_start + 1, start_line + 1), end_line)
            label, inline_value, had_colon = _split_label_value(content_line)
            role = canonical_plan_field_role(label)
            if not role:
                continue
            # A paragraph/list item without a colon is accepted only when it
            # is a standalone decorated field title. This prevents ordinary
            # prose such as "本段事件需要更紧张" from becoming machine control.
            decorated = bool(re.fullmatch(
                r"\s*(?:\*{1,2}|_{1,2}|`|<strong>|<b>).+?"
                r"(?:\*{1,2}|_{1,2}|`|</strong>|</b>)\s*",
                content_line,
                flags=re.I | re.S,
            ))
            if not had_colon and presentation != "heading" and not decorated:
                continue
            markers.append(_Marker(
                role=role,
                label=label,
                presentation=(
                    presentation if had_colon else f"{presentation}_owned"
                ),
                start_line=line_start,
                end_line=line_end,
                inline_value=inline_value,
                heading_level=heading_level,
            ))
    return sorted(markers, key=lambda item: (item.start_line, item.end_line)), table_ranges


def _marker_fields(
    markers: list[_Marker], tokens: list, source: str, offsets: list[int],
) -> list[PlanningFieldValue]:
    results: list[PlanningFieldValue] = []
    heading_boundaries = sorted(
        (
            int(token.map[0]),
            int(token.tag[1:]) if token.tag.startswith("h") else 0,
        )
        for token in tokens
        if token.type == "heading_open" and token.map is not None
    )
    for index, marker in enumerate(markers):
        boundaries = [
            item.start_line for item in markers[index + 1:]
            if item.start_line > marker.start_line
        ]
        if marker.heading_level:
            boundaries.extend(
                line for line, level in heading_boundaries
                if line > marker.start_line and level <= marker.heading_level
            )
        else:
            boundaries.extend(
                line for line, _level in heading_boundaries
                if line > marker.start_line
            )
        # Both inline and standalone labels own following plain blocks until
        # the next field/heading.  This preserves multiline handoffs while
        # preventing one field from swallowing the next marker.
        end_line = min(boundaries) if boundaries else len(offsets) - 1
        body_start = offsets[min(marker.end_line, len(offsets) - 1)]
        body_end = offsets[min(end_line, len(offsets) - 1)]
        body = source[body_start:body_end].strip()
        value = "\n".join(
            part for part in (marker.inline_value.strip(), body) if part
        ).strip()
        if not value:
            continue
        results.append(PlanningFieldValue(
            role=marker.role,
            value=value,
            presentation=marker.presentation,
            label=marker.label,
            span=_source_span(source, offsets, marker.start_line, end_line),
        ))
    return results


def compile_planning_segment(value: object) -> CompiledPlanningSegment:
    """Compile one plan segment through a single AST-based presentation boundary."""
    source = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    if not source:
        return CompiledPlanningSegment(source="", fields={})
    offsets = _line_offsets(source)
    owned, visible_source, invalid_roles, protocol_issues = _owned_fields(
        source, offsets,
    )
    parser = MarkdownIt("commonmark").enable("table")
    tokens = parser.parse(visible_source)
    values = _table_fields(tokens, source, offsets)
    markers, _table_ranges = _structural_markers(tokens)
    values.extend(_marker_fields(markers, tokens, source, offsets))
    owned_roles = {item.role for item in owned}
    values = [
        item for item in values
        if item.role not in owned_roles and item.role not in invalid_roles
    ]
    values.extend(owned)
    fields: dict[str, list[PlanningFieldValue]] = {}
    for item in values:
        fields.setdefault(item.role, []).append(item)
    return CompiledPlanningSegment(
        source=source,
        fields={role: tuple(items) for role, items in fields.items()},
        protocol_issues=protocol_issues,
    )


def compile_planning_segment_ir(
    value: object, *, segment: int, heading: str | None = None,
) -> PlanningSegmentIR:
    """Compile one complete segment into the canonical typed authority."""

    compiled = compile_planning_segment(value)
    if compiled.protocol_issues:
        raise ValueError("; ".join(compiled.protocol_issues))
    required = {
        role: compiled.field(role)
        for role in ("event_id", "outline", "opening", "event", "handoff")
    }
    missing = [role for role, field_value in required.items() if not field_value]
    if missing:
        raise ValueError(
            "planning segment IR is missing or ambiguous: " + ", ".join(missing)
        )
    event_ids = tuple(
        match.group(1).upper()
        for match in re.finditer(
            r"(?<![0-9A-Z_-])(EV-[0-9A-F]{8})(?:-[A-Z0-9_-]+)?(?![0-9A-Z_-])",
            unicodedata.normalize("NFKC", required["event_id"]).upper(),
        )
    )
    if not event_ids or len(event_ids) != len(set(event_ids)):
        raise ValueError("planning segment IR has invalid ordered event ownership")
    source_heading = str(heading or "").strip() or next((
        line.strip() for line in compiled.source.splitlines()
        if line.strip()
    ), f"### 第 {segment} 段：规划")
    return PlanningSegmentIR(
        segment=segment,
        heading=source_heading,
        event_ids=event_ids,
        outline=required["outline"],
        opening=required["opening"],
        event_body=required["event"],
        handoff=required["handoff"],
        source_sha256=hashlib.sha256(compiled.source.encode("utf-8")).hexdigest(),
    )


def render_planning_segment_ir(value: PlanningSegmentIR) -> str:
    """Render display Markdown without surrendering field ownership to it."""

    fields = (
        ("event_id", "事件ID", "、".join(value.event_ids)),
        ("outline", "大纲依据", value.outline),
        ("opening", "段首承接", value.opening),
        ("event", "本段事件", value.event_body),
        ("handoff", "段末交接", value.handoff),
    )
    return (value.heading.strip() + "\n\n" + "\n\n".join(
        f"{label}：\n{_owned_field_envelope(role, field_value)}"
        for role, label, field_value in fields
    )).strip()


def compile_planning_document_ir(
    plan: str, segments: Iterable[str],
) -> PlanningDocumentIR:
    compiled = tuple(
        compile_planning_segment_ir(segment, segment=index)
        for index, segment in enumerate(segments, 1)
    )
    return PlanningDocumentIR(
        plan_sha256=hashlib.sha256(str(plan).encode("utf-8")).hexdigest(),
        segments=compiled,
    )


def extract_planning_field(value: object, role: str) -> str:
    if role not in PLAN_FIELD_ALIASES:
        raise KeyError(f"unknown planning field role: {role}")
    return compile_planning_segment(value).field(role)


def planning_field_sections(
    value: object, role: str, *, presentations: Iterable[str] | None = None,
) -> tuple[str, ...]:
    compiled = compile_planning_segment(value)
    allowed = set(presentations or ())
    results: list[str] = []
    for item in compiled.values(role):
        if allowed and item.presentation not in allowed:
            continue
        normalized = re.sub(r"\s+", " ", item.value).strip()
        if normalized and normalized not in {
            re.sub(r"\s+", " ", current).strip() for current in results
        }:
            results.append(item.value)
    return tuple(results)


def _exact_formal_event_id(value: object) -> str:
    candidate = unicodedata.normalize(
        "NFKC", str(value or ""),
    ).strip().replace("－", "-").upper()
    match = _FORMAL_EVENT_ID.fullmatch(candidate)
    return match.group(1).upper() if match else ""


@dataclass(frozen=True)
class _PlanningExitSegmentSource:
    segment: int
    event_ids: tuple[str, ...]
    opening: str
    handoff: str
    source_sha256: str


def _planning_exit_segment_sources(
    segments: Iterable[PlanningSegmentIR | CompiledPlanningSegment],
) -> tuple[_PlanningExitSegmentSource, ...]:
    result: list[_PlanningExitSegmentSource] = []
    for fallback_segment, value in enumerate(segments, 1):
        if isinstance(value, PlanningSegmentIR):
            segment = value.segment
            event_ids = tuple(value.event_ids)
            opening = value.opening
            handoff = value.handoff
            source_sha256 = value.source_sha256
        elif isinstance(value, CompiledPlanningSegment):
            if value.protocol_issues:
                raise ValueError("planning segment has invalid owned-field protocol")
            segment = fallback_segment
            declared = value.field("event_id")
            event_ids = tuple(
                match.group(1).upper()
                for match in re.finditer(
                    r"(?<![0-9A-Z_-])(EV-[0-9A-F]{8})(?:-[A-Z0-9_-]+)?"
                    r"(?![0-9A-Z_-])",
                    unicodedata.normalize("NFKC", declared).upper(),
                )
            )
            opening = value.field("opening")
            handoff = value.field("handoff")
            source_sha256 = hashlib.sha256(
                value.source.encode("utf-8"),
            ).hexdigest()
        else:
            raise TypeError(
                "planning exits require PlanningSegmentIR or CompiledPlanningSegment"
            )

        normalized_ids = tuple(_exact_formal_event_id(item) for item in event_ids)
        if (
            not normalized_ids
            or any(not event_id for event_id in normalized_ids)
            or len(normalized_ids) != len(set(normalized_ids))
        ):
            raise ValueError("planning exit segment has invalid event ownership")
        opening = _canonical_owned_value(opening)
        if not opening:
            raise ValueError("planning exit segment is missing its opening")
        if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
            raise ValueError("planning exit segment source hash is invalid")
        result.append(_PlanningExitSegmentSource(
            segment=segment,
            event_ids=normalized_ids,
            opening=opening,
            handoff=_canonical_owned_value(handoff),
            source_sha256=source_sha256,
        ))
    if not result:
        raise ValueError("planning exits require at least one segment")
    if [item.segment for item in result] != list(range(1, len(result) + 1)):
        raise ValueError("planning exit segment numbers must be contiguous")
    return tuple(result)


def _planning_formal_event_proofs(
    formal_events: Iterable[dict[str, Any]],
) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for index, item in enumerate(formal_events):
        if not isinstance(item, dict):
            raise TypeError(f"formal_events[{index}] must be an object")
        declared = {
            event_id for event_id in (
                _exact_formal_event_id(item.get("id")),
                _exact_formal_event_id(item.get("event_id")),
            ) if event_id
        }
        if len(declared) != 1:
            raise ValueError(
                f"formal_events[{index}] must declare one exact event ID"
            )
        evidence = _canonical_owned_value(item.get("evidence"))
        if not evidence:
            raise ValueError(
                f"formal_events[{index}] must retain exact formal evidence"
            )
        result.append((next(iter(declared)), evidence))
    if not result:
        raise ValueError("planning exits require formal events")
    ids = [event_id for event_id, _evidence in result]
    if len(ids) != len(set(ids)):
        raise ValueError("formal event IDs must be unique")
    return tuple(result)


def _planning_ending_sha256(formal_ending: dict[str, Any]) -> str:
    if not isinstance(formal_ending, dict) or not formal_ending:
        raise ValueError("terminal closure requires formal ending authority")
    try:
        canonical = json.dumps(
            formal_ending,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("formal ending authority must be canonical JSON") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_planning_exit_event_sequence(
    segments: tuple[_PlanningExitSegmentSource, ...],
    formal_event_ids: tuple[str, ...],
) -> None:
    collapsed: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        for event_id in segment.event_ids:
            if collapsed and collapsed[-1] == event_id:
                continue
            if event_id in seen:
                raise ValueError("formal event ownership re-enters non-contiguously")
            collapsed.append(event_id)
            seen.add(event_id)
    if tuple(collapsed) != formal_event_ids:
        raise ValueError("planning segments do not cover formal event order")


def compile_planning_segment_exit_contracts(
    segments: Iterable[PlanningSegmentIR | CompiledPlanningSegment],
    formal_events: Iterable[dict[str, Any]],
    *,
    formal_ending: dict[str, Any],
    retained_open_obligation_ids: Iterable[str] = (),
) -> tuple[AdjacentHandoffIR | TerminalClosureIR, ...]:
    """Build every segment exit without granting prose boundary authority.

    Legacy ``PlanningSegmentIR`` values remain readable and renderable.  A
    terminal segment may instead enter through ``CompiledPlanningSegment``
    without a legacy handoff: the formal ending and last-event evidence prove
    closure.  Missing handoff remains invalid for every non-terminal segment.
    """

    sources = _planning_exit_segment_sources(segments)
    formal_proofs = _planning_formal_event_proofs(formal_events)
    formal_event_ids = tuple(event_id for event_id, _evidence in formal_proofs)
    last_event_id, last_event_evidence = formal_proofs[-1]
    if last_event_id not in sources[-1].event_ids:
        raise ValueError("terminal segment does not own the formal last event")
    _validate_planning_exit_event_sequence(sources, formal_event_ids)
    ending_sha256 = _planning_ending_sha256(formal_ending)
    retained = tuple(
        str(value or "").strip() for value in retained_open_obligation_ids
    )
    if any(not value for value in retained):
        raise ValueError("retained-open obligation IDs must not be empty")
    if len(retained) != len(set(retained)):
        raise ValueError("retained-open obligation IDs must be unique")

    exits: list[AdjacentHandoffIR | TerminalClosureIR] = []
    for index, source in enumerate(sources):
        if index < len(sources) - 1:
            if not source.handoff:
                raise ValueError(
                    f"non-terminal segment {source.segment} is missing handoff"
                )
            successor = sources[index + 1]
            exits.append(AdjacentHandoffIR(
                segment=source.segment,
                successor_segment=successor.segment,
                established_state=source.handoff,
                successor_opening_sha256=hashlib.sha256(
                    successor.opening.encode("utf-8"),
                ).hexdigest(),
                source_segment_sha256=source.source_sha256,
            ))
        else:
            exits.append(TerminalClosureIR(
                segment=source.segment,
                terminal_event_ids=source.event_ids,
                formal_last_event_id=last_event_id,
                formal_last_event_evidence=last_event_evidence,
                formal_last_event_evidence_sha256=hashlib.sha256(
                    last_event_evidence.encode("utf-8"),
                ).hexdigest(),
                ending_sha256=ending_sha256,
                retained_open_obligation_ids=retained,
                source_segment_sha256=source.source_sha256,
            ))
    return tuple(exits)


def planning_document_exit_topology(
    segments: Iterable[PlanningSegmentIR | CompiledPlanningSegment],
    formal_events: Iterable[dict[str, Any]],
    *,
    formal_ending: dict[str, Any],
    retained_open_obligation_ids: Iterable[str] = (),
) -> PlanningDocumentExitTopologyIR:
    """Compile and validate the closed 1/2/N segment exit topology."""

    segment_values = tuple(segments)
    formal_event_values = tuple(formal_events)
    sources = _planning_exit_segment_sources(segment_values)
    proofs = _planning_formal_event_proofs(formal_event_values)
    exits = compile_planning_segment_exit_contracts(
        segment_values,
        formal_event_values,
        formal_ending=formal_ending,
        retained_open_obligation_ids=retained_open_obligation_ids,
    )
    return PlanningDocumentExitTopologyIR(
        segment_source_sha256=tuple(item.source_sha256 for item in sources),
        segment_opening_sha256=tuple(
            hashlib.sha256(item.opening.encode("utf-8")).hexdigest()
            for item in sources
        ),
        segment_event_ids=tuple(item.event_ids for item in sources),
        formal_event_ids=tuple(event_id for event_id, _evidence in proofs),
        ending_sha256=_planning_ending_sha256(formal_ending),
        exits=exits,
    )


def _structured_source(value: object) -> tuple[object, str, str]:
    if isinstance(value, (dict, list)):
        source = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        return value, source, "tool_arguments" if isinstance(value, dict) else "json"
    source = str(value or "").lstrip("\ufeff").strip()
    if source.startswith("<!--") and source.endswith("-->"):
        source = source[4:-3].strip()
    lines = source.splitlines()
    if len(lines) >= 3 and (
        lines[0].strip().startswith("```")
        or lines[0].strip().startswith("~~~")
    ) and (
        lines[-1].strip().startswith("```")
        or lines[-1].strip().startswith("~~~")
    ):
        source = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(source), source, "json"
    except json.JSONDecodeError as exc:
        raise ValueError("planning event artifact is not one JSON value") from exc


def compile_planning_event_artifact(
    value: object, *, expected_event_ids: Iterable[str] = (),
) -> CompiledPlanningEventArtifact:
    """Compile JSON/schema/tool wrappers by invariant identity, not wrapper names.

    Container topology is open. Event identity, ordered ownership and narrative
    cardinality are closed. Ambiguous or command-bearing packets fail rather
    than granting provider-selected fields mutation authority.
    """
    payload, source, transport = _structured_source(value)
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if not isinstance(payload, dict):
        raise ValueError("planning event artifact must be one JSON object")
    expected = [
        event_id for event_id in (
            _exact_formal_event_id(item) for item in expected_event_ids
        ) if event_id
    ]
    if not expected:
        raise ValueError("planning event artifact has no Runtime-owned event contract")
    adaptation = adapt_registered_contract(
        payload,
        contract_name="planning_event_realizations",
        context={"expected_event_ids": tuple(expected)},
    )
    canonical = adaptation.payload
    if set(canonical) != {"events"} or not isinstance(canonical["events"], list):
        raise ValueError("planning event artifact changed the canonical contract")
    records: list[PlanningEventRealization] = []
    for index, item in enumerate(canonical["events"]):
        if not isinstance(item, dict) or set(item) != {"event_id", "narrative"}:
            raise ValueError("planning event artifact has a malformed event record")
        event_id = _exact_formal_event_id(item.get("event_id"))
        narrative = str(item.get("narrative") or "").strip()
        meaningful = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", narrative)
        if not event_id or len(meaningful) < 12:
            raise ValueError("planning event artifact has an incomplete realization")
        records.append(PlanningEventRealization(
            event_id=event_id,
            narrative=narrative,
            source_path=("events", str(index)),
            source_sha256=hashlib.sha256(json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
        ))
    identities = [item.event_id for item in records]
    if identities != expected or len(identities) != len(set(identities)):
        raise ValueError(
            "planning event artifact changed ordered ownership: "
            f"expected={expected}, actual={identities}"
        )
    return CompiledPlanningEventArtifact(
        transport=transport,
        source_sha256=source_sha256,
        events=tuple(records),
        adapter_audits=tuple(
            item.model_dump(mode="json") for item in adaptation.audits
        ),
    )
