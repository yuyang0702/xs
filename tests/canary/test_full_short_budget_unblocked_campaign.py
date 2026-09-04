from __future__ import annotations

import base64
import copy
import hashlib
import json

import pytest

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.db import Database
from novel_flywheel.domain.models import ModelResponse, ToolCall
from novel_flywheel.generated_artifacts import registered_business_wire_schema
from novel_flywheel.provider_payloads import anthropic_payload_v1
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.providers import registry as registry_module
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.secrets import MemorySecretStore
from tools.canary import full_short_budget_unblocked_campaign as campaign_module
from tools.canary.full_short_budget_unblocked_campaign import (
    AUTHORITATIVE_MATRIX_PATH,
    BLOCKED_SHAPE_COUNT,
    CampaignFixtureError,
    EXACT_PROBE_INPUT_TOKENS,
    RELAY_OPERATOR,
    build_synthetic_probe_fixtures,
    derive_probe_families,
    load_authoritative_matrix,
    _run_guarded_campaign_with_registry_v1,
    run_offline_fake_campaign,
)


VALID_TOOL_ARGUMENTS = {
    "planning_event_realizations": {"events": [{}]},
    "short_causal_chain": {
        "core_goal": None, "cycles": [{}], "ending": None,
        "covered_event_ids": [],
    },
    "execution_manifest": {"beats": [{}], "segments": [{}]},
    "final_review_window": {"summary": None, "issues": []},
    "full_short_final_review": {"issues": []},
}


class TrackingSecrets(MemorySecretStore):
    def __init__(self) -> None:
        super().__init__()
        self.get_calls = 0
        self.on_get = None

    def get(self, provider_id: str) -> str | None:
        self.get_calls += 1
        if self.on_get is not None:
            self.on_get(provider_id)
        return super().get(provider_id)


