from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess

import httpx
import pytest

from novel_flywheel.db import Database
from novel_flywheel.providers.http import HttpProvider, SingleDispatchTransportPolicyV1
from novel_flywheel.secrets import MemorySecretStore
from tools.canary import skill_v3_character_heavy_pilot as pilot
from tools.canary import skill_v3_pilot_approval_store as approvals
from tools.canary.skill_v3_a1_destination_binding import (
    DESTINATION_OPERATOR_THIRD_PARTY,
    SkillV3DestinationBindingError,
    a1_egress_policy_v1,
    request_target_is_exact_v1,
    resolve_a1_destination_binding_v1,
    validate_destination_authority_v1,
)
from tools.canary.skill_v3_pilot_nonce_store import (
    DurablePilotNonceStoreV1,
    NONCE_POLICY_VERSION,
    NONCE_SCHEMA_V2,
)
from tools.canary.skill_v3_real_execution_boundary import (
    DestinationBoundNonceStoreV2Adapter,
    OfflineDispatchDependenciesV1,
    REAL_DISPATCHER_VERSION,
    RealPilotDispatcherV1,
    launch_real_a1_once_v1,
)


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_ID = "sv3s-089dd120ad568f87e7ef"
NEGATIVE_CASES = (
    "MISSING_DESTINATION_BINDING",
    "WRONG_HOST",
    "WRONG_PORT",
    "WRONG_SCHEME",
    "WRONG_PATH_PREFIX",
    "CALLER_BASE_URL_OVERRIDE",
    "ENV_BASE_URL_OVERRIDE",
    "UNBOUND_HTTP_PROXY",
    "UNBOUND_HTTPS_PROXY",
    "UNBOUND_ALL_PROXY",
    "CROSS_ORIGIN_REDIRECT",
    "FALLBACK_TO_SECOND_ORIGIN",
    "ROUTE_SWITCH_TO_SECOND_ORIGIN",
    "MODEL_ROUTE_RESOLVES_DIFFERENT_ORIGIN",
    "APPROVAL_DESTINATION_SHA_MISMATCH",
    "NONCE_DESTINATION_SHA_MISMATCH",
    "EGRESS_POLICY_SHA_MISMATCH",
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _clean_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    (repo / "sentinel.txt").write_text("sealed\n", encoding="utf-8")
    _git(repo, "add", "sentinel.txt")
    _git(repo, "commit", "-m", "baseline")
    return repo, _git(repo, "rev-parse", "HEAD")


def _v3_payload(head: str) -> dict[str, object]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "approval_id": "destination-bound-approval",
        "repository_head": head,
        "pilot_id": pilot.PILOT_ID,
        "sample_id": SAMPLE_ID,
        "sample_slot": "A1",
        "arm": "A",
        "sample_index": 1,
        "sample_lock_sha256": "1" * 64,
        "parent_experiment_lock_sha256": pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        "model_input_component_binding_sha256": "2" * 64,
        "provider_descriptor_sha256": "3" * 64,
        "model_binding_sha256": "4" * 64,
        "route_fingerprint": "5" * 64,
        "wire_input_sha256": "6" * 64,
        "sampling_policy_sha256": "7" * 64,
        "validator_sha256": "8" * 64,
        "nonce_policy_version": NONCE_POLICY_VERSION,
        "real_dispatcher_version": REAL_DISPATCHER_VERSION,
        "max_output_tokens": 4624,
        "user_authorization_message_sha256": "9" * 64,
        "user_authorization_context_identity_sha256": "a" * 64,
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "destination_origin": "https://relay.example.invalid",
        "destination_origin_sha256": "b" * 64,
        "destination_path_or_prefix": "/v1/messages",
        "destination_operator_class": DESTINATION_OPERATOR_THIRD_PARTY,
        "egress_policy_sha256": "c" * 64,
        "cross_origin_redirect_allowed": False,
        "unbound_proxy_route_allowed": False,
    }


def _secret_store() -> MemorySecretStore:
    db = Database(ROOT / "data" / "app.db")
    binding = db.get_role_binding("planning")
    assert binding is not None
    store = MemorySecretStore()
    store.set(str(binding["primary_provider_id"]), "offline-placeholder")
    return store


