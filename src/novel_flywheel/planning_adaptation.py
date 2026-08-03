from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any


PLANNING_ADAPTATION_VERSION = 1

PLANNING_ADAPTATION_PROTOCOL_CODES = frozenset({
    "receipt_schema",
    "authority_hash",
    "planning_hash",
    "segment_identity",
    "event_schema",
    "event_coverage",
    "adaptation_receipt_conflict",
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
    normalized = plan_segment.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return {}
    blocks = [block.strip() for block in re.split(r"\n[ \t]*\n+", normalized)]
    candidates: list[str] = []

    def semantic(value: str) -> bool:
        visible = value.strip()
        if re.fullmatch(r"#{1,6}\s+.+", visible):
            return False
        plain = visible.replace("**", "").replace("__", "").replace("`", "")
        return not re.match(
            r"^(?:[-+*]\s*)?(?:事件\s*ID|大纲依据|正式大纲依据)\s*[：:]",
            plain, flags=re.IGNORECASE,
        )

    for block in blocks:
        if len(re.sub(r"\s+", "", block)) < 8 or not semantic(block):
            continue
        candidates.append(block)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    candidates.extend(
        line for line in lines
        if len(re.sub(r"\s+", "", line)) >= 12 and semantic(line)
    )
    if not candidates and len(normalized) <= 8000:
        candidates.append(normalized)
    unique = list(dict.fromkeys(candidates))
    return {
        f"PLAN-{segment:02d}-E{index:03d}": evidence
        for index, evidence in enumerate(unique, 1)
    }


def planning_adaptation_segment_authority_sha256(
    *, outline_sha256: str, planning_sha256: str, segment: int,
    event_contracts: list[dict], plan_segment: str,
) -> str:
    payload = {
        "version": PLANNING_ADAPTATION_VERSION,
        "outline_sha256": outline_sha256,
        "planning_sha256": planning_sha256,
        "segment": segment,
        "event_contracts": event_contracts,
        "plan_segment": plan_segment,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def planning_adaptation_whole_authority_sha256(
    *, outline_sha256: str, planning_sha256: str,
    segment_receipts: list[dict],
) -> str:
    payload = {
        "version": PLANNING_ADAPTATION_VERSION,
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
        raw_invariants = item.get("invariants")
        if isinstance(raw_invariants, dict):
            invariants: dict[str, object] = {}
            for key, value in raw_invariants.items():
                canonical = _INVARIANT_ALIASES.get(_normalized_label(key))
                if canonical:
                    invariants[canonical] = _boolean(value)
            item["invariants"] = invariants
        invariants = item.get("invariants")
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
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    def add(code: str, message: str, **metadata: Any) -> None:
        issues.append({"code": code, "message": message, **metadata})

    if not isinstance(receipt, dict):
        add("receipt_schema", "规划适配回执必须是一个 JSON 对象")
        return issues
    if receipt.get("authority_sha256") != authority_sha256:
        add("authority_hash", "规划适配回执没有绑定当前正式大纲和规划段")
    if receipt.get("planning_sha256") != planning_sha256:
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
        if (
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
            )
        if classification != "unchanged" and not str(item.get("reason") or "").strip():
            add(
                "adaptation_reason", "非原样规划调整必须说明等价性或结构风险",
                event_id=event_id,
            )
    if receipt.get("segment_order_preserved") is not True:
        add("planning_segment_order", "规划调整改变了正式事件的展示或依赖顺序")
    if receipt.get("formal_direction_preserved") is not True:
        add("planning_formal_direction", "规划调整改变了正式剧情方向或结局承诺")
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
