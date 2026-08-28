from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from tools.canary import skill_v3_character_heavy_pilot as prior
from tools.canary import skill_v3_hybrid_character_heavy_pilot as hybrid
from tools.canary import skill_v3_pilot_approval_store as selective
from tools.canary.skill_v3_hybrid_campaign import (
    HybridApprovalBoundNonceAdapter,
    execute_one_hybrid_sealed_sample,
)
from tools.canary.skill_v3_hybrid_jit_approval import (
    DurableHybridApprovalStoreV1,
    HybridJitApprovalError,
    ZERO_ATTEMPT_COUNTERS,
    campaign_permission_body_from_sealed,
    create_one_hybrid_sample_jit_approval,
    seal_approval_v1,
    seal_campaign_permission_v1,
    validate_approval_domain_v1,
    validate_approval_schema_v1,
    validate_campaign_permission_v1,
)


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _permission(*, now: datetime = NOW) -> dict:
    head = _git("rev-parse", "HEAD")
    body = campaign_permission_body_from_sealed(
        repo_root=ROOT, permission_id="offline-hybrid-permission-v1",
        repository_head=head, authorization_text_sha256="a" * 64,
        authorization_context_identity_sha256="b" * 64,
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=10), offline_test_only=True,
    )
    return seal_campaign_permission_v1(body)


def _git(*args: str) -> str:
    import subprocess
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True,
        text=True, encoding="utf-8",
    ).stdout.strip()


def _create(
    tmp_path: Path, index: int = 0, *, permission: dict | None = None,
) -> tuple[dict, DurableHybridApprovalStoreV1, list[str]]:
    sealed = hybrid.load_sealed_pilot(ROOT)
    completed = [row["SAMPLE_ID"] for row in sealed["samples"][:index]]
    sample_id = sealed["samples"][index]["SAMPLE_ID"]
    store = DurableHybridApprovalStoreV1(
        repo_root=ROOT, store_root=tmp_path / f"approvals-{index}",
    )
    value = create_one_hybrid_sample_jit_approval(
        repo_root=ROOT, store=store, permission=permission or _permission(),
        sample_id=sample_id, completed_sample_ids=completed,
        approval_id=f"offline-hybrid-approval-{index}", now=NOW,
        attempt_counters=ZERO_ATTEMPT_COUNTERS, nonce_preexists=False,
        expires_at=NOW + timedelta(hours=2), offline_test=True,
    )
    return value, store, completed


def _resign_approval(value: dict, field: str, replacement: object) -> dict:
    body = deepcopy(value)
    body.pop("signed_approval_sha256")
    body[field] = replacement
    return seal_approval_v1(body)


def _resign_permission(value: dict, field: str, replacement: object) -> dict:
    body = deepcopy(value)
    body.pop("campaign_permission_sha256")
    body.pop("permission_scope_sha256")
    body[field] = replacement
    return seal_campaign_permission_v1(body)


def test_permission_and_approval_schema_are_closed_and_domain_separated(
    tmp_path: Path,
) -> None:
    permission = _permission()
    assert validate_campaign_permission_v1(
        permission, repo_root=ROOT, now=NOW, require_executable=False,
    ) == permission
    approval, _store, completed = _create(tmp_path, permission=permission)
    assert approval["schema"] == "SkillV3HybridSampleJitSignedApprovalV1"
    assert approval["execution_authorized"] is False
    assert approval["offline_test_only"] is True
    assert approval["nonce_state"] == "NOT_CREATED"
    assert approval["usage_state"] == "UNUSED"
    assert validate_approval_domain_v1(
        approval, repo_root=ROOT, permission=permission,
        completed_sample_ids=completed, now=NOW, require_executable=False,
        attempt_counters=ZERO_ATTEMPT_COUNTERS, nonce_preexists=False,
    ) == approval
    extra = {**approval, "unexpected": True}
    with pytest.raises(HybridJitApprovalError, match="SIGNED_APPROVAL_FIELDS_UNEXPECTED"):
        validate_approval_schema_v1(extra, now=NOW)


