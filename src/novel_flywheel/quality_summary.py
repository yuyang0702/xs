from __future__ import annotations

import hashlib
import re
from typing import Any

from novel_flywheel.quality_profiles import profile_for_project
from novel_flywheel.quality import issue_is_mandatory, issue_is_resolved


HAN_CHARACTER = re.compile(r"[\u3400-\u9fff]")
INTERNAL_MARKER = re.compile(r"<!--\s*NOVEL_FLYWHEEL_[^>]*-->", re.IGNORECASE)
MARKDOWN_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+.*$")
SEVERITY_ORDER = {
    "critical": 4, "blocking": 4, "high": 3, "major": 3,
    "medium": 2, "low": 1,
}
STATUS_ORDER = {
    "unresolved": 3, "open": 3, "partially_resolved": 2,
    "uncertain": 2, "resolved": 1, "closed": 1, "preserved": 1,
}
STATUS_LABELS = {
    "resolved": "已解决",
    "partially_resolved": "部分解决",
    "unresolved": "未解决",
    "uncertain": "待确认",
    "preserved": "保留原写法",
    "open": "未解决（旧记录）",
    "closed": "已解决（旧记录）",
    "not_found": "未找到证据（旧记录）",
}
ACTIVE_ISSUE_STATUSES = {
    "unresolved", "open", "not_found", "partially_resolved", "uncertain",
}
CATEGORY_LABELS = {
    "commercial": "阅读吸引力",
    "commercial_pull": "阅读吸引力",
    "story": "人物与情节逻辑",
    "story_structure": "故事结构",
    "logic_continuity": "人物与情节逻辑",
    "character_arc": "人物选择与变化",
    "ending": "结尾兑现",
    "ending_payoff": "结尾兑现",
    "prose": "文字表达",
    "style": "文字表达",
    "dialogue": "对白与场景",
    "pacing": "剧情节奏",
    "production_text": "正文完整性",
    "manuscript_corruption": "正文完整性",
    "canon": "设定一致性",
    "compliance": "投稿硬性要求",
}


def _issue_handling(category: str) -> tuple[str, str, str]:
    if category in {"production_text", "manuscript_corruption"}:
        return "mechanical", "本地程序先处理", "本地扫描或终审发现"
    if category in {"canon", "compliance"}:
        return "confirmation", "需要你确认", "项目设定或投稿要求"
    if category in {
        "story", "story_structure", "logic_continuity", "character_arc",
        "ending", "ending_payoff", "pacing",
    }:
        return "structural", "规划模型定位，精修模型修改", "终审发现"
    return "polish", "精修模型处理", "终审发现"


def effective_han_characters(text: str) -> int:
    cleaned = INTERNAL_MARKER.sub("", text)
    cleaned = MARKDOWN_HEADING.sub("", cleaned)
    return len(HAN_CHARACTER.findall(cleaned))


