from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any, Callable, Iterable, Mapping

from novel_flywheel.prose_quality import analyze_prose
from novel_flywheel.quality import review_windows
from novel_flywheel.narrative_ledger import build_narrative_ledger
from novel_flywheel.originality import OriginalityEngine, OriginalitySourceChunkV1


ANALYSIS_VERSION = "manuscript-analysis-v5"
EMPTY_REFERENCE_CORPUS_SHA256 = hashlib.sha256(
    b"novel-flywheel:reference-corpus:disabled:v1",
).hexdigest()
_HAN = re.compile(r"[\u4e00-\u9fff]")
_NAME = re.compile(r"[赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程嵇邢滑裴陆荣翁荀羊甄曲封芮储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲台从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍璩桑桂濮牛寿通边扈燕冀浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东欧利师巩聂晁勾敖融冷辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公]{1}[\u4e00-\u9fff]{1,2}")
_TIME = re.compile(r"(?:第[一二三四五六七八九十\d]+天|当天|次日|翌日|清晨|傍晚|深夜|\d{1,2}[点时])")
_QUESTION = re.compile(r"[^。！？\n]{0,60}[？?]")
_CONFLICT = re.compile(r"异常|冲突|目标|必须|却|但是|不料|突然|发现|失踪|死亡|威胁|拒绝")
_SETTING = re.compile(r"学校|医院|公司|古代|现代|末世|修仙|宫廷|地下室|仓库|村庄|城市")
_PLOT = re.compile(r"发现|失踪|复仇|背叛|重生|穿越|反转|真相|秘密|误会|谋杀|追查")


def analyze_manuscript(
    text: str,
    *,
    nlp_analyze: Callable[[str], dict] | None,
    comparison_sources: Iterable[
        OriginalitySourceChunkV1 | Mapping[str, Any]
    ] | None = None,
    reference_corpus_sha256: str = EMPTY_REFERENCE_CORPUS_SHA256,
    market_baseline: dict | None = None,
) -> dict:
    units = stable_text_units(text)
    windows = review_windows(text)
    nlp = nlp_analyze(text) if nlp_analyze else {
        "backend": "rules", "available": False, "backend_version": "rules-v1",
        "reason": "LTP analyzer was not supplied",
    }
    entities, events = _normalize_ltp(text, nlp)
    entities = [_with_provenance(item, units, "ltp", 0.9) for item in entities]
    events = [_with_provenance(item, units, "ltp", 0.86) for item in events]
    questions = [
        _with_provenance(
            {"text": match.group(), "start": match.start(), "end": match.end()},
            units, "rules", 0.72,
        )
        for match in _QUESTION.finditer(text)
    ]
    times = [
        _with_provenance(
            {"text": match.group(), "start": match.start(), "end": match.end()},
            units, "rules", 0.68,
        )
        for match in _TIME.finditer(text)
    ]
    conflicts = [
        _with_provenance(
            {"text": match.group(), "start": match.start(), "end": match.end()},
            units, "rules", 0.65,
        )
        for match in _CONFLICT.finditer(text)
    ]
    first_lines = [line.strip() for line in text.splitlines() if line.strip()][:3]
    prose = analyze_prose(text)
    narrative_ledger = build_narrative_ledger(text, nlp)
    result = {
        "analysis_version": ANALYSIS_VERSION,
        "text_hash": _hash(text),
        "reference_corpus_sha256": reference_corpus_sha256,
        "units": units,
        "characters": len(text),
        "coverage": 1.0 if windows and windows[-1]["end"] == len(text) else (1.0 if not text else 0.0),
        "windows": [{**window, "hash": _hash(window["text"])} for window in windows],
        "opening": {
            "first_three_lines": first_lines,
            "first_three_characters": sum(map(len, first_lines)),
            "zone_characters": min(500, len(text)),
            "has_person": bool(entities),
            "has_event_or_conflict": bool(events or conflicts),
        },
        "prose": prose,
        "nlp": {
            "backend": nlp.get("backend", "rules"),
            "backend_version": nlp.get("backend_version", "unknown"),
            "available": bool(nlp.get("available")),
            "cached": bool(nlp.get("cached")),
            "reason": nlp.get("reason"),
        },
        "entities": entities,
        "events": events,
        "time_candidates": times,
        "conflict_candidates": conflicts,
        "questions": questions,
        "promises": questions,
        "setups": conflicts,
        "payoffs": narrative_ledger.get("payoffs", []),
        "originality": _originality(
            text, entities, events, comparison_sources or [],
        ),
        "narrative_ledger": narrative_ledger,
    }
    result["impact_index"] = build_impact_index(result)
    result["baseline_comparison"] = _compare_market_baseline(result, market_baseline)
    return result


