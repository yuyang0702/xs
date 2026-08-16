"""Canary-only collection profiles for fingerprint evidence comparison."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)


R1_D3_OFFLINE_PROFILE_ID = "r1-d3-offline-fingerprint-profile-v1"
PRODUCTION_MIRROR_SHORT_PROFILE_ID = "production_mirror_short_v1"
FINGERPRINT_COLLECTION_PROFILE_NOT_COMPARABLE = (
    "NOT_COMPARABLE_CROSS_COLLECTION_PROFILE"
)
NOT_COMPARABLE_REASON = "fingerprint_collection_profile_not_comparable"
R1_D3_EVIDENCE_COMMIT = "4c28b162264d15c9dc020b623782116b7d1a2b6c"
R1_D3_ROUTE_MODEL_BASELINE_SHA256 = (
    "787efa24c4c243d47efb41e2ddc613dd627563a0318e1b087bb07a57af6561ea"
)
READINESS_SCHEMA = "R1D3ProductionMirrorReadinessBindingV1"
READINESS_DOMAIN = "novel-flywheel-r1-d3-production-mirror-readiness-v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_KNOWN_PROFILES = {
    R1_D3_OFFLINE_PROFILE_ID: {
        "purpose": "r1_d3_narrow_fix_code_and_evidence_validation",
        "execution_identity_domain": "offline_empty_configuration",
    },
    PRODUCTION_MIRROR_SHORT_PROFILE_ID: {
        "purpose": "short_completion_materialization_preflight_and_runner",
        "execution_identity_domain": "production_mirror_execution_environment",
    },
}


class FingerprintCollectionProfileError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def fingerprint_collection_profile_definitions_v1() -> dict[str, Any]:
    body = {
        "schema": "FingerprintCollectionProfileRegistryV1",
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "profiles": deepcopy(_KNOWN_PROFILES),
        "cross_profile_execution_config_comparison": "not_comparable_by_design",
        "cross_profile_runtime_execution_comparison": "not_comparable_by_design",
        "cross_profile_build_comparison": "exact_required",
        "cross_profile_prompt_policy_comparison": "exact_required",
        "not_comparable_status": FINGERPRINT_COLLECTION_PROFILE_NOT_COMPARABLE,
        "not_comparable_reason_code": NOT_COMPARABLE_REASON,
    }
    return {
        **body,
        "definition_sha256": domain_sha256(
            "novel-flywheel-fingerprint-collection-profile-registry-v1", body,
        ),
    }


def _require_profile(value: Mapping[str, Any]) -> str:
    profile_id = value.get("collection_profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise FingerprintCollectionProfileError(
            "fingerprint_collection_profile_missing"
        )
    if profile_id not in _KNOWN_PROFILES:
        raise FingerprintCollectionProfileError(
            "fingerprint_collection_profile_unknown"
        )
    return profile_id


def _require_hash(value: Any, reason_code: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise FingerprintCollectionProfileError(reason_code)
    return value


def compare_execution_fingerprint_profiles_v1(
    expected: Mapping[str, Any], actual: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare execution hashes only when their collection domain is identical."""

    expected_profile = _require_profile(expected)
    actual_profile = _require_profile(actual)
    fields = (
        ("execution_config_sha256", "execution_config_fingerprint_mismatch"),
        ("runtime_execution_sha256", "runtime_execution_fingerprint_mismatch"),
    )
    for field, reason in fields:
        _require_hash(expected.get(field), reason)
        _require_hash(actual.get(field), reason)
    if expected_profile != actual_profile:
        comparison = {
            "status": FINGERPRINT_COLLECTION_PROFILE_NOT_COMPARABLE,
            "reason_code": NOT_COMPARABLE_REASON,
            "equal": None,
            "expected_collection_profile_id": expected_profile,
            "actual_collection_profile_id": actual_profile,
        }
        return {
            "schema": "ExecutionFingerprintCollectionProfileComparisonV1",
            "version": 1,
            "expected_collection_profile_id": expected_profile,
            "actual_collection_profile_id": actual_profile,
            "execution_config_comparison": deepcopy(comparison),
            "runtime_execution_comparison": deepcopy(comparison),
            "comparison_status": FINGERPRINT_COLLECTION_PROFILE_NOT_COMPARABLE,
        }
    results: dict[str, Any] = {}
    for field, reason in fields:
        if expected[field] != actual[field]:
            raise FingerprintCollectionProfileError(reason)
        results[field.replace("_sha256", "_comparison")] = {
            "status": "exact", "reason_code": "exact", "equal": True,
            "collection_profile_id": expected_profile,
        }
    return {
        "schema": "ExecutionFingerprintCollectionProfileComparisonV1",
        "version": 1,
        "expected_collection_profile_id": expected_profile,
        "actual_collection_profile_id": actual_profile,
        **results,
        "comparison_status": "exact",
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_r1_d3_evidence_v1(repo_root: Path) -> dict[str, Any]:
    """Read the sealed V1 evidence without coercing it into a new profile."""

    report_root = repo_root / "docs" / "superpowers" / "reports" / "r1-d3"
    manifest_path = report_root / "r1-d3-sha256-manifest-v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "R1D3Sha256ManifestV1":
        raise FingerprintCollectionProfileError("r1_d3_evidence_schema_unknown")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise FingerprintCollectionProfileError("r1_d3_evidence_manifest_invalid")
    for entry in files:
        path = repo_root / str(entry.get("path", ""))
        if (
            not path.is_file()
            or path.stat().st_size != entry.get("bytes")
            or _file_sha256(path) != entry.get("sha256")
        ):
            raise FingerprintCollectionProfileError(
                "r1_d3_evidence_manifest_mismatch"
            )
    receipt = json.loads(
        (report_root / "r1-d3-validation-receipt-v1.json").read_text(
            encoding="utf-8"
        )
    )
    prompt = json.loads(
        (report_root / "r1-d3-prompt-policy-manifest-v1.json").read_text(
            encoding="utf-8"
        )
    )
    if (
        receipt.get("schema") != "R1D3ValidationReceiptV1"
        or receipt.get("runtime_fingerprints", {}).get("profile")
        != R1_D3_OFFLINE_PROFILE_ID
    ):
        raise FingerprintCollectionProfileError(
            "r1_d3_collection_profile_mismatch"
        )
    return {
        "manifest_status": "exact",
        "manifest_entry_count": len(files),
        "manifest_sha256": _file_sha256(manifest_path),
        "validation_receipt_sha256": _file_sha256(
            report_root / "r1-d3-validation-receipt-v1.json"
        ),
        "prompt_policy_manifest_file_sha256": _file_sha256(
            report_root / "r1-d3-prompt-policy-manifest-v1.json"
        ),
        "validation_receipt": receipt,
        "prompt_policy_manifest": prompt,
    }


def retry_topology_definition_sha256(
    *, same_scope_retry_limit: int, maximum_draft_attempts: int,
    maximum_total_model_calls: int,
) -> str:
    return domain_sha256("novel-flywheel-r1-d3-retry-topology-v1", {
        "same_scope_retry_limit": same_scope_retry_limit,
        "maximum_draft_attempts": maximum_draft_attempts,
        "maximum_total_model_calls": maximum_total_model_calls,
    })


def route_model_binding_definition_sha256(plan: Mapping[str, Any]) -> str:
    return domain_sha256("novel-flywheel-canary-route-model-binding-v1", {
        "provider_descriptor_definition_sha256": plan[
            "provider_descriptor_definition_sha256"
        ],
        "role_binding_manifest_definition_sha256": plan[
            "role_binding_manifest_definition_sha256"
        ],
        "approved_routes": plan["approved_routes"],
    })


def build_r1_d3_production_mirror_readiness_binding_v1(
    *, repo_root: Path, production_plan: Mapping[str, Any],
    draft_validator_policy_sha256: str, final_review_definition_sha256: str,
    maintenance_definition_sha256: str,
) -> dict[str, Any]:
    evidence = load_r1_d3_evidence_v1(repo_root)
    receipt = evidence["validation_receipt"]
    runtime = receipt["runtime_fingerprints"]
    prompt = receipt["prompt_policy"]
    retry = receipt["retry_and_route_parity"]
    completion = receipt["completion_contract_bindings"]
    production_prompt = production_plan["workloads"][0][
        "prompt_policy_manifest_sha256"
    ]
    topology_sha = retry_topology_definition_sha256(
        same_scope_retry_limit=retry["same_scope_retry_limit_after"],
        maximum_draft_attempts=retry["maximum_draft_attempts_after"],
        maximum_total_model_calls=production_plan["budgets"][
            "maximum_total_model_calls"
        ],
    )
    route_model_sha = route_model_binding_definition_sha256(production_plan)
    cross_profile = compare_execution_fingerprint_profiles_v1(
        {
            "collection_profile_id": R1_D3_OFFLINE_PROFILE_ID,
            "execution_config_sha256": runtime["config_after_sha256"],
            "runtime_execution_sha256": runtime["runtime_after_sha256"],
        },
        {
            "collection_profile_id": PRODUCTION_MIRROR_SHORT_PROFILE_ID,
            "execution_config_sha256": production_plan[
                "approved_execution_config_fingerprint"
            ],
            "runtime_execution_sha256": production_plan[
                "expected_runtime_execution_fingerprint"
            ],
        },
    )
    exact_requirements = {
        "build_comparison": (
            runtime["build_after_sha256"]
            == production_plan["approved_build_fingerprint"]
        ),
        "prompt_policy_comparison": prompt["manifest_after_sha256"]
        == production_prompt,
        "validator_policy_comparison": completion[
            "draft_validator_policy_before_after_sha256"
        ] == draft_validator_policy_sha256,
        "retry_topology_comparison": (
            retry["same_scope_retry_limit_after"] == 2
            and retry["maximum_draft_attempts_after"] == 3
            and production_plan["budgets"]["maximum_total_model_calls"] == 48
        ),
        "route_model_binding_comparison": (
            retry["provider_or_model_binding_changed"] is False
            and retry["primary_fallback_schedule_changed"] is False
            and route_model_sha == R1_D3_ROUTE_MODEL_BASELINE_SHA256
        ),
        "final_review_comparison": completion["final_review_after_sha256"]
        == final_review_definition_sha256,
        "maintenance_comparison": completion["maintenance_after_sha256"]
        == maintenance_definition_sha256,
    }
    mismatched = [name for name, exact in exact_requirements.items() if not exact]
    if mismatched:
        reason = mismatched[0].replace("_comparison", "_mismatch")
        raise FingerprintCollectionProfileError(reason)
    registry = fingerprint_collection_profile_definitions_v1()
    body = {
        "schema": READINESS_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "r1_d3_evidence_commit": R1_D3_EVIDENCE_COMMIT,
        "r1_d3_evidence_manifest_sha256": evidence["manifest_sha256"],
        "r1_d3_evidence_manifest_status": "exact",
        "r1_d3_evidence_manifest_entry_count": evidence["manifest_entry_count"],
        "r1_d3_build_sha256": runtime["build_after_sha256"],
        "r1_d3_initial_prompt_sha256": prompt["initial_after_sha256"],
        "r1_d3_retry_prompt_sha256": prompt["retry_after_sha256"],
        "r1_d3_prompt_policy_sha256": prompt["manifest_after_sha256"],
        "r1_d3_validator_policy_sha256": completion[
            "draft_validator_policy_before_after_sha256"
        ],
        "r1_d3_offline_collection_profile_id": R1_D3_OFFLINE_PROFILE_ID,
        "r1_d3_offline_config_sha256": runtime["config_after_sha256"],
        "r1_d3_offline_runtime_sha256": runtime["runtime_after_sha256"],
        "target_execution_collection_profile_id": (
            PRODUCTION_MIRROR_SHORT_PROFILE_ID
        ),
        "production_mirror_build_sha256": production_plan[
            "approved_build_fingerprint"
        ],
        "production_mirror_config_sha256": production_plan[
            "approved_execution_config_fingerprint"
        ],
        "production_mirror_runtime_sha256": production_plan[
            "expected_runtime_execution_fingerprint"
        ],
        "production_mirror_prompt_policy_sha256": production_prompt,
        "retry_topology_definition_sha256": topology_sha,
        "route_model_binding_definition_sha256": (
            route_model_sha
        ),
        "cross_profile_config_comparison": "not_comparable_by_design",
        "cross_profile_runtime_comparison": "not_comparable_by_design",
        "cross_profile_reason_code": NOT_COMPARABLE_REASON,
        "cross_profile_typed_status": FINGERPRINT_COLLECTION_PROFILE_NOT_COMPARABLE,
        **{name: "exact" for name in exact_requirements},
        "structured_finding_propagation_enabled": receipt["binding_proofs"][
            "retry_input_contains_actionable_finding"
        ],
        "same_scope_retry_limit": 2,
        "maximum_draft_attempts": 3,
        "maximum_total_model_calls": 48,
        "external_action_counters": {
            "credential_lookup_count": 0,
            "provider_client_creation_count": 0,
            "network_call_count": 0,
            "model_call_count": 0,
            "paid_model_call_count": 0,
        },
        "live_parity_status": (
            "exact" if receipt["live_parity"]["before_after_exact"] else "blocked"
        ),
        "residual_risks": deepcopy(receipt["residual_risks"]),
        "collection_profile_registry_definition_sha256": registry[
            "definition_sha256"
        ],
        "readiness_status": "exact",
        "raw_prompt_included": False,
        "raw_story_text_included": False,
        "credentials_or_headers_included": False,
        "cross_profile_observation_sha256": domain_sha256(
            "novel-flywheel-cross-profile-comparison-observation-v1",
            cross_profile,
        ),
    }
    return {
        **body,
        "definition_sha256": domain_sha256(READINESS_DOMAIN, body),
    }


def validate_r1_d3_production_mirror_readiness_binding_v1(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if value.get("schema") != READINESS_SCHEMA or value.get("version") != 1:
        raise FingerprintCollectionProfileError("r1_d3_readiness_schema_unknown")
    _require_profile({
        "collection_profile_id": value.get(
            "r1_d3_offline_collection_profile_id"
        )
    })
    target = value.get("target_execution_collection_profile_id")
    if target != PRODUCTION_MIRROR_SHORT_PROFILE_ID:
        raise FingerprintCollectionProfileError(
            "target_execution_collection_profile_mismatch"
        )
    for field in (
        "r1_d3_build_sha256", "r1_d3_initial_prompt_sha256",
        "r1_d3_retry_prompt_sha256", "r1_d3_prompt_policy_sha256",
        "r1_d3_validator_policy_sha256", "r1_d3_offline_config_sha256",
        "r1_d3_offline_runtime_sha256", "production_mirror_build_sha256",
        "production_mirror_config_sha256", "production_mirror_runtime_sha256",
        "production_mirror_prompt_policy_sha256",
        "retry_topology_definition_sha256",
        "route_model_binding_definition_sha256",
        "collection_profile_registry_definition_sha256",
        "cross_profile_observation_sha256", "definition_sha256",
    ):
        _require_hash(value.get(field), f"{field}_invalid")
    for field in (
        "build_comparison", "prompt_policy_comparison",
        "validator_policy_comparison", "retry_topology_comparison",
        "route_model_binding_comparison", "final_review_comparison",
        "maintenance_comparison", "readiness_status", "live_parity_status",
    ):
        if value.get(field) != "exact":
            raise FingerprintCollectionProfileError(
                field.replace("_comparison", "_mismatch")
            )
    if (
        value.get("cross_profile_config_comparison")
        != "not_comparable_by_design"
        or value.get("cross_profile_runtime_comparison")
        != "not_comparable_by_design"
        or value.get("cross_profile_reason_code") != NOT_COMPARABLE_REASON
        or value.get("cross_profile_typed_status")
        != FINGERPRINT_COLLECTION_PROFILE_NOT_COMPARABLE
    ):
        raise FingerprintCollectionProfileError(
            "cross_profile_comparison_semantics_mismatch"
        )
    body = deepcopy(dict(value))
    digest = body.pop("definition_sha256", None)
    if digest != domain_sha256(READINESS_DOMAIN, body):
        raise FingerprintCollectionProfileError("r1_d3_readiness_hash_mismatch")
    return deepcopy(dict(value))
