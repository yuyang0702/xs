"""Production canary assembly with only the HTTP boundary replaced offline."""
import hashlib
import json

import httpx
import pytest

from .test_full_short_budget_unblocked_campaign import _registry
from novel_flywheel.providers.anthropic import AnthropicAdapter, AnthropicProviderTerminalError
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.providers import registry as registry_module
from tools.canary.full_short_budget_unblocked_campaign import (
    build_synthetic_probe_fixtures, _run_guarded_campaign_with_registry_v1,
    GuardedProviderDispatch,
)


class Tail(httpx.AsyncByteStream):
    def __init__(self, raw, timeout=True): self.raw, self.timeout = raw, timeout
    async def __aiter__(self):
        yield self.raw
        if self.timeout:
            raise httpx.ReadTimeout("synthetic timeout")
    async def aclose(self): pass


@pytest.mark.parametrize("payload", [{"error":{"type":"overloaded_error"}}, "private error", None, False])
@pytest.mark.parametrize("timeout", [False, True])
def test_canary_provider_error_timeout_is_failed_consumed(tmp_path, monkeypatch, payload, timeout):
    registry, secrets = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)
    raw = ("event: error\ndata: " + json.dumps(payload) + "\n\nevent: ping\ndata: {\"type\":\"ping\"}\n\n").encode()

    class Adapter(AnthropicAdapter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, injected_http_transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=Tail(raw, timeout), headers={"content-type":"text/event-stream"}, request=request)))

    monkeypatch.setitem(registry_module.ADAPTERS, "anthropic", Adapter)
    guarded_registry = ProviderRegistry(registry.db, secrets, transport_policy=SingleDispatchTransportPolicyV1.phase_b())
    captures = []
    result = _run_guarded_campaign_with_registry_v1(fixtures, registry=guarded_registry,
        authorization_sha256="a"*64, final_execution_head="b"*40, key_id="offline",
        signing_key=b"offline-fixture-signing-key-32-bytes-minimum", capture_metadata_persist=captures.append)
    record = result.campaign_state["records"][0]
    assert record["typed_code"] == "anthropic_provider_terminal_error"
    assert record["state"] == "FAILED_CONSUMED"
    assert record["raw_response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert all(r["state"] == "UNUSED" for r in result.campaign_state["records"][1:])
    assert captures[0]["transport_complete"] is (not timeout)
    assert result.transport_counters == {"http_post_attempts":1, "network_requests":1}
    assert secrets.get_calls == 1  # Only the synthetic in-memory store.


@pytest.mark.asyncio
async def test_canary_close_failure_does_not_replace_provider_cause():
    class Client:
        async def aclose(self): raise RuntimeError("private close detail")
    class Adapter:
        client = Client()
        async def complete(self, request): raise AnthropicProviderTerminalError("overloaded_error")
    with pytest.raises(AnthropicProviderTerminalError) as caught:
        await GuardedProviderDispatch._complete_and_close(Adapter(), None)
    assert caught.value.provider_stream_error.secondary_post_error_transport_present
