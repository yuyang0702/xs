from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from novel_flywheel.models import ModelDispatchScopeViolationError, ModelGateway
from novel_flywheel.providers.http import HttpProvider, SingleDispatchTransportGuardError
from novel_flywheel.reliability_spine import (
    CanonicalDispatchCoordinator,
    CanonicalDispatchError,
    CutoverRegistry,
    DurableNodeStateStore,
    RecoveryCoordinator,
    ReleaseBuildIdentity,
    TypedFailureGraphStore,
)


def _metadata(**changes):
    value = {
        "project_id": "project-a",
        "run_id": "run-a",
        "workflow_kind": "short-story",
        "stage": "review",
        "logical_node_id": "segment-review",
        "candidate_sha256": "a" * 64,
        "contract_name": "draft_segment_semantic_receipt",
        "contract_version": 1,
        "schema_sha256": "b" * 64,
        "provider_id": "provider-a",
        "model_id": "model-a",
        "route_fingerprint": "c" * 64,
        "protocol": "openai-chat",
        "destination": "https://provider.invalid:443/v1/chat/completions",
        "execution_mode": "strict_json_schema",
        "max_output_tokens": 2048,
        "cutover_state": "CUTOVER",
    }
    value.update(changes)
    return value


def _provider(handler, *, runtime_path_id=""):
    return HttpProvider(
        "https://provider.invalid/v1", "secret",
        injected_http_transport=httpx.MockTransport(handler),
        canonical_dispatch_required=True,
        canonical_runtime_path_id=runtime_path_id,
    )


@pytest.mark.asyncio
async def test_legacy_direct_transport_is_unreachable(tmp_path: Path) -> None:
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(200, json={"ok": True})

    provider = _provider(handler)
    with pytest.raises(SingleDispatchTransportGuardError) as raised:
        await provider.post("chat/completions", payload={"model": "m"}, headers={})
    assert str(raised.value) == "canonical_spine_required"
    assert sent == 0


@pytest.mark.asyncio
async def test_legacy_direct_transport_is_recorded_as_blocked_old_path(tmp_path: Path) -> None:
    spine = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    provider = HttpProvider(
        "https://provider.invalid/v1", "secret",
        injected_http_transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        canonical_dispatch_required=True,
        canonical_runtime_path_id=spine.release.runtime_path_id,
        canonical_dispatch_failure_handler=spine.record_old_path_invocation,
    )
    with pytest.raises(SingleDispatchTransportGuardError):
        await provider.post("chat/completions", payload={"model": "m"}, headers={})
    assert spine.old_path_invocations == 1
    assert "legacy_direct_provider_dispatch" in (
        spine.root / "old-path-invocations.jsonl"
    ).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_canonical_spine_records_physical_request_and_manifest(tmp_path: Path) -> None:
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(200, json={"ok": True})

    spine = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    admitted = spine.admit(_metadata())
    provider = _provider(handler, runtime_path_id=spine.release.runtime_path_id)
    provider.bind_canonical_dispatch(admitted["canonical_dispatch_authorization"])

    assert await provider.post("chat/completions", payload={"model": "m"}, headers={}) == {"ok": True}
    assert sent == 1

    records = [json.loads(line) for line in spine.ledger_path.read_text(encoding="utf-8").splitlines()]
    assert [item["state"] for item in records] == [
        "RESERVED", "DISPATCHING", "RESPONSE_CAPTURED", "RESPONSE_RECEIVED",
    ]
    assert len({item["physical_request_id"] for item in records}) == 1
    assert len({item["runtime_path_id"] for item in records}) == 1
    manifest = json.loads(next(spine.manifest_root.glob("*.json")).read_text(encoding="utf-8"))
    assert manifest["state"] == "RESPONSE_RECEIVED"
    assert manifest["physical_request_id"] == records[0]["physical_request_id"]
    evidence_path = spine.root / manifest["response_evidence_path"]
    evidence_bytes = evidence_path.read_bytes()
    assert manifest["response_evidence_sha256"] == hashlib.sha256(
        evidence_bytes
    ).hexdigest()
    assert json.loads(evidence_bytes)["evidence"]["structured"] == {"ok": True}


