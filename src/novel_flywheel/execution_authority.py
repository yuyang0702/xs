from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable


EXECUTION_FRAGMENT_AUTHORITY_VERSION = "execution-fragment-authority-v2"
PLANNING_EVIDENCE_REFERENCE_VERSION = "planning-evidence-ref-v1"


@dataclass(frozen=True)
class ContentAddressedCollectionIR:
    items: tuple[object, ...]
    source_sha256: str
    event_index: dict[str, tuple[int, ...]]
    unscoped_entries: int
    item_event_ids: tuple[tuple[str, ...], ...]
    item_event_id_sets: tuple[frozenset[str], ...]
    item_sha256: tuple[str, ...]
    item_event_ids_sha256: tuple[str, ...]
    bounded_shared_body: tuple[dict[str, Any] | None, ...]
    nested_event_index: dict[str, dict[int, tuple[dict[str, Any], ...]]]


@dataclass(frozen=True)
class ExecutionFragmentAuthorityIR:
    causal_chain: dict[str, Any]
    causal_chain_sha256: str
    question_chain: ContentAddressedCollectionIR
    relationship_arc: ContentAddressedCollectionIR
    timeline_events: ContentAddressedCollectionIR
    presentation_order: tuple[str, ...]
    presentation_order_sha256: str
    order_index: dict[str, int]
    viewpoint_rule: str


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def planning_evidence_reference(
    *, segment: int, event_id: str, event_body: str,
) -> str:
    """Return a bounded content address instead of duplicating a segment body."""

    body_sha256 = hashlib.sha256(event_body.encode("utf-8")).hexdigest()
    return (
        f"{PLANNING_EVIDENCE_REFERENCE_VERSION}:"
        f"segment-{segment:02d}:{event_id}:{body_sha256}"
    )


def _item_event_ids(item: object) -> tuple[str, ...]:
    if not isinstance(item, dict):
        return ()
    raw = item.get("event_ids")
    if raw is None:
        raw = [item.get("event_id")] if item.get("event_id") else []
    if not isinstance(raw, list):
        return ()
    return tuple(
        str(value).strip().upper() for value in raw
        if str(value).strip()
    )


def _complex_reference(value: object) -> dict[str, Any]:
    count = len(value) if isinstance(value, (dict, list)) else 1
    return {
        "content_addressed": True,
        "source_sha256": canonical_sha256(value),
        "source_count": count,
    }


def _bounded_shared_body(item: dict[str, Any]) -> dict[str, Any]:
    """Keep bounded scalars; complex unknown bodies become content references."""

    return {
        key: (
            _complex_reference(value)
            if isinstance(value, (dict, list)) else value
        )
        for key, value in item.items()
        if key not in {"event_id", "event_ids"}
    }


def _descendant_owner_ids(value: object) -> frozenset[str]:
    owners: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"event_id", "event_ids"}:
                continue
            owners.update(_item_event_ids(child))
            owners.update(_descendant_owner_ids(child))
    elif isinstance(value, list):
        for child in value:
            owners.update(_item_event_ids(child))
            owners.update(_descendant_owner_ids(child))
    return frozenset(owners)


def _event_local_value(value: object, owner_event_id: str) -> object:
    """Preserve local semantics while content-addressing foreign subtrees."""

    if isinstance(value, dict):
        explicit_owners = tuple(dict.fromkeys(_item_event_ids(value)))
        if explicit_owners and owner_event_id not in explicit_owners:
            return {**_complex_reference(value), "foreign_owner_withheld": True}
        return {
            key: _event_local_value(child, owner_event_id)
            for key, child in value.items()
            if key not in {"event_id", "event_ids"}
        }
    if isinstance(value, list):
        return [_event_local_value(child, owner_event_id) for child in value]
    return value


