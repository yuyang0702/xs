from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess

import httpx
import pytest

from novel_flywheel.db import Database
from novel_flywheel.secrets import MemorySecretStore
from tools.canary import skill_v3_character_heavy_pilot as pilot
from tools.canary import skill_v3_pilot_approval_store as approvals
from tools.canary.skill_v3_pilot_nonce_store import (
    DurablePilotNonceStoreV1,
    NONCE_POLICY_VERSION,
    SkillV3NonceStoreError,
)
from tools.canary.skill_v3_real_execution_boundary import (
    OfflineDispatchDependenciesV1,
    REAL_DISPATCHER_VERSION,
    RealPilotDispatcherV1,
    canonical_real_execution_environment_v1,
)


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_ID = "sv3s-089dd120ad568f87e7ef"


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


def _nonce_bindings(approval_id: str = "approval-one") -> dict[str, str]:
    return {
        "pilot_id": pilot.PILOT_ID,
        "sample_id": SAMPLE_ID,
        "sample_lock_sha256": "1" * 64,
        "parent_experiment_lock_sha256": pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        "execution_head": "a" * 40,
        "approval_id": approval_id,
        "signed_approval_sha256": "2" * 64,
        "model_input_component_binding_sha256": "3" * 64,
        "route_fingerprint": "4" * 64,
    }


