from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from novel_flywheel.db import Database
from novel_flywheel.runtime_fingerprint_build import domain_sha256
from novel_flywheel.secrets import MemorySecretStore
from tools.canary import skill_v3_hybrid_character_heavy_pilot as hybrid
from tools.canary.skill_v3_hybrid_campaign import HybridApprovalBoundNonceAdapter
from tools.canary.skill_v3_hybrid_jit_approval import (
    DurableHybridApprovalStoreV1,
    HybridJitApprovalError,
    ZERO_ATTEMPT_COUNTERS,
    create_one_hybrid_sample_jit_approval,
    seal_campaign_permission_v1,
    validate_campaign_permission_v1,
)
from tools.canary.skill_v3_hybrid_real_campaign import (
    DurableHybridCampaignPermissionStoreV1,
    HybridCampaignExecutionEnvironmentV1,
    campaign_permission_from_authorization_v1,
    campaign_transport_preflight_v1,
    materialize_dry_run_blind_bundle_v1,
    render_final_authorization_text_v1,
    run_hybrid_campaign_v1,
    validate_final_authorization_text_v1,
)
from tools.canary.skill_v3_real_execution_boundary import (
    OfflineDispatchDependenciesV1,
    RealPilotDispatcherV1,
)


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)


def _git_head() -> str:
    import subprocess

    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()


def _permission() -> dict[str, object]:
    head = _git_head()
    text = render_final_authorization_text_v1(ROOT, successor_head=head)
    return campaign_permission_from_authorization_v1(
        repo_root=ROOT,
        permission_id="offline-closure-permission",
        authorization_bytes=text,
        repository_head=head,
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=10),
        offline_test_only=True,
    )


