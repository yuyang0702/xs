from __future__ import annotations

import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from novel_flywheel.generated_artifacts import ReliabilityTraceEnvelopeV1
from novel_flywheel.reliability_trace import (
    BestEffortTraceSink,
    canonical_hash,
    read_trace,
    trace_file_for_project,
)
from phase0_baseline_harness import canonical_hash as baseline_hash
from phase0_diagnostic_report import benchmark


def _process_append(arguments: tuple[str, int]) -> bool:
    path, index = arguments
    sink = BestEffortTraceSink(Path(path))
    return sink.emit(event("shared-process-correlation", event_id=f"event-{index:016d}"))


def event(correlation_id: str = "corr-a", **changes) -> ReliabilityTraceEnvelopeV1:
    payload = {
        "schema": "ReliabilityTraceEnvelopeV1",
        "event_id": "event-0000000000000001",
        "correlation_id": correlation_id,
        "run_id": None,
        "stage_id": "stage",
        "event_type": "authority_read",
        "source_component": "tests",
        "source_writer": "observer",
        "semantic_domain": "occurred_current",
        "observation_status": "confirmed",
        "payload": {"authority_type": "StoryState", "reader": "tests"},
    }
    payload.update(changes)
    return ReliabilityTraceEnvelopeV1.model_validate(payload)


def test_envelope_requires_shadow_claims_to_be_non_authoritative() -> None:
    with pytest.raises(ValidationError):
        event(
            event_type="proposed_claim",
            payload={
                "claim_kind": "location", "shadow_only": False,
                "affects_business_decision": False,
            },
        )


def test_unknown_or_cross_domain_evidence_cannot_be_emitted_as_conflict() -> None:
    with pytest.raises(ValidationError):
        event(
            event_type="authority_evidence_conflict",
            semantic_domain="unknown",
            observation_status="unknown",
            payload={
                "shadow_slot": "character:location", "story_time": "chapter-1",
                "left_source_hash": "a" * 64, "right_source_hash": "b" * 64,
                "values_disagree": True, "resolution": "unresolved_phase0",
            },
        )


def test_canonical_hash_matches_baseline_and_ignores_declared_volatility(tmp_path: Path) -> None:
    left = {"b": True, "a": None, "created_at": "a", "run_id": "one",
            "project_path": str(tmp_path / "project")}
    right = {"project_path": str(tmp_path / "project"), "run_id": "two",
             "created_at": "b", "a": None, "b": True}
    assert canonical_hash(left, root=tmp_path) == canonical_hash(right, root=tmp_path)
    assert canonical_hash(left, root=tmp_path) == baseline_hash(left, root=tmp_path)


def test_trace_is_physically_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "data" / "projects" / "project-a"
    project.mkdir(parents=True)
    path = trace_file_for_project(project)
    assert not path.resolve().is_relative_to(project.resolve())
    assert path.parent.parent.name == "reliability-traces"


def test_sink_is_fail_open_for_write_and_privacy_failures(tmp_path: Path, monkeypatch) -> None:
    sink = BestEffortTraceSink(tmp_path / "trace.jsonl")
    monkeypatch.setattr(os, "write", lambda *_args: (_ for _ in ()).throw(OSError("disk")))
    assert sink.emit(event()) is False
    assert sink.metrics.dropped == 1
    assert not sink.path.exists() or sink.path.read_bytes() == b""

    unsafe = event(payload={"authority_type": "StoryState", "reader": "tests",
                            "prompt": "must never persist"})
    assert sink.emit(unsafe) is False
    assert sink.metrics.dropped == 2


def test_disabled_sink_has_no_file_and_no_failure(tmp_path: Path) -> None:
    sink = BestEffortTraceSink(tmp_path / "trace.jsonl", enabled=False)
    assert sink.emit(event()) is False
    assert sink.metrics.attempted == 1
    assert sink.metrics.dropped == 0
    assert not sink.path.exists()


def test_concurrent_append_produces_complete_monotonic_json_lines(tmp_path: Path) -> None:
    sink = BestEffortTraceSink(tmp_path / "trace.jsonl")
    correlations = ["corr-a", "corr-b"]
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(
            lambda index: sink.emit(event(correlations[index % 2], event_id=f"event-{index:016d}")),
            range(80),
        ))
    assert all(results)
    raw_lines = sink.path.read_bytes().splitlines(keepends=True)
    assert len(raw_lines) == 80
    assert all(line.endswith(b"\n") for line in raw_lines)
    assert all(isinstance(json.loads(line), dict) for line in raw_lines)
    report = read_trace(sink.path)
    assert not report.coverage_gaps
    for correlation in correlations:
        sequences = [item.sequence for item in report.events if item.correlation_id == correlation]
        assert sequences == list(range(1, len(sequences) + 1))


def test_multiprocess_append_produces_complete_monotonic_json_lines(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=4, mp_context=context) as executor:
        results = list(executor.map(_process_append, [(str(path), index) for index in range(20)]))
    # Lock contention is allowed to drop observations, but every accepted line
    # must be complete and monotonic for its correlation.
    assert any(results)
    report = read_trace(path)
    assert not report.coverage_gaps
    assert len(report.events) == sum(results)
    assert [item.sequence for item in report.events] == list(range(1, len(report.events) + 1))


def test_reader_reports_corrupt_tail_and_sequence_gap_without_fabrication(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    sink = BestEffortTraceSink(path)
    assert sink.emit(event())
    second = event(event_id="event-0000000000000002").model_copy(update={"sequence": 3})
    with path.open("ab") as handle:
        handle.write(second.model_dump_json().encode("utf-8") + b"\n")
        handle.write(b'{"broken":')
    report = read_trace(path)
    assert len(report.events) == 2
    assert {gap["reason"] for gap in report.coverage_gaps} == {
        "sequence_gap", "incomplete_tail",
    }


def test_overhead_report_is_hash_only_and_reports_failures_and_gaps() -> None:
    report = benchmark(20)
    assert report["iterations"] == 20
    assert report["enabled_written"] == 20
    assert report["enabled_dropped"] == 0
    assert report["write_failure_rate"] == 0.0
    assert report["reader_coverage_gap_count"] == 0
    assert report["disabled_ns_per_event"] >= 0
    assert report["enabled_ns_per_event"] >= 0