def _success_body(slot: str = "A1") -> dict[str, object]:
    fixture = json.loads((ROOT / pilot.FIXTURE_PATH).read_text(encoding="utf-8"))
    narrative = json.dumps({
        "events": [{
            "event_id": fixture["authority_input"]["formal_event_id"],
            "narrative": (
                f"{slot}: Mara chooses a costly defense of Iven, meets resistance, "
                "and changes their wary bargain without erasing the betrayal."
            ),
        }],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    text = json.dumps(
        {"title": f"Pilot {slot}", "narrative": narrative},
        ensure_ascii=False,
    )
    return {
        "id": "offline-message",
        "type": "message",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 200, "output_tokens": 120},
    }


class CountingHandler:
    def __init__(self, *, outcome: str = "SUCCESS", slot: str = "A1") -> None:
        self.outcome = outcome
        self.slot = slot
        self.count = 0
        self.requests: list[dict[str, object]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.count += 1
        payload = json.loads(request.content.decode("utf-8"))
        self.requests.append(payload)
        if self.outcome == "TIMEOUT":
            raise httpx.ReadTimeout("offline timeout", request=request)
        if self.outcome == "HTTP_ERROR":
            return httpx.Response(503, json={"error": "offline"}, request=request)
        if self.outcome == "EMPTY_OUTPUT":
            body = {**_success_body(self.slot), "content": []}
        elif self.outcome == "PARSE_ERROR":
            body = {**_success_body(self.slot), "content": [{"type": "text", "text": "not-json"}]}
        elif self.outcome == "SCHEMA_ERROR":
            body = {**_success_body(self.slot), "content": [{"type": "text", "text": '{"title":"only"}'}]}
        elif self.outcome == "LOCAL_VALIDATION_ERROR":
            body = {**_success_body(self.slot), "content": [{"type": "text", "text": '{"title":"x","narrative":""}'}]}
        else:
            body = _success_body(self.slot)
        return httpx.Response(200, json=body, request=request)


def _secret_store_for(db_path: Path, *, available: bool = True) -> MemorySecretStore:
    db = Database(db_path)
    binding = db.get_role_binding("planning")
    assert binding is not None
    store = MemorySecretStore()
    if available:
        store.set(str(binding["primary_provider_id"]), "offline-placeholder")
    return store


def _real_dispatcher(
    tmp_path: Path,
    handler: CountingHandler,
    *,
    slot: str = "A1",
    secret_available: bool = True,
) -> RealPilotDispatcherV1:
    return RealPilotDispatcherV1(
        repo_root=ROOT,
        route_database=ROOT / "data" / "app.db",
        execution_root=tmp_path / f"real-{slot}",
        offline_dependencies=OfflineDispatchDependenciesV1(
            secret_store=_secret_store_for(ROOT / "data" / "app.db", available=secret_available),
            client_factory=lambda: httpx.AsyncClient(
                timeout=180, transport=httpx.MockTransport(handler),
            ),
        ),
    )


def test_approval_is_decoupled_from_inline_nonce() -> None:
    lock = pilot.load_sealed_pilot(ROOT)["locks"][0]
    approval = pilot.fake_signed_approval(lock)
    assert "nonce" not in approval
    assert approval["nonce_state"] == "NOT_CREATED"
    assert approval["nonce_policy_version"] == NONCE_POLICY_VERSION
    assert approval["real_dispatcher_version"] == REAL_DISPATCHER_VERSION


def test_durable_nonce_restart_consume_and_non_reuse(tmp_path: Path) -> None:
    store_root = tmp_path / "runtime" / "nonces"
    first = DurablePilotNonceStoreV1(repo_root=ROOT, store_root=store_root)
    reserved = first.reserve(**_nonce_bindings())
    assert reserved["state"] == "RESERVED"
    assert first.is_reusable(
        pilot_id=pilot.PILOT_ID, sample_id=SAMPLE_ID, approval_id="approval-one",
    ) is False

    restarted = DurablePilotNonceStoreV1(repo_root=ROOT, store_root=store_root)
    loaded = restarted.load(
        pilot_id=pilot.PILOT_ID, sample_id=SAMPLE_ID, approval_id="approval-one",
    )
    assert loaded == reserved
    restarted.mark_dispatch_attempt(
        pilot_id=pilot.PILOT_ID, sample_id=SAMPLE_ID,
        approval_id="approval-one", nonce_id=reserved["nonce_id"],
    )
    restarted.note_network_attempt(
        pilot_id=pilot.PILOT_ID, sample_id=SAMPLE_ID,
        approval_id="approval-one", nonce_id=reserved["nonce_id"],
    )
    consumed = restarted.consume(
        pilot_id=pilot.PILOT_ID, sample_id=SAMPLE_ID,
        approval_id="approval-one", nonce_id=reserved["nonce_id"],
    )
    assert consumed["state"] == "CONSUMED"
    assert consumed["provider_dispatch_attempts"] == 1
    assert consumed["network_request_attempts"] == 1
    with pytest.raises(SkillV3NonceStoreError, match="NONCE_REUSE"):
        restarted.consume(
            pilot_id=pilot.PILOT_ID, sample_id=SAMPLE_ID,
            approval_id="approval-one", nonce_id=reserved["nonce_id"],
        )


def test_durable_nonce_atomic_duplicate_reservation(tmp_path: Path) -> None:
    store = DurablePilotNonceStoreV1(
        repo_root=ROOT, store_root=tmp_path / "runtime" / "nonces",
    )

    def reserve() -> str:
        try:
            store.reserve(**_nonce_bindings())
            return "RESERVED"
        except SkillV3NonceStoreError as exc:
            return exc.reason_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: reserve(), range(2)))
    assert results.count("RESERVED") == 1
    assert len(results) == 2
    assert set(results) <= {"RESERVED", "NONCE_REUSE", "CONCURRENT_NONCE_RESERVATION"}


def test_nonce_store_rejects_worktree_root() -> None:
    with pytest.raises(SkillV3NonceStoreError, match="NONCE_STORE_INSIDE_GIT_WORKTREE"):
        DurablePilotNonceStoreV1(repo_root=ROOT, store_root=ROOT / ".tmp" / "nonce")