def _success_body(slot: str) -> dict[str, object]:
    fixture = json.loads((ROOT / hybrid.FIXTURE_PATH).read_text(encoding="utf-8"))
    narrative = json.dumps({
        "events": [{
            "event_id": fixture["authority_input"]["formal_event_id"],
            "narrative": (
                f"{slot}: Mara accepts a concrete cost to protect Iven, meets "
                "resistance, and changes their wary bargain without erasing betrayal."
            ),
        }],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    text = json.dumps(
        {"title": f"Dry run {slot}", "narrative": narrative},
        ensure_ascii=False,
    )
    return {
        "id": "offline-message",
        "type": "message",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 200, "output_tokens": 120},
    }


class LowestSeamHandler:
    def __init__(self, slot: str, outcome: str = "SUCCESS") -> None:
        self.slot = slot
        self.outcome = outcome
        self.count = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.count += 1
        if self.outcome == "HTTP_ERROR":
            return httpx.Response(503, json={"error": "offline"}, request=request)
        body = _success_body(self.slot)
        if self.outcome == "PARSE_ERROR":
            body = {**body, "content": [{"type": "text", "text": "not-json"}]}
        return httpx.Response(200, json=body, request=request)


def _secret_store(*, available: bool = True) -> MemorySecretStore:
    database = Database(ROOT / "data" / "app.db")
    binding = database.get_role_binding("planning")
    assert binding is not None
    store = MemorySecretStore()
    if available:
        store.set(str(binding["primary_provider_id"]), "offline-placeholder")
    return store


def _environment(
    tmp_path: Path, *, fail_slot: str | None = None,
    failure_outcome: str = "HTTP_ERROR", secret_available: bool = True,
) -> tuple[HybridCampaignExecutionEnvironmentV1, list[LowestSeamHandler]]:
    handlers: list[LowestSeamHandler] = []

    def factory(lock: dict[str, object], approval_id: str) -> RealPilotDispatcherV1:
        slot = str(lock["SAMPLE_SLOT"])
        handler = LowestSeamHandler(
            slot, failure_outcome if slot == fail_slot else "SUCCESS",
        )
        handlers.append(handler)
        return RealPilotDispatcherV1(
            repo_root=ROOT,
            route_database=ROOT / "data" / "app.db",
            execution_root=tmp_path / "dispatch" / approval_id,
            offline_dependencies=OfflineDispatchDependenciesV1(
                secret_store=_secret_store(available=secret_available),
                client_factory=lambda: httpx.AsyncClient(
                    timeout=180, transport=httpx.MockTransport(handler),
                ),
            ),
            approved_destination_authority={
                "destination_origin": "https://lingsuan.org",
                "destination_origin_sha256": "356a50c853735ad87163de137457b9e95cda70dfdb24229ffef847aff38a0b21",
                "destination_path_or_prefix": "/v1/messages",
                "destination_operator_class": "THIRD_PARTY_RELAY_LOCAL_METADATA_ONLY",
                "egress_policy_sha256": str(lock["EGRESS_POLICY_SHA256"]),
                "cross_origin_redirect_allowed": False,
                "unbound_proxy_route_allowed": False,
            },
            expected_sampling_policy_sha256=str(lock["SAMPLING_FINGERPRINT"]),
            expected_output_cap=int(lock["OUTPUT_CAP"]),
        )

    return HybridCampaignExecutionEnvironmentV1.offline(
        repo_root=ROOT,
        store_parent=tmp_path / "stores",
        output_root=tmp_path / "outputs",
        dispatcher_factory=factory,
    ), handlers


def test_canonical_authorization_is_exact_bytes_only() -> None:
    head = _git_head()
    text = render_final_authorization_text_v1(ROOT, successor_head=head)
    receipt = validate_final_authorization_text_v1(
        ROOT, text, successor_head=head,
        expected_sha256=hashlib.sha256(text).hexdigest(),
    )
    assert receipt["status"] == "EXACT"
    for mutated in (
        text[:-1] + b" ",
        text.replace(b"https://lingsuan.org:443/v1/messages", b"[https://lingsuan.org:443/v1/messages](https://lingsuan.org:443/v1/messages)"),
        text.replace(head.encode(), ("0" * 40).encode()),
        text.replace(b"sv3hs-84e695ee4e02665555cf", b"missing-sample"),
        text.replace(
            b"10dea0857ebee6142a8c1b708484b8abbf8f3a5f848fd19d8bd7154a1c570d09",
            b"0" * 64,
        ),
    ):
        with pytest.raises(HybridJitApprovalError, match="AUTHORIZATION_TEXT_EXACT_MISMATCH"):
            validate_final_authorization_text_v1(ROOT, mutated, successor_head=head)


def test_campaign_permission_is_durable_expiring_and_single_create(tmp_path: Path) -> None:
    permission = _permission()
    store = DurableHybridCampaignPermissionStoreV1(
        repo_root=ROOT, store_root=tmp_path / "campaign",
    )
    created = store.create(permission, now=NOW, require_executable=False)
    restarted = DurableHybridCampaignPermissionStoreV1(
        repo_root=ROOT, store_root=tmp_path / "campaign",
    )
    assert restarted.load(
        str(permission["permission_id"]), now=NOW, require_executable=False,
    )["state"] == created["state"]
    with pytest.raises(HybridJitApprovalError, match="CAMPAIGN_PERMISSION_DOUBLE_CREATE"):
        restarted.create(permission, now=NOW, require_executable=False)
    with pytest.raises(HybridJitApprovalError, match="CAMPAIGN_PERMISSION_EXPIRED"):
        restarted.load(
            str(permission["permission_id"]), now=NOW + timedelta(hours=11),
            require_executable=False,
        )


def _resign_permission(permission: dict[str, object], field: str, value: object) -> dict[str, object]:
    body = deepcopy(permission)
    body.pop("permission_scope_sha256")
    body.pop("campaign_permission_sha256")
    body[field] = value
    return seal_campaign_permission_v1(body)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pilot_id", "wrong-pilot"),
        ("experiment_lock_sha256", "0" * 64),
        ("repository_head", "0" * 40),
        ("authorized_sequence", ["HYBRID_1"]),
        ("authorized_sample_ids", ["wrong"] * 6),
        ("authorized_sample_lock_sha256s", ["0" * 64] * 6),
        ("provider", "wrong-provider"),
        ("provider_descriptor_sha256", "0" * 64),
        ("model", "wrong-model"),
        ("model_binding_sha256", "0" * 64),
        ("protocol", "wrong-protocol"),
        ("route_fingerprint", "0" * 64),
        ("destination_origin", "https://wrong.example.invalid"),
        ("destination_hostname", "wrong.example.invalid"),
        ("destination_port", 444),
        ("destination_path", "/wrong"),
        ("operator_classification", "WRONG"),
        ("egress_policy_sha256s", ["0" * 64] * 6),
        ("per_sample_output_token_hard_cap", 4625),
        ("total_output_token_hard_cap", 27745),
        ("per_sample_provider_request_hard_cap", 2),
        ("total_provider_request_hard_cap", 7),
        ("max_campaign_elapsed_hours", 11),
        ("monetary_cost_cap", "USD_1"),
        ("no_retry", False),
        ("no_fallback", False),
        ("no_route_switch", False),
        ("no_second_dispatch", False),
        ("no_cross_origin_redirect", False),
        ("no_replacement_sample", False),
        ("skill_v3_cutover_authorized", True),
        ("planning_v2_cutover_authorized", True),
        ("full_short_authorized", True),
    ],
)
def test_permission_scope_drift_matrix_fails_closed(field: str, value: object) -> None:
    permission = _resign_permission(_permission(), field, value)
    with pytest.raises(HybridJitApprovalError):
        validate_campaign_permission_v1(
            permission, repo_root=ROOT, now=NOW, require_executable=False,
        )


