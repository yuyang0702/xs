from __future__ import annotations

import re


CONTENT_TYPES = {
    "reference_work", "platform_rule", "popular_sample",
    "writing_tutorial", "competitor_work",
}

_PLATFORMS = {
    "知乎": ("知乎", "zhihu.com"),
    "番茄": ("番茄", "fanqienovel.com"),
    "公众号": ("公众号", "微信公众", "mp.weixin.qq.com"),
    "晋江": ("晋江", "jjwxc.net"),
}


def classify_reference(title: str, text: str, source_uri: str | None = None) -> dict[str, str | float]:
    sample = f"{title}\n{source_uri or ''}\n{text[:4000]}"
    platform = next((
        name for name, markers in _PLATFORMS.items()
        if any(marker.lower() in sample.lower() for marker in markers)
    ), "")
    rules = len(re.findall(r"投稿要求|投稿规范|平台规则|禁止|不得|字数(?:要求|限制)|必须", sample))
    tutorial = len(re.findall(r"写作(?:方法|教程|技巧)|案例(?:分析|讲解)|如何写|创作教程", sample))
    popular = len(re.findall(r"爆款|高赞|热门|阅读量|点赞量|热榜", sample))
    reasons = []
    if platform:
        reasons.append(f"标题、网址或正文中出现了{platform}标记")
    if rules:
        content_type, confidence = "platform_rule", min(0.98, 0.78 + rules * 0.06)
        reasons.append("发现投稿要求或禁止事项")
    elif tutorial:
        content_type, confidence = "writing_tutorial", min(0.95, 0.75 + tutorial * 0.06)
        reasons.append("发现教程、方法或写作技巧说明")
    elif popular:
        content_type, confidence = "popular_sample", min(0.95, 0.74 + popular * 0.06)
        reasons.append("标题或正文写有高赞、热门、榜单等说明")
    else:
        content_type, confidence = "reference_work", 0.55
        reasons.append("没有发现规则、教程或热门标记，暂按参考作品保存")
    return {"platform": platform, "content_type": content_type, "confidence": round(confidence, 2),
            "reasons": reasons}
