import copy
import hashlib
import re
import math
import unicodedata
from statistics import median
from typing import Any

from novel_flywheel.prose_policy import (
    ProseValidationPolicy,
    infer_narrative_beat_tags,
)
from novel_flywheel.prose_quality import analyze_prose
from novel_flywheel.model_output import canonical_model_label


CHECK_KINDS = {"required_text", "forbidden_text"}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
CJK = r"\u3400-\u9fff"
PATCH_OPERATIONS = {"replace", "insert_before", "insert_after"}
REPAIR_KINDS = {"semantic", "mechanical"}
REPAIR_KIND_ALIASES = {
    "semantic": "semantic", "semantic_repair": "semantic",
    "content": "semantic", "narrative": "semantic",
    "targeted_revision": "semantic", "语义": "semantic",
    "语义修复": "semantic", "内容": "semantic", "剧情": "semantic",
    "mechanical": "mechanical", "mechanical_repair": "mechanical",
    "format": "mechanical", "typography": "mechanical",
    "deterministic": "mechanical", "机械": "mechanical",
    "机械修复": "mechanical", "格式": "mechanical", "排版": "mechanical",
}
PATCH_OPERATION_ALIASES = {
    "replace": "replace", "replacement": "replace", "substitute": "replace",
    "rewrite": "replace", "替换": "replace", "改写": "replace", "修改": "replace",
    "insert_before": "insert_before", "add_before": "insert_before",
    "prepend": "insert_before", "before": "insert_before",
    "前插": "insert_before", "前置插入": "insert_before", "在前插入": "insert_before",
    "insert_after": "insert_after", "add_after": "insert_after",
    "append": "insert_after", "after": "insert_after",
    "后插": "insert_after", "后置插入": "insert_after", "在后插入": "insert_after",
}
CHECK_KIND_ALIASES = {
    "required_text": "required_text", "must_include": "required_text",
    "contains": "required_text", "preserve_text": "required_text",
    "必须包含": "required_text", "必须保留": "required_text", "保留文本": "required_text",
    "forbidden_text": "forbidden_text", "must_not_include": "forbidden_text",
    "exclude": "forbidden_text", "remove_text": "forbidden_text",
    "禁止出现": "forbidden_text", "必须删除": "forbidden_text", "删除文本": "forbidden_text",
}
REPAIR_LABELS = {
    "ascii_dialogue_quotes": "ASCII 对话引号",
    "cjk_spacing": "汉字间多余空格",
    "duplicate_punctuation": "连续重复标点",
    "c0_control": "C0 控制字符",
    "consecutive_duplicate_blocks": "连续重复文本块",
    "unpaired_quote": "未配对引号",
    "non_unique_quote_pair": "非唯一引号对",
    "truncated_sentence": "疑似句子截断",
}
_CHINESE_SEGMENT_NUMBERS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}
_SEGMENT_NUMBER_TOKEN = r"\d{1,2}|十二|十一|十|九|八|七|六|五|四|三|二|两|一"
_SEGMENT_LABEL = re.compile(
    rf"^(?:"
    rf"(?:第\s*)?(?P<before>{_SEGMENT_NUMBER_TOKEN})\s*(?:个\s*)?"
    rf"(?:(?:写作|规划)?(?:分)?段(?:落)?)|"
    rf"(?:(?:写作|规划)?(?:分)?段(?:落)?)\s*(?P<after>{_SEGMENT_NUMBER_TOKEN})|"
    rf"segment\s*(?P<english>\d{{1,2}})|"
    rf"(?:scene|场景)\s*[-_]?\s*(?P<scene>{_SEGMENT_NUMBER_TOKEN})"
    rf")(?=$|[\s:：·—–\-（(])",
    re.IGNORECASE,
)


def canonical_repair_kind(value: object) -> str | None:
    return canonical_model_label(value, REPAIR_KIND_ALIASES)


def canonical_patch_operation(value: object) -> str | None:
    return canonical_model_label(value, PATCH_OPERATION_ALIASES)


def canonical_check_kind(value: object) -> str | None:
    return canonical_model_label(value, CHECK_KIND_ALIASES)


