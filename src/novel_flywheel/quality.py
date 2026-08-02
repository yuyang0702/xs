from typing import Any
import hashlib
import json

from novel_flywheel.context_policy import estimate_input_tokens


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
ALLOWED_ISSUE_STATUSES = {
    "resolved", "partially_resolved", "unresolved", "uncertain", "preserved",
}
LEGACY_ISSUE_STATUS_MAP = {
    "closed": "resolved", "open": "unresolved", "not_found": "unresolved",
}


def issue_severity_class(issue: dict) -> str:
    category = str(issue.get("category") or "general").lower()
    severity = str(issue.get("severity") or "medium").lower()
    if category in BLOCKING_CATEGORIES or (
        category == "general" and severity in {"critical", "blocking"}
    ):
        return "blocking"
    explicit = str(issue.get("severity_class") or "").lower()
    if explicit in {"blocking", "targeted_revision", "advisory"}:
        return explicit
    if category in TARGETED_CATEGORIES or severity == "critical":
        return "targeted_revision"
    return "advisory"


def issue_is_mandatory(issue: dict) -> bool:
    return issue_severity_class(issue) == "blocking"


def issue_is_resolved(issue: dict) -> bool:
    return str(issue.get("status") or "unresolved").lower() in {"resolved", "closed"}


def _canonical_issue_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in ALLOWED_ISSUE_STATUSES:
        return status
    return LEGACY_ISSUE_STATUS_MAP.get(status, "unresolved")


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


def review_evidence_batches(
    evidence: list[dict], token_limit: int, overlap: int = 1,
) -> list[list[dict]]:
    """Partition ordered evidence without sampling, retaining boundary overlap."""
    if token_limit <= 0 or overlap < 0:
        raise ValueError("review evidence batch limits must be positive")
    if not evidence:
        return []
    batches: list[list[dict]] = []
    start = 0
    while start < len(evidence):
        end = start
        while end < len(evidence):
            candidate = evidence[start:end + 1]
            tokens = estimate_input_tokens(
                json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
            )
            if tokens > token_limit and end > start:
                break
            end += 1
            if tokens > token_limit:
                break
        batch = evidence[start:end]
        batches.append(batch)
        if end >= len(evidence):
            break
        start = max(start + 1, end - min(overlap, len(batch) - 1))
    return batches


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
            "status": _canonical_issue_status(issue.get("status")),
            "repair_goal": issue.get("repair_goal") or issue.get("action", ""),
            "source": issue.get("source") or source,
        })
    return normalized


def reconcile_review_issues(
    review: dict,
    prior_issues: list[dict],
    reconciliations: list[dict],
    *,
    reviewed_at: str = "",
) -> dict:
    """Carry every prior issue into a review unless it is explicitly reconciled."""
    result = dict(review)
    prior = issue_ledger(prior_issues)
    current = issue_ledger(
        review.get("issues", []) if isinstance(review.get("issues", []), list) else []
    )
    prior_by_id = {str(item["issue_id"]): item for item in prior}
    prior_ids = {str(item["issue_id"]) for item in prior}
    by_id: dict[str, list[dict]] = {}
    for item in reconciliations if isinstance(reconciliations, list) else []:
        if not isinstance(item, dict):
            continue
        by_id.setdefault(str(item.get("issue_id") or ""), []).append(item)

    missing = sorted(issue_id for issue_id in prior_ids if not by_id.get(issue_id))
    duplicates = sorted(
        issue_id for issue_id in prior_ids if len(by_id.get(issue_id, [])) > 1
    )
    unexpected = sorted(issue_id for issue_id in by_id if issue_id not in prior_ids)
    invalid = sorted(
        issue_id
        for issue_id in prior_ids
        if len(by_id.get(issue_id, [])) == 1
        and (
            str(by_id[issue_id][0].get("status") or "").strip().lower()
            not in ALLOWED_ISSUE_STATUSES
            or (
                str(by_id[issue_id][0].get("status") or "").strip().lower()
                == "resolved"
                and not str(
                    by_id[issue_id][0].get("evidence")
                    or by_id[issue_id][0].get("reconciliation_evidence")
                    or ""
                ).strip()
            )
            or (
                str(by_id[issue_id][0].get("status") or "").strip().lower()
                == "preserved"
                and issue_is_mandatory(prior_by_id[issue_id])
            )
        )
    )
    complete = not (missing or duplicates or unexpected or invalid)

    current_by_id = {str(item["issue_id"]): item for item in current}
    merged: list[dict] = []
    for prior_item in prior:
        issue_id = str(prior_item["issue_id"])
        item = {**prior_item, **current_by_id.pop(issue_id, {})}
        if complete:
            reconciliation = by_id[issue_id][0]
            item["status"] = str(reconciliation["status"]).strip().lower()
            item["reconciliation_evidence"] = str(
                reconciliation.get("evidence")
                or reconciliation.get("reconciliation_evidence")
                or ""
            )
            if reviewed_at:
                item["reconciled_at"] = reviewed_at
        else:
            item["status"] = prior_item["status"]
        merged.append(item)
    merged.extend(current_by_id.values())

    result["issues"] = merged
    result["issue_reconciliation_complete"] = complete
    if missing:
        result["missing_reconciliation_issue_ids"] = missing
    if duplicates:
        result["duplicate_reconciliation_issue_ids"] = duplicates
    if unexpected:
        result["unexpected_reconciliation_issue_ids"] = unexpected
    if invalid:
        result["invalid_reconciliation_issue_ids"] = invalid
    return result


