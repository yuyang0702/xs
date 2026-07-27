from __future__ import annotations

from typing import Any


PROFILE_VERSION = "1.0"


def resolve_platform_profile(
    profile_id: str | None, project: Any, baseline: dict | None,
) -> dict[str, Any]:
    if not profile_id:
        return {
            "id": None, "name": "暂不指定平台", "version": None,
            "hard_rules": [], "market_advice": [],
            "market_note": "未启用平台创作配置。",
        }
    if profile_id != "zhihu-salt-short":
        raise ValueError("目前只支持知乎盐选短篇创作配置")
    if project.mode != "short":
        raise ValueError("知乎盐选短篇创作配置只能用于短篇作品")
    advice = []
    if baseline:
        for item in baseline.get("mechanisms", [])[:5]:
            advice.append(
                f"同类样本中有 {item.get('prevalence_percent', 0)}% 使用“{item.get('name')}”"
            )
    return {
        "id": profile_id,
        "name": "知乎盐选短篇创作配置",
        "version": PROFILE_VERSION,
        "hard_rules": [
            "作品必须保持原创，不照搬参考资料的人名、设定、关键情节或独特表达",
            "按短篇整体完成目标、阻碍、努力、结果、意外、反转和结局的推进",
            "投稿稿件必须来自已通过终审的正式正文",
        ],
        "market_advice": advice,
        "market_note": (
            f"参考 {baseline.get('sample_count', 0)} 份已确认的同类榜单作品。"
            if baseline else "没有可用的同类榜单样本，将只执行平台要求，不套用市场写法。"
        ),
    }
