from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from novel_flywheel.db import Database
from novel_flywheel.domain.models import Message, ModelRequest
import novel_flywheel.providers.anthropic as anthropic_module
from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers.http import (
    HttpProvider,
    ProviderResponseError,
    SingleDispatchTransportPolicyV1,
)
from novel_flywheel.providers.registry import ProviderRegistry


def _sse_response(request: httpx.Request) -> httpx.Response:
    body = "data: " + json.dumps({"type": "message_stop"}) + "\n\n"
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=body.encode("utf-8"),
        request=request,
    )


async def _provider(handler, *, guarded: bool) -> HttpProvider:
    provider = HttpProvider(
        "https://provider.example.invalid",
        "test-only-secret",
        transport_policy=(
            SingleDispatchTransportPolicyV1.phase_b()
            if guarded else None
        ),
    )
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


@pytest.mark.asyncio
async def test_guarded_success_records_exactly_one_http_attempt() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return _sse_response(request)

    provider = await _provider(handler, guarded=True)
    try:
        events, body = await provider.post_stream(
            "messages", payload={"stream": True}, headers={},
        )
    finally:
        await provider.client.aclose()

    assert body is None
    assert events == [{"type": "message_stop"}]
    assert attempts == 1
    assert provider.transport_attempt_snapshot() == {
        "guard_active": True,
        "max_http_post_attempts": 1,
        "model_logical_calls": 1,
        "real_provider_request_attempts": 1,
        "http_post_attempts": 1,
        "network_request_attempts": 1,
        "sdk_retries_disabled": True,
        "transport_request_retries_disabled": True,
        "application_second_dispatch_allowed": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("connect failed"),
        httpx.ConnectTimeout("connect timeout"),
        httpx.ReadTimeout("read timeout"),
        httpx.WriteTimeout("write timeout"),
    ],
)
async def test_guarded_transport_failure_never_dispatches_twice(
    failure: httpx.TransportError,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        failure.request = request
        raise failure

    provider = await _provider(handler, guarded=True)
    try:
        with pytest.raises(type(failure)) as caught:
            await provider.post_stream(
                "messages", payload={"stream": True}, headers={},
            )
    finally:
        await provider.client.aclose()

    assert caught.value is failure
    assert attempts == 1
    assert provider.transport_attempt_snapshot()["http_post_attempts"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503])
async def test_guarded_retryable_http_status_never_dispatches_twice(status: int) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, text="retryable", request=request)

    provider = await _provider(handler, guarded=True)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await provider.post_stream(
                "messages", payload={"stream": True}, headers={},
            )
    finally:
        await provider.client.aclose()

    assert attempts == 1
    assert provider.transport_attempt_snapshot()["http_post_attempts"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,detail",
    [
        ({"stream": True, "stream_options": {}}, "stream_options unsupported"),
        ({"stream": True}, "stream unsupported"),
    ],
)
async def test_guarded_protocol_fallback_cannot_issue_a_second_post(
    payload: dict, detail: str,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, text=detail, request=request)

    provider = await _provider(handler, guarded=True)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await provider.post_stream("messages", payload=payload, headers={})
    finally:
        await provider.client.aclose()

    assert attempts == 1


