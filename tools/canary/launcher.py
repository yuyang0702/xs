"""CLI shell for C0A packet validation and later isolated fake execution.

Real-provider modes remain fail-closed in C0A.  This module never imports a
test helper and never constructs a production provider or credential store.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .contracts import (
    CanaryContractError,
    validate_canary_experiment_plan_v1,
    validate_canary_plan_approval_v1,
)
from .hash_manifest import validate_import_closure
from .network_sentinel import FailClosedNetworkSentinel
from .outcomes import blocked_outcome, infrastructure_outcome


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


def validate_packet(
    *, plan_path: Path, approval_path: Path,
    cli_approved_plan_sha256: str,
) -> dict:
    plan = validate_canary_experiment_plan_v1(
        read_json_object(plan_path, "plan_unavailable_or_invalid"),
    )
    if plan["plan_sha256"] != cli_approved_plan_sha256:
        raise CanaryLauncherError("cli_approved_plan_hash_mismatch")
    manifest = validate_import_closure(Path(__file__).resolve().parent)
    if manifest["launcher_sha256"] != plan["launcher_sha256"]:
        raise CanaryLauncherError("launcher_changed_during_canary")
    approval = validate_canary_plan_approval_v1(
        read_json_object(approval_path, "approval_unavailable_or_invalid"),
        expected_scope="C0A_FAKE_DRY_RUN",
        expected_plan_sha256=plan["plan_sha256"],
        expected_launcher_sha256=manifest["launcher_sha256"],
    )
    if plan["canary_mode"] != "c0a_fake_dry_run":
        raise CanaryLauncherError("real_provider_mode_blocked_in_c0a")
    actions = approval["authorized_actions"]
    if any(actions.get(name) is not False for name in (
        "credential_lookup", "provider_client_creation", "network",
        "paid_model_calls",
    )):
        raise CanaryLauncherError("c0a_external_action_authorized")
    if actions.get("fake_boundary") is not True:
        raise CanaryLauncherError("fake_boundary_not_authorized")
    return {
        "schema": "CanaryPacketValidationV1",
        "status": "exact",
        "plan_sha256": plan["plan_sha256"],
        "approval_sha256": approval["approval_sha256"],
        "launcher_sha256": manifest["launcher_sha256"],
        "dependency_file_count": len(manifest["files"]),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Controlled C0A Canary launcher")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--approved-plan-sha256", required=True)
    parser.add_argument("--validate-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    sentinel = FailClosedNetworkSentinel()
    try:
        with sentinel:
            if not args.validate_only:
                raise CanaryLauncherError("c0a_dry_run_not_requested_by_validate_command")
            result = validate_packet(
                plan_path=args.plan, approval_path=args.approval,
                cli_approved_plan_sha256=args.approved_plan_sha256,
            )
        result["network_call_count"] = sentinel.network_call_count
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
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
