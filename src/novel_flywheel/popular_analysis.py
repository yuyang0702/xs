from __future__ import annotations

import re


def _evidence(text: str, pattern: str, limit: int = 5) -> list[dict[str, object]]:
    result = []
    for match in re.finditer(pattern, text):
        start = max(0, text.rfind("。", 0, match.start()) + 1)
        stops = [position for position in (
            text.find("。", match.end()), text.find("！", match.end()), text.find("？", match.end()),
        ) if position >= 0]
        end = min(stops) + 1 if stops else min(len(text), match.end() + 80)
        result.append({"start": start, "end": end, "excerpt": text[start:end].strip()})
        if len(result) >= limit:
            break
    return result


def _section(metrics: dict[str, object], evidence: list[dict[str, object]],
             findings: list[str]) -> dict[str, object]:
    return {"metrics": metrics, "evidence": evidence, "findings": findings}


def analyze_popular_sample(title: str, text: str, nlp: dict | None = None) -> dict[str, object]:
    del nlp
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first_lines = lines[:3]
    opening = text[:500]
    middle_start, middle_end = len(text) // 4, len(text) * 3 // 4
    middle = text[middle_start:middle_end]
    ending_start = max(0, len(text) - 500)
    ending = text[ending_start:]
    hook_pattern = r"死|凶手|失踪|秘密|异常|却|竟|突然|为什么|？|\?"
    turn_pattern = r"却|原来|竟然|突然|真相|没想到|但是|然而"
    event_pattern = r"发现|决定|进入|离开|死亡|出现|改变|拒绝|追|逃|打开|拿出|告诉"

    opening_evidence = _evidence(opening, hook_pattern)
    turn_evidence = _evidence(text, turn_pattern)
    for item in turn_evidence:
        item["position_ratio"] = round(int(item["start"]) / max(1, len(text)), 3)
    ending_evidence = _evidence(ending, r"真相|终于|原来|？|\?")
    for item in ending_evidence:
        item["start"] = int(item["start"]) + ending_start
        item["end"] = int(item["end"]) + ending_start

    sections = {
        "title": _section(
            {"length": len(title), "hook_signals": len(re.findall(hook_pattern, title))},
            _evidence(title, hook_pattern),
            [] if re.search(hook_pattern, title) else ["标题缺少可识别的异常、冲突或信息差"],
        ),
        "first_three_lines": _section(
            {"line_count": len(first_lines), "line_lengths": [len(line) for line in first_lines]},
            _evidence("\n".join(first_lines), hook_pattern),
            [] if re.search(hook_pattern, "\n".join(first_lines)) else ["前三行的继续阅读信号较弱"],
        ),
        "opening_500": _section(
            {
                "characters": len(opening),
                "questions": len(re.findall(r"[？?]", opening)),
                "hook_signals": len(re.findall(hook_pattern, opening)),
            },
            opening_evidence,
            [] if opening_evidence else ["前500字未识别到人物异常、冲突或显式问题"],
        ),
        "middle": _section(
            {
                "characters": len(middle),
                "event_signals": len(re.findall(event_pattern, middle)),
                "paragraphs": len([item for item in re.split(r"\n\s*\n", middle) if item.strip()]),
            },
            _evidence(middle, event_pattern),
            [] if re.search(event_pattern, middle) else ["中段事件推进信号较少"],
        ),
        "turning_points": _section(
            {"count": len(turn_evidence)},
            turn_evidence,
            [] if turn_evidence else ["未识别到明确转折信号"],
        ),
        "ending": _section(
            {
                "characters": len(ending),
                "questions": len(re.findall(r"[？?]", ending)),
                "payoff_signals": len(re.findall(r"真相|终于|原来|解决|明白", ending)),
            },
            ending_evidence,
            [] if ending_evidence else ["结尾未识别到问题兑现或新问题证据"],
        ),
    }
    return {"analyzer": "popular-sample-local", "version": "1", "model_calls": 0, "sections": sections}