@pytest.mark.asyncio
async def test_default_transport_retry_behavior_is_unchanged(monkeypatch) -> None:
    attempts = 0

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("novel_flywheel.providers.http.asyncio.sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("first connect failed", request=request)
        return _sse_response(request)

    provider = await _provider(handler, guarded=False)
    try:
        events, body = await provider.post_stream(
            "messages", payload={"stream": True}, headers={},
        )
    finally:
        await provider.client.aclose()

    assert attempts == 2
    assert body is None
    assert events == [{"type": "message_stop"}]


def test_registry_injects_guard_only_when_explicitly_requested(
    tmp_path, monkeypatch,
) -> None:
    database = Database(tmp_path / "app.db")
    database.migrate()
    database.save_provider(
        provider_id="provider", name="provider", protocol="anthropic",
        base_url="https://provider.example.invalid", auth_type="bearer",
        timeout_seconds=30, extra_headers={}, enabled=True,
    )
    database.save_model(
        model_id="model", provider_id="provider", display_name="model",
        model_name="model-name", capabilities={},
    )

    captured: list[object] = []

    class FakeSecrets:
        def get(self, _provider_id: str) -> str:
            return "test-only-secret"

    class FakeAdapter:
        def __init__(self, *_args, transport_policy=None, **_kwargs) -> None:
            captured.append(transport_policy)

    monkeypatch.setitem(
        __import__(
            "novel_flywheel.providers.registry", fromlist=["ADAPTERS"],
        ).ADAPTERS,
        "anthropic",
        FakeAdapter,
    )

    ProviderRegistry(database, FakeSecrets()).resolve("provider", "model")
    policy = SingleDispatchTransportPolicyV1.phase_b()
    ProviderRegistry(
        database, FakeSecrets(), transport_policy=policy,
    ).resolve("provider", "model")

    assert captured == [None, policy]


@pytest.mark.asyncio
async def test_guarded_malformed_sse_never_dispatches_twice() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: {not-json}\n\n",
            request=request,
        )

    provider = await _provider(handler, guarded=True)
    try:
        with pytest.raises(ProviderResponseError):
            await provider.post_stream(
                "messages", payload={"stream": True}, headers={},
            )
    finally:
        await provider.client.aclose()

    assert attempts == 1
    assert provider.transport_attempt_snapshot()["http_post_attempts"] == 1


@pytest.mark.asyncio
async def test_guarded_cancellation_is_not_swallowed() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise asyncio.CancelledError()

    provider = await _provider(handler, guarded=True)
    try:
        with pytest.raises(asyncio.CancelledError):
            await provider.post_stream(
                "messages", payload={"stream": True}, headers={},
            )
    finally:
        await provider.client.aclose()

    assert attempts == 1


async def _anthropic_adapter(handler) -> AnthropicAdapter:
    adapter = AnthropicAdapter(
        "https://provider.example.invalid/v1",
        "test-only-secret",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


def _anthropic_request() -> ModelRequest:
    return ModelRequest(
        model="model-name",
        messages=[Message(role="user", content="offline fixture")],
        max_output_tokens=128,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content,expected_text,expected_tools",
    [
        ([{"type": "text", "text": "ok"}], "ok", 0),
        ([{"type": "tool_use", "id": "call-1", "name": "done", "input": {}}], "", 1),
        ([{"type": "future_unknown", "shape": "opaque"}], "", 0),
    ],
)
async def test_guard_does_not_change_valid_adapter_output_shapes(
    content: list[dict], expected_text: str, expected_tools: int,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "id": "response-id", "content": content,
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 4, "output_tokens": 3},
            },
            request=request,
        )

    adapter = await _anthropic_adapter(handler)
    try:
        response = await adapter.complete(_anthropic_request())
    finally:
        await adapter.client.aclose()

    assert attempts == 1
    assert response.text == expected_text
    assert len(response.tool_calls) == expected_tools


@pytest.mark.asyncio
async def test_adapter_parse_failure_after_response_never_dispatches_twice() -> None:
    attempts = 0
    events = [
        {"type": "message_start", "message": {"id": "id", "usage": {"input_tokens": 1}}},
        {
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "tool_use", "id": "call", "name": "done"},
        },
        {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": "{"},
        },
        {
            "type": "message_delta", "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 4},
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        body = "".join(
            "data: " + json.dumps(event) + "\n\n" for event in events
        )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            content=body.encode("utf-8"), request=request,
        )

    adapter = await _anthropic_adapter(handler)
    try:
        with pytest.raises(json.JSONDecodeError):
            await adapter.complete(_anthropic_request())
    finally:
        await adapter.client.aclose()

    assert attempts == 1
    assert adapter.transport_attempt_snapshot()["http_post_attempts"] == 1


@pytest.mark.asyncio
async def test_observer_failure_after_response_never_dispatches_twice(
    monkeypatch,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200, headers={"content-type": "application/json"},
            json={
                "id": "response-id", "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            request=request,
        )

    def broken_observer(**_kwargs) -> None:
        raise RuntimeError("offline observer failure")

    monkeypatch.setattr(
        anthropic_module, "capture_provider_raw_shape_v1", broken_observer,
    )
    adapter = await _anthropic_adapter(handler)
    try:
        with pytest.raises(RuntimeError, match="offline observer failure"):
            await adapter.complete(_anthropic_request())
    finally:
        await adapter.client.aclose()

    assert attempts == 1
