from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Callable

from novel_flywheel.prose_quality import analyze_prose
from novel_flywheel.quality import review_windows
from novel_flywheel.narrative_ledger import build_narrative_ledger


ANALYSIS_VERSION = "manuscript-analysis-v2"
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
    comparison_sources: list[dict[str, str]] | None = None,
    market_baseline: dict | None = None,
) -> dict:
    windows = review_windows(text)
    nlp = nlp_analyze(text) if nlp_analyze else {
        "backend": "rules", "available": False, "backend_version": "rules-v1",
        "reason": "LTP analyzer was not supplied",
    }
    entities, events = _normalize_ltp(text, nlp)
    questions = [
        {"text": match.group(), "start": match.start(), "end": match.end()}
        for match in _QUESTION.finditer(text)
    ]
    times = [
        {"text": match.group(), "start": match.start(), "end": match.end()}
        for match in _TIME.finditer(text)
    ]
    conflicts = [
        {"text": match.group(), "start": match.start(), "end": match.end()}
        for match in _CONFLICT.finditer(text)
    ]
    first_lines = [line.strip() for line in text.splitlines() if line.strip()][:3]
    prose = analyze_prose(text)
    narrative_ledger = build_narrative_ledger(text, nlp)
    result = {
        "analysis_version": ANALYSIS_VERSION,
        "text_hash": _hash(text),
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
        "payoffs": [],
        "originality": _originality(text, entities, comparison_sources or []),
        "narrative_ledger": narrative_ledger,
    }
    result["baseline_comparison"] = _compare_market_baseline(result, market_baseline)
    return result


def analysis_matches(report: dict, text: str) -> bool:
    return (
        report.get("analysis_version") == ANALYSIS_VERSION
        and report.get("text_hash") == _hash(text)
    )


def compact_analysis(report: dict, *, max_findings: int = 12) -> dict:
    prose = report.get("prose", {})
    return {
        "analysis_version": report.get("analysis_version"),
        "text_hash": report.get("text_hash"),
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


def _originality(text: str, entities: list[dict], sources: list[dict[str, str]]) -> dict:
    passages, names, semantic = [], [], []
    manuscript_names = {item["text"] for item in entities if len(item["text"]) in (2, 3)}
    if not manuscript_names:
        manuscript_names.update(_NAME.findall(text))
    manuscript_terms = _terms(text)
    for source in sources:
        source_text = str(source.get("text", ""))
        source_id = str(source.get("id", "unknown"))
        matcher = SequenceMatcher(None, text, source_text, autojunk=False)
        for block in matcher.get_matching_blocks():
            candidate = text[block.a:block.a + block.size]
            han_count = len(_HAN.findall(candidate))
            if han_count >= 6:
                passages.append({
                    "source_id": source_id, "manuscript_start": block.a,
                    "source_start": block.b, "text": candidate,
                    "characters": block.size,
                })
        source_names = set(_NAME.findall(source_text))
        for left in manuscript_names:
            for right in source_names:
                score = SequenceMatcher(None, left, right).ratio()
                if left != right and score >= 0.66:
                    names.append({
                        "source_id": source_id, "manuscript_name": left,
                        "source_name": right, "similarity": round(score, 3),
                    })
        shared = sorted(manuscript_terms & _terms(source_text))
        if shared:
            kinds = []
            if any(_SETTING.search(item) for item in shared):
                kinds.append("setting")
            if any(_PLOT.search(item) for item in shared):
                kinds.append("key_plot")
            if passages:
                kinds.append("distinctive_expression")
            for kind in kinds or ["key_plot"]:
                semantic.append({
                    "kind": kind, "source_id": source_id,
                    "manuscript_window": 1, "source_excerpt": source_text[:240],
                    "shared_terms": shared[:20], "requires_model_review": True,
                })
    return {
        "continuous_passages": passages,
        "similar_names": _dedupe(names),
        "semantic_candidates": semantic,
        "scope": "local_corpus_only",
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
