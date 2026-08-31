import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from tools.canary.approval_closure import validate_c0b_approval_closure
from tools.canary.approval_store import ApprovalConsumptionStore, CanaryApprovalReplay
from tools.canary.contracts import (
    CanaryContractError,
    build_canary_plan_approval_v1,
    build_c0b_smoke_1_user_authorization_patch_v2,
    build_c0b_smoke_1_signed_approval_v1,
    materialize_signed_smoke_approval_v1,
    validate_c0b_smoke_1_signed_approval_v1,
    validate_signed_smoke_approval_sources_v1,
)
from tools.canary.final_approval import materialize_c0b_smoke_1_final_approval_v2
from tools.canary.launcher import CanaryLauncherError, validate_packet
from tools.canary.real_boundary import FinalAuthorizationLatch, GuardedProductionGateway
from tools.canary.real_run import validate_c0b_real_run_approval


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "canary" / "short-normal-v1.json"
LIVE_DB = ROOT / "data" / "app.db"
LIVE_PROJECTS = ROOT / "data" / "projects"
MATERIALIZED_AT = datetime(2026, 8, 15, 4, 30, tzinfo=timezone.utc)
SIGNED_AT = datetime(2026, 8, 15, 5, 0, tzinfo=timezone.utc)


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


@pytest.fixture()
def signed_packet(tmp_path: Path):
    materialized = materialize_c0b_smoke_1_final_approval_v2(
        live_database_path=LIVE_DB,
        live_project_root=LIVE_PROJECTS,
        fixture_path=FIXTURE,
        output_root=tmp_path / "outputs",
        cohort_id="c0b-p12-signed-approval-test",
        run_namespace="c0b-p12-signed-approval-test",
        artifact_root_label="docs/superpowers/reports",
        now=MATERIALIZED_AT,
    )
    candidate = materialized["approval_candidate"]
    template = materialized["user_authorization_patch"]
    patch_payload = {
        key: deepcopy(value) for key, value in template.items()
        if key not in {
            "schema", "version", "canonicalization_version",
            "authorization_patch_sha256",
        }
    }
    patch_payload.update({
        "named_approver": "p12-test-approver",
        "approval_timestamp": "2026-08-15T05:00:00Z",
    })
    patch = build_c0b_smoke_1_user_authorization_patch_v2(
        patch_payload, require_confirmation=True,
    )
    signed = materialize_signed_smoke_approval_v1(
        candidate, patch, now=SIGNED_AT,
    )
    paths = materialized["paths"]
    signed_path = tmp_path / "signed-approval.json"
    patch_path = tmp_path / "confirmed-patch.json"
    _write(signed_path, signed)
    _write(patch_path, patch)
    ledger = tmp_path / "approval-ledger"
    ledger.mkdir()
    return {
        **materialized, "candidate": candidate, "patch": patch,
        "signed": signed, "signed_path": signed_path,
        "patch_path": patch_path, "ledger": ledger,
        "candidate_path": paths["approval_candidate"],
    }


def _signed_payload(value: dict) -> dict:
    return {
        key: deepcopy(item) for key, item in value.items()
        if key not in {
            "schema", "version", "canonicalization_version",
            "signed_approval_sha256",
        }
    }


def test_candidate_and_patch_remain_non_executable(signed_packet) -> None:
    plan = signed_packet["plan"]
    assert signed_packet["index"]["contract_status"] == (
        "C0B_SMOKE_1_SIGNED_APPROVAL_CONTRACT_READY"
    )
    assert signed_packet["index"]["status"] == (
        "C0B_SMOKE_1_WAITING_FOR_NEW_FINAL_USER_AUTHORIZATION"
    )
    with pytest.raises(CanaryLauncherError, match="approval_candidate_not_executable"):
        validate_packet(
            plan_path=signed_packet["paths"]["plan"],
            approval_path=signed_packet["candidate_path"],
            cli_approved_plan_sha256=plan["plan_sha256"],
            execution_requested=True,
            now=SIGNED_AT,
        )
    with pytest.raises(CanaryLauncherError, match="authorization_patch_not_executable"):
        validate_packet(
            plan_path=signed_packet["paths"]["plan"],
            approval_path=signed_packet["patch_path"],
            cli_approved_plan_sha256=plan["plan_sha256"],
            execution_requested=True,
            now=SIGNED_AT,
        )


