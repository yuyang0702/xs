from __future__ import annotations

from collections.abc import Iterator, Mapping
import json

import pytest

import novel_flywheel.provider_output as provider_output
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


class _PoisonMapping(dict):
    def get(self, *_args, **_kwargs):
        raise AssertionError("poison tail was inspected")


class _TrapMapping(Mapping):
    def __init__(self) -> None:
        self.access_count = 0

    def __getitem__(self, _key):
        self.access_count += 1
        raise AssertionError("custom mapping access is forbidden")

    def __iter__(self) -> Iterator[object]:
        self.access_count += 1
        raise AssertionError("custom mapping iteration is forbidden")

    def __len__(self) -> int:
        self.access_count += 1
        raise AssertionError("custom mapping length is forbidden")


class _DestructiveEvents:
    def __init__(self) -> None:
        self.consumed = False

    def __iter__(self):
        self.consumed = True
        yield {"type": "content_block_start"}


class _TrapToken:
    def __init__(self) -> None:
        self.stringified = False

    def __str__(self) -> str:
        self.stringified = True
        raise AssertionError("custom token __str__ is forbidden")

    def __repr__(self) -> str:
        self.stringified = True
        raise AssertionError("custom token __repr__ is forbidden")

    def __bool__(self) -> bool:
        raise AssertionError("custom token truth testing is forbidden")

    def __eq__(self, _other: object) -> bool:
        raise AssertionError("custom token equality is forbidden")

    def __hash__(self) -> int:
        raise AssertionError("custom token hashing is forbidden")


def test_high_cardinality_capture_has_structural_work_bounds(
    monkeypatch,
) -> None:
    controlled_calls = 0
    unknown_hash_inputs: list[int] = []
    original_controlled = provider_output._controlled_block_type
    original_sha256 = provider_output.hashlib.sha256

    def counted_controlled(value, *args, **kwargs):
        nonlocal controlled_calls
        controlled_calls += 1
        return original_controlled(value, *args, **kwargs)

    def observed_sha256(data=b""):
        if (
            b"unknown-block-type" in data
            or b"bounded-type-token-fingerprint" in data
        ):
            unknown_hash_inputs.append(len(data))
        return original_sha256(data)

    monkeypatch.setattr(
        provider_output, "_controlled_block_type", counted_controlled,
    )
    monkeypatch.setattr(provider_output.hashlib, "sha256", observed_sha256)
    body = {
        "stop_reason": "end_turn",
        "content": [
            {"type": f"unseen-private-kind-{index}"}
            for index in range(10_001)
        ],
        "usage": {},
    }

    snapshot = _capture(monkeypatch, protocol="anthropic", body=body)

    assert snapshot["raw_block_count"] == 10_001
    assert controlled_calls <= provider_output.MAX_BLOCKS_INSPECTED
    assert provider_output.MAX_BLOCKS_TOUCHED <= (
        provider_output.MAX_BLOCKS_INSPECTED + 1
    )
    assert len(snapshot["raw_block_type_sequence"]) <= (
        provider_output.MAX_CONTROLLED_DETAILS
    )
    assert len(snapshot["unknown_block_type_hashes"]) <= (
        provider_output.MAX_UNKNOWN_DETAILS
    )
    assert len(unknown_hash_inputs) <= provider_output.MAX_UNKNOWN_DETAILS
    assert max(unknown_hash_inputs) <= provider_output.MAX_HASH_INPUT_BYTES
    assert snapshot["sequence_omitted_after_limit"] is True
    assert snapshot["capture_completeness"] == "partial"


@pytest.mark.parametrize("container_type", [list, tuple])
def test_high_cardinality_nested_containers_share_one_work_budget(
    monkeypatch, container_type,
) -> None:
    nested = container_type(
        {"type": "output_text", "text": "x"} for _index in range(10_001)
    )
    body = {
        "status": "completed",
        "output": [{"type": "message", "content": nested}],
        "usage": {"output_tokens": 1},
    }

    snapshot = _capture(monkeypatch, protocol="openai-responses", body=body)

    assert snapshot["capture_completeness"] == "partial"
    assert len(snapshot["raw_block_type_sequence"]) <= (
        provider_output.MAX_BLOCKS_INSPECTED
    )
    assert snapshot["raw_block_count"] == 10_002
    assert snapshot["sequence_omitted_after_limit"] is True


