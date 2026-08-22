from __future__ import annotations

import json

import pytest

from novel_flywheel.domain.models import Message, ModelRequest, ModelResponse
from novel_flywheel.model_diagnostics import (
    ModelDiagnosticContextV1,
    bind_ptr12_raw_shape_observation,
    build_ptr12_guard_decision,
    current_ptr12_raw_shape,
    open_ptr12_raw_shape_capture,
    observe_ptr12_shape_delta,
    reset_ptr12_raw_shape_capture,
    emit_ptr12_output_limit_classification,
)
from novel_flywheel.provider_output import (
    build_provider_output_shape,
    capture_provider_raw_shape_v1,
)
from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
from novel_flywheel.providers.openai_responses import OpenAIResponsesAdapter
from novel_flywheel.reliability_trace import read_trace, trace_file_for_project


def _context(tmp_path, *, ordinal: int = 1) -> ModelDiagnosticContextV1:
    return ModelDiagnosticContextV1(
        project_root=tmp_path,
        run_id="ptr12-offline-run",
        stage="planning",
        boundary="planning_semantic_v2",
        role="planning",
        route_kind="configured_fallback",
        contract_id="planning_semantic_v2",
        contract_version=2,
        outer_retry_ordinal=1,
        inner_attempt_ordinal=ordinal,
    )


def _capture(monkeypatch, *, protocol, body=None, events=()):
    monkeypatch.setenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1")
    token = open_ptr12_raw_shape_capture()
    try:
        capture_provider_raw_shape_v1(
            protocol=protocol, body=body, events=events,
            requested_output_cap=8798,
        )
        return current_ptr12_raw_shape()
    finally:
        reset_ptr12_raw_shape_capture(token)


@pytest.mark.parametrize(
    ("protocol", "body", "expected"),
    [
        ("anthropic", {
            "stop_reason": "max_tokens",
            "content": [{"type": "thinking", "thinking": "PRIVATE"}],
            "usage": {"output_tokens": 8798},
        }, (1, 0, 0)),
        ("anthropic", {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "PRIVATE"}],
            "usage": {"output_tokens": 9},
        }, (0, 1, 0)),
        ("openai-chat", {
            "choices": [{"finish_reason": "stop", "message": {
                "content": None, "tool_calls": [{"function": {"arguments": "PRIVATE"}}],
            }}], "usage": {"completion_tokens": 7},
        }, (0, 0, 1)),
        ("openai-chat", {
            "choices": [{"finish_reason": "max_tokens", "message": {
                "content": "PRIVATE", "reasoning_content": "PRIVATE_REASONING",
            }}], "usage": {"completion_tokens": 12},
        }, (1, 1, 0)),
        ("openai-responses", {
            "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "reasoning", "summary": [{"text": "PRIVATE"}]}],
            "usage": {"output_tokens": 8798},
        }, (1, 0, 0)),
        ("openai-responses", {
            "status": "completed", "output": [{
                "type": "message", "content": [{"type": "output_text", "text": "PRIVATE"}],
            }], "usage": {"output_tokens": 10},
        }, (0, 1, 0)),
    ],
)
def test_body_shape_cases_are_count_only_and_private(
    monkeypatch, protocol, body, expected,
) -> None:
    snapshot = _capture(monkeypatch, protocol=protocol, body=body)
    serialized = json.dumps(snapshot, sort_keys=True)
    assert (
        snapshot["reasoning_block_count"],
        snapshot["text_or_final_block_count"],
        snapshot["tool_block_count"],
    ) == expected
    assert snapshot["content_omitted"] is True
    assert "PRIVATE" not in serialized


@pytest.mark.parametrize(
    ("protocol", "events", "expected_reasoning", "expected_visible"),
    [
        ("anthropic", [
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
            {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {"output_tokens": 8}},
        ], 1, 0),
        ("openai-chat", [{"choices": [{"finish_reason": "max_tokens", "delta": {
            "reasoning_content": "PRIVATE", "content": "",
        }}]}], 1, 0),
        ("openai-responses", [
            {"type": "response.output_item.added", "item": {"type": "reasoning"}},
            {"type": "response.incomplete", "response": {"status": "incomplete", "usage": {"output_tokens": 8}}},
        ], 1, 0),
    ],
)
def test_stream_shape_is_captured_before_aggregation(
    monkeypatch, protocol, events, expected_reasoning, expected_visible,
) -> None:
    snapshot = _capture(monkeypatch, protocol=protocol, events=events)
    assert snapshot["observation_point"] == "stream_event_shape_pre_aggregation"
    assert snapshot["reasoning_block_count"] == expected_reasoning
    assert snapshot["raw_visible_char_count"] == expected_visible


