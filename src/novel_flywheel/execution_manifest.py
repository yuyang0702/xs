from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
import unicodedata
from typing import Any

from novel_flywheel.narrative_ir import StoryClaim


_SHA256 = re.compile(r"[0-9a-f]{64}")
_EVENT_ID = re.compile(r"EV-[0-9A-F]{8}")
_BEAT_ID = re.compile(r"(EV-[0-9A-F]{8})/([0-9]{2})")


@dataclass(frozen=True)
class AtomicBeat:
    beat_id: str
    source_event_id: str
    order: int
    action: str
    preconditions: tuple[str, ...]
    postconditions: tuple[str, ...]
    owner_segment: int
    source_evidence: str = ""
    source_evidence_ids: tuple[str, ...] = ()
    presentation_order: int = 0
    story_time: str = ""
    timeline: str = ""
    actor: str = ""
    location: str = ""
    viewpoint: str = ""
    knowledge_delta: tuple[str, ...] = ()
    relationship_delta: tuple[str, ...] = ()


@dataclass(frozen=True)
class StateAssertion:
    state: str
    produced_by: tuple[str, ...] = ()
    inherited_from: str = ""
    claim: StoryClaim | None = None


@dataclass(frozen=True)
class FutureBeatGuard:
    """Compact proof of the beats that are outside one segment's scope.

    The guard deliberately contains no beat-ID collection.  Its digest binds
    the segment number, the canonical global beat sequence, and the derived
    floor/count, so downstream contracts can retain the prohibition without
    expanding every future beat for every segment.
    """

    order_floor: int
    count: int
    scope_sha256: str

    def __post_init__(self) -> None:
        if self.order_floor < 0 or self.count < 0:
            raise ValueError("future beat guard values must not be negative")
        if (self.order_floor == 0) != (self.count == 0):
            raise ValueError(
                "future beat guard floor and count must be empty together"
            )
        if not _SHA256.fullmatch(self.scope_sha256):
            raise ValueError(
                "future beat guard scope_sha256 must be a lowercase SHA-256 digest"
            )


EMPTY_FUTURE_BEAT_GUARD = FutureBeatGuard(
    order_floor=0,
    count=0,
    scope_sha256=hashlib.sha256(b"future-beat-scope:none").hexdigest(),
)


@dataclass(frozen=True)
class SegmentBeatContract:
    segment: int
    beat_ids: tuple[str, ...]
    entry_state: tuple[StateAssertion, ...]
    exit_state: tuple[StateAssertion, ...]
    previous_exit_sha256: str
    future_beat_guard: FutureBeatGuard = EMPTY_FUTURE_BEAT_GUARD


@dataclass(frozen=True)
class ShortExecutionManifest:
    version: int
    status: str
    authority_sha256: str
    outline_sha256: str
    planning_sha256: str
    causal_chain_sha256: str
    beats: tuple[AtomicBeat, ...]
    segments: tuple[SegmentBeatContract, ...]
    semantic_receipt: dict[str, Any]
    repair_attempts: int = 0


def _text(value: object, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} must not be empty")
    return result


def _sha256(value: object, field: str, *, allow_empty: bool = False) -> str:
    result = str(value or "").strip()
    if allow_empty and not result:
        return ""
    if not _SHA256.fullmatch(result):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return result


