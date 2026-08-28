"""One-sample Hybrid campaign boundary built on strict JIT approvals."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from novel_flywheel.runtime_fingerprint_build import domain_sha256
from tools.canary import skill_v3_hybrid_character_heavy_pilot as hybrid
from tools.canary.skill_v3_a1_destination_binding import DESTINATION_ORIGIN_DOMAIN
from tools.canary.skill_v3_hybrid_jit_approval import (
    DurableHybridApprovalStoreV1,
    HybridJitApprovalError,
    create_one_hybrid_sample_jit_approval,
    project_verified_approval_for_legacy_launch,
    validate_approval_domain_v1,
)


class HybridApprovalBoundNonceAdapter:
    """Bind the generic durable nonce to the verified Hybrid destination."""

    def __init__(self, *, delegate: Any, approval: Mapping[str, Any]) -> None:
        self.delegate = delegate
        self.approval = dict(approval)

    def reserve(self, **bindings: Any) -> Mapping[str, Any]:
        if (
            bindings.get("signed_approval_sha256")
            != self.approval.get("signed_approval_sha256")
        ):
            raise HybridJitApprovalError(
                "NONCE_APPROVAL_BINDING_MISMATCH", operation="nonce_reservation",
                bindings={
                    "pilot_id": bindings.get("pilot_id"),
                    "sample_id": bindings.get("sample_id"),
                    "approval_id": bindings.get("approval_id"),
                },
            )
        return self.delegate.reserve_destination_bound_v2(
            **bindings,
            approved_destination_origin=self.approval["destination_origin"],
            approved_destination_origin_sha256=domain_sha256(
                DESTINATION_ORIGIN_DOMAIN,
                {"origin": self.approval["destination_origin"]},
            ),
            approved_destination_path_or_prefix=self.approval["destination_path"],
            egress_policy_sha256=self.approval["egress_policy_sha256"],
            cross_origin_redirect_allowed=False,
            unbound_proxy_route_allowed=False,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)


async def execute_one_hybrid_sealed_sample(
    *, repo_root: Path, permission: Mapping[str, Any], sample_id: str,
    completed_sample_ids: Sequence[str], approval_store: DurableHybridApprovalStoreV1,
    approval_id: str, approval_created_at: datetime, approval_expires_at: datetime,
    attempt_counters: Mapping[str, Any],
    nonce_store: Any, ledger: hybrid.HybridPilotLedger, dispatcher: Any,
    output_root: Path, offline_test: bool,
) -> dict[str, Any]:
    """Create/verify approval, then reserve nonce and run exactly one sample.

    Tests may use an explicitly non-executable permission, temporary approval
    and nonce stores, and an offline dispatcher.  The production-shaped order
    remains permission -> approval -> verification -> nonce -> dispatch.
    """

    checker = getattr(nonce_store, "is_reusable", None)
    if checker is not None:
        nonce_preexists = not bool(checker(
            pilot_id=permission["pilot_id"], sample_id=sample_id,
            approval_id=approval_id,
        ))
    elif offline_test and hasattr(nonce_store, "records"):
        nonce_key = nonce_store._key({
            "pilot_id": permission["pilot_id"], "sample_id": sample_id,
            "approval_id": approval_id,
        })
        nonce_preexists = nonce_key in nonce_store.records
    else:
        raise HybridJitApprovalError(
            "NONCE_ABSENCE_CHECK_UNAVAILABLE", operation="approval_preflight",
            bindings={
                "pilot_id": permission.get("pilot_id"), "sample_id": sample_id,
                "approval_id": approval_id,
            },
        )
    approval = create_one_hybrid_sample_jit_approval(
        repo_root=repo_root, store=approval_store, permission=permission,
        sample_id=sample_id, completed_sample_ids=completed_sample_ids,
        approval_id=approval_id, now=approval_created_at,
        attempt_counters=attempt_counters, nonce_preexists=nonce_preexists,
        expires_at=approval_expires_at, offline_test=offline_test,
    )
    loaded = approval_store.load(approval_id, now=approval_created_at)["approval"]
    validate_approval_domain_v1(
        loaded, repo_root=repo_root, permission=permission,
        completed_sample_ids=completed_sample_ids, now=approval_created_at,
        attempt_counters=attempt_counters, nonce_preexists=False,
        require_executable=not offline_test,
    )
    sealed = hybrid.load_sealed_pilot(repo_root)
    lock = next(row for row in sealed["samples"] if row["SAMPLE_ID"] == sample_id)
    projected_permission = {
        "schema": "HybridVerifiedCampaignPermissionProjectionV1",
        "non_executable": offline_test,
        "active_campaign_permission": True,
        "pilot_id": permission["pilot_id"], "sample_id": sample_id,
        "experiment_lock_sha256": permission["experiment_lock_sha256"],
        "successor_head": sealed["approval"]["CURRENT_SUCCESSOR_HEAD"],
        "scopes": list(hybrid.PERMISSION_SCOPES),
    }
    projected_approval = project_verified_approval_for_legacy_launch(
        loaded, offline_test=offline_test,
    )
    effective_nonce_store = (
        nonce_store if offline_test else HybridApprovalBoundNonceAdapter(
            delegate=nonce_store, approval=loaded,
        )
    )
    try:
        result = await hybrid.launch_one_sealed_hybrid_sample(
            repo_root=repo_root, pilot_id=str(permission["pilot_id"]),
            sample_id=sample_id,
            expected_sample_lock_sha256=str(lock["SAMPLE_LOCK_SHA256"]),
            expected_experiment_lock_sha256=str(lock["EXPERIMENT_LOCK_SHA256"]),
            permission=projected_permission, signed_approval=projected_approval,
            nonce_store=effective_nonce_store, ledger=ledger,
            dispatcher=dispatcher,
            output_root=output_root, offline_fake=offline_test,
        )
    except BaseException as exc:
        reason = getattr(exc, "reason_code", "HYBRID_SAMPLE_EXECUTION_FAILED")
        approval_store.invalidate(approval_id, reason_code=str(reason))
        raise
    receipt_sha = domain_sha256(
        "novel-flywheel-skill-v3-hybrid-sample-execution-receipt-v1",
        {"sample_id": sample_id, "status": result["status"],
         "signed_approval_sha256": approval["signed_approval_sha256"]},
    )
    lifecycle = approval_store.consume(
        approval_id, execution_receipt_sha256=receipt_sha,
    )
    return {
        **result, "approval_id": approval_id,
        "signed_approval_sha256": approval["signed_approval_sha256"],
        "approval_lifecycle": lifecycle["usage_state"],
        "execution_receipt_sha256": receipt_sha,
    }


__all__ = [
    "HybridJitApprovalError", "execute_one_hybrid_sealed_sample",
]
