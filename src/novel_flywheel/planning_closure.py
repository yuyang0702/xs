from __future__ import annotations

import hashlib
import heapq
import json
import re
from typing import Any, Mapping, Sequence


SHA256 = re.compile(r"^[0-9a-f]{64}$")
FORMAL_EVENT_ID = re.compile(r"^EV-[0-9A-F]{8}$")
SKILL_SOURCE_ID = re.compile(r"^SKILL-[0-9a-f]{16}$")
NODE_KINDS = frozenset({"formal_event", "skill_source"})
EDGE_KINDS = frozenset({"prerequisite", "context"})
MAX_NODE_COUNT = 512
MAX_EDGE_COUNT = 8192
MAX_ROOT_COUNT = 512
MAX_SERIALIZED_BYTES = 1_048_576
MAX_SKILL_SOURCE_COUNT = 64


class PlanningGlobalClosureError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _bounded_sequence(
    value: object, *, limit: int, invalid_code: str, limit_code: str,
) -> Sequence[Any]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise PlanningGlobalClosureError(invalid_code)
    if len(value) > limit:
        raise PlanningGlobalClosureError(limit_code)
    return value


def _valid_node_id(node_id: str, kind: str) -> bool:
    return bool(
        FORMAL_EVENT_ID.fullmatch(node_id)
        if kind == "formal_event"
        else SKILL_SOURCE_ID.fullmatch(node_id)
        if kind == "skill_source"
        else False
    )


