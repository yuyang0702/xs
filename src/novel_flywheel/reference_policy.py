from __future__ import annotations

from typing import Any


TYPE_LABELS = {
    "reference_work": "参考作品",
    "platform_rule": "平台规则",
    "popular_sample": "爆款样本",
    "writing_tutorial": "写作教程",
    "competitor_work": "竞品作品",
}


def build_classification_snapshot(
    recommendation: dict[str, Any], *, platform: str | None, content_type: str | None,
    user_selected: bool,
) -> dict[str, Any]:
    selected_platform = (platform if user_selected else recommendation.get("platform")) or ""
    selected_type = (content_type if user_selected else recommendation.get("content_type")) or "reference_work"
    reasons = list(recommendation.get("reasons") or [])
    if user_selected:
        reasons = ["你在导入或资料设置中确认了这个分类"]
    elif not reasons:
        reasons = ["没有发现更明确的类型信号，暂按参考作品保存"]
    return {
        "platform": selected_platform,
        "content_type": selected_type,
        "trust": "user_confirmed" if user_selected else "inferred",
        "confidence": 1.0 if user_selected else float(recommendation.get("confidence") or 0.5),
        "reasons": reasons,
    }


def reference_usage(source: dict[str, Any], market_context: dict | None) -> dict[str, Any]:
    content_type = source.get("content_type") or "reference_work"
    classification = source.get("classification") or {}
    trust = classification.get("trust") or "inferred"
    allowed: list[str]
    excluded: list[str]
    next_steps: list[dict[str, str]]
    if content_type == "platform_rule":
        allowed = ["投稿规则检查", "平台要求整理"]
        excluded = ["文笔学习", "市场趋势参考"]
        next_steps = [{"action": "local_learn", "label": "整理投稿要求"}]
    elif content_type == "writing_tutorial":
        allowed = ["写作方法整理", "全局检查方法"]
        excluded = ["文笔学习", "真实市场统计"]
        next_steps = [{"action": "local_learn", "label": "整理可执行方法"}]
    elif content_type == "competitor_work":
        allowed = ["原创风险比较", "题材差异检查"]
        excluded = ["文笔学习", "自动采纳写法"]
        next_steps = [{"action": "local_analyze", "label": "检查相似风险"}]
    elif content_type == "popular_sample":
        verified = bool(market_context and market_context.get("status") == "confirmed")
        trust = "market_verified" if verified else "self_described"
        allowed = ["爆款结构分析", "剧情吸引力分析"]
        excluded = ["自动采纳写法"]
        if verified:
            allowed.insert(0, "市场趋势参考")
        else:
            excluded.insert(0, "真实市场统计")
        next_steps = [{"action": "popular_analysis", "label": "查看爆款结构"}]
        if not verified:
            next_steps.insert(0, {"action": "market_match", "label": "查找榜单依据"})
    else:
        allowed = ["剧情结构提炼", "开头吸引力分析", "文笔候选"]
        excluded = ["自动采纳写法", "真实市场统计"]
        next_steps = [{"action": "local_learn", "label": "提炼可学习写法"}]
    return {
        "trust": trust,
        "trust_label": {
            "inferred": "系统推测", "legacy": "根据旧资料恢复", "user_confirmed": "你已确认",
            "self_described": "尚无榜单证明", "market_verified": "榜单已验证",
        }.get(trust, "系统推测"),
        "type_label": TYPE_LABELS.get(content_type, "参考作品"),
        "allowed": allowed,
        "excluded": excluded,
        "next_steps": next_steps,
        "model_called": False,
    }


def reference_receipt(
    source: dict[str, Any], market_match: dict | None = None, market_context: dict | None = None,
) -> dict[str, Any]:
    usage = reference_usage(source, market_context)
    classification = source.get("classification") or {}
    candidates = list((market_match or {}).get("candidates") or [])
    if market_context:
        market_message = f"已关联榜单《{market_context.get('title') or '作品'}》"
    elif candidates:
        market_message = f"发现 {len(candidates)} 个可能匹配的榜单作品，等你确认"
    else:
        market_message = "暂时没有找到榜单依据，不影响本地分析"
    platform = source.get("platform") or "平台未确定"
    return {
        "headline": f"{platform} · {usage['type_label']}",
        "trust_label": usage["trust_label"],
        "reasons": list(classification.get("reasons") or []),
        "market_message": market_message,
        "recommended_for": usage["allowed"],
        "not_used_for": usage["excluded"],
        "next_steps": usage["next_steps"],
        "cost_message": "本次导入没有调用模型，也不会修改任何作品",
    }