def test_repeated_tool_entries_are_bounded_without_entry_access(monkeypatch) -> None:
    tools = [{"function": {"arguments": "PRIVATE"}} for _ in range(10_001)]
    tools.append(_PoisonMapping())
    body = {
        "choices": [{"finish_reason": "stop", "message": {
            "content": None, "tool_calls": tools,
        }}],
        "usage": {"completion_tokens": 1},
    }

    snapshot = _capture(monkeypatch, protocol="openai-chat", body=body)

    assert snapshot["raw_block_count"] == len(tools)
    assert snapshot["capture_completeness"] == "partial"
    assert len(snapshot["raw_block_type_sequence"]) <= (
        provider_output.MAX_BLOCKS_INSPECTED
    )
    assert snapshot["raw_tool_call_present"] is True


def test_poison_tail_after_capture_bound_is_not_touched(monkeypatch) -> None:
    content = [
        {"type": "thinking"}
        for _index in range(provider_output.MAX_RAW_BLOCK_SEQUENCE)
    ]
    content.append(_PoisonMapping(type="tool_use"))

    snapshot = _capture(monkeypatch, protocol="anthropic", body={
        "stop_reason": "max_tokens",
        "content": content,
        "usage": {"output_tokens": 8},
    })

    assert snapshot is not None
    assert snapshot["capture_completeness"] == "partial"
    assert snapshot["raw_tool_call_present"] is None
    assert snapshot["sequence_omitted_after_limit"] is True


def test_huge_unknown_token_uses_bounded_fingerprint_input(monkeypatch) -> None:
    fingerprint_input_lengths: list[int] = []
    original_sha256 = provider_output.hashlib.sha256

    def observed_sha256(data=b""):
        if b"bounded-type-token-fingerprint" in data:
            fingerprint_input_lengths.append(len(data))
        return original_sha256(data)

    monkeypatch.setattr(provider_output.hashlib, "sha256", observed_sha256)
    huge_token = "private-unknown-" + ("x" * 2_000_000)

    snapshot = _capture(monkeypatch, protocol="anthropic", body={
        "stop_reason": "end_turn",
        "content": [{"type": huge_token}],
        "usage": {},
    })

    assert fingerprint_input_lengths
    assert max(fingerprint_input_lengths) <= provider_output.MAX_HASH_INPUT_BYTES
    assert huge_token not in json.dumps(snapshot)
    assert snapshot["raw_block_type_sequence"] == ("unknown",)


def test_tool_in_unobserved_tail_remains_unknown(monkeypatch, tmp_path) -> None:
    content = [
        {"type": "thinking"}
        for _index in range(provider_output.MAX_RAW_BLOCK_SEQUENCE)
    ] + [{"type": "tool_use"}]
    snapshot = _capture(monkeypatch, protocol="anthropic", body={
        "stop_reason": "max_tokens", "content": content,
        "usage": {"output_tokens": 8},
    })
    assert snapshot["capture_completeness"] == "partial"
    assert snapshot["raw_tool_call_present"] is None
    assert snapshot["raw_final_text_present"] is None

    raw = bind_ptr12_raw_shape_observation(
        _context(tmp_path), snapshot=snapshot,
        provider_id="provider", model_id="model",
        route_fingerprint="a" * 64, schema_sha256="b" * 64,
        request_mode="plain",
    )
    normalized = _shape("thinking")
    delta = observe_ptr12_shape_delta(
        _context(tmp_path), raw_shape=raw, normalized_shape=normalized,
        normalized_finish_reason="max_tokens",
    )
    assert delta.comparison_completeness == "partial"
    assert {
        "BLOCK_TYPE_SEQUENCE", "REASONING_COUNT", "TEXT_COUNT",
        "TOOL_COUNT", "VISIBLE_CHAR_COUNT",
    }.issubset(delta.unavailable_dimensions)


def test_destructive_events_are_not_consumed(monkeypatch) -> None:
    events = _DestructiveEvents()
    snapshot = _capture(
        monkeypatch, protocol="anthropic", body=None, events=events,
    )
    assert events.consumed is False
    assert snapshot["capture_completeness"] == "unavailable"


def test_custom_mapping_and_token_traps_are_not_invoked(monkeypatch) -> None:
    body = _TrapMapping()
    snapshot = _capture(monkeypatch, protocol="anthropic", body=body)
    assert body.access_count == 0
    assert snapshot["capture_completeness"] == "unavailable"

    token = _TrapToken()
    snapshot = _capture(monkeypatch, protocol="anthropic", body={
        "stop_reason": token,
        "content": [{"type": token}],
        "usage": {},
    })
    assert token.stringified is False
    assert snapshot["raw_block_type_sequence"] == ("unknown",)
    assert snapshot["finish_reason_raw_class"] == "unknown"


