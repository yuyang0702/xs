import re
from collections import Counter

from novel_flywheel.prose_quality import split_prose_sentences


ANALYZER = "local-editorial"
VERSION = "2"
_SENTENCE = re.compile(r"[^。！？!?]+[。！？!?]?")
_DIALOGUE_START = ("“", '"', "‘", "'")


def analyze_prose(text: str, baseline: dict | None = None) -> dict[str, object]:
    sentences = _sentences(text)
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    lengths = [len(_plain(item[0])) for item in sentences]
    findings: list[dict[str, object]] = []
    baseline = baseline or {}

    if _is_checklist_judgment(sentences):
        start = sentences[0][1]
        end = sentences[min(2, len(sentences) - 1)][2]
        findings.append(_finding(
            "checklist_judgment", "review", text, start, end,
            "连续判断缺少观察、推断或行动过程",
            "把结论还原为人物可感知的证据、有限判断和有代价的行动",
        ))

    functional = _functional_repetition(text, paragraphs)
    if functional:
        findings.append(_finding(
            "functional_repetition", "review", text, *functional,
            "相邻段落反复表达相同的停顿或沉默功能",
            "保留最有效的一处，其余位置改为新的动作、信息或关系变化",
        ))

    repeated = _repeated_phrase(text)
    if repeated:
        item = _finding(
            "repeated_phrase", "review", text, *repeated,
            "短距离内出现完全重复的表达",
            "删除重复内容，或让第二次出现承担不同的叙事作用",
        )
        item["intentional_repetition_candidate"] = _intentional_repetition(text, *repeated)
        if item["intentional_repetition_candidate"]:
            item["message"] = "重复表达附近存在循环或状态变化信号，可能是有意复现"
            item["repair_goal"] = "确认第二次出现是否承担新的信息、状态或情绪叙事作用；有效循环锚点可以保留"
        findings.append(item)

    dialogue = _dialogue_run(text, paragraphs)
    if dialogue:
        findings.append(_finding(
            "mechanical_dialogue_run", "review", text, *dialogue,
            "连续对白缺少动作、观察、迟疑或关系状态变化",
            "只在有意义的位置插入动作、感知或潜台词，不延长无效问答",
        ))

    if len(lengths) >= 4 and max(lengths) - min(lengths) <= 2:
        findings.append(_finding(
            "regular_sentence_rhythm", "review", text, sentences[0][1], sentences[-1][2],
            "连续句子长度过于整齐，节奏缺少场景驱动的变化",
            "根据动作速度、注意力和情绪变化调整句子节奏",
        ))

    one_sentence = [item for item in paragraphs if len(_sentences(item)) == 1 and len(_plain(item)) < 24]
    if len(one_sentence) >= int(baseline.get("one_sentence_paragraph_run", 4)):
        start, end = text.find(one_sentence[0]), text.find(one_sentence[-1]) + len(one_sentence[-1])
        findings.append(_finding(
            "one_sentence_paragraph_run", "review", text, start, end,
            "连续单句段落让节奏呈现模板化断裂", "按场景动作、观察与因果关系合并必要段落",
        ))

    body = re.findall(r"(?:皱了皱眉|抿了抿唇|攥紧(?:了)?手|心头一紧|呼吸一滞)", text)
    if len(body) >= int(baseline.get("body_reaction_repeat", 3)):
        phrase = Counter(body).most_common(1)[0][0]
        start, end = text.find(phrase), text.rfind(phrase) + len(phrase)
        findings.append(_finding(
            "repeated_body_reaction", "review", text, start, end,
            "相同身体反应被重复用来代替不同情绪", "改用与人物目标、环境和关系变化相关的具体反应",
        ))

    certainty = re.search(r"(?:显然|毫无疑问|她很确定|他很确定|一定是).{0,35}(?:。|！|？)", text)
    if certainty:
        findings.append(_finding(
            "unsupported_certainty", "review", text, certainty.start(), certainty.end(),
            "人物判断显得过度确定，正文未给出足够证据", "补充可感知证据、经验来源或保留合理的不确定性",
        ))

    for forbidden in baseline.get("forbidden_patterns", []):
        if forbidden and (index := text.find(str(forbidden))) >= 0:
            findings.append(_finding(
                "project_forbidden_pattern", "blocking", text, index, index + len(str(forbidden)),
                "出现项目明确禁用的表达", "按项目文笔基线替换该表达",
            ))

    return {
        "analyzer": ANALYZER,
        "version": VERSION,
        "metrics": {
            "character_count": len(text),
            "sentence_count": len(sentences),
            "paragraph_count": len(paragraphs),
            "dialogue_paragraph_count": sum(item.startswith(_DIALOGUE_START) for item in paragraphs),
            "average_sentence_length": round(sum(lengths) / len(lengths), 2) if lengths else 0,
        },
        "findings": findings,
    }


