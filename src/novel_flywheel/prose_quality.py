import re
from statistics import mean
from typing import Any


SEGMENT_SEPARATOR = "<!-- NOVEL_FLYWHEEL_SEGMENT -->"
PRODUCTION_PATTERNS = (
    r"以下(?:是|为).{0,20}(?:润色|修改|改写)(?:后|的)?(?:版本|正文)",
    r"(?:本片段|这个片段).{0,30}(?:不含|已经|修改)",
    r"(?:修改说明|润色说明|审核结论|作为AI|作为 AI)",
)
FORMULA_PATTERNS = (
    ("timestamp_scene_fragment", r"[-\u2014]{2}\s*[\u96f6\u3007\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\d]{1,4}[\u70b9\u65f6\u6642:\uff1a][^\u3002\uff01\uff1f\n]{0,12}[\u3002\uff01\uff1f]\s*[^\u201c\u201d\n]{4,45}[\u3002\uff01\uff1f]"),
    ("epiphany_formula", r"这一刻.{0,12}(?:终于)?明白"),
    ("binary_formula", r"不是.{0,28}而是"),
    ("vague_metaphor", r"仿佛在(?:诉说|提醒|宣告)"),
    ("emotion_explained", r"(?:他|她)(?:这才)?明白了?[,，：:]"),
)
WEAK_ADVERBS = re.compile(r"微微|缓缓|轻轻|猛地|悄然|不由得|下意识")
THEME_ENDING = re.compile(r"(?:这座城市|这个时代|命运|时代).{0,30}(?:仍|还|继续|向前|运转|洪流)")


def _segment_for(text: str, offset: int) -> int:
    return text[:offset].count(SEGMENT_SEPARATOR) + 1


def _finding(code: str, text: str, match: re.Match[str], blocking: bool = False,
             severity: str = "medium") -> dict[str, Any]:
    start = max(0, match.start() - 28)
    end = min(len(text), match.end() + 48)
    return {
        "code": code,
        "severity": "critical" if blocking else severity,
        "blocking": blocking,
        "segment": _segment_for(text, match.start()),
        "excerpt": text[start:end].replace("\n", " ").strip(),
        "count": 1,
    }


def analyze_prose(text: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for pattern in PRODUCTION_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            findings.append(_finding("production_text", text, match, True))
    for code, pattern in FORMULA_PATTERNS:
        matches = list(re.finditer(pattern, text))
        if matches:
            item = _finding(code, text, matches[0])
            item["count"] = len(matches)
            findings.append(item)
    weak = list(WEAK_ADVERBS.finditer(text))
    if len(weak) >= max(4, len(text) // 2500):
        item = _finding("weak_adverb_density", text, weak[0], severity="low")
        item["count"] = len(weak)
        findings.append(item)
    ending_start = max(0, len(text) - 500)
    ending_match = THEME_ENDING.search(text, ending_start)
    if ending_match:
        findings.append(_finding("theme_summary_ending", text, ending_match, severity="high"))
    metrics = prose_metrics(text)
    if metrics["one_sentence_paragraph_run"] >= 3:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
        sample = next((item for item in paragraphs if _sentence_count(item) == 1), text[:80])
        match = re.search(re.escape(sample), text)
        if match:
            item = _finding("one_sentence_paragraph_run", text, match)
            item["count"] = int(metrics["one_sentence_paragraph_run"])
            item["action"] = (
                "Merge consecutive one-sentence paragraphs that describe one continuous action; "
                "keep paragraph breaks only for dialogue, emphasis, suspense, or scene changes."
            )
            findings.append(item)
    if metrics["short_sentence_run"] >= 3:
        fake = re.search(r"[^。！？\n]{1,14}[。！？]", text)
        if fake:
            findings.append(_finding("uniform_short_sentence_run", text, fake))
    if metrics["dialogue_turn_run"] >= 4:
        fake = re.search(r"(?m)^[“\"]", text)
        if fake:
            item = _finding("dialogue_ping_pong", text, fake)
            item["count"] = int(metrics["dialogue_turn_run"])
            item["action"] = (
                "Break up four or more consecutive dialogue-only paragraphs with meaningful "
                "action, observation, hesitation, or changed subtext."
            )
            findings.append(item)
    blocking_count = sum(item["count"] for item in findings if item["blocking"])
    targeted_count = sum(item["count"] for item in findings if not item["blocking"])
    penalty = blocking_count * 30 + min(45, targeted_count * 5)
    return {
        "naturalness_score": max(0, 100 - penalty),
        "blocking_count": blocking_count,
        "targeted_count": targeted_count,
        "findings": findings,
        "metrics": metrics,
    }


def prose_metrics(text: str) -> dict[str, float]:
    clean = text.replace(SEGMENT_SEPARATOR, "")
    sentences = [item.strip() for item in re.split(r"[。！？.!?]+", clean) if item.strip()]
    lengths = [len(item) for item in sentences] or [0]
    short_run = run = 0
    for length in lengths:
        run = run + 1 if length <= 14 else 0
        short_run = max(short_run, run)
    dialogue_chars = sum(len(item) for item in re.findall(r"[“\"][^”\"\n]+[”\"]", clean))
    paragraph_run = dialogue_run = run = 0
    dialogue_current = 0
    for paragraph in (item.strip() for item in re.split(r"\n\s*\n", clean)):
        is_single = bool(paragraph) and not paragraph.startswith("#") and _sentence_count(paragraph) == 1
        run = run + 1 if is_single else 0
        paragraph_run = max(paragraph_run, run)
        dialogue_current = dialogue_current + 1 if paragraph.startswith(("“", '"')) else 0
        dialogue_run = max(dialogue_run, dialogue_current)
    return {
        "mean_sentence_length": round(mean(lengths), 2),
        "short_sentence_ratio": round(sum(length <= 14 for length in lengths) / len(lengths), 3),
        "short_sentence_run": float(short_run),
        "one_sentence_paragraph_run": float(paragraph_run),
        "dialogue_turn_run": float(dialogue_run),
        "dialogue_ratio": round(dialogue_chars / max(1, len(clean)), 3),
        "weak_adverb_density": round(len(WEAK_ADVERBS.findall(clean)) * 1000 / max(1, len(clean)), 3),
    }


def _sentence_count(text: str) -> int:
    return len(re.findall(r"[。！？.!?](?:[”\"']|$)", text.strip()))


def compare_voice_metrics(current: dict[str, float], history: list[dict[str, float]]) -> dict[str, Any]:
    if not history:
        return {"drifted": False, "blocking": False, "signals": []}
    history = history[-5:]
    signals = []
    thresholds = {
        "mean_sentence_length": 0.45,
        "short_sentence_ratio": 0.35,
        "dialogue_ratio": 0.35,
        "weak_adverb_density": 1.0,
    }
    for key, threshold in thresholds.items():
        baseline = mean(item.get(key, 0.0) for item in history)
        delta = abs(current.get(key, 0.0) - baseline)
        relative = delta / max(abs(baseline), 0.05)
        if relative > threshold:
            signals.append({"metric": key, "current": current.get(key), "baseline": round(baseline, 3)})
    return {"drifted": bool(signals), "blocking": False, "signals": signals}