def test_real_dispatcher_route_drift_fails_before_secret_lookup(tmp_path: Path) -> None:
    database = tmp_path / "app.db"
    shutil.copy2(ROOT / "data" / "app.db", database)
    db = Database(database)
    binding = db.get_role_binding("planning")
    assert binding is not None
    provider = db.get_provider(str(binding["primary_provider_id"]))
    assert provider is not None
    db.save_provider(
        provider_id=str(provider["id"]),
        name=str(provider["name"]),
        protocol=str(provider["protocol"]),
        base_url="https://route-drift.example.invalid",
        auth_type=str(provider["auth_type"]),
        timeout_seconds=int(provider["timeout_seconds"]),
        extra_headers=dict(provider.get("extra_headers") or {}),
        enabled=bool(provider["enabled"]),
    )
    handler = CountingHandler()
    with pytest.raises(pilot.PilotBoundaryError, match="WRONG_ROUTE"):
        RealPilotDispatcherV1(
            repo_root=ROOT,
            route_database=database,
            execution_root=tmp_path / "run",
            offline_dependencies=OfflineDispatchDependenciesV1(
                secret_store=MemorySecretStore(),
                client_factory=lambda: httpx.AsyncClient(
                    timeout=180, transport=httpx.MockTransport(handler),
                ),
            ),
        )
    assert handler.count == 0


def test_real_dispatcher_full_offline_path_is_exact_and_single_shot(tmp_path: Path) -> None:
    lock = pilot.load_sealed_pilot(ROOT)["locks"][0]
    handler = CountingHandler()
    dispatcher = _real_dispatcher(tmp_path, handler)
    nonce_store = DurablePilotNonceStoreV1(
        repo_root=ROOT, store_root=tmp_path / "runtime" / "nonces",
    )
    result = asyncio.run(pilot.launch_one_sealed_sample(
        repo_root=ROOT,
        pilot_id=pilot.PILOT_ID,
        sample_id=lock["sample_id"],
        expected_sample_lock_sha256=lock["sample_lock_sha256"],
        expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        permission=pilot.fake_permission(lock),
        signed_approval=pilot.fake_signed_approval(lock),
        nonce_store=nonce_store,
        ledger=pilot.FakePilotLedger(),
        dispatcher=dispatcher,
        output_root=tmp_path / "real-A1" / "output",
        offline_fake=True,
    ))
    assert result["status"] == "SEALED_VALID"
    assert result["attempts"] == {
        "logical_model_call_count": 1,
        "provider_dispatch_attempt_count": 1,
        "http_post_attempt_count": 1,
        "network_request_attempt_count": 1,
    }
    assert handler.count == 1
    assert handler.requests[0]["max_tokens"] == 4624
    assert handler.requests[0]["model"]
    assert handler.requests[0]["stream"] is True
    assert dispatcher.credential_lookup_count == 1
    assert dispatcher.provider_client_creation_count == 1
    record = nonce_store.load(
        pilot_id=pilot.PILOT_ID,
        sample_id=lock["sample_id"],
        approval_id=pilot.fake_signed_approval(lock)["approval_id"],
    )
    assert record["state"] == "CONSUMED"
    assert record["network_request_attempts"] == 1


@pytest.mark.parametrize(
    "outcome",
    ["TIMEOUT", "HTTP_ERROR", "EMPTY_OUTPUT", "PARSE_ERROR", "SCHEMA_ERROR", "LOCAL_VALIDATION_ERROR"],
)
def test_post_dispatch_failures_never_retry_or_reuse_nonce(
    tmp_path: Path, outcome: str,
) -> None:
    lock = pilot.load_sealed_pilot(ROOT)["locks"][0]
    handler = CountingHandler(outcome=outcome)
    dispatcher = _real_dispatcher(tmp_path, handler)
    nonce_store = DurablePilotNonceStoreV1(
        repo_root=ROOT, store_root=tmp_path / "runtime" / "nonces",
    )
    approval = pilot.fake_signed_approval(lock)
    with pytest.raises(pilot.PilotBoundaryError):
        asyncio.run(pilot.launch_one_sealed_sample(
            repo_root=ROOT,
            pilot_id=pilot.PILOT_ID,
            sample_id=lock["sample_id"],
            expected_sample_lock_sha256=lock["sample_lock_sha256"],
            expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
            permission=pilot.fake_permission(lock),
            signed_approval=approval,
            nonce_store=nonce_store,
            ledger=pilot.FakePilotLedger(),
            dispatcher=dispatcher,
            output_root=tmp_path / "real-A1" / "output",
            offline_fake=True,
        ))
    assert handler.count <= 1
    record = nonce_store.load(
        pilot_id=pilot.PILOT_ID,
        sample_id=lock["sample_id"],
        approval_id=approval["approval_id"],
    )
    assert record["state"] == "INVALIDATED_FAILED_DISPATCH"
    assert nonce_store.is_reusable(
        pilot_id=pilot.PILOT_ID,
        sample_id=lock["sample_id"],
        approval_id=approval["approval_id"],
    ) is False


