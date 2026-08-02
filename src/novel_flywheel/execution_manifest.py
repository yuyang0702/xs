from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any


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
    source_evidence: str


@dataclass(frozen=True)
class StateAssertion:
    state: str
    produced_by: str = ""
    inherited_from: str = ""


@dataclass(frozen=True)
class SegmentBeatContract:
    segment: int
    beat_ids: tuple[str, ...]
    entry_state: tuple[StateAssertion, ...]
    exit_state: tuple[StateAssertion, ...]
    previous_exit_sha256: str
    prohibited_future_beat_ids: tuple[str, ...]


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


def _state_assertions(value: object, field: str) -> tuple[StateAssertion, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    assertions = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{field}[{index}] must be an object")
        produced_by = str(item.get("produced_by") or "").strip().upper()
        if produced_by:
            produced_by = _beat_id(produced_by, f"{field}[{index}].produced_by")
        assertions.append(StateAssertion(
            state=_text(item.get("state"), f"{field}[{index}].state"),
            produced_by=produced_by,
            inherited_from=str(item.get("inherited_from") or "").strip(),
        ))
    return tuple(assertions)


def parse_execution_manifest(value: object) -> ShortExecutionManifest:
    if not isinstance(value, dict):
        raise ValueError("execution manifest must be a JSON object")
    if value.get("version") != 2:
        raise ValueError("execution manifest version must be 2")
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
        beats.append(AtomicBeat(
            beat_id=beat_id,
            source_event_id=source_event_id,
            order=_positive_int(item.get("order"), f"beats[{index}].order"),
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
            source_evidence=_text(
                item.get("source_evidence"), f"beats[{index}].source_evidence",
            ),
        ))

    segments = []
    seen_segments: set[int] = set()
    for index, item in enumerate(raw_segments):
        if not isinstance(item, dict):
            raise ValueError(f"segments[{index}] must be an object")
        segment = _positive_int(item.get("segment"), f"segments[{index}].segment")
        if segment in seen_segments:
            raise ValueError(f"duplicate segment: {segment}")
        seen_segments.add(segment)
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
            ),
            exit_state=_state_assertions(
                item.get("exit_state"), f"segments[{index}].exit_state",
            ),
            previous_exit_sha256=_sha256(
                item.get("previous_exit_sha256"),
                f"segments[{index}].previous_exit_sha256", allow_empty=True,
            ),
            prohibited_future_beat_ids=tuple(
                _beat_id(beat_id, f"segments[{index}].prohibited_future_beat_ids")
                for beat_id in _string_tuple(
                    item.get("prohibited_future_beat_ids"),
                    f"segments[{index}].prohibited_future_beat_ids",
                )
            ),
        ))

    semantic_receipt = value.get("semantic_receipt")
    if not isinstance(semantic_receipt, dict):
        raise ValueError("semantic_receipt must be an object")
    return ShortExecutionManifest(
        version=2,
        status=_text(value.get("status"), "status"),
        authority_sha256=_sha256(value.get("authority_sha256"), "authority_sha256"),
        outline_sha256=_sha256(value.get("outline_sha256"), "outline_sha256"),
        planning_sha256=_sha256(value.get("planning_sha256"), "planning_sha256"),
        causal_chain_sha256=_sha256(
            value.get("causal_chain_sha256"), "causal_chain_sha256",
        ),
        beats=tuple(beats),
        segments=tuple(segments),
        semantic_receipt=dict(semantic_receipt),
        repair_attempts=_positive_int(
            value.get("repair_attempts", 0), "repair_attempts", allow_zero=True,
        ),
    )