def merge_quality_issues(report: dict, review: dict | None = None) -> list[dict]:
    review = review or _current_review(report)
    groups: dict[str, dict] = {}
    for index, issue in enumerate(review.get("issues", [])):
        if not isinstance(issue, dict):
            continue
        category = str(issue.get("category") or "general")
        action = str(issue.get("repair_goal") or issue.get("action") or "请复核该问题")
        issue_id = str(issue.get("issue_id") or "")
        grouping = issue_id or hashlib.sha256(
            f"{category}|{_normalized(action)}".encode("utf-8"),
        ).hexdigest()[:16]
        severity = str(issue.get("severity_class") or issue.get("severity") or "medium").lower()
        status = str(issue.get("status") or "unresolved").lower()
        repair_mode, handling_label, source_label = _issue_handling(category)
        item = groups.setdefault(grouping, {
            "issue_id": issue_id or f"quality-{grouping}",
            "title": CATEGORY_LABELS.get(category, "正文问题"),
            "category": category,
            "severity": severity,
            "status": status,
            "status_label": STATUS_LABELS.get(status, "状态未知"),
            "mandatory": issue_is_mandatory(issue),
            "repair_direction": action,
            "effect": str(issue.get("effect") or "可能影响阅读理解或剧情可信度"),
            "repair_mode": repair_mode,
            "handling_label": handling_label,
            "source_label": source_label,
            "reconciliation_evidence": str(
                issue.get("reconciliation_evidence") or ""
            ),
            "reconciled_at": str(issue.get("reconciled_at") or ""),
            "evidence": [],
        })
        if SEVERITY_ORDER.get(severity, 2) > SEVERITY_ORDER.get(item["severity"], 2):
            item["severity"] = severity
        if STATUS_ORDER.get(status, 3) > STATUS_ORDER.get(item["status"], 3):
            item["status"] = status
            item["status_label"] = STATUS_LABELS.get(status, "状态未知")
        item["mandatory"] = item["mandatory"] or issue_is_mandatory(issue)
        if issue.get("reconciliation_evidence"):
            item["reconciliation_evidence"] = str(issue["reconciliation_evidence"])
        if issue.get("reconciled_at"):
            item["reconciled_at"] = str(issue["reconciled_at"])
        evidence = {
            "location": str(issue.get("location") or "正文相关位置"),
            "excerpt": str(
                issue.get("reconciliation_evidence")
                or issue.get("evidence")
                or "未提供原文证据"
            ),
            "window": issue.get("window"),
        }
        if evidence not in item["evidence"]:
            item["evidence"].append(evidence)
    return sorted(groups.values(), key=lambda item: (
        -STATUS_ORDER.get(item["status"], 3),
        -SEVERITY_ORDER.get(item["severity"], 2),
        item["title"],
    ))


