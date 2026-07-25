import re
from collections import Counter


ANALYZER = "local-editorial"
VERSION = "1"
_SENTENCE = re.compile(r"[^。！？!?]+[。！？!?]?")
_DIALOGUE_START = ("“", '"', "‘", "'")


def analyze_prose(text: str) -> dict[str, object]:
    sentences = _sentences(text)
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    lengths = [len(_plain(item[0])) for item in sentences]
    findings: list[dict[str, object]] = []

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
        findings.append(_finding(
            "repeated_phrase", "review", text, *repeated,
            "短距离内出现完全重复的表达",
            "删除重复内容，或让第二次出现承担不同的叙事作用",
        ))

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
    for match in _SENTENCE.finditer(text):
        sentence = match.group().strip()
        if sentence:
            offset = match.start() + len(match.group()) - len(match.group().lstrip())
            result.append((sentence, offset, offset + len(sentence)))
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
