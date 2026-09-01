from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from novel_flywheel.db import Database
from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.full_short_execution import (
    FullShortDispatchLedgerObserverV1,
    FullShortDurableExecutionStoreV1,
    FullShortExecutionBoundaryError,
    FullShortExecutionPolicyV1,
    RESPONSE_CAPTURE_POLICY_V1,
    LOGICAL_STAGE_RECOVERY_POLICY_SHA256,
    LOGICAL_STAGE_RECOVERY_POLICY_V1,
    TRANSPORT_RECOVERY_POLICY_SHA256,
    TRANSPORT_RECOVERY_POLICY_V1,
    _expected_provider_payload_v1,
    build_full_short_completion_receipt_v1,
    reconcile_full_short_capture_anchor_v1,
    replay_full_short_provider_attempt_v1,
    render_full_short_canonical_authorization_v1,
    validate_full_short_canonical_authorization_v1,
    validate_full_short_preflight_v1,
    validate_policy_v1,
)
from novel_flywheel.contract_runtime import (
    ExecutableContractSpec,
    execute_contract_runtime,
)
from novel_flywheel.provider_response_capture import (
    ProviderResponseCaptureError,
)
from novel_flywheel.providers.http import (
    HttpProvider,
    SingleDispatchTransportGuardError,
    SingleDispatchTransportPolicyV1,
)
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.structured_artifacts import StructuredArtifactContract
from novel_flywheel.runtime_fingerprint_build import domain_sha256
from tools.canary import first_trustworthy_full_short_runner as real_runner


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _egress() -> dict:
    return {
        "allowed": [
            "system_context", "task_contract", "authority", "story_slice",
            "current_baseline_skill_context", "output_contract",
            "provider_request_metadata",
        ],
        "forbidden": [
            "credentials", "unrelated_project_data", "raw_provider_evidence",
            "retired_skill_v3_hybrid_context",
        ],
    }


def _request(max_tokens: int = 128) -> ModelRequest:
    return ModelRequest(
        model="offline", messages=[], max_output_tokens=max_tokens,
    )


def _payload(max_tokens: int = 128) -> dict:
    return {
        "model": "offline", "messages": [], "max_tokens": max_tokens,
        "stream": True,
    }


def _routes() -> tuple[dict, ...]:
    return ({
        "role": "planning", "lane": "primary",
        "provider_id_sha256": hashlib.sha256(b"provider").hexdigest(),
        "model_id_sha256": hashlib.sha256(b"model-id").hexdigest(),
        "model_name": "offline", "protocol": "anthropic",
        "route_fingerprint": "9" * 64,
        "destination": "https://unit.test:443/v1/messages",
        "max_output_tokens": 4096,
    },)


def _logical_stage_plan(
    *stages: tuple[str, str, str, int, str, bool, int],
) -> tuple[dict, ...]:
    if not stages:
        stages = ((
            "planning", "planning", "unstructured_text", 1,
            _hash({}), False, 128,
        ),)
    occurrences: dict[str, int] = {}
    result = []
    for ordinal, (
        stage_id, role, contract_name, contract_version,
        contract_schema_sha256, runtime_input_required, output_tokens,
    ) in enumerate(stages, 1):
        occurrences[stage_id] = occurrences.get(stage_id, 0) + 1
        occurrence = occurrences[stage_id]
        logical_stage_id = stage_id
        if occurrence > 1:
            suffix = (
                f".{occurrence}."
                f"{hashlib.sha256(stage_id.encode('utf-8')).hexdigest()[:8]}"
            )
            logical_stage_id = f"{stage_id[:160-len(suffix)]}{suffix}"
        result.append({
            "ordinal": ordinal,
            "stage_id": stage_id,
            "logical_stage_base_id": stage_id,
            "logical_stage_id": logical_stage_id,
            "role": role,
            "contract_name": contract_name,
            "contract_version": contract_version,
            "contract_schema_sha256": contract_schema_sha256,
            "contract_runtime_input_required": runtime_input_required,
            "requested_output_tokens": output_tokens,
        })
    return tuple(result)


def _policy(
    store: FullShortDurableExecutionStoreV1 | None = None, *,
    expected_stage_calls: int = 1,
    routes: tuple[dict, ...] | None = None,
    logical_stage_plan: tuple[dict, ...] | None = None,
) -> dict:
    store_hash = store.store_root_sha256 if store is not None else "0" * 64
    bound_routes = routes or _routes()
    bound_plan = logical_stage_plan or _logical_stage_plan(*(
        (
            "planning", "planning", "unstructured_text", 1,
            _hash({}), False, 128,
        ) for _ in range(expected_stage_calls)
    ))
    return FullShortExecutionPolicyV1(
        execution_head="a" * 40,
        branch="test",
        run_id="test-full-short",
        project_id_sha256="b" * 64,
        workload_sha256="c" * 64,
        runtime_authority_sha256="d" * 64,
        style_reference_authority_sha256="e" * 64,
        route_manifest_sha256=_hash(list(bound_routes)),
        destination_manifest_sha256=_hash(sorted({
            str(item["destination"]) for item in bound_routes
        })),
        egress_policy_sha256=_hash(_egress()),
        store_root_sha256=store_hash,
        required_stage_roles=("planning",),
        logical_stage_plan=bound_plan,
        expected_stage_calls=expected_stage_calls,
        hard_max_provider_requests=4,
        hard_max_http_posts=4,
        hard_max_network_attempts=4,
        per_call_output_token_hard_cap=4096,
        total_output_token_hard_cap=4096,
        maximum_elapsed_seconds=3600,
    ).document()


def _store(tmp_path: Path) -> FullShortDurableExecutionStoreV1:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    return FullShortDurableExecutionStoreV1(
        repo_root=repo, store_root=tmp_path / "external-store",
    )


def _authorize_offline(
    store: FullShortDurableExecutionStoreV1, execution_id: str,
    *, expected_stage_calls: int = 1,
    routes: tuple[dict, ...] | None = None,
    logical_stage_plan: tuple[dict, ...] | None = None,
) -> tuple[dict, dict, dict]:
    policy = _policy(
        store, expected_stage_calls=expected_stage_calls, routes=routes,
        logical_stage_plan=logical_stage_plan,
    )
    permission = store.create_permission(
        execution_id=execution_id,
        authorization_text_sha256="3" * 64,
        policy=policy,
        external_actions_enabled=False,
    )
    approval = store.create_jit_approval(
        execution_id=execution_id,
        policy=policy,
        permission=permission,
        external_actions_enabled=False,
    )
    nonce = store.reserve_nonce(
        execution_id=execution_id,
        policy=policy,
        approval=approval,
        external_actions_enabled=False,
    )
    return permission, approval, nonce


def _observer(
    store: FullShortDurableExecutionStoreV1, execution_id: str, *,
    session_id: str | None = None, max_tokens: int = 128,
) -> FullShortDispatchLedgerObserverV1:
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id=execution_id, policy=_policy(store),
        authorized_routes=_routes(), egress_policy=_egress(),
        session_id=session_id,
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    observer.bind_model_request(
        protocol="anthropic", request=_request(max_tokens),
    )
    return observer


def _terminal(manuscript_sha256: str = "4" * 64) -> dict:
    body = {
        "schema": "ShortCompletionVerificationV1", "version": 1,
        "workflow_final_status": "completed",
        "unresolved_terminal_status": "none", "live_parity_status": "exact",
        "completion_goal_outcome": (
            "SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED"
        ),
        "final_manuscript_sha256": manuscript_sha256,
        "final_manuscript_binding_status": "exact",
        "final_review": {"accepted_status": "accepted", "binding_status": "exact"},
        "maintenance": {"closure_status": "exact"},
        "final_artifact": {"binding_status": "exact"},
        "final_checkpoint": {"closure_status": "exact"},
    }
    return {**body, "verification_receipt_sha256": domain_sha256(
        "novel-flywheel-short-completion-verification-v1", body,
    )}


def _dispatch_and_close(
    store: FullShortDurableExecutionStoreV1, execution_id: str,
) -> FullShortDispatchLedgerObserverV1:
    observer = _observer(store, execution_id)
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages",
        payload=_payload(),
    )
    observer.after_http_response(status_code=200)
    observer.mark_local_stage_complete(
        stage="planning", role="planning",
        role_binding_sha256=observer.bound_route["role_binding_sha256"],
        output_sha256="a" * 64, receipt_sha256="b" * 64,
    )
    return observer


def _local_rejection(*, route_attempt: int = 1) -> dict:
    return {
        "schema": "ContractLocalRejectionReceiptV1",
        "version": 1,
        "contract_name": "planning_semantic_v2",
        "contract_version": 2,
        "contract_schema_sha256": "1" * 64,
        "attempt_index": route_attempt,
        "route": "primary",
        "route_attempt": route_attempt,
        "failure_kind": "domain_validation",
        "failure_reason_sha256": "2" * 64,
        "response_text_sha256": "3" * 64,
        "conversion_audit_sha256": "4" * 64,
        "raw_content_persisted": False,
    }


def _final_artifact_rejection() -> dict:
    return {
        "schema": "ProviderFinalArtifactRejectionReceiptV1",
        "version": 1,
        "contract_name": "planning_semantic_v2",
        "contract_version": 2,
        "contract_schema_sha256": "a" * 64,
        "attempt_index": 1,
        "route": "primary",
        "route_attempt": 1,
        "failure_kind": "final_artifact_unavailable",
        "failure_code": "reasoning_only_final_artifact_unavailable",
        "failure_reason_sha256": "b" * 64,
        "provider_output_shape_sha256": "c" * 64,
        "contract_runtime_input_present": False,
        "raw_content_persisted": False,
    }