def test_valid_candidate_and_patch_materialize_exact_signed_approval(signed_packet) -> None:
    signed = signed_packet["signed"]
    assert signed["schema"] == "C0BSmoke1SignedApprovalV1"
    assert signed["approval_scope"] == "C0B_REAL_PROVIDER_PATH_REACHABILITY_SMOKE_1"
    assert signed["approval_method"] == "manual_user_confirmation"
    assert signed["source_candidate_sha256"] == signed_packet["candidate"][
        "approval_candidate_sha256"
    ]
    assert signed["source_authorization_patch_sha256"] == signed_packet["patch"][
        "authorization_patch_sha256"
    ]
    assert signed["execution_authorized"] is True
    assert all(signed[name] is True for name in (
        "authorize_credential_lookup", "authorize_provider_client_creation",
        "authorize_network", "authorize_paid_model_calls",
    ))
    assert validate_signed_smoke_approval_sources_v1(
        signed, signed_packet["candidate"], signed_packet["patch"], now=SIGNED_AT,
    )["signed_approval_sha256"] == signed["signed_approval_sha256"]


def test_signed_approval_validate_only_closure_is_exact_and_inert(signed_packet) -> None:
    receipt = validate_c0b_approval_closure(
        plan_path=signed_packet["paths"]["plan"],
        approval_path=signed_packet["signed_path"],
        source_candidate_path=signed_packet["candidate_path"],
        source_authorization_patch_path=signed_packet["patch_path"],
        packet_path=signed_packet["paths"]["packet"],
        workload_fixture_path=FIXTURE,
        live_database_path=LIVE_DB,
        live_project_root=LIVE_PROJECTS,
        canary_root=signed_packet["paths"]["index"].parent / "future-canary",
        approval_ledger_root=signed_packet["ledger"],
        cli_approved_plan_sha256=signed_packet["plan"]["plan_sha256"],
        now=SIGNED_AT,
    )
    assert receipt["overall_status"] == "exact", receipt
    assert receipt["approval_document_kind"] == "signed_smoke_approval"
    assert receipt["approval_state"] == "signed_approval_exact_and_executable"
    assert set(receipt["external_action_counters"].values()) == {0}
    assert len(receipt["ordered_checks"]) > 25


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("named_approver", "", "signed_approval_named_approver_invalid"),
    ("named_approver", "USER_CONFIRMATION_REQUIRED", "signed_approval_named_approver_invalid"),
    ("approval_timestamp", "not-utc", "approval_timestamp_invalid"),
    ("approval_scope", "C0B_REAL_PROVIDER_PATH_REACHABILITY", "approval_scope_mismatch"),
])
def test_signed_approval_rejects_invalid_authority_fields(
    signed_packet, field, value, reason,
) -> None:
    payload = _signed_payload(signed_packet["signed"])
    payload[field] = value
    with pytest.raises(CanaryContractError, match=reason):
        build_c0b_smoke_1_signed_approval_v1(payload, now=SIGNED_AT)