def _registry(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    secrets = TrackingSecrets()
    registry = ProviderRegistry(db, secrets)
    routes = (
        (
            "87f5f31c-ef5d-4282-ae6f-86f4b335d9ff",
            "happy", "https://happyapi.org/v1", "qwen-3.7-plus",
        ),
        (
            "68fd833c-17a5-4f45-830b-bd6dfa64d718",
            "lingsuan_sonnet", "https://lingsuan.org", "claude-sonnet-5",
        ),
        (
            "247c0b35-b5ff-47a0-9793-9f9a6c663b08",
            "lingsuan_gpt", "https://lingsuan.org", "gpt-5.6-sol",
        ),
    )
    for provider_id, name, base_url, model in routes:
        registry.add_provider(
            provider_id=provider_id, name=name, protocol="anthropic",
            base_url=base_url, api_key="offline-never-read",
        )
        registry.add_model(provider_id, model, model)
    return registry, secrets


def test_authoritative_sparse_blocked_ordinals_partition_into_exact_eight_families() -> None:
    families = derive_probe_families()
    matrix = json.loads(
        AUTHORITATIVE_MATRIX_PATH.read_text(encoding="utf-8")
    )
    source_passed = sum(
        item["admission_result"] == "PASS"
        for item in matrix["attempts"]
    )
    assert [item.family_id for item in families] == [
        "draft_plain",
        "polish_plain",
        "planning_adaptation",
        "causal_chain",
        "execution_manifest",
        "final_review_window",
        "final_review_adjudication",
        "maintenance_plain",
    ]
    assert [item.blocked_shape_ordinals for item in families] == [
        (29, 31, 33, 35, 37, 39, 122, 124, 126, 128, 130, 132),
        tuple(range(52, 64)) + tuple(range(145, 157)),
        (2, 3, 4, 5, 95, 96, 97, 98),
        (15, 16, 108, 109),
        (17, 19, 21, 23, 25, 27, 110, 112, 114, 116, 118, 120),
        (64, 65, 66, 67, 157, 158, 159, 160),
        (68, 161),
        tuple(range(69, 89)) + tuple(range(162, 183)),
    ]
    assert [item.estimated_input_tokens for item in families] == [
        30458, 32380, 16321, 18140, 18429, 21136, 18549, 31320,
    ]
    assert [item.wire_requested_output_cap for item in families] == [
        2974, 2832, 8328, 7625, 3541, 768, 768, 768,
    ]
    covered = [shape for item in families for shape in item.blocked_shape_ordinals]
    assert len(covered) == len(set(covered)) == BLOCKED_SHAPE_COUNT
    assert sum(item.estimated_input_tokens for item in families) == EXACT_PROBE_INPUT_TOKENS
    assert set(covered) != set(range(1, 112))
    # Promotion is exactly the pre-existing PASS set plus every formerly
    # blocked physical shape, with neither omission nor double counting.
    assert (
        len(matrix["attempts"])
        == campaign_module.AUTHORITATIVE_SHAPE_COUNT
        == 183
    )
    assert source_passed == (
        campaign_module.AUTHORITATIVE_SHAPE_COUNT - BLOCKED_SHAPE_COUNT
    )
    assert source_passed + len(set(covered)) == 183
    assert (
        campaign_module.AUTHORITATIVE_SHAPE_COUNT
        - source_passed
        - len(set(covered))
        == 0
    )


def test_synthetic_payloads_bind_current_public_routes_and_exact_wire_maxima(tmp_path) -> None:
    registry, secrets = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)
    rebuilt = build_synthetic_probe_fixtures(registry)

    assert secrets.get_calls == 0
    assert len(fixtures) == 8
    assert sum(item.case.estimated_input_tokens for item in fixtures) == 186733
    for fixture, rebuilt_fixture in zip(fixtures, rebuilt, strict=True):
        assert fixture.route.operator == RELAY_OPERATOR
        assert fixture.case.route.route_fingerprint == fixture.definition.route_fingerprint
        assert fixture.case.route.destination_sha256 == hashlib.sha256(
            fixture.route.destination.encode("utf-8")
        ).hexdigest()
        assert [message.role for message in fixture.request.messages] == ["system", "user"]
        assert estimate_input_tokens(fixture.payload_bytes.decode("utf-8")) == (
            fixture.definition.estimated_input_tokens
        )
        assert fixture.payload["max_tokens"] == fixture.definition.wire_requested_output_cap
        assert fixture.payload["stream"] is True
        assert fixture.request_family_sha256 != fixture.request_sha256
        assert fixture.request_sha256 == hashlib.sha256(fixture.payload_bytes).hexdigest()
        assert rebuilt_fixture.payload_bytes == fixture.payload_bytes
        user_content = fixture.request.messages[1].content
        filler = user_content.split(". ", 1)[1]
        assert "x" * 64 not in filler
        sample = filler[: min(len(filler), 8192)]
        blocks = [sample[index:index + 32] for index in range(0, len(sample), 32)]
        assert len(set(blocks)) >= max(1, len(blocks) - 2)
        if fixture.definition.contract_name is None:
            assert "tools" not in fixture.payload
            assert "tool_choice" not in fixture.payload
        else:
            name = fixture.definition.contract_name
            assert fixture.payload["tool_choice"] == {"type": "tool", "name": name}
            assert fixture.payload["tools"] == [{
                "name": name,
                "description": "Return the complete validated structured artifact.",
                "input_schema": registered_business_wire_schema(name),
            }]


def test_offline_fake_campaign_captures_exact_responses_and_seals_evidence(tmp_path) -> None:
    registry, secrets = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)
    result = run_offline_fake_campaign(
        fixtures,
        authorization_sha256="a" * 64,
        final_execution_head="b" * 40,
        key_id="offline-fixture-key",
        signing_key=b"offline-fixture-signing-key-32-bytes-minimum",
    )

    assert secrets.get_calls == 0
    assert len(result.raw_responses) == len(result.sealed_evidence) == 8
    assert len(result.verified_evidence) == len(result.promoted_evidence) == 8
    assert set(result.external_action_counters.values()) == {0}
    assert result.privacy_counts == {
        "RAW_NOVEL_CONTENT_EGRESS_COUNT": 0,
        "REAL_PROJECT_CONTENT_EGRESS_COUNT": 0,
    }
    assert result.campaign_state["counters"] == {
        "provider_requests": 8,
        "http_post_attempts": 8,
        "network_requests": 8,
        "input_tokens": 186733,
        "generated_output_tokens": 8,
        "elapsed_seconds": result.campaign_state["counters"]["elapsed_seconds"],
    }
    for raw, record, verified in zip(
        result.raw_responses,
        result.campaign_state["records"],
        result.verified_evidence,
        strict=True,
    ):
        assert base64.b64decode(record["raw_response_base64"], validate=True) == raw
        assert record["raw_response_sha256"] == hashlib.sha256(raw).hexdigest()
        assert verified.response_sha256 == record["raw_response_sha256"]
        assert verified.authorization_sha256 == "a" * 64
        assert verified.final_execution_head == "b" * 40