@pytest.mark.parametrize("index", range(6))
@pytest.mark.asyncio
async def test_all_six_hybrid_roles_follow_production_shaped_boundary(
    tmp_path: Path, index: int,
) -> None:
    sealed = hybrid.load_sealed_pilot(ROOT)
    completed = [row["SAMPLE_ID"] for row in sealed["samples"][:index]]
    ledger = hybrid.HybridPilotLedger(sample_states={
        row["SAMPLE_ID"]: f"{row['SAMPLE_SLOT']}:SEALED_VALID"
        for row in sealed["samples"][:index]
    })
    store = DurableHybridApprovalStoreV1(
        repo_root=ROOT, store_root=tmp_path / f"approval-{index}",
    )
    nonce_store = prior.FakeNonceStore()
    row = sealed["samples"][index]
    result = await execute_one_hybrid_sealed_sample(
        repo_root=ROOT, permission=_permission(), sample_id=row["SAMPLE_ID"],
        completed_sample_ids=completed, approval_store=store,
        approval_id=f"offline-role-{index}", approval_created_at=NOW,
        approval_expires_at=NOW + timedelta(hours=2),
        attempt_counters=ZERO_ATTEMPT_COUNTERS,
        nonce_store=nonce_store, ledger=ledger,
        dispatcher=hybrid.HybridFakeDispatcher(ROOT),
        output_root=tmp_path / f"output-{index}", offline_test=True,
    )
    assert result["status"] == "SEALED_VALID"
    assert result["approval_lifecycle"] == "CONSUMED"
    assert result["real_boundary_reached"] == 0
    assert nonce_store.reservation_count == 1
    with pytest.raises(HybridJitApprovalError, match="APPROVAL_REUSE"):
        store.load(f"offline-role-{index}", now=NOW)


def test_durable_lifecycle_is_single_use_restart_safe_and_tamper_evident(
    tmp_path: Path,
) -> None:
    approval, store, _completed = _create(tmp_path)
    restarted = DurableHybridApprovalStoreV1(
        repo_root=ROOT, store_root=store.store_root,
    )
    assert restarted.load(approval["approval_id"], now=NOW)["approval"] == approval
    receipt = restarted.consume(
        approval["approval_id"], execution_receipt_sha256="c" * 64,
    )
    assert receipt["usage_state"] == "CONSUMED"
    with pytest.raises(HybridJitApprovalError, match="APPROVAL_REUSE"):
        restarted.consume(approval["approval_id"], execution_receipt_sha256="d" * 64)
    approval_path = next(store.store_root.glob("*.approval.json"))
    tampered = json.loads(approval_path.read_text(encoding="utf-8"))
    tampered["sample_id"] = "tampered"
    approval_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(HybridJitApprovalError):
        validate_approval_schema_v1(tampered, now=NOW)


def test_duplicate_active_approval_for_same_sample_is_rejected(tmp_path: Path) -> None:
    _approval, store, _completed = _create(tmp_path)
    sealed = hybrid.load_sealed_pilot(ROOT)
    with pytest.raises(HybridJitApprovalError, match="ACTIVE_APPROVAL_ALREADY_EXISTS"):
        create_one_hybrid_sample_jit_approval(
            repo_root=ROOT, store=store, permission=_permission(),
            sample_id=sealed["samples"][0]["SAMPLE_ID"],
            completed_sample_ids=[], approval_id="second-active-identity",
            attempt_counters=ZERO_ATTEMPT_COUNTERS, nonce_preexists=False,
            now=NOW, expires_at=NOW + timedelta(hours=1), offline_test=True,
        )