def _event_local_body(
    value: dict[str, Any], owner_event_id: str, *, shared_node: bool,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for key, child in value.items():
        if key in {"event_id", "event_ids"}:
            continue
        if shared_node and isinstance(child, (dict, list)) and not _item_event_ids(child):
            body[key] = _complex_reference(child)
        else:
            body[key] = _event_local_value(child, owner_event_id)
    return body


def _compile_nested_owned_entries(
    value: object, *, parent_offset: int, path: tuple[str, ...],
    event_index: dict[str, dict[int, list[dict[str, Any]]]],
) -> None:
    """Index provably event-owned descendants without broadcasting containers."""

    if isinstance(value, dict):
        event_ids = tuple(dict.fromkeys(_item_event_ids(value)))
        if event_ids:
            source_sha256 = canonical_sha256(value)
            scope_sha256 = canonical_sha256(list(event_ids))
            descendant_owners = _descendant_owner_ids(value)
            for event_id in event_ids:
                complete_single_owner = (
                    len(event_ids) == 1
                    and descendant_owners <= {event_id}
                )
                body = (
                    {
                        key: child for key, child in value.items()
                        if key not in {"event_id", "event_ids"}
                    }
                    if complete_single_owner else _event_local_body(
                        value, event_id, shared_node=len(event_ids) > 1,
                    )
                )
                event_index.setdefault(event_id, {}).setdefault(
                    parent_offset, [],
                ).append({
                    "field_path": list(path),
                    "entry": body,
                    "shared_scope": {
                        "source_sha256": source_sha256,
                        "event_ids_sha256": scope_sha256,
                        "event_count": len(event_ids),
                        "owned_event_ids": [event_id],
                    },
                })
            if len(event_ids) == 1 and descendant_owners <= set(event_ids):
                return
        for key, child in value.items():
            if key in {"event_id", "event_ids"}:
                continue
            if isinstance(child, (dict, list)):
                _compile_nested_owned_entries(
                    child, parent_offset=parent_offset,
                    path=(*path, str(key)), event_index=event_index,
                )
        return
    if isinstance(value, list):
        for child in value:
            if isinstance(child, (dict, list)):
                _compile_nested_owned_entries(
                    child, parent_offset=parent_offset,
                    path=path, event_index=event_index,
                )


def compile_content_addressed_collection(
    value: object,
) -> ContentAddressedCollectionIR:
    """Compile one collection once; later segment projection is index-only."""

    items = value if isinstance(value, list) else (
        [value] if value not in (None, "", {}, []) else []
    )
    index: dict[str, list[int]] = {}
    item_event_ids: list[tuple[str, ...]] = []
    item_sha256: list[str] = []
    item_event_ids_sha256: list[str] = []
    shared_body: list[dict[str, Any] | None] = []
    nested_index: dict[str, dict[int, list[dict[str, Any]]]] = {}
    for offset, item in enumerate(items):
        event_ids = tuple(dict.fromkeys(_item_event_ids(item)))
        item_event_ids.append(event_ids)
        item_sha256.append(canonical_sha256(item))
        item_event_ids_sha256.append(canonical_sha256(list(event_ids)))
        shared_body.append(
            _bounded_shared_body(item)
            if isinstance(item, dict) and len(event_ids) > 1 else None
        )
        for event_id in event_ids:
            index.setdefault(event_id, []).append(offset)
        if isinstance(item, dict) and len(event_ids) > 1:
            for key, child in item.items():
                if key in {"event_id", "event_ids"}:
                    continue
                if isinstance(child, (dict, list)):
                    _compile_nested_owned_entries(
                        child, parent_offset=offset, path=(str(key),),
                        event_index=nested_index,
                    )
    return ContentAddressedCollectionIR(
        items=tuple(items),
        source_sha256=canonical_sha256(items),
        event_index={key: tuple(offsets) for key, offsets in index.items()},
        unscoped_entries=sum(1 for event_ids in item_event_ids if not event_ids),
        item_event_ids=tuple(item_event_ids),
        item_event_id_sets=tuple(frozenset(value) for value in item_event_ids),
        item_sha256=tuple(item_sha256),
        item_event_ids_sha256=tuple(item_event_ids_sha256),
        bounded_shared_body=tuple(shared_body),
        nested_event_index={
            event_id: {
                offset: tuple(entries) for offset, entries in by_offset.items()
            }
            for event_id, by_offset in nested_index.items()
        },
    )


def project_content_addressed_collection(
    authority_ir: ContentAddressedCollectionIR,
    owned_event_ids: Iterable[str],
) -> dict[str, Any]:
    """Project event-local bodies without rebroadcasting shared owner lists."""

    owned_sequence = tuple(dict.fromkeys(
        str(value).strip().upper() for value in owned_event_ids
        if str(value).strip()
    ))
    owned = set(owned_sequence)
    offsets = sorted({
        offset
        for event_id in owned
        for offset in authority_ir.event_index.get(event_id, ())
    })
    local: list[object] = []
    for offset in offsets:
        item = authority_ir.items[offset]
        event_ids = authority_ir.item_event_ids[offset]
        if len(event_ids) <= 1:
            local.append(item)
            continue
        event_id_set = authority_ir.item_event_id_sets[offset]
        local_owned_event_ids = [
            event_id for event_id in owned_sequence if event_id in event_id_set
        ]
        nested_entries = [
            nested
            for event_id in local_owned_event_ids
            for nested in authority_ir.nested_event_index.get(
                event_id, {},
            ).get(offset, ())
        ]
        local.append({
            "entry": authority_ir.bounded_shared_body[offset],
            "shared_scope": {
                "source_sha256": authority_ir.item_sha256[offset],
                "event_ids_sha256": authority_ir.item_event_ids_sha256[offset],
                "event_count": len(event_ids),
                "owned_event_ids": local_owned_event_ids,
            },
            **({"nested_local_entries": nested_entries} if nested_entries else {}),
        })
    return {
        "source_sha256": authority_ir.source_sha256,
        "source_count": len(authority_ir.items),
        "local_entries": local,
        "unscoped_entries_withheld": authority_ir.unscoped_entries,
    }


def compile_execution_fragment_authority(
    *, causal_chain: dict[str, Any], timeline_events: object,
    presentation_order: list[str], viewpoint_rule: str,
) -> ExecutionFragmentAuthorityIR:
    """Build the content-addressed, event-indexed authority once per manifest."""

    normalized_order = tuple(str(value).strip().upper() for value in presentation_order)
    return ExecutionFragmentAuthorityIR(
        causal_chain=causal_chain,
        causal_chain_sha256=canonical_sha256(causal_chain),
        question_chain=compile_content_addressed_collection(
            causal_chain.get("question_chain"),
        ),
        relationship_arc=compile_content_addressed_collection(
            causal_chain.get("relationship_arc"),
        ),
        timeline_events=compile_content_addressed_collection(timeline_events),
        presentation_order=normalized_order,
        presentation_order_sha256=canonical_sha256(normalized_order),
        order_index={
            event_id: index for index, event_id in enumerate(normalized_order, 1)
        },
        viewpoint_rule=viewpoint_rule,
    )


def project_execution_fragment_authority(
    *, authority_ir: ExecutionFragmentAuthorityIR,
    owned_event_ids: list[str], segment: int, segment_count: int,
) -> dict[str, Any]:
    """Create the sole bounded whole-story projection for one fragment.

    Untyped global arrays are content-addressed, never broadcast.  Entries may
    appear verbatim only when they declare event ownership that intersects the
    current fragment.
    """

    causal_chain = authority_ir.causal_chain
    owned_positions = [
        authority_ir.order_index[event_id] for event_id in owned_event_ids
        if event_id in authority_ir.order_index
    ]
    order_guard = {
        "source_sha256": authority_ir.presentation_order_sha256,
        "total_events": len(authority_ir.presentation_order),
        "owned_event_ids": list(owned_event_ids),
        "owned_order_start": min(owned_positions) if owned_positions else 0,
        "owned_order_end": max(owned_positions) if owned_positions else 0,
    }
    return {
        "version": EXECUTION_FRAGMENT_AUTHORITY_VERSION,
        "segment": segment,
        "segment_count": segment_count,
        "causal_chain_sha256": authority_ir.causal_chain_sha256,
        "core_goal": causal_chain.get("core_goal"),
        "reversal": causal_chain.get("reversal") if (
            segment in {1, segment_count}
        ) else {"source_sha256": canonical_sha256(causal_chain.get("reversal"))},
        **({"opening": causal_chain.get("opening")} if segment == 1 else {}),
        **({"ending": causal_chain.get("ending")} if segment == segment_count else {}),
        "question_chain": project_content_addressed_collection(
            authority_ir.question_chain, owned_event_ids,
        ),
        "relationship_arc": project_content_addressed_collection(
            authority_ir.relationship_arc, owned_event_ids,
        ),
        "presentation_order": order_guard,
        "timeline_events": project_content_addressed_collection(
            authority_ir.timeline_events, owned_event_ids,
        ),
        "viewpoint_rule": authority_ir.viewpoint_rule,
        "nonlinear_rule": (
            "Presentation order is executable order; story_time/timeline may "
            "describe chronology but must never reorder flashbacks or parallel timelines."
        ),
    }