def test_sequence_and_unknown_bounds(monkeypatch) -> None:
    body = {
        "stop_reason": "end_turn",
        "content": [{"type": f"private-kind-{index}"} for index in range(160)],
        "usage": {},
    }
    snapshot = _capture(monkeypatch, protocol="anthropic", body=body)
    assert snapshot["raw_block_count"] == 160
    assert len(snapshot["raw_block_type_sequence"]) == 128
    assert len(snapshot["unknown_block_type_hashes"]) == 32
    assert snapshot["sequence_omitted_after_limit"] is True
    assert snapshot["capture_completeness"] == "partial"
    assert "private-kind" not in json.dumps(snapshot)


def test_aggregate_usage_is_not_inferred_as_reasoning_or_final(monkeypatch) -> None:
    snapshot = _capture(monkeypatch, protocol="anthropic", body={
        "stop_reason": "max_tokens",
        "content": [{"type": "thinking", "thinking": "PRIVATE"}],
        "usage": {"output_tokens": 8798},
    })
    assert snapshot["output_token_count"] == 8798
    assert snapshot["provider_exposed_reasoning_usage_status"] == "NOT_EXPOSED"
    assert snapshot["provider_exposed_reasoning_usage"] is None
    assert snapshot["provider_exposed_final_usage_status"] == "NOT_EXPOSED"
    assert snapshot["provider_exposed_final_usage"] is None


def test_flag_off_has_no_capture(monkeypatch) -> None:
    monkeypatch.delenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", raising=False)
    assert open_ptr12_raw_shape_capture() is None
    capture_provider_raw_shape_v1(
        protocol="anthropic", body={"content": []}, events=[],
        requested_output_cap=1,
    )
    assert current_ptr12_raw_shape() is None


def test_exact_inner_attempt_binding_and_trace(monkeypatch, tmp_path) -> None:
    snapshot = _capture(monkeypatch, protocol="anthropic", body={
        "stop_reason": "max_tokens", "content": [{"type": "thinking", "thinking": "PRIVATE"}],
        "usage": {"output_tokens": 8798},
    })
    context = _context(tmp_path, ordinal=2)
    record = bind_ptr12_raw_shape_observation(
        context, snapshot=snapshot, provider_id="provider-private",
        model_id="model-private", route_fingerprint="a" * 64,
        schema_sha256="b" * 64, request_mode="plain",
    )
    assert record.correlation_id == context.inner_attempt_id
    assert record.inner_attempt_ordinal == 2
    report = read_trace(trace_file_for_project(tmp_path))
    event = report.events[-1]
    assert event.correlation_id == context.inner_attempt_id
    serialized = event.model_dump_json()
    assert "provider-private" not in serialized
    assert "model-private" not in serialized
    assert "PRIVATE" not in serialized


def _shape(*types: str, finish="max_tokens", visible=0, tools=0):
    return build_provider_output_shape(
        provider_family="anthropic", protocol="anthropic",
        finish_reason=finish, output_tokens=8, block_types=types,
        text_values=(["x" * visible] if visible else []),
        reasoning_block_count=sum(item in {"thinking", "reasoning"} for item in types),
        transport_complete=True, normalized_text="x" * visible,
        normalized_tool_call_count=tools,
    )


