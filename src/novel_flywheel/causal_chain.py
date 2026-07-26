from __future__ import annotations

import json
import re
from typing import Any


START = "SHORT_CAUSAL_CHAIN_JSON_START"
END = "SHORT_CAUSAL_CHAIN_JSON_END"


def cycle_range(target_words: int) -> tuple[int, int]:
    if target_words < 3000:
        return 1, 2
    if target_words < 8000:
        return 2, 3
    if target_words < 15000:
        return 3, 5
    if target_words < 30000:
        return 4, 7
    return 5, 9


def analyze_short_causal_chain(chain: dict[str, Any], target_words: int) -> dict[str, Any]:
    findings: list[dict[str, str]] = []

    def add(code: str, message: str, severity: str = "warning") -> None:
        findings.append({"code": code, "message": message, "severity": severity})

    goal = _text(chain.get("core_goal"))
    if not goal:
        add("missing_core_goal", "短篇因果链缺少核心目标", "error")

    cycles = chain.get("cycles") if isinstance(chain.get("cycles"), list) else []
    if not cycles:
        add("missing_cycle", "短篇至少需要一轮阻碍-努力-结果推进", "error")
    low, high = cycle_range(int(target_words or 0))
    if cycles and len(cycles) < low:
        add("cycle_count_low", f"当前 {len(cycles)} 轮，建议 {low}-{high} 轮")
    if len(cycles) > high:
        add("cycle_count_high", f"当前 {len(cycles)} 轮，建议 {low}-{high} 轮")

    seen = set()
    seen_outcomes = set()
    for index, cycle in enumerate(cycles, 1):
        if not isinstance(cycle, dict):
            add("cycle_invalid", f"第 {index} 轮不是结构化对象", "error")
            continue
        for key, label in (("obstacle", "阻碍"), ("effort", "努力"), ("result", "结果")):
            if not _text(cycle.get(key)):
                add(f"cycle_missing_{key}", f"第 {index} 轮缺少{label}", "error")
        if not _text(cycle.get("state_change")):
            add("cycle_missing_state_change", f"第 {index} 轮缺少状态变化")
        signature = tuple(_text(cycle.get(key)) for key in ("obstacle", "effort", "result"))
        if signature in seen:
            add("cycle_duplicate", f"第 {index} 轮与前文推进重复")
        seen.add(signature)
        outcome_signature = tuple(_text(cycle.get(key)) for key in ("result", "state_change"))
        if all(outcome_signature) and outcome_signature in seen_outcomes:
            add("cycle_repeated_outcome", f"第 {index} 轮结果和状态变化与前文相同，剧情没有获得新推进")
        seen_outcomes.add(outcome_signature)

    reversal = chain.get("reversal")
    if isinstance(reversal, dict) and _text(reversal):
        evidence = reversal.get("prior_evidence")
        if not isinstance(evidence, list) or not [item for item in evidence if _text(item)]:
            add("reversal_missing_evidence", "反转缺少前置证据")

    ending = chain.get("ending")
    if not _text(ending):
        add("missing_ending", "短篇因果链缺少结局", "error")

    status = "invalid" if any(item["severity"] == "error" for item in findings) else (
        "needs_review" if findings else "valid"
    )
    return {
        "status": status,
        "target_cycle_range": [low, high],
        "cycle_count": len(cycles),
        "findings": findings,
    }


def compact_causal_chain(chain: dict[str, Any], max_cycles: int = 7) -> str:
    lines = [f"核心目标：{_text(chain.get('core_goal')) or '未确认'}"]
    opening = chain.get("opening")
    if isinstance(opening, dict):
        lines.append(
            f"开头吸引：压力={_text(opening.get('pressure'))}；异常={_text(opening.get('anomaly'))}；"
            f"读者问题={_text(opening.get('reader_question'))}；后续承诺={_text(opening.get('future_promise'))}"
        )
    for index, cycle in enumerate(chain.get("cycles") or [], 1):
        if index > max_cycles or not isinstance(cycle, dict):
            continue
        lines.append(
            f"推进{index}：阻碍={_text(cycle.get('obstacle'))}；"
            f"努力={_text(cycle.get('effort'))}；结果={_text(cycle.get('result'))}；"
            f"状态变化={_text(cycle.get('state_change'))}；升级={_text(cycle.get('escalation'))}；"
            f"下一问题={_text(cycle.get('next_question'))}"
        )
    for item in chain.get("accidents") or []:
        lines.append(f"意外：{_text(item)}")
    if _text(chain.get("reversal")):
        lines.append(f"反转：{_text(chain.get('reversal'))}")
    if _text(chain.get("question_chain")):
        lines.append(f"问题链：{_text(chain.get('question_chain'))}")
    if _text(chain.get("relationship_arc")):
        lines.append(f"关系变化：{_text(chain.get('relationship_arc'))}")
    lines.append(f"结局：{_text(chain.get('ending')) or '未确认'}")
    return "\n".join(line for line in lines if line.strip())


def extract_short_causal_chain(text: str) -> tuple[str, dict[str, Any] | None]:
    match = re.search(
        rf"\n?{START}\s*(?P<json>\{{.*?\}})\s*{END}\n?",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return text, None
    outline = (text[:match.start()] + text[match.end():]).strip()
    return outline, json.loads(match.group("json"))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("content", "surface_goal", "inner_goal", "result", "changes"):
            if key in value and _text(value[key]):
                return _text(value[key])
        return "；".join(_text(item) for item in value.values() if _text(item))
    if isinstance(value, list):
        return "；".join(_text(item) for item in value if _text(item))
    return str(value).strip()