def build_quality_summary(project: Any, run_id: str, text: str, report: dict,
                          checkpoint: dict | None) -> dict:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    active_profile = profile_for_project(project)
    latest_review = _current_review(report)
    checkpoint_review = (checkpoint or {}).get("review")
    review = (
        checkpoint_review
        if checkpoint and checkpoint.get("manuscript_hash") == digest
        and isinstance(checkpoint_review, dict)
        else latest_review
    )
    current_profile = str(
        review.get("scoring_profile_id") or report.get("scoring_profile_id") or "legacy-v1"
    )
    best_profile = str((checkpoint or {}).get("scoring_profile_id") or current_profile)
    current_score = review.get("score")
    best_score = (checkpoint or {}).get("score", report.get("best_score"))
    review_matches_checkpoint = bool(
        checkpoint and checkpoint.get("manuscript_hash") == digest
    )
    if review_matches_checkpoint:
        bound_judge = (checkpoint or {}).get("judge_signature")
        if not bound_judge and isinstance(checkpoint_review, dict):
            bound_judge = checkpoint_review.get("judge_signature")
        if not bound_judge and report.get("terminal_reviewed_hash") == digest:
            bound_judge = latest_review.get("judge_signature") or report.get("judge_signature")
    else:
        bound_judge = review.get("judge_signature") or report.get("judge_signature")
    judge_signature = str(bound_judge or "legacy-unknown")
    judge_label = (
        "旧记录未保存模型名称"
        if judge_signature in {"", "legacy-unknown", "unknown", "none"}
        else judge_signature
    )
    comparable = bool(
        checkpoint
        and best_profile == current_profile == active_profile
        and (checkpoint.get("judge_signature") in {
            None, "legacy-unknown", review.get("judge_signature"),
        })
    )
    current_count = effective_han_characters(text)
    target = int(getattr(project, "metadata", {}).get("target_words") or 0)
    minimum, maximum = _target_range(project, target)
    word_count = {
        "label": "有效正文汉字",
        "current": current_count,
        "minimum": minimum,
        "maximum": maximum,
        "remaining": max(0, minimum - current_count),
        "within_target": minimum <= current_count <= maximum,
    }
    reasons = []
    if active_profile == "zhihu-short-v2":
        if report.get("status") != "passed":
            reasons.append("当前候选稿还没有通过终审")
        if report.get("terminal_reviewed_hash") != digest:
            reasons.append("终审结果与当前候选稿内容不一致，需要重新终审")
        if active_profile != current_profile:
            reasons.append("当前候选稿还没有按正在使用的评分标准完成终审")
        if not word_count["within_target"]:
            reasons.append(
                f"有效正文汉字需保持在 {minimum:,}～{maximum:,} 字"
            )
    all_issues = merge_quality_issues(report, review)
    issues = [
        item for item in all_issues if item["status"] in ACTIVE_ISSUE_STATUSES
    ]
    resolved_issues = [
        item for item in all_issues if item["status"] not in ACTIVE_ISSUE_STATUSES
    ]
    if active_profile == "zhihu-short-v2" and any(
        item["mandatory"] and not issue_is_resolved(item) for item in issues
    ):
        reasons.append("仍有必须解决的正文问题")
    can_set_formal = not reasons
    next_action = (
        "可以设为正式稿" if can_set_formal else
        "补足正文篇幅" if current_count < minimum else
        "继续修改候选稿"
    )
    return {
        "profile": {
            "id": active_profile,
            "label": "知乎短篇评分 v2" if active_profile == "zhihu-short-v2" else "旧版评分标准",
            "current_review_profile_id": current_profile,
            "judge_signature": judge_signature,
            "judge_label": judge_label,
        },
        "manuscript_state": {
            "current": "protected_best" if checkpoint and checkpoint.get("manuscript_hash") == digest
            else "candidate",
            "protected_best": bool(checkpoint and checkpoint.get("manuscript_hash") == digest),
            "run_id": run_id,
            "manuscript_hash": digest,
        },
        "score": {
            "current": current_score,
            "best": best_score,
            "dimensions": review.get("dimensions", {}),
            "dimension_labels": review.get("dimension_labels", {}),
            "criteria": review.get("criteria", {}),
            "criterion_labels": review.get("criterion_labels", {}),
            "criterion_evidence": review.get("criterion_evidence", {}),
            "comparable": comparable,
            "comparison_message": _comparison_message(
                current_score, best_score, comparable,
            ),
        },
        "issues": issues,
        "resolved_issues": resolved_issues,
        "issue_counts": {
            "total": len(issues),
            "mandatory": sum(
                item["mandatory"] and not issue_is_resolved(item)
                for item in issues
            ),
            "unresolved": sum(
                not issue_is_resolved(item) and item["status"] != "preserved"
                for item in issues
            ),
            "historical": len(resolved_issues),
        },
        "word_count": word_count,
        "publication_authority": {
            "can_set_formal": can_set_formal,
            "can_generate_package": False,
            "blocking_reasons": reasons,
        },
        "next_action": next_action,
    }


def _current_review(report: dict) -> dict:
    attempts = report.get("final_attempts")
    if isinstance(attempts, list) and attempts:
        for item in reversed(attempts):
            if isinstance(item, dict) and isinstance(item.get("review"), dict):
                return item["review"]
    for key in ("review", "final_review", "initial_review"):
        if isinstance(report.get(key), dict):
            return report[key]
    return {}


def _target_range(project: Any, target: int) -> tuple[int, int]:
    if (getattr(project, "mode", None) == "short"
            and getattr(project, "metadata", {}).get("platform_profile_id")
            == "zhihu-salt-short"):
        return int(target * 0.9), int(target * 1.1)
    return max(0, target), max(0, target)


def _normalized(value: str) -> str:
    return re.sub(r"[^\u3400-\u9fffa-z0-9]+", "", value.lower())


def _comparison_message(current: Any, best: Any, comparable: bool) -> str:
    if current is None or best is None:
        return "等待建立可比较的评分记录"
    if not comparable:
        return "评分标准或终审模型不同，本次分数不能与历史分数直接比较"
    delta = round(float(current) - float(best), 2)
    if delta >= 2:
        return f"本轮比受保护最佳稿提高 {delta:g} 分"
    if delta <= -2:
        return f"本轮比受保护最佳稿低 {abs(delta):g} 分，继续保留最佳稿"
    return "分差不足 2 分，视为同一水平并继续保留原最佳稿"