def parse_segment_number(value: Any, *, allow_scene: bool = True) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    text = re.sub(r"^#{1,6}[ \t]*", "", text)
    text = text.translate(str.maketrans("", "", "*_`")).strip()
    text = re.sub(
        r"^\d+\s*[.、)]\s*(?=(?:第|段|分段|写作段|规划段|segment))",
        "", text, flags=re.IGNORECASE,
    )
    if text.isdecimal():
        return int(text)
    if text in _CHINESE_SEGMENT_NUMBERS:
        return _CHINESE_SEGMENT_NUMBERS[text]
    match = _SEGMENT_LABEL.match(text)
    if not match:
        return None
    if match.group("scene") is not None and not allow_scene:
        return None
    token = next(value for value in match.groupdict().values() if value is not None)
    return int(token) if token.isdecimal() else _CHINESE_SEGMENT_NUMBERS.get(token)


def _repair_record(code: str) -> dict[str, str]:
    return {"code": code, "label": REPAIR_LABELS[code]}


def apply_patch_group(manuscript: str, group: dict, source_hash: str) -> dict:
    if hashlib.sha256(manuscript.encode("utf-8")).hexdigest() != source_hash:
        return {"accepted": False, "text": manuscript,
                "failures": [{"patch": 0, "code": "source_hash_changed"}], "diffs": []}
    candidate = manuscript
    diffs = []
    for number, patch in enumerate(group.get("patches", []), 1):
        old = str(patch.get("old_text") or "")
        new = str(patch.get("new_text") or "")
        operation = patch.get("operation")
        if not old or candidate.count(old) != 1:
            return {"accepted": False, "text": manuscript,
                    "failures": [{"patch": number, "code": "anchor_not_unique"}], "diffs": []}
        if operation == "replace":
            replacement = new
        elif operation == "insert_before":
            replacement = new + old
        elif operation == "insert_after":
            replacement = old + new
        else:
            return {"accepted": False, "text": manuscript,
                    "failures": [{"patch": number, "code": "operation_invalid"}], "diffs": []}
        start = candidate.index(old)
        candidate = candidate[:start] + replacement + candidate[start + len(old):]
        diffs.append({"patch": number, "start": start, "old_text": old, "new_text": replacement})
    return {"accepted": True, "text": candidate, "failures": [], "diffs": diffs}


def normalize_repair_contract(value: dict, manuscript: str,
                              issue_ids: set[str]) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Repair contract must be an object")
    result = copy.deepcopy(value)
    manuscript_hash = hashlib.sha256(manuscript.encode("utf-8")).hexdigest()
    if result.get("manuscript_hash") != manuscript_hash:
        raise ValueError("Repair contract manuscript_hash is stale")
    groups = result.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("Repair contract must contain a group")
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Repair contract group must be an object")
        linked_ids = group.get("issue_ids")
        if not isinstance(linked_ids, list) or not linked_ids:
            raise ValueError("Repair contract group must reference an issue")
        if any(not isinstance(issue_id, str) or issue_id not in issue_ids
               for issue_id in linked_ids):
            raise ValueError("Repair contract references an unknown issue")
        if len(set(linked_ids)) != 1:
            raise ValueError("Repair contract group mixes unrelated issue IDs")
        raw_kind = group.get("kind", "semantic")
        kind = canonical_repair_kind(raw_kind)
        if kind not in REPAIR_KINDS:
            raise ValueError("Repair contract group kind is unsupported")
        if str(raw_kind) != kind:
            group["raw_kind"] = raw_kind
        group["kind"] = kind
        if not group.get("requires_user_confirmation"):
            raise ValueError("Repair contract group requires user confirmation")
        patches = group.get("patches")
        if not isinstance(patches, list) or not patches:
            raise ValueError("Repair contract group must contain a patch")
        for patch in patches:
            if not isinstance(patch, dict):
                raise ValueError("Repair contract patch operation is unsupported")
            raw_operation = patch.get("operation")
            operation = canonical_patch_operation(raw_operation)
            if operation not in PATCH_OPERATIONS:
                raise ValueError("Repair contract patch operation is unsupported")
            if str(raw_operation) != operation:
                patch["raw_operation"] = raw_operation
            patch["operation"] = operation
            old = patch.get("old_text")
            if not isinstance(old, str) or not old or manuscript.count(old) != 1:
                raise ValueError("Repair contract old_text must be unique")
    return result


