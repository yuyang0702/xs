"""Materialize one canonical Full Short authorization outside Git.

This command is offline-only. It discovers the deterministic call plan with
the existing in-memory provider boundary, binds current live public identity,
writes canonical authorization bytes with exclusive create, and runs the real
preflight with external actions disabled. It never creates a permission,
signed approval, nonce, credential store, Provider client, or network request.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from novel_flywheel.db import Database
from novel_flywheel.full_short_execution import (
    FullShortExecutionBoundaryError,
    FullShortExecutionPolicyV1,
    render_full_short_canonical_authorization_v1,
    validate_full_short_canonical_authorization_v1,
    validate_full_short_preflight_v1,
)
from tools.canary.first_trustworthy_full_short_dry_run import (
    _copy_private_data,
    _discover_plan,
)
from tools.canary.first_trustworthy_full_short_runner import (
    FULL_SHORT_REQUIRED_EXECUTION_ROLES,
    collect_live_bindings,
    preflight_full_short_control_plane,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, encoding="utf-8",
    ).strip()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z",
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _write_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


async def _materialize(args: argparse.Namespace) -> dict:
    repo = args.repo.resolve(strict=True)
    data_dir = (repo / "data").resolve(strict=True)
    authorization_path = Path(os.path.abspath(args.authorization))
    receipt_path = Path(os.path.abspath(args.receipt))
    store_root = Path(os.path.abspath(args.store_root))
    for path in (authorization_path, receipt_path, store_root):
        if _inside(path.resolve(strict=False), repo):
            raise RuntimeError("AUTHORIZATION_OUTPUT_OR_STORE_INSIDE_WORKTREE")
    if _git(repo, "status", "--porcelain"):
        raise RuntimeError("AUTHORIZATION_REQUIRES_CLEAN_WORKTREE")
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    db = Database(data_dir / "app.db")
    row = db.get_project(args.project_id)
    if row is None:
        raise RuntimeError("AUTHORIZATION_PROJECT_NOT_FOUND")
    source_project = Path(str(row["path"])).resolve(strict=True)

    with tempfile.TemporaryDirectory(prefix="full-short-auth-discovery-") as name:
        discovery_data = _copy_private_data(
            repo=repo, source_project=source_project,
            project_id=args.project_id, target=Path(name),
        )
        call_plan, logical_stage_plan = await _discover_plan(
            repo=repo, data_dir=discovery_data, project_id=args.project_id,
        )

    actual, public = collect_live_bindings(
        repo=repo, data_dir=data_dir, project_id=args.project_id,
        run_id=args.run_id, logical_stage_plan=logical_stage_plan,
        store_root=store_root,
    )
    if public.get("authorization_eligible") is not True:
        raise RuntimeError("AUTHORIZATION_ROUTE_CAPABILITY_NOT_VERIFIED")
    if actual["head"] != head or actual["branch"] != branch:
        raise RuntimeError("AUTHORIZATION_HEAD_OR_BRANCH_DRIFT")
    if actual["worktree_clean"] is not True:
        raise RuntimeError("AUTHORIZATION_WORKTREE_DRIFT")
    if actual["skill_v3_production_cutover"] is not False:
        raise RuntimeError("AUTHORIZATION_SKILL_V3_CUTOVER_DRIFT")
    if actual["planning_v2_production_cutover"] is not False:
        raise RuntimeError("AUTHORIZATION_PLANNING_V2_CUTOVER_DRIFT")

    roles = tuple(sorted({str(item["role"]) for item in call_plan}))
    if not set(FULL_SHORT_REQUIRED_EXECUTION_ROLES).issubset(roles):
        raise RuntimeError("AUTHORIZATION_CALL_PLAN_MISSING_ROLE")
    planning_caps = [
        int(item["requested_output_tokens"])
        for item in call_plan
        if item.get("contract_marker") == "planning_semantic_v2"
    ]
    if not planning_caps:
        raise RuntimeError("AUTHORIZATION_PLANNING_RECOVERY_CAP_MISSING")
    discovered_total = sum(
        int(item["requested_output_tokens"]) for item in call_plan
    )
    hard_max = len(call_plan) + 1
    policy = FullShortExecutionPolicyV1(
        execution_head=head, branch=branch, run_id=args.run_id,
        project_id_sha256=actual["project_id_sha256"],
        workload_sha256=actual["workload_sha256"],
        runtime_authority_sha256=actual["runtime_authority_sha256"],
        style_reference_authority_sha256=actual[
            "style_reference_authority_sha256"
        ],
        route_manifest_sha256=actual["route_manifest_sha256"],
        destination_manifest_sha256=actual["destination_manifest_sha256"],
        egress_policy_sha256=actual["egress_policy_sha256"],
        store_root_sha256=actual["store_root_sha256"],
        required_stage_roles=roles,
        logical_stage_plan=tuple(logical_stage_plan),
        expected_stage_calls=len(call_plan),
        hard_max_provider_requests=hard_max,
        hard_max_http_posts=hard_max,
        hard_max_network_attempts=hard_max,
        per_call_output_token_hard_cap=max(
            int(item["requested_output_tokens"]) for item in call_plan
        ),
        total_output_token_hard_cap=discovered_total + planning_caps[0],
        maximum_elapsed_seconds=36_000,
        monetary_cost_cap_state="UNKNOWN_NOT_SEALED",
    ).document()
    raw = render_full_short_canonical_authorization_v1(
        policy=policy, public_bindings=public,
    )
    authorization = validate_full_short_canonical_authorization_v1(
        raw, policy=policy, public_bindings=public,
    )
    authorization_sha256 = hashlib.sha256(raw).hexdigest()
    preflight_args = argparse.Namespace(
        repo=repo, data_dir=data_dir, project_id=args.project_id,
        store_root=store_root, authorization_raw=raw,
    )
    _authorization, preflight = preflight_full_short_control_plane(
        preflight_args, raw, external_actions_enabled=False,
    )
    drifted = dict(actual)
    drifted["head"] = "0" * 40
    post_auth_head_drift_rejected = False
    try:
        validate_full_short_preflight_v1(
            policy=policy, actual=drifted,
            authorization_text_sha256=authorization_sha256,
            external_actions_enabled=False,
        )
    except FullShortExecutionBoundaryError as exc:
        post_auth_head_drift_rejected = exc.reason_code == "HEAD_DRIFT"
    if not post_auth_head_drift_rejected:
        raise RuntimeError("POST_AUTH_HEAD_DRIFT_WAS_NOT_REJECTED")

    receipt = {
        "schema": "FirstTrustworthyFullShortExternalAuthorizationReceiptV1",
        "version": 1,
        "created_at": _now(),
        "authorization_text_sha256": authorization_sha256,
        "authorization_byte_length": len(raw),
        "authorization_path_sha256": hashlib.sha256(
            str(authorization_path).encode("utf-8")
        ).hexdigest(),
        "final_execution_head": head,
        "branch": branch,
        "run_id": args.run_id,
        "policy_sha256": policy["policy_sha256"],
        "response_capture_policy_sha256": policy[
            "response_capture_policy_sha256"
        ],
        "logical_stage_plan_sha256": policy["logical_stage_plan_sha256"],
        "transport_recovery_policy_sha256": policy[
            "transport_recovery_policy_sha256"
        ],
        "transport_recovery_policy_identity": policy[
            "transport_recovery_policy_identity"
        ],
        "logical_stage_recovery_policy_sha256": policy[
            "logical_stage_recovery_policy_sha256"
        ],
        "logical_stage_recovery_policy_identity": policy[
            "logical_stage_recovery_policy_identity"
        ],
        "failure_architecture_identity": policy[
            "failure_architecture_identity"
        ],
        "recovery_policy_registry_sha256": policy[
            "recovery_policy_registry_sha256"
        ],
        "predispatch_state_machine_sha256": policy[
            "predispatch_state_machine_sha256"
        ],
        "nonce_reservation_policy_sha256": policy[
            "nonce_reservation_policy_sha256"
        ],
        "observer_isolation_policy_sha256": policy[
            "observer_isolation_policy_sha256"
        ],
        "durable_failure_evidence_policy_sha256": policy[
            "durable_failure_evidence_policy_sha256"
        ],
        "normal_planning_reasoning_policy": "CURRENT_PROVIDER_DEFAULT",
        "planning_finalization_recovery_reasoning_policy": (
            "DEEPSEEK_OFFICIAL_ANTHROPIC_REASONING_EFFORT_NONE"
        ),
        "max_physical_attempts_per_logical_stage": 2,
        "expected_stage_calls": len(call_plan),
        "hard_max_provider_requests": hard_max,
        "hard_max_http_posts": hard_max,
        "hard_max_network_attempts": hard_max,
        "per_call_output_token_hard_cap": policy[
            "per_call_output_token_hard_cap"
        ],
        "total_output_token_hard_cap": policy["total_output_token_hard_cap"],
        "maximum_elapsed_seconds": policy["maximum_elapsed_seconds"],
        "monetary_cost_cap_state": policy["monetary_cost_cap_state"],
        "preflight_receipt_sha256": preflight["preflight_receipt_sha256"],
        "real_full_short_authorization_preflight": "PASS",
        "post_auth_head_drift_rejected": True,
        "signed_approval": "ABSENT",
        "durable_nonce": "ABSENT",
        "full_short_execution_authorized": False,
        "external_action_counters": actual["external_action_counters"],
    }
    _write_exclusive(authorization_path, raw)
    _write_exclusive(
        receipt_path,
        json.dumps(
            receipt, ensure_ascii=False, sort_keys=True, indent=2,
            allow_nan=False,
        ).encode("utf-8") + b"\n",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    receipt = asyncio.run(_materialize(parser.parse_args()))
    print(json.dumps(receipt, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