def test_campaign_permission_concurrent_double_create_is_blocked(tmp_path: Path) -> None:
    permission = _permission()
    store = DurableHybridCampaignPermissionStoreV1(
        repo_root=ROOT, store_root=tmp_path / "campaign",
    )

    def create() -> str:
        try:
            store.create(permission, now=NOW, require_executable=False)
            return "CREATED"
        except HybridJitApprovalError as exc:
            return exc.reason_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: create(), range(2)))
    assert results.count("CREATED") == 1
    assert set(results) <= {
        "CREATED", "CAMPAIGN_PERMISSION_DOUBLE_CREATE",
        "CONCURRENT_APPROVAL_MUTATION",
    }


def test_later_sample_is_not_eligible_for_approval_or_nonce(tmp_path: Path) -> None:
    permission = _permission()
    store = DurableHybridCampaignPermissionStoreV1(
        repo_root=ROOT, store_root=tmp_path / "campaign",
    )
    store.create(permission, now=NOW, require_executable=False)
    second = hybrid.load_sealed_pilot(ROOT)["samples"][1]
    with pytest.raises(HybridJitApprovalError, match="LATER_SAMPLE_BEFORE_TURN"):
        store.assert_next_eligible(
            str(permission["permission_id"]),
            sample_id=str(second["SAMPLE_ID"]), now=NOW,
            require_executable=False,
        )
    approval_store = DurableHybridApprovalStoreV1(
        repo_root=ROOT, store_root=tmp_path / "approval",
    )
    with pytest.raises(
        HybridJitApprovalError,
        match="LATER_SAMPLE_APPROVAL_PRECREATION_FORBIDDEN",
    ):
        create_one_hybrid_sample_jit_approval(
            repo_root=ROOT, store=approval_store, permission=permission,
            sample_id=str(second["SAMPLE_ID"]), completed_sample_ids=[],
            approval_id="later-sample", attempt_counters=ZERO_ATTEMPT_COUNTERS,
            nonce_preexists=False, now=NOW,
            expires_at=NOW + timedelta(minutes=30), offline_test=True,
        )


@pytest.mark.asyncio
async def test_complete_six_sample_production_shaped_dry_run(tmp_path: Path) -> None:
    environment, handlers = _environment(tmp_path)
    permission = _permission()
    environment.campaign_store.create(permission, now=NOW, require_executable=False)
    receipt = await run_hybrid_campaign_v1(
        environment=environment,
        permission_id=str(permission["permission_id"]),
        now=NOW,
        offline_test=True,
    )
    assert receipt["status"] == "COMPLETED"
    assert receipt["sample_count"] == receipt["valid_sample_count"] == 6
    assert [handler.count for handler in handlers] == [1] * 6
    assert receipt["synthetic_http_attempt_count"] == 6
    assert receipt["real_external_action_count"] == 0
    assert receipt["approval_states"] == ["CONSUMED"] * 6
    assert receipt["nonce_states"] == ["CONSUMED"] * 6
    restarted = DurableHybridCampaignPermissionStoreV1(
        repo_root=ROOT, store_root=environment.campaign_store.store_root,
    )
    state = restarted.load(
        str(permission["permission_id"]), now=NOW, require_executable=False,
        allow_completed=True,
    )["state"]
    assert state["status"] == "COMPLETED"
    with pytest.raises(HybridJitApprovalError, match="CAMPAIGN_PERMISSION_NOT_ACTIVE"):
        await run_hybrid_campaign_v1(
            environment=environment,
            permission_id=str(permission["permission_id"]),
            now=NOW,
            offline_test=True,
        )


@pytest.mark.asyncio
async def test_middle_failure_stops_and_never_creates_later_authority(tmp_path: Path) -> None:
    environment, handlers = _environment(tmp_path, fail_slot="CONTROL_2")
    permission = _permission()
    environment.campaign_store.create(permission, now=NOW, require_executable=False)
    with pytest.raises(Exception):
        await run_hybrid_campaign_v1(
            environment=environment,
            permission_id=str(permission["permission_id"]),
            now=NOW,
            offline_test=True,
        )
    state = environment.campaign_store.load(
        str(permission["permission_id"]), now=NOW,
        require_executable=False, allow_stopped=True,
    )["state"]
    assert state["status"] == "STOPPED"
    assert len(state["completed_sample_ids"]) == 2
    assert len(handlers) == 3
    assert sum(handler.count for handler in handlers) == 3
    assert len(list(environment.approval_store.store_root.glob("*.approval.json"))) == 3
    assert len(list(environment.nonce_store.store_root.glob("*.nonce.json"))) == 3


