"""CLI shell for C0A packet validation and later isolated fake execution.

Real-provider modes remain fail-closed in C0A.  This module never imports a
test helper and never constructs a production provider or credential store.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys
from datetime import datetime

from .contracts import (
    CanaryContractError,
    SMOKE_APPROVAL_CANDIDATE_SCHEMA,
    SMOKE_AUTHORIZATION_PATCH_SCHEMA,
    SMOKE_AUTHORIZATION_PATCH_SCHEMA_V1,
    SMOKE_SIGNED_APPROVAL_SCHEMA,
    SMOKE_APPROVAL_SCOPE,
    validate_canary_approval_document,
    validate_canary_experiment_plan_v1,
    validate_signed_smoke_approval_plan_v1,
    validate_signed_smoke_approval_sources_v1,
)
from .approval_dispatch import (
    profile_for_plan, validate_registered_approval_document,
    validate_registered_signed_plan, validate_registered_signed_sources,
)
from .hash_manifest import validate_import_closure
from .network_sentinel import FailClosedNetworkSentinel
from .outcomes import blocked_outcome, infrastructure_outcome
from .dry_run import run_c0a_dry_run


class CanaryLauncherError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def read_json_object(path: Path, reason_code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CanaryLauncherError(reason_code) from exc
    if not isinstance(value, dict):
        raise CanaryLauncherError(reason_code)
    return value


def _validate_registered_closure(profile_name: str, **kwargs) -> dict:
    if profile_name == "c0b_approval_closure_v1":
        from .approval_closure import validate_c0b_approval_closure
        return validate_c0b_approval_closure(**kwargs)
    if profile_name == "pa_strict_tool_observation_closure_v1":
        from .pa_approval_closure import validate_pa_approval_closure
        return validate_pa_approval_closure(**kwargs)
    raise CanaryLauncherError("validate_only_profile_not_supported")


def validate_packet(
    *, plan_path: Path, approval_path: Path,
    cli_approved_plan_sha256: str,
    execution_requested: bool = False,
    source_candidate_path: Path | None = None,
    source_authorization_patch_path: Path | None = None,
    now: datetime | None = None,
) -> dict:
    plan = validate_canary_experiment_plan_v1(
        read_json_object(plan_path, "plan_unavailable_or_invalid"),
    )
    if plan["plan_sha256"] != cli_approved_plan_sha256:
        raise CanaryLauncherError("cli_approved_plan_hash_mismatch")
    approved_third_party = plan["approved_dependency_manifest"].get(
        "third_party", [],
    )
    manifest = validate_import_closure(
        Path(__file__).resolve().parent,
        approved_third_party=approved_third_party,
    )
    if manifest["launcher_sha256"] != plan["launcher_sha256"]:
        raise CanaryLauncherError("launcher_changed_during_canary")
    approval_input = read_json_object(
        approval_path, "approval_unavailable_or_invalid",
    )
    registered_real = plan["canary_mode"] != "c0a_fake_dry_run"
    profile = profile_for_plan(plan) if registered_real else None
    registered_schema = profile is not None and approval_input.get("schema") in {
        profile.candidate_schema, profile.authorization_patch_schema,
        profile.authorization_patch_template_schema, profile.signed_approval_schema,
    }
    if profile is not None and approval_input.get("schema") in {
        profile.authorization_patch_schema,
        profile.authorization_patch_template_schema,
    }:
        raise CanaryLauncherError("authorization_patch_not_executable")
    if profile is not None and registered_schema:
        approval, approval_identity, approval_kind, document_profile = (
            validate_registered_approval_document(
                approval_input, expected_profile_id=profile.profile_id,
                expected_scope=profile.approval_scope,
                expected_plan_sha256=plan["plan_sha256"],
                expected_launcher_sha256=manifest["launcher_sha256"], now=now,
            )
        )
        if document_profile.profile_id != profile.profile_id:
            raise CanaryLauncherError("approval_profile_scope_mismatch")
    else:
        legacy_scope = (
            "C0B_REAL_PROVIDER_PATH_REACHABILITY"
            if profile is not None else "C0A_FAKE_DRY_RUN"
        )
        approval, approval_identity, approval_kind = validate_canary_approval_document(
            approval_input, expected_scope=legacy_scope,
            expected_plan_sha256=plan["plan_sha256"],
            expected_launcher_sha256=manifest["launcher_sha256"], now=now,
        )
    if approval_kind == "final_approval_candidate" and execution_requested:
        raise CanaryLauncherError("approval_candidate_not_executable")
    if profile is not None and approval_kind in {"signed_smoke_approval", "signed_approval"}:
        if source_candidate_path is None or source_authorization_patch_path is None:
            raise CanaryLauncherError("signed_approval_source_document_missing")
        validate_registered_signed_sources(
            profile.profile_id, approval,
            read_json_object(source_candidate_path,
                             "approval_candidate_unavailable_or_invalid"),
            read_json_object(source_authorization_patch_path,
                             "authorization_patch_unavailable_or_invalid"),
            now=now,
        )
        validate_registered_signed_plan(profile.profile_id, approval, plan, now=now)
    actions = approval["authorized_actions"]
    if plan["canary_mode"] == "c0a_fake_dry_run":
        if execution_requested:
            raise CanaryLauncherError("fake_approval_cannot_execute_real_mode")
        if any(actions.get(name) is not False for name in (
            "credential_lookup", "provider_client_creation", "network",
            "paid_model_calls",
        )):
            raise CanaryLauncherError("c0a_external_action_authorized")
        if actions.get("fake_boundary") is not True:
            raise CanaryLauncherError("fake_boundary_not_authorized")
    elif profile is not None:
        if execution_requested:
            if any(actions.get(name) is not True for name in (
                "credential_lookup", "provider_client_creation", "network",
                "paid_model_calls",
            )):
                raise CanaryLauncherError("real_mode_final_authorization_missing")
            if actions.get("fake_boundary") is not False:
                raise CanaryLauncherError("real_mode_fake_boundary_forbidden")
            if not approval.get("named_approver"):
                raise CanaryLauncherError("real_mode_named_approver_missing")
    else:
        raise CanaryLauncherError("statistical_mode_not_supported_by_c0b_launcher")
    return {
        "schema": "CanaryPacketValidationV1",
        "status": "exact",
        "plan_sha256": plan["plan_sha256"],
        "approval_sha256": approval_identity,
        "approval_document_kind": approval_kind,
        "launcher_sha256": manifest["launcher_sha256"],
        "dependency_file_count": len(manifest["files"]),
        "canary_mode": plan["canary_mode"],
        "execution_authorized": bool(execution_requested),
        "profile_id": profile.profile_id if profile is not None else None,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Controlled C0A Canary launcher")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--approval-candidate", type=Path)
    parser.add_argument("--authorization-patch", type=Path)
    parser.add_argument("--approved-plan-sha256", required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--real-run", action="store_true")
    parser.add_argument("--workload-fixture", type=Path)
    parser.add_argument("--canary-root", type=Path)
    parser.add_argument("--approval-ledger-root", type=Path)
    parser.add_argument("--approval-packet", type=Path)
    parser.add_argument("--live-database", type=Path)
    parser.add_argument("--live-project-root", type=Path)
    parser.add_argument("--live-incident-root", type=Path, action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    sentinel = FailClosedNetworkSentinel()
    try:
        if sum(bool(value) for value in (
            args.validate_only, args.dry_run, args.real_run,
        )) != 1:
            raise CanaryLauncherError("exactly_one_canary_action_required")
        if args.validate_only:
            with sentinel:
                result = validate_packet(
                    plan_path=args.plan, approval_path=args.approval,
                    cli_approved_plan_sha256=args.approved_plan_sha256,
                    source_candidate_path=args.approval_candidate,
                    source_authorization_patch_path=args.authorization_patch,
                )
                if result.get("profile_id") is not None:
                    required = (
                        args.approval_packet, args.workload_fixture,
                        args.canary_root, args.approval_ledger_root,
                        args.live_database, args.live_project_root,
                    )
                    if any(item is None for item in required):
                        raise CanaryLauncherError(
                            "c0b_validate_only_closure_argument_missing"
                        )
                    profile = profile_for_plan(read_json_object(
                        args.plan, "plan_unavailable_or_invalid",
                    ))
                    result = _validate_registered_closure(
                        profile.validate_only_profile,
                        plan_path=args.plan, approval_path=args.approval,
                        source_candidate_path=args.approval_candidate,
                        source_authorization_patch_path=args.authorization_patch,
                        packet_path=args.approval_packet,
                        workload_fixture_path=args.workload_fixture,
                        live_database_path=args.live_database,
                        live_project_root=args.live_project_root,
                        canary_root=args.canary_root,
                        approval_ledger_root=args.approval_ledger_root,
                        cli_approved_plan_sha256=args.approved_plan_sha256,
                    )
            result["network_call_count"] = sentinel.network_call_count
            if result.get("overall_status") == "blocked":
                first = next(
                    item for item in result["ordered_checks"]
                    if item["status"] == "blocked"
                )
                result["outcome"] = "CANARY_BLOCKED_PRE_PROVIDER"
                result["reason_code"] = first["reason_code"]
        elif args.dry_run:
            required = (
                args.workload_fixture, args.canary_root,
                args.approval_ledger_root, args.live_database,
                args.live_project_root,
            )
            if any(item is None for item in required):
                raise CanaryLauncherError("c0a_dry_run_argument_missing")
            result = validate_packet(
                plan_path=args.plan, approval_path=args.approval,
                cli_approved_plan_sha256=args.approved_plan_sha256,
            )
            completed = asyncio.run(run_c0a_dry_run(
                plan_path=args.plan, approval_path=args.approval,
                approved_plan_sha256=args.approved_plan_sha256,
                workload_fixture_path=args.workload_fixture,
                canary_root=args.canary_root,
                approval_ledger_root=args.approval_ledger_root,
                live_database_path=args.live_database,
                live_project_root=args.live_project_root,
                live_incident_roots=args.live_incident_root,
            ))
            evidence = completed["evidence"]
            result = {
                "schema": "CanaryDryRunResultV1",
                "outcome": evidence["outcome"]["value"],
                "reason_code": evidence["outcome"]["reason_code"],
                "evidence_sha256": evidence["evidence_sha256"],
                "network_call_count": evidence["counters"]["network_call_count"],
                "paid_model_call_count": evidence["counters"]["paid_model_call_count"],
            }
        else:
            required = (
                args.workload_fixture, args.canary_root,
                args.approval_ledger_root, args.live_database,
                args.live_project_root,
            )
            if any(item is None for item in required):
                raise CanaryLauncherError("c0b_real_run_argument_missing")
            validate_packet(
                plan_path=args.plan, approval_path=args.approval,
                cli_approved_plan_sha256=args.approved_plan_sha256,
                source_candidate_path=args.approval_candidate,
                source_authorization_patch_path=args.authorization_patch,
                execution_requested=True,
            )
            from .real_run import run_registered_real_run
            completed = asyncio.run(run_registered_real_run(
                plan_path=args.plan, approval_path=args.approval,
                source_candidate_path=args.approval_candidate,
                source_authorization_patch_path=args.authorization_patch,
                approved_plan_sha256=args.approved_plan_sha256,
                workload_fixture_path=args.workload_fixture,
                canary_root=args.canary_root,
                approval_ledger_root=args.approval_ledger_root,
                live_database_path=args.live_database,
                live_project_root=args.live_project_root,
                live_incident_roots=args.live_incident_root,
            ))
            evidence = completed["evidence"]
            result = {
                "schema": "C0BRealCanaryResultV1",
                "outcome": evidence["outcome"]["value"],
                "reason_code": evidence["outcome"]["reason_code"],
                "evidence_sha256": evidence["evidence_sha256"],
                "network_call_count": evidence["counters"]["network_call_count"],
                "paid_model_call_count": evidence["counters"]["paid_model_call_count"],
            }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("outcome") in {None, "WORKFLOW_COMPLETED"} else 4
    except (CanaryContractError, CanaryLauncherError) as exc:
        outcome = blocked_outcome(getattr(exc, "reason_code", "canary_packet_blocked"))
        report = {**asdict(outcome), "outcome": outcome.outcome.value,
                  "network_call_count": sentinel.network_call_count}
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 2
    except BaseException:
        outcome = infrastructure_outcome("canary_launcher_unhandled_failure")
        report = {**asdict(outcome), "outcome": outcome.outcome.value,
                  "network_call_count": sentinel.network_call_count}
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 3


if __name__ == "__main__":
    sys.exit(main())