def stable_key(kind: str, text: str, occurrence: int) -> str:
    normalized = re.sub(r"\s+", "", text)
    digest = hashlib.sha256(
        f"{kind}\0{normalized}\0{occurrence}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{kind}-{digest}"


def stable_text_units(text: str) -> dict:
    paragraphs = _stable_records("paragraph", _paragraph_spans(text))
    scenes = _stable_records("scene", _paragraph_spans(text))
    return {"paragraphs": paragraphs, "scenes": scenes}


def build_impact_index(report: dict) -> dict:
    index: dict[str, dict[str, list[dict]]] = {
        "entities": {}, "events": {}, "terms": {}, "relations": {},
    }
    for entity in report.get("entities", []):
        _add_location(index["entities"], str(entity.get("text", "")), entity)
    for event in report.get("events", []):
        key = str(event.get("signature") or event.get("predicate") or "")
        _add_location(index["events"], key, event)

    if not report.get("nlp", {}).get("available"):
        paragraphs = report.get("units", {}).get("paragraphs", [])
        for term in _ledger_term_anchors(report.get("narrative_ledger", {})):
            locations = []
            for paragraph_number, paragraph in enumerate(paragraphs, 1):
                content = str(paragraph.get("text", ""))
                for match in re.finditer(re.escape(term), content):
                    start = int(paragraph["start"]) + match.start()
                    locations.append({
                        "start": start,
                        "end": start + len(term),
                        "unit_id": paragraph["stable_id"],
                        "paragraph": paragraph_number,
                        "source": "rules",
                        "confidence": 0.62,
                    })
            if len({item["paragraph"] for item in locations}) >= 2:
                index["terms"][term] = locations

    for relation in report.get("narrative_ledger", {}).get("relations", []):
        key = str(relation.get("id") or relation.get("kind") or "")
        endpoints = [
            {
                "start": relation.get("from_start"),
                "end": relation.get("from_end"),
                "unit_id": relation.get("from_unit_id"),
                "source": relation.get("source", "rules"),
                "confidence": relation.get("confidence", 0.5),
                "endpoint": "from",
            },
            {
                "start": relation.get("to_start"),
                "end": relation.get("to_end"),
                "unit_id": relation.get("to_unit_id"),
                "source": relation.get("source", "rules"),
                "confidence": relation.get("confidence", 0.5),
                "endpoint": "to",
            },
        ]
        index["relations"].setdefault(key, []).extend(endpoints)
    return index


def analysis_matches(
    report: dict, text: str,
    reference_corpus_sha256: str = EMPTY_REFERENCE_CORPUS_SHA256,
) -> bool:
    return (
        report.get("analysis_version") == ANALYSIS_VERSION
        and report.get("text_hash") == _hash(text)
        and report.get("reference_corpus_sha256") == reference_corpus_sha256
    )


def compact_analysis(report: dict, *, max_findings: int = 12) -> dict:
    prose = report.get("prose", {})
    return {
        "analysis_version": report.get("analysis_version"),
        "text_hash": report.get("text_hash"),
        "reference_corpus_sha256": report.get("reference_corpus_sha256"),
        "coverage": report.get("coverage"),
        "opening": report.get("opening", {}),
        "metrics": prose.get("metrics", {}),
        "findings": prose.get("findings", [])[:max_findings],
        "entity_count": len(report.get("entities", [])),
        "event_count": len(report.get("events", [])),
        "conflict_count": len(report.get("conflict_candidates", [])),
        "question_count": len(report.get("questions", [])),
        "originality_counts": {
            key: len(report.get("originality", {}).get(key, []))
            for key in ("continuous_passages", "similar_names", "semantic_candidates")
        },
        "nlp": report.get("nlp", {}),
        "baseline_comparison": report.get("baseline_comparison"),
        "narrative_ledger": {
            "question_count": len(report.get("narrative_ledger", {}).get("questions", [])),
            "promise_count": len(report.get("narrative_ledger", {}).get("promises", [])),
            "setup_count": len(report.get("narrative_ledger", {}).get("setups", [])),
            "relation_count": len(report.get("narrative_ledger", {}).get("relations", [])),
            "scene_count": len(report.get("narrative_ledger", {}).get("scenes", [])),
            "important_uncertainties": report.get("narrative_ledger", {}).get("important_uncertainties", [])[:8],
        },
    }


def _compare_market_baseline(report: dict, baseline: dict | None) -> dict | None:
    if not baseline:
        return None
    sample_count = int(baseline.get("sample_count") or 0)
    deviations = []
    opening = baseline.get("opening") or {}
    current_lines = "".join(report.get("opening", {}).get("first_three_lines", []))
    if float(opening.get("question_percent") or 0) >= 50 and not re.search(
        r"[？?]|为什么|怎么会|究竟", current_lines,
    ):
        deviations.append({
            "signal": "opening_question", "message": "开头未出现同类样本中常见的明确问题信号",
            "blocking": False,
        })
    if float(opening.get("anomaly_percent") or 0) >= 50 and not _CONFLICT.search(current_lines):
        deviations.append({
            "signal": "opening_anomaly", "message": "开头未出现同类样本中常见的异常或冲突信号",
            "blocking": False,
        })
    return {
        "sample_count": sample_count,
        "confidence_level": baseline.get("confidence_level", "insufficient"),
        "deviations": deviations,
        "advisory_only": True,
        "boundary": baseline.get("boundary"),
    }


def _paragraph_spans(text: str) -> list[dict]:
    spans = []
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
        spans.append({"text": content, "start": start, "end": start + len(content)})
    return spans


def _stable_records(kind: str, spans: list[dict]) -> list[dict]:
    occurrences: dict[str, int] = {}
    records = []
    for span in spans:
        normalized = re.sub(r"\s+", "", span["text"])
        occurrences[normalized] = occurrences.get(normalized, 0) + 1
        occurrence = occurrences[normalized]
        records.append({
            **span,
            "text_hash": _hash(span["text"]),
            "stable_id": stable_key(kind, span["text"], occurrence),
            "occurrence": occurrence,
        })
    return records


def _with_provenance(
    item: dict, units: dict, source: str, confidence: float,
) -> dict:
    start = int(item.get("start", 0))
    paragraph_number, unit_id = _unit_at(units, start)
    return {
        **item,
        "paragraph": paragraph_number,
        "unit_id": unit_id,
        "source": source,
        "confidence": confidence,
    }


def _unit_at(units: dict, offset: int) -> tuple[int | None, str | None]:
    for number, unit in enumerate(units.get("paragraphs", []), 1):
        if unit["start"] <= offset < unit["end"]:
            return number, unit["stable_id"]
    return None, None


def _add_location(target: dict[str, list[dict]], key: str, item: dict) -> None:
    if not key:
        return
    target.setdefault(key, []).append({
        name: item.get(name)
        for name in ("start", "end", "unit_id", "paragraph", "source", "confidence")
    })


def _ledger_term_anchors(ledger: dict) -> list[str]:
    anchors = []
    for kind in ("questions", "promises", "setups", "payoffs", "relations"):
        for item in ledger.get(kind, []):
            anchors.extend(item.get("anchors") or [])
    return list(dict.fromkeys(
        str(anchor)
        for anchor in anchors
        if re.fullmatch(r"[\u4e00-\u9fff]{2,6}", str(anchor))
    ))


def _normalize_ltp(text: str, payload: dict) -> tuple[list[dict], list[dict]]:
    if not payload.get("available"):
        return [], []
    result = payload.get("result") or {}
    words = _first_sentence(result.get("cws"))
    pos = _first_sentence(result.get("pos"))
    offsets, cursor = [], 0
    for word in words:
        start = text.find(str(word), cursor)
        start = cursor if start < 0 else start
        offsets.append((start, start + len(str(word))))
        cursor = start + len(str(word))
    entities = []
    ner = _first_sentence(result.get("ner"))
    for item in ner:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        if len(item) >= 4 and isinstance(item[1], str):
            label, start_i, end_i = item[0], int(item[2]), int(item[3])
        else:
            label, start_i, end_i = item[0], int(item[1]), int(item[2])
        if 0 <= start_i <= end_i < len(words):
            entities.append({
                "type": str(label), "text": "".join(map(str, words[start_i:end_i + 1])),
                "start": offsets[start_i][0], "end": offsets[end_i][1],
                "window": _window_for(offsets[start_i][0], review_windows(text)),
            })
    events = []
    srl = _first_sentence(result.get("srl"))
    if len(srl) == 1 and isinstance(srl[0], list):
        srl = srl[0]
    for frame in srl:
        if isinstance(frame, dict):
            predicate_i = int(frame.get("index", -1))
            frame_arguments = frame.get("arguments") or []
        elif isinstance(frame, (list, tuple)) and frame:
            predicate_i = int(frame[0])
            frame_arguments = frame[1] if len(frame) > 1 else []
        else:
            continue
        if not 0 <= predicate_i < len(words):
            continue
        arguments = []
        for argument in frame_arguments:
            if isinstance(argument, (list, tuple)) and len(argument) >= 3:
                if len(argument) >= 4 and isinstance(argument[1], str):
                    label, start_i, end_i = argument[0], int(argument[2]), int(argument[3])
                else:
                    label, start_i, end_i = argument[0], int(argument[1]), int(argument[2])
                if 0 <= start_i <= end_i < len(words):
                    arguments.append({
                        "role": str(label),
                        "text": "".join(map(str, words[start_i:end_i + 1])),
                    })
        events.append({
            "predicate": str(words[predicate_i]),
            "start": offsets[predicate_i][0], "end": offsets[predicate_i][1],
            "arguments": arguments,
            "signature": "|".join([str(words[predicate_i]), *(item["text"] for item in arguments)]),
            "window": _window_for(offsets[predicate_i][0], review_windows(text)),
        })
    return entities, events


def _first_sentence(value):
    if not isinstance(value, list) or not value:
        return []
    first = value[0]
    return first if isinstance(first, list) else value


def _window_for(offset: int, windows: list[dict]) -> int | None:
    return next((item["index"] for item in windows if item["start"] <= offset < item["end"]), None)


def _originality(
    text: str, entities: list[dict], events: list[dict],
    sources: Iterable[OriginalitySourceChunkV1 | Mapping[str, Any]],
) -> dict:
    report = OriginalityEngine().scan(
        text, sources, manuscript_events=events,
    )
    passages = [{
        "source_id": item.source_id,
        "manuscript_start": item.manuscript_start,
        "manuscript_end": item.manuscript_end,
        "source_start": item.source_start,
        "source_end": item.source_end,
        "text": text[item.manuscript_start:item.manuscript_end],
        "characters": item.manuscript_end - item.manuscript_start,
        "score": item.score,
        "severity": item.severity,
        "evidence_sha256": item.evidence_sha256,
        "method": "winnowing_v1",
        "metadata": item.metadata,
    } for item in report.findings if item.finding_type == "literal_winnowing"]
    semantic = [{
        "kind": item.finding_type,
        "source_id": item.source_id,
        "manuscript_start": item.manuscript_start,
        "manuscript_end": item.manuscript_end,
        "source_start": item.source_start,
        "source_end": item.source_end,
        "similarity": item.score,
        "severity": item.severity,
        "evidence_sha256": item.evidence_sha256,
        **item.metadata,
    } for item in report.findings if item.finding_type != "literal_winnowing"]
    names = []
    manuscript_names = {item["text"] for item in entities if len(item["text"]) in (2, 3)}
    if not manuscript_names:
        manuscript_names.update(_NAME.findall(text))
    for source in sources:
        source_text = str(source.get("text", ""))
        source_id = str(source.get("id", "unknown"))
        source_names = set(_NAME.findall(source_text))
        for left in manuscript_names:
            for right in source_names:
                score = SequenceMatcher(None, left, right).ratio()
                if left != right and score >= 0.66:
                    names.append({
                        "source_id": source_id, "manuscript_name": left,
                        "source_name": right, "similarity": round(score, 3),
                    })
    return {
        "continuous_passages": passages,
        "similar_names": _dedupe(names),
        "semantic_candidates": semantic,
        "scope": report.scope,
        "layers": report.layers,
        "source_ids": report.source_ids,
    }


def _terms(text: str) -> set[str]:
    return {
        match.group()
        for match in re.finditer(r"[\u4e00-\u9fff]{2,6}", text)
        if _SETTING.search(match.group()) or _PLOT.search(match.group())
    }


def _dedupe(items: list[dict]) -> list[dict]:
    result, seen = [], set()
    for item in items:
        key = tuple(sorted(item.items()))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