def test_matrix_or_family_drift_fails_closed_before_registry_or_dispatch(tmp_path) -> None:
    tampered_path = tmp_path / "matrix.json"
    tampered_path.write_bytes(AUTHORITATIVE_MATRIX_PATH.read_bytes() + b"\n")
    with pytest.raises(CampaignFixtureError, match="AUTHORITATIVE_MATRIX_SHA256_MISMATCH"):
        load_authoritative_matrix(tampered_path)

    matrix = copy.deepcopy(load_authoritative_matrix())
    blocked = next(
        item for item in matrix["attempts"]
        if item["admission_result"] == "BLOCKED"
    )
    blocked["stage"] = "unknown-future-stage"
    with pytest.raises(CampaignFixtureError, match="BLOCKED_SHAPE_FAMILY_UNKNOWN"):
        derive_probe_families(matrix)


def test_public_route_drift_fails_before_any_credential_read(tmp_path) -> None:
    registry, secrets = _registry(tmp_path)
    provider = registry.db.get_provider("247c0b35-b5ff-47a0-9793-9f9a6c663b08")
    assert provider is not None
    registry.db.save_provider(
        provider_id=provider["id"], name=provider["name"],
        protocol=provider["protocol"], base_url="https://route-drift.invalid",
        auth_type=provider["auth_type"], timeout_seconds=provider["timeout_seconds"],
        extra_headers=provider["extra_headers"], enabled=True,
    )
    with pytest.raises(CampaignFixtureError, match="CURRENT_REGISTRY_ROUTE_BINDING_MISMATCH"):
        build_synthetic_probe_fixtures(registry)
    assert secrets.get_calls == 0