def test_expired_approval_becomes_permanently_expired(tmp_path: Path) -> None:
    approval, store, _completed = _create(tmp_path)
    with pytest.raises(HybridJitApprovalError, match="APPROVAL_EXPIRED"):
        store.load(approval["approval_id"], now=NOW + timedelta(hours=3))
    state = json.loads(next(store.store_root.glob("*.state.json")).read_text(encoding="utf-8"))
    assert state["usage_state"] == "EXPIRED"
    with pytest.raises(HybridJitApprovalError, match="APPROVAL_REUSE"):
        store.load(approval["approval_id"], now=NOW)


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        ("pilot_id", "wrong-pilot", "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("experiment_lock_sha256", "1" * 64, "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("sample_id", "sv3hs-wrong", "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("sample_lock_sha256", "2" * 64, "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("current_execution_head", "1" * 40, "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("expected_branch", "wrong", "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("model_input_component_sha256", "3" * 64, "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("non_skill_identity_sha256", "4" * 64, "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("reference_guidance_sha256", "5" * 64, "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("skill_context_sha256", "6" * 64, "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("route_fingerprint", "7" * 64, "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("sampling_fingerprint", "9" * 64, "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("validator_fingerprint", "a" * 64, "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("destination_origin", "https://example.invalid", "DESTINATION_DRIFT"),
        ("egress_policy_sha256", "8" * 64, "APPROVAL_DOMAIN_BINDING_MISMATCH"),
        ("output_token_hard_cap", 4623, "WRONG_OUTPUT_CAP"),
        ("sample_slot", "B1", "APPROVAL_FOR_WRONG_SAMPLE"),
    ],
)
def test_hash_bound_negative_injections_fail_closed(
    tmp_path: Path, field: str, replacement: object, reason: str,
) -> None:
    approval, _store, completed = _create(tmp_path)
    changed = _resign_approval(approval, field, replacement)
    with pytest.raises(HybridJitApprovalError, match=reason) as caught:
        validate_approval_domain_v1(
            changed, repo_root=ROOT, permission=_permission(),
            completed_sample_ids=completed, now=NOW, require_executable=False,
            attempt_counters=ZERO_ATTEMPT_COUNTERS, nonce_preexists=False,
        )
    assert caught.value.failure_receipt["external_action_count"] == 0
    assert caught.value.failure_receipt["raw_content_included"] is False


def test_permission_negative_injections_and_later_sample_precreation(
    tmp_path: Path,
) -> None:
    for field, replacement in (
        ("pilot_id", "wrong"),
        ("experiment_lock_sha256", "1" * 64),
        ("repository_head", "2" * 40),
        ("repository_branch", "wrong"),
        ("model", "wrong"),
        ("route_fingerprint", "3" * 64),
        ("destination_hostname", "example.invalid"),
        ("egress_policy_sha256s", ["4" * 64] * 6),
        ("active", False),
    ):
        with pytest.raises(HybridJitApprovalError):
            validate_campaign_permission_v1(
                _resign_permission(_permission(), field, replacement),
                repo_root=ROOT, now=NOW, require_executable=False,
            )
    sealed = hybrid.load_sealed_pilot(ROOT)
    store = DurableHybridApprovalStoreV1(
        repo_root=ROOT, store_root=tmp_path / "later",
    )
    with pytest.raises(
        HybridJitApprovalError,
        match="LATER_SAMPLE_APPROVAL_PRECREATION_FORBIDDEN",
    ):
        create_one_hybrid_sample_jit_approval(
            repo_root=ROOT, store=store, permission=_permission(),
            sample_id=sealed["samples"][1]["SAMPLE_ID"], completed_sample_ids=[],
            approval_id="later-sample", now=NOW,
            attempt_counters=ZERO_ATTEMPT_COUNTERS, nonce_preexists=False,
            expires_at=NOW + timedelta(hours=1), offline_test=True,
        )
    assert not list(store.store_root.glob("*.approval.json"))
    assert not list(store.store_root.glob("*.nonce.json"))


def test_executable_permission_requires_clean_worktree() -> None:
    permission = _permission()
    body = dict(permission)
    body.pop("campaign_permission_sha256")
    body.pop("permission_scope_sha256")
    body["execution_authorized"] = True
    body["offline_test_only"] = False
    executable = seal_campaign_permission_v1(body)
    marker = ROOT / "hybrid-jit-dirty-worktree-probe.tmp"
    marker.write_text("offline test marker\n", encoding="utf-8")
    try:
        with pytest.raises(HybridJitApprovalError, match="WORKTREE_POLICY_VIOLATION"):
            validate_campaign_permission_v1(
                executable, repo_root=ROOT, now=NOW,
                require_executable=True,
            )
    finally:
        marker.unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("attempts", "nonce_preexists", "reason"),
    [
        (
            {**ZERO_ATTEMPT_COUNTERS, "provider_request_attempt_count": 1},
            False,
            "ATTEMPT_COUNTER_ALREADY_NONZERO",
        ),
        (ZERO_ATTEMPT_COUNTERS, True, "NONCE_EXISTS_BEFORE_APPROVAL"),
    ],
)
def test_attempt_or_nonce_state_blocks_approval_before_store_write(
    tmp_path: Path, attempts: dict, nonce_preexists: bool, reason: str,
) -> None:
    sealed = hybrid.load_sealed_pilot(ROOT)
    store = DurableHybridApprovalStoreV1(
        repo_root=ROOT, store_root=tmp_path / reason,
    )
    with pytest.raises(HybridJitApprovalError, match=reason):
        create_one_hybrid_sample_jit_approval(
            repo_root=ROOT, store=store, permission=_permission(),
            sample_id=sealed["samples"][0]["SAMPLE_ID"], completed_sample_ids=[],
            approval_id="blocked-before-write", attempt_counters=attempts,
            nonce_preexists=nonce_preexists, now=NOW,
            expires_at=NOW + timedelta(hours=1), offline_test=True,
        )
    assert not list(store.store_root.glob("*.approval.json"))


def test_signature_malformed_and_old_namespace_crossing_fail_closed(
    tmp_path: Path,
) -> None:
    approval, _store, _completed = _create(tmp_path)
    bad_signature = {**approval, "signed_approval_sha256": "f" * 64}
    with pytest.raises(HybridJitApprovalError, match="SIGNED_APPROVAL_SHA256_MISMATCH"):
        validate_approval_schema_v1(bad_signature, now=NOW)
    malformed = dict(approval)
    malformed.pop("wire_input_sha256")
    with pytest.raises(HybridJitApprovalError, match="SIGNED_APPROVAL_FIELDS_UNEXPECTED"):
        validate_approval_schema_v1(malformed, now=NOW)
    with pytest.raises(selective.SkillV3ApprovalStoreError, match="SIGNED_APPROVAL_SCHEMA_MISMATCH"):
        selective.validate_remaining_campaign_signed_approval_v4(
            approval, expected=approval, now=NOW,
        )


def test_nonce_cannot_be_reached_after_invalid_approval(tmp_path: Path) -> None:
    sealed = hybrid.load_sealed_pilot(ROOT)

    class CountingNonceStore(prior.FakeNonceStore):
        pass

    nonce = CountingNonceStore()
    permission = _resign_permission(_permission(), "pilot_id", "wrong")
    with pytest.raises(HybridJitApprovalError, match="WRONG_PILOT"):
        import asyncio
        asyncio.run(execute_one_hybrid_sealed_sample(
            repo_root=ROOT, permission=permission,
            sample_id=sealed["samples"][0]["SAMPLE_ID"],
            completed_sample_ids=[],
            approval_store=DurableHybridApprovalStoreV1(
                repo_root=ROOT, store_root=tmp_path / "ordering",
            ),
            approval_id="never-created", approval_created_at=NOW,
            approval_expires_at=NOW + timedelta(hours=1), nonce_store=nonce,
            attempt_counters=ZERO_ATTEMPT_COUNTERS,
            ledger=hybrid.HybridPilotLedger(),
            dispatcher=hybrid.HybridFakeDispatcher(ROOT),
            output_root=tmp_path / "never-output", offline_test=True,
        ))
    assert nonce.reservation_count == 0


def test_real_nonce_adapter_binds_exact_destination_and_approval(tmp_path: Path) -> None:
    approval, _store, _completed = _create(tmp_path)

    class Delegate:
        def __init__(self) -> None:
            self.received: dict | None = None

        def reserve_destination_bound_v2(self, **bindings: object) -> dict:
            self.received = dict(bindings)
            return {"nonce_id": "offline-capture"}

    delegate = Delegate()
    adapter = HybridApprovalBoundNonceAdapter(
        delegate=delegate, approval=approval,
    )
    adapter.reserve(
        pilot_id=approval["pilot_id"], sample_id=approval["sample_id"],
        sample_lock_sha256=approval["sample_lock_sha256"],
        parent_experiment_lock_sha256=approval["experiment_lock_sha256"],
        execution_head=approval["current_execution_head"],
        approval_id=approval["approval_id"],
        signed_approval_sha256=approval["signed_approval_sha256"],
        model_input_component_binding_sha256=approval["model_input_component_sha256"],
        route_fingerprint=approval["route_fingerprint"],
    )
    assert delegate.received is not None
    assert delegate.received["approved_destination_origin"] == "https://lingsuan.org"
    assert delegate.received["approved_destination_path_or_prefix"] == "/v1/messages"
    assert delegate.received["cross_origin_redirect_allowed"] is False
    assert delegate.received["unbound_proxy_route_allowed"] is False
    with pytest.raises(HybridJitApprovalError, match="NONCE_APPROVAL_BINDING_MISMATCH"):
        adapter.reserve(signed_approval_sha256="f" * 64)


def test_hybrid_boundary_source_has_no_silent_failure_or_external_capability() -> None:
    approval_source = Path(
        "tools/canary/skill_v3_hybrid_jit_approval.py"
    ).read_text(encoding="utf-8")
    runner_source = Path(
        "tools/canary/skill_v3_hybrid_campaign.py"
    ).read_text(encoding="utf-8")
    combined = approval_source + runner_source
    assert "except Exception: pass" not in combined
    assert "requests." not in combined
    assert "httpx." not in combined
    assert "credential" not in approval_source.lower()
    assert "SkillV3RemainingCampaignJitSignedApprovalV4" not in combined