@pytest.mark.parametrize(
    ("shape", "triggered", "reason"),
    [
        (_shape("thinking"), True, None),
        (_shape("thinking", finish="stop"), False, "FINISH_REASON_NOT_MAX_TOKENS"),
        (_shape("thinking", "text", visible=1), False, "RAW_VISIBLE_NONZERO"),
        (_shape(), False, "REASONING_BLOCK_ABSENT"),
        (_shape("thinking", "tool_call", tools=1), False, "TOOL_CALL_PRESENT"),
        (_shape("unknown"), False, "REASONING_BLOCK_ABSENT"),
    ],
)
def test_guard_predicate_reason_matrix(
    monkeypatch, tmp_path, shape, triggered, reason,
) -> None:
    monkeypatch.setenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1")
    record = build_ptr12_guard_decision(
        _context(tmp_path), shape=shape, raw_shape=None, delta=None,
        finish_reason=shape.finish_reason, scope_eligible=True,
        guard_triggered=triggered, provider_id="provider", model_id="model",
        route_fingerprint="a" * 64, contract_identity="planning_semantic_v2",
        schema_sha256="b" * 64,
        negative_write_status="RECORDED" if triggered else "NOT_REQUIRED",
    )
    assert record.guard_triggered is triggered
    assert record.predicate_all_true is triggered
    if reason is not None:
        assert reason in record.guard_miss_reasons


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_kind", ["anthropic", "openai_chat", "openai_responses"])
async def test_three_adapters_deposit_snapshot_before_model_response(
    monkeypatch, adapter_kind,
) -> None:
    monkeypatch.setenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1")
    request = ModelRequest(
        model="offline", messages=[Message(role="user", content="PRIVATE_PROMPT")],
        max_output_tokens=8,
    )
    if adapter_kind == "anthropic":
        adapter = AnthropicAdapter("https://offline.invalid/v1", "PRIVATE_SECRET")
        body = {"stop_reason": "max_tokens", "content": [{"type": "thinking", "thinking": "PRIVATE"}], "usage": {"output_tokens": 8}}
    elif adapter_kind == "openai_chat":
        adapter = OpenAIChatAdapter("https://offline.invalid/v1", "PRIVATE_SECRET")
        body = {"choices": [{"finish_reason": "max_tokens", "message": {"content": None, "reasoning_content": "PRIVATE"}}], "usage": {"completion_tokens": 8}}
    else:
        adapter = OpenAIResponsesAdapter("https://offline.invalid/v1", "PRIVATE_SECRET")
        body = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": [{"type": "reasoning", "summary": [{"text": "PRIVATE"}]}], "usage": {"output_tokens": 8}}

    async def fake_post_stream(*_args, **_kwargs):
        return [], body

    monkeypatch.setattr(adapter, "post_stream", fake_post_stream)
    token = open_ptr12_raw_shape_capture()
    try:
        response: ModelResponse = await adapter.complete(request)
        snapshot = current_ptr12_raw_shape()
    finally:
        reset_ptr12_raw_shape_capture(token)
    assert response.text == ""
    assert snapshot["reasoning_block_count"] == 1
    assert "PRIVATE" not in json.dumps(snapshot)


def test_visible_drop_is_typed_representation_delta(monkeypatch, tmp_path) -> None:
    snapshot = _capture(monkeypatch, protocol="anthropic", body={
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "PRIVATE_VISIBLE"}],
        "usage": {"output_tokens": 4},
    })
    context = _context(tmp_path)
    raw = bind_ptr12_raw_shape_observation(
        context, snapshot=snapshot, provider_id="provider", model_id="model",
        route_fingerprint="a" * 64, schema_sha256="b" * 64,
        request_mode="plain",
    )
    normalized = build_provider_output_shape(
        provider_family="anthropic", protocol="anthropic",
        finish_reason="end_turn", output_tokens=4, block_types=["text"],
        text_values=["PRIVATE_VISIBLE"], reasoning_block_count=0,
        transport_complete=True, normalized_text="",
        normalized_tool_call_count=0,
    )
    delta = observe_ptr12_shape_delta(
        context, raw_shape=raw, normalized_shape=normalized,
        normalized_finish_reason="end_turn",
    )
    assert delta.representation_changed == "YES"
    assert "VISIBLE_CHAR_COUNT" in delta.changed_dimensions


def test_raw_unavailable_remains_unknown_not_reasoning(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1")
    normalized = _shape()
    delta = observe_ptr12_shape_delta(
        _context(tmp_path), raw_shape=None, normalized_shape=normalized,
        normalized_finish_reason="max_tokens",
    )
    decision = build_ptr12_guard_decision(
        _context(tmp_path), shape=None, raw_shape=None, delta=delta,
        finish_reason="max_tokens", scope_eligible=True, guard_reached=True,
        guard_triggered=False, provider_id="provider", model_id="model",
        route_fingerprint="a" * 64, contract_identity="planning_semantic_v2",
        schema_sha256="b" * 64,
    )
    assert delta.representation_changed == "UNKNOWN"
    assert decision.shape_available is False
    assert decision.primary_guard_miss_reason == "SHAPE_UNAVAILABLE"


def test_output_limit_classification_uses_same_attempt_identity(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1")
    context = _context(tmp_path, ordinal=3)
    trace_file_for_project(tmp_path).unlink(missing_ok=True)
    assert emit_ptr12_output_limit_classification(
        context, output_limit_seen=True,
        receipt={"finish_reason": "max_tokens", "output_tokens": 8798},
        terminal=True,
    ) is True
    event = read_trace(trace_file_for_project(tmp_path)).events[-1]
    assert event.event_type == "diagnostic_contract_output_limit_classification_v1"
    assert event.correlation_id == context.inner_attempt_id
    assert event.payload["aggregate_output_usage"] == 8798