def _dispatch_reasoning_recovery_and_close(
    store: FullShortDurableExecutionStoreV1, execution_id: str,
) -> FullShortDispatchLedgerObserverV1:
    observer = _observer(store, execution_id)
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=_payload(),
    )
    observer.capture_provider_protocol_input(
        data=b"reasoning-only", status_code=200,
        content_type="application/json", encoding="utf-8",
        transport_complete=True,
    )
    observer.after_http_response(status_code=200)
    observer.mark_local_attempt_rejected(
        stage="planning", role="planning",
        role_binding_sha256=observer.bound_route["role_binding_sha256"],
        rejection=_final_artifact_rejection(),
    )
    observer.bind_stage_context(
        stage_id="planning", contract_name="unstructured_text",
        contract_version=1, contract_schema_sha256=_hash({}),
        stage_role="PLANNING_FINAL_ARTIFACT_RECOVERY",
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    recovery_request = _request().model_copy(update={
        "reasoning_directive": "disable_reasoning",
        "stage_role": "PLANNING_FINAL_ARTIFACT_RECOVERY",
    })
    observer.bind_model_request(
        protocol="anthropic", request=recovery_request,
    )
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages",
        payload={**_payload(), "reasoning": {"effort": "none"}},
    )
    observer.capture_provider_protocol_input(
        data=b'{"complete":true}', status_code=200,
        content_type="application/json", encoding="utf-8",
        transport_complete=True,
    )
    observer.after_http_response(status_code=200)
    observer.mark_local_stage_complete(
        stage="planning", role="planning",
        role_binding_sha256=observer.bound_route["role_binding_sha256"],
        output_sha256="a" * 64, receipt_sha256="b" * 64,
    )
    return observer


def test_live_authority_drift_fails_before_credential_lookup_or_nonce_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path / "credential-boundary")
    _authorize_offline(store, "authority-drift-before-secret")

    def reject_drift() -> None:
        raise FullShortExecutionBoundaryError("LIVE_AUTHORITY_DRIFT")

    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id="authority-drift-before-secret",
        policy=_policy(store), authorized_routes=_routes(),
        egress_policy=_egress(), live_authority_recheck=reject_drift,
    )
    db = Database(tmp_path / "credential-boundary" / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://unit.test/v1", auth_type="x-api-key",
        timeout_seconds=30, extra_headers={},
    )
    db.save_model(
        model_id="model-id", provider_id="provider", display_name="Model",
        model_name="offline", context_window=None, max_output_tokens=4096,
    )

    class CountingSecrets:
        calls = 0

        def get(self, _provider_id: str) -> str:
            self.calls += 1
            return "never-read"

    secrets = CountingSecrets()
    registry = ProviderRegistry(db, secrets, attempt_observer=observer)
    monkeypatch.setattr(
        registry, "route_fingerprint", lambda _provider, _model: "9" * 64,
    )

    with pytest.raises(FullShortExecutionBoundaryError) as drift:
        registry.resolve(
            "provider", "model-id", role="planning", lane="primary",
        )

    assert drift.value.reason_code == "LIVE_AUTHORITY_DRIFT"
    assert secrets.calls == 0
    assert store._read(
        "authority-drift-before-secret", "nonce",
    )["state"] == "RESERVED"
    assert store.load_ledger(
        "authority-drift-before-secret",
    )["attempts"] == []


def test_live_authority_is_rechecked_again_before_nonce_consumption(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "wire-boundary")
    _authorize_offline(store, "authority-drift-before-wire")
    calls = 0

    def drift_on_wire() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise FullShortExecutionBoundaryError("LIVE_AUTHORITY_DRIFT")

    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id="authority-drift-before-wire",
        policy=_policy(store), authorized_routes=_routes(),
        egress_policy=_egress(), live_authority_recheck=drift_on_wire,
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    observer.bind_model_request(protocol="anthropic", request=_request())

    with pytest.raises(FullShortExecutionBoundaryError) as drift:
        observer.before_http_dispatch(
            method="POST", url="https://unit.test/v1/messages",
            payload=_payload(),
        )

    assert drift.value.reason_code == "LIVE_AUTHORITY_DRIFT"
    assert calls == 2
    assert store._read(
        "authority-drift-before-wire", "nonce",
    )["state"] == "RESERVED"
    assert store.load_ledger("authority-drift-before-wire")["attempts"] == []


def test_exact_pre_dispatch_route_rebind_is_idempotent_but_drift_fails(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "pre-dispatch-route-rebind")
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id="pre-dispatch-route-rebind",
        policy=_policy(store), authorized_routes=_routes(),
        egress_policy=_egress(),
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    assert observer.pending_ordinal is None
    assert observer.expected_provider_payload is None

    with pytest.raises(FullShortExecutionBoundaryError) as drift:
        observer.bind_route(
            role="planning", lane="configured_fallback",
            provider_id="provider", model_id="model-id",
            route_fingerprint="9" * 64,
        )
    assert drift.value.reason_code == "ROUTE_BINDING_DRIFT"


@pytest.mark.asyncio
async def test_lowest_transport_seam_is_durable_and_completable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    permission, approval, nonce = _authorize_offline(store, "offline-full-short")
    observer = _observer(store, "offline-full-short")
    provider = HttpProvider(
        "https://unit.test", "offline-key",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
        attempt_observer=observer,
    )
    original = provider.client
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ok": True}, request=request),
    ))
    await original.aclose()

    assert await provider.post("v1/messages", payload={
        **_payload(),
    }, headers={}) == {"ok": True}
    response_hash = hashlib.sha256(b"offline-response").hexdigest()
    receipt_hash = hashlib.sha256(b"offline-receipt").hexdigest()
    observer.mark_local_stage_complete(
        stage="planning", role="planning",
        role_binding_sha256=observer.bound_route["role_binding_sha256"],
        output_sha256=response_hash,
        receipt_sha256=receipt_hash,
    )
    ledger = store.load_ledger("offline-full-short")
    assert ledger["attempts"][0]["state"] == "LOCAL_STAGE_COMPLETE"
    completion = build_full_short_completion_receipt_v1(
        execution_id="offline-full-short", policy=_policy(store),
        permission_sha256=permission["permission_sha256"],
        signed_approval_sha256=approval["signed_approval_sha256"],
        nonce_sha256=nonce["nonce_sha256"], ledger=ledger,
        final_bindings={
            "manuscript_sha256": "4" * 64,
            "chapter_sha256": "5" * 64,
            "canon_sha256": "6" * 64,
            "story_state_sha256": "7" * 64,
            "quality_checkpoint_sha256": "8" * 64,
            "terminal_verification_sha256": _terminal()[
                "verification_receipt_sha256"
            ],
        },
        terminal_verification=_terminal(),
    )
    assert completion["outcome"] == "FULL_SHORT_COMPLETED_EXACT"
    store.commit_completion(
        execution_id="offline-full-short", policy=_policy(store),
        receipt=completion,
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    with pytest.raises(FullShortExecutionBoundaryError) as replay:
        observer.bind_model_request(protocol="anthropic", request=_request())
    assert replay.value.reason_code == "LOGICAL_STAGE_PLAN_EXHAUSTED"
    await provider.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [422, 503])
async def test_complete_non_2xx_response_keeps_typed_http_close(
    tmp_path: Path, status_code: int,
) -> None:
    store = _store(tmp_path)
    execution_id = f"complete-non-2xx-{status_code}"
    _authorize_offline(store, execution_id)
    observer = _observer(store, execution_id)
    provider = HttpProvider(
        "https://unit.test", "offline-key",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
        attempt_observer=observer,
    )
    original = provider.client
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(
            status_code, json={"error": "terminal provider rejection"},
            request=request,
        ),
    ))
    await original.aclose()

    with pytest.raises(httpx.HTTPStatusError):
        await provider.post(
            "v1/messages", payload=_payload(), headers={},
        )

    attempt = store.load_ledger(execution_id)["attempts"][0]
    assert attempt["state"] == "HTTP_RESPONSE_FAILED_CLOSED"
    assert attempt["provider_protocol_capture_transport_complete"] is True
    assert attempt["provider_protocol_capture_http_success"] is False
    assert len(store.load_ledger(execution_id)["attempts"]) == 1
    await provider.client.aclose()


def test_partial_capture_remains_ambiguous_transport_failure(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    execution_id = "partial-capture-ambiguous"
    _authorize_offline(store, execution_id)
    observer = _observer(store, execution_id)
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=_payload(),
    )
    observer.capture_provider_protocol_input(
        data=b'data: {"type":"content_block_delta"}', status_code=200,
        content_type="text/event-stream", encoding="utf-8",
        transport_complete=False,
    )
    observer.after_http_failure(failure_kind="ReadTimeout")

    attempt = store.load_ledger(execution_id)["attempts"][0]
    assert attempt["provider_protocol_capture_transport_complete"] is False
    assert attempt["state"] == "OUTCOME_UNKNOWN_FAIL_CLOSED"


