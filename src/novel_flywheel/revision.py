import copy
import hashlib
import re
import math
from typing import Any

from novel_flywheel.prose_quality import analyze_prose


CHECK_KINDS = {"required_text", "forbidden_text"}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
CJK = r"\u3400-\u9fff"
PATCH_OPERATIONS = {"replace", "insert_before", "insert_after"}
REPAIR_KINDS = {"semantic", "mechanical"}
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
    manuscript_hash = hashlib.sha256(manuscript.encode("utf-8")).hexdigest()
    if value.get("manuscript_hash") != manuscript_hash:
        raise ValueError("Repair contract manuscript_hash is stale")
    groups = value.get("groups")
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
        kind = group.get("kind", "semantic")
        if kind not in REPAIR_KINDS:
            raise ValueError("Repair contract group kind is unsupported")
        if not group.get("requires_user_confirmation"):
            raise ValueError("Repair contract group requires user confirmation")
        patches = group.get("patches")
        if not isinstance(patches, list) or not patches:
            raise ValueError("Repair contract group must contain a patch")
        for patch in patches:
            if not isinstance(patch, dict) or patch.get("operation") not in PATCH_OPERATIONS:
                raise ValueError("Repair contract patch operation is unsupported")
            old = patch.get("old_text")
            if not isinstance(old, str) or not old or manuscript.count(old) != 1:
                raise ValueError("Repair contract old_text must be unique")
    return copy.deepcopy(value)


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


def assess_polish_candidate(source: str, candidate: str,
                            required_literals: list[str] | None = None,
                            minimum_ratio: float = 0.70,
                            maximum_ratio: float = 1.60) -> dict[str, Any]:
    candidate = candidate.strip()
    ratio = len(candidate) / max(1, len(source.strip()))
    report = analyze_prose(candidate)
    reasons = []
    if len(source.strip()) >= 200 and (ratio < minimum_ratio or ratio > maximum_ratio):
        reasons.append("length_ratio")
    if report["blocking_count"]:
        reasons.append("production_text")
    for literal in required_literals or []:
        if literal and literal in source and literal not in candidate:
            reasons.append(f"missing_literal:{literal}")
    source_report = analyze_prose(source)
    if report["targeted_count"] > source_report["targeted_count"] + 2:
        reasons.append("style_regression")
    source_metrics = source_report["metrics"]
    candidate_metrics = report["metrics"]
    source_codes = {item["code"] for item in source_report["findings"]}
    candidate_codes = {item["code"] for item in report["findings"]}
    if "timestamp_scene_fragment" in source_codes & candidate_codes:
        reasons.append("timestamp_scene_fragment_not_improved")
    if (source_metrics["dialogue_turn_run"] >= 4
            and candidate_metrics["dialogue_turn_run"] >= 4):
        reasons.append("dialogue_ping_pong_not_improved")
    if source_metrics["short_sentence_run"] >= 4:
        rhythm_improved = (
            candidate_metrics["short_sentence_run"]
            <= max(3, source_metrics["short_sentence_run"] - 2)
            or candidate_metrics["short_sentence_ratio"]
            <= source_metrics["short_sentence_ratio"] - 0.05
        )
        if not rhythm_improved:
            reasons.append("sentence_rhythm_not_improved")
    if re.search(r"[。！？.!?]", source) and (
        candidate_metrics["short_sentence_run"] > max(3, source_metrics["short_sentence_run"])
        or candidate_metrics["short_sentence_ratio"]
        > source_metrics["short_sentence_ratio"] + 0.05
        or candidate_metrics["one_sentence_paragraph_run"]
        > max(2, source_metrics["one_sentence_paragraph_run"])
    ):
        reasons.append("sentence_rhythm_regression")
    return {
        "accepted": not reasons, "reasons": reasons, "ratio": round(ratio, 3),
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


def segment_map(parts: list[str], width: int = 320) -> list[dict[str, Any]]:
    return [
        {
            "segment": index,
            "scene_id": f"scene-{index:02d}",
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
        kind, text = item.get("kind"), item.get("value")
        if (kind in CHECK_KINDS and isinstance(text, str) and text.strip()
                and not (kind == "forbidden_text" and text.strip() in {'"', "'"})):
            checks.append({"kind": kind, "value": text.strip()})
    tasks = []
    for item in value.get("tasks", []):
        if not isinstance(item, dict):
            continue
        instruction = item.get("instruction")
        segments = item.get("segments")
        if not isinstance(instruction, str) or not instruction.strip() or not isinstance(segments, list):
            continue
        valid_segments = sorted({number for number in segments
                                 if isinstance(number, int) and 1 <= number <= segment_count})
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
