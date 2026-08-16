"""Exact per-boundary C0A revalidation using the existing Runtime preflight."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable, Mapping

from novel_flywheel.runtime_fingerprint import (
    canary_runtime_fingerprint_preflight_v1,
)

from .contracts import (
    SMOKE_SIGNED_APPROVAL_SCHEMA,
    validate_canary_approval_document,
    validate_canary_experiment_plan_v1,
    validate_signed_smoke_approval_plan_v1,
    validate_signed_smoke_approval_sources_v1,
)
from .approval_dispatch import (
    validate_registered_approval_document,
    validate_registered_signed_plan,
    validate_registered_signed_sources,
)
from .approval_profiles import approval_profile
from .gate import BoundaryRequest


class CanaryPreflightBlocked(RuntimeError):
    def __init__(
        self, reason_code: str, *, component_diff: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.component_diff = deepcopy(dict(component_diff or {}))


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise CanaryPreflightBlocked(reason_code)


def execution_config_component_diff_v2(
    approved: Mapping[str, Any], observed: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare V2 hash components without revealing values or source material."""

    expected_components = dict(approved.get("semantic_components") or {})
    actual_components = dict(observed.get("semantic_components") or {})
    differing = sorted(
        key for key in set(expected_components) | set(actual_components)
        if expected_components.get(key) != actual_components.get(key)
    )
    expected_provenance = approved.get("feature_flag_provenance_sha256")
    actual_provenance = observed.get("feature_flag_provenance_sha256")
    provenance_known = all(
        isinstance(value, str) and len(value) == 64
        for value in (expected_provenance, actual_provenance)
    )
    provenance_equal = (
        provenance_known and expected_provenance == actual_provenance
    )
    if provenance_known and not provenance_equal:
        differing.append("feature_flag_provenance")
    return {
        "policy_version": observed.get("policy_version"),
        "expected_semantic_sha256": approved.get("semantic_sha256"),
        "actual_semantic_sha256": observed.get("semantic_sha256"),
        "expected_provenance_sha256": expected_provenance,
        "actual_provenance_sha256": actual_provenance,
        "semantic_equal": (
            approved.get("semantic_sha256") == observed.get("semantic_sha256")
            and isinstance(approved.get("semantic_sha256"), str)
        ),
        "provenance_equal": provenance_equal if provenance_known else None,
        "provenance_known": provenance_known,
        "differing_component_ids": sorted(set(differing)),
        "hash_only": True,
    }


def validate_execution_config_prelaunch_v2(
    plan: Mapping[str, Any], observed: Mapping[str, Any],
) -> dict[str, Any]:
    """Typed V2 semantic gate shared by launcher boundary checks."""

    approved = plan.get("approved_execution_config_components")
    if not isinstance(approved, Mapping):
        raise CanaryPreflightBlocked("execution_config_policy_mismatch")
    if (
        approved.get("policy_version") != "runtime-fingerprint-v2"
        or observed.get("policy_version") != "runtime-fingerprint-v2"
    ):
        raise CanaryPreflightBlocked("execution_config_policy_mismatch")
    diff = execution_config_component_diff_v2(approved, observed)
    if diff["semantic_equal"] is not True:
        raise CanaryPreflightBlocked(
            "execution_config_fingerprint_mismatch", component_diff=diff,
        )
    if diff["provenance_known"] is not True:
        raise CanaryPreflightBlocked(
            "execution_config_provenance_unknown", component_diff=diff,
        )
    return {
        "status": "exact" if diff["provenance_equal"] else (
            "equivalent_provenance_variation"
        ),
        "component_diff": diff,
    }


class ExactBoundaryVerifier:
    """Re-reads every mutable input; fingerprint decisions stay Runtime-owned."""

    def __init__(
        self, *, snapshot_supplier: Callable[[], Mapping[str, Any]],
        cli_approved_plan_sha256: str, initial_plan_sha256: str,
        initial_approval_sha256: str, initial_launcher_sha256: str,
        initial_workload_manifest_hash: str,
        expected_scope: str = "C0A_FAKE_DRY_RUN",
        expected_profile_id: str | None = None,
        now: datetime | None = None,
    ) -> None:
        self.snapshot_supplier = snapshot_supplier
        self.cli_approved_plan_sha256 = cli_approved_plan_sha256
        self.initial_plan_sha256 = initial_plan_sha256
        self.initial_approval_sha256 = initial_approval_sha256
        self.initial_launcher_sha256 = initial_launcher_sha256
        self.initial_workload_manifest_hash = initial_workload_manifest_hash
        self.expected_scope = expected_scope
        self.expected_profile_id = expected_profile_id
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
        if self.expected_profile_id is None:
            approval, approval_identity, approval_kind = validate_canary_approval_document(
                snapshot["approval"], expected_scope=self.expected_scope,
                expected_plan_sha256=plan["plan_sha256"],
                expected_launcher_sha256=plan["launcher_sha256"], now=self.now,
            )
        else:
            profile = approval_profile(self.expected_profile_id)
            approval, approval_identity, approval_kind, _document_profile = (
                validate_registered_approval_document(
                    snapshot["approval"], expected_profile_id=profile.profile_id,
                    expected_scope=profile.approval_scope,
                    expected_plan_sha256=plan["plan_sha256"],
                    expected_launcher_sha256=plan["launcher_sha256"], now=self.now,
                )
            )
        _require(approval_kind != "final_approval_candidate",
                 "approval_candidate_not_executable")
        if self.expected_profile_id is not None and approval_kind in {
            "signed_smoke_approval", "signed_approval",
        }:
            _require("approval_candidate" in snapshot
                     and "authorization_patch" in snapshot,
                     "signed_approval_source_document_missing")
            validate_registered_signed_sources(
                self.expected_profile_id, approval, snapshot["approval_candidate"],
                snapshot["authorization_patch"], now=self.now,
            )
            validate_registered_signed_plan(
                self.expected_profile_id, approval, plan, now=self.now,
            )
        _require(approval_identity == self.initial_approval_sha256,
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
        execution_config_observation = None
        if plan["runtime_fingerprint_policy_version"] == "runtime-fingerprint-v2":
            execution_config_observation = validate_execution_config_prelaunch_v2(
                plan, snapshot.get("execution_config_components") or {},
            )
        else:
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
        return {
            "snapshot": snapshot, "plan": plan,
            "execution_config_observation": execution_config_observation,
        }

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
        observation = validated.get("execution_config_observation")
        if isinstance(observation, Mapping):
            receipt["execution_config_observation_status"] = observation["status"]
            receipt["execution_config_component_diff"] = observation["component_diff"]
        self.receipts.append(receipt)
        return receipt

    def __call__(self, request: BoundaryRequest) -> dict:
        return self.run_runtime_preflight(request, self.validate_inputs(request))
