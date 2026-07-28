from typing import Any
import hashlib
import json


WEIGHTS = {"commercial": 0.45, "story": 0.35, "prose": 0.20}
MINIMUMS = {"commercial": 75.0, "story": 70.0, "prose": 65.0}
KEY_MARKERS = (
    "开篇", "前三章", "付费", "高潮", "结局", "关键", "揭晓", "卷末",
    "opening", "paid", "climax", "ending", "reveal", "volume end",
)
BLOCKING_CATEGORIES = {
    "compliance", "canon", "canon_conflict", "manuscript_corruption",
    "production_text", "missing_required_content", "safety",
}
TARGETED_CATEGORIES = {
    "prose", "style", "dialogue", "pacing", "commercial", "commercial_pull",
    "historical_realism", "procedural_realism", "ending", "ending_payoff",
    "format", "character_arc", "story", "story_structure", "logic_continuity",
}


def review_windows(text: str, target: int = 5000, overlap: int = 400) -> list[dict]:
    """Return paragraph-aligned, overlapping windows that cover the complete text."""
    if not text:
        return []
    windows = []
    start = 0
    while start < len(text):
        wanted = min(len(text), start + target)
        end = wanted
        if wanted < len(text):
            boundary = text.rfind("\n\n", start + target // 2, wanted + 1)
            if boundary > start:
                end = boundary
        windows.append({"index": len(windows) + 1, "start": start, "end": end,
                        "text": text[start:end]})
        if end == len(text):
            break
        next_start = max(start + 1, end - overlap)
        boundary = text.find("\n\n", next_start, end)
        start = boundary + 2 if boundary >= 0 else next_start
    return windows


def issue_ledger(issues: list[dict], source: str = "final_review") -> list[dict]:
    normalized = []
    for issue in issues:
        identity = {
            key: str(issue.get(key, "")).strip()
            for key in ("category", "severity", "evidence", "action")
        }
        digest = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        normalized.append({
            **issue,
            "issue_id": issue.get("issue_id") or f"issue-{digest}",
            "status": issue.get("status") or "open",
            "repair_goal": issue.get("repair_goal") or issue.get("action", ""),
            "source": issue.get("source") or source,
        })
    return normalized


def apply_evidence_gate(review: dict, evidence: dict) -> tuple[dict, list[str]]:
    """Apply deterministic coverage and unresolved-issue caps to a model review."""
    result = dict(review)
    reasons = []
    reconciliations = evidence.get("reconciliations") or []
    reconciled_ids = {item.get("issue_id") for item in reconciliations}
    prior_ids = set(evidence.get("prior_issue_ids") or [])
    if prior_ids - reconciled_ids:
        reasons.append("missing_issue_reconciliation")
    if (evidence.get("coverage", 0) < 1
            or evidence.get("reviewed_windows", 0) != evidence.get("window_count", 0)):
        reasons.append("incomplete_manuscript_coverage")
    if evidence.get("evidence_count", 0) < evidence.get("window_count", 0):
        reasons.append("insufficient_review_evidence")
    unresolved = [item for item in reconciliations
                  if item.get("status") in {"unresolved", "partially_resolved", "not_found"}]
    if any(str(item.get("severity", "")).lower() in {"major", "critical", "blocking"}
           for item in unresolved):
        reasons.append("unresolved_major_issue")
    elif len([item for item in unresolved
              if str(item.get("severity", "")).lower() in {"medium", "moderate"}]) >= 2:
        reasons.append("multiple_unresolved_moderate_issues")
    if reasons:
        cap = 74 if any(reason != "multiple_unresolved_moderate_issues" for reason in reasons) else 79
        result["score"] = min(result["score"], cap)
        result["decision"] = "revise"
    result["evidence_gate_reasons"] = reasons
    return result, reasons


def _score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Quality dimensions must be between 0 and 100")
    score = float(value)
    if not 0 <= score <= 100:
        raise ValueError("Quality dimensions must be between 0 and 100")
    return score


def _issues(values: Any) -> list[dict[str, str]]:
    if not isinstance(values, list):
        raise ValueError("Review issues must be a list")
    normalized = []
    for value in values:
        if isinstance(value, str):
            normalized.append({
                "category": "general", "severity": "medium",
                "evidence": "", "action": value,
            })
            continue
        if not isinstance(value, dict):
            raise ValueError("Each review issue must be text or an object")
        issue = {
            **value,
            "category": value.get("category", "general"),
            "severity": value.get("severity", "medium"),
            "evidence": value.get("evidence", ""),
            "action": value.get("action", ""),
        }
        if any(not isinstance(issue[key], str) for key in (
            "category", "severity", "evidence", "action",
        )):
            raise ValueError("Each review issue field must be text")
        category = issue["category"].lower()
        if category in BLOCKING_CATEGORIES or (
            category == "general" and issue["severity"].lower() == "critical"
        ):
            issue["severity_class"] = "blocking"
        elif category in TARGETED_CATEGORIES or issue["severity"].lower() == "critical":
            issue["severity_class"] = "targeted_revision"
        else:
            issue["severity_class"] = "advisory"
        normalized.append(issue)
    return normalized


def normalize_review(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Review must be a JSON object")
    result = dict(value)
    dimensions = result.get("dimensions")
    if dimensions is None:
        if all(name in result for name in WEIGHTS):
            normalized = {name: _score(result[name]) for name in WEIGHTS}
        else:
            legacy = _score(result.get("score"))
            normalized = {name: legacy for name in WEIGHTS}
    else:
        if not isinstance(dimensions, dict):
            raise ValueError("Review dimensions must be an object")
        try:
            normalized = {name: _score(dimensions[name]) for name in WEIGHTS}
        except KeyError as exc:
            raise ValueError(f"Review dimension is missing: {exc.args[0]}") from exc
    result["dimensions"] = normalized
    result["score"] = round(sum(normalized[name] * WEIGHTS[name] for name in WEIGHTS), 2)
    model_hard_fail = bool(result.get("hard_fail", False))
    result["hard_fail"] = model_hard_fail
    decision = result.get("decision", "revise")
    if decision not in {"pass", "revise", "rewrite"}:
        raise ValueError("Review decision must be pass, revise, or rewrite")
    result["decision"] = decision
    result["issues"] = _issues(result.get("issues", []))
    blockers = [item for item in result["issues"] if item.get("severity_class") == "blocking"]
    categorized = [item for item in result["issues"] if "severity_class" in item]
    result["hard_fail"] = bool(blockers) or (model_hard_fail and not categorized)
    if result["decision"] == "rewrite" and categorized and not blockers:
        result["decision"] = "revise"
    return result


def quality_outcome(review: dict) -> tuple[str, list[str]]:
    reasons = []
    if review["score"] < 75:
        reasons.append("overall_below_75")
    for name, minimum in MINIMUMS.items():
        if review["dimensions"][name] < minimum:
            reasons.append(f"{name}_below_{int(minimum)}")
    if review.get("hard_fail"):
        reasons.append("hard_fail")
    if review.get("decision") == "rewrite":
        reasons.append("rewrite")
    if any(
        issue.get("severity_class") == "blocking"
        or ("severity_class" not in issue and issue.get("severity", "").lower() == "critical")
        for issue in review["issues"]
    ):
        reasons.append("critical")
    if reasons:
        return "failed", reasons
    return ("passed" if review["score"] >= 80 else "conditional_pass"), []


def quality_gate(review: dict) -> tuple[bool, list[str]]:
    outcome, reasons = quality_outcome(review)
    return outcome != "failed", reasons


def select_route(mode: str, chapter_number: int | None, chapter_goal: str,
                 volume_end: bool, review: dict | None = None) -> dict:
    reasons = []
    if mode == "short":
        reasons.append("short_story")
    if chapter_number is not None and chapter_number <= 3:
        reasons.append("opening_chapter")
    if volume_end:
        reasons.append("volume_end")
    normalized_goal = chapter_goal.lower()
    if any(marker in normalized_goal for marker in KEY_MARKERS):
        reasons.append("key_goal")
    if review and (review.get("decision") == "rewrite"
                   or review["dimensions"]["commercial"] < 60):
        reasons.append("severe_first_review")
    enhanced = bool(reasons)
    return {
        "enhanced": enhanced,
        "max_corrections": 2 if enhanced else 1,
        "reasons": reasons or ["ordinary_chapter"],
    }


def reader_sample(text: str, mode: str, limit: int = 9000) -> str:
    text = text.replace("<!-- NOVEL_FLYWHEEL_SEGMENT -->", "")
    notice = (
        "NOTE: These are non-contiguous review excerpts. Excerpt and label boundaries are not "
        "manuscript or paywall boundaries; never report them as truncation.\n\n"
    )
    labels = (["OPENING", "PAID REGION", "CLIMAX", "ENDING"] if mode == "short"
              else ["OPENING", "MIDDLE", "ENDING"])
    headers = [f"--- {label} ---\n" for label in labels]
    separators_size = 2 * (len(labels) - 1)
    content_budget = max(
        len(labels), limit - len(notice) - sum(map(len, headers)) - separators_size,
    )
    width = max(1, content_budget // len(labels))
    points = ([0, int(len(text) * 0.35), int(len(text) * 0.75), len(text)] if mode == "short"
              else [0, int(len(text) * 0.5), len(text)])
    parts = []
    for index, (header, point) in enumerate(zip(headers, points)):
        if index == 0:
            start = 0
        elif index == len(points) - 1:
            target = max(0, len(text) - width)
            boundary = text.find("\n\n", target)
            start = boundary + 2 if boundary >= 0 else target
        else:
            boundary = text.rfind("\n\n", 0, point + 1)
            start = boundary + 2 if boundary >= 0 else min(point, max(0, len(text) - width))
        if index == len(points) - 1:
            end = len(text)
        else:
            target = min(len(text), start + width)
            boundary = text.rfind("\n\n", start, target + 1)
            end = boundary if boundary > start else target
        parts.append(header + text[start:end].strip())
    return (notice + "\n\n".join(parts))[:limit]