def test_missing_credentials_is_after_nonce_and_before_network(tmp_path: Path) -> None:
    lock = pilot.load_sealed_pilot(ROOT)["locks"][0]
    handler = CountingHandler()
    dispatcher = _real_dispatcher(tmp_path, handler, secret_available=False)
    nonce_store = DurablePilotNonceStoreV1(
        repo_root=ROOT, store_root=tmp_path / "runtime" / "nonces",
    )
    with pytest.raises(pilot.PilotBoundaryError, match="PROVIDER_BOUNDARY_FAILED"):
        asyncio.run(pilot.launch_one_sealed_sample(
            repo_root=ROOT,
            pilot_id=pilot.PILOT_ID,
            sample_id=lock["sample_id"],
            expected_sample_lock_sha256=lock["sample_lock_sha256"],
            expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
            permission=pilot.fake_permission(lock),
            signed_approval=pilot.fake_signed_approval(lock),
            nonce_store=nonce_store,
            ledger=pilot.FakePilotLedger(),
            dispatcher=dispatcher,
            output_root=tmp_path / "real-A1" / "output",
            offline_fake=True,
        ))
    assert dispatcher.credential_lookup_count == 1
    assert dispatcher.provider_client_creation_count == 0
    assert handler.count == 0


def test_six_samples_cross_real_dispatcher_code_path_offline(tmp_path: Path) -> None:
    sealed = pilot.load_sealed_pilot(ROOT)
    ledger = pilot.FakePilotLedger()
    nonce_store = DurablePilotNonceStoreV1(
        repo_root=ROOT, store_root=tmp_path / "runtime" / "nonces",
    )
    rows = []
    total_outbound = 0
    for lock in sealed["locks"]:
        handler = CountingHandler(slot=lock["sample_slot"])
        dispatcher = _real_dispatcher(tmp_path, handler, slot=lock["sample_slot"])
        rows.append(asyncio.run(pilot.launch_one_sealed_sample(
            repo_root=ROOT,
            pilot_id=pilot.PILOT_ID,
            sample_id=lock["sample_id"],
            expected_sample_lock_sha256=lock["sample_lock_sha256"],
            expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
            permission=pilot.fake_permission(lock),
            signed_approval=pilot.fake_signed_approval(lock),
            nonce_store=nonce_store,
            ledger=ledger,
            dispatcher=dispatcher,
            output_root=tmp_path / f"real-{lock['sample_slot']}" / "output",
            offline_fake=True,
        )))
        total_outbound += handler.count
    assert [row["sample_slot"] for row in rows] == list(pilot.SEQUENCE)
    assert all(row["status"] == "SEALED_VALID" for row in rows)
    assert total_outbound == 6


