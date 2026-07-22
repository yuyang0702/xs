from typing import Any


WEIGHTS = {"commercial": 0.45, "story": 0.35, "prose": 0.20}
MINIMUMS = {"commercial": 75.0, "story": 70.0, "prose": 65.0}
KEY_MARKERS = (
    "开篇", "前三章", "付费", "高潮", "结局", "关键", "揭晓", "卷末",
    "opening", "paid", "climax", "ending", "reveal", "volume end",
)


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
            "category": value.get("category", "general"),
            "severity": value.get("severity", "medium"),
            "evidence": value.get("evidence", ""),
            "action": value.get("action", ""),
        }
        if any(not isinstance(item, str) for item in issue.values()):
            raise ValueError("Each review issue field must be text")
        normalized.append(issue)
    return normalized


def normalize_review(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Review must be a JSON object")
    result = dict(value)
    dimensions = result.get("dimensions")
    if dimensions is None:
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
    result["hard_fail"] = bool(result.get("hard_fail", False))
    decision = result.get("decision", "revise")
    if decision not in {"pass", "revise", "rewrite"}:
        raise ValueError("Review decision must be pass, revise, or rewrite")
    result["decision"] = decision
    result["issues"] = _issues(result.get("issues", []))
    return result


def quality_gate(review: dict) -> tuple[bool, list[str]]:
    reasons = []
    if review["score"] < 80:
        reasons.append("overall_below_80")
    for name, minimum in MINIMUMS.items():
        if review["dimensions"][name] < minimum:
            reasons.append(f"{name}_below_{int(minimum)}")
    if review.get("hard_fail"):
        reasons.append("hard_fail")
    return not reasons, reasons


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
    labels = (["OPENING", "PAID CUTOFF", "CLIMAX", "ENDING"] if mode == "short"
              else ["OPENING", "MIDDLE", "ENDING"])
    headers = [f"--- {label} ---\n" for label in labels]
    separators_size = 2 * (len(labels) - 1)
    content_budget = max(len(labels), limit - sum(map(len, headers)) - separators_size)
    width = max(1, content_budget // len(labels))
    last = max(0, len(text) - width)
    points = ([0, int(len(text) * 0.35), int(len(text) * 0.75), last] if mode == "short"
              else [0, int(len(text) * 0.5), last])
    parts = []
    for header, point in zip(headers, points):
        start = min(point, last)
        parts.append(header + text[start:start + width])
    return "\n\n".join(parts)[:limit]

