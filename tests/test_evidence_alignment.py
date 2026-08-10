import pytest

from novel_flywheel.evidence_alignment import align_unique_evidence_span


@pytest.mark.parametrize(("source", "evidence"), (
    (
        "The archivist opens the sealed registry before sunset and records every transfer.",
        "The archivist opens the sealed registry ... and records every transfer.",
    ),
    (
        "巡夜人先核对城门交接记录，再把缺失的时刻逐项写入值守册。",
        "巡夜人先核对城门交接记录……再把缺失的时刻写入值守册。",
    ),
))
def test_align_unique_evidence_span_returns_only_an_exact_source_span(
    source: str, evidence: str,
) -> None:
    aligned = align_unique_evidence_span(source, evidence)

    assert aligned
    assert aligned in source
    assert source.count(aligned) == 1


def test_align_unique_evidence_span_is_idempotent_for_exact_evidence() -> None:
    source = "A sufficiently informative exact evidence phrase remains unchanged."

    assert align_unique_evidence_span(source, source) == source


def test_align_unique_evidence_span_rejects_repeated_exact_evidence() -> None:
    phrase = "A sufficiently informative exact evidence phrase remains unchanged."

    assert align_unique_evidence_span(phrase + " " + phrase, phrase) == ""


@pytest.mark.parametrize(("source", "evidence"), (
    (
        "the same informative evidence phrase appears here; " * 2,
        "the same informative evidence phrase ... appears here",
    ),
    ("A short source.", "short ... source"),
    ("", "an otherwise informative evidence phrase"),
))
def test_align_unique_evidence_span_rejects_repeated_weak_or_missing_sources(
    source: str, evidence: str,
) -> None:
    assert align_unique_evidence_span(source, evidence) == ""