def compute_planning_global_closure(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    roots: Sequence[str],
) -> dict[str, Any]:
    """Compute one deterministic, fail-closed transitive dependency closure."""

    node_values = _bounded_sequence(
        nodes, limit=MAX_NODE_COUNT,
        invalid_code="PLANNING_CLOSURE_NODES_INVALID",
        limit_code="PLANNING_CLOSURE_NODE_LIMIT_EXCEEDED",
    )
    edge_values = _bounded_sequence(
        edges, limit=MAX_EDGE_COUNT,
        invalid_code="PLANNING_CLOSURE_EDGES_INVALID",
        limit_code="PLANNING_CLOSURE_EDGE_LIMIT_EXCEEDED",
    )
    root_inputs = _bounded_sequence(
        roots, limit=MAX_ROOT_COUNT,
        invalid_code="PLANNING_CLOSURE_ROOTS_INVALID",
        limit_code="PLANNING_CLOSURE_ROOT_LIMIT_EXCEEDED",
    )
    canonical_nodes = []
    by_id: dict[str, dict[str, Any]] = {}
    formal_orders: set[int] = set()
    for raw in node_values:
        if not isinstance(raw, Mapping) or set(raw) != {
            "node_id", "kind", "order", "authority_sha256",
        }:
            raise PlanningGlobalClosureError("PLANNING_CLOSURE_NODE_SHAPE_INVALID")
        node = dict(raw)
        if (
            not isinstance(node["node_id"], str)
            or not isinstance(node["kind"], str)
            or node["kind"] not in NODE_KINDS
            or not _valid_node_id(node["node_id"], node["kind"])
            or isinstance(node["order"], bool)
            or not isinstance(node["order"], int)
            or node["order"] < 0
            or (
                node["kind"] == "formal_event" and node["order"] < 1
            )
            or (node["kind"] == "skill_source" and node["order"] != 0)
            or not isinstance(node["authority_sha256"], str)
            or SHA256.fullmatch(node["authority_sha256"]) is None
        ):
            raise PlanningGlobalClosureError("PLANNING_CLOSURE_NODE_INVALID")
        if node["node_id"] in by_id:
            raise PlanningGlobalClosureError("PLANNING_CLOSURE_DUPLICATE_NODE")
        if node["kind"] == "formal_event":
            if node["order"] in formal_orders:
                raise PlanningGlobalClosureError(
                    "PLANNING_CLOSURE_DUPLICATE_FORMAL_ORDER"
                )
            formal_orders.add(node["order"])
        by_id[node["node_id"]] = node
        canonical_nodes.append(node)
    if not by_id:
        raise PlanningGlobalClosureError("PLANNING_CLOSURE_EMPTY")

    canonical_edges = []
    edge_identities: set[tuple[str, str, str]] = set()
    incoming: dict[str, list[str]] = {node_id: [] for node_id in by_id}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in by_id}
    for raw in edge_values:
        if not isinstance(raw, Mapping) or set(raw) != {
            "source", "target", "kind",
        }:
            raise PlanningGlobalClosureError("PLANNING_CLOSURE_EDGE_SHAPE_INVALID")
        source = raw.get("source")
        target = raw.get("target")
        kind = raw.get("kind")
        if not all(isinstance(item, str) for item in (source, target, kind)):
            raise PlanningGlobalClosureError("PLANNING_CLOSURE_EDGE_INVALID")
        identity = (source, target, kind)
        if identity in edge_identities:
            raise PlanningGlobalClosureError("PLANNING_CLOSURE_DUPLICATE_EDGE")
        edge_identities.add(identity)
        if source not in by_id or target not in by_id:
            raise PlanningGlobalClosureError("PLANNING_CLOSURE_MISSING_TARGET")
        if source == target:
            raise PlanningGlobalClosureError("PLANNING_CLOSURE_CYCLE")
        if kind not in EDGE_KINDS:
            raise PlanningGlobalClosureError("PLANNING_CLOSURE_EDGE_INVALID")
        source_kind = by_id[source]["kind"]
        target_kind = by_id[target]["kind"]
        if (
            (kind == "prerequisite" and (
                source_kind != "formal_event" or target_kind != "formal_event"
            ))
            or (kind == "context" and (
                source_kind != "skill_source" or target_kind != "formal_event"
            ))
        ):
            raise PlanningGlobalClosureError(
                "PLANNING_CLOSURE_UNSUPPORTED_CROSS_KIND_EDGE"
            )
        canonical_edges.append({
            "source": source, "target": target, "kind": kind,
        })
        incoming[target].append(source)
        outgoing[source].append(target)

    root_values = tuple(root_inputs)
    if any(not isinstance(root, str) for root in root_values):
        raise PlanningGlobalClosureError("PLANNING_CLOSURE_ROOTS_INVALID")
    if not root_values or len(set(root_values)) != len(root_values):
        raise PlanningGlobalClosureError("PLANNING_CLOSURE_ROOTS_INVALID")
    if any(root not in by_id for root in root_values):
        raise PlanningGlobalClosureError("PLANNING_CLOSURE_MISSING_ROOT")
    canonical_nodes.sort(key=lambda item: (
        item["order"], item["kind"], item["node_id"],
    ))
    canonical_edges.sort(key=lambda item: (
        item["target"], item["source"], item["kind"],
    ))
    input_receipt = {
        "schema": "PlanningGlobalClosureInputV1",
        "version": 1,
        "nodes": canonical_nodes,
        "edges": canonical_edges,
        "roots": sorted(root_values),
    }
    try:
        input_bytes = json.dumps(
            input_receipt, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PlanningGlobalClosureError(
            "PLANNING_CLOSURE_SERIALIZATION_INVALID"
        ) from exc
    if len(input_bytes) > MAX_SERIALIZED_BYTES:
        raise PlanningGlobalClosureError(
            "PLANNING_CLOSURE_SERIALIZED_BYTES_EXCEEDED"
        )

    # Validate the whole declared graph before selecting the root dependency
    # closure. A disconnected cycle is still malformed declared authority.
    global_indegree = {
        node_id: len(incoming[node_id]) for node_id in by_id
    }
    global_ready = [
        (by_id[node_id]["order"], by_id[node_id]["kind"], node_id)
        for node_id, degree in global_indegree.items() if degree == 0
    ]
    heapq.heapify(global_ready)
    globally_ordered: list[str] = []
    while global_ready:
        _order, _kind, node_id = heapq.heappop(global_ready)
        globally_ordered.append(node_id)
        for target in sorted(outgoing[node_id]):
            global_indegree[target] -= 1
            if global_indegree[target] == 0:
                node = by_id[target]
                heapq.heappush(
                    global_ready, (node["order"], node["kind"], target),
                )
    if len(globally_ordered) != len(by_id):
        raise PlanningGlobalClosureError("PLANNING_CLOSURE_CYCLE")

    closure: set[str] = set()
    stack = list(root_values)
    while stack:
        node_id = stack.pop()
        if node_id in closure:
            continue
        closure.add(node_id)
        stack.extend(incoming[node_id])

    ordered = [node_id for node_id in globally_ordered if node_id in closure]
    result = {
        "schema": "PlanningGlobalClosureReceiptV1",
        "version": 1,
        "status": "closed",
        "input_sha256": _sha(input_receipt),
        "roots": sorted(root_values),
        "ordered_member_ids": ordered,
        "edge_policy": {
            "prerequisite_cycles": "fail_closed",
            "context_cycles": "fail_closed",
            "missing_targets": "fail_closed",
            "duplicates": "fail_closed",
            "disconnected_components": "validated_not_selected",
            "resource_bounds": "fail_closed_without_truncation",
            "ranking": "none",
        },
        "limits": {
            "max_node_count": MAX_NODE_COUNT,
            "max_edge_count": MAX_EDGE_COUNT,
            "max_root_count": MAX_ROOT_COUNT,
            "max_serialized_bytes": MAX_SERIALIZED_BYTES,
        },
    }
    result["closure_sha256"] = _sha(result)
    return result


def build_runtime_planning_global_closure(
    formal_events: Sequence[Mapping[str, Any]],
    *,
    skill_source_sha256s: Sequence[str] = (),
) -> dict[str, Any]:
    """Build the supported production graph from Runtime-owned identities."""

    formal_event_values = _bounded_sequence(
        formal_events, limit=MAX_NODE_COUNT,
        invalid_code="PLANNING_CLOSURE_FORMAL_EVENTS_INVALID",
        limit_code="PLANNING_CLOSURE_NODE_LIMIT_EXCEEDED",
    )
    skill_values = _bounded_sequence(
        skill_source_sha256s, limit=MAX_SKILL_SOURCE_COUNT,
        invalid_code="PLANNING_CLOSURE_SKILL_SOURCES_INVALID",
        limit_code="PLANNING_CLOSURE_SKILL_SOURCE_LIMIT_EXCEEDED",
    )
    if len(formal_event_values) + len(skill_values) > MAX_NODE_COUNT:
        raise PlanningGlobalClosureError("PLANNING_CLOSURE_NODE_LIMIT_EXCEEDED")
    estimated_edges = max(0, len(formal_event_values) - 1) + (
        len(formal_event_values) * len(skill_values)
    )
    if estimated_edges > MAX_EDGE_COUNT:
        raise PlanningGlobalClosureError("PLANNING_CLOSURE_EDGE_LIMIT_EXCEEDED")
    if len(formal_event_values) > MAX_ROOT_COUNT:
        raise PlanningGlobalClosureError("PLANNING_CLOSURE_ROOT_LIMIT_EXCEEDED")

    nodes = []
    event_ids = []
    for order, event in enumerate(formal_event_values, 1):
        if not isinstance(event, Mapping):
            raise PlanningGlobalClosureError(
                "PLANNING_CLOSURE_FORMAL_EVENT_INVALID"
            )
        explicit_id = event.get("id")
        alias_id = event.get("event_id")
        if (
            explicit_id is not None
            and alias_id is not None
            and explicit_id != alias_id
        ):
            raise PlanningGlobalClosureError(
                "PLANNING_CLOSURE_FORMAL_EVENT_ID_CONFLICT"
            )
        event_id = explicit_id if explicit_id is not None else alias_id
        if (
            not isinstance(event_id, str)
            or FORMAL_EVENT_ID.fullmatch(event_id) is None
        ):
            raise PlanningGlobalClosureError(
                "PLANNING_CLOSURE_FORMAL_EVENT_INVALID"
            )
        event_ids.append(event_id)
        nodes.append({
            "node_id": event_id,
            "kind": "formal_event",
            "order": order,
            "authority_sha256": _sha(dict(event)),
        })
    skill_ids = []
    for sha256 in skill_values:
        if not isinstance(sha256, str) or SHA256.fullmatch(sha256) is None:
            raise PlanningGlobalClosureError(
                "PLANNING_CLOSURE_SKILL_SOURCE_INVALID"
            )
        node_id = "SKILL-" + sha256[:16]
        skill_ids.append(node_id)
        nodes.append({
            "node_id": node_id,
            "kind": "skill_source",
            "order": 0,
            "authority_sha256": sha256,
        })
    edges = [
        {"source": previous, "target": current, "kind": "prerequisite"}
        for previous, current in zip(event_ids, event_ids[1:])
    ]
    edges.extend(
        {"source": skill_id, "target": event_id, "kind": "context"}
        for skill_id in skill_ids for event_id in event_ids
    )
    return compute_planning_global_closure(nodes, edges, event_ids)
