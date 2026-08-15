from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from novel_flywheel.generated_artifacts import ReliabilityTraceEnvelopeV1
from novel_flywheel.model_diagnostics import (
    ModelDiagnosticContextV1,
    PlanningAdaptationOutputBudgetLineageV1,
    ProviderToolShapeSnapshotV1,
    StrictToolShapeObservationV1,
    ToolCallShapeV1,
    build_budget_lineage_record,
    diagnostic_flag_enabled,
    domain_sha256,
    provider_tool_shape_snapshot,
)
from novel_flywheel.reliability_trace import BestEffortTraceSink
from test_model_diagnostics import strict_observation


SPECS = Path(__file__).parents[1] / "docs" / "superpowers" / "specs"
ALLOWLIST = SPECS / "r1-pa1-diagnostic-human-readable-fields-v1.json"


def _context(tmp_path: Path) -> ModelDiagnosticContextV1:
    return ModelDiagnosticContextV1(
        project_root=tmp_path,
        run_id="controlled-run",
        stage="review",
        boundary="planning_adaptation_whole_receipt",
        role="review",
        route_kind="configured_fallback",
        contract_id="planning_adaptation_whole",
        contract_version=1,
        outer_retry_ordinal=1,
    )


def _budget(tmp_path: Path) -> PlanningAdaptationOutputBudgetLineageV1:
    return build_budget_lineage_record(
        _context(tmp_path),
        lineage_event="request_dispatched",
        original_requested_output_budget=1276,
        current_requested_output_budget=1276,
        previous_attempt_budget=None,
        expansion_trigger=None,
        expansion_requested=False,
        expansion_target=None,
        expansion_target_before_cap=None,
        effective_budget_after_policy=1276,
        effective_budget_after_provider_cap=1276,
        effective_budget_after_canary_cap=1276,
        expansion_applied=False,
        retained_expansion_state=False,
        runtime_reconstructed=False,
        reconstruction_reason=None,
        retry_owner="workflow_outer_receipt_schedule",
        route_kind="configured_fallback",
        finish_reason=None,
        typed_failure=None,
        cap_applied=False,
        cap_source="none",
        cap_sources=(),
        system="private system prompt",
        user="private user prompt",
        contract_schema={"type": "object"},
    )


def _string_fields(model: type) -> set[str]:
    properties = model.model_json_schema(by_alias=True)["properties"]
    result = set()
    for name, schema in properties.items():
        serialized = json.dumps(schema, sort_keys=True)
        if '"type": "string"' in serialized and not (
            name.endswith("sha256") or name.endswith("sha256s")
            or name.endswith("_hashes")
        ):
            result.add(name)
    return result


def test_human_readable_diagnostic_fields_are_closed_and_reviewable() -> None:
    allowlist = json.loads(ALLOWLIST.read_text(encoding="utf-8"))

    assert _string_fields(StrictToolShapeObservationV1) == set(
        allowlist["strict_tool_shape"]
    )
    assert _string_fields(ProviderToolShapeSnapshotV1) == set(
        allowlist["provider_snapshot"]
    )
    assert _string_fields(ToolCallShapeV1) == set(allowlist["tool_call_shape"])
    assert _string_fields(PlanningAdaptationOutputBudgetLineageV1) == set(
        allowlist["budget_lineage"]
    )


def test_sensitive_provider_and_prompt_values_are_absent_from_diagnostic_records(
    tmp_path,
) -> None:
    secrets = {
        "prompt": "PRIVATE_SYSTEM_PROMPT_7e956",
        "prose": "PRIVATE_NARRATIVE_52ca0",
        "argument": "PRIVATE_TOOL_ARGUMENT_4af8e",
        "request": "PRIVATE_REQUEST_ID_f1072",
        "credential": "sk-private-credential-591cd",
        "path": "C:\\private\\novel\\chapter.md",
    }
    snapshot = provider_tool_shape_snapshot(
        adapter_id="anthropic",
        adapter_version=1,
        provider_body=secrets,
        provider_request_id=secrets["request"],
        content_block_count=1,
        text_present=True,
        tool_use_present=True,
        finish_reason="tool_use",
        calls=[{
            "call_id": secrets["request"],
            "name": "planning_adaptation_whole",
            "arguments_present": True,
            "arguments": {"private": secrets["argument"]},
        }],
        snapshot_status="snapshot_exact",
    )
    records = [
        snapshot.model_dump(mode="json", by_alias=True),
        strict_observation(),
        _budget(tmp_path).model_dump(mode="json", by_alias=True),
    ]
    serialized = json.dumps(records, ensure_ascii=False, sort_keys=True)

    for value in secrets.values():
        assert value not in serialized
    for forbidden_key in (
        '"prompt"', '"system_prompt"', '"user_prompt"', '"prose"',
        '"content"', '"raw"', '"credential"', '"secret"', '"api_key"',
    ):
        assert forbidden_key not in serialized.casefold()


def test_disabled_and_enabled_diagnostic_primitive_overhead_and_storage_bounds(
    tmp_path, monkeypatch,
) -> None:
    iterations = 20_000
    monkeypatch.delenv("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1", raising=False)
    started = time.perf_counter_ns()
    for _ in range(iterations):
        assert diagnostic_flag_enabled("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1") is False
    disabled_mean_us = (time.perf_counter_ns() - started) / iterations / 1_000

    hash_iterations = 2_000
    started = time.perf_counter_ns()
    for index in range(hash_iterations):
        domain_sha256("r1-pa1-performance-v1", {"ordinal": index, "shape": [1, 2, 3]})
    enabled_hash_mean_us = (time.perf_counter_ns() - started) / hash_iterations / 1_000

    strict = strict_observation()
    budget = _budget(tmp_path).model_dump(mode="json", by_alias=True)
    strict_bytes = len(json.dumps(strict, separators=(",", ":")).encode("utf-8"))
    budget_bytes = len(json.dumps(budget, separators=(",", ":")).encode("utf-8"))

    sink = BestEffortTraceSink(tmp_path / "trace.jsonl", enabled=True)
    durations = []
    for ordinal in range(100):
        envelope = ReliabilityTraceEnvelopeV1.model_validate({
            "event_id": f"event-performance-{ordinal:04d}",
            "correlation_id": "performance-correlation",
            "sequence": ordinal + 1,
            "timestamp": datetime(2026, 8, 15, tzinfo=timezone.utc),
            "event_type": "diagnostic_strict_tool_shape",
            "source_component": "performance-test",
            "source_writer": "performance-test",
            "observation_status": "confirmed",
            "payload": strict,
        })
        started = time.perf_counter_ns()
        assert sink.emit(envelope) is True
        durations.append((time.perf_counter_ns() - started) / 1_000)
    append_mean_us = statistics.mean(durations)
    append_p95_us = sorted(durations)[94]

    metrics = {
        "disabled_flag_check_mean_us": round(disabled_mean_us, 3),
        "enabled_canonical_hash_mean_us": round(enabled_hash_mean_us, 3),
        "jsonl_append_mean_us": round(append_mean_us, 3),
        "jsonl_append_p95_us": round(append_p95_us, 3),
        "strict_record_bytes": strict_bytes,
        "budget_record_bytes": budget_bytes,
        "append_failures": sink.metrics.dropped,
    }
    print("R1_PA1_PERFORMANCE=" + json.dumps(metrics, sort_keys=True))

    assert disabled_mean_us < 1_000
    assert enabled_hash_mean_us < 10_000
    assert append_p95_us < 100_000
    assert strict_bytes < 32 * 1024
    assert budget_bytes < 16 * 1024
    assert sink.metrics.dropped == 0