def repair_mechanical_text(text: str) -> dict:
    applied: list[dict[str, str]] = []
    blocked: list[dict[str, str]] = []

    def record(items: list[dict[str, str]], code: str) -> None:
        if not any(item["code"] == code for item in items):
            items.append(_repair_record(code))

    normalized_lines = []
    quote_repaired = False
    for line in text.splitlines(keepends=True):
        quote_count = line.count('"')
        if quote_count == 2:
            opening = line.index('"')
            closing = line.index('"', opening + 1)
            dialogue = line[opening + 1:closing]
            if re.search(rf"[{CJK}]", dialogue):
                line = line[:opening] + "“" + dialogue + "”" + line[closing + 1:]
                quote_repaired = True
        elif quote_count % 2:
            record(blocked, "unpaired_quote")
        elif quote_count > 2:
            record(blocked, "non_unique_quote_pair")
        normalized_lines.append(line)
    normalized = "".join(normalized_lines)
    if quote_repaired:
        record(applied, "ascii_dialogue_quotes")

    normalized, count = re.subn(rf"(?<=[{CJK}]) +(?=[{CJK}])", "", normalized)
    if count:
        record(applied, "cjk_spacing")
    normalized, count = re.subn(r"([。！？；，])\1{2,}", r"\1", normalized)
    if count:
        record(applied, "duplicate_punctuation")
    normalized, count = re.subn(r"[\x00-\x08\x0b-\x1f]", "", normalized)
    if count:
        record(applied, "c0_control")
    normalized, removals = remove_consecutive_duplicate_blocks(normalized)
    if removals:
        record(applied, "consecutive_duplicate_blocks")

    if re.search(rf"[{CJK}]\s*$", normalized):
        record(blocked, "truncated_sentence")
    return {"text": normalized, "applied": applied, "blocked": blocked}


def normalize_chinese_prose(text: str) -> tuple[str, list[str]]:
    repairs = []
    normalized, count = re.subn(
        rf'"([^"\n]*[{CJK}][^"\n]*)"', r"“\1”", text,
    )
    if count:
        repairs.append("ascii_dialogue_quotes")
    normalized, count = re.subn(rf"(?<=[{CJK}]) +(?=[{CJK}])", "", normalized)
    if count:
        repairs.append("cjk_spacing")
    normalized, count = re.subn(r"([。！？；，])\1{2,}", r"\1", normalized)
    if count:
        repairs.append("duplicate_punctuation")
    return normalized, repairs


def _robust_boundary(values: list[float], *, floor: float) -> float:
    if not values:
        return floor
    center = median(values)
    deviation = median(abs(value - center) for value in values)
    return center + max(floor, 3 * deviation)


