from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from novel_flywheel.db import Database
from novel_flywheel.domain.models import Message, ModelRequest
from novel_flywheel.full_short_execution import (
    FullShortDispatchLedgerObserverV1,
    FullShortDurableExecutionStoreV1,
    FullShortExecutionBoundaryError,
    FullShortExecutionPolicyV1,
    _expected_provider_payload_v1,
    build_full_short_completion_receipt_v1,
    render_full_short_canonical_authorization_v1,
    validate_full_short_canonical_authorization_v1,
    validate_full_short_preflight_v1,
)
from novel_flywheel.providers.http import (
    HttpProvider,
    SingleDispatchTransportGuardError,
    SingleDispatchTransportPolicyV1,
)
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.story_state import StoryStateStore
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


def _policy(
    store: FullShortDurableExecutionStoreV1 | None = None, *,
    expected_stage_calls: int = 1,
) -> dict:
    store_hash = store.store_root_sha256 if store is not None else "0" * 64
    return FullShortExecutionPolicyV1(
        execution_head="a" * 40,
        branch="test",
        run_id="test-full-short",
        project_id_sha256="b" * 64,
        workload_sha256="c" * 64,
        runtime_authority_sha256="d" * 64,
        style_reference_authority_sha256="e" * 64,
        route_manifest_sha256=_hash(list(_routes())),
        destination_manifest_sha256=_hash([
            "https://unit.test:443/v1/messages",
        ]),
        egress_policy_sha256=_hash(_egress()),
        store_root_sha256=store_hash,
        required_stage_roles=("planning",),
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
) -> tuple[dict, dict, dict]:
    policy = _policy(store)
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
    observer.bind_model_request(protocol="anthropic", request=_request())
    with pytest.raises(FullShortExecutionBoundaryError) as replay:
        observer.before_http_dispatch(
            method="POST", url="https://unit.test/v1/messages",
            payload=_payload(),
        )
    assert replay.value.reason_code == "EXECUTION_ALREADY_COMPLETED"
    await provider.client.aclose()


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

    with pytest.raises(
        SingleDispatchTransportGuardError,
        match="credential_reflection_rejected",
    ):
        await provider.post(
            "v1/messages",
            payload={**_payload(), "unexpected_extension": "offline-key"},
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
    bindings = {
        "project_workload": "hash-bound-test",
        "routes": list(_routes()),
        "destinations": ["https://unit.test:443/v1/messages"],
        "egress_policy": _egress(),
        "store_root_sha256": "0" * 64,
    }
    raw = render_full_short_canonical_authorization_v1(
        policy=_policy(), public_bindings=bindings,
    )
    authorization = validate_full_short_canonical_authorization_v1(
        raw, policy=_policy(), public_bindings=bindings,
    )
    receipt = validate_full_short_preflight_v1(
        policy=_policy(), actual=_preflight_actual(),
        authorization_text_sha256=authorization["authorization_text_sha256"],
        external_actions_enabled=False,
    )
    assert receipt["binding_status"] == "exact"
    assert receipt["approval_state"] == "NOT_CREATED"
    assert receipt["nonce_state"] == "NOT_CREATED"


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
    store = _store(tmp_path)
    _authorize_offline(store, "token-cap")
    observer = _observer(store, "token-cap", max_tokens=3000)
    observer.before_http_dispatch(
        method="POST", url="https://unit.test/v1/messages",
        payload=_payload(3000),
    )
    observer.after_http_response(status_code=200)
    observer.mark_local_stage_complete(
        stage="planning", role="planning",
        role_binding_sha256=observer.bound_route["role_binding_sha256"],
        output_sha256="a" * 64,
        receipt_sha256="b" * 64,
    )
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model-id", route_fingerprint="9" * 64,
    )
    observer.bind_model_request(
        protocol="anthropic", request=_request(2000),
    )
    with pytest.raises(FullShortExecutionBoundaryError) as capped:
        observer.before_http_dispatch(
            method="POST", url="https://unit.test/v1/messages",
            payload=_payload(2000),
        )
    assert capped.value.reason_code == "TOTAL_OUTPUT_TOKEN_CAP_EXHAUSTED"
    ledger = store.load_ledger("token-cap")
    assert len(ledger["attempts"]) == 1
    assert ledger["total_requested_output_tokens"] == 3000


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
    observer = _dispatch_and_close(store, "pending-only")
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
        run_id="one-trustworthy-full-short", store_root=tmp_path / "store",
    )

    assert actual["worktree_clean"] is True
    assert actual["run_id"] == "one-trustworthy-full-short"
    assert public["destinations"] == [
        "https://unit.test:443/v1/messages",
    ]
    assert public["maximum_configured_output_tokens_per_call"] == 12_288
    assert actual["external_action_counters"] == {
        "credential_lookup": 0, "provider_client_creation": 0,
        "provider_request": 0, "http_post": 0, "network": 0,
        "model": 0, "paid": 0,
    }