def test_capture_publication_crash_reconciles_exactly_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    execution_id = "capture-anchor-crash"
    _authorize_offline(store, execution_id)
    observer = _observer(store, execution_id)
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=_payload(),
    )
    events = [
        {"type": "message_start", "message": {
            "id": "offline", "usage": {"input_tokens": 1},
        }},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "reconciled"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 1}},
        {"type": "message_stop"},
    ]
    entity = "".join(
        "data: " + json.dumps(event, separators=(",", ":")) + "\n\n"
        for event in events
    ).encode("utf-8")
    with monkeypatch.context() as crash:
        crash.setattr(
            store, "update_ledger",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected ledger-anchor crash")
            ),
        )
        with pytest.raises(RuntimeError, match="ledger-anchor crash"):
            observer.capture_provider_protocol_input(
                data=entity, status_code=200,
                content_type="text/event-stream", encoding="utf-8",
                transport_complete=True,
            )

    assert store.load_ledger(execution_id)["attempts"][0][
        "provider_protocol_capture_receipt_sha256"
    ] is None
    reconciled = reconcile_full_short_capture_anchor_v1(
        store=store, execution_id=execution_id, ordinal=1,
    )
    assert reconciled["attempts"][0][
        "provider_protocol_capture_transport_complete"
    ] is True
    assert replay_full_short_provider_attempt_v1(
        store=store, execution_id=execution_id, ordinal=1,
    ).text == "reconciled"


def test_capture_reconciliation_rejects_tampered_published_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    execution_id = "capture-anchor-tamper"
    _authorize_offline(store, execution_id)
    observer = _observer(store, execution_id)
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=_payload(),
    )
    with monkeypatch.context() as crash:
        crash.setattr(
            store, "update_ledger",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("crash")),
        )
        with pytest.raises(RuntimeError, match="crash"):
            observer.capture_provider_protocol_input(
                data=b'{"ok":true}', status_code=200,
                content_type="application/json", encoding="utf-8",
                transport_complete=True,
            )
    capture_path = next(observer.capture_store.root.glob("*.capture"))
    payload = capture_path.read_bytes()
    capture_path.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))

    with pytest.raises(ProviderResponseCaptureError, match="SHA256_MISMATCH"):
        reconcile_full_short_capture_anchor_v1(
            store=store, execution_id=execution_id, ordinal=1,
        )
    assert store.load_ledger(execution_id)["attempts"][0][
        "provider_protocol_capture_receipt_sha256"
    ] is None


@pytest.mark.parametrize("protocol", ["openai-chat", "openai-responses"])
def test_capture_reconciliation_binds_openai_protocol_adapter_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, protocol: str,
) -> None:
    store = _store(tmp_path)
    execution_id = f"capture-anchor-{protocol}"
    path = (
        "chat/completions" if protocol == "openai-chat" else "responses"
    )
    route = ({
        **_routes()[0],
        "protocol": protocol,
        "destination": f"https://unit.test:443/v1/{path}",
    },)
    _authorize_offline(store, execution_id, routes=route)
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id=execution_id,
        policy=_policy(store, routes=route),
        authorized_routes=route, egress_policy=_egress(),
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    request = _request()
    observer.bind_model_request(protocol=protocol, request=request)
    payload = _expected_provider_payload_v1(
        protocol, request, destination=route[0]["destination"],
    )
    observer.before_http_dispatch(
        method="POST", url=route[0]["destination"], payload=payload,
    )
    with monkeypatch.context() as crash:
        crash.setattr(
            store, "update_ledger",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("crash")),
        )
        with pytest.raises(RuntimeError, match="crash"):
            observer.capture_provider_protocol_input(
                data=b'{"ok":true}', status_code=200,
                content_type="application/json", encoding="utf-8",
                transport_complete=True,
            )

    reconciled = reconcile_full_short_capture_anchor_v1(
        store=store, execution_id=execution_id, ordinal=1,
    )
    attempt = reconciled["attempts"][0]
    assert attempt["provider_protocol_capture_transport_complete"] is True
    assert len(attempt["provider_protocol_capture_receipt_sha256"]) == 64


@pytest.mark.asyncio
async def test_contract_runtime_terminal_exception_after_complete_capture_never_retries(
    tmp_path: Path,
) -> None:
    contract = StructuredArtifactContract(
        name="interview_planning", version=1,
        schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
            "additionalProperties": False,
        },
    )
    plan = _logical_stage_plan((
        "planning", "planning", contract.name, contract.version,
        contract.schema_sha256(), True, 128,
    ))
    store = _store(tmp_path)
    execution_id = "post-capture-terminal"
    _authorize_offline(store, execution_id, logical_stage_plan=plan)
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id=execution_id,
        policy=_policy(store, logical_stage_plan=plan),
        authorized_routes=_routes(), egress_policy=_egress(),
    )
    observer.bind_stage_context(
        stage_id="planning", contract_name=contract.name,
        contract_version=contract.version,
        contract_schema_sha256=contract.schema_sha256(),
        contract_runtime_input_required=True,
        contract_attempt_index=1, contract_route="primary",
        contract_route_attempt=1,
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    observer.bind_model_request(protocol="anthropic", request=_request())
    gateway = SimpleNamespace(
        registry=SimpleNamespace(attempt_observer=observer),
    )
    calls = 0

    async def terminal_adapter_failure(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        observer.before_http_dispatch(
            method="POST", url="https://unit.test/v1/messages",
            payload=_payload(),
        )
        observer.capture_provider_protocol_input(
            data=b'{"terminal":"provider-protocol-error"}', status_code=200,
            content_type="application/json", encoding="utf-8",
            transport_complete=True,
        )
        observer.after_http_response(status_code=200)
        raise RuntimeError("adapter terminal protocol exception")

    observations: list[dict] = []
    spec = ExecutableContractSpec(
        contract_name=contract.name, structured_contract=contract,
        semantic_normalizer=lambda value: value,
        domain_validator=lambda value: value,
    )
    with pytest.raises(RuntimeError, match="adapter terminal protocol exception"):
        await execute_contract_runtime(
            gateway, role="planning", system="", user="",
            execution_spec=spec,
            same_route_attempts=2, fallback_attempts=0,
            attempt_executor=terminal_adapter_failure,
            attempt_observer=observations.append,
        )

    assert calls == 1
    assert observations[0]["outcome"] == "post_capture_terminal_failure"
    assert observations[0]["outcome"] != "transport_failure"
    attempt = store.load_ledger(execution_id)["attempts"][0]
    assert attempt["state"] == "POST_CAPTURE_TERMINAL_FAILED_CLOSED"
    assert attempt["failure_class"] == "normal_invalid_output"


def test_restart_after_dispatch_before_local_receipt_never_redispatches(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "restart-blocked")
    first = _observer(store, "restart-blocked", session_id="session-one")
    first.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages",
        payload=_payload(),
    )
    first.after_http_response(status_code=200)

    with pytest.raises(FullShortExecutionBoundaryError) as caught:
        _observer(
            store, "restart-blocked", session_id="session-two",
        )
    assert caught.value.reason_code == "NONCE_ALREADY_CONSUMED_NO_RESTART"
    assert len(store.load_ledger("restart-blocked")["attempts"]) == 1


def test_restart_read_only_replay_uses_exact_ledger_anchored_capture(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "anchored-local-replay")
    observer = _observer(store, "anchored-local-replay")
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=_payload(),
    )
    events = [
        {"type": "message_start", "message": {
            "id": "offline", "usage": {"input_tokens": 2},
        }},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "exact local artifact"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 3}},
        {"type": "message_stop"},
    ]
    entity = "".join(
        "data: " + json.dumps(event, separators=(",", ":")) + "\n\n"
        for event in events
    ).encode("utf-8")
    observer.capture_provider_protocol_input(
        data=entity, status_code=200, content_type="text/event-stream",
        encoding="utf-8", transport_complete=True,
    )
    observer.after_http_response(status_code=200)

    replayed = replay_full_short_provider_attempt_v1(
        store=store, execution_id="anchored-local-replay", ordinal=1,
    )

    assert replayed.text == "exact local artifact"
    assert len(store.load_ledger("anchored-local-replay")["attempts"]) == 1


def test_restart_read_only_replay_fails_closed_without_ledger_anchor(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "unanchored-local-replay")
    observer = _observer(store, "unanchored-local-replay")
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=_payload(),
    )

    with pytest.raises(FullShortExecutionBoundaryError) as missing:
        replay_full_short_provider_attempt_v1(
            store=store, execution_id="unanchored-local-replay", ordinal=1,
        )

    assert missing.value.reason_code == "REPLAY_LEDGER_CAPTURE_RECEIPT_MISSING"


def test_closed_local_rejection_allows_only_same_session_bounded_recovery(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    permission, approval, nonce = _authorize_offline(
        store, "local-rejection-recovery",
    )
    observer = _observer(
        store, "local-rejection-recovery", session_id="one-session",
    )
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=_payload(),
    )
    observer.after_http_response(status_code=200)
    role_binding = observer.bound_route["role_binding_sha256"]
    observer.mark_local_attempt_rejected(
        stage="planning-semantic-v2", role="planning",
        role_binding_sha256=role_binding,
        rejection=_local_rejection(),
    )

    with pytest.raises(FullShortExecutionBoundaryError) as restarted:
        _observer(
            store, "local-rejection-recovery", session_id="new-session",
        )
    assert restarted.value.reason_code == "NONCE_ALREADY_CONSUMED_NO_RESTART"

    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    observer.bind_model_request(protocol="anthropic", request=_request())
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=_payload(),
    )
    observer.after_http_response(status_code=200)
    observer.mark_local_stage_complete(
        stage="planning", role="planning",
        role_binding_sha256=observer.bound_route["role_binding_sha256"],
        output_sha256="a" * 64, receipt_sha256="b" * 64,
    )

    ledger = store.load_ledger("local-rejection-recovery")
    assert [attempt["state"] for attempt in ledger["attempts"]] == [
        "LOCAL_ATTEMPT_REJECTED", "LOCAL_STAGE_COMPLETE",
    ]
    assert ledger["attempts"][0]["logical_stage_id"] == (
        ledger["attempts"][1]["logical_stage_id"]
    )
    assert ledger["attempts"][0]["logical_stage_base_id"] == "planning"
    assert len(ledger["completed_stage_receipts"]) == 1
    completion = build_full_short_completion_receipt_v1(
        execution_id="local-rejection-recovery", policy=_policy(store),
        permission_sha256=permission["permission_sha256"],
        signed_approval_sha256=approval["signed_approval_sha256"],
        nonce_sha256=nonce["nonce_sha256"], ledger=ledger,
        final_bindings={
            "manuscript_sha256": "4" * 64,
            "chapter_sha256": "5" * 64,
            "canon_sha256": "6" * 64,
            "story_state_sha256": "7" * 64,
            "quality_checkpoint_sha256": "8" * 64,
            "terminal_verification_sha256": _terminal()[
                "verification_receipt_sha256"
            ],
        },
        terminal_verification=_terminal(),
    )
    assert completion["provider_request_count"] == 2
    assert completion["completed_stage_count"] == 1
    store.commit_completion(
        execution_id="local-rejection-recovery", policy=_policy(store),
        receipt=completion,
    )


