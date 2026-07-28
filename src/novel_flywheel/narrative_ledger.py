from __future__ import annotations

import hashlib
import re
from typing import Any


LEDGER_VERSION = "narrative-ledger-v2"
_SENTENCE = re.compile(r"[^。！？!?\n]+[。！？!?]?")
_QUESTION = re.compile(r"[^。！？!?\n]{0,80}(?:为什么|怎么会|究竟|是否|能不能|[？?])[^。！？!?\n]*[。！？!?]?")
_PROMISE = re.compile(r"[^。！？!?\n]{0,80}(?:一定|必须|发誓|答应|承诺|会让|要让|决定)[^。！？!?\n]*[。！？!?]?")
_ANSWER = re.compile(r"真相|答案|原来|因为|其实|揭晓|证实|证明|才知道|终于明白")
_SETUP = re.compile(r"照片|信|钥匙|伤疤|录音|日记|遗物|秘密|异常|奇怪|不对劲|记号")
_PAYOFF = re.compile(r"真相|揭晓|原来|证明|证实|终于|正是|意味着|答案")
_CHANGE = re.compile(r"决定|选择|拒绝|接受|发现|知道|明白|失去|得到|离开|进入|相信|不再|开始|停止")


def build_narrative_ledger(text: str, nlp: dict | None = None) -> dict[str, Any]:
    units = _paragraph_units(text)
    sentences = [
        {"text": match.group().strip(), "start": match.start(), "end": match.end()}
        for match in _SENTENCE.finditer(text) if match.group().strip()
    ]
    questions = _items(text, _QUESTION, "question", units)
    promises = _items(text, _PROMISE, "promise", units)
    setup_sentences = [sentence for sentence in sentences if _SETUP.search(sentence["text"])]
    setups = _evidence_items(setup_sentences, "setup", units, 0.7)
    relations: list[dict[str, Any]] = []
    payoffs: list[dict[str, Any]] = []
    for question in questions:
        answer = _later_match(question, sentences, _ANSWER)
        if answer:
            target = _target_item(answer, "answer", sentences, units, 0.76)
            question["status"] = "linked"
            question["linked_to"] = target["id"]
            relations.append(_relation("question_answer", question, target, 0.76))
    for promise in promises:
        payoff = _later_match(promise, sentences, _PAYOFF, require_anchor=True)
        if payoff:
            target = _target_item(payoff, "payoff", sentences, units, 0.68)
            promise["status"] = "linked"
            promise["linked_to"] = target["id"]
            payoffs.append(target)
            relations.append(_relation("promise_payoff", promise, target, 0.68))
    for setup in setups:
        payoff = _later_match(setup, sentences, _PAYOFF, require_anchor=True)
        if payoff:
            target = _target_item(payoff, "payoff", sentences, units, 0.72)
            setup["status"] = "linked"
            setup["linked_to"] = target["id"]
            payoffs.append(target)
            relations.append(_relation("setup_payoff", setup, target, 0.72))
    scenes = _scenes(text, sentences, units)
    unresolved = [*filter(lambda item: item["status"] == "unresolved", promises)]
    important = [
        {**item, "requires_model_review": True, "reason": "开头或核心目标承诺尚无明确兑现候选"}
        for item in unresolved
        if item["start"] / max(1, len(text)) < 0.2 or re.search(r"朋友|复活|真相|目标|一定|必须", item["text"])
    ]
    return {
        "version": LEDGER_VERSION,
        "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "questions": questions,
        "promises": promises,
        "setups": setups,
        "payoffs": _dedupe_by_id(payoffs),
        "relations": relations,
        "scenes": scenes,
        "important_uncertainties": important,
        "nlp_source": (nlp or {}).get("backend", "rules"),
    }


def _items(
    text: str, pattern: re.Pattern, kind: str, units: list[dict],
) -> list[dict[str, Any]]:
    matches = []
    for match in pattern.finditer(text):
        value = match.group().strip()
        start = match.start() + len(match.group()) - len(match.group().lstrip())
        matches.append({"text": value, "start": start, "end": start + len(value)})
    return _evidence_items(matches, kind, units, 0.72)


def _evidence_items(
    evidence: list[dict], kind: str, units: list[dict], confidence: float,
) -> list[dict[str, Any]]:
    occurrences: dict[str, int] = {}
    result = []
    for item in evidence:
        normalized = re.sub(r"\s+", "", item["text"])
        occurrences[normalized] = occurrences.get(normalized, 0) + 1
        unit_id = _unit_id_at(units, item["start"])
        result.append({
            **item,
            "id": _stable_id(kind, item["text"], occurrences[normalized]),
            "kind": kind,
            "status": "unresolved",
            "anchors": _anchors(item["text"]),
            "source": "rules",
            "confidence": confidence,
            "unit_id": unit_id,
        })
    return result


