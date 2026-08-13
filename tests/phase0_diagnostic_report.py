"""Generate hash-only Phase 0 diagnostic and overhead reports."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from novel_flywheel.generated_artifacts import ReliabilityTraceEnvelopeV1
from novel_flywheel.reliability_trace import (
    BestEffortTraceSink,
    artifact_binding_matrix,
    authority_lineage,
    event_type_coverage_matrix,
    projection_provenance_matrix,
    projection_reconciliation,
    read_trace,
    recovery_attempt_dag,
    repair_diff_view,
    trace_coverage_matrix,
)


def diagnostic_report(path: Path) -> dict:
    trace = read_trace(path)
    return {
        "schema": "Phase0ReliabilityDiagnosticReportV1",
        "trace_event_count": len(trace.events),
        "reader_coverage_gaps": trace.coverage_gaps,
        "authority_lineage": authority_lineage(trace.events),
        "projection_reconciliation": projection_reconciliation(trace.events),
        "projection_provenance_matrix": projection_provenance_matrix(
            trace.events,
        ),
        "artifact_binding_matrix": artifact_binding_matrix(trace.events),
        "repair_diff": repair_diff_view(trace.events),
        "recovery_attempt_dag": recovery_attempt_dag(trace.events),
        "trace_coverage_matrix": trace_coverage_matrix(trace.events),
        "event_type_coverage_matrix": event_type_coverage_matrix(
            trace.events,
        ),
    }


def _benchmark_event(index: int) -> ReliabilityTraceEnvelopeV1:
    return ReliabilityTraceEnvelopeV1.model_validate({
        "schema": "ReliabilityTraceEnvelopeV1",
        "event_id": f"benchmark-event-{index:016d}",
        "correlation_id": "benchmark-correlation",
        "event_type": "authority_read",
        "source_component": "benchmark",
        "source_writer": "benchmark",
        "semantic_domain": "occurred_current",
        "observation_status": "confirmed",
        "payload": {"authority_type": "StoryState", "reader": "benchmark"},
    })


def benchmark(iterations: int = 200) -> dict:
    with tempfile.TemporaryDirectory(prefix="phase0-trace-benchmark-") as temporary:
        root = Path(temporary)
        disabled = BestEffortTraceSink(root / "disabled.jsonl", enabled=False)
        started = time.perf_counter_ns()
        for index in range(iterations):
            disabled.emit(_benchmark_event(index))
        disabled_ns = time.perf_counter_ns() - started

        enabled = BestEffortTraceSink(root / "enabled.jsonl", enabled=True)
        started = time.perf_counter_ns()
        for index in range(iterations):
            enabled.emit(_benchmark_event(index))
        enabled_ns = time.perf_counter_ns() - started
        read = read_trace(enabled.path)
        return {
            "schema": "Phase0TraceOverheadReportV1",
            "iterations": iterations,
            "disabled_ns_per_event": disabled_ns / iterations,
            "enabled_ns_per_event": enabled_ns / iterations,
            "enabled_written": enabled.metrics.written,
            "enabled_dropped": enabled.metrics.dropped,
            "write_failure_rate": enabled.metrics.failure_rate,
            "reader_coverage_gap_count": len(read.coverage_gaps),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--trace", type=Path, required=True)
    report_parser.add_argument("--output", type=Path, required=True)
    benchmark_parser = subparsers.add_parser("benchmark")
    benchmark_parser.add_argument("--iterations", type=int, default=200)
    benchmark_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = (
        diagnostic_report(args.trace)
        if args.command == "report" else benchmark(args.iterations)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