@pytest.mark.asyncio
async def test_bounded_fingerprint_failure_keeps_adapter_result(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1")
    adapter = AnthropicAdapter("https://offline.invalid/v1", "PRIVATE_SECRET")
    request = ModelRequest(
        model="offline",
        messages=[Message(role="user", content="PRIVATE_PROMPT")],
        max_output_tokens=8,
    )

    async def fake_post_stream(*_args, **_kwargs):
        return [], {
            "stop_reason": "end_turn",
            "content": [{"type": "private-unknown-kind"}],
            "usage": {"output_tokens": 1},
        }

    def fail_fingerprint(*_args, **_kwargs):
        raise RuntimeError("synthetic observer failure")

    monkeypatch.setattr(adapter, "post_stream", fake_post_stream)
    monkeypatch.setattr(
        provider_output, "_bounded_type_token_fingerprint", fail_fingerprint,
    )
    response = await adapter.complete(request)
    assert response.finish_reason == "end_turn"
    assert response.output_tokens == 1


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
    (
        "raw_mode", "normalized_shape", "expected_raw_zero",
        "expected_normalized_zero", "expected_predicate", "expected_delta",
    ),
    [
        ("nonzero", _shape("thinking"), False, True, False, "YES"),
        ("zero", _shape("thinking"), True, True, True, "NO"),
        (
            "nonzero", _shape("thinking", "text", visible=1),
            False, False, False, "NO",
        ),
        ("unavailable", _shape("thinking"), None, True, False, "UNKNOWN"),
        ("partial", _shape("thinking"), None, True, False, "UNKNOWN"),
        (
            "zero", _shape("thinking", "text", visible=1),
            True, False, False, "YES",
        ),
        ("absent", _shape("thinking"), None, True, False, "UNKNOWN"),
    ],
)
def test_guard_decision_keeps_raw_and_normalized_visibility_independent(
    monkeypatch, tmp_path, raw_mode, normalized_shape, expected_raw_zero,
    expected_normalized_zero, expected_predicate, expected_delta,
) -> None:
    monkeypatch.setenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1")
    if raw_mode == "nonzero":
        snapshot = _capture(monkeypatch, protocol="anthropic", body={
            "stop_reason": "max_tokens",
            "content": [
                {"type": "thinking", "thinking": "PRIVATE_REASONING"},
                {"type": "text", "text": "x"},
            ],
            "usage": {"output_tokens": 8},
        })
    elif raw_mode == "zero":
        snapshot = _capture(monkeypatch, protocol="anthropic", body={
            "stop_reason": "max_tokens",
            "content": [{"type": "thinking", "thinking": "PRIVATE_REASONING"}],
            "usage": {"output_tokens": 8},
        })
    elif raw_mode == "unavailable":
        snapshot = _capture(monkeypatch, protocol="anthropic", body={
            "stop_reason": "max_tokens", "content": None,
            "usage": {"output_tokens": 8},
        })
    elif raw_mode == "partial":
        snapshot = _capture(monkeypatch, protocol="anthropic", body={
            "stop_reason": "max_tokens",
            "content": [
                {"type": "thinking"}
                for _index in range(provider_output.MAX_BLOCKS_TOUCHED + 1)
            ],
            "usage": {"output_tokens": 8},
        })
    else:
        snapshot = None

    context = _context(tmp_path)
    raw = (
        bind_ptr12_raw_shape_observation(
            context, snapshot=snapshot, provider_id="provider",
            model_id="model", route_fingerprint="a" * 64,
            schema_sha256="b" * 64, request_mode="plain",
        )
        if snapshot is not None else None
    )
    delta = observe_ptr12_shape_delta(
        context, raw_shape=raw, normalized_shape=normalized_shape,
        normalized_finish_reason="max_tokens",
    )
    guard_triggered = (
        normalized_shape.reasoning_block_count > 0
        and normalized_shape.text_block_count == 0
        and normalized_shape.provider_visible_text_chars == 0
        and normalized_shape.normalized_visible_text_chars == 0
    )
    decision = build_ptr12_guard_decision(
        context, shape=normalized_shape, raw_shape=raw, delta=delta,
        finish_reason="max_tokens", scope_eligible=True,
        guard_triggered=guard_triggered, provider_id="provider",
        model_id="model", route_fingerprint="a" * 64,
        contract_identity="planning_semantic_v2", schema_sha256="b" * 64,
        negative_write_status=("RECORDED" if guard_triggered else "NOT_REQUIRED"),
    )

    assert decision.raw_visible_chars_zero is expected_raw_zero
    assert decision.normalized_visible_chars_zero is expected_normalized_zero
    assert decision.predicate_all_true is expected_predicate
    assert delta.representation_changed == expected_delta
    if raw_mode == "partial":
        assert raw.capture_completeness == "partial"
        assert "VISIBLE_CHAR_COUNT" in delta.unavailable_dimensions


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
    assert record.raw_visible_chars_zero is None
    assert record.predicate_all_true is False
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
