from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

from novel_flywheel.narrative_contract import narrative_voice_projection
from novel_flywheel.narrative_document import parse_narrative_document
from novel_flywheel.planning_compiler import compile_planning_segment


PLANNING_ADAPTATION_VERSION = 3
LEGACY_PLANNING_ADAPTATION_VERSION = 1
PREVIOUS_PLANNING_ADAPTATION_VERSION = 2
SUPPORTED_PLANNING_ADAPTATION_VERSIONS = frozenset({
    LEGACY_PLANNING_ADAPTATION_VERSION,
    PREVIOUS_PLANNING_ADAPTATION_VERSION,
    PLANNING_ADAPTATION_VERSION,
})

PLANNING_ADAPTATION_PROTOCOL_CODES = frozenset({
    "receipt_schema",
    "authority_hash",
    "planning_hash",
    "segment_identity",
    "event_schema",
    "event_coverage",
    "adaptation_receipt_conflict",
    "adaptation_order_uncertain",
    "adaptation_order_evidence",
    "invariant_schema",
    "evidence_binding",
    "adaptation_reason",
    "summary",
    "whole_receipt_schema",
    "whole_authority_hash",
    "whole_planning_hash",
    "whole_segment_coverage",
    "whole_event_coverage",
    "whole_affected_scope",
    "whole_reason",
    "whole_summary",
})

_CLASSIFICATION_ALIASES = {
    "unchanged": "unchanged",
    "no_change": "unchanged",
    "same": "unchanged",
    "未修改": "unchanged",
    "不变": "unchanged",
    "presentation": "presentation",
    "presentation_only": "presentation",
    "surface": "presentation",
    "表现调整": "presentation",
    "表现层调整": "presentation",
    "equivalent": "equivalent",
    "equivalent_adaptation": "equivalent",
    "adaptive": "equivalent",
    "等价调整": "equivalent",
    "等价展开": "equivalent",
    "structural": "structural",
    "structural_change": "structural",
    "plot_change": "structural",
    "结构性变化": "structural",
    "剧情改写": "structural",
}

_DIMENSION_ALIASES = {
    "dialogue": "dialogue",
    "对话": "dialogue",
    "description": "description",
    "描写": "description",
    "transition": "transition",
    "过渡": "transition",
    "minor_action": "minor_action",
    "次要动作": "minor_action",
    "minor_prop": "minor_prop",
    "次要道具": "minor_prop",
    "scene_realization": "scene_realization",
    "场景展开": "scene_realization",
    "trigger_method": "trigger_method",
    "触发方式": "trigger_method",
    "supporting_actor": "supporting_actor",
    "次要参与者": "supporting_actor",
    "local_location": "local_location",
    "局部地点": "local_location",
    "evidence_method": "evidence_method",
    "证据取得方式": "evidence_method",
    "micro_order": "micro_order",
    "局部顺序": "micro_order",
    "primary_actor_agency": "primary_actor_agency",
    "主要执行者": "primary_actor_agency",
    "人物主动性": "primary_actor_agency",
    "event_function": "event_function",
    "事件功能": "event_function",
    "causal_dependencies": "causal_dependencies",
    "因果依赖": "causal_dependencies",
    "entry_state": "entry_state",
    "入口状态": "entry_state",
    "exit_state": "exit_state",
    "出口状态": "exit_state",
    "knowledge_state": "knowledge_state",
    "知情状态": "knowledge_state",
    "relationship_state": "relationship_state",
    "关系状态": "relationship_state",
    "viewpoint": "viewpoint",
    "视角": "viewpoint",
    "timeline_order": "timeline_order",
    "时间顺序": "timeline_order",
    "promise_ending": "promise_ending",
    "伏笔与结局": "promise_ending",
}

PRESENTATION_DIMENSIONS = frozenset({
    "dialogue", "description", "transition", "minor_action", "minor_prop",
    "scene_realization",
})
EQUIVALENT_DIMENSIONS = PRESENTATION_DIMENSIONS | frozenset({
    "trigger_method", "supporting_actor", "local_location",
    "evidence_method", "micro_order",
})
STRUCTURAL_DIMENSIONS = frozenset({
    "primary_actor_agency", "event_function", "causal_dependencies",
    "entry_state", "exit_state", "knowledge_state", "relationship_state",
    "viewpoint", "timeline_order", "promise_ending",
})

INVARIANT_FIELDS = (
    "event_function",
    "primary_actor_agency",
    "causal_dependencies",
    "entry_state",
    "exit_state",
    "knowledge_state",
    "relationship_state",
    "viewpoint",
    "timeline_order",
    "promise_ending",
)

PLANNING_ADAPTATION_EVENT_FACETS = {
    "function": (
        "event_function", "primary_actor_agency", "causal_dependencies",
    ),
    "state": (
        "entry_state", "exit_state", "knowledge_state", "relationship_state",
    ),
    "continuity": (
        "viewpoint", "timeline_order", "promise_ending",
    ),
}

WHOLE_STORY_FIELDS = (
    "causal_order_preserved",
    "adjacent_handoffs_preserved",
    "knowledge_progression_preserved",
    "relationship_progression_preserved",
    "viewpoint_timeline_preserved",
    "promises_ending_preserved",
    "formal_direction_preserved",
)

_INVARIANT_ALIASES = {
    **{field: field for field in INVARIANT_FIELDS},
    "事件功能": "event_function",
    "主要执行者": "primary_actor_agency",
    "人物主动性": "primary_actor_agency",
    "因果依赖": "causal_dependencies",
    "入口状态": "entry_state",
    "出口状态": "exit_state",
    "知情状态": "knowledge_state",
    "关系状态": "relationship_state",
    "视角": "viewpoint",
    "时间顺序": "timeline_order",
    "伏笔与结局": "promise_ending",
}

_ORDER_DEPENDENCY_ALIASES = {
    "hard": "hard",
    "required": "hard",
    "causal": "hard",
    "硬依赖": "hard",
    "因果依赖": "hard",
    "soft": "soft",
    "presentation": "soft",
    "independent": "soft",
    "软顺序": "soft",
    "展示顺序": "soft",
    "可调整": "soft",
    "unknown": "unknown",
    "uncertain": "unknown",
    "needs_review": "unknown",
    "不确定": "unknown",
    "需复核": "unknown",
}


def _normalized_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    text = re.sub(r"[\s\-]+", "_", text)
    return text


def _boolean(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = _normalized_label(value)
    if normalized in {"true", "yes", "y", "1", "是", "通过", "保留"}:
        return True
    if normalized in {"false", "no", "n", "0", "否", "未通过", "改变"}:
        return False
    return None


def _string_list(value: object) -> list[str] | None:
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value).strip()
        if not normalized:
            return []
        return [
            item.strip() for item in re.split(r"[,，;；\n]+", normalized)
            if item.strip()
        ]
    if not isinstance(value, list):
        return None
    result = []
    for item in value:
        normalized = unicodedata.normalize("NFKC", str(item or "")).strip()
        if not normalized:
            return None
        result.append(normalized)
    return result


def _runtime_event_classification(
    invariants: object, dimensions: object, *, fallback: str = "unresolved",
) -> str:
    if not isinstance(invariants, dict) or set(invariants) != set(INVARIANT_FIELDS) \
            or any(not isinstance(invariants[field], bool) for field in INVARIANT_FIELDS):
        return fallback
    if any(invariants[field] is not True for field in INVARIANT_FIELDS):
        return "structural"
    return "equivalent" if isinstance(dimensions, list) and dimensions else "unchanged"


def planning_adaptation_evidence_candidates(
    plan_segment: str, segment: int,
) -> dict[str, str]:
    """Return exact, bounded plan excerpts for Runtime-owned evidence binding."""
    spans = planning_semantic_evidence_spans(plan_segment, segment)
    return {
        str(item["evidence_id"]): str(item["text"])
        for item in spans
    }


_EVENT_ID_RE = re.compile(
    r"(?<![A-Z0-9_-])EV-[A-Z0-9_-]+(?![A-Z0-9_-])", re.IGNORECASE,
)
_FORMAL_EVENT_ID_RE = re.compile(
    r"(?<![A-Z0-9_-])(?P<event_id>EV-[0-9A-F]{8})"
    r"(?:-[A-Z0-9_-]+)?(?![A-Z0-9_-])",
    re.IGNORECASE,
)
_PROTOCOL_DASHES = frozenset({
    "\u058a", "\u05be", "\u1400", "\u1806", "\u2010", "\u2011", "\u2012",
    "\u2013", "\u2014", "\u2015", "\u2e17", "\u2e1a", "\u2e3a", "\u2e3b",
    "\u2e40", "\u2e5d", "\u301c", "\u3030", "\u30a0", "\ufe31", "\ufe32",
    "\ufe58", "\ufe63", "\uff0d",
})
_PROTOCOL_SLASHES = frozenset({
    "\u2044", "\u2215", "\u29f8", "\u2cc6", "\u2cc7", "\uff0f",
})