def test_signed_approval_expires_and_old_scope_cannot_use_new_schema(signed_packet) -> None:
    with pytest.raises(CanaryContractError, match="approval_expired"):
        validate_c0b_smoke_1_signed_approval_v1(
            signed_packet["signed"],
            now=datetime(2026, 8, 17, 5, 0, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize("field", [
    "approved_plan_sha256", "approved_launcher_sha256",
    "approved_workload_sha256", "approved_build_fingerprint",
    "approved_execution_config_fingerprint",
    "approved_runtime_execution_fingerprint", "provider_descriptor_hash",
    "model_role_binding_manifest_hash", "pricing_evidence_manifest_hash",
    "stop_condition_manifest_hash", "call_budget_definition_sha256",
    "token_budget_definition_sha256", "monetary_budget_definition_sha256",
    "elapsed_budget_definition_sha256", "single_use_cohort_id",
])
def test_signed_source_validation_rejects_protected_field_mutation(
    signed_packet, field,
) -> None:
    payload = _signed_payload(signed_packet["signed"])
    payload[field] = "f" * 64 if field != "single_use_cohort_id" else "different-cohort"
    changed = build_c0b_smoke_1_signed_approval_v1(
        payload, now=SIGNED_AT, validate_source_independent=True,
    )
    with pytest.raises(CanaryContractError, match="signed_approval_protected_fields_mismatch"):
        validate_signed_smoke_approval_sources_v1(
            changed, signed_packet["candidate"], signed_packet["patch"],
            now=SIGNED_AT,
        )


def test_candidate_and_patch_hash_mismatch_are_rejected(signed_packet) -> None:
    candidate = deepcopy(signed_packet["candidate"])
    candidate["approval_candidate_sha256"] = "f" * 64
    with pytest.raises(CanaryContractError, match="approval_candidate_hash_mismatch"):
        validate_signed_smoke_approval_sources_v1(
            signed_packet["signed"], candidate, signed_packet["patch"], now=SIGNED_AT,
        )
    patch = deepcopy(signed_packet["patch"])
    patch["authorization_patch_sha256"] = "e" * 64
    with pytest.raises(CanaryContractError, match="authorization_patch_hash_mismatch"):
        validate_signed_smoke_approval_sources_v1(
            signed_packet["signed"], signed_packet["candidate"], patch, now=SIGNED_AT,
        )


def test_patch_protected_field_is_rejected_and_sources_are_not_overwritten(signed_packet) -> None:
    candidate_before = json.dumps(signed_packet["candidate"], sort_keys=True)
    patch_before = json.dumps(signed_packet["patch"], sort_keys=True)
    payload = {
        key: deepcopy(value) for key, value in signed_packet["patch"].items()
        if key not in {
            "schema", "version", "canonicalization_version",
            "authorization_patch_sha256",
        }
    }
    payload["route"] = "forbidden"
    with pytest.raises(CanaryContractError, match="authorization_patch_fields_unexpected"):
        build_c0b_smoke_1_user_authorization_patch_v2(payload)
    assert json.dumps(signed_packet["candidate"], sort_keys=True) == candidate_before
    assert json.dumps(signed_packet["patch"], sort_keys=True) == patch_before


def test_signed_approval_ledger_identity_replay_and_consumption(signed_packet) -> None:
    store = ApprovalConsumptionStore(signed_packet["ledger"])
    reservation = store.reserve(signed_packet["signed"])
    assert reservation["payload"]["signed_approval_sha256"] == signed_packet["signed"][
        "signed_approval_sha256"
    ]
    with pytest.raises(CanaryApprovalReplay, match="approval_already_reserved"):
        store.reserve(signed_packet["signed"])
    second_payload = _signed_payload(signed_packet["signed"])
    second_payload["approval_timestamp"] = "2026-08-15T05:01:00Z"
    second = build_c0b_smoke_1_signed_approval_v1(second_payload, now=SIGNED_AT)
    with pytest.raises(CanaryApprovalReplay, match="approval_already_reserved"):
        store.reserve(second)
    consumed = store.consume(signed_packet["signed"], "a" * 64)
    assert consumed["payload"]["consumed_evidence_sha256"] == "a" * 64
    assert signed_packet["candidate"]["usage_status"] == "unused"
    assert signed_packet["patch"].get("usage_status") is None


def test_candidate_and_patch_cannot_be_reserved(signed_packet) -> None:
    store = ApprovalConsumptionStore(signed_packet["ledger"])
    with pytest.raises(CanaryApprovalReplay, match="approval_candidate_not_executable"):
        store.reserve(signed_packet["candidate"])
    with pytest.raises(CanaryApprovalReplay, match="authorization_patch_not_executable"):
        store.reserve(signed_packet["patch"])


def test_signed_approval_hash_mutation_is_rejected(signed_packet) -> None:
    changed = deepcopy(signed_packet["signed"])
    changed["signed_approval_sha256"] = "f" * 64
    with pytest.raises(CanaryContractError, match="signed_approval_hash_mismatch"):
        validate_c0b_smoke_1_signed_approval_v1(changed, now=SIGNED_AT)


def test_signed_launcher_requires_both_source_documents(signed_packet) -> None:
    with pytest.raises(CanaryLauncherError, match="signed_approval_source_document_missing"):
        validate_packet(
            plan_path=signed_packet["paths"]["plan"],
            approval_path=signed_packet["signed_path"],
            cli_approved_plan_sha256=signed_packet["plan"]["plan_sha256"],
            execution_requested=True,
            now=SIGNED_AT,
        )


def test_signed_approval_timestamp_before_window_is_rejected(signed_packet) -> None:
    payload = _signed_payload(signed_packet["signed"])
    payload["approval_timestamp"] = "2026-08-15T04:31:00Z"
    with pytest.raises(
        CanaryContractError, match="approval_timestamp_outside_execution_window",
    ):
        build_c0b_smoke_1_signed_approval_v1(payload, now=SIGNED_AT)


def test_patch_cohort_mismatch_cannot_materialize_signed_approval(signed_packet) -> None:
    payload = {
        key: deepcopy(value) for key, value in signed_packet["patch"].items()
        if key not in {
            "schema", "version", "canonicalization_version",
            "authorization_patch_sha256",
        }
    }
    payload["single_use_cohort_id"] = "different-cohort"
    changed = build_c0b_smoke_1_user_authorization_patch_v2(
        payload, require_confirmation=True,
    )
    with pytest.raises(CanaryContractError, match="signed_approval_source_binding_mismatch"):
        materialize_signed_smoke_approval_v1(
            signed_packet["candidate"], changed, now=SIGNED_AT,
        )


def test_new_smoke_scope_cannot_be_used_by_legacy_approval_schema(signed_packet) -> None:
    payload = _signed_payload(signed_packet["signed"])
    payload.pop("approval_timestamp")
    payload.pop("approval_method")
    payload.pop("source_candidate_sha256")
    payload.pop("source_authorization_patch_sha256")
    with pytest.raises(CanaryContractError, match="approval_scope_mismatch"):
        build_canary_plan_approval_v1(payload)


def test_signed_approval_enters_real_runner_validation_and_fake_paid_boundary(
    signed_packet,
) -> None:
    approval, identity = validate_c0b_real_run_approval(
        plan_path=signed_packet["paths"]["plan"],
        approval_path=signed_packet["signed_path"],
        source_candidate_path=signed_packet["candidate_path"],
        source_authorization_patch_path=signed_packet["patch_path"],
        approved_plan_sha256=signed_packet["plan"]["plan_sha256"],
        now=SIGNED_AT,
    )
    assert identity == approval["signed_approval_sha256"]

    class FakePaidBoundary:
        calls = 0

        async def complete_route(self, route, role, system, user, **kwargs):
            self.calls += 1
            return {"status": "fake_paid_boundary"}

        async def complete_primary(self, role, system, user, **kwargs):
            self.calls += 1
            return {"status": "fake_paid_boundary"}

        def has_configured_fallback(self, role):
            return False

    fake = FakePaidBoundary()
    latch = FinalAuthorizationLatch()
    latch.authorize(identity)
    guarded = GuardedProductionGateway(lambda: fake, latch=latch)
    result = asyncio.run(guarded.complete_primary("planning", "system", "user"))
    assert result == {"status": "fake_paid_boundary"}
    assert fake.calls == 1