def _positive_int(value: object, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    minimum = 0 if allow_zero else 1
    if result < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return result


def _string_tuple(value: object, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    result = tuple(str(item or "").strip() for item in value)
    if any(not item for item in result):
        raise ValueError(f"{field} contains an empty value")
    if not allow_empty and not result:
        raise ValueError(f"{field} must not be empty")
    return result


def _beat_id(value: object, field: str) -> str:
    result = str(value or "").strip().upper()
    if not _BEAT_ID.fullmatch(result):
        raise ValueError(f"{field} must use EV-XXXXXXXX/NN")
    return result


def _event_id(value: object, field: str) -> str:
    result = str(value or "").strip().upper()
    if not _EVENT_ID.fullmatch(result):
        raise ValueError(f"{field} must use EV-XXXXXXXX")
    return result


def _producer_ids(value: object, field: str) -> tuple[str, ...]:
    """Normalize one or more beat producers without dropping composite causality."""
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value).strip()
        if not normalized:
            return ()
        values: list[object] = re.split(r"[,;、]+", normalized)
    elif isinstance(value, (list, tuple)):
        values = list(value)
        if not values:
            return ()
    else:
        raise ValueError(f"{field} must be a beat ID or a list of beat IDs")

    result: list[str] = []
    for index, item in enumerate(values):
        normalized = unicodedata.normalize("NFKC", str(item or "")).strip().upper()
        if not normalized:
            raise ValueError(f"{field}[{index}] must not be empty")
        beat_id = _beat_id(normalized, f"{field}[{index}]")
        if beat_id not in result:
            result.append(beat_id)
    return tuple(result)


def _state_assertions(
    value: object, field: str, *, version: int = 4,
) -> tuple[StateAssertion, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    assertions = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{field}[{index}] must be an object")
        assertions.append(StateAssertion(
            state=_text(item.get("state"), f"{field}[{index}].state"),
            produced_by=_producer_ids(
                item.get("produced_by"), f"{field}[{index}].produced_by",
            ),
            inherited_from=str(item.get("inherited_from") or "").strip(),
            claim=(
                StoryClaim.model_validate(item["claim"])
                if version >= 5 and isinstance(item.get("claim"), dict)
                else None
            ),
        ))
    return tuple(assertions)


def _future_beat_sequence_sha256(beats: tuple[AtomicBeat, ...]) -> str:
    """Hash the ordered ownership index once for all compact guards."""

    return hashlib.sha256(json.dumps(
        [
            {
                "beat_id": beat.beat_id,
                "order": beat.order,
                "owner_segment": beat.owner_segment,
            }
            for beat in sorted(beats, key=lambda item: item.order)
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def future_beat_guards(
    beats: tuple[AtomicBeat, ...], segment_numbers: tuple[int, ...],
) -> dict[int, FutureBeatGuard]:
    """Derive every segment guard in one reverse ownership pass."""

    if len(segment_numbers) != len(set(segment_numbers)):
        raise ValueError("future beat guards require unique segment numbers")
    counts_by_owner: dict[int, int] = {}
    floor_by_owner: dict[int, int] = {}
    for beat in beats:
        counts_by_owner[beat.owner_segment] = (
            counts_by_owner.get(beat.owner_segment, 0) + 1
        )
        floor_by_owner[beat.owner_segment] = min(
            floor_by_owner.get(beat.owner_segment, beat.order), beat.order,
        )

    sequence_sha256 = _future_beat_sequence_sha256(beats)
    owners = sorted(counts_by_owner, reverse=True)
    owner_index = 0
    future_count = 0
    future_floor = 0
    result: dict[int, FutureBeatGuard] = {}
    for segment in sorted(segment_numbers, reverse=True):
        while owner_index < len(owners) and owners[owner_index] > segment:
            owner = owners[owner_index]
            future_count += counts_by_owner[owner]
            owner_floor = floor_by_owner[owner]
            future_floor = (
                min(future_floor, owner_floor) if future_floor else owner_floor
            )
            owner_index += 1
        scope_sha256 = hashlib.sha256(json.dumps(
            {
                "beat_sequence_sha256": sequence_sha256,
                "segment": segment,
                "order_floor": future_floor,
                "count": future_count,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        result[segment] = FutureBeatGuard(
            order_floor=future_floor,
            count=future_count,
            scope_sha256=scope_sha256,
        )
    return result


def bind_fragment_future_beat_guard(value: dict[str, Any]) -> dict[str, Any]:
    """Inject the compact guard derived from a model fragment's local ownership."""

    raw_beats = value.get("beats")
    raw_segments = value.get("segments")
    if (
        not isinstance(raw_beats, list)
        or not isinstance(raw_segments, list)
        or len(raw_segments) != 1
        or not isinstance(raw_segments[0], dict)
    ):
        return dict(value)
    index = []
    for raw_beat in raw_beats:
        if not isinstance(raw_beat, dict):
            return dict(value)
        try:
            index.append({
                "beat_id": str(raw_beat.get("beat_id") or "").strip().upper(),
                "order": int(raw_beat.get("order")),
                "owner_segment": int(raw_beat.get("owner_segment")),
            })
        except (TypeError, ValueError):
            return dict(value)
    try:
        segment = int(raw_segments[0].get("segment"))
    except (TypeError, ValueError):
        return dict(value)
    ordered = sorted(index, key=lambda item: item["order"])
    sequence_sha256 = hashlib.sha256(json.dumps(
        ordered, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    future = [item for item in ordered if item["owner_segment"] > segment]
    floor = min((item["order"] for item in future), default=0)
    scope_sha256 = hashlib.sha256(json.dumps({
        "beat_sequence_sha256": sequence_sha256,
        "segment": segment,
        "order_floor": floor,
        "count": len(future),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    raw_segment = dict(raw_segments[0])
    raw_segment.pop("prohibited_future_beat_ids", None)
    raw_segment.update({
        "future_beat_order_floor": floor,
        "future_beat_count": len(future),
        "future_beat_scope_sha256": scope_sha256,
    })
    return {**value, "segments": [raw_segment]}


def extend_future_beat_guard(
    parent: FutureBeatGuard, deferred_beats: tuple[AtomicBeat, ...],
) -> FutureBeatGuard:
    """Add a child's deferred owned suffix without retaining its beat IDs.

    A split task's first child must prohibit both the parent's future scope and
    the beats delegated to its second child.  The ordered deferred beats are
    hashed once at the split boundary; only the resulting compact guard crosses
    into the draft contract.
    """

    if not isinstance(parent, FutureBeatGuard):
        raise ValueError("parent must be a compact FutureBeatGuard")
    if not deferred_beats:
        return parent
    if len({beat.beat_id for beat in deferred_beats}) != len(deferred_beats):
        raise ValueError("deferred beats must not contain duplicate beat IDs")
    if len({beat.order for beat in deferred_beats}) != len(deferred_beats):
        raise ValueError("deferred beats must not contain duplicate orders")
    deferred_floor = min(beat.order for beat in deferred_beats)
    order_floor = (
        min(parent.order_floor, deferred_floor)
        if parent.count else deferred_floor
    )
    count = parent.count + len(deferred_beats)
    scope_sha256 = hashlib.sha256(json.dumps(
        {
            "parent_scope_sha256": parent.scope_sha256,
            "deferred_sequence_sha256": _future_beat_sequence_sha256(
                deferred_beats,
            ),
            "order_floor": order_floor,
            "count": count,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return FutureBeatGuard(
        order_floor=order_floor,
        count=count,
        scope_sha256=scope_sha256,
    )


def _legacy_future_beat_ids(
    beats: tuple[AtomicBeat, ...], segment: int,
) -> tuple[str, ...]:
    """Materialize only at a legacy v2-v4 serialization/migration boundary."""

    return tuple(
        beat.beat_id
        for beat in sorted(beats, key=lambda item: item.order)
        if beat.owner_segment > segment
    )


def parse_execution_manifest(value: object) -> ShortExecutionManifest:
    if not isinstance(value, dict):
        raise ValueError("execution manifest must be a JSON object")
    version = value.get("version")
    if version not in {2, 3, 4, 5, 6}:
        raise ValueError("execution manifest version must be 2, 3, 4, 5 or 6")
    raw_beats = value.get("beats")
    raw_segments = value.get("segments")
    if not isinstance(raw_beats, list) or not raw_beats:
        raise ValueError("execution manifest beats must be a non-empty list")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("execution manifest segments must be a non-empty list")

    beats = []
    seen_beat_ids: set[str] = set()
    for index, item in enumerate(raw_beats):
        if not isinstance(item, dict):
            raise ValueError(f"beats[{index}] must be an object")
        beat_id = _beat_id(item.get("beat_id"), f"beats[{index}].beat_id")
        if beat_id in seen_beat_ids:
            raise ValueError(f"duplicate beat_id: {beat_id}")
        seen_beat_ids.add(beat_id)
        source_event_id = _event_id(
            item.get("source_event_id"), f"beats[{index}].source_event_id",
        )
        if _BEAT_ID.fullmatch(beat_id).group(1) != source_event_id:
            raise ValueError(f"beat_id source does not match source_event_id: {beat_id}")
        order = _positive_int(item.get("order"), f"beats[{index}].order")
        source_evidence = str(item.get("source_evidence") or "").strip()
        source_evidence_ids = _string_tuple(
            item.get("source_evidence_ids", []),
            f"beats[{index}].source_evidence_ids",
            allow_empty=(version < 6),
        )
        if version >= 6:
            if source_evidence:
                raise ValueError(
                    f"beats[{index}] v6 evidence must use source_evidence_ids only"
                )
            if len(source_evidence_ids) != len(set(source_evidence_ids)):
                raise ValueError(
                    f"beats[{index}].source_evidence_ids must not contain duplicates"
                )
        elif not source_evidence:
            raise ValueError(f"beats[{index}].source_evidence must not be empty")
        beats.append(AtomicBeat(
            beat_id=beat_id,
            source_event_id=source_event_id,
            order=order,
            action=_text(item.get("action"), f"beats[{index}].action"),
            preconditions=_string_tuple(
                item.get("preconditions"), f"beats[{index}].preconditions",
            ),
            postconditions=_string_tuple(
                item.get("postconditions"), f"beats[{index}].postconditions",
                allow_empty=False,
            ),
            owner_segment=_positive_int(
                item.get("owner_segment"), f"beats[{index}].owner_segment",
            ),
            source_evidence=source_evidence,
            source_evidence_ids=source_evidence_ids,
            presentation_order=_positive_int(
                item.get("presentation_order", order),
                f"beats[{index}].presentation_order",
            ),
            story_time=str(item.get("story_time") or "").strip(),
            timeline=str(item.get("timeline") or "").strip(),
            actor=str(item.get("actor") or "").strip(),
            location=str(item.get("location") or "").strip(),
            viewpoint=str(item.get("viewpoint") or "").strip(),
            knowledge_delta=_string_tuple(
                item.get("knowledge_delta", []),
                f"beats[{index}].knowledge_delta",
            ),
            relationship_delta=_string_tuple(
                item.get("relationship_delta", []),
                f"beats[{index}].relationship_delta",
            ),
        ))

    beats_tuple = tuple(beats)
    raw_segment_numbers: list[int] = []
    for index, item in enumerate(raw_segments):
        if not isinstance(item, dict):
            raise ValueError(f"segments[{index}] must be an object")
        raw_segment_numbers.append(_positive_int(
            item.get("segment"), f"segments[{index}].segment",
        ))
    expected_guards = future_beat_guards(
        beats_tuple, tuple(raw_segment_numbers),
    )

    segments = []
    seen_segments: set[int] = set()
    for index, item in enumerate(raw_segments):
        if not isinstance(item, dict):
            raise ValueError(f"segments[{index}] must be an object")
        segment = _positive_int(item.get("segment"), f"segments[{index}].segment")
        if segment in seen_segments:
            raise ValueError(f"duplicate segment: {segment}")
        seen_segments.add(segment)
        expected_guard = expected_guards[segment]
        if version >= 5:
            floor = _positive_int(
                item.get("future_beat_order_floor"),
                f"segments[{index}].future_beat_order_floor",
                allow_zero=True,
            )
            if floor != expected_guard.order_floor:
                raise ValueError(
                    f"segments[{index}].future_beat_order_floor is stale"
                )
            if _positive_int(
                item.get("future_beat_count"),
                f"segments[{index}].future_beat_count",
                allow_zero=True,
            ) != expected_guard.count:
                raise ValueError(
                    f"segments[{index}].future_beat_count is stale"
                )
            if _sha256(
                item.get("future_beat_scope_sha256"),
                f"segments[{index}].future_beat_scope_sha256",
            ) != expected_guard.scope_sha256:
                raise ValueError(
                    f"segments[{index}].future_beat_scope_sha256 is stale"
                )
        else:
            legacy_future_ids = tuple(
                _beat_id(beat_id, f"segments[{index}].prohibited_future_beat_ids")
                for beat_id in _string_tuple(
                    item.get("prohibited_future_beat_ids"),
                    f"segments[{index}].prohibited_future_beat_ids",
                )
            )
            if legacy_future_ids != _legacy_future_beat_ids(beats_tuple, segment):
                raise ValueError(
                    f"segments[{index}].prohibited_future_beat_ids is stale"
                )
        segments.append(SegmentBeatContract(
            segment=segment,
            beat_ids=tuple(
                _beat_id(beat_id, f"segments[{index}].beat_ids")
                for beat_id in _string_tuple(
                    item.get("beat_ids"), f"segments[{index}].beat_ids",
                    allow_empty=False,
                )
            ),
            entry_state=_state_assertions(
                item.get("entry_state"), f"segments[{index}].entry_state",
                version=version,
            ),
            exit_state=_state_assertions(
                item.get("exit_state"), f"segments[{index}].exit_state",
                version=version,
            ),
            previous_exit_sha256=_sha256(
                item.get("previous_exit_sha256"),
                f"segments[{index}].previous_exit_sha256", allow_empty=True,
            ),
            future_beat_guard=expected_guard,
        ))

    semantic_receipt = value.get("semantic_receipt")
    if not isinstance(semantic_receipt, dict):
        raise ValueError("semantic_receipt must be an object")
    return ShortExecutionManifest(
        version=version,
        status=_text(value.get("status"), "status"),
        authority_sha256=_sha256(value.get("authority_sha256"), "authority_sha256"),
        outline_sha256=_sha256(value.get("outline_sha256"), "outline_sha256"),
        planning_sha256=_sha256(value.get("planning_sha256"), "planning_sha256"),
        causal_chain_sha256=_sha256(
            value.get("causal_chain_sha256"), "causal_chain_sha256",
        ),
        beats=beats_tuple,
        segments=tuple(segments),
        semantic_receipt=dict(semantic_receipt),
        repair_attempts=_positive_int(
            value.get("repair_attempts", 0), "repair_attempts", allow_zero=True,
        ),
    )


def _state_assertion_payload(assertion: StateAssertion, *, version: int) -> dict[str, Any]:
    produced_by: object
    if version >= 4:
        produced_by = list(assertion.produced_by)
    else:
        produced_by = (
            assertion.produced_by[0] if len(assertion.produced_by) == 1
            else ", ".join(assertion.produced_by)
        )
    payload = {
        "state": assertion.state,
        "produced_by": produced_by,
        "inherited_from": assertion.inherited_from,
    }
    if version >= 5:
        payload["claim"] = (
            assertion.claim.model_dump(mode="json") if assertion.claim else None
        )
    return payload


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value


def execution_manifest_payload(manifest: ShortExecutionManifest) -> dict[str, Any]:
    """Serialize manifests in their version-specific canonical representation."""
    payload = asdict(manifest)
    for raw_segment, segment in zip(payload.get("segments", []), manifest.segments):
        raw_segment.pop("future_beat_guard", None)
        raw_segment["entry_state"] = [
            _state_assertion_payload(item, version=manifest.version)
            for item in segment.entry_state
        ]
        raw_segment["exit_state"] = [
            _state_assertion_payload(item, version=manifest.version)
            for item in segment.exit_state
        ]
        if manifest.version >= 5:
            raw_segment.update({
                "future_beat_order_floor": segment.future_beat_guard.order_floor,
                "future_beat_count": segment.future_beat_guard.count,
                "future_beat_scope_sha256": (
                    segment.future_beat_guard.scope_sha256
                ),
            })
        else:
            raw_segment["prohibited_future_beat_ids"] = list(
                _legacy_future_beat_ids(manifest.beats, segment.segment)
            )
    if manifest.version == 2:
        for beat in payload.get("beats", []):
            for field in (
                "presentation_order", "story_time", "timeline", "actor",
                "location", "viewpoint", "knowledge_delta", "relationship_delta",
            ):
                beat.pop(field, None)
    for beat in payload.get("beats", []):
        if manifest.version >= 6:
            beat.pop("source_evidence", None)
        else:
            beat.pop("source_evidence_ids", None)
    return _json_compatible(payload)


def execution_manifest_sha256(manifest: ShortExecutionManifest) -> str:
    payload = execution_manifest_payload(manifest)
    payload.pop("semantic_receipt", None)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def state_assertions_sha256(
    assertions: tuple[StateAssertion, ...], *, version: int = 3,
) -> str:
    encoded = json.dumps(
        [_state_assertion_payload(item, version=version) for item in assertions],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bind_previous_exit_hashes(value: dict[str, Any]) -> dict[str, Any]:
    """Bind adjacent segment state hashes deterministically instead of trusting model math."""
    result = dict(value)
    raw_segments = value.get("segments")
    if not isinstance(raw_segments, list):
        return result
    segments = [dict(item) if isinstance(item, dict) else item for item in raw_segments]
    ordered = sorted(
        (item for item in segments if isinstance(item, dict)),
        key=lambda item: int(item.get("segment") or 0),
    )
    version = int(value.get("version") or 3)
    previous_exit: tuple[StateAssertion, ...] | None = None
    for item in ordered:
        item["previous_exit_sha256"] = (
            state_assertions_sha256(previous_exit, version=version)
            if previous_exit else ""
        )
        previous_exit = _state_assertions(
            item.get("exit_state"), "segments.exit_state", version=version,
        )
    result["segments"] = segments
    return result


def _bound_evidence(authority_text: str, value: object, field: str) -> str:
    evidence = str(value or "").strip()
    if not evidence or evidence not in authority_text:
        raise ValueError(f"execution manifest {field} evidence is not bound to authority")
    return evidence


EXECUTION_MANIFEST_RECEIPT_PROTOCOL_CODES = frozenset({
    "receipt_schema",
    "receipt_authority_hash",
    "receipt_manifest_hash",
    "receipt_beat_schema",
    "receipt_beat_coverage",
    "receipt_beat_evidence_unbound",
    "receipt_beat_evidence_mismatch",
    "receipt_segment_schema",
    "receipt_segment_coverage",
    "receipt_segment_evidence_unbound",
    "receipt_summary",
})


def execution_manifest_receipt_issues_are_protocol_only(
    issues: list[dict],
) -> bool:
    """Return whether failures belong only to the review receipt protocol."""
    return bool(issues) and all(
        str(item.get("code") or "") in EXECUTION_MANIFEST_RECEIPT_PROTOCOL_CODES
        for item in issues
    )


def _evidence_match_key(value: object) -> str:
    """Normalize presentation-only variants for evidence selection."""
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        line = re.sub(r"^(?:#{1,6}\s+|>\s*)", "", line)
        line = re.sub(r"^(?:[-+]\s+|\d+[.)、]\s*)", "", line)
        line = line.replace("**", "").replace("__", "").replace("`", "")
        line = re.sub(
            r"^(?:段首承接|段末交接|入口|出口)\s*[:：]\s*", "", line,
        )
        line = re.sub(r"\s+", "", line)
        if line:
            lines.append(line)
    return "".join(lines)


def bind_execution_manifest_receipt_evidence(
    manifest: ShortExecutionManifest,
    authority_text: str,
    receipt: object,
    *,
    segment_evidence_candidates: dict[int, dict[str, str]] | None = None,
) -> object:
    """Bind receipt evidence to immutable Runtime-owned authority excerpts.

    Beat evidence is never model-authored: the Runtime copies the exact source
    evidence already validated on the manifest. Segment evidence may select a
    Runtime-provided candidate by ID. A legacy formatted excerpt is adapted
    only when its normalized value equals exactly one candidate; ambiguous,
    partial, or unrelated authority text never becomes boundary evidence.
    """
    if not isinstance(receipt, dict):
        return receipt
    result = dict(receipt)
    beat_by_id = {beat.beat_id: beat for beat in manifest.beats}
    raw_beat_receipts = receipt.get("beat_receipts")
    if isinstance(raw_beat_receipts, list):
        bound_beats: list[object] = []
        for raw_item in raw_beat_receipts:
            if not isinstance(raw_item, dict):
                bound_beats.append(raw_item)
                continue
            item = dict(raw_item)
            beat_id = str(item.get("beat_id") or "").strip().upper()
            beat = beat_by_id.get(beat_id)
            if beat is not None:
                item["beat_id"] = beat.beat_id
                if beat.source_evidence_ids:
                    item["evidence_ids"] = list(beat.source_evidence_ids)
                    item.pop("evidence", None)
                else:
                    item["evidence"] = beat.source_evidence
            bound_beats.append(item)
        result["beat_receipts"] = bound_beats

    raw_segment_receipts = receipt.get("segment_receipts")
    if isinstance(raw_segment_receipts, list):
        bound_segments: list[object] = []
        candidate_groups = segment_evidence_candidates or {}
        for raw_item in raw_segment_receipts:
            if not isinstance(raw_item, dict):
                bound_segments.append(raw_item)
                continue
            item = dict(raw_item)
            try:
                segment_number = int(item.get("segment"))
            except (TypeError, ValueError):
                bound_segments.append(item)
                continue
            candidates = candidate_groups.get(segment_number, {})
            evidence_id = str(item.get("evidence_id") or "").strip()
            selected = candidates.get(evidence_id, "")
            evidence = str(item.get("evidence") or "").strip()
            selected_id = evidence_id if selected else ""
            if not selected and not evidence_id and evidence and candidates:
                evidence_key = _evidence_match_key(evidence)
                matches = [
                    (candidate_id, candidate)
                    for candidate_id, candidate in candidates.items()
                    if evidence_key
                    and _evidence_match_key(candidate) == evidence_key
                ]
                if len(matches) == 1:
                    selected_id, selected = matches[0]
            if selected:
                item["evidence_id"] = selected_id
                item["evidence"] = selected
            elif candidates:
                item["evidence"] = ""
            bound_segments.append(item)
        result["segment_receipts"] = bound_segments
    return result


def validate_execution_manifest_receipt(
    manifest: ShortExecutionManifest,
    authority_text: str,
    receipt: object,
) -> dict:
    issues = execution_manifest_receipt_issues(manifest, authority_text, receipt)
    if issues:
        raise ValueError("; ".join(item["message"] for item in issues))
    assert isinstance(receipt, dict)
    beat_receipts = receipt.get("beat_receipts")
    assert isinstance(beat_receipts, list)
    normalized_beats = []
    for beat, item in zip(manifest.beats, beat_receipts):
        normalized = {
            "beat_id": beat.beat_id,
            "actor_action_valid": True,
        }
        if beat.source_evidence_ids:
            normalized["evidence_ids"] = list(beat.source_evidence_ids)
        else:
            normalized["evidence"] = str(item.get("evidence") or "").strip()
        normalized_beats.append(normalized)
    segment_receipts = receipt.get("segment_receipts")
    assert isinstance(segment_receipts, list)
    normalized_segments = []
    for segment, item in zip(manifest.segments, segment_receipts):
        normalized_segments.append({
            "segment": segment.segment,
            "boundary_valid": True,
            "evidence": str(item.get("evidence") or "").strip(),
        })
    summary = str(receipt.get("summary") or "").strip()
    return {
        **receipt,
        "authority_sha256": manifest.authority_sha256,
        "manifest_sha256": execution_manifest_sha256(manifest),
        "beat_receipts": normalized_beats,
        "segment_receipts": normalized_segments,
        "formal_plot_unchanged": True,
        "summary": summary[:800],
    }


def _issue(code: str, message: str, **metadata: object) -> dict:
    return {"code": code, **metadata, "message": message}


def beat_source_evidence_reference(beat: AtomicBeat) -> tuple[str, ...] | str:
    """Return the versioned, compact evidence authority used by receipts."""

    return beat.source_evidence_ids if beat.source_evidence_ids else beat.source_evidence


def _event_evidence_catalogs(
    expected_events: list[dict] | None,
) -> dict[str, tuple[tuple[str, str], ...]]:
    catalogs: dict[str, tuple[tuple[str, str], ...]] = {}
    for event in expected_events or []:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "").strip().upper()
        if not event_id:
            continue
        entries: list[tuple[str, str]] = []
        raw_entries = event.get("evidence_catalog")
        if isinstance(raw_entries, list):
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, dict):
                    continue
                evidence_id = str(raw_entry.get("evidence_id") or "").strip()
                evidence = str(raw_entry.get("text") or "").strip()
                if evidence_id and evidence:
                    entries.append((evidence_id, evidence))
        if not entries:
            evidence = str(event.get("evidence") or "").strip()
            if evidence:
                digest = hashlib.sha256(
                    (event_id + "\0" + evidence).encode("utf-8")
                ).hexdigest().upper()
                entries.append((f"EXEC-{digest[:24]}", evidence))
        catalogs[event_id] = tuple(entries)
    return catalogs


def execution_event_contract_prompt_payload(
    expected_events: list[dict],
) -> list[dict[str, Any]]:
    """Render evidence text once per atom and hash redundant whole-event copies."""

    result: list[dict[str, Any]] = []
    for raw_event in expected_events:
        event = dict(raw_event)
        evidence = str(event.pop("evidence", "") or "").strip()
        formal_evidence = str(event.pop("formal_evidence", "") or "").strip()
        if evidence:
            event["evidence_sha256"] = hashlib.sha256(
                evidence.encode("utf-8")
            ).hexdigest()
        if formal_evidence:
            event["formal_evidence_sha256"] = hashlib.sha256(
                formal_evidence.encode("utf-8")
            ).hexdigest()
        result.append(event)
    return result


def _beat_evidence_reference_issue(
    beat: AtomicBeat, contract: dict | None,
    catalog: tuple[tuple[str, str], ...],
) -> str:
    if beat.source_evidence_ids:
        candidate_ids = tuple(item[0] for item in catalog)
        selected = beat.source_evidence_ids
        starts = [
            index for index in range(len(candidate_ids))
            if candidate_ids[index:index + len(selected)] == selected
        ]
        if len(starts) != 1:
            return "source evidence references are unknown or non-contiguous"
        return ""
    evidence = str((contract or {}).get("evidence") or "").strip()
    if evidence and beat.source_evidence not in evidence:
        return "legacy source evidence is outside its formal event"
    return ""


def execution_manifest_receipt_issues(
    manifest: ShortExecutionManifest,
    authority_text: str,
    receipt: object,
) -> list[dict]:
    """Return every independent semantic-receipt failure in one pass."""
    if not isinstance(receipt, dict):
        return [_issue(
            "receipt_schema",
            "execution manifest semantic receipt must be an object",
        )]
    issues: list[dict] = []
    if receipt.get("authority_sha256") != manifest.authority_sha256:
        issues.append(_issue(
            "receipt_authority_hash",
            "execution manifest receipt authority hash is stale",
        ))
    if receipt.get("manifest_sha256") != execution_manifest_sha256(manifest):
        issues.append(_issue(
            "receipt_manifest_hash",
            "execution manifest receipt manifest hash is stale",
        ))

    beat_receipts = receipt.get("beat_receipts")
    expected_beat_ids = [beat.beat_id for beat in manifest.beats]
    if not isinstance(beat_receipts, list) or any(
        not isinstance(item, dict) for item in beat_receipts
    ):
        issues.append(_issue(
            "receipt_beat_schema", "execution manifest beat receipts are invalid",
        ))
        beat_receipts = []
    actual_beat_ids = [
        str(item.get("beat_id") or "").upper() for item in beat_receipts
    ]
    if actual_beat_ids != expected_beat_ids:
        issues.append(_issue(
            "receipt_beat_coverage",
            "execution manifest beat receipt coverage is incomplete",
            expected_beat_ids=expected_beat_ids,
            actual_beat_ids=actual_beat_ids,
        ))
    receipts_by_id = {
        str(item.get("beat_id") or "").upper(): item for item in beat_receipts
    }
    for beat in manifest.beats:
        item = receipts_by_id.get(beat.beat_id)
        if item is None:
            continue
        raw_invalid_fields = item.get("invalid_fields")
        invalid_fields = (
            [str(field).strip() for field in raw_invalid_fields if str(field).strip()]
            if isinstance(raw_invalid_fields, list) else []
        )
        field_verdicts = item.get("field_verdicts")
        if isinstance(field_verdicts, dict):
            invalid_fields.extend(
                str(field).strip() for field, valid in field_verdicts.items()
                if valid is not True and str(field).strip()
            )
        invalid_fields = list(dict.fromkeys(invalid_fields))
        if item.get("actor_action_valid") is not True or invalid_fields:
            metadata: dict[str, object] = {"beat_id": beat.beat_id}
            if invalid_fields:
                metadata["invalid_fields"] = invalid_fields
            reason = str(item.get("reason") or "").strip()
            if reason:
                metadata["reason"] = reason[:800]
            issues.append(_issue(
                "receipt_beat_actor_action",
                f"execution manifest beat actor/action is invalid: {beat.beat_id}",
                **metadata,
            ))
        if beat.source_evidence_ids:
            evidence_ids = item.get("evidence_ids")
            if evidence_ids != list(beat.source_evidence_ids):
                issues.append(_issue(
                    "receipt_beat_evidence_mismatch",
                    "execution manifest beat receipt does not bind its evidence references: "
                    + beat.beat_id,
                    beat_id=beat.beat_id,
                ))
        else:
            evidence = str(item.get("evidence") or "").strip()
            if not evidence:
                issues.append(_issue(
                    "receipt_beat_evidence_unbound",
                    "execution manifest beat evidence is missing: "
                    + beat.beat_id,
                    beat_id=beat.beat_id,
                ))
            elif evidence != beat.source_evidence:
                issues.append(_issue(
                    "receipt_beat_evidence_mismatch",
                    "execution manifest beat receipt does not verify its source evidence: "
                    + beat.beat_id,
                    beat_id=beat.beat_id,
                ))

    segment_receipts = receipt.get("segment_receipts")
    expected_segments = [segment.segment for segment in manifest.segments]
    if not isinstance(segment_receipts, list) or any(
        not isinstance(item, dict) for item in segment_receipts
    ):
        issues.append(_issue(
            "receipt_segment_schema",
            "execution manifest segment receipts are invalid",
        ))
        segment_receipts = []
    actual_segments = [item.get("segment") for item in segment_receipts]
    if actual_segments != expected_segments:
        issues.append(_issue(
            "receipt_segment_coverage",
            "execution manifest segment receipt coverage is incomplete",
            expected_segments=expected_segments,
            actual_segments=actual_segments,
        ))
    receipts_by_segment = {
        item.get("segment"): item for item in segment_receipts
    }
    for segment in manifest.segments:
        item = receipts_by_segment.get(segment.segment)
        if item is None:
            continue
        if item.get("boundary_valid") is not True:
            issues.append(_issue(
                "receipt_segment_boundary",
                f"execution manifest segment boundary is invalid: {segment.segment}",
                segment=segment.segment,
            ))
        evidence = str(item.get("evidence") or "").strip()
        if not evidence or evidence not in authority_text:
            issues.append(_issue(
                "receipt_segment_evidence_unbound",
                "execution manifest segment boundary evidence is not bound to authority: "
                + str(segment.segment),
                segment=segment.segment,
            ))
    if receipt.get("formal_plot_unchanged") is not True:
        issues.append(_issue(
            "receipt_formal_plot", "execution manifest changes the formal plot",
        ))
    if not str(receipt.get("summary") or "").strip():
        issues.append(_issue(
            "receipt_summary", "execution manifest receipt summary is missing",
        ))
    return issues


def execution_manifest_receipt_binding_issues(
    manifest: ShortExecutionManifest,
) -> list[dict]:
    """Check that a persisted semantic receipt still belongs to this manifest."""
    receipt = manifest.semantic_receipt
    issues: list[dict] = []
    if receipt.get("authority_sha256") != manifest.authority_sha256:
        issues.append(_issue(
            "receipt_authority_hash",
            "执行清单语义回执没有绑定当前权威资料",
        ))
    if receipt.get("manifest_sha256") != execution_manifest_sha256(manifest):
        issues.append(_issue(
            "receipt_manifest_hash",
            "执行清单语义回执没有绑定当前执行清单",
        ))

    beat_receipts = receipt.get("beat_receipts")
    expected_beat_ids = [beat.beat_id for beat in manifest.beats]
    actual_beat_ids = (
        [str(item.get("beat_id") or "").upper() for item in beat_receipts]
        if isinstance(beat_receipts, list)
        and all(isinstance(item, dict) for item in beat_receipts)
        else []
    )
    if actual_beat_ids != expected_beat_ids:
        issues.append(_issue(
            "receipt_beat_coverage",
            "执行清单语义回执没有逐项覆盖全部原子节拍",
        ))
    elif any(
        item.get("actor_action_valid") is not True
        or (
            item.get("evidence_ids") != list(beat.source_evidence_ids)
            if beat.source_evidence_ids else
            str(item.get("evidence") or "").strip() != beat.source_evidence
        )
        for beat, item in zip(manifest.beats, beat_receipts)
    ):
        issues.append(_issue(
            "receipt_beat_verdict",
            "执行清单语义回执存在未通过或缺少证据的原子节拍",
        ))

    segment_receipts = receipt.get("segment_receipts")
    expected_segments = [segment.segment for segment in manifest.segments]
    actual_segments = (
        [item.get("segment") for item in segment_receipts]
        if isinstance(segment_receipts, list)
        and all(isinstance(item, dict) for item in segment_receipts)
        else []
    )
    if actual_segments != expected_segments:
        issues.append(_issue(
            "receipt_segment_coverage",
            "执行清单语义回执没有逐项覆盖全部写作段",
        ))
    elif any(
        item.get("boundary_valid") is not True
        or not str(item.get("evidence") or "").strip()
        for item in segment_receipts
    ):
        issues.append(_issue(
            "receipt_segment_verdict",
            "执行清单语义回执存在未通过或缺少证据的分段边界",
        ))

    if receipt.get("formal_plot_unchanged") is not True:
        issues.append(_issue(
            "receipt_formal_plot",
            "执行清单语义回执没有确认正式剧情保持不变",
        ))
    if not str(receipt.get("summary") or "").strip():
        issues.append(_issue(
            "receipt_summary",
            "执行清单语义回执缺少核验摘要",
        ))
    return issues


def execution_manifest_issues(
    manifest: ShortExecutionManifest,
    *,
    expected_event_ids: list[str],
    segment_count: int,
    authority_hashes: dict[str, str],
    expected_events: list[dict] | None = None,
) -> list[dict]:
    issues: list[dict] = []
    for field in (
        "authority_sha256", "outline_sha256", "planning_sha256",
        "causal_chain_sha256",
    ):
        expected = str(authority_hashes.get(field) or "")
        if expected and getattr(manifest, field) != expected:
            issues.append(_issue(
                "stale_authority_hash", f"执行清单的 {field} 已过期", field=field,
            ))

    expected_ids = [str(item).upper() for item in expected_event_ids]
    covered_events = {beat.source_event_id for beat in manifest.beats}
    for event_id in expected_ids:
        if event_id not in covered_events:
            issues.append(_issue(
                "missing_source_event", "正式事件没有展开为原子节拍",
                event_id=event_id,
            ))
    for event_id in sorted(covered_events - set(expected_ids)):
        issues.append(_issue(
            "unexpected_source_event", "执行清单引用了当前大纲之外的事件",
            event_id=event_id,
        ))

    event_contracts = {
        str(item.get("id") or "").strip().upper(): item
        for item in (expected_events or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    evidence_catalogs = _event_evidence_catalogs(expected_events)
    event_orders = {
        event_id: index for index, event_id in enumerate(expected_ids)
    }
    collapsed_event_ids: list[str] = []
    for beat in manifest.beats:
        if not collapsed_event_ids or collapsed_event_ids[-1] != beat.source_event_id:
            collapsed_event_ids.append(beat.source_event_id)
        contract = event_contracts.get(beat.source_event_id)
        if contract is None:
            continue
        evidence_issue = _beat_evidence_reference_issue(
            beat, contract, evidence_catalogs.get(beat.source_event_id, ()),
        )
        if evidence_issue:
            issues.append(_issue(
                "source_evidence_mismatch",
                "原子节拍证据不属于它声明的正式事件",
                beat_id=beat.beat_id,
                event_id=beat.source_event_id,
                reason=evidence_issue,
            ))
    for previous, current in zip(collapsed_event_ids, collapsed_event_ids[1:]):
        if (
            previous in event_orders and current in event_orders
            and event_orders[current] < event_orders[previous]
        ):
            issues.append(_issue(
                "source_event_order_reversal",
                "原子节拍改变了正式事件的展示顺序",
                previous_event_id=previous,
                current_event_id=current,
            ))

    orders = [beat.order for beat in manifest.beats]
    if orders != list(range(1, len(orders) + 1)):
        issues.append(_issue(
            "non_contiguous_beat_order", "原子节拍顺序必须从 1 连续递增",
        ))
    if manifest.version >= 3 and [
        beat.presentation_order for beat in manifest.beats
    ] != list(range(1, len(manifest.beats) + 1)):
        issues.append(_issue(
            "non_contiguous_presentation_order",
            "原子节拍展示顺序必须由 Runtime 从 1 连续绑定",
        ))

    segments = sorted(manifest.segments, key=lambda item: item.segment)
    if [item.segment for item in segments] != list(range(1, segment_count + 1)):
        issues.append(_issue(
            "segment_manifest_mismatch", "执行清单必须覆盖全部连续写作段",
        ))
    if segments and segments[0].previous_exit_sha256:
        issues.append(_issue(
            "opening_previous_exit_hash", "第一段不得伪造上一段出口状态哈希",
            segment=segments[0].segment,
        ))

    beat_by_id = {beat.beat_id: beat for beat in manifest.beats}
    expected_future_guards = future_beat_guards(
        manifest.beats, tuple(segment.segment for segment in segments),
    )
    claimed_by: dict[str, list[int]] = {}
    flattened_orders: list[int] = []
    for segment in segments:
        for beat_id in segment.beat_ids:
            claimed_by.setdefault(beat_id, []).append(segment.segment)
            beat = beat_by_id.get(beat_id)
            if beat is None:
                issues.append(_issue(
                    "unknown_segment_beat", "写作段引用了不存在的原子节拍",
                    segment=segment.segment, beat_id=beat_id,
                ))
                continue
            flattened_orders.append(beat.order)
            if beat.owner_segment != segment.segment:
                issues.append(_issue(
                    "beat_owner_mismatch", "原子节拍负责段与分段清单不一致",
                    segment=segment.segment, beat_id=beat_id,
                ))

        owned = set(segment.beat_ids)
        entry_states = {assertion.state for assertion in segment.entry_state}
        for assertion in segment.exit_state:
            producers = assertion.produced_by
            if not producers:
                if not assertion.inherited_from:
                    issues.append(_issue(
                        "exit_producer_missing",
                        "新增出口状态必须注明由当前段拥有的原子节拍产生",
                        segment=segment.segment,
                        state=assertion.state,
                    ))
                elif assertion.state not in entry_states:
                    issues.append(_issue(
                        "inherited_exit_state_missing_entry",
                        "继承的出口状态必须已经存在于当前段入口状态",
                        segment=segment.segment,
                        state=assertion.state,
                    ))
            for producer in producers:
                producer_beat = beat_by_id.get(producer)
                if (
                    producer not in owned
                    or producer_beat is None
                    or producer_beat.owner_segment != segment.segment
                ):
                    issues.append(_issue(
                        "exit_producer_not_owned",
                        f"第 {segment.segment} 段出口状态由其他段负责的节拍产生",
                        segment=segment.segment, beat_id=producer,
                    ))
        expected_guard = expected_future_guards[segment.segment]
        if segment.future_beat_guard != expected_guard:
            issues.append(_issue(
                "future_beat_prohibition_mismatch",
                "当前段必须精确禁止所有后续写作段拥有的原子节拍",
                segment=segment.segment,
                expected_guard=asdict(expected_guard),
                actual_guard=asdict(segment.future_beat_guard),
            ))

    for beat in manifest.beats:
        claims = claimed_by.get(beat.beat_id, [])
        if not claims:
            issues.append(_issue(
                "unclaimed_beat", "原子节拍没有分配到写作段",
                beat_id=beat.beat_id,
            ))
        elif len(claims) > 1:
            issues.append(_issue(
                "duplicate_segment_beat", "原子节拍被多个写作段重复认领",
                beat_id=beat.beat_id, segments=claims,
            ))
    if flattened_orders != sorted(flattened_orders):
        issues.append(_issue(
            "beat_order_reversal", "写作段认领的原子节拍顺序发生倒退",
        ))

    for previous, current in zip(segments, segments[1:]):
        expected_previous_hash = state_assertions_sha256(
            previous.exit_state, version=manifest.version,
        )
        if current.previous_exit_sha256 != expected_previous_hash:
            issues.append(_issue(
                "previous_exit_hash_mismatch",
                "下一段没有绑定上一段的准确出口状态哈希",
                segment=current.segment,
                expected_sha256=expected_previous_hash,
            ))
        previous_states = {item.state for item in previous.exit_state}
        current_states = {item.state for item in current.entry_state}
        if not previous_states <= current_states:
            issues.append(_issue(
                "adjacent_boundary_mismatch", "下一段入口没有完整继承上一段出口",
                segment=current.segment,
                missing_states=sorted(previous_states - current_states),
            ))
    return issues


def execution_manifest_fragment_issues(
    manifest: ShortExecutionManifest,
    *,
    owner_segment: int,
    expected_event_ids: list[str],
    authority_hashes: dict[str, str],
    expected_events: list[dict] | None = None,
    previous_exit_state: tuple[StateAssertion, ...] = (),
) -> list[dict]:
    """Validate one independently generated formal-segment manifest fragment."""
    issues: list[dict] = []
    for field in (
        "authority_sha256", "outline_sha256", "planning_sha256",
        "causal_chain_sha256",
    ):
        expected = str(authority_hashes.get(field) or "")
        if expected and getattr(manifest, field) != expected:
            issues.append(_issue(
                "stale_authority_hash", f"执行清单的 {field} 已过期", field=field,
            ))
    segments = list(manifest.segments)
    if len(segments) != 1 or segments[0].segment != owner_segment:
        issues.append(_issue(
            "fragment_segment_mismatch",
            "执行索引子任务必须只返回当前正式写作段",
            expected_segment=owner_segment,
            actual_segments=[item.segment for item in segments],
        ))
        return issues
    segment = segments[0]
    local_orders = [beat.order for beat in manifest.beats]
    if local_orders != list(range(1, len(local_orders) + 1)):
        issues.append(_issue(
            "non_contiguous_beat_order",
            "子任务原子节拍顺序必须从 1 连续递增",
            segment=owner_segment,
        ))
    expected_ids = [str(item).upper() for item in expected_event_ids]
    covered_ids = {beat.source_event_id for beat in manifest.beats}
    for event_id in expected_ids:
        if event_id not in covered_ids:
            issues.append(_issue(
                "missing_source_event", "当前正式段事件没有展开为原子节拍",
                segment=owner_segment, event_id=event_id,
            ))
    for event_id in sorted(covered_ids - set(expected_ids)):
        issues.append(_issue(
            "unexpected_source_event", "当前正式段提前或越界引用了其他事件",
            segment=owner_segment, event_id=event_id,
        ))
    contract_map = {
        str(item.get("id") or "").strip().upper(): item
        for item in (expected_events or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    evidence_catalogs = _event_evidence_catalogs(expected_events)
    event_order = {event_id: index for index, event_id in enumerate(expected_ids)}
    collapsed: list[str] = []
    for beat in manifest.beats:
        if beat.owner_segment != owner_segment:
            issues.append(_issue(
                "beat_owner_mismatch", "子任务节拍被分配到了其他写作段",
                segment=owner_segment, beat_id=beat.beat_id,
            ))
        if not collapsed or collapsed[-1] != beat.source_event_id:
            collapsed.append(beat.source_event_id)
        contract = contract_map.get(beat.source_event_id)
        evidence_issue = _beat_evidence_reference_issue(
            beat, contract, evidence_catalogs.get(beat.source_event_id, ()),
        ) if contract else ""
        if evidence_issue:
            issues.append(_issue(
                "source_evidence_mismatch",
                "原子节拍证据不属于它声明的正式事件",
                segment=owner_segment, beat_id=beat.beat_id,
                event_id=beat.source_event_id,
                reason=evidence_issue,
            ))
    for previous, current in zip(collapsed, collapsed[1:]):
        if (
            previous in event_order and current in event_order
            and event_order[current] < event_order[previous]
        ):
            issues.append(_issue(
                "source_event_order_reversal",
                "当前正式段改变了规划中的事件展示顺序",
                segment=owner_segment,
                previous_event_id=previous,
                current_event_id=current,
            ))
    beat_ids = [beat.beat_id for beat in manifest.beats]
    if list(segment.beat_ids) != beat_ids:
        issues.append(_issue(
            "fragment_beat_coverage",
            "当前正式段清单没有按顺序认领它的全部原子节拍",
            segment=owner_segment,
        ))
    owned = set(beat_ids)
    beat_by_id = {beat.beat_id: beat for beat in manifest.beats}
    entry_states = {assertion.state for assertion in segment.entry_state}
    previous_states = {assertion.state for assertion in previous_exit_state}
    expected_previous_hash = (
        state_assertions_sha256(previous_exit_state, version=manifest.version)
        if previous_exit_state else ""
    )
    if segment.previous_exit_sha256 != expected_previous_hash:
        issues.append(_issue(
            "previous_exit_hash_mismatch",
            "当前段没有绑定上一段的准确出口状态哈希",
            segment=owner_segment,
            expected_sha256=expected_previous_hash,
        ))
    if previous_states and not previous_states <= entry_states:
        issues.append(_issue(
            "adjacent_boundary_mismatch", "当前段入口没有完整继承上一段出口",
            segment=owner_segment,
            missing_states=sorted(previous_states - entry_states),
        ))
    for assertion in segment.exit_state:
        producers = assertion.produced_by
        if not producers:
            if not assertion.inherited_from:
                issues.append(_issue(
                    "exit_producer_missing",
                    "新增出口状态必须注明由当前段拥有的原子节拍产生",
                    segment=owner_segment, state=assertion.state,
                ))
            elif assertion.state not in entry_states:
                issues.append(_issue(
                    "inherited_exit_state_missing_entry",
                    "继承的出口状态必须已经存在于当前段入口状态",
                    segment=owner_segment, state=assertion.state,
                ))
        for producer in producers:
            if producer not in owned or producer not in beat_by_id:
                issues.append(_issue(
                    "exit_producer_not_owned",
                    f"第 {owner_segment} 段出口状态由其他段负责的节拍产生",
                    segment=owner_segment, beat_id=producer,
                ))
    return issues


def merge_execution_manifest_fragments(
    fragments: list[ShortExecutionManifest],
    *,
    authority_hashes: dict[str, str],
    segment_count: int,
    repair_attempts: int = 0,
) -> ShortExecutionManifest:
    """Merge validated fragments and bind global IDs, order, handoffs and future bans."""
    ordered = sorted(fragments, key=lambda item: item.segments[0].segment)
    if [item.segments[0].segment for item in ordered] != list(
        range(1, segment_count + 1)
    ):
        raise ValueError("execution manifest fragments do not cover every segment")
    counters: dict[str, int] = {}
    beats: list[AtomicBeat] = []
    segment_rows: list[tuple[int, tuple[StateAssertion, ...], tuple[StateAssertion, ...], list[str]]] = []
    previous_id_map: dict[str, str] = {}
    for fragment in ordered:
        segment = fragment.segments[0]
        id_map: dict[str, str] = {}
        current_ids: list[str] = []
        for beat in sorted(fragment.beats, key=lambda item: item.order):
            counters[beat.source_event_id] = counters.get(beat.source_event_id, 0) + 1
            if counters[beat.source_event_id] > 99:
                raise ValueError(
                    f"formal event has more than 99 atomic beats: {beat.source_event_id}"
                )
            beat_id = f"{beat.source_event_id}/{counters[beat.source_event_id]:02d}"
            id_map[beat.beat_id] = beat_id
            current_ids.append(beat_id)
            global_order = len(beats) + 1
            beats.append(replace(
                beat,
                beat_id=beat_id,
                order=global_order,
                presentation_order=global_order,
                owner_segment=segment.segment,
            ))
        entry_state = tuple(replace(
            assertion,
            produced_by=tuple(
                previous_id_map.get(producer, producer)
                for producer in assertion.produced_by
            ),
        ) for assertion in segment.entry_state)
        exit_state = tuple(replace(
            assertion,
            produced_by=tuple(
                id_map.get(producer, producer)
                for producer in assertion.produced_by
            ),
        ) for assertion in segment.exit_state)
        segment_rows.append((
            segment.segment, entry_state, exit_state, current_ids,
        ))
        previous_id_map = id_map
    segments: list[SegmentBeatContract] = []
    previous_exit: tuple[StateAssertion, ...] = ()
    merged_beats = tuple(beats)
    merged_future_guards = future_beat_guards(
        merged_beats, tuple(row[0] for row in segment_rows),
    )
    for number, entry_state, exit_state, beat_ids in segment_rows:
        segments.append(SegmentBeatContract(
            segment=number,
            beat_ids=tuple(beat_ids),
            entry_state=entry_state,
            exit_state=exit_state,
            previous_exit_sha256=(
                state_assertions_sha256(previous_exit, version=6)
                if previous_exit else ""
            ),
            future_beat_guard=merged_future_guards[number],
        ))
        previous_exit = exit_state
    return ShortExecutionManifest(
        version=6,
        status="ready",
        authority_sha256=authority_hashes["authority_sha256"],
        outline_sha256=authority_hashes["outline_sha256"],
        planning_sha256=authority_hashes["planning_sha256"],
        causal_chain_sha256=authority_hashes["causal_chain_sha256"],
        beats=merged_beats,
        segments=tuple(segments),
        semantic_receipt={},
        repair_attempts=repair_attempts,
    )


def legacy_execution_index_requires_rebuild(value: object) -> bool:
    return not (
        isinstance(value, dict)
        and value.get("version") in {3, 4, 5, 6}
        and isinstance(value.get("beats"), list)
        and bool(value.get("beats"))
        and isinstance(value.get("segments"), list)
        and bool(value.get("segments"))
        and isinstance(value.get("semantic_receipt"), dict)
    )