def _sentences(text: str) -> list[tuple[str, int, int]]:
    result = []
    cursor = 0
    for sentence in split_prose_sentences(text):
        offset = text.find(sentence, cursor)
        if offset < 0:
            offset = cursor
        result.append((sentence, offset, offset + len(sentence)))
        cursor = offset + len(sentence)
    return result


def _plain(sentence: str) -> str:
    return re.sub(r"[\s。！？!?，“”‘’\"']", "", sentence)


def _is_checklist_judgment(sentences: list[tuple[str, int, int]]) -> bool:
    if len(sentences) < 3:
        return False
    sample = [item[0] for item in sentences[:3]]
    judgment_markers = sum(bool(re.search(r"是|没|没有|不能|不该|应该|先别|暂时", item)) for item in sample)
    return judgment_markers >= 2 and all(len(_plain(item)) <= 18 for item in sample)


def _functional_repetition(text: str, paragraphs: list[str]) -> tuple[int, int] | None:
    quiet = [item for item in paragraphs if re.search(r"沉默|没(?:有)?说话|一言不发|安静下来", item)]
    if len(quiet) < 3:
        return None
    start = text.find(quiet[0])
    end = text.find(quiet[-1], start) + len(quiet[-1])
    return start, end


def _repeated_phrase(text: str) -> tuple[int, int] | None:
    compact = re.sub(r"\s+", "", text)
    phrases = re.findall(r"[\u4e00-\u9fff]{6,}", compact)
    duplicate = next((item for item, count in Counter(phrases).items() if count > 1), None)
    if duplicate:
        first = text.find(duplicate)
        second = text.find(duplicate, first + len(duplicate))
        return first, second + len(duplicate)
    for phrase in phrases:
        for width in range(min(12, len(phrase)), 5, -1):
            chunks = [phrase[index:index + width] for index in range(len(phrase) - width + 1)]
            repeated = next((item for item, count in Counter(chunks).items() if count > 1), None)
            if repeated:
                first = text.find(repeated)
                second = text.find(repeated, first + len(repeated))
                if first >= 0 and second >= 0:
                    return first, second + len(repeated)
    return None


def _intentional_repetition(text: str, start: int, end: int) -> bool:
    nearby = text[max(0, start - 80):min(len(text), end + 120)]
    loop_signal = re.search(r"第[一二三四五六七八九十\d]+(?:轮|次|天)|循环|重来|再次|又一次|重新", nearby)
    change_signal = re.search(r"但|却|变化|改变|换了|不同|多了|少了|不再|这一次", nearby)
    return bool(loop_signal and change_signal)


def _dialogue_run(text: str, paragraphs: list[str]) -> tuple[int, int] | None:
    run: list[str] = []
    longest: list[str] = []
    for paragraph in paragraphs:
        if paragraph.startswith(_DIALOGUE_START):
            run.append(paragraph)
            if len(run) > len(longest):
                longest = list(run)
        else:
            run = []
    if len(longest) < 3:
        return None
    start = text.find(longest[0])
    end = text.find(longest[-1], start) + len(longest[-1])
    return start, end


def _finding(rule_id: str, severity: str, text: str, start: int, end: int,
             message: str, repair_goal: str) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "start": start,
        "end": end,
        "evidence": text[start:end],
        "message": message,
        "repair_goal": repair_goal,
    }