@pytest.mark.asyncio
async def test_hidden_stream_compatibility_retry_cannot_bypass_ledger(tmp_path: Path) -> None:
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(
            400,
            headers={"content-type": "application/json"},
            json={"error": "stream_options unsupported"},
        )

    spine = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    admitted = spine.admit(_metadata())
    provider = _provider(handler, runtime_path_id=spine.release.runtime_path_id)
    provider.bind_canonical_dispatch(admitted["canonical_dispatch_authorization"])

    with pytest.raises((httpx.HTTPStatusError, SingleDispatchTransportGuardError)):
        await provider.post_stream(
            "chat/completions",
            payload={"model": "m", "stream": True, "stream_options": {"include_usage": True}},
            headers={},
        )
    assert sent == 1
    records = [json.loads(line) for line in spine.ledger_path.read_text(encoding="utf-8").splitlines()]
    assert [item["state"] for item in records] == [
        "RESERVED", "DISPATCHING", "RESPONSE_CAPTURED", "RESPONSE_RECEIVED",
    ]
    status = spine.status_for_run("run-a")
    assert status["last_physical_request"]["state"] == "RESPONSE_RECEIVED"
    assert status["unknown_or_dispatching_count"] == 0


@pytest.mark.asyncio
async def test_canonical_capture_redacts_hidden_reasoning_and_keeps_final_content(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "reasoning": "private chain",
                "output": {"verdict": "PASS"},
            },
        )

    spine = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    admitted = spine.admit(_metadata())
    provider = _provider(handler, runtime_path_id=spine.release.runtime_path_id)
    provider.bind_canonical_dispatch(admitted["canonical_dispatch_authorization"])

    result = await provider.post(
        "chat/completions", payload={"model": "m"}, headers={},
    )

    assert result["output"] == {"verdict": "PASS"}
    manifest = json.loads(next(spine.manifest_root.glob("*.json")).read_text())
    evidence = json.loads(
        (spine.root / manifest["response_evidence_path"]).read_text()
    )
    structured = evidence["evidence"]["structured"]
    assert structured["output"] == {"verdict": "PASS"}
    assert structured["reasoning"]["redacted"] is True
    assert "private chain" not in json.dumps(evidence)


