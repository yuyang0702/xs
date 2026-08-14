"""Exact per-boundary C0A revalidation using the existing Runtime preflight."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable, Mapping

from novel_flywheel.runtime_fingerprint import (
    canary_runtime_fingerprint_preflight_v1,
)

from .contracts import (
    validate_canary_experiment_plan_v1,
    validate_canary_plan_approval_v1,
)
from .gate import BoundaryRequest


class CanaryPreflightBlocked(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise CanaryPreflightBlocked(reason_code)


class ExactBoundaryVerifier:
    """Re-reads every mutable input; fingerprint decisions stay Runtime-owned."""

    def __init__(
        self, *, snapshot_supplier: Callable[[], Mapping[str, Any]],
        cli_approved_plan_sha256: str, initial_plan_sha256: str,
        initial_approval_sha256: str, initial_launcher_sha256: str,
        initial_workload_manifest_hash: str,
        expected_scope: str = "C0A_FAKE_DRY_RUN",
        now: datetime | None = None,
    ) -> None:
        self.snapshot_supplier = snapshot_supplier
        self.cli_approved_plan_sha256 = cli_approved_plan_sha256
        self.initial_plan_sha256 = initial_plan_sha256
        self.initial_approval_sha256 = initial_approval_sha256
        self.initial_launcher_sha256 = initial_launcher_sha256
        self.initial_workload_manifest_hash = initial_workload_manifest_hash
        self.expected_scope = expected_scope
        self.now = now
        self.receipts: list[dict] = []

    def validate_inputs(self, request: BoundaryRequest) -> dict[str, Any]:
        """Validate mutable inputs before any budget authority is reserved."""

        snapshot = deepcopy(dict(self.snapshot_supplier()))
        plan = validate_canary_experiment_plan_v1(snapshot["plan"])
        _require(plan["plan_sha256"] == self.cli_approved_plan_sha256,
                 "plan_hash_unapproved")
        _require(plan["plan_sha256"] == self.initial_plan_sha256,
                 "plan_changed_during_canary")
        approval = validate_canary_plan_approval_v1(
            snapshot["approval"], expected_scope=self.expected_scope,
            expected_plan_sha256=plan["plan_sha256"],
            expected_launcher_sha256=plan["launcher_sha256"], now=self.now,
        )
        _require(approval["approval_sha256"] == self.initial_approval_sha256,
                 "approval_changed_during_canary")
        _require(snapshot["launcher_sha256"] == self.initial_launcher_sha256,
                 "launcher_changed_during_canary")
        _require(snapshot["launcher_sha256"] == plan["launcher_sha256"],
                 "launcher_hash_unapproved")
        _require(snapshot["workload_manifest_hash"] == self.initial_workload_manifest_hash,
                 "workload_changed_during_canary")
        _require(snapshot["workload_manifest_hash"] == plan["workload_manifest_hash"],
                 "workload_manifest_mismatch")
        expected_fixtures = {
            str(item["workload_id"]): str(item["fixture_sha256"])
            for item in plan["workloads"]
        }
        _require(snapshot["workload_fixture_hashes"] == expected_fixtures,
                 "workload_fixture_changed_during_canary")
        _require(
            snapshot["provider_descriptor_definition_sha256"]
            == plan["provider_descriptor_definition_sha256"],
            "provider_descriptor_mismatch",
        )
        _require(
            snapshot["role_binding_manifest_definition_sha256"]
            == plan["role_binding_manifest_definition_sha256"],
            "role_binding_manifest_mismatch",
        )
        _require(snapshot["feature_flag_snapshot"] == plan["feature_flag_snapshot"],
                 "execution_feature_flags_changed")
        _require(snapshot["feature_flag_snapshot"].get(
            "NOVEL_SHORT_CANONICAL_V2") is False,
            "phase1b_environment_flag_enabled")
        _require(snapshot["feature_flag_snapshot"].get(
            "project_short_canonical_v2") is False,
            "phase1b_project_flag_enabled")
        _require(snapshot["build_fingerprint"] == plan["approved_build_fingerprint"],
                 "build_changed_during_canary")
        _require(
            snapshot["execution_config_fingerprint"]
            == plan["approved_execution_config_fingerprint"],
            "execution_config_changed_during_canary",
        )
        _require(
            snapshot["runtime_execution_fingerprint"]
            == plan["expected_runtime_execution_fingerprint"],
            "runtime_execution_changed_during_canary",
        )
        _require(snapshot["canary_root_validation"].get("validation_status") == "exact",
                 "canary_root_identity_mismatch")
        return {"snapshot": snapshot, "plan": plan}

    def run_runtime_preflight(
        self, request: BoundaryRequest, validated: Mapping[str, Any],
    ) -> dict:
        snapshot = validated["snapshot"]
        plan = validated["plan"]
        runtime_receipt = canary_runtime_fingerprint_preflight_v1(
            deployment_mode=plan["runtime_mode"],
            approved_build_fingerprint=plan["approved_build_fingerprint"],
            approved_execution_config_fingerprint=(
                plan["approved_execution_config_fingerprint"]
            ),
            origin_binding=snapshot.get("origin_binding"),
            executor_binding=snapshot.get("executor_binding"),
            current_source_revalidation=snapshot["current_source_revalidation"],
            sidecar_validation=snapshot["sidecar_validation"],
            contradictory_binding=bool(snapshot.get("contradictory_binding")),
        )
        if not runtime_receipt.eligible:
            raise CanaryPreflightBlocked(runtime_receipt.blocked_reason_codes[0])
        receipt = {
            "schema": "CanaryBoundaryPreflightReceiptV1",
            "ordinal": request.ordinal,
            "stage": request.stage,
            "role": request.role,
            "runtime_validation_receipt_sha256": (
                runtime_receipt.validation_receipt_sha256
            ),
            "status": "exact",
        }
        self.receipts.append(receipt)
        return receipt

    def __call__(self, request: BoundaryRequest) -> dict:
        return self.run_runtime_preflight(request, self.validate_inputs(request))