def planning_protocol_comparison_view(value: object) -> str:
    """Return a length-preserving Unicode comparison view for protocol text.

    Generated identifiers and labels are machine protocol, while surrounding
    prose remains creative text.  Normalize only one-codepoint presentation
    variants so every returned offset still indexes the original source.
    """
    result: list[str] = []
    for original in str(value or ""):
        normalized = unicodedata.normalize("NFKC", original)
        character = normalized if len(normalized) == 1 else original
        if character in _PROTOCOL_DASHES:
            character = "-"
        elif character in _PROTOCOL_SLASHES:
            character = "/"
        result.append(character)
    return "".join(result)


def planning_event_id_occurrences(
    value: object, *, formal_only: bool = False,
) -> list[tuple[str, int, int]]:
    """Return canonical event IDs with offsets into the unmodified source."""
    comparison = planning_protocol_comparison_view(value)
    pattern = _FORMAL_EVENT_ID_RE if formal_only else _EVENT_ID_RE
    occurrences: list[tuple[str, int, int]] = []
    for match in pattern.finditer(comparison):
        event_id = (
            match.group("event_id") if formal_only else match.group(0)
        ).upper()
        occurrences.append((event_id, match.start(), match.end()))
    return occurrences


def planning_event_ids(
    value: object, *, formal_only: bool = False,
) -> list[str]:
    """Return stable ordered event identity without presentation duplicates."""
    return list(dict.fromkeys(
        event_id
        for event_id, _start, _end in planning_event_id_occurrences(
            value, formal_only=formal_only,
        )
    ))


def remove_planning_event_ids(
    value: object, *, formal_only: bool = False,
) -> str:
    """Remove presentation-variant event IDs without rewriting adjacent prose."""
    source = str(value or "")
    occurrences = planning_event_id_occurrences(source, formal_only=formal_only)
    if not occurrences:
        return source
    pieces: list[str] = []
    cursor = 0
    for _event_id, start, end in occurrences:
        pieces.append(source[cursor:start])
        cursor = end
    pieces.append(source[cursor:])
    return "".join(pieces)

_PLAN_FIELD_RE = re.compile(
    r"(?mi)^[ \t]*(?:[-+*][ \t]+)?(?:#{1,6}[ \t]*)?"
    r"(?:\*{1,2}|_{1,2}|`)?[ \t]*"
    r"(?P<label>事件\s*ID|大纲依据|正式大纲依据|段首承接|本段事件|段末交接|"
    r"event\s*ids?|outline\s*basis|opening|segment\s*events?|handoff)"
    r"[ \t]*(?:\*{1,2}|_{1,2}|`)?[ \t]*[：:][ \t]*",
)


def _field_value_span(text: str, labels: set[str]) -> tuple[int, int] | None:
    matches = list(_PLAN_FIELD_RE.finditer(text))
    for index, match in enumerate(matches):
        label = unicodedata.normalize("NFKC", match.group("label")).lower().replace(" ", "")
        if label not in labels:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        start = match.end()
        while start < end and text[start] in " \t\r\n":
            start += 1
        while end > start and text[end - 1] in " \t\r\n":
            end -= 1
        return start, end
    return None


def _sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    opening = {"“": "”", "「": "」", "『": "』", '"': '"'}
    stack: list[str] = []
    cursor = start
    index = start
    while index < end:
        char = text[index]
        if char in opening:
            closing = opening[char]
            if char == '"' and stack and stack[-1] == '"':
                stack.pop()
            else:
                stack.append(closing)
        elif stack and char == stack[-1]:
            stack.pop()
        if not stack and char in "。！？；!?;":
            value_start = cursor
            while value_start <= index and text[value_start].isspace():
                value_start += 1
            if index + 1 - value_start >= 8:
                result.append((value_start, index + 1))
            cursor = index + 1
        index += 1
    tail = cursor
    while tail < end and text[tail].isspace():
        tail += 1
    if end - tail >= 8:
        result.append((tail, end))
    return result