def test_two_rejections_exhaust_shared_logical_stage_physical_ceiling(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "two-slot-recovery-ceiling")
    observer = _observer(
        store, "two-slot-recovery-ceiling", session_id="one-session",
    )

    for route_attempt in (1, 2):
        observer.before_http_dispatch(
            method="POST", url="https://unit.test/v1/messages",
            payload=_payload(),
        )
        observer.after_http_response(status_code=200)
        observer.mark_local_attempt_rejected(
            stage="planning-semantic-v2", role="planning",
            role_binding_sha256=observer.bound_route[
                "role_binding_sha256"
            ],
            rejection=_local_rejection(route_attempt=route_attempt),
        )
        if route_attempt == 1:
            observer.bind_route(
                role="planning", lane="primary", provider_id="provider",
                model_id="model-id", route_fingerprint="9" * 64,
            )
            observer.bind_model_request(
                protocol="anthropic", request=_request(),
            )

    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    observer.bind_model_request(protocol="anthropic", request=_request())
    with pytest.raises(FullShortExecutionBoundaryError) as rejected:
        observer.before_http_dispatch(
            method="POST", url="https://unit.test/v1/messages",
            payload=_payload(),
        )
    assert rejected.value.reason_code == (
        "LOGICAL_STAGE_REDISPATCH_NOT_AUTHORIZED"
    )
    ledger = store.load_ledger("two-slot-recovery-ceiling")
    assert len(ledger["attempts"]) == 2
    assert len({
        item["physical_attempt_id"] for item in ledger["attempts"]
    }) == 2


def test_pre_contract_final_artifact_rejection_closes_captured_response(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "pre-contract-final-artifact")
    observer = _observer(store, "pre-contract-final-artifact")
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=_payload(),
    )
    observer.capture_provider_protocol_input(
        data=b"event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n",
        status_code=200,
        content_type="text/event-stream; charset=utf-8",
        encoding="utf-8",
        transport_complete=True,
    )
    observer.after_http_response(status_code=200)
    observer.mark_local_attempt_rejected(
        stage="planning-semantic-v2", role="planning",
        role_binding_sha256=observer.bound_route["role_binding_sha256"],
        rejection={
            "schema": "ProviderFinalArtifactRejectionReceiptV1",
            "version": 1,
            "contract_name": "planning_semantic_v2",
            "contract_version": 2,
            "contract_schema_sha256": "a" * 64,
            "attempt_index": 1,
            "route": "primary",
            "route_attempt": 1,
            "failure_kind": "final_artifact_unavailable",
            "failure_code": "reasoning_only_final_artifact_unavailable",
            "failure_reason_sha256": "b" * 64,
            "provider_output_shape_sha256": "c" * 64,
            "contract_runtime_input_present": False,
            "raw_content_persisted": False,
        },
    )

    ledger = store.load_ledger("pre-contract-final-artifact")
    attempt = ledger["attempts"][0]
    assert ledger["state"] == "READY_FOR_RECOVERY_ATTEMPT"
    assert attempt["state"] == "LOCAL_ATTEMPT_REJECTED"
    assert attempt["local_rejection_schema"] == (
        "ProviderFinalArtifactRejectionReceiptV1"
    )
    assert attempt["local_rejection_failure_code"] == (
        "reasoning_only_final_artifact_unavailable"
    )
    assert attempt["contract_runtime_capture_receipt_sha256"] is None


def test_reasoning_only_rejection_requires_exact_recovery_stage_role(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "typed-recovery-stage-role")
    observer = _observer(store, "typed-recovery-stage-role")
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=_payload(),
    )
    observer.capture_provider_protocol_input(
        data=b"reasoning-only", status_code=200,
        content_type="application/json", encoding="utf-8",
        transport_complete=True,
    )
    observer.after_http_response(status_code=200)
    observer.mark_local_attempt_rejected(
        stage="planning", role="planning",
        role_binding_sha256=observer.bound_route["role_binding_sha256"],
        rejection=_final_artifact_rejection(),
    )
    observer.bind_stage_context(
        stage_id="planning", contract_name="unstructured_text",
        contract_version=1, contract_schema_sha256=_hash({}),
        stage_role="NORMAL",
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    observer.bind_model_request(protocol="anthropic", request=_request())
    with pytest.raises(FullShortExecutionBoundaryError) as rejected:
        observer.before_http_dispatch(
            method="POST", url="https://unit.test/v1/messages",
            payload=_payload(),
        )
    assert rejected.value.reason_code == (
        "REASONING_ONLY_RECOVERY_STAGE_ROLE_REQUIRED"
    )
    assert len(store.load_ledger("typed-recovery-stage-role")["attempts"]) == 1


@pytest.mark.parametrize("tamper", ["accepted_id", "rejected_provenance"])
def test_completion_recomputes_recovery_acceptance_provenance(
    tmp_path: Path, tamper: str,
) -> None:
    store = _store(tmp_path)
    execution_id = f"completion-provenance-{tamper}"
    permission, approval, nonce = _authorize_offline(store, execution_id)
    _dispatch_reasoning_recovery_and_close(store, execution_id)

    def mutate(body):
        receipt = body["completed_stage_receipts"][0]
        if tamper == "accepted_id":
            receipt["accepted_physical_attempt_id"] = "physical-forged"
        else:
            receipt["rejected_attempt_provenance"] = []
        return body

    store.update_ledger(execution_id, mutate)
    ledger = store.load_ledger(execution_id)
    terminal = _terminal()
    with pytest.raises(FullShortExecutionBoundaryError) as rejected:
        build_full_short_completion_receipt_v1(
            execution_id=execution_id, policy=_policy(store),
            permission_sha256=permission["permission_sha256"],
            signed_approval_sha256=approval["signed_approval_sha256"],
            nonce_sha256=nonce["nonce_sha256"], ledger=ledger,
            final_bindings={
                "manuscript_sha256": "4" * 64,
                "chapter_sha256": "5" * 64,
                "canon_sha256": "6" * 64,
                "story_state_sha256": "7" * 64,
                "quality_checkpoint_sha256": "8" * 64,
                "terminal_verification_sha256": terminal[
                    "verification_receipt_sha256"
                ],
            },
            terminal_verification=terminal,
        )
    assert rejected.value.reason_code == (
        "STAGE_ACCEPTANCE_PROVENANCE_MISMATCH"
    )


def test_local_rejection_receipt_rejects_raw_content_and_stays_pending(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "local-rejection-privacy")
    observer = _observer(store, "local-rejection-privacy")
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=_payload(),
    )
    observer.after_http_response(status_code=200)
    rejection = {
        **_local_rejection(),
        "raw_provider_content": "must never be persisted",
    }
    with pytest.raises(FullShortExecutionBoundaryError) as invalid:
        observer.mark_local_attempt_rejected(
            stage="planning", role="planning",
            role_binding_sha256=observer.bound_route[
                "role_binding_sha256"
            ],
            rejection=rejection,
        )
    assert invalid.value.reason_code == "LOCAL_REJECTION_RECEIPT_SHAPE_INVALID"
    ledger = store.load_ledger("local-rejection-privacy")
    assert ledger["state"] == "RESPONSE_RECEIVED_AWAITING_LOCAL_RECEIPT"
    assert "raw_provider_content" not in json.dumps(ledger)


def test_local_rejection_normalizes_only_configured_fallback_lane(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    routes = (_routes()[0], {
        **_routes()[0],
        "lane": "fallback",
        "provider_id_sha256": hashlib.sha256(b"fallback-provider").hexdigest(),
        "model_id_sha256": hashlib.sha256(b"fallback-model-id").hexdigest(),
        "model_name": "offline-fallback",
        "route_fingerprint": "8" * 64,
    })
    policy = _policy(store, routes=routes)
    permission = store.create_permission(
        execution_id="fallback-local-rejection",
        authorization_text_sha256="3" * 64,
        policy=policy, external_actions_enabled=False,
    )
    approval = store.create_jit_approval(
        execution_id="fallback-local-rejection", policy=policy,
        permission=permission, external_actions_enabled=False,
    )
    store.reserve_nonce(
        execution_id="fallback-local-rejection", policy=policy,
        approval=approval, external_actions_enabled=False,
    )
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id="fallback-local-rejection", policy=policy,
        authorized_routes=routes, egress_policy=_egress(),
    )
    observer.bind_route(
        role="planning", lane="fallback", provider_id="fallback-provider",
        model_id="fallback-model-id", route_fingerprint="8" * 64,
    )
    request = ModelRequest(
        model="offline-fallback", messages=[], max_output_tokens=128,
    )
    payload = {
        "model": "offline-fallback", "messages": [], "max_tokens": 128,
        "stream": True,
    }
    observer.bind_model_request(protocol="anthropic", request=request)
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=payload,
    )
    observer.after_http_response(status_code=200)
    observer.mark_local_attempt_rejected(
        stage="planning", role="planning",
        role_binding_sha256=observer.bound_route["role_binding_sha256"],
        rejection={
            **_local_rejection(),
            "route": "configured_fallback",
        },
    )
    assert store.load_ledger("fallback-local-rejection")["attempts"][0][
        "state"
    ] == "LOCAL_ATTEMPT_REJECTED"