def test_guarded_real_entrypoint_reserves_before_secret_and_never_retries_or_switches(
    tmp_path, monkeypatch,
) -> None:
    registry, secrets = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)
    snapshots = []
    adapter_instances = []
    resolve_calls = []

    class OfflineProviderAdapter:
        def __init__(
            self, base_url, api_key, headers, timeout, *, auth_type,
            transport_policy, attempt_observer,
        ) -> None:
            assert api_key == "offline-never-read"
            assert transport_policy == SingleDispatchTransportPolicyV1.phase_b()
            self.base_url = base_url.rstrip("/")
            self.transport_policy = transport_policy
            self.observer = attempt_observer
            self.complete_calls = 0
            adapter_instances.append(self)

        async def complete(self, request):
            self.complete_calls += 1
            assert self.complete_calls == 1
            self.observer.bind_model_request(protocol="anthropic", request=request)
            payload = anthropic_payload_v1(request)
            fixture = next(
                fixture for fixture in fixtures if fixture.request == request
            )
            destination = fixture.route.destination
            actual_input_tokens = fixture.definition.estimated_input_tokens
            request_bytes = __import__("httpx").Request(
                "POST", destination, json=payload,
            ).content
            self.observer.before_http_dispatch(
                method="POST", url=destination,
                payload=payload, request_bytes=request_bytes,
            )
            self.observer.before_http_post()
            self.observer.before_network_request()
            raw_content = (
                [{"type": "tool_use", "id": "synthetic",
                  "name": request.required_tool,
                  "input": VALID_TOOL_ARGUMENTS[request.required_tool]}]
                if request.required_tool else
                [{"type": "text", "text": "SYNTHETIC_ACCEPTED"}]
            )
            raw = __import__("json").dumps({
                "content": raw_content,
                "stop_reason": "tool_use" if request.required_tool else "end_turn",
                "usage": {
                    "input_tokens": actual_input_tokens, "output_tokens": 1,
                },
            }, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.observer.capture_provider_protocol_input(
                data=raw, status_code=200, content_type="application/json",
                encoding="utf-8", transport_complete=True,
            )
            return ModelResponse(
                text=("" if request.required_tool else "SYNTHETIC_ACCEPTED"),
                tool_calls=(
                    [ToolCall(id="synthetic", name=request.required_tool,
                              arguments=VALID_TOOL_ARGUMENTS[request.required_tool])]
                    if request.required_tool else []
                ),
                finish_reason=("tool_use" if request.required_tool else "end_turn"),
                input_tokens=actual_input_tokens, output_tokens=1,
            )

    class CountingRegistry(ProviderRegistry):
        def resolve(self, provider_id, model_id, **kwargs):
            resolve_calls.append((provider_id, model_id, kwargs))
            return super().resolve(provider_id, model_id, **kwargs)

    monkeypatch.setitem(registry_module.ADAPTERS, "anthropic", OfflineProviderAdapter)
    monkeypatch.setattr(campaign_module, "ProviderRegistry", CountingRegistry)

    def before_secret(provider_id):
        case_index = secrets.get_calls - 1
        assert snapshots[-1]["records"][case_index]["state"] == (
            "DISPATCH_ATTEMPTED"
        )
        assert any(
            snapshot["records"][case_index]["state"]
            == "RESERVED_PRE_CREDENTIAL"
            for snapshot in snapshots
        )

    secrets.on_get = before_secret
    guarded_registry = CountingRegistry(
        registry.db, secrets,
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    result = _run_guarded_campaign_with_registry_v1(
        fixtures, registry=guarded_registry, authorization_sha256="a" * 64,
        final_execution_head="b" * 40, key_id="offline-fixture-key",
        signing_key=b"offline-fixture-signing-key-32-bytes-minimum",
        persist=lambda snapshot: snapshots.append(copy.deepcopy(snapshot)),
    )

    assert secrets.get_calls == len(resolve_calls) == len(adapter_instances) == 8
    assert all(adapter.complete_calls == 1 for adapter in adapter_instances)
    assert result.transport_counters == {
        "http_post_attempts": 8, "network_requests": 8,
    }
    assert len(result.raw_responses) == len(result.sealed_evidence) == 8
    assert all(
        item.actual_input_tokens == item.input_tokens
        for item in result.verified_evidence
    )


def test_probe_fixture_module_has_no_importable_keyring_paid_entrypoint() -> None:
    assert not hasattr(campaign_module, "run_keyring_guarded_real_campaign")
    assert not hasattr(campaign_module, "_ORCHESTRATOR_PROBE_DISPATCH_CAPABILITY_V1")
    assert not hasattr(campaign_module, "KeyringSecretStore")


def test_absolute_deadline_expiry_after_nonce_stops_before_credential_and_http(
    tmp_path,
) -> None:
    registry, secrets = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)

    class AdvancingClock:
        now = 100.0

        def __call__(self):
            return self.now

    clock = AdvancingClock()

    def persist(snapshot):
        if snapshot["records"][0]["state"] == "RESERVED_PRE_CREDENTIAL":
            clock.now = 105.0

    guarded_registry = ProviderRegistry(
        registry.db, secrets,
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    result = _run_guarded_campaign_with_registry_v1(
        fixtures, registry=guarded_registry,
        authorization_sha256="a" * 64,
        final_execution_head="b" * 40, key_id="offline-fixture-key",
        signing_key=b"offline-fixture-signing-key-32-bytes-minimum",
        persist=persist, absolute_deadline_unix_seconds=105.0,
        wall_clock=clock,
    )

    assert secrets.get_calls == 0
    assert result.transport_counters == {
        "http_post_attempts": 0, "network_requests": 0,
    }
    assert result.campaign_state["records"][0]["state"] == (
        "AMBIGUOUS_CONSUMED"
    )
    assert all(
        record["state"] == "UNUSED"
        for record in result.campaign_state["records"][1:]
    )


def test_absolute_deadline_expiry_during_route_recheck_stops_credential_and_http(
    tmp_path, monkeypatch,
) -> None:
    registry, secrets = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)

    class Clock:
        now = 100.0

        def __call__(self):
            return self.now

    clock = Clock()
    original = campaign_module._bind_public_route
    route_reads = 0

    def delayed_route_recheck(bound_registry, family):
        nonlocal route_reads
        route_reads += 1
        result = original(bound_registry, family)
        # Eight initial reads bind the fixture set.  The ninth is the first
        # per-dispatch route recheck between nonce reservation and secrets.get.
        if route_reads == 9:
            clock.now = 105.0
        return result

    monkeypatch.setattr(
        campaign_module, "_bind_public_route", delayed_route_recheck,
    )
    guarded_registry = ProviderRegistry(
        registry.db, secrets,
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    result = _run_guarded_campaign_with_registry_v1(
        fixtures, registry=guarded_registry,
        authorization_sha256="a" * 64,
        final_execution_head="b" * 40, key_id="offline-fixture-key",
        signing_key=b"offline-fixture-signing-key-32-bytes-minimum",
        absolute_deadline_unix_seconds=105.0, wall_clock=clock,
    )

    assert secrets.get_calls == 0
    assert result.transport_counters == {
        "http_post_attempts": 0, "network_requests": 0,
    }
    assert result.campaign_state["records"][0]["state"] == "FAILED_CONSUMED"


def test_real_probe_does_not_promote_when_provider_reports_smaller_input(
    tmp_path, monkeypatch,
) -> None:
    registry, secrets = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)

    class UnderreportedInputAdapter:
        def __init__(
            self, base_url, api_key, headers, timeout, *, auth_type,
            transport_policy, attempt_observer,
        ) -> None:
            self.observer = attempt_observer

        async def complete(self, request):
            fixture = next(
                fixture for fixture in fixtures if fixture.request == request
            )
            self.observer.bind_model_request(
                protocol="anthropic", request=request,
            )
            payload = anthropic_payload_v1(request)
            request_bytes = __import__("httpx").Request(
                "POST", fixture.route.destination, json=payload,
            ).content
            self.observer.before_http_dispatch(
                method="POST", url=fixture.route.destination,
                payload=payload, request_bytes=request_bytes,
            )
            self.observer.before_http_post()
            self.observer.before_network_request()
            raw = json.dumps({
                "content": [{"type": "text", "text": "SYNTHETIC_ACCEPTED"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.observer.capture_provider_protocol_input(
                data=raw, status_code=200, content_type="application/json",
                encoding="utf-8", transport_complete=True,
            )
            return ModelResponse(
                text="SYNTHETIC_ACCEPTED", finish_reason="end_turn",
                input_tokens=1, output_tokens=1,
            )

    monkeypatch.setitem(
        registry_module.ADAPTERS, "anthropic", UnderreportedInputAdapter,
    )
    guarded_registry = ProviderRegistry(
        registry.db, secrets,
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    result = _run_guarded_campaign_with_registry_v1(
        fixtures, registry=guarded_registry, authorization_sha256="a" * 64,
        final_execution_head="b" * 40, key_id="offline-fixture-key",
        signing_key=b"offline-fixture-signing-key-32-bytes-minimum",
    )

    assert result.campaign_state["halt_code"] == "FIRST_DISPATCHED_FAILURE"
    assert result.campaign_state["records"][0]["typed_code"] == (
        "probe.provider.input_workload_bound_unproven"
    )
    assert result.sealed_evidence == ()
    assert result.verified_evidence == ()


def test_guarded_real_transport_fault_halts_without_retry_or_fallback(
    tmp_path, monkeypatch,
) -> None:
    registry, secrets = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)
    complete_calls = []

    class FailingAdapter:
        def __init__(
            self, base_url, api_key, headers, timeout, *, auth_type,
            transport_policy, attempt_observer,
        ) -> None:
            assert transport_policy == SingleDispatchTransportPolicyV1.phase_b()
            self.observer = attempt_observer

        async def complete(self, request):
            complete_calls.append(request.model)
            self.observer.bind_model_request(protocol="anthropic", request=request)
            payload = anthropic_payload_v1(request)
            destination = next(
                fixture.route.destination for fixture in fixtures
                if fixture.route.model == request.model
            )
            request_bytes = __import__("httpx").Request(
                "POST", destination, json=payload,
            ).content
            self.observer.before_http_dispatch(
                method="POST", url=destination,
                payload=payload, request_bytes=request_bytes,
            )
            self.observer.before_http_post()
            self.observer.before_network_request()
            raise RuntimeError("offline transport interruption")

    monkeypatch.setitem(registry_module.ADAPTERS, "anthropic", FailingAdapter)
    guarded_registry = ProviderRegistry(
        registry.db, secrets,
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    result = _run_guarded_campaign_with_registry_v1(
        fixtures, registry=guarded_registry, authorization_sha256="a" * 64,
        final_execution_head="b" * 40, key_id="offline-fixture-key",
        signing_key=b"offline-fixture-signing-key-32-bytes-minimum",
    )

    assert secrets.get_calls == len(complete_calls) == 1
    assert result.transport_counters == {
        "http_post_attempts": 1, "network_requests": 1,
    }
    assert result.campaign_state["halt_code"] == "FIRST_DISPATCHED_FAILURE"
    assert result.campaign_state["records"][0]["state"] == "AMBIGUOUS_CONSUMED"
    assert {
        record["state"] for record in result.campaign_state["records"][1:]
    } == {"UNUSED"}
    assert result.sealed_evidence == ()


def test_real_dispatch_rejects_semantically_equal_non_authorized_wire_bytes(
    tmp_path,
) -> None:
    registry, secrets = _registry(tmp_path)
    fixture = build_synthetic_probe_fixtures(registry)[0]
    guarded_registry = ProviderRegistry(
        registry.db,
        secrets,
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    observer = campaign_module.GuardedProviderDispatch(
        (fixture,) + build_synthetic_probe_fixtures(registry)[1:],
        guarded_registry,
    )
    observer._active = fixture
    different_bytes = json.dumps(
        dict(fixture.payload), ensure_ascii=False, indent=1,
    ).encode("utf-8")
    assert json.loads(different_bytes) == dict(fixture.payload)
    assert different_bytes != fixture.payload_bytes

    with pytest.raises(CampaignFixtureError, match="DISPATCH_REQUEST_BINDING_MISMATCH"):
        observer.before_http_dispatch(
            method="POST",
            url=fixture.route.destination,
            payload=fixture.payload,
            request_bytes=different_bytes,
        )


def test_real_dispatch_rejects_destination_switch_with_authorized_bytes(
    tmp_path,
) -> None:
    registry, secrets = _registry(tmp_path)
    fixtures = build_synthetic_probe_fixtures(registry)
    fixture = fixtures[0]
    guarded_registry = ProviderRegistry(
        registry.db,
        secrets,
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    observer = campaign_module.GuardedProviderDispatch(fixtures, guarded_registry)
    observer._active = fixture

    with pytest.raises(CampaignFixtureError, match="DISPATCH_REQUEST_BINDING_MISMATCH"):
        observer.before_http_dispatch(
            method="POST",
            url="https://route-switch.invalid/v1/messages",
            payload=fixture.payload,
            request_bytes=fixture.payload_bytes,
        )


@pytest.mark.parametrize("finish_reason", ["max_tokens", "length"])
def test_real_pass_classification_rejects_truncated_plain_response(
    tmp_path, finish_reason,
) -> None:
    registry, _secrets = _registry(tmp_path)
    fixture = build_synthetic_probe_fixtures(registry)[0]
    response = ModelResponse(
        text="apparently complete", finish_reason=finish_reason,
        input_tokens=1, output_tokens=1,
    )
    assert not campaign_module.GuardedProviderDispatch._response_is_accepted(
        fixture, response,
    )


def test_real_pass_classification_rejects_empty_reasoning_only_projection(
    tmp_path,
) -> None:
    registry, _secrets = _registry(tmp_path)
    fixture = build_synthetic_probe_fixtures(registry)[0]
    response = ModelResponse(
        text="   ", finish_reason="end_turn", input_tokens=1, output_tokens=1,
        provider_state={"reasoning": "private reasoning only"},
    )
    assert not campaign_module.GuardedProviderDispatch._response_is_accepted(
        fixture, response,
    )


def test_real_pass_classification_rejects_wrong_structured_tool_name(
    tmp_path,
) -> None:
    registry, _secrets = _registry(tmp_path)
    fixture = build_synthetic_probe_fixtures(registry)[2]
    response = ModelResponse(
        tool_calls=[ToolCall(
            id="wrong", name="short_causal_chain", arguments={"events": [{}]},
        )],
        finish_reason="tool_use", input_tokens=1, output_tokens=1,
    )
    assert not campaign_module.GuardedProviderDispatch._response_is_accepted(
        fixture, response,
    )


def test_real_pass_classification_rejects_schema_invalid_tool_arguments(
    tmp_path,
) -> None:
    registry, _secrets = _registry(tmp_path)
    fixture = build_synthetic_probe_fixtures(registry)[2]
    response = ModelResponse(
        tool_calls=[ToolCall(
            id="invalid", name="planning_event_realizations",
            arguments={"events": []},
        )],
        finish_reason="tool_use", input_tokens=1, output_tokens=1,
    )
    assert not campaign_module.GuardedProviderDispatch._response_is_accepted(
        fixture, response,
    )


def test_real_pass_classification_accepts_one_schema_valid_expected_tool(
    tmp_path,
) -> None:
    registry, _secrets = _registry(tmp_path)
    fixture = build_synthetic_probe_fixtures(registry)[2]
    response = ModelResponse(
        tool_calls=[ToolCall(
            id="valid", name="planning_event_realizations",
            arguments={"events": [{}]},
        )],
        finish_reason="tool_use", input_tokens=1, output_tokens=1,
    )
    assert campaign_module.GuardedProviderDispatch._response_is_accepted(
        fixture, response,
    )
