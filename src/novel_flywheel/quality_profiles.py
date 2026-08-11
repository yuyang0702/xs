from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_flywheel.quality import (
    issue_is_mandatory,
    issue_is_resolved,
    quality_outcome,
    unresolved_major_issue_ids,
)


@dataclass(frozen=True)
class QualityProfile:
    id: str
    labels: dict[str, str]
    dimension_weights: dict[str, float]
    criterion_dimensions: dict[str, str]
    criterion_weights: dict[str, float]
    pass_total: float
    conditional_total: float
    pass_minimums: dict[str, float]
    conditional_minimums: dict[str, float]


ZHihu_SHORT_V2 = QualityProfile(
    id="zhihu-short-v2",
    labels={
        "commercial": "商业吸引力",
        "story": "故事质量",
        "prose": "文笔质量",
        "opening_pull": "开头吸引力",
        "sustained_motivation": "持续阅读动力",
        "escalation_density": "剧情推进与变化",
        "climax_ending_payoff": "高潮与结尾兑现",
        "platform_fit": "知乎短篇适配",
        "causal_arc": "七步因果结构",
        "character_agency": "人物动机与自主性",
        "continuity_logic": "时间线与人物认知",
        "promise_payoff": "伏笔、问题与承诺兑现",
        "relationship_change": "关系与情绪变化",
        "clarity": "表达自然清楚",
        "scene_dialogue": "场景与对白",
        "voice_emotion": "人物声音与情绪",
        "rhythm": "句子与段落节奏",
        "repetition_ai": "重复与机械表达",
    },
    dimension_weights={"commercial": 0.40, "story": 0.40, "prose": 0.20},
    criterion_dimensions={
        "opening_pull": "commercial",
        "sustained_motivation": "commercial",
        "escalation_density": "commercial",
        "climax_ending_payoff": "commercial",
        "platform_fit": "commercial",
        "causal_arc": "story",
        "character_agency": "story",
        "continuity_logic": "story",
        "promise_payoff": "story",
        "relationship_change": "story",
        "clarity": "prose",
        "scene_dialogue": "prose",
        "voice_emotion": "prose",
        "rhythm": "prose",
        "repetition_ai": "prose",
    },
    criterion_weights={
        "opening_pull": 8,
        "sustained_motivation": 9,
        "escalation_density": 8,
        "climax_ending_payoff": 10,
        "platform_fit": 5,
        "causal_arc": 10,
        "character_agency": 8,
        "continuity_logic": 8,
        "promise_payoff": 8,
        "relationship_change": 6,
        "clarity": 5,
        "scene_dialogue": 5,
        "voice_emotion": 4,
        "rhythm": 3,
        "repetition_ai": 3,
    },
    pass_total=80,
    conditional_total=75,
    pass_minimums={"commercial": 75, "story": 75, "prose": 68},
    conditional_minimums={"commercial": 72, "story": 70, "prose": 65},
)


PROFILES = {ZHihu_SHORT_V2.id: ZHihu_SHORT_V2}


def quality_profile_prompt(profile_id: str) -> str:
    profile = PROFILES.get(profile_id)
    if profile is None:
        return ""
    criteria = ", ".join(profile.criterion_dimensions)
    return (
        "QUALITY SCORING PROFILE: zhihu-short-v2. Return criteria with exactly these "
        f"0-100 numeric keys: {criteria}. Also return criterion_evidence with the same "
        "keys; every value must include location, excerpt, and effect. Runtime calculates "
        "commercial/story/prose and the 40/40/20 total from criteria, so do not adjust "
        "scores for compliance. Every issue must include issue_id when known, status, "
        "category, severity, location, evidence, effect, and action.\n\n"
    )


def judge_signature(receipt: dict | None) -> str:
    value = receipt or {}
    provider = value.get("provider_id") or "unknown-provider"
    model = value.get("model_id") or value.get("model_name") or "unknown-model"
    return f"{provider}/{model}"


def profile_for_project(project: Any) -> str:
    if (getattr(project, "mode", None) == "short"
            and getattr(project, "metadata", {}).get("platform_profile_id")
            == "zhihu-salt-short"):
        return ZHihu_SHORT_V2.id
    return "legacy-v1"


