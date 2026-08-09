from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable

from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict, Field


PLAN_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "event_id": ("事件ID", "正式事件ID"),
    "outline": ("大纲依据", "正式大纲依据"),
    "opening": ("段首承接", "开场承接"),
    "event": ("本段事件", "本段子事件", "核心事件", "负责事件"),
    "handoff": ("段末交接", "交接状态", "段末状态"),
}


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


@dataclass(frozen=True)
class CompiledPlanningSegment:
    source: str
    fields: dict[str, tuple[PlanningFieldValue, ...]]

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
    parser = MarkdownIt("commonmark").enable("table")
    tokens = parser.parse(source)
    offsets = _line_offsets(source)
    values = _table_fields(tokens, source, offsets)
    markers, _table_ranges = _structural_markers(tokens)
    values.extend(_marker_fields(markers, tokens, source, offsets))
    fields: dict[str, list[PlanningFieldValue]] = {}
    for item in values:
        fields.setdefault(item.role, []).append(item)
    return CompiledPlanningSegment(
        source=source,
        fields={role: tuple(items) for role, items in fields.items()},
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


_FORMAL_EVENT_ID = re.compile(
    r"^(EV-[0-9A-F]{8})(?:-[A-Z0-9_-]+)?$", re.IGNORECASE,
)
_STRUCTURED_NARRATIVE_FIELDS = (
    "narrative", "narrative_summary", "event_body", "description",
    "summary", "causal_plan", "resolution", "realization",
)
_STRUCTURED_IDENTITY_FIELDS = frozenset({"event_id", "id"})
_STRUCTURED_CONTROL_FIELDS = frozenset({
    "command", "commands", "control", "control_action", "mutation", "op",
    "operation", "operations", "patch", "patches", "repair_operation",
    "review_decision",
})


def _json_key(value: object) -> str:
    return re.sub(
        r"[^0-9a-z_]+", "_",
        unicodedata.normalize("NFKC", str(value or ""))
        .strip().casefold().replace("-", "_").replace(" ", "_"),
    ).strip("_")


def _exact_formal_event_id(value: object) -> str:
    candidate = unicodedata.normalize(
        "NFKC", str(value or ""),
    ).strip().replace("－", "-").upper()
    match = _FORMAL_EVENT_ID.fullmatch(candidate)
    return match.group(1).upper() if match else ""


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


def _structured_narrative(item: dict[str, Any]) -> str:
    normalized = {_json_key(key): value for key, value in item.items()}
    for field in _STRUCTURED_NARRATIVE_FIELDS:
        value = normalized.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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
    unsafe: list[str] = []
    records: list[PlanningEventRealization] = []

    def visit(node: object, path: tuple[str, ...], inherited_id: str = "") -> None:
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, path + (str(index),), inherited_id="")
            return
        if not isinstance(node, dict):
            return
        normalized = {_json_key(key): (key, child) for key, child in node.items()}
        for key in normalized:
            if key in _STRUCTURED_CONTROL_FIELDS:
                unsafe.append(".".join(path + (str(normalized[key][0]),)))
        direct_ids = {
            _exact_formal_event_id(normalized[key][1])
            for key in _STRUCTURED_IDENTITY_FIELDS if key in normalized
        } - {""}
        if len(direct_ids) > 1:
            raise ValueError("planning event object has conflicting identities")
        direct_id = next(iter(direct_ids), "")
        if inherited_id and direct_id and inherited_id != direct_id:
            raise ValueError("planning event mapping conflicts with child identity")
        owner = inherited_id or direct_id
        narrative = _structured_narrative(node)
        if owner and narrative:
            records.append(PlanningEventRealization(
                event_id=owner,
                narrative=narrative,
                source_path=path,
                source_sha256=hashlib.sha256(json.dumps(
                    node, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")).hexdigest(),
            ))
        for raw_key, child in node.items():
            mapped_id = _exact_formal_event_id(raw_key)
            # A record owns its own descriptive children. Only recurse into
            # nested containers that may contain independent event records.
            if owner and not isinstance(child, (dict, list)):
                continue
            visit(
                child,
                path + (str(raw_key),),
                inherited_id=mapped_id,
            )

    visit(payload, ())
    if unsafe:
        raise ValueError(
            "planning event artifact contains unknown machine controls: "
            + ", ".join(sorted(set(unsafe)))
        )
    identities = [item.event_id for item in records]
    if len(identities) != len(set(identities)):
        raise ValueError("planning event artifact has duplicate or ambiguous ownership")
    expected = [
        event_id for event_id in (
            _exact_formal_event_id(item) for item in expected_event_ids
        ) if event_id
    ]
    if expected and identities != expected:
        raise ValueError(
            "planning event artifact changed ordered ownership: "
            f"expected={expected}, actual={identities}"
        )
    if not records:
        raise ValueError("planning event artifact has no complete event realizations")
    return CompiledPlanningEventArtifact(
        transport=transport,
        source_sha256=source_sha256,
        events=tuple(records),
    )