def assess_polish_candidate(
    source: str,
    candidate: str,
    required_literals: list[str] | None = None,
    minimum_ratio: float = 0.70,
    maximum_ratio: float = 1.60,
    *,
    policy: ProseValidationPolicy | None = None,
    history_metrics: list[dict[str, float]] | None = None,
    narrative_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = candidate.strip()
    ratio = len(candidate) / max(1, len(source.strip()))
    report = analyze_prose(candidate)
    source_report = analyze_prose(source)
    policy = policy or ProseValidationPolicy()
    history = [item for item in (history_metrics or [])[-5:] if isinstance(item, dict)]
    hard_reasons: list[str] = []
    soft_by_family: dict[str, dict[str, Any]] = {}

    def add_soft(family: str, code: str, *, severe: bool = False,
                 evidence: dict[str, Any] | None = None) -> None:
        current = soft_by_family.get(family)
        if current is None:
            soft_by_family[family] = {
                "family": family,
                "code": code,
                "severe": severe,
                "evidence": evidence or {},
                "codes": [code],
            }
            return
        current["severe"] = bool(current["severe"] or severe)
        if code not in current["codes"]:
            current["codes"].append(code)

    if len(source.strip()) >= 200 and (ratio < minimum_ratio or ratio > maximum_ratio):
        hard_reasons.append("length_ratio")
    if report["blocking_count"]:
        hard_reasons.append("production_text")
    for literal in required_literals or []:
        if literal and literal in source and literal not in candidate:
            hard_reasons.append(f"missing_literal:{literal}")
    source_metrics = source_report["metrics"]
    candidate_metrics = report["metrics"]
    source_codes = {item["code"] for item in source_report["findings"]}
    candidate_codes = {item["code"] for item in report["findings"]}
    if "timestamp_scene_fragment" in source_codes & candidate_codes:
        add_soft("scene_transition", "timestamp_scene_fragment_not_improved", severe=True)
    if (source_metrics["dialogue_turn_run"] >= 4
            and candidate_metrics["dialogue_turn_run"] >= 4):
        add_soft("dialogue", "dialogue_ping_pong_not_improved", severe=True)

    rhythm_code = ""
    rhythm_severe = False
    if source_metrics["short_sentence_run"] >= 4:
        rhythm_improved = (
            candidate_metrics["short_sentence_run"]
            <= max(3, source_metrics["short_sentence_run"] - 2)
            or candidate_metrics["short_sentence_ratio"]
            <= source_metrics["short_sentence_ratio"] - 0.05
        )
        if not rhythm_improved:
            rhythm_code = "sentence_rhythm_not_improved"
            rhythm_severe = True

    history_ratios = [float(item.get("short_sentence_ratio", 0.0)) for item in history]
    ratio_boundary = max(
        float(source_metrics["short_sentence_ratio"]) + policy.absolute_ratio_floor,
        _robust_boundary(history_ratios, floor=policy.absolute_ratio_floor),
    )
    new_short_units = (
        int(candidate_metrics["short_sentence_count"])
        - int(source_metrics["short_sentence_count"])
    )
    ratio_risk = (
        new_short_units >= policy.minimum_new_units
        and candidate_metrics["short_sentence_ratio"] > ratio_boundary
    )
    short_run_risk = (
        candidate_metrics["short_sentence_run"]
        > max(3.0, float(source_metrics["short_sentence_run"]) + 2.0)
    )
    paragraph_run_risk = (
        candidate_metrics["one_sentence_paragraph_run"]
        > max(2.0, float(source_metrics["one_sentence_paragraph_run"]) + 2.0)
    )
    if re.search(r"[。！？.!?]", source) and (
        ratio_risk or short_run_risk or paragraph_run_risk
    ):
        rhythm_code = rhythm_code or "sentence_rhythm_regression"
        rhythm_severe = bool(
            rhythm_severe
            or candidate_metrics["short_sentence_run"] >= 4
            or candidate_metrics["one_sentence_paragraph_run"] >= 4
            or candidate_metrics["one_sentence_paragraph_ratio"] >= 0.5
        )
    if rhythm_code:
        add_soft("rhythm", rhythm_code, severe=rhythm_severe, evidence={
            "source_short_sentence_ratio": source_metrics["short_sentence_ratio"],
            "candidate_short_sentence_ratio": candidate_metrics["short_sentence_ratio"],
            "short_sentence_ratio_boundary": round(ratio_boundary, 3),
            "new_short_units": new_short_units,
            "short_sentence_run": candidate_metrics["short_sentence_run"],
            "one_sentence_paragraph_run": candidate_metrics["one_sentence_paragraph_run"],
        })

    rhythm_findings = {"uniform_short_sentence_run", "one_sentence_paragraph_run"}
    new_non_rhythm_codes = (candidate_codes - source_codes) - rhythm_findings
    if (report["targeted_count"] > source_report["targeted_count"] + 2
            and new_non_rhythm_codes):
        add_soft("style", "style_regression", severe=True, evidence={
            "new_codes": sorted(new_non_rhythm_codes),
        })

    soft_signals = list(soft_by_family.values())
    beat_tags = infer_narrative_beat_tags(narrative_context or {})
    style_allowances: list[dict[str, Any]] = []
    actionable = list(soft_signals)
    if ("rhythm" in soft_by_family and not policy.conflicts
            and beat_tags.intersection(policy.authorized_short_beats)):
        style_allowances.append({
            "family": "rhythm",
            "authorized_beats": sorted(beat_tags.intersection(
                policy.authorized_short_beats
            )),
            "policy_sources": list(policy.source_ids),
        })
        actionable = [item for item in actionable if item["family"] != "rhythm"]

    if hard_reasons:
        disposition = "reject"
    elif len(actionable) >= 2 or any(item["severe"] for item in actionable):
        disposition = "targeted_repair"
    elif style_allowances and not actionable:
        disposition = "pass_with_style_allowance"
    else:
        disposition = "pass"

    reasons = list(hard_reasons)
    if disposition == "targeted_repair":
        reasons.extend(item["code"] for item in actionable)
    return {
        "accepted": disposition in {"pass", "pass_with_style_allowance"},
        "disposition": disposition,
        "reasons": reasons,
        "hard_reasons": hard_reasons,
        "soft_signals": soft_signals,
        "signal_families": [item["family"] for item in soft_signals],
        "style_allowances": style_allowances,
        "baseline": {
            "history_count": len(history),
            "short_sentence_ratio_boundary": round(ratio_boundary, 3),
        },
        "ratio": round(ratio, 3),
        "length_bounds": {
            "minimum_ratio": minimum_ratio, "maximum_ratio": maximum_ratio,
        },
        "diagnostics": report,
    }


def compact_review(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": review.get("score"),
        "dimensions": review.get("dimensions", {}),
        "hard_fail": bool(review.get("hard_fail")),
        "decision": review.get("decision", "revise"),
        "issues": [
            {
                "category": issue.get("category", "general"),
                "severity": issue.get("severity", "medium"),
                "evidence": issue.get("evidence", ""),
                "action": issue.get("action", ""),
            }
            for issue in review.get("issues", []) if isinstance(issue, dict)
        ],
    }


def compact_polish_findings(value: dict[str, Any], max_issues: int = 8) -> dict[str, Any]:
    reviews = [item for item in value.values() if isinstance(item, dict)]
    if "issues" in value:
        reviews.insert(0, value)
    issues = []
    seen = set()
    for review in reviews:
        for issue in review.get("issues", []):
            if not isinstance(issue, dict):
                continue
            key = (str(issue.get("category", "general")), str(issue.get("action", "")))
            if key in seen:
                continue
            seen.add(key)
            issues.append({
                "category": key[0],
                "severity": str(issue.get("severity", "medium")),
                "evidence": str(issue.get("evidence", ""))[:280],
                "action": key[1][:500],
            })
    issues.sort(key=lambda issue: SEVERITY_ORDER.get(issue["severity"], 2))
    reader = value.get("target_reader") if isinstance(value.get("target_reader"), dict) else value
    result = {"issues": issues[:max_issues]}
    if isinstance(reader.get("reader_signals"), dict):
        result["reader_signals"] = reader["reader_signals"]
    return result


_POLISH_GLOBAL_CATEGORIES = {
    "global", "overall", "structure", "story_structure", "plot_structure",
}
_POLISH_GLOBAL_MARKERS = re.compile(
    r"全文|全篇|全局|整体|通篇|\boverall\b|\bthroughout\b|"
    r"\bwhole\s+(?:story|manuscript)\b|\bacross\s+(?:the\s+)?(?:story|manuscript)\b",
    flags=re.IGNORECASE,
)
_POLISH_TERM_STOP = {
    "一个", "这个", "当前", "全文", "全篇", "整体", "问题", "内容", "正文",
    "段落", "故事", "情节", "人物", "读者", "需要", "应该", "避免", "保持",
    "加强", "调整", "修改", "修复", "处理", "表达", "部分", "进行", "没有",
    "with", "from", "that", "this", "into", "only", "story", "segment",
    "manuscript", "should", "revise", "improve", "strengthen", "preserve",
}


def _polish_match_terms(value: str) -> set[str]:
    terms = {
        item.lower() for item in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", value)
        if item.lower() not in _POLISH_TERM_STOP
    }
    for run in re.findall(r"[\u3400-\u9fff]{2,}", value):
        for width in range(2, min(6, len(run)) + 1):
            terms.update(
                run[index:index + width]
                for index in range(len(run) - width + 1)
                if run[index:index + width] not in _POLISH_TERM_STOP
            )
    return terms


def filter_polish_findings_for_segment(
    compacted: dict[str, Any], segment: str, max_issues: int = 4, max_global: int = 1,
) -> dict[str, Any]:
    """Return only findings that can guide this segment, plus one global priority."""
    segment_plain = re.sub(r"\s+", "", segment).lower()
    segment_terms = _polish_match_terms(segment)
    local: list[dict[str, Any]] = []
    global_issues: list[dict[str, Any]] = []
    for source in compacted.get("issues", []):
        if not isinstance(source, dict):
            continue
        issue = copy.deepcopy(source)
        evidence = str(issue.get("evidence") or "")
        action = str(issue.get("action") or "")
        evidence_plain = re.sub(r"\s+", "", evidence).lower()
        related = bool(
            (len(evidence_plain) >= 2 and evidence_plain in segment_plain)
            or segment_terms.intersection(_polish_match_terms(f"{evidence}\n{action}"))
        )
        if related:
            local.append(issue)
            continue
        category = str(issue.get("category") or "").strip().lower()
        severity = str(issue.get("severity") or "medium").strip().lower()
        if (
            severity in {"critical", "high"}
            and (
                category in _POLISH_GLOBAL_CATEGORIES
                or _POLISH_GLOBAL_MARKERS.search(f"{category}\n{evidence}\n{action}")
            )
        ):
            global_issues.append(issue)
    selected_global = global_issues[:max_global]
    local_limit = max(0, max_issues - len(selected_global))
    result = {"issues": [*local[:local_limit], *selected_global]}
    if isinstance(compacted.get("reader_signals"), dict):
        result["reader_signals"] = copy.deepcopy(compacted["reader_signals"])
    return result


def segment_map(parts: list[str], width: int = 320,
                event_assignments: list[dict] | None = None) -> list[dict[str, Any]]:
    assignments = {
        int(item.get("segment", 0)): item
        for item in (event_assignments or []) if isinstance(item, dict)
    }
    return [
        {
            "segment": index,
            "scene_id": f"scene-{index:02d}",
            **({
                "event_ids": assignments[index].get("event_ids", []),
                "handoff": assignments[index].get("handoff", ""),
            } if index in assignments else {}),
            "characters": len(part),
            "opening": part[:width],
            "ending": part[-width:],
        }
        for index, part in enumerate(parts, 1)
    ]


def normalize_revision_plan(value: dict[str, Any], segment_count: int,
                            max_target_ratio: float | None = None,
                            require_checks: bool = False,
                            defer_excess_targets: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Revision plan must be an object")
    facts = [item.strip() for item in value.get("global_facts", [])
             if isinstance(item, str) and item.strip()]
    checks = []
    for item in value.get("checks", []):
        if not isinstance(item, dict):
            continue
        raw_kind, text = item.get("kind"), item.get("value")
        kind = canonical_check_kind(raw_kind)
        if (kind in CHECK_KINDS and isinstance(text, str) and text.strip()
                and not (kind == "forbidden_text" and text.strip() in {'"', "'"})):
            check = {"kind": kind, "value": text.strip()}
            if str(raw_kind) != kind:
                check["raw_kind"] = raw_kind
            checks.append(check)
    tasks = []
    for item in value.get("tasks", []):
        if not isinstance(item, dict):
            continue
        instruction = item.get("instruction")
        segments = item.get("segments")
        if not isinstance(instruction, str) or not instruction.strip() or not isinstance(segments, list):
            continue
        valid_segments = sorted({number for value in segments
                                 if (number := parse_segment_number(value)) is not None
                                 and 1 <= number <= segment_count})
        if valid_segments:
            task = {"segments": valid_segments, "instruction": instruction.strip()}
            issue_ids = sorted({issue_id.strip() for issue_id in item.get("issue_ids", [])
                                if isinstance(issue_id, str) and issue_id.strip()})
            if issue_ids:
                task["issue_ids"] = issue_ids
            tasks.append(task)
    if not tasks:
        raise ValueError("Revision plan has no actionable task")
    ordered_targets = list(dict.fromkeys(
        number for task in tasks for number in task["segments"]
    ))
    target_segments = sorted(ordered_targets)
    deferred_segments: list[int] = []
    deferred_tasks: list[dict[str, Any]] = []
    if require_checks and not checks:
        raise ValueError("Structural revision plan requires a deterministic check")
    if max_target_ratio is not None:
        limit = max(1, math.ceil(segment_count * max_target_ratio))
        if len(target_segments) > limit:
            if not defer_excess_targets:
                raise ValueError(
                    f"Structural revision plan targets more than {max_target_ratio:.0%} of scenes"
                )
            selected = set(ordered_targets[:limit])
            deferred = set(ordered_targets[limit:])
            deferred_segments = sorted(deferred)
            current_tasks = []
            for task in tasks:
                current_segments = [number for number in task["segments"] if number in selected]
                later_segments = [number for number in task["segments"] if number in deferred]
                if current_segments:
                    current_tasks.append({**task, "segments": current_segments})
                if later_segments:
                    deferred_tasks.append({**task, "segments": later_segments})
            tasks = current_tasks
            target_segments = sorted(selected)
    plan = {
        "global_facts": facts,
        "checks": checks,
        "tasks": tasks,
        "target_segments": target_segments,
    }
    if defer_excess_targets:
        plan["deferred_segments"] = deferred_segments
        plan["deferred_tasks"] = deferred_tasks
    return plan


def align_revision_plan_targets(plan: dict[str, Any],
                                scenes: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    aligned = {
        **plan,
        "tasks": [{**task, "segments": list(task["segments"])} for task in plan["tasks"]],
    }
    corrections = []
    for check in aligned.get("checks", []):
        if check.get("kind") != "forbidden_text":
            continue
        value = check["value"]
        actual = [index for index, scene in enumerate(scenes, 1) if value in scene]
        if not actual:
            continue
        matching = [task for task in aligned["tasks"] if value in task["instruction"]]
        if matching:
            for task in matching:
                planned = list(task["segments"])
                if planned != actual:
                    corrections.append({
                        "value": value, "planned_segments": planned,
                        "actual_segments": actual,
                    })
                    task["segments"] = actual
        elif not set(actual).issubset(aligned.get("target_segments", [])):
            aligned["tasks"].append({
                "segments": actual,
                "instruction": f"Remove the forbidden literal exactly: {value}",
            })
            corrections.append({
                "value": value, "planned_segments": [], "actual_segments": actual,
            })
    aligned["target_segments"] = sorted({
        segment for task in aligned["tasks"] for segment in task["segments"]
    })
    return aligned, corrections


def remove_consecutive_duplicate_blocks(text: str) -> tuple[str, int]:
    paragraphs = text.split("\n\n")
    removals = 0
    index = 0
    while index < len(paragraphs):
        removed = False
        max_width = (len(paragraphs) - index) // 2
        for width in range(max_width, 1, -1):
            if paragraphs[index:index + width] == paragraphs[index + width:index + 2 * width]:
                del paragraphs[index + width:index + 2 * width]
                removals += 1
                removed = True
                break
        if not removed:
            index += 1
    return "\n\n".join(paragraphs), removals


def check_revision_constraints(text: str, plan: dict[str, Any]) -> list[str]:
    failures = []
    for check in plan.get("checks", []):
        value = check["value"]
        if check["kind"] == "required_text" and value not in text:
            failures.append(f"required text missing: {value}")
        elif check["kind"] == "forbidden_text" and value in text:
            failures.append(f"forbidden text remains: {value}")
    return failures


def check_source_local_constraints(source: str, candidate: str,
                                   plan: dict[str, Any]) -> list[str]:
    local_plan = {"checks": [
        check for check in plan.get("checks", [])
        if check.get("kind") == "forbidden_text" and check.get("value") in source
    ]}
    return check_revision_constraints(candidate, local_plan)