def _later_match(
    source: dict, sentences: list[dict], pattern: re.Pattern, *, require_anchor: bool = False,
) -> dict | None:
    source_anchors = set(source.get("anchors") or _anchors(source["text"]))
    for sentence in sentences:
        if sentence["start"] <= source["end"] or not pattern.search(sentence["text"]):
            continue
        if require_anchor and not source_anchors.intersection(_anchors(sentence["text"])):
            continue
        return sentence
    return None


def _relation(kind: str, source: dict, target: dict, confidence: float) -> dict[str, Any]:
    return {
        "id": _relation_id(kind, source["id"], target["id"]), "kind": kind,
        "from_id": source["id"], "from_start": source["start"],
        "from_end": source["end"], "from_unit_id": source.get("unit_id"),
        "to_id": target["id"],
        "to_start": target["start"], "to_end": target["end"],
        "to_unit_id": target.get("unit_id"),
        "evidence": target["text"], "confidence": confidence,
        "source": "rules",
    }


def _scenes(
    text: str, sentences: list[dict], units: list[dict],
) -> list[dict[str, Any]]:
    spans = []
    for match in re.finditer(r"(?:^|\n\s*\n)(.*?)(?=\n\s*\n|$)", text, flags=re.DOTALL):
        content = match.group(1).strip()
        if not content:
            continue
        start = text.find(content, match.start())
        end = start + len(content)
        changes = [
            {"start": item["start"], "end": item["end"], "evidence": item["text"]}
            for item in sentences if start <= item["start"] < end and _CHANGE.search(item["text"])
        ]
        occurrence = 1 + sum(
            re.sub(r"\s+", "", item.get("text", "")) == re.sub(r"\s+", "", content)
            for item in spans
        )
        stable_id = _stable_id("scene", content, occurrence)
        spans.append({
            "id": f"scene-{len(spans) + 1:02d}", "start": start, "end": end,
            "stable_id": stable_id, "unit_id": _unit_id_at(units, start),
            "text": content,
            "text_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "occurrence": occurrence,
            "entry_state": changes[0]["evidence"] if changes else None,
            "exit_state": changes[-1]["evidence"] if changes else None,
            "state_changes": changes,
        })
    return spans


def _anchors(text: str) -> list[str]:
    terms = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
    stop = {"为什么", "怎么会", "究竟", "是否", "一定", "必须", "终于", "真相", "答案", "原来", "因为", "其实"}
    anchors = []
    for term in terms:
        for width in (3, 2):
            anchors.extend(term[index:index + width] for index in range(max(0, len(term) - width + 1)))
    return list(dict.fromkeys(item for item in anchors if item not in stop))


def _stable_id(kind: str, text: str, occurrence: int) -> str:
    normalized = re.sub(r"\s+", "", text)
    digest = hashlib.sha256(
        f"{kind}\0{normalized}\0{occurrence}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{kind}-{digest}"


def _relation_id(kind: str, from_id: str, to_id: str) -> str:
    digest = hashlib.sha256(
        f"{kind}\0{from_id}\0{to_id}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{kind}-{digest}"


def _paragraph_units(text: str) -> list[dict]:
    units = []
    occurrences: dict[str, int] = {}
    for match in re.finditer(
        r"(?:^|\r?\n[ \t]*\r?\n)(.*?)(?=\r?\n[ \t]*\r?\n|\Z)",
        text,
        flags=re.DOTALL,
    ):
        raw = match.group(1)
        content = raw.strip()
        if not content:
            continue
        start = match.start(1) + len(raw) - len(raw.lstrip())
        normalized = re.sub(r"\s+", "", content)
        occurrences[normalized] = occurrences.get(normalized, 0) + 1
        units.append({
            "start": start, "end": start + len(content), "text": content,
            "stable_id": _stable_id("paragraph", content, occurrences[normalized]),
        })
    return units


def _unit_id_at(units: list[dict], offset: int) -> str | None:
    return next(
        (item["stable_id"] for item in units if item["start"] <= offset < item["end"]),
        None,
    )


def _target_item(
    target: dict, kind: str, sentences: list[dict], units: list[dict], confidence: float,
) -> dict:
    normalized = re.sub(r"\s+", "", target["text"])
    occurrence = sum(
        1
        for sentence in sentences
        if sentence["start"] <= target["start"]
        and re.sub(r"\s+", "", sentence["text"]) == normalized
    )
    return {
        **target,
        "id": _stable_id(kind, target["text"], occurrence),
        "kind": kind,
        "unit_id": _unit_id_at(units, target["start"]),
        "source": "rules",
        "confidence": confidence,
    }


def _dedupe_by_id(items: list[dict]) -> list[dict]:
    return list({item["id"]: item for item in items}.values())