def score_review(review: dict, profile_id: str) -> dict:
    result = dict(review)
    if profile_id not in PROFILES:
        result["scoring_profile_id"] = "legacy-v1"
        result["criteria_complete"] = False
        return result
    profile = PROFILES[profile_id]
    criteria = result.get("criteria") if isinstance(result.get("criteria"), dict) else {}
    complete = all(name in criteria for name in profile.criterion_dimensions)
    if complete:
        dimensions: dict[str, float] = {}
        for dimension in profile.dimension_weights:
            names = [
                name for name, parent in profile.criterion_dimensions.items()
                if parent == dimension
            ]
            total_weight = sum(profile.criterion_weights[name] for name in names)
            dimensions[dimension] = round(sum(
                _score(criteria[name]) * profile.criterion_weights[name]
                for name in names
            ) / total_weight, 2)
    else:
        source = result.get("dimensions") or {}
        dimensions = {
            name: _score(source[name]) for name in profile.dimension_weights
        }
    result["dimensions"] = dimensions
    result["score"] = round(sum(
        dimensions[name] * weight
        for name, weight in profile.dimension_weights.items()
    ), 2)
    result["criteria"] = {
        name: _score(value) for name, value in criteria.items()
        if name in profile.criterion_dimensions
    }
    result["criterion_labels"] = {
        name: profile.labels[name] for name in result["criteria"]
    }
    result["dimension_labels"] = {
        name: profile.labels[name] for name in profile.dimension_weights
    }
    result["scoring_profile_id"] = profile.id
    result["criteria_complete"] = complete
    return result


def quality_outcome_for_profile(review: dict, profile_id: str) -> tuple[str, list[str]]:
    if profile_id not in PROFILES:
        return quality_outcome(review)
    profile = PROFILES[profile_id]
    reasons = _blocker_reasons(review)
    dimensions = review.get("dimensions", {})
    score = float(review.get("score", 0))
    if reasons:
        return "failed", reasons
    if (score >= profile.pass_total
            and all(float(dimensions.get(name, 0)) >= minimum
                    for name, minimum in profile.pass_minimums.items())):
        return "passed", []
    conditional_reasons = []
    if score < profile.conditional_total:
        conditional_reasons.append("overall_below_75")
    for name, minimum in profile.conditional_minimums.items():
        if float(dimensions.get(name, 0)) < minimum:
            conditional_reasons.append(f"{name}_below_{int(minimum)}")
    return ("failed", conditional_reasons) if conditional_reasons else (
        "conditional_pass", [],
    )


def compare_quality_candidates(best: dict, candidate: dict) -> dict:
    score_delta = round(
        float(candidate.get("score", 0)) - float(best.get("score", 0)), 2,
    )
    dimension_deltas = {
        name: round(
            float(candidate.get("dimensions", {}).get(name, 0))
            - float(best.get("dimensions", {}).get(name, 0)),
            2,
        )
        for name in ("commercial", "story", "prose")
    }
    reasons = []
    if best.get("scoring_profile_id") != candidate.get("scoring_profile_id"):
        reasons.append("different_scoring_profile")
    elif best.get("judge_signature") != candidate.get("judge_signature"):
        reasons.append("different_judge")
    if reasons:
        return {
            "promote": False, "comparable": False,
            "score_delta": score_delta, "dimension_deltas": dimension_deltas,
            "reasons": reasons,
        }
    if score_delta < 2:
        reasons.append("score_gain_below_2")
    reasons.extend(
        f"dimension_regression:{name}"
        for name, delta in dimension_deltas.items() if delta < -3
    )
    best_major_ids = _unresolved_major_ids(best)
    if _unresolved_major_ids(candidate) - best_major_ids:
        reasons.append("new_unresolved_major_issue")
    if _unresolved_mandatory_ids(candidate):
        reasons.append("unresolved_mandatory_issue")
    return {
        "promote": not reasons, "comparable": True,
        "score_delta": score_delta, "dimension_deltas": dimension_deltas,
        "reasons": reasons,
    }


def _blocker_reasons(review: dict) -> list[str]:
    reasons = []
    if review.get("hard_fail"):
        reasons.append("hard_fail")
    if review.get("decision") == "rewrite":
        reasons.append("rewrite")
    if _unresolved_major_ids(review):
        reasons.append("unresolved_major_issue")
    if _unresolved_mandatory_ids(review):
        reasons.append("unresolved_mandatory_issue")
    return reasons


def _unresolved_major_ids(review: dict) -> set[str]:
    return unresolved_major_issue_ids(review)


def _unresolved_mandatory_ids(review: dict) -> set[str]:
    return {
        str(issue.get("issue_id") or f"issue-{index}")
        for index, issue in enumerate(review.get("issues", []))
        if isinstance(issue, dict)
        and issue_is_mandatory(issue)
        and not issue_is_resolved(issue)
    }


def _score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Quality criteria must be numbers between 0 and 100")
    score = float(value)
    if not 0 <= score <= 100:
        raise ValueError("Quality criteria must be numbers between 0 and 100")
    return score