def test_restart_before_dispatch_is_also_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "restart-before-dispatch")
    _observer(store, "restart-before-dispatch", session_id="first-process")
    with pytest.raises(FullShortExecutionBoundaryError) as restarted:
        _observer(store, "restart-before-dispatch", session_id="new-process")
    assert restarted.value.reason_code == "OBSERVER_ALREADY_CLAIMED_NO_RESTART"
    assert store._read("restart-before-dispatch", "nonce")["state"] == "RESERVED"


def test_nonce_and_approval_are_exclusive_and_destination_is_exact(tmp_path: Path) -> None:
    store = _store(tmp_path)
    permission, _approval, _nonce = _authorize_offline(store, "single-use")
    with pytest.raises(FullShortExecutionBoundaryError) as caught:
        store.create_jit_approval(
            execution_id="single-use", policy=_policy(store),
            permission=permission, external_actions_enabled=False,
        )
    assert caught.value.reason_code == "SINGLE_USE_REPLAY"

    observer = _observer(store, "single-use")
    with pytest.raises(FullShortExecutionBoundaryError) as destination:
        observer.before_http_dispatch(
            method="POST", url="https://other.test/v1/messages",
            payload=_payload(),
        )
    assert destination.value.reason_code == "DESTINATION_DRIFT"
    assert store.load_ledger("single-use")["attempts"] == []


@pytest.mark.parametrize("mutation", [
    {"credentials": "secret"},
    {"unrelated_project_data": "foreign"},
    {"raw_provider_evidence": "raw"},
    {"retired_skill_v3_hybrid_context": "retired"},
    {"unexpected_extension": True},
])
def test_egress_payload_drift_is_rejected_before_nonce_or_dispatch(
    tmp_path: Path, mutation: dict,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "egress-drift")
    observer = _observer(store, "egress-drift")
    payload = {**_payload(), **mutation}

    with pytest.raises(FullShortExecutionBoundaryError) as caught:
        observer.before_http_dispatch(
            method="POST", url="https://unit.test/v1/messages",
            payload=payload,
        )

    assert caught.value.reason_code == "EGRESS_PAYLOAD_SCHEMA_OR_CONTENT_DRIFT"
    assert store._read("egress-drift", "nonce")["state"] == "RESERVED"
    assert store.load_ledger("egress-drift")["attempts"] == []


def test_egress_model_request_content_is_exactly_bound(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "egress-content")
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id="egress-content", policy=_policy(store),
        authorized_routes=_routes(), egress_policy=_egress(),
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    request = ModelRequest(
        model="offline", messages=[Message(role="user", content="authorized")],
        max_output_tokens=128,
    )
    observer.bind_model_request(protocol="anthropic", request=request)

    with pytest.raises(FullShortExecutionBoundaryError) as caught:
        observer.before_http_dispatch(
            method="POST", url="https://unit.test/v1/messages",
            payload={
                "model": "offline",
                "messages": [{"role": "user", "content": "changed"}],
                "max_tokens": 128,
                "stream": True,
            },
        )

    assert caught.value.reason_code == "EGRESS_PAYLOAD_SCHEMA_OR_CONTENT_DRIFT"
    assert store._read("egress-content", "nonce")["state"] == "RESERVED"
    assert store.load_ledger("egress-content")["attempts"] == []


@pytest.mark.parametrize(("protocol", "token_key", "content_key"), [
    ("anthropic", "max_tokens", "messages"),
    ("openai-chat", "max_tokens", "messages"),
    ("openai-responses", "max_output_tokens", "input"),
])
def test_closed_egress_projection_covers_each_provider_protocol(
    protocol: str, token_key: str, content_key: str,
) -> None:
    request = ModelRequest(
        model="offline",
        messages=[Message(role="user", content="authorized")],
        max_output_tokens=128,
    )
    payload = _expected_provider_payload_v1(
        protocol, request, destination="https://unit.test:443/v1/messages",
    )

    assert payload["model"] == "offline"
    assert payload[token_key] == 128
    assert payload[content_key] == [{"role": "user", "content": "authorized"}]
    assert payload["stream"] is True


def test_egress_intent_persists_only_hashes_not_raw_content(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "egress-private")
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id="egress-private", policy=_policy(store),
        authorized_routes=_routes(), egress_policy=_egress(),
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    sentinel = "RAW-STORY-SENTINEL-MUST-NOT-PERSIST"
    request = ModelRequest(
        model="offline", messages=[Message(role="user", content=sentinel)],
        max_output_tokens=128,
    )
    observer.bind_model_request(protocol="anthropic", request=request)
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages",
        payload={
            "model": "offline",
            "messages": [{"role": "user", "content": sentinel}],
            "max_tokens": 128,
            "stream": True,
        },
    )

    persisted = b"\n".join(
        path.read_bytes() for path in store.root.rglob("*")
        if path.is_file()
    )
    assert sentinel.encode("utf-8") not in persisted
    attempt = store.load_ledger("egress-private")["attempts"][0]
    assert len(attempt["egress_intent_sha256"]) == 64
    assert len(attempt["provider_payload_sha256"]) == 64


@pytest.mark.asyncio
async def test_credential_reflection_is_rejected_before_attempt_accounting(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "credential-reflection")
    observer = _observer(store, "credential-reflection")
    provider = HttpProvider(
        "https://unit.test", "offline-key",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
        attempt_observer=observer,
    )
    original = provider.client
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: pytest.fail("transport must not be reached"),
    ))
    await original.aclose()

    for reflected in (
        "offline-key",
        "prefix offline-key suffix",
        {"nested": ["prefix-offline-key-suffix"]},
    ):
        with pytest.raises(
            SingleDispatchTransportGuardError,
            match="credential_reflection_rejected",
        ):
            await provider.post(
                "v1/messages",
                payload={**_payload(), "unexpected_extension": reflected},
                headers={},
            )

    assert provider.transport_attempt_snapshot()["http_post_attempts"] == 0
    assert store._read("credential-reflection", "nonce")["state"] == "RESERVED"
    assert store.load_ledger("credential-reflection")["attempts"] == []
    await provider.client.aclose()


