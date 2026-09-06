"""Offline production transport -> consumed nonce -> safe durable diagnostics."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os

import httpx
import pytest

from novel_flywheel.full_short_probe_campaign import (
    DispatchResult, FullShortProbeCampaign, ProbeCampaignError, ProbeResultKind,
    build_probe_campaign_plan,
)
from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.providers import registry as registry_module
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.provider_stream_error import normalize_stream_error_v1
from tools.canary.full_short_budget_unblocked_campaign import (
    GuardedProviderDispatch, build_synthetic_probe_fixtures,
)
from .test_full_short_budget_unblocked_campaign import _registry


KEY = b"offline-closed-world-durable-evidence-key"
PRIVATE = "private-provider-message credential=not-a-real-key C:/private/novel"


def _success_bytes():
    items = [
        {"type": "message_start", "message": {"id": "offline", "usage": {"input_tokens": 20, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": "offline accepted result"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 7}},
        {"type": "message_stop"},
    ]
    return b"".join(b"data: " + json.dumps(item).encode() + b"\n\n" for item in items)


def _failure(tail):
    if tail == "timeout":
        return httpx.ReadTimeout(PRIVATE)
    if tail == "cancel":
        return asyncio.CancelledError(PRIVATE)
    return httpx.ReadError(PRIVATE)


def _boundary(tmp_path, monkeypatch, raw, tail, *, durable=True, close_tail=False):
    registry, secrets = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)
    adapters = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield raw
            if tail != "clean" and not close_tail:
                raise _failure(tail)

    class OfflineAdapter(AnthropicAdapter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, injected_http_transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=Stream(), headers={"content-type": "text/event-stream"})))
            adapters.append(self)
            if close_tail:
                original = self.client.aclose

                async def fail_close():
                    await original()
                    raise _failure(tail)

                self.client.aclose = fail_close

    monkeypatch.setitem(registry_module.ADAPTERS, "anthropic", OfflineAdapter)
    guarded = ProviderRegistry(registry.db, secrets, transport_policy=SingleDispatchTransportPolicyV1.phase_b())
    captures = []

    def persist_bytes(data, metadata):
        path = tmp_path / f"capture-{len(captures)}.bin"
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        assert path.read_bytes() == data
        captures.append((path, dict(metadata)))
        return True

    dispatch = GuardedProviderDispatch(fixtures, guarded,
        raw_capture_persist=persist_bytes if durable else None)
    plan = build_probe_campaign_plan([f.case for f in fixtures],
        source_blocked_shape_ordinals=sorted(n for f in fixtures for n in f.case.blocked_shape_ordinals))
    return fixtures, plan, dispatch, captures, secrets, adapters


@pytest.mark.parametrize("payload,shape,nested", [
    ({"error": {"type": "overloaded_error", "message": PRIVATE}}, "object", "object"),
    ({"error": PRIVATE}, "object", "string"),
    (PRIVATE, "string", "missing"),
    ([PRIVATE], "array", "missing"),
    (True, "boolean", "missing"),
    (42, "number", "missing"),
    (None, "null", "missing"),
])
@pytest.mark.parametrize("tail", ["clean", "timeout", "cancel", "transport"])
def test_provider_error_typed_evidence_is_durable_primary_and_reload_safe(
    tmp_path, monkeypatch, payload, shape, nested, tail,
):
    data = json.dumps(payload).encode()
    raw = b"event: error\ndata: " + data + b"\n\nevent: ping\ndata: {\"type\":\"ping\"}\n\n"
    fixtures, plan, dispatch, captures, secrets, _ = _boundary(tmp_path, monkeypatch, raw, tail)
    campaign = FullShortProbeCampaign(plan, integrity_key=KEY)
    snapshot = campaign.run(dispatch)
    record = snapshot["records"][0]
    evidence = record["provider_stream_error"]
    outcome = record["stream_outcome_v1"]
    assert record["state"] == "FAILED_CONSUMED"
    assert record["typed_code"] == "anthropic_provider_terminal_error"
    assert evidence["primary_cause_family"] == "provider.terminal_error_event"
    assert evidence["payload_shape"] == shape and evidence["nested_error_shape"] == nested
    assert evidence["raw_payload_sha256"] == hashlib.sha256(data).hexdigest()
    assert evidence["secondary_post_error_ping_count"] == 1
    assert evidence["secondary_post_error_transport_present"] == (tail != "clean")
    assert outcome["primary_cause"] == "PROVIDER_ERROR"
    assert outcome["terminal_capture_complete"] is True
    assert outcome["semantic_terminal_complete"] is False
    assert outcome["transport_tail_closed_cleanly"] == (tail == "clean")
    assert outcome["provider_id_sha256"] == hashlib.sha256(fixtures[0].route.provider_id.encode()).hexdigest()
    assert evidence["route_fingerprint_sha256"] == outcome["route_fingerprint_sha256"]
    assert outcome["route_fingerprint_sha256"] == fixtures[0].route.route_fingerprint
    assert outcome["request_sha256"] == fixtures[0].request_sha256
    assert outcome["provider_entity_sha256"] == record["raw_response_sha256"]
    assert PRIVATE not in json.dumps({"error": evidence, "outcome": outcome})
    assert len(captures) == secrets.get_calls == 1
    assert captures[0][0].read_bytes() == raw
    assert dispatch.transport_counters == {"http_post_attempts": 1, "network_requests": 1}
    restored = FullShortProbeCampaign.restore(plan, snapshot, integrity_key=KEY)
    assert restored.snapshot() == snapshot
    exposed = restored.records[0]
    exposed["stream_outcome_v1"]["tail_counts"]["EOF"] = 999
    assert restored.snapshot() == snapshot
    with pytest.raises(ProbeCampaignError, match="FIRST_DISPATCHED_FAILURE"):
        restored.run(dispatch)
    assert secrets.get_calls == 1


@pytest.mark.parametrize("tail,close_tail", [
    ("clean", False), ("timeout", False), ("cancel", False), ("transport", False),
    ("timeout", True), ("cancel", True), ("transport", True),
])
def test_success_transport_tail_persists_separately_without_second_request(
    tmp_path, monkeypatch, tail, close_tail,
):
    raw = _success_bytes()
    _, plan, dispatch, captures, secrets, adapters = _boundary(
        tmp_path, monkeypatch, raw, tail, close_tail=close_tail)

    class CheckpointReached(Exception):
        pass

    def stop_after_first_terminal(snapshot):
        if snapshot["records"][0]["state"] == "PASS_CONSUMED":
            raise CheckpointReached

    campaign = FullShortProbeCampaign(plan, integrity_key=KEY, persist=stop_after_first_terminal)
    with pytest.raises(CheckpointReached):
        campaign.run(dispatch)
    snapshot = campaign.snapshot()
    record = snapshot["records"][0]
    outcome = record["stream_outcome_v1"]
    assert "provider_stream_error" not in record
    assert outcome["primary_cause"] == "SUCCESS"
    assert outcome["semantic_terminal_complete"] is True
    assert outcome["terminal_capture_complete"] is True
    assert outcome["transport_tail_closed_cleanly"] == (tail == "clean")
    assert len(captures) == secrets.get_calls == len(adapters) == 1
    assert captures[0][0].read_bytes() == raw
    assert dispatch.transport_counters == {"http_post_attempts": 1, "network_requests": 1}
    assert FullShortProbeCampaign.restore(plan, snapshot, integrity_key=KEY).snapshot() == snapshot


def test_legacy_no_optional_fields_reload_is_idempotent(tmp_path, monkeypatch):
    _, plan, _, _, _, _ = _boundary(tmp_path, monkeypatch, b"", "clean")
    campaign = FullShortProbeCampaign(plan, integrity_key=KEY)
    snapshot = campaign.run(lambda _: DispatchResult(ProbeResultKind.FAILED, "offline", b"", 0))
    assert "provider_stream_error" not in snapshot["records"][0]
    assert "stream_outcome_v1" not in snapshot["records"][0]
    for _ in range(2):
        restored = FullShortProbeCampaign.restore(plan, snapshot, integrity_key=KEY)
        assert restored.snapshot() == snapshot


def test_safe_evidence_rejects_extra_raw_fields_and_untyped_values():
    evidence = normalize_stream_error_v1({"error": PRIVATE})
    with pytest.raises(ProbeCampaignError, match="RESULT_STREAM_EVIDENCE_INVALID"):
        DispatchResult(ProbeResultKind.FAILED, "offline", b"", 0,
                       provider_stream_error={"message": PRIVATE})
    forged = evidence.model_copy(update={"safe_message": PRIVATE})
    with pytest.raises(ProbeCampaignError, match="RESULT_STREAM_EVIDENCE_INVALID"):
        DispatchResult(ProbeResultKind.FAILED, "offline", b"", 0, provider_stream_error=forged)


@pytest.mark.parametrize("capture", ["absent", "unacknowledged", "write_failure"])
def test_capture_completeness_requires_durable_byte_ack(tmp_path, monkeypatch, capture):
    raw = b"event: error\ndata: {\"error\":\"private-provider-message\"}\n\n"
    _, plan, dispatch, _, secrets, _ = _boundary(tmp_path, monkeypatch, raw, "timeout", durable=False)
    if capture == "unacknowledged":
        dispatch._raw_capture_persist = lambda data, metadata: False
    elif capture == "write_failure":
        def failed(data, metadata):
            raise OSError(PRIVATE)
        dispatch._raw_capture_persist = failed
    snapshot = FullShortProbeCampaign(plan, integrity_key=KEY).run(dispatch)
    record = snapshot["records"][0]
    assert record["typed_code"] == "anthropic_provider_terminal_error"
    assert record["state"] == "FAILED_CONSUMED"
    assert record["stream_outcome_v1"]["terminal_capture_complete"] is False
    assert record["provider_stream_error"]["primary_cause_family"] == "provider.terminal_error_event"
    assert record["provider_stream_error"]["secondary_post_error_observer_failure_count"] == (capture != "absent")
    assert FullShortProbeCampaign.restore(plan, snapshot, integrity_key=KEY).snapshot() == snapshot
    assert secrets.get_calls == 1


@pytest.mark.parametrize("tail", ["timeout", "cancel", "transport"])
def test_provider_error_client_close_tail_is_sealed_after_capture(tmp_path, monkeypatch, tail):
    raw = b"event: error\ndata: {\"error\":{\"type\":\"overloaded_error\"}}\n\n"
    _, plan, dispatch, captures, secrets, _ = _boundary(tmp_path, monkeypatch, raw, tail, close_tail=True)
    snapshot = FullShortProbeCampaign(plan, integrity_key=KEY).run(dispatch)
    record = snapshot["records"][0]
    assert record["typed_code"] == "anthropic_provider_terminal_error"
    assert record["provider_stream_error"]["secondary_post_error_transport_present"] is True
    assert record["stream_outcome_v1"]["transport_tail_closed_cleanly"] is False
    assert record["stream_outcome_v1"]["terminal_capture_complete"] is True
    assert len(captures) == secrets.get_calls == 1
    assert captures[0][0].read_bytes() == raw
    assert captures[0][1]["transport_complete"] is True
    assert FullShortProbeCampaign.restore(plan, snapshot, integrity_key=KEY).snapshot() == snapshot


def test_success_capture_rejection_remains_typed_and_durable(tmp_path, monkeypatch):
    _, plan, dispatch, _, secrets, _ = _boundary(tmp_path, monkeypatch, _success_bytes(), "clean", durable=False)
    dispatch._raw_capture_persist = lambda data, metadata: False
    snapshot = FullShortProbeCampaign(plan, integrity_key=KEY).run(dispatch)
    record = snapshot["records"][0]
    assert record["state"] == "FAILED_CONSUMED"
    assert record["typed_code"] == "probe.provider.capture_failure"
    assert record["stream_outcome_v1"]["primary_cause"] == "CAPTURE_FAILURE"
    assert record["stream_outcome_v1"]["terminal_capture_complete"] is False
    assert FullShortProbeCampaign.restore(plan, snapshot, integrity_key=KEY).snapshot() == snapshot
    assert secrets.get_calls == 1
