from __future__ import annotations

from novel_flywheel.originality import (
    OriginalityEngine,
    OriginalitySourceChunkV1,
    affected_segments,
)
from novel_flywheel.db import Database


class _ParaphraseEncoder:
    def encode(self, texts: list[str]) -> list[list[float]]:
        # The engine owns batching and similarity; a production adapter may use
        # Sentence Transformers or another locally configured embedding model.
        return [[1.0, 0.5] for _text in texts]


class _RecordingEncoder:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        return [[1.0, 0.5] for _text in texts]


def test_winnowing_detects_literal_reuse_with_exact_offsets() -> None:
    source = "序章。" + "雨水沿着生锈的门牌滴落，他第三次听见地下室传来钟声。" + "尾声。"
    manuscript = "开头不同。" + "雨水沿着生锈的门牌滴落，他第三次听见地下室传来钟声。" + "后来改变。"

    report = OriginalityEngine().scan(manuscript, [{"id": "source", "text": source}])
    literal = [item for item in report.findings if item.finding_type == "literal_winnowing"]

    assert literal
    finding = literal[0]
    assert manuscript[finding.manuscript_start:finding.manuscript_end]
    assert source[finding.source_start:finding.source_end]
    assert affected_segments(report, [(1, 0, 8), (2, 8, len(manuscript))]) == [2]


def test_typed_source_chunk_translates_findings_to_absolute_version_offsets() -> None:
    copied = "雨水沿着生锈门牌滴落，地下室的旧钟连续响了三次。"
    chunk = OriginalitySourceChunkV1(
        id="reference:source:version",
        text=f"块首。{copied}块尾。",
        source_start=120_000,
        source_end=120_000 + len(f"块首。{copied}块尾。"),
        chunk_index=3,
        chunk_count=8,
        version_id="version",
        version_sha256="a" * 64,
    )

    report = OriginalityEngine().scan(f"开头。{copied}结尾。", [chunk])
    finding = next(
        item for item in report.findings
        if item.finding_type == "literal_winnowing"
    )

    assert finding.source_start >= 120_000
    assert finding.source_end <= chunk.source_end
    assert finding.metadata == {
        "fingerprint_count": finding.metadata["fingerprint_count"],
        "source_chunk_start": 120_000,
        "source_chunk_end": chunk.source_end,
        "source_chunk_index": 3,
        "source_chunk_count": 8,
        "source_version_id": "version",
        "source_version_sha256": "a" * 64,
    }


def test_semantic_window_marks_close_repackaging_for_review() -> None:
    source = (
        "调查员为了拿到证据潜入仓库，被守卫发现后失去同伴，"
        "但他从破损账本中确认了幕后交易，并决定公开真相。"
    ) * 6
    manuscript = (
        "侦探为取得证据进入库房，遭人阻拦并与伙伴失散，"
        "随后凭残缺账册查明暗中交易，最终选择把事实公之于众。"
    ) * 6

    report = OriginalityEngine(
        semantic_threshold=0.45, encoder=_ParaphraseEncoder(),
    ).scan(
        manuscript, [{"id": "source", "text": source}],
    )

    candidates = [
        item for item in report.findings if item.finding_type == "semantic_candidate"
    ]
    assert candidates
    assert candidates[0].metadata["candidate_method"] == "semantic_encoder"


def test_chunked_semantic_scan_encodes_manuscript_once_then_streams_sources() -> None:
    encoder = _RecordingEncoder()
    manuscript = "调查员进入仓库寻找证据。" * 50
    chunks = [
        OriginalitySourceChunkV1(
            id="reference:source:version",
            text=("侦探潜入库房查找证据。" * 45),
            source_start=index * 5_000,
            source_end=index * 5_000 + len("侦探潜入库房查找证据。" * 45),
            chunk_index=index,
            chunk_count=2,
            version_id="version",
            version_sha256="b" * 64,
        )
        for index in range(2)
    ]

    OriginalityEngine(encoder=encoder).scan(manuscript, chunks)

    assert len(encoder.batches) == 3
    assert encoder.batches[0]
    assert all(text in manuscript for text in encoder.batches[0])
    assert all(
        all("调查员" not in text for text in batch)
        for batch in encoder.batches[1:]
    )


def test_event_chain_detects_same_three_step_structure_without_matching_prose() -> None:
    manuscript_events = [
        {"signature": "search|archive"},
        {"signature": "confront|witness"},
        {"signature": "publish|proof"},
        {"signature": "leave|city"},
    ]
    source_events = [
        {"signature": "search|archive"},
        {"signature": "confront|witness"},
        {"signature": "publish|proof"},
    ]

    report = OriginalityEngine().scan(
        "completely different prose", [{
            "id": "source", "text": "unrelated wording", "events": source_events,
        }], manuscript_events=manuscript_events,
    )

    assert any(item.finding_type == "event_chain" for item in report.findings)


def test_originality_audit_is_hash_only_and_idempotent(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("book", "Book", "short", tmp_path / "book")
    db.create_run("run", "book", "short-story", status="running")
    report = OriginalityEngine().scan(
        "A long exact phrase that must be audited safely.",
        [{"id": "local-source", "text": "A long exact phrase that must be audited safely."}],
    )
    findings = [item.model_dump(mode="json") for item in report.findings]

    first = db.record_originality_findings(
        project_id="book", run_id="run", label="publish", findings=findings,
    )
    second = db.record_originality_findings(
        project_id="book", run_id="run", label="publish", findings=findings,
    )

    assert first == second
    stored = db.list_originality_findings("book", run_id="run")
    assert len(stored) == len(set(first))
    assert "long exact phrase" not in str(stored).casefold()
