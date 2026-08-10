from __future__ import annotations

from difflib import SequenceMatcher
import re


def align_unique_evidence_span(source: str, evidence: object) -> str:
    """Return one informative exact source span selected by fuzzy evidence.

    The conversion is deliberately extractive.  It never invents a quote and
    rejects weak, repeated, or low-overlap matches so a caller can use its
    normal minimal-regeneration path when equivalence cannot be proved.
    """

    candidate = str(evidence or "").strip()
    if not candidate or not source:
        return ""
    if candidate in source:
        return candidate if source.count(candidate) == 1 else ""
    match = SequenceMatcher(
        None, candidate, source, autojunk=False,
    ).find_longest_match(0, len(candidate), 0, len(source))
    span = source[match.b:match.b + match.size].strip()
    if not span or source.count(span) != 1:
        return ""
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", span))
    latin_words = re.findall(r"[A-Za-z0-9]+", span)
    informative = cjk_count >= 12 or (
        len(span) >= 20 and len(latin_words) >= 4
    )
    if not informative:
        return ""
    if len(span) / max(1, len(candidate)) < 0.20:
        return ""
    return span
