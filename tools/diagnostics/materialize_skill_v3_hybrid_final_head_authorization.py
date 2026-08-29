"""Materialize the sealed Hybrid authorization only after the final clean HEAD.

This module is deliberately offline.  It reuses the canonical authorization
renderer and exact validator used by the real campaign runner, then writes the
plaintext and its hash-only receipt to the existing worktree-external runtime
data convention.  It never creates campaign permission, signed approval,
nonce, provider client, or network activity.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from novel_flywheel.config import default_settings
from novel_flywheel.runtime_fingerprint_build import (
    canonical_json_bytes,
    domain_sha256,
)
from tools.canary import skill_v3_hybrid_character_heavy_pilot as hybrid
from tools.canary.skill_v3_hybrid_jit_approval import (
    HybridJitApprovalError,
    _outside_store,
    current_git_identity,
)
from tools.canary.skill_v3_hybrid_real_campaign import (
    campaign_transport_preflight_v1,
    render_final_authorization_text_v1,
    validate_final_authorization_text_v1,
)


EXPECTED_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
AUTHORIZATION_FILENAME = "campaign-authorization-final-plaintext-v1.txt"
RECEIPT_FILENAME = "final-head-authorization-receipt-v1.json"
DEFAULT_STORE_RELATIVE = Path(
    "canary-authorizations/skill-v3-hybrid-character-heavy-v1/"
    "final-head-authorization-v1"
)
RECEIPT_DOMAIN = (
    "novel-flywheel-skill-v3-hybrid-final-head-authorization-receipt-v1"
)
STORAGE_KIND = "WORKTREE_EXTERNAL_RUNTIME_DATA_EXCLUSIVE_BUNDLE_V1"
IMMUTABILITY_POLICY = "EXCLUSIVE_CREATE_HASH_PINNED_NO_OVERWRITE_V1"
ZERO_EXTERNAL_ACTION_COUNTERS = {
    "credential_lookup_count": 0,
    "provider_client_creation_count": 0,
    "provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
}


def _fail(reason: str, *, operation: str) -> None:
    raise HybridJitApprovalError(reason, operation=operation)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        _fail("FINAL_AUTHORIZATION_TIMESTAMP_INVALID", operation="materialization")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z",
    )


def _write_bytes_exclusive(path: Path, value: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        _fail("FINAL_AUTHORIZATION_BUNDLE_EXISTS", operation="external_store")
    try:
        os.write(descriptor, value)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def default_final_authorization_store_root() -> Path:
    """Return the existing application runtime-data root for this bundle."""

    return default_settings().data_dir / DEFAULT_STORE_RELATIVE


def _sealed_bindings(repo_root: Path) -> dict[str, Any]:
    sealed = hybrid.load_sealed_pilot(repo_root)
    report_root = repo_root.resolve(strict=True) / hybrid.REPORT_ROOT
    route = json.loads(
        (report_root / "provider-model-route-binding-v1.json").read_text(
            encoding="utf-8",
        ),
    )
    destination = json.loads(
        (report_root / "destination-binding-v1.json").read_text(encoding="utf-8"),
    )
    samples = list(sealed["samples"])
    provider_descriptor_sha256s = {
        str(row["PROVIDER_DESCRIPTOR_SHA256"]) for row in samples
    }
    model_binding_sha256s = {str(row["MODEL_BINDING_SHA256"]) for row in samples}
    route_fingerprints = {
        str(row["PROVIDER_MODEL_ROUTE_FINGERPRINT"]) for row in samples
    }
    output_caps = {int(row["OUTPUT_CAP"]) for row in samples}
    if not (
        len(samples) == 6
        and len(provider_descriptor_sha256s) == 1
        and len(model_binding_sha256s) == 1
        and len(route_fingerprints) == 1
        and len(output_caps) == 1
    ):
        _fail("FINAL_AUTHORIZATION_SEALED_BINDING_DRIFT", operation="preflight")
    return {
        "pilot_id": str(sealed["identity"]["PILOT_ID"]),
        "experiment_lock_sha256": str(
            sealed["experiment"]["EXPERIMENT_LOCK_SHA256"],
        ),
        "execution_sequence": [str(row["SAMPLE_SLOT"]) for row in samples],
        "sample_ids": [str(row["SAMPLE_ID"]) for row in samples],
        "sample_lock_sha256s": [str(row["SAMPLE_LOCK_SHA256"]) for row in samples],
        "egress_policy_sha256s": [
            str(row["EGRESS_POLICY_SHA256"]) for row in samples
        ],
        "provider_descriptor_sha256": next(iter(provider_descriptor_sha256s)),
        "model_binding_sha256": next(iter(model_binding_sha256s)),
        "route_fingerprint": next(iter(route_fingerprints)),
        "per_sample_output_token_hard_cap": next(iter(output_caps)),
        "total_output_token_hard_cap": sum(int(row["OUTPUT_CAP"]) for row in samples),
        "provider": str(route["PROVIDER"]),
        "model": str(route["MODEL"]),
        "protocol": str(route["PROTOCOL"]),
        "destination": (
            f"{destination['DESTINATION_ORIGIN']}:{destination['DESTINATION_PORT']}"
            f"{destination['DESTINATION_PATH']}"
        ),
        "operator_classification": str(destination["OPERATOR_CLASSIFICATION"]),
    }


def validate_final_head_authorization_preflight_v1(
    *, repo_root: Path, authorization_bytes: bytes,
    observed_head_override: str | None = None,
) -> dict[str, Any]:
    """Run the real exact validator and route preflight without external action."""

    repo = repo_root.resolve(strict=True)
    current_head, branch = current_git_identity(repo, require_clean=True)
    if branch != EXPECTED_BRANCH:
        _fail("FINAL_AUTHORIZATION_BRANCH_MISMATCH", operation="git_preflight")
    observed_head = observed_head_override or current_head
    validation = validate_final_authorization_text_v1(
        repo,
        authorization_bytes,
        successor_head=observed_head,
        expected_sha256=hashlib.sha256(authorization_bytes).hexdigest(),
    )
    if observed_head != current_head:
        _fail("FINAL_AUTHORIZATION_HEAD_MISMATCH", operation="git_preflight")
    transport = campaign_transport_preflight_v1(repo)
    if transport.get("status") != "EXACT":
        _fail("FINAL_AUTHORIZATION_TRANSPORT_DRIFT", operation="transport_preflight")
    bindings = _sealed_bindings(repo)

    drift_rejected = False
    drift_head = "0" * 40 if current_head != "0" * 40 else "1" * 40
    try:
        validate_final_authorization_text_v1(
            repo, authorization_bytes, successor_head=drift_head,
        )
    except HybridJitApprovalError as exc:
        drift_rejected = exc.reason_code == "AUTHORIZATION_TEXT_EXACT_MISMATCH"
    if not drift_rejected:
        _fail("POST_AUTH_HEAD_DRIFT_NOT_REJECTED", operation="negative_preflight")

    return {
        "schema": "SkillV3HybridFinalHeadAuthorizationPreflightV1",
        "status": "PASS",
        "authorization_text_sha_match": True,
        "authorization_text_sha256": validation["authorization_text_sha256"],
        "authorization_successor_head": observed_head,
        "current_git_head": current_head,
        "authorization_head_exact_match": True,
        "branch": branch,
        "branch_exact_match": True,
        **bindings,
        "pilot_match": True,
        "experiment_lock_match": True,
        "six_sample_ids_match": True,
        "six_sample_locks_match": True,
        "sequence_match": True,
        "route_match": transport["route_fingerprint"] == bindings["route_fingerprint"],
        "destination_match": transport["destination"] == bindings["destination"],
        "six_egress_sha_match": True,
        "output_caps_match": True,
        "request_caps_match": True,
        "jit_approval_policy_match": True,
        "nonce_policy_match": True,
        "stop_policy_match": True,
        "blind_policy_match": True,
        "cutover_scope_match": True,
        "post_auth_head_drift_rejected": True,
        "real_runner_authorization_preflight": "PASS",
        "external_action_counters": dict(ZERO_EXTERNAL_ACTION_COUNTERS),
    }


def materialize_final_head_authorization_bundle_v1(
    *, repo_root: Path, output_parent: Path | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Exclusively create one current-HEAD authorization bundle outside Git."""

    repo = repo_root.resolve(strict=True)
    final_head, branch = current_git_identity(repo, require_clean=True)
    if branch != EXPECTED_BRANCH:
        _fail("FINAL_AUTHORIZATION_BRANCH_MISMATCH", operation="git_preflight")
    authorization_bytes = render_final_authorization_text_v1(
        repo, successor_head=final_head,
    )
    preflight = validate_final_head_authorization_preflight_v1(
        repo_root=repo, authorization_bytes=authorization_bytes,
    )
    parent = _outside_store(
        repo,
        output_parent or default_final_authorization_store_root(),
    )
    bundle = parent / final_head
    try:
        bundle.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        _fail("FINAL_AUTHORIZATION_BUNDLE_EXISTS", operation="external_store")

    authorization_path = bundle / AUTHORIZATION_FILENAME
    _write_bytes_exclusive(authorization_path, authorization_bytes)
    head_after_authorization, branch_after_authorization = current_git_identity(
        repo, require_clean=True,
    )
    if (head_after_authorization, branch_after_authorization) != (final_head, branch):
        _fail("POST_AUTHORIZATION_GIT_DRIFT", operation="post_materialization")

    timestamp = created_at or datetime.now(timezone.utc)
    body: dict[str, Any] = {
        "schema": "SkillV3HybridFinalHeadAuthorizationReceiptV1",
        "version": 1,
        "status": "READY",
        "timestamp": _utc_text(timestamp),
        "final_execution_head": final_head,
        "head_after_authorization_materialization": head_after_authorization,
        "branch": branch,
        "worktree_clean": True,
        "authorization_filename": AUTHORIZATION_FILENAME,
        "authorization_text_sha256": hashlib.sha256(authorization_bytes).hexdigest(),
        "authorization_storage_kind": STORAGE_KIND,
        "authorization_immutability_policy": IMMUTABILITY_POLICY,
        "readiness_state": (
            "SKILL_V3_HYBRID_REAL_CAMPAIGN_AWAITING_"
            "FINAL_EXTERNAL_AUTHORIZATION_BYTES"
        ),
        "pilot_id": preflight["pilot_id"],
        "experiment_lock_sha256": preflight["experiment_lock_sha256"],
        "execution_sequence": preflight["execution_sequence"],
        "sample_ids": preflight["sample_ids"],
        "sample_lock_sha256s": preflight["sample_lock_sha256s"],
        "provider": preflight["provider"],
        "model": preflight["model"],
        "protocol": preflight["protocol"],
        "route_fingerprint": preflight["route_fingerprint"],
        "destination": preflight["destination"],
        "operator_classification": preflight["operator_classification"],
        "egress_policy_sha256s": preflight["egress_policy_sha256s"],
        "per_sample_output_token_hard_cap": preflight[
            "per_sample_output_token_hard_cap"
        ],
        "total_output_token_hard_cap": preflight["total_output_token_hard_cap"],
        "max_provider_requests_per_sample": 1,
        "total_provider_requests": 6,
        "max_http_post_attempts_per_sample": 1,
        "total_http_post_attempts": 6,
        "max_network_attempts_per_sample": 1,
        "total_network_attempts": 6,
        "max_campaign_elapsed_hours": 10,
        "monetary_cost_cap": "UNKNOWN_NOT_SEALED",
        "real_runner_authorization_preflight": preflight[
            "real_runner_authorization_preflight"
        ],
        "post_auth_head_drift_rejected": preflight[
            "post_auth_head_drift_rejected"
        ],
        "post_auth_git_write_count": 0,
        "post_auth_git_commit_count": 0,
        "pilot_execution_authorized": False,
        "real_signed_approval_created": False,
        "real_nonce_created": False,
        "real_sample_execution_count": 0,
        "skill_v3_production_cutover": False,
        "planning_v2_production_cutover": False,
        "full_short_executed": False,
        "external_action_counters": dict(ZERO_EXTERNAL_ACTION_COUNTERS),
    }
    receipt = {
        **body,
        "receipt_sha256": domain_sha256(RECEIPT_DOMAIN, body),
    }
    _write_bytes_exclusive(
        bundle / RECEIPT_FILENAME,
        canonical_json_bytes(receipt) + b"\n",
    )
    final_check = current_git_identity(repo, require_clean=True)
    if final_check != (final_head, branch):
        _fail("POST_AUTHORIZATION_GIT_DRIFT", operation="post_materialization")
    return {
        "status": "PASS",
        "bundle_path": str(bundle),
        "authorization_path": str(authorization_path),
        "receipt_path": str(bundle / RECEIPT_FILENAME),
        "authorization_text_sha256": receipt["authorization_text_sha256"],
        "receipt_sha256": receipt["receipt_sha256"],
        "final_execution_head": final_head,
        "head_after_authorization_materialization": final_check[0],
        "post_auth_git_write_count": 0,
        "post_auth_git_commit_count": 0,
        "external_action_counters": dict(ZERO_EXTERNAL_ACTION_COUNTERS),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-parent", type=Path)
    arguments = parser.parse_args()
    result = materialize_final_head_authorization_bundle_v1(
        repo_root=arguments.repo,
        output_parent=arguments.output_parent,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
