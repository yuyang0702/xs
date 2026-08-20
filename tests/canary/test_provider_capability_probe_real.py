from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.canary import provider_capability_probe_real as probe


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKET_ROOT = (
    REPO_ROOT / "docs/superpowers/reports/r1-ptr4-probe-mat"
    / "r1-ptr4-probe-20260820t110721z-001"
)


def _request():
    receipt = probe._sealed(
        "r1-ptr4-probe-real-request-reassembly-v1", {
            "schema": "ProviderCapabilityProbeRequestReassemblyReceiptV1",
            "version": 1,
            "status": "exact",
            "source_content_embedded": False,
            "base_system_sha256": "64efaf5d938f38c073358772254169da653b76fae69a744f547d72782f5740a8",
            "target_system_sha256": probe.SYSTEM_SHA256,
            "target_user_sha256": probe.USER_SHA256,
            "target_boundary_identity_sha256": probe.TARGET_SHA256,
            "definition_sha256": probe.DEFINITION_SHA256,
            "fixture_sha256": probe.FIXTURE_SHA256,
            "contract_sha256": "f23bb155296d9df6bf8e8992108c651c3354fd4d791dc0bbbcc46d2943cd42c7",
            "tool_schema_sha256": "5424046dc2054fb588e161be0ef09b4badc53b150c78dc9f6ca3866cca590311",
            "route_kind": "configured_fallback",
            "protocol": "anthropic",
            "execution_mode": "plain",
            "requested_max_output_tokens": probe.MAX_OUTPUT_TOKENS,
            "raw_prompt_omitted": True,
            "raw_story_omitted": True,
            "raw_tool_arguments_omitted": True,
            "external_action_counters": {
                "credential_lookup_count": 0,
                "provider_client_creation_count": 0,
                "network_call_count": 0,
                "model_call_count": 0,
                "paid_model_call_count": 0,
            },
        }, "request_reassembly_receipt_sha256",
    )
    return {
        "system": "not persisted",
        "user": "not persisted",
        "formal_events": [{"id": "EV-1"}],
        "formal_ending": {},
        "owned_event_count": 1,
        "receipt": receipt,
    }


@pytest.fixture
def offline(monkeypatch, tmp_path):
    parity = {"parity_sha256": "a" * 64}
    monkeypatch.setattr(probe, "reassemble_boundary_12_request", lambda _root: _request())
    monkeypatch.setattr(probe, "live_parity_manifest", lambda **_kwargs: parity)
    monkeypatch.setattr(probe, "parity_equal", lambda left, right: left == right)
    monkeypatch.setattr(probe, "_utc_now", lambda: "2026-08-20T12:00:00Z")
    monkeypatch.setattr(probe, "_validate_live_route", lambda _db: {
        "provider_alias": "provider", "model_alias": "model",
        "provider_descriptor_hash": probe.PROVIDER_SHA256,
        "model_binding_hash": probe.MODEL_SHA256, "protocol": "anthropic",
    })
    output = tmp_path / "real-observation-v1"
    common = {
        "repo_root": REPO_ROOT,
        "packet_root": PACKET_ROOT,
        "output_root": output,
        "source_root": tmp_path,
        "live_database": tmp_path / "app.db",
        "live_projects": tmp_path / "projects",
    }
    return output, common


def test_fresh_packet_is_exact_and_still_disabled():
    value = probe.verify_fresh_packet_exact(REPO_ROOT, PACKET_ROOT)
    assert value["plan"]["plan_sha256"] == probe.PLAN_SHA256
    assert value["candidate"]["execution_authorized"] is False
    assert value["candidate"]["usage_status"] == "unused"
    assert value["packet_ledger"]["entry_count"] == 0


def test_signed_materialization_is_exact_and_external_zero(offline):
    output, common = offline
    value = probe.materialize_signed_authorization(**common)
    assert value["patch"]["execution_authorized"] is True
    assert value["signed_approval"]["maximum_executions"] == 1
    assert value["receipt"]["overall_status"] == "exact"
    assert set(value["receipt"]["external_action_counters"].values()) == {0}
    assert not (output / "approval-ledger" / "reserved-v1.json").exists()


def test_signed_validator_rejects_tamper(offline):
    output, common = offline
    probe.materialize_signed_authorization(**common)
    path = output / "authorization/provider-capability-probe-signed-approval-v1.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["second_run_allowed"] = True
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(probe.ProviderCapabilityProbeRealError, match="signed_approval_hash_mismatch"):
        probe.validate_signed_authorization(**common)