@pytest.mark.parametrize("outcome", ["HTTP_ERROR", "PARSE_ERROR"])
@pytest.mark.asyncio
async def test_first_transport_or_terminal_failure_stops_without_retry(
    tmp_path: Path, outcome: str,
) -> None:
    environment, handlers = _environment(
        tmp_path, fail_slot="CONTROL_1", failure_outcome=outcome,
    )
    permission = _permission()
    environment.campaign_store.create(permission, now=NOW, require_executable=False)
    with pytest.raises(Exception):
        await run_hybrid_campaign_v1(
            environment=environment,
            permission_id=str(permission["permission_id"]),
            now=NOW,
            offline_test=True,
        )
    assert len(handlers) == 1
    assert handlers[0].count == 1
    state = environment.campaign_store.load(
        str(permission["permission_id"]), now=NOW,
        require_executable=False, allow_stopped=True,
    )["state"]
    assert state["status"] == "STOPPED"
    assert state["completed_sample_ids"] == []


@pytest.mark.asyncio
async def test_credential_boundary_failure_stops_before_http(tmp_path: Path) -> None:
    environment, handlers = _environment(
        tmp_path, fail_slot="CONTROL_1", secret_available=False,
    )
    permission = _permission()
    environment.campaign_store.create(permission, now=NOW, require_executable=False)
    with pytest.raises(Exception):
        await run_hybrid_campaign_v1(
            environment=environment,
            permission_id=str(permission["permission_id"]),
            now=NOW,
            offline_test=True,
        )
    assert len(handlers) == 1
    assert handlers[0].count == 0


@pytest.mark.asyncio
async def test_uncertain_post_dispatch_restart_never_dispatches_again(tmp_path: Path) -> None:
    environment, handlers = _environment(tmp_path)
    permission = _permission()
    environment.campaign_store.create(permission, now=NOW, require_executable=False)
    lock = hybrid.load_sealed_pilot(ROOT)["samples"][0]
    sample_id = str(lock["SAMPLE_ID"])
    approval_id = (
        "offline-hybrid-jit-1-"
        + domain_sha256(
            "novel-flywheel-skill-v3-hybrid-offline-approval-id-v1",
            {
                "permission": permission["campaign_permission_sha256"],
                "sample": sample_id,
            },
        )[:16]
    )
    approval = create_one_hybrid_sample_jit_approval(
        repo_root=ROOT, store=environment.approval_store,
        permission=permission, sample_id=sample_id, completed_sample_ids=[],
        approval_id=approval_id, attempt_counters=ZERO_ATTEMPT_COUNTERS,
        nonce_preexists=False, now=NOW,
        expires_at=NOW + timedelta(minutes=30), offline_test=True,
    )
    adapter = HybridApprovalBoundNonceAdapter(
        delegate=environment.nonce_store, approval=approval,
    )
    nonce = adapter.reserve(
        pilot_id=permission["pilot_id"], sample_id=sample_id,
        sample_lock_sha256=lock["SAMPLE_LOCK_SHA256"],
        parent_experiment_lock_sha256=lock["EXPERIMENT_LOCK_SHA256"],
        execution_head=approval["current_execution_head"],
        approval_id=approval_id,
        signed_approval_sha256=approval["signed_approval_sha256"],
        model_input_component_binding_sha256=lock["MODEL_INPUT_COMPONENT_SHA256"],
        route_fingerprint=lock["PROVIDER_MODEL_ROUTE_FINGERPRINT"],
    )
    environment.nonce_store.mark_dispatch_attempt(
        pilot_id=permission["pilot_id"], sample_id=sample_id,
        approval_id=approval_id, nonce_id=nonce["nonce_id"],
    )
    with pytest.raises(HybridJitApprovalError):
        await run_hybrid_campaign_v1(
            environment=environment,
            permission_id=str(permission["permission_id"]),
            now=NOW,
            offline_test=True,
        )
    assert handlers == []
    restarted_nonce = environment.nonce_store.load(
        pilot_id=str(permission["pilot_id"]), sample_id=sample_id,
        approval_id=approval_id,
    )
    assert restarted_nonce["state"] == "DISPATCH_ATTEMPTED"


def test_transport_preflight_and_dry_run_blind_bundle_are_exact_and_isolated(tmp_path: Path) -> None:
    preflight = campaign_transport_preflight_v1(ROOT)
    assert preflight["status"] == "EXACT"
    assert preflight["destination"] == "https://lingsuan.org:443/v1/messages"
    assert preflight["alternate_destination_count"] == 0
    bundle = materialize_dry_run_blind_bundle_v1(
        output_root=tmp_path / "blind",
        artifacts=[{"sample_id": "one", "artifact_file_sha256": "a" * 64}],
    )
    assert bundle["dry_run_only"] is True
    assert bundle["production_sample_eligible"] is False
    assert "one" not in json.dumps(bundle)