def planning_semantic_evidence_spans(
    plan_segment: str, segment: int,
) -> list[dict[str, Any]]:
    """Build exact offset-bound anchors from complete semantic units."""
    text = str(plan_segment or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return []
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()

    def add(start: int, end: int, kind: str, parent_event_id: str = "") -> None:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end - start < 8 or (start, end) in seen:
            return
        value = text[start:end]
        plain = value.replace("**", "").replace("__", "").replace("`", "")
        if re.fullmatch(r"#{1,6}\s+.+", value.strip()) or re.match(
            r"^(?:[-+*]\s*)?(?:事件\s*ID|大纲依据|正式大纲依据)\s*[：:]",
            plain.strip(), flags=re.IGNORECASE,
        ):
            return
        seen.add((start, end))
        candidates.append({
            "text": value,
            "start": start,
            "end": end,
            "kind": kind,
            "parent_event_id": parent_event_id,
            "source_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        })

    event_span = _field_value_span(text, {"本段事件", "segmentevents", "segmentevent"})
    if event_span:
        body_start, body_end = event_span
        occurrences = [
            (event_id, body_start + start, body_start + end)
            for event_id, start, end in planning_event_id_occurrences(
                text[body_start:body_end],
            )
        ]
        for index, occurrence in enumerate(occurrences):
            event_id, occurrence_start, _occurrence_end = occurrence
            line_start = text.rfind("\n", body_start, occurrence_start) + 1
            next_start = (
                text.rfind("\n", body_start, occurrences[index + 1][1]) + 1
                if index + 1 < len(occurrences) else body_end
            )
            add(line_start, next_start, "event_block", event_id)
            for sentence_start, sentence_end in _sentence_spans(
                text, line_start, next_start,
            ):
                add(sentence_start, sentence_end, "sentence", event_id)
                sentence = text[sentence_start:sentence_end]
                for split in re.finditer(
                    r"[，,](?=(?:却|但|而|可|只是|然而|不过|反而))", sentence,
                ):
                    clause_start = sentence_start + split.end()
                    add(clause_start, sentence_end, "semantic_clause", event_id)

    for block in re.finditer(r"(?ms)(?:\A|(?<=\n\n))(?P<value>\S.*?)(?=\n\n|\Z)", text):
        start, end = block.span("value")
        event_ids = planning_event_ids(text[start:end])
        add(start, end, "paragraph", event_ids[0] if len(event_ids) == 1 else "")
        for sentence_start, sentence_end in _sentence_spans(text, start, end):
            add(
                sentence_start, sentence_end, "sentence",
                event_ids[0] if len(event_ids) == 1 else "",
            )
    candidates.sort(key=lambda item: (int(item["start"]), int(item["end"]), str(item["kind"])))
    for index, item in enumerate(candidates, 1):
        item["evidence_id"] = f"PLAN-{segment:02d}-E{index:03d}"
    return candidates


def planning_event_body_issues(
    plan_segment: str, expected_event_ids: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    """Verify that every claimed formal event still owns an independent body."""
    expected = [str(value or "").strip().upper() for value in expected_event_ids]
    text = str(plan_segment or "")
    body_values = compile_planning_segment(text).values("event")
    if len(body_values) != 1:
        # A complete formal segment has one event-body field. Zero means this
        # is an event-owned transport excerpt; more than one means a synthetic
        # packet containing several already separated formal blocks. Their
        # individual parent segments own the authoritative validation.
        return []
    body = body_values[0].value
    matches = planning_event_id_occurrences(body)
    actual = [event_id for event_id, _start, _end in matches]
    issues: list[dict[str, Any]] = []
    for event_id in expected:
        indexes = [index for index, value in enumerate(actual) if value == event_id]
        if not indexes:
            inferred = re.sub(r"[\s*_`#（）()\[\]：:，,。.!！?？;；\-]+", "", body)
            if len(expected) == 1 and len(inferred) >= 4:
                continue
            issues.append({
                "code": "event_body_missing",
                "message": "规划正式事件只在段首清单中出现，缺少可执行的独立事件正文",
                "event_id": event_id,
            })
            continue
        if len(indexes) > 1:
            issues.append({
                "code": "event_body_duplicate",
                "message": "规划正式事件在本段事件正文中重复声明",
                "event_id": event_id,
            })
            continue
        index = indexes[0]
        start = matches[index][2]
        end = matches[index + 1][1] if index + 1 < len(matches) else len(body)
        owned = re.sub(r"[\s*_`#（）()\[\]：:，,。.!！?？;；\-]+", "", body[start:end])
        if len(owned) < 8:
            # Adjacent formal events may intentionally share one complete
            # realization (for example, a relationship beat and its private
            # aftermath written as one sentence).  When the IDs are joined
            # only by presentation punctuation, bind the following complete
            # body to both IDs instead of treating the first ID as a collapsed
            # event.  Explicitly separated IDs still require independent
            # executable text, and duplicate IDs remain a hard error.
            if index + 1 < len(matches):
                shared_index = index
                while shared_index + 1 < len(matches):
                    separator = body[
                        matches[shared_index][2]:matches[shared_index + 1][1]
                    ]
                    if re.sub(
                        r"[\s*_`#（）()\[\]：:，,。.!！?？;；、\-]+",
                        "",
                        separator,
                    ):
                        break
                    shared_index += 1
                shared_start = matches[shared_index][2]
                shared_end = (
                    matches[shared_index + 1][1]
                    if shared_index + 1 < len(matches) else len(body)
                )
                shared = re.sub(
                    r"[\s*_`#（）()\[\]：:，,。.!！?？;；\-]+",
                    "",
                    body[shared_start:shared_end],
                )
                if shared_index > index and len(shared) >= 8:
                    continue
            issues.append({
                "code": "event_body_incomplete",
                "message": "规划正式事件缺少足以核对执行者、动作和结果的正文",
                "event_id": event_id,
            })
    filtered = [value for value in actual if value in set(expected)]
    if filtered and list(dict.fromkeys(filtered)) != expected:
        issues.append({
            "code": "event_body_order",
            "message": "规划本段事件正文中的正式事件顺序与段首清单不一致",
            "expected_event_ids": expected,
            "actual_event_ids": list(dict.fromkeys(filtered)),
        })
    return issues


def bind_planning_participant_realizations(
    obligation_checklists: dict[str, dict] | None,
    participant_realizations: dict[str, dict[str, object]] | None,
) -> dict[str, dict]:
    """Bind project-owned identity realizations to every relevant checklist.

    Outline extraction owns canonical participant names.  The narrative
    contract owns alternate textual realizations of the same identity.  This
    adapter keeps those authorities separate and discards stale or unrelated
    realization entries instead of accumulating aliases across projects.
    """
    if not isinstance(obligation_checklists, dict):
        return {}
    authoritative = (
        participant_realizations
        if isinstance(participant_realizations, dict) else {}
    )
    result: dict[str, dict] = {}
    for event_id, raw_checklist in obligation_checklists.items():
        if not isinstance(raw_checklist, dict):
            continue
        checklist = dict(raw_checklist)
        required = {
            unicodedata.normalize("NFKC", str(value or "")).strip()
            for value in (
                checklist.get("identity_stable_participants")
                or checklist.get("required_participants")
                or []
            )
            if str(value or "").strip()
        }
        bound = {
            name: dict(authoritative[name])
            for name in sorted(required)
            if name in authoritative
            and isinstance(authoritative[name], dict)
        }
        if bound:
            checklist["participant_realizations"] = bound
        else:
            checklist.pop("participant_realizations", None)
        result[str(event_id)] = checklist
    return result


def _identity_reference_present(text: str, reference: object) -> bool:
    normalized_text = unicodedata.normalize("NFKC", str(text or ""))
    normalized_reference = unicodedata.normalize(
        "NFKC", str(reference or ""),
    ).strip()
    if not normalized_reference:
        return False
    if all(ord(character) < 128 for character in normalized_reference) \
            and any(character.isalnum() for character in normalized_reference):
        return re.search(
            rf"(?<!\w){re.escape(normalized_reference)}(?!\w)",
            normalized_text,
            flags=re.IGNORECASE,
        ) is not None
    return normalized_reference in normalized_text


def _participant_identity_realized(
    canonical_name: str, event_text: str, checklist: dict[str, Any],
) -> bool:
    normalized_name = unicodedata.normalize("NFKC", canonical_name).strip()
    normalized_event = unicodedata.normalize("NFKC", event_text)
    if normalized_name and normalized_name in normalized_event:
        return True
    mappings = checklist.get("participant_realizations")
    if not isinstance(mappings, dict):
        return False
    realization = mappings.get(normalized_name)
    if not isinstance(realization, dict):
        return False
    if realization.get("kind") != "first_person_narrator":
        return False
    mapped_name = unicodedata.normalize(
        "NFKC", str(realization.get("canonical_name") or ""),
    ).strip()
    references = realization.get("narrative_references")
    if mapped_name != normalized_name or not isinstance(references, list):
        return False
    narrative_voice = narrative_voice_projection(normalized_event)
    return any(
        _identity_reference_present(narrative_voice, reference)
        for reference in references
    )


def planning_event_obligation_issues(
    plan_segment: str, expected_event_ids: list[str] | tuple[str, ...],
    obligation_checklists: dict[str, dict] | None,
) -> list[dict[str, Any]]:
    """Catch a composite formal event that drops an explicitly named participant.

    The check is deliberately narrow.  It applies only when the confirmed event
    names at least two required participants, so a single-actor event may still
    use natural pronouns in planning prose.  It does not judge literary wording;
    semantic action/reaction quality remains the review model's responsibility.
    """
    if not isinstance(obligation_checklists, dict) or not obligation_checklists:
        return []
    expected = [str(value or "").strip().upper() for value in expected_event_ids]
    text = str(plan_segment or "")
    body_span = _field_value_span(
        text, {"本段事件", "segmentevents", "segmentevent"},
    )
    if body_span is None:
        return []
    body = text[body_span[0]:body_span[1]]
    matches = planning_event_id_occurrences(body)
    owned_parts: dict[str, list[str]] = {}
    if not matches and len(expected) == 1:
        owned_parts[expected[0]] = [body]
    else:
        list_items = list(re.finditer(
            r"(?m)^(?P<indent>[ \t]*)(?:\d{1,3}\s*[.、)）]|[-+*])[ \t]+",
            body,
        ))

        def indentation(value: str) -> int:
            return len(value.expandtabs(4))

        for event_id, match_start, _match_end in matches:
            if event_id not in expected:
                continue
            owner_index = next((
                index for index in range(len(list_items) - 1, -1, -1)
                if list_items[index].start() <= match_start
            ), None)
            if owner_index is not None:
                owner = list_items[owner_index]
                owner_indent = indentation(owner.group("indent"))
                start = owner.start()
                end = len(body)
                for sibling in list_items[owner_index + 1:]:
                    if indentation(sibling.group("indent")) <= owner_indent:
                        end = sibling.start()
                        break
            else:
                start = body.rfind("\n\n", 0, match_start) + 2
                paragraph_end = body.find("\n\n", _match_end)
                end = paragraph_end if paragraph_end >= 0 else len(body)
            value = body[start:end].strip()
            if value and value not in owned_parts.setdefault(event_id, []):
                owned_parts[event_id].append(value)
    owned = {
        event_id: "\n".join(parts)
        for event_id, parts in owned_parts.items()
    }

    checklist_by_id = {
        str(key or "").strip().upper(): value
        for key, value in obligation_checklists.items()
        if isinstance(value, dict)
    }
    issues: list[dict[str, Any]] = []
    for event_id in expected:
        checklist = checklist_by_id.get(event_id)
        if not isinstance(checklist, dict):
            continue
        required = [
            str(value or "").strip()
            for value in checklist.get("required_participants", [])
            if str(value or "").strip()
        ]
        stable_values = checklist.get("identity_stable_participants")
        required_for_check = (
            [
                str(value or "").strip()
                for value in stable_values
                if str(value or "").strip()
            ]
            if isinstance(stable_values, list) else required
        )
        if len(required_for_check) < 2:
            continue
        event_text = unicodedata.normalize("NFKC", owned.get(event_id, ""))
        missing = [
            name for name in required_for_check
            if not _participant_identity_realized(name, event_text, checklist)
        ]
        if not missing:
            continue
        affected_obligations = [
            dict(item) for item in checklist.get("obligations", [])
            if isinstance(item, dict) and any(
                name in {
                    str(value or "").strip()
                    for value in item.get("required_participants", [])
                }
                for name in missing
            )
        ]
        kinds = {
            str(kind or "").strip()
            for item in affected_obligations
            for kind in item.get("kinds", [])
            if str(kind or "").strip()
        }
        invariants = {"event_function", "primary_actor_agency"}
        if "outcome" in kinds:
            invariants.add("exit_state")
        if "commitment" in kinds:
            invariants.update({"exit_state", "relationship_state", "promise_ending"})
        issues.append({
            "code": "planning_required_participant_missing",
            "message": "规划正式复合事件遗漏了正式大纲明确要求的参与者、回应者或承诺方",
            "event_id": event_id,
            "classification": "structural",
            "changed_dimensions": ["必需参与者覆盖", *sorted(kinds)],
            "invalid_invariants": [
                field for field in INVARIANT_FIELDS if field in invariants
            ],
            "required_participants": required,
            "missing_participants": missing,
            "obligation_ids": [
                str(item.get("id") or "") for item in affected_obligations
                if str(item.get("id") or "")
            ],
            "formal_obligations": affected_obligations,
            "plan_evidence": [owned.get(event_id, "").strip()],
            "reason": (
                f"正式事件要求同时覆盖{'、'.join(required)}；当前事件正文未明确出现"
                f"{'、'.join(missing)}，因此相应动作、回应、结果或关系承诺无法进入后续状态。"
            ),
        })
    return issues


def repair_planning_event_obligation_coverage(
    plan_segment: str,
    expected_event_ids: list[str] | tuple[str, ...],
    obligation_checklists: dict[str, dict] | None,
) -> tuple[str, list[dict[str, Any]]]:
    """Complete one uniquely owned formal obligation without a model rewrite.

    A confirmed outline can already contain the exact action/reaction text that
    a generated plan accidentally omitted.  When that source is hash-bound,
    names every missing participant, and belongs to exactly one formal event,
    Runtime may append it inside that event's existing list item.  The helper
    never guesses between multiple obligations, never creates prose from a
    diagnostic message, and never edits a sibling event or segment boundary.
    """
    if not isinstance(obligation_checklists, dict) or not obligation_checklists:
        return str(plan_segment or ""), []
    expected = [str(value or "").strip().upper() for value in expected_event_ids]
    if not expected:
        return str(plan_segment or ""), []
    current = str(plan_segment or "")
    repairs: list[dict[str, Any]] = []
    initial_body_issues = planning_event_body_issues(current, expected)

    def safe_obligations(issue: dict[str, Any]) -> list[dict[str, Any]]:
        event_id = str(issue.get("event_id") or "").strip().upper()
        missing = {
            str(value or "").strip()
            for value in issue.get("missing_participants", [])
            if str(value or "").strip()
        }
        if not event_id or not missing:
            return []
        candidates: list[dict[str, Any]] = []
        for raw in issue.get("formal_obligations", []):
            if not isinstance(raw, dict):
                continue
            obligation = dict(raw)
            excerpt = str(obligation.get("source_excerpt") or "").strip()
            source_sha256 = str(obligation.get("source_sha256") or "").strip()
            participants = {
                str(value or "").strip()
                for value in obligation.get("required_participants", [])
                if str(value or "").strip()
            }
            normalized_excerpt = unicodedata.normalize("NFKC", excerpt)
            if (
                not excerpt
                or not source_sha256
                or hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
                != source_sha256
                or not participants
                or not all(name in normalized_excerpt for name in participants)
                or not participants.intersection(missing)
            ):
                continue
            referenced_ids = set(planning_event_ids(excerpt, formal_only=True))
            if referenced_ids - {event_id}:
                continue
            candidates.append(obligation)

        selected: dict[str, dict[str, Any]] = {}
        for name in sorted(missing):
            matches = [
                item for item in candidates
                if name in {
                    str(value or "").strip()
                    for value in item.get("required_participants", [])
                }
            ]
            if len(matches) != 1:
                return []
            identity = str(matches[0].get("id") or "").strip()
            if not identity:
                return []
            selected[identity] = matches[0]
        return [selected[key] for key in selected]

    def append_to_owned_item(
        value: str, event_id: str, obligations: list[dict[str, Any]],
    ) -> str | None:
        body_span = _field_value_span(
            value, {"本段事件", "segmentevents", "segmentevent"},
        )
        if body_span is None:
            return None
        body = value[body_span[0]:body_span[1]]
        occurrences = [
            item for item in planning_event_id_occurrences(body, formal_only=True)
            if item[0] == event_id
        ]
        if len(occurrences) != 1:
            return None
        _identity, occurrence_start, _occurrence_end = occurrences[0]
        list_items = list(re.finditer(
            r"(?m)^(?P<indent>[ \t]*)(?:\d{1,3}\s*[.、)）]|[-+*])[ \t]+",
            body,
        ))
        owner_index = next((
            index for index in range(len(list_items) - 1, -1, -1)
            if list_items[index].start() <= occurrence_start
        ), None)
        if owner_index is None:
            return None
        owner = list_items[owner_index]
        owner_indent = len(owner.group("indent").expandtabs(4))
        owner_end = len(body)
        for sibling in list_items[owner_index + 1:]:
            if len(sibling.group("indent").expandtabs(4)) <= owner_indent:
                owner_end = sibling.start()
                break
        owned = body[owner.start():owner_end]
        owned_ids = planning_event_ids(owned, formal_only=True)
        if owned_ids != [event_id]:
            return None
        insertion = "\n".join(
            " " * (owner_indent + 3)
            + f"- **正式义务补全（{str(item.get('id') or '').strip()}）**："
            + str(item.get("source_excerpt") or "").strip()
            for item in obligations
        )
        if not insertion.strip():
            return None
        trimmed_end = owner_end
        while trimmed_end > owner.start() and body[trimmed_end - 1] in " \t\r\n":
            trimmed_end -= 1
        repaired_body = (
            body[:trimmed_end]
            + "\n"
            + insertion
            + body[trimmed_end:]
        )
        return value[:body_span[0]] + repaired_body + value[body_span[1]:]

    for issue in planning_event_obligation_issues(
        current, expected, obligation_checklists,
    ):
        event_id = str(issue.get("event_id") or "").strip().upper()
        obligations = safe_obligations(issue)
        if not obligations:
            continue
        candidate = append_to_owned_item(current, event_id, obligations)
        if candidate is None:
            continue
        if planning_event_body_issues(candidate, expected) != initial_body_issues:
            continue
        remaining = [
            item for item in planning_event_obligation_issues(
                candidate, expected, obligation_checklists,
            )
            if str(item.get("event_id") or "").strip().upper() == event_id
        ]
        if remaining:
            continue
        current = candidate
        repairs.append({
            "event_id": event_id,
            "obligation_ids": [
                str(item.get("id") or "").strip() for item in obligations
            ],
            "missing_participants": [
                str(value or "").strip()
                for value in issue.get("missing_participants", [])
                if str(value or "").strip()
            ],
            "repair": "append_unique_formal_obligation_excerpt",
        })
    return current, repairs


def repair_planning_event_obligation_ownership(
    plan_segment: str,
    expected_event_ids: list[str] | tuple[str, ...],
    obligation_checklists: dict[str, dict] | None,
) -> tuple[str, list[dict[str, Any]]]:
    """Bind an unlabelled continuation item to its formal event when safe.

    Models often split one composite formal event into adjacent numbered items,
    placing the event ID on the first item and leaving a required response on
    the next item.  The strict ownership checker must continue to reject a
    genuinely independent unlabelled event, so this helper is deliberately a
    separate, deterministic repair step: it only annotates an unlabelled item
    when exactly one affected formal obligation owns all of that item's named
    participants and the item sits between the event's labelled item and the
    next labelled event.  Ambiguous items are left untouched for model repair.
    """
    if not isinstance(obligation_checklists, dict) or not obligation_checklists:
        return str(plan_segment or ""), []
    expected = [str(value or "").strip().upper() for value in expected_event_ids]
    if not expected:
        return str(plan_segment or ""), []
    text = str(plan_segment or "")
    body_span = _field_value_span(text, {"本段事件", "segmentevents", "segmentevent"})
    if body_span is None:
        return text, []
    body = text[body_span[0]:body_span[1]]
    list_items = list(re.finditer(
        r"(?m)^(?P<indent>[ \t]*)(?:\d{1,3}\s*[.、)）]|[-+*])[ \t]+",
        body,
    ))
    if not list_items:
        return text, []

    def item_end(index: int) -> int:
        return list_items[index + 1].start() if index + 1 < len(list_items) else len(body)

    expected_set = set(expected)
    item_values: list[tuple[int, int, str, list[str]]] = []
    for index, match in enumerate(list_items):
        start = match.start()
        end = item_end(index)
        value = body[start:end].strip()
        ids = [
            event_id for event_id in planning_event_ids(value)
            if event_id in expected_set
        ]
        item_values.append((start, end, value, ids))

    checklists = {
        str(key or "").strip().upper(): value
        for key, value in obligation_checklists.items()
        if isinstance(value, dict)
    }
    initial_issues = planning_event_obligation_issues(
        text, expected, obligation_checklists,
    )
    if not initial_issues:
        return text, []

    repairs: list[dict[str, Any]] = []
    replacements: list[tuple[int, int, str]] = []
    for issue in initial_issues:
        event_id = str(issue.get("event_id") or "").strip().upper()
        checklist = checklists.get(event_id)
        if not isinstance(checklist, dict):
            continue
        missing = {
            str(value or "").strip()
            for value in issue.get("missing_participants", [])
            if str(value or "").strip()
        }
        if not missing:
            continue
        affected = [
            item for item in checklist.get("obligations", [])
            if isinstance(item, dict)
            and missing.intersection({
                str(value or "").strip()
                for value in item.get("required_participants", [])
                if str(value or "").strip()
            })
        ]
        matches: list[tuple[int, dict[str, Any]]] = []
        for index, (_start, _end, value, ids) in enumerate(item_values):
            if ids:
                continue
            normalized = unicodedata.normalize("NFKC", value)
            for obligation in affected:
                participants = {
                    str(value or "").strip()
                    for value in obligation.get("required_participants", [])
                    if str(value or "").strip()
                }
                if participants and all(name in normalized for name in participants):
                    matches.append((index, obligation))
        # A continuation is only safe when it is unique.  Requiring a prior
        # owned item prevents borrowing an unrelated item before the event.
        viable = [
            (index, obligation) for index, obligation in matches
            if any(event_id in item_values[prior][3] for prior in range(index))
        ]
        if len(viable) != 1:
            continue
        index, obligation = viable[0]
        start, end, value, _ids = item_values[index]
        if event_id in value:
            continue
        first_line_end = body.find("\n", start, end)
        if first_line_end < 0:
            first_line_end = end
        first_line = body[start:first_line_end]
        unnumbered = re.sub(
            r"^(?P<indent>[ \t]*)(?:\d{1,3}\s*[.、)）]|[-+*])[ \t]+",
            r"\g<indent>", first_line, count=1,
        )
        if unnumbered == first_line:
            continue
        replacement = unnumbered + body[first_line_end:end]
        replacements.append((start, end, replacement))
        repairs.append({
            "event_id": event_id,
            "item_index": index + 1,
            "obligation_id": str(obligation.get("id") or ""),
            "missing_participants": sorted(missing),
            "repair": "merge_unlabelled_continuation_into_prior_event",
        })

    if not replacements:
        return text, []
    repaired_body = body
    for start, end, replacement in sorted(replacements, reverse=True):
        repaired_body = repaired_body[:start] + replacement + repaired_body[end:]
    repaired = text[:body_span[0]] + repaired_body + text[body_span[1]:]
    if planning_event_obligation_issues(repaired, expected, obligation_checklists):
        return text, []
    return repaired, repairs


def planning_event_body_retention_issues(
    source_segment: str, candidate_segment: str,
    expected_event_ids: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    """Reject a repair that technically keeps fields but collapses their story work."""
    source_span = _field_value_span(
        str(source_segment or ""), {"本段事件", "segmentevents", "segmentevent"},
    )
    candidate_span = _field_value_span(
        str(candidate_segment or ""), {"本段事件", "segmentevents", "segmentevent"},
    )
    if source_span is None or candidate_span is None:
        return []

    def meaningful(text: str, span: tuple[int, int]) -> str:
        body = text[span[0]:span[1]]
        body = remove_planning_event_ids(body)
        return re.sub(r"[\s*_`#（）()\[\]：:，,。.!！?？;；\-]+", "", body)

    source = meaningful(str(source_segment or ""), source_span)
    candidate = meaningful(str(candidate_segment or ""), candidate_span)
    minimum = max(12, int(len(source) * 0.35))
    if len(source) >= 20 and len(candidate) < minimum:
        return [{
            "code": "event_body_collapsed",
            "message": "规划修复保留了字段外壳，但删除了事件执行、反应或结果所需的大部分正文",
            "event_ids": [str(value).upper() for value in expected_event_ids],
            "source_characters": len(source),
            "candidate_characters": len(candidate),
            "minimum_characters": minimum,
        }]
    return []


def planning_adaptation_event_projection(
    plan_segment: str, segment: int, event_ids: list[str],
) -> tuple[str, dict[str, str]]:
    """Return exact event-owned plan blocks with stable parent evidence IDs.

    The complete segment remains the persisted authority. This projection only
    changes the transport view for one packet, so merged receipts can still be
    validated against the unchanged parent segment.
    """
    normalized = str(plan_segment or "").replace(
        "\r\n", "\n",
    ).replace("\r", "\n").strip()
    candidates = planning_adaptation_evidence_candidates(normalized, segment)
    requested = list(dict.fromkeys(
        unicodedata.normalize("NFKC", str(value or "")).strip().upper()
        for value in event_ids
        if str(value or "").strip()
    ))
    if not normalized or not requested:
        return normalized, candidates

    requested_set = set(requested)
    document = parse_narrative_document(
        normalized, event_id_extractor=planning_event_ids,
    )
    selected_blocks = document.event_blocks(requested)
    covered = {
        event_id
        for block in selected_blocks
        for event_id in block.owner_event_ids
        if event_id in requested_set
    }

    all_segment_ids = set(planning_event_ids(normalized))
    if covered != requested_set:
        if len(requested) == 1 and len(all_segment_ids) <= 1:
            return normalized, candidates
        # An ambiguous ownership projection is less safe than the complete
        # segment. Keep all exact authority instead of guessing boundaries.
        return normalized, candidates

    projected = document.project_events(requested)
    projected_candidates = {
        evidence_id: value
        for evidence_id, value in candidates.items()
        if value in projected
    }
    if (
        not projected
        or not projected_candidates
        or planning_event_body_issues(projected, requested)
    ):
        return normalized, candidates
    return projected, projected_candidates


def planning_adaptation_event_facet_authority_sha256(
    *, packet_authority_sha256: str, segment: int, event_id: str,
    facet: str, invariant_fields: list[str] | tuple[str, ...],
    version: int = PLANNING_ADAPTATION_VERSION,
) -> str:
    payload = {
        "version": version,
        "packet_authority_sha256": packet_authority_sha256,
        "segment": int(segment),
        "event_id": str(event_id or "").strip().upper(),
        "facet": str(facet or "").strip(),
        "invariant_fields": list(invariant_fields),
    }
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def planning_repair_anchor_ids(
    issues: list[dict], evidence_candidates: dict[str, str],
) -> list[str]:
    """Return the smallest non-overlapping Runtime-owned repair anchors.

    Reviewers may select both a paragraph and one of its lines as evidence. A
    repair should not ask the model to replace both overlapping ranges: doing
    so would silently widen the mutation scope. Prefer the shortest exact
    anchors and keep their original issue order.
    """
    requested: list[str] = []
    issue_quotes: dict[str, str] = {}
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        values = issue.get("plan_evidence_ids")
        if not isinstance(values, list):
            continue
        quote = str(issue.get("plan_evidence_quote") or "").strip()
        for value in values:
            key = str(value or "").strip()
            if key in evidence_candidates and key not in requested:
                requested.append(key)
            if quote and quote in str(evidence_candidates.get(key) or ""):
                issue_quotes.setdefault(key, quote)
    positions = {key: index for index, key in enumerate(requested)}

    def semantic_length(value: str) -> int:
        plain = remove_planning_event_ids(value)
        plain = re.sub(
            r"(?mi)^\s*(?:[-+*]\s*)?(?:事件\s*ID|大纲依据|正式大纲依据|"
            r"段首承接|本段事件|段末交接|event\s*ids?|outline\s*basis|"
            r"opening|segment\s*events?|handoff)\s*[：:]\s*",
            "",
            plain,
        )
        return len(re.sub(r"[\s*_`#（）()\[\]：:，,。.!！?？;；\-]+", "", plain))

    def shrink(key: str) -> str:
        """Shrink broad model evidence only through exact nested authority.

        A reviewer can legally bind a complete segment paragraph even when a
        smaller Runtime-owned event block exists inside it.  Replacing the
        complete paragraph is unsafe (it may contain a heading or neighboring
        fields), while choosing an arbitrary sentence is also unsafe.  Keep
        the smallest nested candidate that has the same event-ID set and enough
        semantic body to remain a complete event realization.  If no such
        candidate exists, retain the original evidence ID and let the complete
        segment ladder handle recovery.
        """
        outer = str(evidence_candidates.get(key) or "")
        if not outer:
            return key
        quote = issue_quotes.get(key, "")
        if quote:
            quoted_nested: list[tuple[int, int, str]] = []
            for candidate_id, candidate in evidence_candidates.items():
                candidate = str(candidate or "")
                if (
                    not candidate or candidate == outer or candidate not in outer
                    or quote not in candidate or "###" in candidate
                    or semantic_length(candidate) < 6
                ):
                    continue
                quoted_nested.append((
                    len(candidate), positions.get(candidate_id, len(positions)),
                    candidate_id,
                ))
            if quoted_nested:
                quoted_nested.sort()
                return quoted_nested[0][2]
        outer_event_ids = tuple(planning_event_ids(outer))
        if not outer_event_ids:
            return key
        nested: list[tuple[int, int, str]] = []
        for candidate_id, candidate in evidence_candidates.items():
            candidate = str(candidate or "")
            if not candidate or candidate == outer or candidate not in outer:
                continue
            if "###" in candidate:
                continue
            candidate_event_ids = tuple(planning_event_ids(candidate))
            if candidate_event_ids != outer_event_ids:
                continue
            if semantic_length(candidate) < 20:
                continue
            nested.append((len(candidate), positions.get(candidate_id, len(positions)), candidate_id))
        if not nested:
            return key
        nested.sort()
        return nested[0][2]

    requested = [shrink(key) for key in requested]
    requested = list(dict.fromkeys(requested))
    positions = {key: index for index, key in enumerate(requested)}
    requested.sort(key=lambda key: (len(evidence_candidates[key]), positions[key]))
    selected: list[str] = []
    selected_values: list[str] = []
    for key in requested:
        value = evidence_candidates[key]
        if any(value in existing or existing in value for existing in selected_values):
            continue
        selected.append(key)
        selected_values.append(value)
    return sorted(selected, key=positions.__getitem__)


def planning_evidence_quote_valid(
    review: object, evidence_candidates: dict[str, str],
) -> bool:
    """Bind every negative invariant to one exact current-plan problem phrase.

    A hash and an evidence ID prove which candidate was reviewed, but they do
    not prove that the review reason describes text that is actually present in
    that candidate.  Negative verdicts therefore need one verbatim phrase from
    their selected Runtime-owned evidence.  This prevents stale findings from
    a rejected plan from consuming semantic-repair budget on the current plan.
    """
    if not isinstance(review, dict):
        return False
    invariants = review.get("invariants")
    if not isinstance(invariants, dict) or not any(
        value is False for value in invariants.values()
    ):
        return True
    evidence_ids = review.get("plan_evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        return False
    quote = str(review.get("plan_evidence_quote") or "").strip()
    reason = str(review.get("reason") or "")
    semantic_length = len(re.sub(
        r"[^\w]+", "", unicodedata.normalize("NFKC", quote),
        flags=re.UNICODE,
    ))
    if semantic_length < 6 or quote not in reason:
        return False
    return any(
        quote in str(evidence_candidates.get(str(evidence_id)) or "")
        for evidence_id in evidence_ids
    )


def planning_repair_patch_authority_sha256(
    *, planning_sha256: str, segment: int, issue_keys: list[str],
    anchor_ids: list[str], version: int = PLANNING_ADAPTATION_VERSION,
) -> str:
    payload = {
        "version": version,
        "planning_sha256": planning_sha256,
        "segment": segment,
        "issue_keys": list(issue_keys),
        "anchor_ids": list(anchor_ids),
    }
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def normalize_planning_repair_patch(
    value: object, *, authority_sha256: str, segment: int,
    evidence_candidates: dict[str, str], allowed_anchor_ids: list[str],
    current_segment: str,
) -> dict:
    """Validate a bounded evidence replacement returned by the repair model."""
    if not isinstance(value, dict):
        raise ValueError("规划修复补丁必须是一个 JSON 对象")
    if value.get("authority_sha256") != authority_sha256:
        raise ValueError("规划修复补丁绑定的审核问题已经过期")
    try:
        returned_segment = int(value.get("segment"))
    except (TypeError, ValueError):
        raise ValueError("规划修复补丁缺少有效分段编号") from None
    if returned_segment != segment:
        raise ValueError("规划修复补丁返回了错误的分段编号")
    replacements = value.get("replacements")
    if not isinstance(replacements, list) or not replacements:
        raise ValueError("规划修复补丁必须包含 replacements")
    allowed = set(allowed_anchor_ids)
    seen: set[str] = set()
    normalized: list[dict[str, str]] = []
    for item in replacements:
        if not isinstance(item, dict):
            raise ValueError("规划修复补丁中的 replacement 格式无效")
        evidence_id = str(item.get("evidence_id") or "").strip()
        if evidence_id not in allowed or evidence_id in seen:
            raise ValueError("规划修复补丁引用了未授权或重复的原文锚点")
        old = evidence_candidates.get(evidence_id)
        replacement = str(item.get("replacement") or "")
        if not old or not replacement.strip():
            raise ValueError("规划修复补丁的替换内容不能为空")
        if current_segment.count(old) != 1:
            raise ValueError("规划修复补丁的原文锚点不再唯一")
        source_sha256 = str(item.get("source_sha256") or "")
        expected_source_sha256 = hashlib.sha256(old.encode("utf-8")).hexdigest()
        if source_sha256 and source_sha256 != expected_source_sha256:
            raise ValueError("规划修复补丁的原文锚点哈希不匹配")
        if "###" in replacement or "SHORT_CAUSAL_CHAIN" in replacement:
            raise ValueError("规划修复补丁不得写入段落标题或因果链协议块")
        seen.add(evidence_id)
        normalized.append({
            "evidence_id": evidence_id,
            "source_sha256": expected_source_sha256,
            "replacement": replacement,
        })
    return {
        "authority_sha256": authority_sha256,
        "segment": segment,
        "replacements": normalized,
        "summary": str(value.get("summary") or "").strip(),
    }


def planning_repair_patch_from_segment(
    candidate_segment: str, *, authority_sha256: str, segment: int,
    evidence_candidates: dict[str, str], allowed_anchor_ids: list[str],
    current_segment: str,
) -> dict:
    """Convert a legacy full-segment response only when it changed anchors alone."""
    anchors: list[tuple[int, str, str]] = []
    for evidence_id in allowed_anchor_ids:
        old = evidence_candidates.get(evidence_id)
        if not old or current_segment.count(old) != 1:
            raise ValueError("规划完整段兼容回退的原文锚点不再唯一")
        anchors.append((current_segment.index(old), evidence_id, old))
    anchors.sort()
    if not anchors:
        raise ValueError("规划完整段兼容回退缺少授权锚点")
    cursor = 0
    pattern = "^"
    for start, _evidence_id, old in anchors:
        if start < cursor:
            raise ValueError("规划完整段兼容回退包含重叠授权锚点")
        pattern += re.escape(current_segment[cursor:start]) + "(.*?)"
        cursor = start + len(old)
    pattern += re.escape(current_segment[cursor:]) + "$"
    match = re.fullmatch(pattern, candidate_segment, flags=re.DOTALL)
    if match is None:
        raise ValueError("规划完整段兼容回退修改了授权锚点以外的内容")
    replacements = []
    for (_start, evidence_id, old), replacement in zip(
        anchors, match.groups(), strict=True,
    ):
        if replacement == old:
            continue
        replacements.append({
            "evidence_id": evidence_id,
            "source_sha256": hashlib.sha256(old.encode("utf-8")).hexdigest(),
            "replacement": replacement,
        })
    if not replacements:
        raise ValueError("规划完整段兼容回退没有产生有效修改")
    return normalize_planning_repair_patch(
        {
            "authority_sha256": authority_sha256,
            "segment": segment,
            "replacements": replacements,
            "summary": "legacy full-segment response narrowed to authorized anchors",
        },
        authority_sha256=authority_sha256,
        segment=segment,
        evidence_candidates=evidence_candidates,
        allowed_anchor_ids=allowed_anchor_ids,
        current_segment=current_segment,
    )


def apply_planning_repair_patch(
    current_segment: str, patch: dict, evidence_candidates: dict[str, str],
) -> str:
    """Apply only the exact anchors authorized by the current issue receipt."""
    result = current_segment
    replacements = []
    for item in patch.get("replacements", []):
        old = evidence_candidates[item["evidence_id"]]
        start = result.find(old)
        if start < 0 or result.count(old) != 1:
            raise ValueError("规划修复补丁无法在当前分段中定位原文锚点")
        replacements.append((start, old, item["replacement"]))
    for start, old, replacement in sorted(replacements, reverse=True):
        result = result[:start] + replacement + result[start + len(old):]
    return result


def planning_adaptation_segment_authority_sha256(
    *, outline_sha256: str, planning_sha256: str, segment: int,
    event_contracts: list[dict], plan_segment: str,
    previous_handoff: str = "", next_entry: str = "",
    generation_context_sha256: str = "",
    version: int = PLANNING_ADAPTATION_VERSION,
) -> str:
    payload = {
        "version": version,
        "outline_sha256": outline_sha256,
        "segment": segment,
        "event_contracts": event_contracts,
        "plan_segment": plan_segment,
    }
    if version == LEGACY_PLANNING_ADAPTATION_VERSION:
        payload["planning_sha256"] = planning_sha256
    elif version == PREVIOUS_PLANNING_ADAPTATION_VERSION:
        payload.update({
            "previous_handoff": previous_handoff,
            "next_entry": next_entry,
            "generation_context_sha256": generation_context_sha256,
        })
    else:
        # V3 separates the local event realization from mutable neighboring
        # handoffs. Boundary and whole-plan authority still binds those
        # handoffs; a byte-identical unaffected segment must not be re-judged
        # merely because its sibling changed.
        payload.update({
            "generation_context_sha256": generation_context_sha256,
        })
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def planning_adaptation_segment_packet_authority_sha256(
    *, segment_authority_sha256: str, segment: int,
    event_ids: list[str] | tuple[str, ...],
    version: int = PLANNING_ADAPTATION_VERSION,
) -> str:
    """Bind a capacity-split review packet to one immutable segment scope.

    The packet is only a transport topology.  Its authority remains rooted in
    the complete segment hash and the ordered event IDs it owns, so a packet
    cannot be reused for another segment or silently broaden its scope.
    """
    payload = {
        "version": version,
        "segment_authority_sha256": segment_authority_sha256,
        "segment": segment,
        "event_ids": [str(value).strip().upper() for value in event_ids],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def planning_adaptation_whole_authority_sha256(
    *, outline_sha256: str, planning_sha256: str,
    segment_receipts: list[dict],
    version: int = PLANNING_ADAPTATION_VERSION,
) -> str:
    payload = {
        "version": version,
        "outline_sha256": outline_sha256,
        "planning_sha256": planning_sha256,
        "segment_receipts": segment_receipts,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_planning_adaptation_receipt(
    receipt: object, *, evidence_candidates: dict[str, str],
) -> object:
    """Normalize documented model-output variants without rewriting prose."""
    if not isinstance(receipt, dict):
        return receipt
    result = dict(receipt)
    segment = result.get("segment")
    try:
        result["segment"] = int(unicodedata.normalize("NFKC", str(segment)))
    except (TypeError, ValueError):
        pass
    result["segment_order_preserved"] = _boolean(
        result.get("segment_order_preserved")
    )
    result["formal_direction_preserved"] = _boolean(
        result.get("formal_direction_preserved")
    )
    raw_reviews = result.get("event_reviews")
    if not isinstance(raw_reviews, list):
        return result
    reviews: list[object] = []
    for raw in raw_reviews:
        if not isinstance(raw, dict):
            reviews.append(raw)
            continue
        item = dict(raw)
        item["event_id"] = unicodedata.normalize(
            "NFKC", str(item.get("event_id") or ""),
        ).strip().upper()
        raw_classification = unicodedata.normalize(
            "NFKC", str(item.get(
                "raw_classification", item.get("classification"),
            ) or ""),
        ).strip()
        model_classification = _CLASSIFICATION_ALIASES.get(
            _normalized_label(raw_classification),
        )
        item["raw_classification"] = raw_classification
        item["model_classification"] = (
            model_classification or _normalized_label(raw_classification)
        )
        raw_dimension_value = item.get(
            "raw_changed_dimensions", item.get("changed_dimensions"),
        )
        raw_dimensions = _string_list(raw_dimension_value)
        if raw_dimensions is None:
            raw_dimensions = []
            if raw_dimension_value is not None:
                item["raw_changed_dimensions_unparsed"] = raw_dimension_value
        raw_dimensions = list(dict.fromkeys(raw_dimensions))
        canonical_dimensions: list[str] = []
        unrecognized_dimensions: list[str] = []
        normalized_dimensions: list[str] = []
        for dimension in raw_dimensions:
            canonical = _DIMENSION_ALIASES.get(_normalized_label(dimension))
            if canonical:
                canonical_dimensions.append(canonical)
                normalized_dimensions.append(canonical)
            else:
                unrecognized_dimensions.append(dimension)
                normalized_dimensions.append(dimension)
        item["raw_changed_dimensions"] = raw_dimensions
        item["canonical_dimensions"] = list(dict.fromkeys(canonical_dimensions))
        item["unrecognized_dimensions"] = list(dict.fromkeys(
            unrecognized_dimensions
        ))
        # Keep the legacy field readable, but never use its vocabulary as an
        # authorization boundary. Known aliases remain canonical for backward
        # compatibility; unknown descriptions stay lossless.
        item["changed_dimensions"] = list(dict.fromkeys(normalized_dimensions))
        raw_order_dependency = item.get("order_dependency")
        order_dependency = _ORDER_DEPENDENCY_ALIASES.get(
            _normalized_label(raw_order_dependency),
        )
        if raw_order_dependency is not None:
            item["raw_order_dependency"] = raw_order_dependency
        if order_dependency:
            item["order_dependency"] = order_dependency
        dependency_event_ids = _string_list(item.get("dependency_event_ids"))
        if dependency_event_ids is not None:
            item["dependency_event_ids"] = [
                unicodedata.normalize("NFKC", value).strip().upper()
                for value in dependency_event_ids
            ]
        evidence_ids = _string_list(
            item.get("plan_evidence_ids", item.get("plan_evidence_id")),
        )
        if evidence_ids is not None:
            item["plan_evidence_ids"] = evidence_ids
            item["plan_evidence"] = [
                evidence_candidates[evidence_id]
                for evidence_id in evidence_ids
                if evidence_id in evidence_candidates
            ]
        evidence_quote = item.get(
            "plan_evidence_quote", item.get("evidence_quote"),
        )
        if isinstance(evidence_quote, str):
            item["plan_evidence_quote"] = evidence_quote.strip()
        raw_invariants = item.get("invariants")
        if isinstance(raw_invariants, dict):
            invariants: dict[str, object] = {}
            for key, value in raw_invariants.items():
                canonical = _INVARIANT_ALIASES.get(_normalized_label(key))
                if canonical:
                    invariants[canonical] = _boolean(value)
            item["invariants"] = invariants
        invariants = item.get("invariants")
        if isinstance(invariants, dict) and order_dependency == "soft" \
                and invariants.get("timeline_order") is False \
                and all(
                    invariants.get(field) is True
                    for field in INVARIANT_FIELDS if field != "timeline_order"
                ):
            item["raw_invariants"] = dict(invariants)
            invariants = dict(invariants)
            invariants["timeline_order"] = True
            item["invariants"] = invariants
            item["soft_order_authorized"] = True
        runtime_classification = _runtime_event_classification(
            invariants, raw_dimensions,
            fallback=model_classification or "unresolved",
        )
        if runtime_classification != (model_classification or "unresolved") \
                or runtime_classification in {"unchanged", "equivalent", "structural"}:
            item["classification"] = runtime_classification
            item["classification_source"] = "runtime_invariants"
        else:
            item["classification"] = model_classification or "unresolved"
            item["classification_source"] = "model_pending_invariant_validation"
        reviews.append(item)
    result["event_reviews"] = reviews
    return result


def planning_adaptation_receipt_issues(
    receipt: object, *, authority_sha256: str, planning_sha256: str,
    segment: int, expected_event_ids: list[str],
    evidence_candidates: dict[str, str],
    authority_version: int = PLANNING_ADAPTATION_VERSION,
    authority_event_ids: list[str] | None = None,
    plan_segment: str = "",
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    def add(code: str, message: str, **metadata: Any) -> None:
        issues.append({"code": code, "message": message, **metadata})

    if not isinstance(receipt, dict):
        add("receipt_schema", "规划适配回执必须是一个 JSON 对象")
        return issues
    if receipt.get("authority_sha256") != authority_sha256:
        add("authority_hash", "规划适配回执没有绑定当前正式大纲和规划段")
    if authority_version == LEGACY_PLANNING_ADAPTATION_VERSION \
            and receipt.get("planning_sha256") != planning_sha256:
        add("planning_hash", "规划适配回执绑定的规划稿已经过期")
    if receipt.get("segment") != segment:
        add("segment_identity", "规划适配回执返回了错误的正式段编号")
    raw_reviews = receipt.get("event_reviews")
    if not isinstance(raw_reviews, list) or any(
        not isinstance(item, dict) for item in raw_reviews
    ):
        add("event_schema", "规划适配回执的 event_reviews 格式不完整")
        return issues
    returned_ids = [str(item.get("event_id") or "").upper() for item in raw_reviews]
    expected_ids = [str(item).upper() for item in expected_event_ids]
    event_body_issues = (
        planning_event_body_issues(plan_segment, expected_ids)
        if plan_segment else []
    )
    missing_body_ids = {
        str(item.get("event_id") or "").upper()
        for item in event_body_issues
        if str(item.get("code") or "").startswith("event_body_")
    }
    issues.extend(event_body_issues)
    dependency_authority_ids = {
        str(item).upper() for item in (authority_event_ids or expected_event_ids)
    }
    if returned_ids != expected_ids:
        add(
            "event_coverage", "规划适配回执没有按顺序覆盖当前段全部正式事件",
            expected_event_ids=expected_ids, actual_event_ids=returned_ids,
        )
    for item in raw_reviews:
        event_id = str(item.get("event_id") or "").upper()
        classification = str(item.get("classification") or "unresolved")
        dimensions = item.get("changed_dimensions")
        dimensions = dimensions if isinstance(dimensions, list) else []
        evidence_ids = item.get("plan_evidence_ids")
        bound_evidence = item.get("plan_evidence")
        if event_id not in missing_body_ids and (
            not isinstance(evidence_ids, list) or not evidence_ids
            or any(evidence_id not in evidence_candidates for evidence_id in evidence_ids)
            or not isinstance(bound_evidence, list)
            or bound_evidence != [evidence_candidates[value] for value in evidence_ids]
        ):
            add(
                "evidence_binding", "规划适配回执没有绑定当前规划段的准确原文",
                event_id=event_id,
            )
        invariants = item.get("invariants")
        if not isinstance(invariants, dict) or set(invariants) != set(INVARIANT_FIELDS) \
                or any(not isinstance(invariants[field], bool) for field in INVARIANT_FIELDS):
            add(
                "invariant_schema", "规划适配回执没有逐项核对全部剧情不变量",
                event_id=event_id,
            )
            continue
        false_invariants = [
            field for field in INVARIANT_FIELDS if invariants[field] is not True
        ]
        if false_invariants and event_id not in missing_body_ids \
                and not planning_evidence_quote_valid(
            item, evidence_candidates,
        ):
            add(
                "evidence_binding",
                "规划适配回执没有用当前规划原文中的具体问题句证明负面判断",
                event_id=event_id,
            )
            # This is a receipt protocol defect, not verified semantic drift.
            # Retry only the immutable review receipt instead of spending a
            # planning-repair attempt on stale or unrelated evidence.
            continue
        if false_invariants == ["timeline_order"]:
            order_dependency = str(item.get("order_dependency") or "unknown")
            dependency_event_ids = item.get("dependency_event_ids")
            if order_dependency == "unknown":
                add(
                    "adaptation_order_uncertain",
                    "规划顺序变化尚未说明是硬因果依赖还是可调整展示顺序，需要只重审回执",
                    event_id=event_id,
                )
                continue
            if order_dependency == "hard" and (
                not isinstance(dependency_event_ids, list)
                or not dependency_event_ids
                or any(value not in dependency_authority_ids for value in dependency_event_ids)
            ):
                add(
                    "adaptation_order_evidence",
                    "规划顺序被判为硬依赖，但回执没有绑定有效的依赖事件 ID",
                    event_id=event_id,
                )
                continue
        described_structural = sorted(
            set(item.get("canonical_dimensions") or []) & STRUCTURAL_DIMENSIONS
        )
        model_classification = str(item.get("model_classification") or "")
        if not false_invariants and (
            model_classification == "structural" or described_structural
        ):
            add(
                "adaptation_receipt_conflict",
                "规划适配回执的变化描述与逐项剧情不变量互相矛盾，需要只重审回执",
                event_id=event_id,
                model_classification=model_classification,
                described_structural_dimensions=described_structural,
                raw_changed_dimensions=list(item.get("raw_changed_dimensions") or []),
            )
        if false_invariants:
            add(
                "planning_structural_drift",
                "规划改变了正式事件的剧情功能、人物主动性、因果或后续状态",
                event_id=event_id,
                classification=classification,
                changed_dimensions=list(dimensions),
                invalid_invariants=false_invariants,
                reason=str(item.get("reason") or "").strip()[:800],
                plan_evidence_ids=list(evidence_ids),
                plan_evidence=list(bound_evidence or []),
                plan_evidence_quote=str(
                    item.get("plan_evidence_quote") or ""
                ).strip(),
            )
        if classification != "unchanged" and not str(item.get("reason") or "").strip():
            add(
                "adaptation_reason", "非原样规划调整必须说明等价性或结构风险",
                event_id=event_id,
            )
    if receipt.get("segment_order_preserved") is not True:
        evidence_ids = [
            str(value) for item in raw_reviews
            if isinstance(item, dict)
            for value in (item.get("plan_evidence_ids") or [])
            if str(value) in evidence_candidates
        ]
        add(
            "planning_segment_order", "规划调整改变了正式事件的展示或依赖顺序",
            plan_evidence_ids=evidence_ids,
            plan_evidence=[evidence_candidates[value] for value in evidence_ids],
        )
    if receipt.get("formal_direction_preserved") is not True:
        evidence_ids = [
            str(value) for item in raw_reviews
            if isinstance(item, dict)
            for value in (item.get("plan_evidence_ids") or [])
            if str(value) in evidence_candidates
        ]
        add(
            "planning_formal_direction", "规划调整改变了正式剧情方向或结局承诺",
            plan_evidence_ids=evidence_ids,
            plan_evidence=[evidence_candidates[value] for value in evidence_ids],
        )
    if not str(receipt.get("summary") or "").strip():
        add("summary", "规划适配回执缺少核对摘要")
    return issues


def normalize_planning_adaptation_whole_receipt(receipt: object) -> object:
    if not isinstance(receipt, dict):
        return receipt
    result = dict(receipt)
    for field in WHOLE_STORY_FIELDS:
        result[field] = _boolean(result.get(field))
    raw_segments = _string_list(result.get("segment_numbers"))
    if raw_segments is not None:
        try:
            result["segment_numbers"] = [int(value) for value in raw_segments]
        except ValueError:
            result["segment_numbers"] = raw_segments
    affected_segments = _string_list(result.get("affected_segments"))
    if affected_segments is not None:
        try:
            result["affected_segments"] = [int(value) for value in affected_segments]
        except ValueError:
            result["affected_segments"] = affected_segments
    for field in ("event_ids", "affected_event_ids"):
        values = _string_list(result.get(field))
        if values is not None:
            result[field] = [
                unicodedata.normalize("NFKC", value).strip().upper()
                for value in values
            ]
    return result


def planning_adaptation_whole_receipt_issues(
    receipt: object, *, authority_sha256: str, planning_sha256: str,
    segment_count: int, expected_event_ids: list[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    def add(code: str, message: str, **metadata: Any) -> None:
        issues.append({"code": code, "message": message, **metadata})

    if not isinstance(receipt, dict):
        add("whole_receipt_schema", "整篇规划适配回执必须是一个 JSON 对象")
        return issues
    if receipt.get("authority_sha256") != authority_sha256:
        add("whole_authority_hash", "整篇规划适配回执没有绑定全部分段回执")
    if receipt.get("planning_sha256") != planning_sha256:
        add("whole_planning_hash", "整篇规划适配回执绑定的规划稿已经过期")
    expected_segments = list(range(1, segment_count + 1))
    if receipt.get("segment_numbers") != expected_segments:
        add(
            "whole_segment_coverage", "整篇规划适配回执没有覆盖全部连续分段",
            expected_segments=expected_segments,
            actual_segments=receipt.get("segment_numbers"),
        )
    expected_ids = [str(item).upper() for item in expected_event_ids]
    if receipt.get("event_ids") != expected_ids:
        add(
            "whole_event_coverage", "整篇规划适配回执没有按顺序覆盖全部正式事件",
            expected_event_ids=expected_ids,
            actual_event_ids=receipt.get("event_ids"),
        )
    affected_segments = receipt.get("affected_segments")
    affected_event_ids = receipt.get("affected_event_ids")
    affected_scope_valid = not (
        not isinstance(affected_segments, list)
        or any(not isinstance(item, int) or item not in expected_segments for item in affected_segments)
        or not isinstance(affected_event_ids, list)
        or any(str(item).upper() not in expected_ids for item in affected_event_ids)
    )
    invalid = [field for field in WHOLE_STORY_FIELDS if receipt.get(field) is not True]
    if not affected_scope_valid or (
        bool(invalid) and (not affected_segments or not affected_event_ids)
    ) or (
        not invalid and (bool(affected_segments) or bool(affected_event_ids))
    ):
        add("whole_affected_scope", "整篇规划适配回执的受影响范围不合法")
    if invalid:
        if not str(receipt.get("reason") or "").strip():
            add("whole_reason", "整篇规划适配回执没有说明跨段问题的具体原因")
        add(
            "planning_whole_story_drift",
            "规划分段单独成立，但合并后改变了整篇因果、衔接、状态推进或结局承诺",
            invalid_dimensions=invalid,
            affected_segments=affected_segments if isinstance(affected_segments, list) else [],
            affected_event_ids=(
                affected_event_ids if isinstance(affected_event_ids, list) else []
            ),
            reason=str(receipt.get("reason") or "").strip()[:1000],
        )
    if not str(receipt.get("summary") or "").strip():
        add("whole_summary", "整篇规划适配回执缺少核对摘要")
    return issues


def planning_adaptation_issues_are_protocol_only(issues: list[dict]) -> bool:
    return bool(issues) and all(
        str(item.get("code") or "") in PLANNING_ADAPTATION_PROTOCOL_CODES
        for item in issues
    )


def planning_adaptation_artifact_sha256(artifact: dict) -> str:
    encoded = json.dumps(
        artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def effective_event_contracts(
    formal_contracts: list[dict], adaptation_artifact: dict | None,
) -> list[dict]:
    """Use only independently authorized plan realizations as downstream evidence."""
    if not isinstance(adaptation_artifact, dict) \
            or adaptation_artifact.get("status") != "ready":
        return [dict(item) for item in formal_contracts]
    reviews: dict[str, list[dict]] = {}
    for review in (
        review
        for segment in adaptation_artifact.get("segments", [])
        if isinstance(segment, dict)
        for review in segment.get("event_reviews", [])
        if isinstance(review, dict)
    ):
        reviews.setdefault(
            str(review.get("event_id") or "").upper(), [],
        ).append(review)
    rank = {"unchanged": 0, "equivalent": 1, "structural": 2}
    result = []
    for contract in formal_contracts:
        event = dict(contract)
        event_id = str(event.get("id") or "").upper()
        event_reviews = reviews.get(event_id, [])
        evidence = list(dict.fromkeys(
            str(item)
            for review in event_reviews
            for item in review.get("plan_evidence", [])
            if str(item).strip()
        ))
        if event_reviews and evidence:
            review_classifications = [
                _runtime_event_classification(
                    review.get("invariants"),
                    review.get(
                        "raw_changed_dimensions", review.get("changed_dimensions", []),
                    ),
                    fallback=(
                        "equivalent"
                        if str(review.get("classification") or "") == "presentation"
                        else str(review.get("classification") or "unchanged")
                    ),
                )
                for review in event_reviews
            ]
            classification = max(
                review_classifications,
                key=lambda value: rank.get(value, 99),
            )
            dimensions = list(dict.fromkeys(
                str(item)
                for review in event_reviews
                for item in review.get("changed_dimensions", [])
            ))
            raw_dimensions = list(dict.fromkeys(
                str(item)
                for review in event_reviews
                for item in review.get("raw_changed_dimensions", [])
            ))
            canonical_dimensions = list(dict.fromkeys(
                str(item)
                for review in event_reviews
                for item in review.get("canonical_dimensions", [])
            ))
            unrecognized_dimensions = list(dict.fromkeys(
                str(item)
                for review in event_reviews
                for item in review.get("unrecognized_dimensions", [])
            ))
            model_classifications = list(dict.fromkeys(
                str(review.get("raw_classification") or "").strip()
                for review in event_reviews
                if str(review.get("raw_classification") or "").strip()
            ))
            invariants = {
                field: all(
                    (review.get("invariants") or {}).get(field) is True
                    for review in event_reviews
                )
                for field in INVARIANT_FIELDS
            }
            event["formal_evidence"] = str(event.get("evidence") or "")
            event["evidence"] = "\n\n".join(str(item) for item in evidence)
            event["source"] = "accepted_plan_adaptation"
            event["adaptation"] = {
                "classification": classification,
                "changed_dimensions": dimensions,
                "raw_changed_dimensions": raw_dimensions,
                "canonical_dimensions": canonical_dimensions,
                "unrecognized_dimensions": unrecognized_dimensions,
                "model_classifications": model_classifications,
                "invariants": invariants,
                "reason": "；".join(dict.fromkeys(
                    str(review.get("reason") or "").strip()
                    for review in event_reviews
                    if str(review.get("reason") or "").strip()
                )),
            }
        result.append(event)
    return result
