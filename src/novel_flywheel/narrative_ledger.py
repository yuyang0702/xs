from __future__ import annotations

import hashlib
import re
from typing import Any


LEDGER_VERSION = "narrative-ledger-v1"
_SENTENCE = re.compile(r"[^。！？!?\n]+[。！？!?]?")
_QUESTION = re.compile(r"[^。！？!?\n]{0,80}(?:为什么|怎么会|究竟|是否|能不能|[？?])[^。！？!?\n]*[。！？!?]?")
_PROMISE = re.compile(r"[^。！？!?\n]{0,80}(?:一定|必须|发誓|答应|承诺|会让|要让|决定)[^。！？!?\n]*[。！？!?]?")
_ANSWER = re.compile(r"真相|答案|原来|因为|其实|揭晓|证实|证明|才知道|终于明白")
_SETUP = re.compile(r"照片|信|钥匙|伤疤|录音|日记|遗物|秘密|异常|奇怪|不对劲|记号")
_PAYOFF = re.compile(r"真相|揭晓|原来|证明|证实|终于|正是|意味着|答案")
_CHANGE = re.compile(r"决定|选择|拒绝|接受|发现|知道|明白|失去|得到|离开|进入|相信|不再|开始|停止")


def build_narrative_ledger(text: str, nlp: dict | None = None) -> dict[str, Any]:
    sentences = [
        {"text": match.group().strip(), "start": match.start(), "end": match.end()}
        for match in _SENTENCE.finditer(text) if match.group().strip()
    ]
    questions = [_item(match, "question") for match in _QUESTION.finditer(text)]
    promises = [_item(match, "promise") for match in _PROMISE.finditer(text)]
    setups = [
        {**sentence, "id": _id("setup", sentence["start"], sentence["text"]),
         "kind": "setup", "status": "unresolved", "anchors": _anchors(sentence["text"])}
        for sentence in sentences if _SETUP.search(sentence["text"])
    ]
    relations: list[dict[str, Any]] = []
    for question in questions:
        answer = _later_match(question, sentences, _ANSWER)
        if answer:
            question["status"] = "linked"
            question["linked_to"] = _id("answer", answer["start"], answer["text"])
            relations.append(_relation("question_answer", question, answer, 0.76))
    for promise in promises:
        payoff = _later_match(promise, sentences, _PAYOFF, require_anchor=True)
        if payoff:
            promise["status"] = "linked"
            promise["linked_to"] = _id("payoff", payoff["start"], payoff["text"])
            relations.append(_relation("promise_payoff", promise, payoff, 0.68))
    for setup in setups:
        payoff = _later_match(setup, sentences, _PAYOFF, require_anchor=True)
        if payoff:
            setup["status"] = "linked"
            setup["linked_to"] = _id("payoff", payoff["start"], payoff["text"])
            relations.append(_relation("setup_payoff", setup, payoff, 0.72))
    scenes = _scenes(text, sentences)
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
        "relations": relations,
        "scenes": scenes,
        "important_uncertainties": important,
        "nlp_source": (nlp or {}).get("backend", "rules"),
    }


def _item(match: re.Match, kind: str) -> dict[str, Any]:
    text = match.group().strip()
    return {
        "id": _id(kind, match.start(), text), "kind": kind, "text": text,
        "start": match.start(), "end": match.start() + len(text),
        "status": "unresolved", "anchors": _anchors(text), "confidence": 0.72,
    }


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
        "id": _id(kind, source["start"], target["text"]), "kind": kind,
        "from_id": source["id"], "from_start": source["start"],
        "to_id": _id("evidence", target["start"], target["text"]),
        "to_start": target["start"], "to_end": target["end"],
        "evidence": target["text"], "confidence": confidence,
    }


def _scenes(text: str, sentences: list[dict]) -> list[dict[str, Any]]:
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
        spans.append({
            "id": f"scene-{len(spans) + 1:02d}", "start": start, "end": end,
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


def _id(kind: str, start: int, text: str) -> str:
    digest = hashlib.sha256(f"{kind}\0{start}\0{text}".encode("utf-8")).hexdigest()[:12]
    return f"{kind}-{digest}"
