from __future__ import annotations

import re
from typing import Any


SENTENCE_PATTERN = re.compile(r"[^。！？?!\n]+[。！？?!]?")
QUESTION_PATTERN = re.compile(r"为什么|为何|怎么|谁|哪[里个]|究竟|是否|[？?]")
DECISION_PATTERN = re.compile(r"决定|选择|拒绝|答应|离开|走进|进入|追上|逃|烧掉|递给|放弃|留下")
CONSEQUENCE_PATTERN = re.compile(r"因此|所以|于是|从此|导致|换来|结果|终于|失去|得到|成为|不再|却")
TURN_PATTERN = re.compile(r"却|原来|竟然?|突然|没想到|真相|揭晓|其实")
RELATIONSHIP_PATTERN = re.compile(r"相信|怀疑|背叛|原谅|保护|依赖|疏远|和解|爱上|离开|重逢")
PAYOFF_PATTERN = re.compile(r"兑现|回答|完成|终于|原来|回到|再见|结局|从此|一切结束")
PRESSURE_PATTERN = re.compile(r"危险|威胁|追杀|死亡|失踪|封锁|家暴|霸凌|绝境|来不及|只剩|唯一")
ANOMALY_PATTERN = re.compile(r"却|竟然?|突然|反而|唯一|仇人|陌生人|死人|不可能|第一次|烧掉|递给")
FUTURE_PROMISE_PATTERN = re.compile(r"后来|多年后|从此|最终|直到|没想到|再也|一辈子|十年|真相")


def local_attraction_candidates(text: str) -> dict:
    opening_text = text[:500]
    return {
        "coverage_percent": 100.0 if text else 0.0,
        "opening": {
            "pressure": _evidence(opening_text, PRESSURE_PATTERN),
            "anomaly": _evidence(opening_text, ANOMALY_PATTERN),
            "question": _evidence(opening_text, QUESTION_PATTERN),
            "future_promise": _evidence(opening_text, FUTURE_PROMISE_PATTERN),
        },
        "questions": _evidence(text, QUESTION_PATTERN),
        "decisions": _evidence(text, DECISION_PATTERN),
        "consequences": _evidence(text, CONSEQUENCE_PATTERN),
        "turns": _evidence(text, TURN_PATTERN),
        "relationship_changes": _evidence(text, RELATIONSHIP_PATTERN),
        "payoffs": _evidence(text, PAYOFF_PATTERN),
        "boundary": "本地结果是候选证据，不等于已确认的七步结构",
    }


def normalize_attraction_map(value: dict, text_length: int) -> dict:
    if not isinstance(value, dict):
        value = {}
    fit = value.get("fit") if isinstance(value.get("fit"), dict) else {}
    level = fit.get("level") if fit.get("level") in {"strong", "partial", "not_applicable"} else "partial"
    result = {
        "fit": {"level": level, "explanation": _text(fit.get("explanation"))},
        "opening": _mapping(value.get("opening")),
        "core_goal": _mapping(value.get("core_goal")),
        "cycles": [_mapping(item) for item in _list(value.get("cycles")) if isinstance(item, dict)],
        "accidents": [_mapping(item) for item in _list(value.get("accidents")) if isinstance(item, dict)],
        "reversal": _mapping(value.get("reversal")),
        "ending": _mapping(value.get("ending")),
        "question_chain": [_mapping(item) for item in _list(value.get("question_chain")) if isinstance(item, dict)],
        "relationship_arc": [_mapping(item) for item in _list(value.get("relationship_arc")) if isinstance(item, dict)],
        "uncertainties": [_text(item) for item in _list(value.get("uncertainties")) if _text(item)],
    }
    result = _clean_evidence(result, max(0, int(text_length or 0)))
    reversal = result.get("reversal")
    if reversal and not _list(reversal.get("prior_evidence")):
        result["reversal"] = None
        _append_once(result["uncertainties"], "反转缺少可回看的前置证据")
    if not _goal_text(result.get("core_goal")):
        _append_once(result["uncertainties"], "未识别出有证据支持的核心目标")
    if not _goal_text(result.get("ending")):
        _append_once(result["uncertainties"], "未识别出有证据支持的结局兑现")
    return result


def compact_attraction_guidance(value: dict) -> dict:
    opening = value.get("opening") if isinstance(value.get("opening"), dict) else {}
    cycles = value.get("cycles") if isinstance(value.get("cycles"), list) else []
    reversal = value.get("reversal") if isinstance(value.get("reversal"), dict) else {}
    ending = value.get("ending") if isinstance(value.get("ending"), dict) else {}
    relationship = value.get("relationship_arc") if isinstance(value.get("relationship_arc"), list) else []
    return {
        "fit": _text((value.get("fit") or {}).get("level")) if isinstance(value.get("fit"), dict) else "",
        "opening": _text(opening.get("mechanism")),
        "opening_rule": _text(opening.get("transfer_guidance")),
        "cycle_rules": _unique(_text(item.get("transfer_guidance")) for item in cycles if isinstance(item, dict)),
        "question_rules": _unique(
            _text(item.get("transfer_guidance")) for item in value.get("question_chain", []) if isinstance(item, dict)
        ),
        "relationship_rules": _unique(
            _text(item.get("transfer_guidance")) for item in relationship if isinstance(item, dict)
        ),
        "reversal_rule": _text(reversal.get("transfer_guidance")),
        "ending_rule": _text(ending.get("transfer_guidance")),
    }


def _evidence(text: str, pattern: re.Pattern[str]) -> list[dict]:
    result = []
    for sentence in SENTENCE_PATTERN.finditer(text):
        excerpt = sentence.group().strip()
        if not excerpt or not pattern.search(excerpt):
            continue
        leading = len(sentence.group()) - len(sentence.group().lstrip())
        start = sentence.start() + leading
        result.append({"start": start, "end": start + len(excerpt), "excerpt": excerpt})
    return result


def _mapping(value: Any) -> dict | None:
    return dict(value) if isinstance(value, dict) and value else None


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _goal_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return next((_text(value.get(key)) for key in (
        "surface", "emotional", "surface_payoff", "emotional_payoff", "content",
    ) if _text(value.get(key))), "")


def _clean_evidence(value: Any, text_length: int) -> Any:
    if isinstance(value, list):
        return [_clean_evidence(item, text_length) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {"evidence", "prior_evidence", "answer_evidence", "opening_evidence"} and isinstance(item, list):
            cleaned = []
            for evidence in item:
                if isinstance(evidence, str) and evidence.strip():
                    cleaned.append(evidence.strip())
                elif isinstance(evidence, dict):
                    start = evidence.get("start")
                    end = evidence.get("end")
                    excerpt = _text(evidence.get("excerpt"))
                    if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= text_length and excerpt:
                        cleaned.append({"start": start, "end": end, "excerpt": excerpt})
            result[key] = cleaned
        else:
            result[key] = _clean_evidence(item, text_length)
    return result


def _append_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _unique(values) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