def execution_manifest_sha256(manifest: ShortExecutionManifest) -> str:
    payload = asdict(manifest)
    payload.pop("semantic_receipt", None)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def state_assertions_sha256(assertions: tuple[StateAssertion, ...]) -> str:
    encoded = json.dumps(
        [asdict(item) for item in assertions],
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
    previous_exit: tuple[StateAssertion, ...] | None = None
    for item in ordered:
        item["previous_exit_sha256"] = (
            state_assertions_sha256(previous_exit) if previous_exit else ""
        )
        previous_exit = _state_assertions(
            item.get("exit_state"), "segments.exit_state",
        )
    result["segments"] = segments
    return result


def _bound_evidence(authority_text: str, value: object, field: str) -> str:
    evidence = str(value or "").strip()
    if not evidence or evidence not in authority_text:
        raise ValueError(f"execution manifest {field} evidence is not bound to authority")
    return evidence


def validate_execution_manifest_receipt(
    manifest: ShortExecutionManifest,
    authority_text: str,
    receipt: object,
) -> dict:
    if not isinstance(receipt, dict):
        raise ValueError("execution manifest semantic receipt must be an object")
    if receipt.get("authority_sha256") != manifest.authority_sha256:
        raise ValueError("execution manifest receipt authority hash is stale")
    if receipt.get("manifest_sha256") != execution_manifest_sha256(manifest):
        raise ValueError("execution manifest receipt manifest hash is stale")
    beat_receipts = receipt.get("beat_receipts")
    if not isinstance(beat_receipts, list) or any(
        not isinstance(item, dict) for item in beat_receipts
    ):
        raise ValueError("execution manifest beat receipts are invalid")
    if [str(item.get("beat_id") or "").upper() for item in beat_receipts] != [
        beat.beat_id for beat in manifest.beats
    ]:
        raise ValueError("execution manifest beat receipt coverage is incomplete")
    normalized_beats = []
    for beat, item in zip(manifest.beats, beat_receipts):
        if item.get("actor_action_valid") is not True:
            raise ValueError(f"execution manifest beat actor/action is invalid: {beat.beat_id}")
        if beat.source_evidence not in authority_text:
            raise ValueError(
                f"execution manifest beat source evidence is not bound to authority: {beat.beat_id}"
            )
        receipt_evidence = _bound_evidence(
            authority_text, item.get("evidence"), "beat",
        )
        if receipt_evidence != beat.source_evidence:
            raise ValueError(
                f"execution manifest beat receipt does not verify its source evidence: {beat.beat_id}"
            )
        normalized_beats.append({
            "beat_id": beat.beat_id,
            "evidence": receipt_evidence,
            "actor_action_valid": True,
        })
    segment_receipts = receipt.get("segment_receipts")
    if not isinstance(segment_receipts, list) or any(
        not isinstance(item, dict) for item in segment_receipts
    ):
        raise ValueError("execution manifest segment receipts are invalid")
    if [item.get("segment") for item in segment_receipts] != [
        segment.segment for segment in manifest.segments
    ]:
        raise ValueError("execution manifest segment receipt coverage is incomplete")
    normalized_segments = []
    for segment, item in zip(manifest.segments, segment_receipts):
        if item.get("boundary_valid") is not True:
            raise ValueError(
                f"execution manifest segment boundary is invalid: {segment.segment}"
            )
        normalized_segments.append({
            "segment": segment.segment,
            "boundary_valid": True,
            "evidence": _bound_evidence(
                authority_text, item.get("evidence"), "segment boundary",
            ),
        })
    if receipt.get("formal_plot_unchanged") is not True:
        raise ValueError("execution manifest changes the formal plot")
    summary = str(receipt.get("summary") or "").strip()
    if not summary:
        raise ValueError("execution manifest receipt summary is missing")
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
        or str(item.get("evidence") or "").strip() != beat.source_evidence
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

    expected_events = [str(item).upper() for item in expected_event_ids]
    covered_events = {beat.source_event_id for beat in manifest.beats}
    for event_id in expected_events:
        if event_id not in covered_events:
            issues.append(_issue(
                "missing_source_event", "正式事件没有展开为原子节拍",
                event_id=event_id,
            ))
    for event_id in sorted(covered_events - set(expected_events)):
        issues.append(_issue(
            "unexpected_source_event", "执行清单引用了当前大纲之外的事件",
            event_id=event_id,
        ))

    orders = [beat.order for beat in manifest.beats]
    if orders != list(range(1, len(orders) + 1)):
        issues.append(_issue(
            "non_contiguous_beat_order", "原子节拍顺序必须从 1 连续递增",
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
            producer = assertion.produced_by
            producer_beat = beat_by_id.get(producer) if producer else None
            if not producer:
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
            if producer and (
                producer not in owned
                or producer_beat is None
                or producer_beat.owner_segment != segment.segment
            ):
                issues.append(_issue(
                    "exit_producer_not_owned",
                    f"第 {segment.segment} 段出口状态由其他段负责的节拍产生",
                    segment=segment.segment, beat_id=producer,
                ))
        prohibited = set(segment.prohibited_future_beat_ids)
        expected_future = tuple(
            beat.beat_id
            for beat in sorted(manifest.beats, key=lambda item: item.order)
            if beat.owner_segment > segment.segment
        )
        if segment.prohibited_future_beat_ids != expected_future:
            issues.append(_issue(
                "future_beat_prohibition_mismatch",
                "当前段必须精确禁止所有后续写作段拥有的原子节拍",
                segment=segment.segment,
                expected_beat_ids=list(expected_future),
                actual_beat_ids=list(segment.prohibited_future_beat_ids),
            ))
        for beat_id in sorted(owned & prohibited):
            issues.append(_issue(
                "owned_beat_is_prohibited", "当前段同时拥有并禁止同一原子节拍",
                segment=segment.segment, beat_id=beat_id,
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
        expected_previous_hash = state_assertions_sha256(previous.exit_state)
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


def legacy_execution_index_requires_rebuild(value: object) -> bool:
    return not (
        isinstance(value, dict)
        and value.get("version") == 2
        and isinstance(value.get("beats"), list)
        and bool(value.get("beats"))
        and isinstance(value.get("segments"), list)
        and bool(value.get("segments"))
        and isinstance(value.get("semantic_receipt"), dict)
    )