def test_pre_dispatch_store_never_accepts_worktree_location(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(FullShortExecutionBoundaryError) as caught:
        FullShortDurableExecutionStoreV1(
            repo_root=repo, store_root=repo / "forbidden",
        )
    assert caught.value.reason_code == "STORE_INSIDE_GIT_WORKTREE"


def test_policy_is_bound_to_exact_store_root(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(FullShortExecutionBoundaryError) as caught:
        store.create_permission(
            execution_id="wrong-store", authorization_text_sha256="3" * 64,
            policy=_policy(), external_actions_enabled=False,
        )
    assert caught.value.reason_code == "STORE_ROOT_POLICY_MISMATCH"


def _preflight_actual() -> dict:
    policy = _policy()
    return {
        "head": policy["execution_head"],
        "branch": policy["branch"],
        "run_id": policy["run_id"],
        "worktree_clean": True,
        "project_id_sha256": policy["project_id_sha256"],
        "workload_sha256": policy["workload_sha256"],
        "runtime_authority_sha256": policy["runtime_authority_sha256"],
        "style_reference_authority_sha256": policy[
            "style_reference_authority_sha256"
        ],
        "route_manifest_sha256": policy["route_manifest_sha256"],
        "destination_manifest_sha256": policy["destination_manifest_sha256"],
        "egress_policy_sha256": policy["egress_policy_sha256"],
        "response_capture_policy_sha256": (
            policy["response_capture_policy_sha256"]
        ),
        "logical_stage_plan_sha256": policy["logical_stage_plan_sha256"],
        "transport_recovery_policy_sha256": policy[
            "transport_recovery_policy_sha256"
        ],
        "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
        "logical_stage_recovery_policy_sha256": policy[
            "logical_stage_recovery_policy_sha256"
        ],
        "logical_stage_recovery_policy_identity": (
            "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY"
        ),
        "store_root_sha256": policy["store_root_sha256"],
        "skill_v3_production_cutover": False,
        "planning_v2_production_cutover": False,
        "external_action_counters": {
            "credential_lookup": 0, "provider_client_creation": 0,
            "provider_request": 0, "http_post": 0, "network": 0,
            "model": 0, "paid": 0,
        },
    }


def test_canonical_authorization_and_disabled_preflight_are_exact() -> None:
    policy = _policy()
    bindings = {
        "project_workload": "hash-bound-test",
        "routes": list(_routes()),
        "destinations": ["https://unit.test:443/v1/messages"],
        "egress_policy": _egress(),
        "response_capture_policy": RESPONSE_CAPTURE_POLICY_V1,
        "logical_stage_plan": policy["logical_stage_plan"],
        "logical_stage_plan_sha256": policy["logical_stage_plan_sha256"],
        "transport_recovery_policy": TRANSPORT_RECOVERY_POLICY_V1,
        "transport_recovery_policy_sha256": (
            TRANSPORT_RECOVERY_POLICY_SHA256
        ),
        "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
        "logical_stage_recovery_policy": LOGICAL_STAGE_RECOVERY_POLICY_V1,
        "logical_stage_recovery_policy_sha256": (
            LOGICAL_STAGE_RECOVERY_POLICY_SHA256
        ),
        "logical_stage_recovery_policy_identity": (
            "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY"
        ),
        "store_root_sha256": "0" * 64,
    }
    raw = render_full_short_canonical_authorization_v1(
        policy=policy, public_bindings=bindings,
    )
    authorization = validate_full_short_canonical_authorization_v1(
        raw, policy=policy, public_bindings=bindings,
    )
    receipt = validate_full_short_preflight_v1(
        policy=policy, actual=_preflight_actual(),
        authorization_text_sha256=authorization["authorization_text_sha256"],
        external_actions_enabled=False,
    )
    assert receipt["binding_status"] == "exact"
    assert receipt["approval_state"] == "NOT_CREATED"
    assert receipt["nonce_state"] == "NOT_CREATED"
    assert receipt["logical_stage_plan_sha256"] == policy[
        "logical_stage_plan_sha256"
    ]
    assert receipt["transport_recovery_policy_identity"] == "EXACT_REPLAY_ONLY"


def test_policy_binds_canonical_exact_replay_matrix_and_old_packets_fail() -> None:
    policy = _policy()
    assert policy["transport_recovery_policy"] == TRANSPORT_RECOVERY_POLICY_V1
    assert [item["outcome_class"] for item in policy[
        "transport_recovery_policy"
    ]["ordered_outcome_matrix"]] == [
        "complete_valid", "explicit_provider_error",
        "proven_pre_response", "ambiguous",
    ]
    assert policy["transport_recovery_policy"]["max_network_retries"] == 0
    assert policy["transport_recovery_policy"]["fresh_nonce_allowed"] is False
    assert policy["transport_recovery_policy"][
        "network_redispatch_allowed"
    ] is False
    matrix = policy["transport_recovery_policy"]["ordered_outcome_matrix"]
    assert [
        {
            key: item[key] for key in (
                "response_bytes_present", "valid_completion",
                "explicit_error", "ambiguity", "max_retry",
                "fresh_nonce", "budget_counted",
            )
        }
        for item in matrix
    ] == [
        {
            "response_bytes_present": True, "valid_completion": True,
            "explicit_error": False, "ambiguity": False,
            "max_retry": 0, "fresh_nonce": False, "budget_counted": True,
        },
        {
            "response_bytes_present": True, "valid_completion": False,
            "explicit_error": True, "ambiguity": False,
            "max_retry": 0, "fresh_nonce": False, "budget_counted": True,
        },
        {
            "response_bytes_present": False, "valid_completion": False,
            "explicit_error": False, "ambiguity": False,
            "max_retry": 0, "fresh_nonce": False, "budget_counted": True,
        },
        {
            "response_bytes_present": False, "valid_completion": False,
            "explicit_error": False, "ambiguity": True,
            "max_retry": 0, "fresh_nonce": False, "budget_counted": True,
        },
    ]

    old_packet = dict(policy)
    old_packet.pop("policy_sha256")
    old_packet.pop("logical_stage_plan")
    old_packet.pop("logical_stage_plan_sha256")
    old_packet["policy_version"] = "full-short-trustworthy-execution-v1"
    with pytest.raises(FullShortExecutionBoundaryError) as rejected:
        validate_policy_v1(old_packet)
    assert rejected.value.reason_code == "POLICY_VERSION_MISMATCH"


def test_authorization_candidate_rejects_same_count_role_plan_reordering() -> None:
    plan = _logical_stage_plan(
        ("planning", "planning", "planning_text", 1,
         "1" * 64, False, 128),
        ("draft", "planning", "draft_text", 1,
         "2" * 64, False, 128),
    )
    policy = _policy(expected_stage_calls=2, logical_stage_plan=plan)
    bindings = {
        "routes": list(_routes()),
        "destinations": ["https://unit.test:443/v1/messages"],
        "egress_policy": _egress(),
        "response_capture_policy": RESPONSE_CAPTURE_POLICY_V1,
        "logical_stage_plan": list(reversed(policy["logical_stage_plan"])),
        "logical_stage_plan_sha256": policy["logical_stage_plan_sha256"],
        "transport_recovery_policy": TRANSPORT_RECOVERY_POLICY_V1,
        "transport_recovery_policy_sha256": TRANSPORT_RECOVERY_POLICY_SHA256,
        "transport_recovery_policy_identity": "EXACT_REPLAY_ONLY",
        "logical_stage_recovery_policy": LOGICAL_STAGE_RECOVERY_POLICY_V1,
        "logical_stage_recovery_policy_sha256": (
            LOGICAL_STAGE_RECOVERY_POLICY_SHA256
        ),
        "logical_stage_recovery_policy_identity": (
            "TWO_SLOT_MUTUALLY_EXCLUSIVE_TYPED_RECOVERY"
        ),
        "store_root_sha256": "0" * 64,
    }
    with pytest.raises(FullShortExecutionBoundaryError) as rejected:
        render_full_short_canonical_authorization_v1(
            policy=policy, public_bindings=bindings,
        )
    assert rejected.value.reason_code == (
        "AUTHORIZATION_LOGICAL_STAGE_PLAN_MISMATCH"
    )


def test_signed_chain_and_stage_dispatch_bind_exact_plan_and_recovery(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    permission, approval, nonce = _authorize_offline(store, "exact-plan-chain")
    policy = _policy(store)
    for value in (permission, approval, nonce, store.load_ledger(
        "exact-plan-chain"
    )):
        assert value["logical_stage_plan_sha256"] == policy[
            "logical_stage_plan_sha256"
        ]
        assert value["transport_recovery_policy_sha256"] == (
            TRANSPORT_RECOVERY_POLICY_SHA256
        )
        assert value["transport_recovery_policy_identity"] == (
            "EXACT_REPLAY_ONLY"
        )

    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id="exact-plan-chain", policy=policy,
        authorized_routes=_routes(), egress_policy=_egress(),
    )
    with pytest.raises(FullShortExecutionBoundaryError) as rejected:
        observer.bind_stage_context(
            stage_id="draft", contract_name="unstructured_text",
            contract_version=1, contract_schema_sha256=_hash({}),
        )
    assert rejected.value.reason_code == "LOGICAL_STAGE_PLAN_CONTEXT_DRIFT"
    assert store.load_ledger("exact-plan-chain")["attempts"] == []


def test_post_authorization_head_drift_fails_before_external_actions() -> None:
    actual = _preflight_actual()
    actual["head"] = "9" * 40
    with pytest.raises(FullShortExecutionBoundaryError) as caught:
        validate_full_short_preflight_v1(
            policy=_policy(), actual=actual,
            authorization_text_sha256="8" * 64,
            external_actions_enabled=False,
        )
    assert caught.value.reason_code == "HEAD_DRIFT"


def test_invalid_public_route_identity_never_crosses_credential_boundary(
    tmp_path: Path,
) -> None:
    class CountingSecrets:
        lookups = 0

        def get(self, _provider_id: str) -> str | None:
            self.lookups += 1
            return "must-not-be-read"

        def set(self, _provider_id: str, _value: str) -> None:
            raise AssertionError

        def delete(self, _provider_id: str) -> None:
            raise AssertionError

    db = Database(tmp_path / "app.db")
    db.migrate()
    secrets = CountingSecrets()
    registry = ProviderRegistry(db, secrets)
    with pytest.raises(ValueError, match="provider_not_found"):
        registry.resolve("missing-provider", "missing-model")
    assert secrets.lookups == 0


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("worktree_clean", False, "WORKTREE_DRIFT"),
        ("run_id", "other-run", "RUN_ID_DRIFT"),
        ("project_id_sha256", "9" * 64, "PROJECT_ID_SHA256_DRIFT"),
        ("workload_sha256", "9" * 64, "WORKLOAD_SHA256_DRIFT"),
        ("runtime_authority_sha256", "9" * 64, "RUNTIME_AUTHORITY_SHA256_DRIFT"),
        ("style_reference_authority_sha256", "9" * 64,
         "STYLE_REFERENCE_AUTHORITY_SHA256_DRIFT"),
        ("route_manifest_sha256", "9" * 64, "ROUTE_MANIFEST_SHA256_DRIFT"),
        ("destination_manifest_sha256", "9" * 64,
         "DESTINATION_MANIFEST_SHA256_DRIFT"),
        ("egress_policy_sha256", "9" * 64, "EGRESS_POLICY_SHA256_DRIFT"),
        ("response_capture_policy_sha256", "9" * 64,
         "RESPONSE_CAPTURE_POLICY_SHA256_DRIFT"),
        ("logical_stage_plan_sha256", "9" * 64,
         "LOGICAL_STAGE_PLAN_SHA256_DRIFT"),
        ("transport_recovery_policy_sha256", "9" * 64,
         "TRANSPORT_RECOVERY_POLICY_SHA256_DRIFT"),
        ("transport_recovery_policy_identity", "NETWORK_RETRY",
         "TRANSPORT_RECOVERY_POLICY_IDENTITY_DRIFT"),
        ("store_root_sha256", "9" * 64, "STORE_ROOT_SHA256_DRIFT"),
        ("skill_v3_production_cutover", True, "SKILL_V3_CUTOVER_DRIFT"),
        ("planning_v2_production_cutover", True, "PLANNING_V2_CUTOVER_DRIFT"),
    ],
)
def test_every_immutable_preflight_drift_fails_closed(
    field: str, value: object, reason: str,
) -> None:
    actual = _preflight_actual()
    actual[field] = value
    with pytest.raises(FullShortExecutionBoundaryError) as caught:
        validate_full_short_preflight_v1(
            policy=_policy(), actual=actual,
            authorization_text_sha256="8" * 64,
            external_actions_enabled=False,
        )
    assert caught.value.reason_code == reason