def _success_body() -> dict[str, object]:
    fixture = json.loads((ROOT / pilot.FIXTURE_PATH).read_text(encoding="utf-8"))
    narrative = json.dumps({
        "events": [{
            "event_id": fixture["authority_input"]["formal_event_id"],
            "narrative": "A1: Mara chooses a costly defense and changes the wary bargain.",
        }],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "id": "offline-message",
        "type": "message",
        "content": [{"type": "text", "text": json.dumps({"title": "A1", "narrative": narrative})}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 100},
    }


class RecordingHandler:
    def __init__(self, *, redirect: bool = False) -> None:
        self.redirect = redirect
        self.urls: list[str] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        if self.redirect:
            return httpx.Response(
                307,
                headers={"location": "https://second.example.invalid/v1/messages"},
                request=request,
            )
        return httpx.Response(200, json=_success_body(), request=request)


def _destination_authority() -> tuple[object, dict[str, object], dict[str, object]]:
    destination = resolve_a1_destination_binding_v1(
        repo_root=ROOT, route_database=ROOT / "data" / "app.db",
    )
    egress = a1_egress_policy_v1(ROOT)
    authority = {
        "destination_origin": destination.origin,
        "destination_origin_sha256": destination.destination_origin_sha256,
        "destination_path_or_prefix": destination.api_path,
        "destination_operator_class": destination.operator_class,
        "egress_policy_sha256": egress["egress_policy_sha256"],
        "cross_origin_redirect_allowed": False,
        "unbound_proxy_route_allowed": False,
    }
    return destination, egress, authority


def _fake_v3_approval(lock: dict[str, object], authority: dict[str, object], approval_id: str) -> dict[str, object]:
    approval = pilot.fake_signed_approval(lock)
    approval.update(authority)
    approval["approval_id"] = approval_id
    approval["signed_approval_sha256"] = "d" * 64
    return approval


def _offline_dispatcher(tmp_path: Path, handler: RecordingHandler, authority: dict[str, object]) -> RealPilotDispatcherV1:
    return RealPilotDispatcherV1(
        repo_root=ROOT,
        route_database=ROOT / "data" / "app.db",
        execution_root=tmp_path / "run",
        approved_destination_authority=authority,
        offline_dependencies=OfflineDispatchDependenciesV1(
            secret_store=_secret_store(),
            client_factory=lambda: httpx.AsyncClient(
                timeout=180,
                follow_redirects=False,
                trust_env=False,
                transport=httpx.MockTransport(handler),
            ),
        ),
    )


def test_exact_non_secret_destination_and_egress_binding() -> None:
    destination, egress, authority = _destination_authority()
    assert destination.origin == "https://lingsuan.org"
    assert destination.hostname == "lingsuan.org"
    assert destination.scheme == "https"
    assert destination.port == 443
    assert destination.api_path == "/v1/messages"
    assert destination.operator_class == DESTINATION_OPERATOR_THIRD_PARTY
    assert destination.allowed_destination_count == 1
    assert destination.cross_origin_redirect_allowed is False
    assert destination.unbound_proxy_route_allowed is False
    assert len(egress["components"]) == 8
    assert all(row["egress_included"] for row in egress["components"])
    assert all(value is False for value in egress["excluded"].values())
    validate_destination_authority_v1(
        authority,
        destination=destination,
        egress_policy_sha256=str(egress["egress_policy_sha256"]),
    )


def test_approval_v3_is_destination_bound_and_worktree_external(tmp_path: Path) -> None:
    repo, head = _clean_repo(tmp_path)
    payload = _v3_payload(head)
    store = tmp_path / "external" / "approvals"
    signed = approvals.create_successor_signed_approval_v3(
        repo_root=repo, store_root=store, payload=payload,
    )
    assert signed["schema"] == approvals.SIGNED_APPROVAL_SCHEMA_V3
    assert signed["version"] == 3
    assert signed["destination_origin"] == payload["destination_origin"]
    assert signed["destination_path_or_prefix"] == "/v1/messages"
    assert signed["cross_origin_redirect_allowed"] is False
    assert signed["unbound_proxy_route_allowed"] is False
    assert signed["usage_status"] == "unused"
    assert signed["nonce_state"] == "NOT_CREATED"
    assert _git(repo, "status", "--porcelain=v1") == ""


def test_destination_bound_nonce_v2_is_restart_safe(tmp_path: Path) -> None:
    store = DurablePilotNonceStoreV1(
        repo_root=ROOT, store_root=tmp_path / "external" / "nonces",
    )
    destination, egress, _authority = _destination_authority()
    reserved = store.reserve_destination_bound_v2(
        pilot_id=pilot.PILOT_ID,
        sample_id=SAMPLE_ID,
        sample_lock_sha256="1" * 64,
        parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        execution_head="a" * 40,
        approval_id="destination-bound-nonce",
        signed_approval_sha256="2" * 64,
        model_input_component_binding_sha256="3" * 64,
        route_fingerprint=destination.route_fingerprint,
        approved_destination_origin=destination.origin,
        approved_destination_origin_sha256=destination.destination_origin_sha256,
        approved_destination_path_or_prefix=destination.api_path,
        egress_policy_sha256=str(egress["egress_policy_sha256"]),
        cross_origin_redirect_allowed=False,
        unbound_proxy_route_allowed=False,
    )
    assert reserved["schema"] == NONCE_SCHEMA_V2
    restarted = DurablePilotNonceStoreV1(repo_root=ROOT, store_root=store.store_root)
    assert restarted.load(
        pilot_id=pilot.PILOT_ID,
        sample_id=SAMPLE_ID,
        approval_id="destination-bound-nonce",
    ) == reserved


def test_real_dispatcher_counting_transport_targets_only_sealed_destination(tmp_path: Path) -> None:
    lock = pilot.load_sealed_pilot(ROOT)["locks"][0]
    destination, egress, authority = _destination_authority()
    approval = _fake_v3_approval(lock, authority, "offline-v3-a1")
    handler = RecordingHandler()
    dispatcher = _offline_dispatcher(tmp_path, handler, authority)
    nonce = DestinationBoundNonceStoreV2Adapter(
        delegate=DurablePilotNonceStoreV1(
            repo_root=ROOT, store_root=tmp_path / "external" / "nonces",
        ),
        destination=destination,
        approval=approval,
    )
    result = asyncio.run(pilot.launch_one_sealed_sample(
        repo_root=ROOT,
        pilot_id=pilot.PILOT_ID,
        sample_id=str(lock["sample_id"]),
        expected_sample_lock_sha256=str(lock["sample_lock_sha256"]),
        expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        permission=pilot.fake_permission(lock),
        signed_approval=approval,
        nonce_store=nonce,
        ledger=pilot.FakePilotLedger(),
        dispatcher=dispatcher,
        output_root=tmp_path / "run" / "output",
        offline_fake=True,
    ))
    assert result["status"] == "SEALED_VALID"
    assert handler.urls == ["https://lingsuan.org/v1/messages"]
    assert request_target_is_exact_v1(handler.urls[0], destination)
    assert dispatcher.destination_check_count == 3
    record = nonce.load(
        pilot_id=pilot.PILOT_ID, sample_id=SAMPLE_ID,
        approval_id=str(approval["approval_id"]),
    )
    assert record["state"] == "CONSUMED"
    assert record["approved_destination_origin_sha256"] == destination.destination_origin_sha256
    assert record["egress_policy_sha256"] == egress["egress_policy_sha256"]


def test_cross_origin_redirect_is_not_followed(tmp_path: Path) -> None:
    lock = pilot.load_sealed_pilot(ROOT)["locks"][0]
    destination, _egress, authority = _destination_authority()
    approval = _fake_v3_approval(lock, authority, "offline-v3-redirect")
    handler = RecordingHandler(redirect=True)
    dispatcher = _offline_dispatcher(tmp_path, handler, authority)
    nonce = DestinationBoundNonceStoreV2Adapter(
        delegate=DurablePilotNonceStoreV1(
            repo_root=ROOT, store_root=tmp_path / "external" / "nonces",
        ),
        destination=destination,
        approval=approval,
    )
    with pytest.raises(pilot.PilotBoundaryError, match="PROVIDER_BOUNDARY_FAILED"):
        asyncio.run(pilot.launch_one_sealed_sample(
            repo_root=ROOT,
            pilot_id=pilot.PILOT_ID,
            sample_id=str(lock["sample_id"]),
            expected_sample_lock_sha256=str(lock["sample_lock_sha256"]),
            expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
            permission=pilot.fake_permission(lock),
            signed_approval=approval,
            nonce_store=nonce,
            ledger=pilot.FakePilotLedger(),
            dispatcher=dispatcher,
            output_root=tmp_path / "run" / "output",
            offline_fake=True,
        ))
    assert handler.urls == ["https://lingsuan.org/v1/messages"]


def test_legacy_destination_unbound_launcher_fails_before_nonce(tmp_path: Path) -> None:
    with pytest.raises(pilot.PilotBoundaryError, match="DESTINATION_BOUND_APPROVAL_V3_REQUIRED"):
        asyncio.run(launch_real_a1_once_v1(
            repo_root=ROOT,
            permission={},
            approval_id="legacy",
        ))
    assert not (tmp_path / "nonce").exists()


@pytest.mark.parametrize("case", NEGATIVE_CASES)
def test_negative_destination_matrix(case: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    destination, egress, authority = _destination_authority()
    if case == "MISSING_DESTINATION_BINDING":
        with pytest.raises(SkillV3DestinationBindingError):
            validate_destination_authority_v1({}, destination=destination, egress_policy_sha256=str(egress["egress_policy_sha256"]))
    elif case == "WRONG_HOST":
        bad = {**authority, "destination_origin": "https://wrong.example.invalid"}
        with pytest.raises(SkillV3DestinationBindingError):
            validate_destination_authority_v1(bad, destination=destination, egress_policy_sha256=str(egress["egress_policy_sha256"]))
    elif case == "WRONG_PORT":
        assert not request_target_is_exact_v1("https://lingsuan.org:444/v1/messages", destination)
    elif case == "WRONG_SCHEME":
        assert not request_target_is_exact_v1("http://lingsuan.org/v1/messages", destination)
    elif case == "WRONG_PATH_PREFIX":
        assert not request_target_is_exact_v1("https://lingsuan.org/v2/messages", destination)
    elif case == "CALLER_BASE_URL_OVERRIDE":
        with pytest.raises(TypeError):
            RealPilotDispatcherV1(repo_root=ROOT, route_database=ROOT / "data/app.db", execution_root=tmp_path / "x", base_url="https://wrong.example.invalid")
    elif case == "ENV_BASE_URL_OVERRIDE":
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://wrong.example.invalid")
        assert resolve_a1_destination_binding_v1(repo_root=ROOT, route_database=ROOT / "data/app.db") == destination
    elif case in {"UNBOUND_HTTP_PROXY", "UNBOUND_HTTPS_PROXY", "UNBOUND_ALL_PROXY"}:
        monkeypatch.setenv(case.removeprefix("UNBOUND_"), "http://proxy.example.invalid")
        provider = HttpProvider("https://lingsuan.org", "offline", transport_policy=SingleDispatchTransportPolicyV1.phase_b())
        try:
            assert provider.client._mounts == {}
        finally:
            asyncio.run(provider.client.aclose())
    elif case == "CROSS_ORIGIN_REDIRECT":
        assert destination.cross_origin_redirect_allowed is False
    elif case == "FALLBACK_TO_SECOND_ORIGIN":
        dispatcher = _offline_dispatcher(tmp_path, RecordingHandler(), authority)
        assert dispatcher.fallback_disabled is True
    elif case == "ROUTE_SWITCH_TO_SECOND_ORIGIN":
        dispatcher = _offline_dispatcher(tmp_path, RecordingHandler(), authority)
        assert dispatcher.route_switch_disabled is True
    elif case == "MODEL_ROUTE_RESOLVES_DIFFERENT_ORIGIN":
        database = tmp_path / "drift.db"
        shutil.copy2(ROOT / "data/app.db", database)
        db = Database(database)
        binding = db.get_role_binding("planning")
        provider = db.get_provider(str(binding["primary_provider_id"]))
        db.save_provider(provider_id=str(provider["id"]), name=str(provider["name"]), protocol=str(provider["protocol"]), base_url="https://wrong.example.invalid", auth_type=str(provider["auth_type"]), timeout_seconds=int(provider["timeout_seconds"]), extra_headers=dict(provider.get("extra_headers") or {}), enabled=True)
        with pytest.raises(Exception):
            resolve_a1_destination_binding_v1(repo_root=ROOT, route_database=database)
    elif case == "APPROVAL_DESTINATION_SHA_MISMATCH":
        bad = {**authority, "destination_origin_sha256": "0" * 64}
        with pytest.raises(SkillV3DestinationBindingError, match="APPROVAL_DESTINATION_SHA_MISMATCH"):
            validate_destination_authority_v1(bad, destination=destination, egress_policy_sha256=str(egress["egress_policy_sha256"]))
    elif case == "NONCE_DESTINATION_SHA_MISMATCH":
        bad = {**authority, "destination_origin_sha256": "0" * 64, "signed_approval_sha256": "d" * 64}
        with pytest.raises(SkillV3DestinationBindingError, match="APPROVAL_DESTINATION_SHA_MISMATCH"):
            DestinationBoundNonceStoreV2Adapter(delegate=DurablePilotNonceStoreV1(repo_root=ROOT, store_root=tmp_path / "nonces"), destination=destination, approval=bad)
    elif case == "EGRESS_POLICY_SHA_MISMATCH":
        bad = {**authority, "egress_policy_sha256": "0" * 64}
        with pytest.raises(SkillV3DestinationBindingError, match="EGRESS_POLICY_SHA_MISMATCH"):
            validate_destination_authority_v1(bad, destination=destination, egress_policy_sha256=str(egress["egress_policy_sha256"]))
    else:  # pragma: no cover
        raise AssertionError(case)
