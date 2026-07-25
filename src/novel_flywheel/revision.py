import re
import math
from typing import Any

from novel_flywheel.prose_quality import analyze_prose


CHECK_KINDS = {"required_text", "forbidden_text"}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
CJK = r"\u3400-\u9fff"


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
    if (source_metrics["short_sentence_run"] >= 3
            and candidate_metrics["short_sentence_run"] >= 3):
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
                            require_checks: bool = False) -> dict[str, Any]:
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
            tasks.append({"segments": valid_segments, "instruction": instruction.strip()})
    if not tasks:
        raise ValueError("Revision plan has no actionable task")
    target_segments = sorted({number for task in tasks for number in task["segments"]})
    if require_checks and not checks:
        raise ValueError("Structural revision plan requires a deterministic check")
    if max_target_ratio is not None:
        limit = max(1, math.ceil(segment_count * max_target_ratio))
        if len(target_segments) > limit:
            raise ValueError(
                f"Structural revision plan targets more than {max_target_ratio:.0%} of scenes"
            )
    return {
        "global_facts": facts,
        "checks": checks,
        "tasks": tasks,
        "target_segments": target_segments,
    }


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