def test_restart_after_completed_stage_is_explicitly_fail_closed(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "completed-stage-restart")
    first = _observer(store, "completed-stage-restart", session_id="session-one")
    first.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages",
        payload=_payload(),
    )
    first.after_http_response(status_code=200)
    first.mark_local_stage_complete(
        stage="planning", role="planning",
        role_binding_sha256=first.bound_route["role_binding_sha256"],
        output_sha256="a" * 64,
        receipt_sha256="b" * 64,
    )
    with pytest.raises(FullShortExecutionBoundaryError) as caught:
        _observer(store, "completed-stage-restart", session_id="session-two")
    assert caught.value.reason_code == "NONCE_ALREADY_CONSUMED_NO_RESTART"
    ledger = store.load_ledger("completed-stage-restart")
    assert [item["ordinal"] for item in ledger["attempts"]] == [1]


def test_external_action_counter_at_preflight_is_terminal() -> None:
    actual = _preflight_actual()
    actual["external_action_counters"]["credential_lookup"] = 1
    with pytest.raises(FullShortExecutionBoundaryError) as caught:
        validate_full_short_preflight_v1(
            policy=_policy(), actual=actual,
            authorization_text_sha256="8" * 64,
            external_actions_enabled=False,
        )
    assert caught.value.reason_code == "PREFLIGHT_EXTERNAL_ACTION_OCCURRED"


def test_durable_chain_tamper_and_external_authority_mismatch_fail_closed(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "chain-exact")
    with pytest.raises(FullShortExecutionBoundaryError) as mismatch:
        FullShortDispatchLedgerObserverV1(
            store=store, execution_id="chain-exact", policy=_policy(store),
            authorized_routes=_routes(), egress_policy=_egress(),
            external_actions_enabled=True,
        )
    assert mismatch.value.reason_code == "EXTERNAL_ACTION_AUTHORITY_MISMATCH"

    approval_path = store._path("chain-exact", "approval")
    approval_path.write_bytes(approval_path.read_bytes().replace(
        b'"state":"SIGNED"', b'"state":"BROKEN"',
    ))
    with pytest.raises(FullShortExecutionBoundaryError) as tampered:
        FullShortDispatchLedgerObserverV1(
            store=store, execution_id="chain-exact", policy=_policy(store),
            authorized_routes=_routes(), egress_policy=_egress(),
        )
    assert tampered.value.reason_code == "APPROVAL_SHA256_MISMATCH"


def test_total_requested_output_cap_is_enforced_before_second_dispatch(
    tmp_path: Path,
) -> None:
    with pytest.raises(FullShortExecutionBoundaryError) as capped:
        _policy(
            _store(tmp_path), expected_stage_calls=2,
            logical_stage_plan=_logical_stage_plan(
                ("planning", "planning", "unstructured_text", 1,
                 _hash({}), False, 3000),
                ("planning", "planning", "unstructured_text", 1,
                 _hash({}), False, 2000),
            ),
        )
    assert capped.value.reason_code == "LOGICAL_STAGE_PLAN_CAPS_MISMATCH"


def test_nonce_is_consumed_before_first_dispatch_and_duplicate_is_blocked(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "nonce-consumed")
    observer = _observer(store, "nonce-consumed")
    assert store._read("nonce-consumed", "nonce")["state"] == "RESERVED"

    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages",
        payload=_payload(),
    )

    nonce = store._read("nonce-consumed", "nonce")
    assert nonce["state"] == "CONSUMED"
    assert nonce["dispatch_attempt_count"] == 1
    with pytest.raises(FullShortExecutionBoundaryError) as duplicate:
        observer.before_http_dispatch(
            method="POST", url="https://unit.test/v1/messages",
            payload=_payload(),
        )
    assert duplicate.value.reason_code == "AMBIGUOUS_OR_UNCLOSED_DISPATCH_NO_RESTART"
    assert len(store.load_ledger("nonce-consumed")["attempts"]) == 1


def test_route_and_egress_drift_fail_before_nonce_consumption(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "route-drift")
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id="route-drift", policy=_policy(store),
        authorized_routes=_routes(), egress_policy=_egress(),
    )
    with pytest.raises(FullShortExecutionBoundaryError) as route:
        observer.bind_route(
            role="planning", lane="primary", provider_id="other-provider",
            model_id="model-id", route_fingerprint="9" * 64,
        )
    assert route.value.reason_code == "ROUTE_BINDING_DRIFT"
    assert store._read("route-drift", "nonce")["state"] == "RESERVED"

    with pytest.raises(FullShortExecutionBoundaryError) as egress:
        FullShortDispatchLedgerObserverV1(
            store=store, execution_id="route-drift", policy=_policy(store),
            authorized_routes=_routes(), egress_policy={"allowed": ["secret"]},
        )
    assert egress.value.reason_code == "EGRESS_POLICY_DRIFT"


def test_only_success_response_can_close_and_success_cannot_be_rewritten(
    tmp_path: Path,
) -> None:
    failed_store = _store(tmp_path / "failed")
    _authorize_offline(failed_store, "http-failed")
    failed = _observer(failed_store, "http-failed")
    failed.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages",
        payload=_payload(),
    )
    with pytest.raises(FullShortExecutionBoundaryError) as status:
        failed.after_http_response(status_code=500)
    assert status.value.reason_code == "HTTP_RESPONSE_NOT_SUCCESSFUL"
    with pytest.raises(FullShortExecutionBoundaryError) as close:
        failed.mark_local_stage_complete(
            stage="planning", role="planning",
            role_binding_sha256=failed.bound_route["role_binding_sha256"],
            output_sha256="a" * 64, receipt_sha256="b" * 64,
        )
    assert close.value.reason_code == "RESPONSE_NOT_RECEIVED"

    success_store = _store(tmp_path / "success")
    _authorize_offline(success_store, "http-success")
    success = _observer(success_store, "http-success")
    success.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages",
        payload=_payload(),
    )
    success.after_http_response(status_code=200)
    with pytest.raises(FullShortExecutionBoundaryError) as rewrite:
        success.after_http_failure(failure_kind="late-error")
    assert rewrite.value.reason_code == (
        "SUCCESSFUL_RESPONSE_CANNOT_BE_REWRITTEN_AS_FAILURE"
    )
    assert success_store.load_ledger("http-success")["attempts"][0]["state"] == (
        "RESPONSE_RECEIVED"
    )


def test_completion_rejects_terminal_false_positive_and_binding_key_drift(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    permission, approval, nonce = _authorize_offline(store, "terminal-false")
    _dispatch_and_close(store, "terminal-false")
    ledger = store.load_ledger("terminal-false")
    terminal = _terminal()
    terminal_body = dict(terminal)
    terminal_body.pop("verification_receipt_sha256")
    terminal_body["workflow_final_status"] = "failed"
    false_terminal = {**terminal_body, "verification_receipt_sha256": domain_sha256(
        "novel-flywheel-short-completion-verification-v1", terminal_body,
    )}
    bindings = {
        "manuscript_sha256": "4" * 64, "chapter_sha256": "5" * 64,
        "canon_sha256": "6" * 64, "story_state_sha256": "7" * 64,
        "quality_checkpoint_sha256": "8" * 64,
        "terminal_verification_sha256": false_terminal[
            "verification_receipt_sha256"
        ],
    }
    with pytest.raises(FullShortExecutionBoundaryError) as false_positive:
        build_full_short_completion_receipt_v1(
            execution_id="terminal-false", policy=_policy(store),
            permission_sha256=permission["permission_sha256"],
            signed_approval_sha256=approval["signed_approval_sha256"],
            nonce_sha256=nonce["nonce_sha256"], ledger=ledger,
            final_bindings=bindings, terminal_verification=false_terminal,
        )
    assert false_positive.value.reason_code == "TERMINAL_VERIFICATION_NOT_SUCCESSFUL"

    bindings.pop("canon_sha256")
    with pytest.raises(FullShortExecutionBoundaryError) as keys:
        build_full_short_completion_receipt_v1(
            execution_id="terminal-false", policy=_policy(store),
            permission_sha256=permission["permission_sha256"],
            signed_approval_sha256=approval["signed_approval_sha256"],
            nonce_sha256=nonce["nonce_sha256"], ledger=ledger,
            final_bindings=bindings, terminal_verification=_terminal(),
        )
    assert keys.value.reason_code == "COMPLETION_BINDING_KEYS_MISMATCH"


def test_mark_local_stage_complete_closes_only_pending_ordinal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "pending-only")
    observer = _observer(store, "pending-only")
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages",
        payload=_payload(),
    )
    observer.after_http_response(status_code=200)
    observer.mark_local_attempt_rejected(
        stage="planning-semantic-v2", role="planning",
        role_binding_sha256=observer.bound_route["role_binding_sha256"],
        rejection=_local_rejection(),
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    observer.bind_model_request(protocol="anthropic", request=_request())
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages",
        payload=_payload(),
    )
    observer.after_http_response(status_code=200)
    binding = observer.bound_route["role_binding_sha256"]

    def reopen_first(body: dict) -> dict:
        body["attempts"][0]["state"] = "RESPONSE_RECEIVED"
        return body

    store.update_ledger("pending-only", reopen_first)
    observer.mark_local_stage_complete(
        stage="planning", role="planning", role_binding_sha256=binding,
        output_sha256="c" * 64, receipt_sha256="d" * 64,
    )
    ledger = store.load_ledger("pending-only")
    assert ledger["attempts"][0]["state"] == "RESPONSE_RECEIVED"
    assert ledger["attempts"][1]["state"] == "LOCAL_STAGE_COMPLETE"