def update_issue_status(ledger: list[dict], issue_id: str, status: str,
                        evidence: str = "") -> list[dict]:
    if status not in ALLOWED_ISSUE_STATUSES:
        raise ValueError("问题状态无效")
    result = []
    for item in ledger:
        if item.get("issue_id") != issue_id:
            result.append(dict(item))
            continue
        if issue_is_mandatory(item) and status != "resolved":
            raise ValueError("必须处理的问题只有解决后才能更新状态")
        result.append({
            **item, "status": status, "reconciliation_evidence": evidence,
        })
    return result


def apply_evidence_gate(review: dict, evidence: dict) -> tuple[dict, list[str]]:
    """Apply deterministic coverage and unresolved-issue caps to a model review."""
    result = dict(review)
    reasons = []
    reconciliations = evidence.get("reconciliations") or []
    reconciliation_ids = [item.get("issue_id") for item in reconciliations]
    reconciled_ids = set(reconciliation_ids)
    prior_ids = set(evidence.get("prior_issue_ids") or [])
    prior_by_id = {
        str(item.get("issue_id")): item
        for item in evidence.get("prior_issues", [])
        if isinstance(item, dict) and item.get("issue_id")
    }
    if prior_ids - reconciled_ids:
        reasons.append("missing_issue_reconciliation")
    if (
        len(reconciliation_ids) != len(reconciled_ids)
        or bool(reconciled_ids - prior_ids)
        or any(
            str(item.get("status") or "").strip().lower()
            not in ALLOWED_ISSUE_STATUSES
            or (
                str(item.get("status") or "").strip().lower() == "resolved"
                and not str(
                    item.get("evidence") or item.get("reconciliation_evidence") or ""
                ).strip()
            )
            for item in reconciliations
        )
    ):
        reasons.append("invalid_issue_reconciliation")
    if (evidence.get("coverage", 0) < 1
            or evidence.get("reviewed_windows", 0) != evidence.get("window_count", 0)):
        reasons.append("incomplete_manuscript_coverage")
    if evidence.get("evidence_count", 0) < evidence.get("window_count", 0):
        reasons.append("insufficient_review_evidence")
    authoritative_reconciliations = [
        {
            **item,
            **{
                key: prior_by_id[str(item.get("issue_id"))][key]
                for key in ("category", "severity", "severity_class")
                if str(item.get("issue_id")) in prior_by_id
                and key in prior_by_id[str(item.get("issue_id"))]
            },
        }
        for item in reconciliations
    ]
    unresolved = [
        item for item in authoritative_reconciliations
        if _canonical_issue_status(item.get("status")) in {
            "unresolved", "partially_resolved", "uncertain",
        }
    ]
    if any(issue_is_mandatory(item) and not issue_is_resolved(item)
           for item in authoritative_reconciliations):
        reasons.append("unresolved_mandatory_issue")
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
                "evidence": "", "action": value, "status": "unresolved",
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
            "status": _canonical_issue_status(value.get("status")),
        }
        if any(not isinstance(issue[key], str) for key in (
            "category", "severity", "evidence", "action",
        )):
            raise ValueError("Each review issue field must be text")
        issue["severity_class"] = issue_severity_class(issue)
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
    blockers = [
        item for item in result["issues"]
        if issue_is_mandatory(item) and not issue_is_resolved(item)
    ]
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
        issue_is_mandatory(issue) and not issue_is_resolved(issue)
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
