"""Production-shaped offline Full Short transport failure injections.

The workflow, control plane, authorization validation, registry and provider
adapters are real.  Only the lowest HTTP seam is replaced.  The two injected
outcomes are intentionally terminal under EXACT_REPLAY_ONLY; this tool proves
that they close after one physical dispatch without mutating story authority.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from novel_flywheel.db import Database
from novel_flywheel.full_short_execution import (
    FullShortExecutionPolicyV1,
    render_full_short_canonical_authorization_v1,
    validate_full_short_canonical_authorization_v1,
)
from novel_flywheel.offline_http_transport import (
    OfflineHttpRequestV1,
    OfflineHttpResponseV1,
    build_offline_http_transport_v1,
    offline_read_timeout_v1,
)
from novel_flywheel.provider_response_capture import (
    PROVIDER_PROTOCOL_INPUT_BYTES,
    ProviderResponseCaptureStoreV1,
)
from tools.canary.first_trustworthy_full_short_dry_run import (
    _copy_private_data,
    _discover_plan,
    _domain,
    _memory_secrets,
    _registry_factory,
    _request_messages,
    _request_role,
)
from tools.canary.first_trustworthy_full_short_runner import (
    FULL_SHORT_REQUIRED_EXECUTION_ROLES,
    collect_live_bindings,
    execute_full_short_control_plane,
)


_SCENARIO_SHORT_NAME = {
    "provider_unavailable_complete_response": "b",
    "ambiguous_external_completion": "c",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, encoding="utf-8",
    ).strip()


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _FailureInjectionTransportFactory:
    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.call_plan: list[dict[str, Any]] = []
        self.failure: dict[str, Any] | None = None

    def build(
        self, *, protocol: str, destination: str,
        bound_role: str | None = None,
    ) -> Any:
        async def respond(
            request: OfflineHttpRequestV1,
        ) -> OfflineHttpResponseV1:
            payload = json.loads(request.content.decode("utf-8"))
            system, user = _request_messages(payload)
            role = bound_role or _request_role(system, user)
            maximum = int(
                payload.get("max_tokens")
                or payload.get("max_output_tokens") or 0
            )
            self.call_plan.append({
                "ordinal": len(self.call_plan) + 1,
                "role": role,
                "requested_output_tokens": maximum,
                "destination_sha256": hashlib.sha256(
                    destination.encode("utf-8"),
                ).hexdigest(),
                "request_shape_sha256": _domain({
                    "protocol": protocol,
                    "payload_keys": sorted(str(key) for key in payload),
                    "role": role,
                    "requested_output_tokens": maximum,
                }),
            })
            if len(self.call_plan) != 1:
                raise RuntimeError("TRANSPORT_FAILURE_SCENARIO_REDISPATCHED")
            if self.scenario == "provider_unavailable_complete_response":
                return OfflineHttpResponseV1(
                    503,
                    content=b'{"type":"error","error":{"type":"unavailable"}}',
                    headers={"content-type": "application/json"},
                )
            if self.scenario == "ambiguous_external_completion":
                raise offline_read_timeout_v1(
                    "offline injected ambiguous external completion",
                )
            raise RuntimeError("TRANSPORT_FAILURE_SCENARIO_UNKNOWN")

        return build_offline_http_transport_v1(respond)


async def _run_scenario(
    *, repo: Path, source_project: Path, project_id: str,
    private_root: Path, call_plan: list[dict[str, Any]],
    logical_stage_plan: list[dict[str, Any]], scenario: str,
) -> dict[str, Any]:
    short_name = _SCENARIO_SHORT_NAME[scenario]
    execution_id = f"private-fs-transport-{short_name}"
    execution_data = _copy_private_data(
        repo=repo, source_project=source_project, project_id=project_id,
        target=private_root / short_name,
    )
    private_project = (
        execution_data / "projects" / source_project.name
    )
    manuscript = private_project / "manuscript" / "story.md"
    authority_before = _file_sha256(manuscript)
    store_root = private_root / f"{short_name}-control"
    actual, public = collect_live_bindings(
        repo=repo, data_dir=execution_data, project_id=project_id,
        run_id=execution_id, logical_stage_plan=logical_stage_plan,
        store_root=store_root,
    )
    per_call_cap = max(
        int(item["requested_output_tokens"]) for item in call_plan
    )
    total_cap = sum(
        int(item["requested_output_tokens"]) for item in call_plan
    ) + per_call_cap
    roles = tuple(sorted({str(item["role"]) for item in call_plan}))
    policy = FullShortExecutionPolicyV1(
        execution_head=actual["head"], branch=actual["branch"],
        run_id=execution_id,
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
        hard_max_provider_requests=len(call_plan) + 1,
        hard_max_http_posts=len(call_plan) + 1,
        hard_max_network_attempts=len(call_plan) + 1,
        per_call_output_token_hard_cap=per_call_cap,
        total_output_token_hard_cap=total_cap,
        maximum_elapsed_seconds=36_000,
        monetary_cost_cap_state="UNKNOWN_NOT_SEALED",
    ).document()
    raw = render_full_short_canonical_authorization_v1(
        policy=policy, public_bindings=public,
    )
    authorization = validate_full_short_canonical_authorization_v1(
        raw, policy=policy, public_bindings=public,
    )
    factory = _FailureInjectionTransportFactory(scenario)
    args = argparse.Namespace(
        repo=repo, data_dir=execution_data, store_root=store_root,
        authorization_raw=raw,
        activated_sha256=hashlib.sha256(raw).hexdigest(),
    )
    observed_exception: BaseException | None = None
    try:
        await execute_full_short_control_plane(
            args, authorization, external_actions_enabled=False,
            secret_store_factory=_memory_secrets(execution_data),
            registry_factory=_registry_factory,
            http_transport_factory=factory,
            required_stage_roles=roles,
        )
    except BaseException as exc:
        observed_exception = exc
    if observed_exception is None:
        raise RuntimeError("TRANSPORT_FAILURE_SCENARIO_DID_NOT_FAIL_CLOSED")

    ledger_paths = sorted(store_root.glob("*.ledger.json"))
    if len(ledger_paths) != 1:
        raise RuntimeError("TRANSPORT_FAILURE_LEDGER_NOT_UNIQUE")
    ledger = json.loads(ledger_paths[0].read_text(encoding="utf-8"))
    attempts = list(ledger.get("attempts") or [])
    if len(attempts) != 1 or len(factory.call_plan) != 1:
        raise RuntimeError("TRANSPORT_FAILURE_DISPATCH_COUNT_INVALID")
    attempt = attempts[0]
    capture_store = ProviderResponseCaptureStoreV1(
        repo_root=repo,
        store_root=store_root / "provider-response-captures-v1",
    )
    captures = [
        item for item in capture_store.audit_all()
        if item["byte_domain"] == PROVIDER_PROTOCOL_INPUT_BYTES
    ]
    expected_state = {
        "provider_unavailable_complete_response": "HTTP_RESPONSE_FAILED_CLOSED",
        "ambiguous_external_completion": "OUTCOME_UNKNOWN_FAIL_CLOSED",
    }[scenario]
    expected_capture_count = int(
        scenario == "provider_unavailable_complete_response"
    )
    authority_after = _file_sha256(manuscript)
    passed = all((
        attempt.get("state") == expected_state,
        len(captures) == expected_capture_count,
        authority_after == authority_before,
        len(ledger.get("completed_stage_receipts") or []) == 0,
        ledger.get("state") == "RECONCILIATION_REQUIRED_NO_REDISPATCH",
    ))
    if not passed:
        raise RuntimeError("TRANSPORT_FAILURE_DURABLE_CLOSE_INVALID")
    return {
        "scenario": scenario,
        "status": "PASS_EXPECTED_FAIL_CLOSED",
        "source_head": actual["head"],
        "logical_stage_plan_sha256": policy["logical_stage_plan_sha256"],
        "transport_recovery_policy_identity": policy[
            "transport_recovery_policy_identity"
        ],
        "transport_recovery_policy_sha256": policy[
            "transport_recovery_policy_sha256"
        ],
        "observed_exception_type": type(observed_exception).__name__,
        "physical_dispatch_count": 1,
        "logical_stage_completion_count": 0,
        "network_redispatch_count": 0,
        "attempt_state": attempt["state"],
        "ledger_state": ledger["state"],
        "provider_protocol_capture_count": len(captures),
        "response_bytes_present": bool(captures),
        "authority_sha256_unchanged": authority_before == authority_after,
        "real_credential_lookup_count": 0,
        "real_provider_client_creation_count": 0,
        "real_provider_request_attempts": 0,
        "real_http_post_attempts": 0,
        "real_network_calls": 0,
        "real_model_calls": 0,
        "paid_calls": 0,
        "pass": True,
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo.resolve(strict=True)
    if _git(repo, "status", "--porcelain"):
        raise RuntimeError("TRANSPORT_FAILURE_DRY_RUN_REQUIRES_CLEAN_WORKTREE")
    db = Database(repo / "data" / "app.db")
    row = db.get_project(args.project_id)
    if row is None:
        raise RuntimeError("TRANSPORT_FAILURE_PROJECT_NOT_FOUND")
    source_project = Path(str(row["path"])).resolve(strict=True)
    with tempfile.TemporaryDirectory(
        prefix="fs-tf-",
    ) as name:
        private_root = Path(name)
        discovery_data = _copy_private_data(
            repo=repo, source_project=source_project,
            project_id=args.project_id, target=private_root / "d",
        )
        call_plan, logical_stage_plan = await _discover_plan(
            repo=repo, data_dir=discovery_data, project_id=args.project_id,
        )
        roles = {str(item["role"]) for item in call_plan}
        if not set(FULL_SHORT_REQUIRED_EXECUTION_ROLES).issubset(roles):
            raise RuntimeError("TRANSPORT_FAILURE_DISCOVERY_ROLE_GAP")
        scenarios = []
        for scenario in (
            "provider_unavailable_complete_response",
            "ambiguous_external_completion",
        ):
            scenarios.append(await _run_scenario(
                repo=repo, source_project=source_project,
                project_id=args.project_id, private_root=private_root,
                call_plan=call_plan, logical_stage_plan=logical_stage_plan,
                scenario=scenario,
            ))
    return {
        "schema": "ProductionShapedFullShortTransportFailureMatrixV1",
        "version": 1,
        "source_head": _git(repo, "rev-parse", "HEAD"),
        "status": "PASS",
        "discovered_logical_stage_count": len(logical_stage_plan),
        "all_required_roles_discovered": True,
        "scenarios": scenarios,
        "full_short_execution_authorized": False,
        "full_short_executed_against_real_provider": False,
        "real_external_action_counters_all_zero": True,
        "pass": all(item["pass"] for item in scenarios),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("output already exists")
    previous_canonical_flag = os.environ.get("NOVEL_SHORT_CANONICAL_V2")
    os.environ["NOVEL_SHORT_CANONICAL_V2"] = "1"
    try:
        result = asyncio.run(_run(args))
    finally:
        if previous_canonical_flag is None:
            os.environ.pop("NOVEL_SHORT_CANONICAL_V2", None)
        else:
            os.environ["NOVEL_SHORT_CANONICAL_V2"] = previous_canonical_flag
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"],
        "scenario_count": len(result["scenarios"]),
        "real_external_action_counters_all_zero": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