def test_mark_local_stage_complete_cannot_replace_authorized_stage_id(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    plan = _logical_stage_plan((
        "draft_node_1", "planning", "unstructured_text", 1,
        _hash({}), False, 128,
    ))
    _authorize_offline(
        store, "immutable-stage-id", logical_stage_plan=plan,
    )
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id="immutable-stage-id",
        policy=_policy(store, logical_stage_plan=plan),
        authorized_routes=_routes(), egress_policy=_egress(),
    )
    observer.bind_stage_context(
        stage_id="draft_node_1", contract_name="unstructured_text",
        contract_version=1, contract_schema_sha256=_hash({}),
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    observer.bind_model_request(protocol="anthropic", request=_request())
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages",
        payload=_payload(),
    )
    observer.capture_provider_protocol_input(
        data=b"{}", status_code=200, content_type="application/json",
        encoding="utf-8", transport_complete=True,
    )
    observer.after_http_response(status_code=200)
    binding = observer.bound_route["role_binding_sha256"]

    with pytest.raises(FullShortExecutionBoundaryError) as drift:
        observer.mark_local_stage_complete(
            stage="Draft Chapter One", role="planning",
            role_binding_sha256=binding,
            output_sha256="a" * 64, receipt_sha256="b" * 64,
        )
    assert drift.value.reason_code == "STAGE_ID_DRIFT"

    observer.mark_local_stage_complete(
        stage="draft_node_1", role="planning",
        role_binding_sha256=binding,
        output_sha256="a" * 64, receipt_sha256="b" * 64,
    )
    ledger = store.load_ledger("immutable-stage-id")
    assert ledger["attempts"][0]["stage"] == "draft_node_1"
    assert ledger["completed_stage_receipts"][0]["stage"] == "draft_node_1"


def test_local_rejection_must_match_current_logical_attempt_identity(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    plan = _logical_stage_plan((
        "planning", "planning", "planning_semantic_v2", 2,
        "1" * 64, False, 128,
    ))
    _authorize_offline(
        store, "rejection-attempt-identity", logical_stage_plan=plan,
    )
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id="rejection-attempt-identity",
        policy=_policy(store, logical_stage_plan=plan),
        authorized_routes=_routes(),
        egress_policy=_egress(),
    )
    observer.bind_stage_context(
        stage_id="planning", contract_name="planning_semantic_v2",
        contract_version=2, contract_schema_sha256="1" * 64,
        contract_attempt_index=1, contract_route="primary",
        contract_route_attempt=1,
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    observer.bind_model_request(protocol="anthropic", request=_request())
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages", payload=_payload(),
    )
    observer.capture_provider_protocol_input(
        data=b"{}", status_code=200, content_type="application/json",
        encoding="utf-8", transport_complete=True,
    )
    observer.capture_contract_runtime_input(
        data=b"{}", adapter_id="anthropic", adapter_version=1,
        finish_reason="stop", transport_complete=True,
    )
    observer.after_http_response(status_code=200)

    with pytest.raises(FullShortExecutionBoundaryError) as mismatch:
        observer.mark_local_attempt_rejected(
            stage="planning-semantic-v2", role="planning",
            role_binding_sha256=observer.bound_route["role_binding_sha256"],
            rejection=_local_rejection(route_attempt=2),
        )

    assert mismatch.value.reason_code == (
        "LOCAL_REJECTION_ATTEMPT_IDENTITY_INVALID"
    )
    assert store.load_ledger("rejection-attempt-identity")["attempts"][0][
        "state"
    ] == "RESPONSE_RECEIVED"


def test_new_logical_stage_over_cap_is_rejected_before_dispatch(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "logical-cap")
    observer = _dispatch_and_close(store, "logical-cap")
    with pytest.raises(FullShortExecutionBoundaryError) as capped:
        observer.bind_stage_context(
            stage_id="draft", contract_name="unstructured_text",
            contract_version=1, contract_schema_sha256=_hash({}),
        )

    assert capped.value.reason_code == "LOGICAL_STAGE_PLAN_EXHAUSTED"
    assert len(store.load_ledger("logical-cap")["attempts"]) == 1


def test_repeated_workflow_node_allocates_distinct_logical_occurrences(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    execution_id = "repeated-workflow-node"
    plan = _logical_stage_plan(*(
        ("draft", "planning", "draft_text", 1, _hash({}), False, 128)
        for _ in range(2)
    ))
    policy = _policy(
        store, expected_stage_calls=2, logical_stage_plan=plan,
    )
    _authorize_offline(
        store, execution_id, expected_stage_calls=2,
        logical_stage_plan=plan,
    )
    observer = FullShortDispatchLedgerObserverV1(
        store=store, execution_id=execution_id, policy=policy,
        authorized_routes=_routes(), egress_policy=_egress(),
    )

    for _ in range(2):
        observer.bind_stage_context(
            stage_id="draft", contract_name="draft_text",
            contract_version=1, contract_schema_sha256=_hash({}),
        )
        observer.bind_route(
            role="planning", lane="primary", provider_id="provider",
            model_id="model-id", route_fingerprint="9" * 64,
        )
        observer.bind_model_request(protocol="anthropic", request=_request())
        observer.before_http_dispatch(
            method="POST", url="https://unit.test/v1/messages",
            payload=_payload(),
        )
        observer.capture_provider_protocol_input(
            data=b"{}", status_code=200, content_type="application/json",
            encoding="utf-8", transport_complete=True,
        )
        observer.after_http_response(status_code=200)
        observer.mark_local_stage_complete(
            stage="draft", role="planning",
            role_binding_sha256=observer.bound_route["role_binding_sha256"],
            output_sha256="a" * 64, receipt_sha256="b" * 64,
        )

    attempts = store.load_ledger(execution_id)["attempts"]
    assert [item["logical_stage_base_id"] for item in attempts] == [
        "draft", "draft",
    ]
    assert attempts[0]["logical_stage_id"] == "draft"
    assert attempts[1]["logical_stage_id"].startswith("draft.2.")


def test_pre_dispatch_failure_releases_only_unrecorded_request_binding(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _authorize_offline(store, "pre-dispatch-release")
    observer = _observer(store, "pre-dispatch-release")

    observer.after_http_failure(failure_kind="LocalAuthorizationError")

    assert observer.bound_route is None
    assert observer.expected_provider_payload is None
    assert observer.egress_intent_sha256 is None
    assert observer.pending_stage_context is None
    assert store.load_ledger("pre-dispatch-release")["attempts"] == []
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )


def test_real_runner_collects_live_bindings_without_secret_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    db = Database(data / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="public-provider", name="Public", protocol="anthropic",
        base_url="https://unit.test/v1", auth_type="x-api-key",
        timeout_seconds=30, extra_headers={},
    )
    db.save_model(
        model_id="public-model", provider_id="public-provider",
        display_name="Public Model", model_name="public-model",
        context_window=None, max_output_tokens=None,
    )
    for role in (
        "planning", "draft", "review", "reader_review", "polish",
        "final_review", "maintenance",
    ):
        db.save_role_binding(
            role, "public-provider", "public-model", None, None,
        )
    projects = ProjectStore(db, data / "projects")
    project = projects.create(ProjectCreate(
        title="Bound", mode="short", genre="mystery",
        premise="A sealed binding is checked.", target_words=13_000,
    ))
    StoryStateStore(db).ensure(project.id, project.path)
    db.set_feature_flag(
        "short_canonical_v2", True,
        scope_type="project", scope_id=project.id,
    )
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    monkeypatch.setattr(real_runner, "_git", lambda _repo, *args: (
        "a" * 40 if args == ("rev-parse", "HEAD")
        else "test-branch" if args == ("branch", "--show-current")
        else ""
    ))
    monkeypatch.setattr(real_runner, "REQUIRED_SKILLS", {})
    monkeypatch.setattr(real_runner, "OPTIONAL_PROMPT_SKILLS", {})

    actual, public = real_runner.collect_live_bindings(
        repo=repo, data_dir=data, project_id=project.id,
        run_id="one-trustworthy-full-short",
        logical_stage_plan=list(_logical_stage_plan()),
        store_root=tmp_path / "store",
    )

    assert actual["worktree_clean"] is True
    assert actual["run_id"] == "one-trustworthy-full-short"
    assert actual["logical_stage_plan_sha256"] == public[
        "logical_stage_plan_sha256"
    ]
    assert public["transport_recovery_policy"] == TRANSPORT_RECOVERY_POLICY_V1
    assert public["destinations"] == [
        "https://unit.test:443/v1/messages",
    ]
    assert public["maximum_configured_output_tokens_per_call"] == 12_288
    assert actual["external_action_counters"] == {
        "credential_lookup": 0, "provider_client_creation": 0,
        "provider_request": 0, "http_post": 0, "network": 0,
        "model": 0, "paid": 0,
    }