def test_same_approval_cannot_launch_twice_after_dispatch(tmp_path: Path) -> None:
    lock = pilot.load_sealed_pilot(ROOT)["locks"][0]
    approval = pilot.fake_signed_approval(lock)
    nonce_store = DurablePilotNonceStoreV1(
        repo_root=ROOT, store_root=tmp_path / "runtime" / "nonces",
    )
    first_handler = CountingHandler()
    asyncio.run(pilot.launch_one_sealed_sample(
        repo_root=ROOT,
        pilot_id=pilot.PILOT_ID,
        sample_id=lock["sample_id"],
        expected_sample_lock_sha256=lock["sample_lock_sha256"],
        expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        permission=pilot.fake_permission(lock),
        signed_approval=approval,
        nonce_store=nonce_store,
        ledger=pilot.FakePilotLedger(),
        dispatcher=_real_dispatcher(tmp_path, first_handler, slot="first"),
        output_root=tmp_path / "real-first" / "output",
        offline_fake=True,
    ))
    second_handler = CountingHandler()
    with pytest.raises(SkillV3NonceStoreError, match="NONCE_REUSE"):
        asyncio.run(pilot.launch_one_sealed_sample(
            repo_root=ROOT,
            pilot_id=pilot.PILOT_ID,
            sample_id=lock["sample_id"],
            expected_sample_lock_sha256=lock["sample_lock_sha256"],
            expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
            permission=pilot.fake_permission(lock),
            signed_approval=approval,
            nonce_store=nonce_store,
            ledger=pilot.FakePilotLedger(),
            dispatcher=_real_dispatcher(tmp_path, second_handler, slot="second"),
            output_root=tmp_path / "real-second" / "output",
            offline_fake=True,
        ))
    assert first_handler.count == 1
    assert second_handler.count == 0


def test_concurrent_double_launch_has_at_most_one_outbound(tmp_path: Path) -> None:
    lock = pilot.load_sealed_pilot(ROOT)["locks"][0]
    approval = pilot.fake_signed_approval(lock)
    store_root = tmp_path / "runtime" / "nonces"
    handlers = [CountingHandler(), CountingHandler()]

    async def launch(index: int):
        return await pilot.launch_one_sealed_sample(
            repo_root=ROOT,
            pilot_id=pilot.PILOT_ID,
            sample_id=lock["sample_id"],
            expected_sample_lock_sha256=lock["sample_lock_sha256"],
            expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
            permission=pilot.fake_permission(lock),
            signed_approval=approval,
            nonce_store=DurablePilotNonceStoreV1(repo_root=ROOT, store_root=store_root),
            ledger=pilot.FakePilotLedger(),
            dispatcher=_real_dispatcher(tmp_path, handlers[index], slot=f"race-{index}"),
            output_root=tmp_path / f"real-race-{index}" / "output",
            offline_fake=True,
        )

    async def run_both():
        return await asyncio.gather(launch(0), launch(1), return_exceptions=True)

    results = asyncio.run(run_both())
    assert sum(handler.count for handler in handlers) <= 1
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, BaseException) for result in results) == 1


def test_v2_approval_binds_wire_nonce_policy_and_dispatcher_without_nonce(
    tmp_path: Path,
) -> None:
    repo, head = _clean_repo(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "approval_id": "real-boundary-approval",
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
    }
    signed = approvals.create_successor_signed_approval_v2(
        repo_root=repo,
        store_root=tmp_path / "runtime" / "approvals",
        payload=payload,
        now=now,
    )
    assert signed["nonce_state"] == "NOT_CREATED"
    assert "nonce" not in signed
    assert signed["wire_input_sha256"] == "6" * 64
    assert signed["nonce_policy_version"] == NONCE_POLICY_VERSION
    assert signed["real_dispatcher_version"] == REAL_DISPATCHER_VERSION


def test_canonical_factory_is_metadata_only_and_not_normal_app_wired() -> None:
    environment = canonical_real_execution_environment_v1(ROOT)
    assert environment.route_database == ROOT / "data" / "app.db"
    assert not environment.nonce_store_root.is_relative_to(ROOT)
    assert not environment.approval_store_root.is_relative_to(ROOT)
    symbol = "skill_v3_real_execution_boundary"
    for relative in (
        "src/novel_flywheel/app.py",
        "src/novel_flywheel/workflows.py",
        "src/novel_flywheel/api.py",
    ):
        path = ROOT / relative
        if path.is_file():
            assert symbol not in path.read_text(encoding="utf-8")


def test_ordinary_registry_default_has_no_attempt_observer() -> None:
    source = (ROOT / "src/novel_flywheel/providers/registry.py").read_text(encoding="utf-8")
    assert "attempt_observer: SingleDispatchAttemptObserver | None = None" in source
    assert "self.attempt_observer = attempt_observer" in source