@pytest.mark.asyncio
async def test_capture_write_failure_preserves_consumed_response_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(200, json={"ok": True})

    spine = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    admitted = spine.admit(_metadata())
    provider = _provider(handler, runtime_path_id=spine.release.runtime_path_id)
    provider.bind_canonical_dispatch(admitted["canonical_dispatch_authorization"])
    monkeypatch.setattr(
        spine, "_capture_provider_response",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        await provider.post(
            "chat/completions", payload={"model": "m"}, headers={},
        )

    assert sent == 1
    records = [
        json.loads(line)
        for line in spine.ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["state"] == "RESPONSE_CAPTURE_FAILED"
    assert all(item["state"] != "TRANSPORT_CONFIRMED_FAILED" for item in records)


@pytest.mark.asyncio
async def test_mixed_release_worker_is_fenced_before_transport(tmp_path: Path) -> None:
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(200, json={"ok": True})

    first = CanonicalDispatchCoordinator(tmp_path / "first", worker_fencing_id="worker-a")
    second = CanonicalDispatchCoordinator(tmp_path / "second", worker_fencing_id="worker-b")
    admitted = first.admit(_metadata())
    provider = _provider(handler, runtime_path_id=second.release.runtime_path_id)
    provider.bind_canonical_dispatch(admitted["canonical_dispatch_authorization"])

    with pytest.raises(SingleDispatchTransportGuardError) as raised:
        await provider.post("chat/completions", payload={"model": "m"}, headers={})
    assert str(raised.value) == "mixed_release_worker_fenced"
    assert sent == 0


@pytest.mark.asyncio
async def test_real_canary_requires_persisted_foundation_gates(tmp_path: Path) -> None:
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(200, json={"ok": True})

    spine = CanonicalDispatchCoordinator(
        tmp_path, worker_fencing_id="worker-a", require_foundation_gates=True,
    )
    admitted = spine.admit(_metadata())
    provider = _provider(handler, runtime_path_id=spine.release.runtime_path_id)
    provider.bind_canonical_dispatch(admitted["canonical_dispatch_authorization"])
    with pytest.raises(CanonicalDispatchError, match="foundation_gates_incomplete"):
        await provider.post("chat/completions", payload={"model": "m"}, headers={})
    assert sent == 0


def test_stale_prepared_work_and_ambiguous_cutover_fail_closed(tmp_path: Path) -> None:
    spine = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    with pytest.raises(CanonicalDispatchError) as raised:
        spine.admit(_metadata(cutover_state="SHADOW_AND_CUTOVER"))
    assert raised.value.code == "ambiguous_cutover_state"

    authorization = spine.admit(_metadata())["canonical_dispatch_authorization"]
    spine.release = ReleaseBuildIdentity.collect(tmp_path, worker_fencing_id="worker-b")
    with pytest.raises(CanonicalDispatchError) as stale:
        authorization.before_network()
    assert stale.value.code == "stale_prepared_work_identity"


def test_route_change_invalidates_prepared_node_before_network(tmp_path: Path) -> None:
    spine = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    spine.admit(_metadata())
    with pytest.raises(CanonicalDispatchError, match="stale_durable_node_identity"):
        spine.admit(_metadata(route_fingerprint="d" * 64))


def test_config_change_fences_prepared_work_before_network(tmp_path: Path) -> None:
    spine = CanonicalDispatchCoordinator(
        tmp_path, worker_fencing_id="worker-a", config_version="cfg-1",
    )
    authorization = spine.admit(
        _metadata(config_version="cfg-1")
    )["canonical_dispatch_authorization"]
    spine.cutover = CutoverRegistry(config_version="cfg-2")
    with pytest.raises(CanonicalDispatchError) as raised:
        authorization.before_network()
    assert raised.value.code == "can_run_real_dispatch_proof_failed"


def test_gateway_binds_exact_coordinator_authorization(tmp_path: Path) -> None:
    spine = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    adapter = SimpleNamespace(bound=None)
    adapter.bind_canonical_dispatch = lambda value: setattr(adapter, "bound", value)
    resolved = SimpleNamespace(
        provider_id="provider-a", model_id="model-a", protocol="openai-chat",
        destination="https://provider.invalid:443/v1/chat/completions",
        adapter=adapter,
    )
    gateway = ModelGateway(SimpleNamespace(get_run=lambda _run_id: None), SimpleNamespace())
    gateway.dispatch_admitter = spine.admit
    metadata = gateway._admit_transport_dispatch(
        role="review", resolved=resolved, execution_mode="strict_json_schema",
        stage="review", contract_name="receipt", contract_version=1,
        schema_sha256="b" * 64, route_fingerprint="c" * 64,
        max_output_tokens=1024,
    )
    assert adapter.bound is metadata["canonical_dispatch_authorization"]
    assert metadata["runtime_path_id"] == spine.release.runtime_path_id
    assert metadata["physical_request_id"] == adapter.bound.physical_request_id


def test_gateway_binds_run_config_and_request_identity_before_admission() -> None:
    class FakeDb:
        def list_providers(self):
            return []

        def list_role_bindings(self):
            return []

        def get_run(self, run_id):
            assert run_id == "run-a"
            return {
                "id": run_id, "project_id": "project-a",
                "workflow": "short-story",
            }

    captured = {}
    gateway = ModelGateway(FakeDb(), SimpleNamespace())
    gateway.dispatch_admitter = lambda metadata: captured.update(metadata) or {}
    resolved = SimpleNamespace(
        provider_id="provider-a", model_id="model-a", protocol="openai-chat",
        destination="https://provider.invalid/v1", adapter=SimpleNamespace(),
    )
    with gateway.bind_workflow_execution_identity(
        project_id="project-a", run_id="run-a", workflow_kind="short-story",
    ):
        gateway._admit_transport_dispatch(
            role="planning", resolved=resolved, execution_mode="strict_json_schema",
            stage="planning", contract_name="planning_semantic_v2",
            contract_version=2, schema_sha256="b" * 64,
            route_fingerprint="c" * 64, system="system", user="user",
        )

    assert captured["project_id"] == "project-a"
    assert captured["operation_run_id"] == "run-a"
    assert captured["workflow_kind"] == "short-story"
    assert len(captured["config_version"]) == 64
    assert len(captured["candidate_sha256"]) == 64
    assert captured["logical_node_id"].startswith(
        "run-a:planning:planning_semantic_v2:"
    )


def test_gateway_binds_plain_draft_contract_before_canonical_admission() -> None:
    """A real Draft call may be prose-only, but its durable node is not unbound."""

    class FakeDb:
        def list_providers(self):
            return []

        def list_role_bindings(self):
            return []

        def get_run(self, run_id):
            assert run_id == "run-a"
            return {
                "id": run_id, "project_id": "project-a",
                "workflow": "short-story",
            }

    captured = {}
    gateway = ModelGateway(FakeDb(), SimpleNamespace())
    gateway.dispatch_admitter = lambda metadata: captured.update(metadata) or {}
    resolved = SimpleNamespace(
        provider_id="provider-a", model_id="model-a", protocol="anthropic",
        destination="https://provider.invalid/v1", adapter=SimpleNamespace(),
    )
    with gateway.bind_workflow_execution_identity(
        project_id="project-a", run_id="run-a", workflow_kind="short-story",
    ):
        gateway._admit_transport_dispatch(
            role="draft", resolved=resolved, execution_mode="plain",
            stage="draft", route_fingerprint="c" * 64,
            system="system", user="prose request",
        )

    assert captured["contract_name"] == "draft_plain_completion"
    assert captured["project_id"] == "project-a"
    assert captured["operation_run_id"] == "run-a"
    assert len(captured["candidate_sha256"]) == 64
    assert captured["logical_node_id"].startswith(
        "run-a:draft:draft_plain_completion:"
    )


def test_gateway_route_change_has_distinct_durable_node_identity() -> None:
    class FakeDb:
        def list_providers(self):
            return []

        def list_role_bindings(self):
            return []

        def get_run(self, _run_id):
            return {"project_id": "project-a", "workflow": "short-story"}

    nodes = []
    gateway = ModelGateway(FakeDb(), SimpleNamespace())
    gateway.dispatch_admitter = lambda metadata: nodes.append(
        metadata["logical_node_id"]
    ) or {}
    resolved = SimpleNamespace(
        provider_id="provider-a", model_id="model-a", protocol="openai-chat",
        destination="https://provider.invalid/v1", adapter=SimpleNamespace(),
    )
    with gateway.bind_workflow_execution_identity(
        project_id="project-a", run_id="run-a", workflow_kind="short-story",
    ):
        for route in ("c" * 64, "d" * 64):
            gateway._admit_transport_dispatch(
                role="review", resolved=resolved,
                execution_mode="strict_json_schema", stage="review",
                contract_name="receipt", contract_version=1,
                schema_sha256="b" * 64, route_fingerprint=route,
                system="same", user="same",
            )
    assert len(set(nodes)) == 2


def test_gateway_projects_canonical_pre_dispatch_rejection_as_local() -> None:
    gateway = ModelGateway(SimpleNamespace(get_run=lambda _run_id: None), SimpleNamespace())
    gateway.dispatch_admitter = lambda _metadata: (_ for _ in ()).throw(
        CanonicalDispatchError("stale_cutover_config")
    )
    resolved = SimpleNamespace(
        provider_id="provider-a", model_id="model-a", protocol="openai-chat",
        destination="https://provider.invalid/v1", adapter=SimpleNamespace(),
    )
    with pytest.raises(ModelDispatchScopeViolationError) as raised:
        gateway._admit_transport_dispatch(
            role="review", resolved=resolved, execution_mode="plain",
        )
    assert raised.value.code == "stale_cutover_config"
    assert raised.value.provider_call_executed is False


def test_production_spine_rejects_incomplete_episode_identity(tmp_path: Path) -> None:
    spine = CanonicalDispatchCoordinator(
        tmp_path, worker_fencing_id="worker-a", require_release=True,
        config_version="f" * 64,
    )
    metadata = _metadata(config_version="f" * 64)
    metadata.pop("project_id")
    with pytest.raises(CanonicalDispatchError) as raised:
        spine.admit(metadata)
    assert raised.value.code == "canonical_episode_identity_incomplete"


def test_runtime_attestation_exposes_single_production_authority(tmp_path: Path) -> None:
    spine = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    attestation = spine.attest()
    assert attestation["runtime_path_attestation"] == "PASS"
    assert attestation["canonical_production_entrypoints"] == "PASS"
    assert attestation["provider_dispatch_decision_makers"] == 1
    assert attestation["legacy_entrypoint_direct_provider_dispatch"] == 0


def test_negative_old_path_matrix_is_fail_closed_without_bound_evidence(tmp_path: Path) -> None:
    spine = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    pending = spine.negative_old_path_reachability_matrix()
    assert pending["pass"] is False
    assert pending["status"] == "PENDING_EVIDENCE"

    evidence = {
        "schema": "NegativeOldPathReachabilityMatrixV1",
        "release_build_id": spine.release.build_id,
        "runtime_path_id": spine.release.runtime_path_id,
        "provider_http_performed": False,
        "provider_http_count": 0,
        "provider_bypass_count": 0,
        "checks": {
            "ambiguous_cutover": True,
            "stale_prepared_work": True,
            "missing_manifest_replay": True,
            "old_worker_fencing": True,
            "hidden_sdk_retry": True,
            "legacy_supervisor_retry": True,
            "historical_checkpoint_migration": True,
        },
    }
    (spine.root / "old-path-reachability-matrix.json").write_text(
        json.dumps(evidence), encoding="utf-8"
    )
    passed = spine.negative_old_path_reachability_matrix()
    assert passed["pass"] is True
    assert passed["status"] == "PASS"


def test_recovery_condition_signature_survives_coordinator_restart(tmp_path: Path) -> None:
    metadata = _metadata(
        project_id="project-a", run_id="run-a", operation_run_id="run-a",
        logical_node_id="review-05", capability_snapshot={"strict_json": True},
        config_version="cfg-1", failure_sha256="f" * 64,
    )
    first = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    first_result = first.evaluate_reentry(
        metadata, node_state="BLOCKED_RECOVERABLE",
        failure_class="receipt_invalid", blocker_signature="f" * 64,
    )
    assert first_result["provider_intent_created"] is False
    assert first_result["physical_dispatch_allowed"] is True

    restarted = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    second_result = restarted.evaluate_reentry(
        metadata, node_state="BLOCKED_RECOVERABLE",
        failure_class="receipt_invalid", blocker_signature="f" * 64,
    )
    assert second_result["action"] == "NO_ACTION"
    assert second_result["provider_intent_created"] is False
    assert second_result["recovery_child_id"] == first_result["recovery_child_id"]


def test_foundation_gates_are_stale_for_a_different_worker_identity(tmp_path: Path) -> None:
    gates = {
        "F1_CANONICAL_EPISODE_IDENTITY": "PASS",
        "F2_PHYSICAL_REQUEST_LEDGER": "PASS",
        "F3_TYPED_FAILURE_GRAPH": "PASS",
        "F4_NODE_LEVEL_DURABLE_STATE": "PASS",
        "F5_CAPTURE_MANIFEST": "PASS",
        "F6_SINGLE_RECOVERY_COORDINATOR": "PASS",
        "F7_RELEASE_BUILD_IDENTITY_AND_WORKER_FENCING": "PASS",
        "F8_PRODUCTION_SHAPED_CORE_MATRIX": "PASS",
    }
    first = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-a")
    first.mark_foundation_gates(gates, evidence_refs=("fixture://foundation",))
    assert all(value == "PASS" for value in first.foundation_gates().values())

    different_worker = CanonicalDispatchCoordinator(tmp_path, worker_fencing_id="worker-b")
    assert all(value == "STALE" for value in different_worker.foundation_gates().values())


def test_durable_node_cas_and_failure_graph_preserve_root_cause(tmp_path: Path) -> None:
    nodes = DurableNodeStateStore(tmp_path / "spine")
    node = nodes.prepare(
        node_id="review-05", episode_id="episode-05",
        candidate_sha256="a" * 64, contract_sha256="b" * 64,
        release_build_id="build-1", cutover_version="cutover-1",
    )
    assert node.state == "REVIEW_PREPARED"
    captured = nodes.transition("review-05", expected_state="REVIEW_PREPARED",
                                state="RESPONSE_CAPTURED")
    assert captured.version == 2
    with pytest.raises(CanonicalDispatchError, match="cas"):
        nodes.transition("review-05", expected_state="REVIEW_PREPARED",
                         state="RECEIPT_VALIDATED")

    graph = TypedFailureGraphStore(tmp_path / "spine")
    record = graph.record(
        failure_class="receipt_invalid", source_component="validator",
        episode_id="episode-05", physical_request_id="physical-1",
        condition_signature="sig-1", recovery_eligible=True, terminal=False,
        evidence_refs=("capture-1",),
    )
    assert record.failure_id
    line = (tmp_path / "spine" / "typed-failure-graph.jsonl").read_text()
    assert "receipt_invalid" in line and "capture-1" in line


def test_durable_node_legacy_checkpoint_adapter_is_idempotent(tmp_path: Path) -> None:
    store = DurableNodeStateStore(tmp_path / "spine")
    path = store._path("legacy-node")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "ShortDurableNodeV1", "node_id": "legacy-node",
        "episode_id": "episode", "state": "REVIEW_PREPARED", "version": 1,
        "candidate_sha256": "a" * 64, "contract_sha256": "b" * 64,
        "release_build_id": "build", "cutover_version": "cutover",
        "updated_at": "2026-09-22T00:00:00+00:00",
    }), encoding="utf-8")
    first = store.load("legacy-node")
    second = store.load("legacy-node")
    assert first == second
    assert first is not None and first.route_fingerprint == ""


def test_recovery_coordinator_stops_same_signature_and_replays_saved_response(tmp_path: Path) -> None:
    coordinator = RecoveryCoordinator(tmp_path / "spine")
    first = coordinator.decide(node_state="REVIEW_PREPARED",
                               condition_signature="same", failure_class="receipt_invalid")
    second = coordinator.decide(node_state="REVIEW_PREPARED",
                                condition_signature="same", failure_class="receipt_invalid")
    assert first.action == "RECEIPT_CORRECTION"
    assert second.action == "NO_ACTION"
    replay = coordinator.decide(node_state="RESPONSE_CAPTURED",
                                condition_signature="saved", failure_class="transport")
    assert replay.action == "LOCAL_REPLAY_VALIDATION"


def test_cutover_registry_rejects_dual_authority() -> None:
    registry = CutoverRegistry(state="CUTOVER", active_authority="legacy")
    with pytest.raises(CanonicalDispatchError, match="authority"):
        registry.validate()