def test_signed_validator_rejects_expired_window(offline, monkeypatch):
    _output, common = offline
    probe.materialize_signed_authorization(**common)
    monkeypatch.setattr(probe, "_utc_now", lambda: "2026-08-23T00:00:00Z")
    with pytest.raises(probe.ProviderCapabilityProbeRealError, match="approval_outside_execution_window"):
        probe.validate_signed_authorization(**common)


def test_request_reassembly_receipt_contains_no_raw_content():
    value = _request()["receipt"]
    serialized = json.dumps(value, ensure_ascii=False).casefold()
    assert "not persisted" not in serialized
    assert value["raw_prompt_omitted"] is True
    assert value["raw_story_omitted"] is True


def test_stream_event_shape_capture_is_content_free():
    blocks, finish, tokens = probe._block_metadata_from_events([
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "secret-text"}},
        {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {"output_tokens": 31}},
    ])
    assert blocks == [
        {"block_type": "thinking", "visible_text_characters": 0, "tool_arguments_present": False, "tool_argument_byte_length": 0, "partial_tool_arguments": False},
        {"block_type": "text", "visible_text_characters": 11, "tool_arguments_present": False, "tool_argument_byte_length": 0, "partial_tool_arguments": False},
    ]
    assert "secret-text" not in json.dumps(blocks)
    assert finish == "max_tokens"
    assert tokens == 31


def test_execute_once_consumes_and_cannot_replay(offline, monkeypatch):
    output, common = offline
    probe.materialize_signed_authorization(**common)

    async def fake_call(*, live_database, request_data, counters):
        del live_database, request_data
        for key in counters:
            counters[key] = 1
        return {
            "capture": {
                "blocks": [{
                    "block_type": "reasoning", "visible_text_characters": 0,
                    "tool_arguments_present": False,
                    "tool_argument_byte_length": 0,
                    "partial_tool_arguments": False,
                }],
                "finish_reason": "max_tokens", "output_tokens": 8798,
            },
            "adapter_visible_characters": 0,
            "adapter_tool_arguments_present": False,
            "input_tokens": 29,
            "output_tokens": 8798,
            "reachability": {
                "parser_reached": True, "json_conversion_reached": False,
                "wire_schema_reached": False,
                "semantic_validation_reached": False,
            },
            "cost_currency": "USD", "actual_cost_microunits": 100,
            "maximum_cost_microunits": probe.MAX_USD_MICROUNITS,
        }

    monkeypatch.setattr(probe, "_execute_one_provider_call", fake_call)
    result = probe.execute_real_probe_once(**common)
    assert result["execution"]["executed_run_count"] == 1
    assert result["execution"]["external_action_counters"]["model_call_count"] == 1
    assert result["observation"]["provider_capability_evidence_status"] == "real_probe_observed"
    assert result["consumption"]["status"] == "consumed"
    with pytest.raises(probe.ProviderCapabilityProbeRealError, match="operational_ledger_not_unused"):
        probe.execute_real_probe_once(**common)


def test_provider_failure_is_terminal_and_consumes(offline, monkeypatch):
    output, common = offline
    probe.materialize_signed_authorization(**common)

    async def failed(*, live_database, request_data, counters):
        del live_database, request_data
        counters["credential_lookup_count"] = 1
        counters["provider_client_creation_count"] = 1
        counters["network_call_count"] = 1
        counters["model_call_count"] = 1
        counters["paid_model_call_count"] = 1
        raise ConnectionError("raw-error-must-not-persist")

    monkeypatch.setattr(probe, "_execute_one_provider_call", failed)
    result = probe.execute_real_probe_once(**common)
    assert result["execution"]["terminal_status"] == "typed_provider_call_failure"
    assert result["observation"] is None
    assert result["execution"]["observation_receipt_sha256"] is None
    assert not (output / "reports/provider-capability-probe-observation-v1.json").exists()
    serialized = json.dumps(result, ensure_ascii=False)
    assert "raw-error-must-not-persist" not in serialized
    assert (output / "approval-ledger/consumed-v1.json").is_file()


def test_materialization_rejects_reuse(offline):
    _output, common = offline
    probe.materialize_signed_authorization(**common)
    with pytest.raises(probe.ProviderCapabilityProbeRealError, match="signed_output_root_already_exists"):
        probe.materialize_signed_authorization(**common)
