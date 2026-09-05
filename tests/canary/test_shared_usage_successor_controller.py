"""Fresh proof revalidation and capture-before-conversion at the real HTTP seam."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import shutil

import httpx
import pytest

from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers import registry as registry_module
from novel_flywheel.secrets import MemorySecretStore
from tools.canary import execute_full_short_budget_unblocked_one_round as controller
from canary.test_full_short_budget_unblocked_orchestrator import KEY, KEY_ID, _materialized


def _proof_repo(tmp_path):
    source = Path(__file__).resolve().parents[2]
    repo = tmp_path / "proof-repo"
    report_root = controller._SHARED_USAGE_EVIDENCE_ROOT
    target = repo / report_root
    target.mkdir(parents=True)
    for name in ("authoritative-usage-semantics-v1.json", "probe01-replay-after-fix-v1.json",
                 "probe01-workload-evidence-disposition-v1.json", "shared-protocol-request-zero-diff-v1.json"):
        shutil.copyfile(source / report_root / name, target / name)
    # This is explicitly a unit gate fixture, not reported as execution evidence.
    (target / "shared-protocol-response-regression-matrix-v1.json").write_bytes(json.dumps({
        "status": "PASS", "SHARED_PROTOCOL_REGRESSION_COUNT": 0,
        "PRECISE_CHILD_CAUSE_LOST_TO_INCOMPLETE_TERMINAL_COUNT": 0,
        "cases": [{"id": f"unit-{i}", "status": "PASS"} for i in range(12)],
    }).encode())
    for relative in ("provider_payloads.py", "providers/http.py", "providers/registry.py",
                     "context_policy.py", "providers/anthropic.py"):
        path = Path("src/novel_flywheel") / relative
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / path, repo / path)
    return repo, target


def test_successor_proof_bytes_and_current_request_sources_are_revalidated(tmp_path):
    repo, _ = _proof_repo(tmp_path)
    proof = controller._shared_usage_recovery_binding_v1(repo)
    authorization = {"schema": controller.SHARED_USAGE_RECOVERY_SCHEMA,
                     "shared_protocol_usage_recovery": proof}
    controller._require_shared_usage_recovery_binding_v1(repo, authorization)
    source = repo / "src/novel_flywheel/provider_payloads.py"
    source.write_bytes(source.read_bytes() + b"\n# drift\n")
    with pytest.raises(controller.OneRoundCampaignError, match="REQUEST_BUILDER_SOURCE_DRIFT"):
        controller._require_shared_usage_recovery_binding_v1(repo, authorization)


@pytest.mark.parametrize("filename,field,value", [
    ("authoritative-usage-semantics-v1.json", "AUTHORITATIVE_CUMULATIVE_USAGE_SEMANTICS_VERIFIED", "NO"),
    ("probe01-replay-after-fix-v1.json", "CANONICAL_FINAL_PROVIDER_INPUT_TOKENS", 48916),
    ("probe01-workload-evidence-disposition-v1.json", "PROBE01_HISTORICAL_EVIDENCE_DISPOSITION", "REPLAY_PROVEN_PASS"),
    ("shared-protocol-request-zero-diff-v1.json", "OUTBOUND_REQUEST_BODY_CHANGED_COUNT", 1),
    ("shared-protocol-response-regression-matrix-v1.json", "PRECISE_CHILD_CAUSE_LOST_TO_INCOMPLETE_TERMINAL_COUNT", 1),
])
def test_semantic_gate_failure_cannot_be_authorized_by_a_fresh_hash(tmp_path, filename, field, value):
    repo, target = _proof_repo(tmp_path)
    path = target / filename
    document = json.loads(path.read_bytes())
    document[field] = value
    path.write_bytes(json.dumps(document).encode())
    with pytest.raises(controller.OneRoundCampaignError, match="PROTOCOL_GATE_NOT_PASS"):
        controller._shared_usage_recovery_binding_v1(repo)


def test_http_metadata_is_sealed_to_reserved_nonce_even_when_usage_conversion_fails(tmp_path, monkeypatch):
    materialized, repo, fixtures, db, *_ = _materialized(tmp_path, monkeypatch)
    secrets = MemorySecretStore()
    for fixture in fixtures:
        secrets.set(fixture.route.provider_id, "offline-only-secret")
    monkeypatch.setattr(controller, "KeyringSecretStore", lambda: secrets)
    raw = json.dumps({"id": "safe", "content": [{"type": "text", "text": "safe"}],
                      "stop_reason": "end_turn", "usage": {"input_tokens": -1, "output_tokens": 9}}).encode()

    class OfflineAdapter(AnthropicAdapter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, injected_http_transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=raw, headers={"content-type": "application/json"})))

    monkeypatch.setitem(registry_module.ADAPTERS, "anthropic", OfflineAdapter)
    with pytest.raises(controller.OneRoundCampaignError, match="FIRST_DISPATCHED_PROBE_FAILURE"):
        controller.run_probe_phase_v1(materialized, repo=repo, fixtures=fixtures,
            db=db, store_root=tmp_path / "store", verification_key_id=KEY_ID, verification_key=KEY)
    envelope = json.loads((materialized.evidence_root / "probe-capture-metadata-01.json").read_bytes())
    state = json.loads((materialized.evidence_root / "probe-terminal-state-v1.json").read_bytes())
    body = envelope["metadata"]
    assert body["nonce_sha256"] == state["records"][0]["nonce_sha256"]
    assert body["provider_entity_sha256"] == hashlib.sha256(raw).hexdigest()
    assert body["request_sha256"] == fixtures[0].request_sha256
    assert body["status_code"] == 200 and body["transport_complete"] is True
    assert envelope["metadata_hmac_sha256"] == hmac.new(KEY,
        b"probe-protocol-capture-metadata-v1\0" + controller.canonical_json_bytes(body), hashlib.sha256).hexdigest()
    assert state["records"][0]["typed_code"].endswith("provider_reported_usage_field_invalid.input_tokens")
    assert state["records"][1]["state"] == "UNUSED"
    assert "offline-only-secret" not in json.dumps(envelope)
