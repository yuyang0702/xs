"""Successor-aware, hash-only readiness for the post R1-PTR3 Short canary."""

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

from .artifact_hash import file_sha256


PTR3_SCHEMA = "ShortCompletionPTR3ReadinessBindingV1"
PTR3_DOMAIN = "novel-flywheel-short-completion-ptr3-readiness-v1"
DRAFT_SCHEMA = "R1D3SuccessorReadinessBindingV1"
DRAFT_DOMAIN = "novel-flywheel-r1-d3-successor-readiness-v1"
PTR3_EVIDENCE_COMMIT = "ab458a016caaed2148432c8c67b27734c61fe3ed"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class SuccessorReadinessError(RuntimeError):
    pass


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SuccessorReadinessError("successor_document_not_object")
    return value


def _require_hash(value: Any, reason: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise SuccessorReadinessError(reason)
    return value


def _seal(schema: str, domain: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        "schema": schema,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        **deepcopy(dict(payload)),
    }
    return {**body, "definition_sha256": domain_sha256(domain, body)}


def _validate_seal(value: Mapping[str, Any], schema: str, domain: str) -> dict[str, Any]:
    if value.get("schema") != schema or value.get("version") != 1:
        raise SuccessorReadinessError("successor_readiness_schema_unknown")
    body = deepcopy(dict(value))
    digest = body.pop("definition_sha256", None)
    if digest != domain_sha256(domain, body):
        raise SuccessorReadinessError("successor_readiness_hash_mismatch")
    if value.get("readiness_status") != "exact":
        raise SuccessorReadinessError("successor_readiness_not_exact")
    return deepcopy(dict(value))


def _successor_evidence(repo_root: Path) -> dict[str, Any]:
    fixture_path = repo_root / (
        "tests/fixtures/reliability/r0f/"
        "r1-ptr3-authorized-protected-source-successor-v1.json"
    )
    successor = _read(fixture_path)
    if (
        successor.get("schema")
        != "R1PTR3AuthorizedProtectedSourceSuccessorV1"
        or successor.get("phase") != "R1-PTR3"
        or successor.get("implementation_source_head")
        != "a6d16638bdc55c5639979be7e2b50ffb0d927461"
    ):
        raise SuccessorReadinessError("ptr3_successor_identity_mismatch")
    for entry in successor.get("current_protected_sources", []):
        path = repo_root / str(entry.get("path") or "")
        canonical = (
            path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            if path.is_file() else b""
        )
        if (
            not path.is_file()
            or hashlib.sha256(canonical).hexdigest()
            != entry.get("sha256")
        ):
            raise SuccessorReadinessError("ptr3_successor_source_mismatch")
    report_root = repo_root / "docs/superpowers/reports/r1-ptr3"
    report = report_root / "r1-ptr3-final-report-v1.md"
    receipt = report_root / "r1-ptr3-test-receipt-v1.json"
    receipt_value = _read(receipt)
    if (
        receipt_value.get("gate")
        != "R1_PTR3_PLANNING_REPAIR_FINDING_PROPAGATION_FIX_READY"
        or receipt_value.get("external_counters", {}).get("paid_model_calls") != 0
    ):
        raise SuccessorReadinessError("ptr3_evidence_gate_mismatch")
    return {
        "successor_sha256": file_sha256(fixture_path),
        "report_sha256": file_sha256(report),
        "test_receipt_sha256": file_sha256(receipt),
        "successor": successor,
    }


def build_ptr3_readiness_v1(
    *, repo_root: Path, production_plan: Mapping[str, Any],
    planning_domain_validator_sha256: str,
) -> dict[str, Any]:
    evidence = _successor_evidence(repo_root)
    workflows = file_sha256(repo_root / "src/novel_flywheel/workflows.py")
    runtime = file_sha256(repo_root / "src/novel_flywheel/contract_runtime.py")
    diagnostics = file_sha256(
        repo_root / "src/novel_flywheel/planning_repair_diagnostics.py"
    )
    prompt_policy = production_plan["workloads"][0][
        "prompt_policy_manifest_sha256"
    ]
    initial = domain_sha256("ptr3-planning-initial-request-v1", {
        "workflows": workflows, "boundary": "planning_initial",
        "retry_findings_present": False,
    })
    first_repair = domain_sha256("ptr3-planning-first-repair-request-v1", {
        "workflows": workflows, "boundary": "planning_repair_patch",
        "prior_domain_failure": False,
    })
    retry_contract = domain_sha256("ptr3-planning-retry-contract-v1", {
        "contract_runtime": runtime, "diagnostics": diagnostics,
        "schema": "PlanningRepairRetryFindingV1", "version": 1,
    })
    bounds = domain_sha256("ptr3-planning-finding-bounds-v1", {
        "maximum_findings": 8, "maximum_utf8_bytes": 8192,
        "rule_chars": 160, "path_chars": 256,
        "invariant_chars": 160, "validator_chars": 160,
        "hint_chars": 80, "oversize_action": "fail_closed_before_dispatch",
    })
    return _seal(PTR3_SCHEMA, PTR3_DOMAIN, {
        "ptr3_evidence_commit": PTR3_EVIDENCE_COMMIT,
        "ptr3_successor_baseline_sha256": evidence["successor_sha256"],
        "ptr3_report_sha256": evidence["report_sha256"],
        "ptr3_test_receipt_sha256": evidence["test_receipt_sha256"],
        "current_build_sha256": production_plan["approved_build_fingerprint"],
        "current_config_sha256": production_plan[
            "approved_execution_config_fingerprint"
        ],
        "current_runtime_sha256": production_plan[
            "expected_runtime_execution_fingerprint"
        ],
        "current_prompt_policy_sha256": prompt_policy,
        "initial_planning_request_sha256": initial,
        "first_planning_repair_request_sha256": first_repair,
        "retry_after_domain_failure_contract_sha256": retry_contract,
        "planning_domain_validator_sha256": planning_domain_validator_sha256,
        "finding_contract_schema": "PlanningRepairRetryFindingV1",
        "finding_contract_version": 1,
        "finding_contract_sha256": domain_sha256(
            "ptr3-finding-contract-v1", {"diagnostics": diagnostics}
        ),
        "finding_bounds_policy_sha256": bounds,
        "expected_stale_finding_count": 0,
        "repair_scope_identity": "exact_hash_bound_current_patch_scope",
        "route_model_parity": "exact",
        "retry_fallback_parity": "exact",
        "production_output_budget_parity": "exact",
        "verified_recovery_defect": (
            "planning.targeted_repair_finding_not_propagated=fixed"
        ),
        "historical_call7_primary_root_cause": "unclosed",
        "planning_repair_scope_mutation": "residual_unproven",
        "provider_terminal_amplifier_shape": "residual_unclosed",
        "readiness_status": "exact",
        "raw_prompt_included": False,
        "raw_story_included": False,
        "credentials_or_headers_included": False,
    })


def validate_ptr3_readiness_v1(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _validate_seal(value, PTR3_SCHEMA, PTR3_DOMAIN)
    for field in (
        "ptr3_successor_baseline_sha256", "current_build_sha256",
        "current_config_sha256", "current_runtime_sha256",
        "current_prompt_policy_sha256", "initial_planning_request_sha256",
        "first_planning_repair_request_sha256",
        "retry_after_domain_failure_contract_sha256",
        "planning_domain_validator_sha256", "finding_contract_sha256",
        "finding_bounds_policy_sha256",
    ):
        _require_hash(result.get(field), f"{field}_invalid")
    return result


def build_r1_d3_successor_readiness_v1(
    *, repo_root: Path, production_plan: Mapping[str, Any],
    draft_validator_sha256: str, mixed_script_sha256: str,
) -> dict[str, Any]:
    evidence = _successor_evidence(repo_root)
    workflows = file_sha256(repo_root / "src/novel_flywheel/workflows.py")
    return _seal(DRAFT_SCHEMA, DRAFT_DOMAIN, {
        "ptr3_successor_baseline_sha256": evidence["successor_sha256"],
        "production_mirror_build_sha256": production_plan[
            "approved_build_fingerprint"
        ],
        "production_mirror_config_sha256": production_plan[
            "approved_execution_config_fingerprint"
        ],
        "production_mirror_runtime_sha256": production_plan[
            "expected_runtime_execution_fingerprint"
        ],
        "production_mirror_prompt_policy_sha256": production_plan["workloads"][0][
            "prompt_policy_manifest_sha256"
        ],
        "draft_initial_request_sha256": domain_sha256(
            "r1-d3-current-draft-initial-v1", {"workflows": workflows}
        ),
        "draft_retry_contract_sha256": domain_sha256(
            "r1-d3-current-draft-retry-v1", {
                "workflows": workflows,
                "finding_contract": "DraftRetryFindingV1",
            },
        ),
        "draft_validator_sha256": draft_validator_sha256,
        "mixed_script_policy_sha256": mixed_script_sha256,
        "structured_draft_finding_propagation": "enabled",
        "draft_retry_count_parity": "exact",
        "draft_maximum_attempts": 3,
        "draft_retry_scope_too_broad": "residual",
        "readiness_status": "exact",
        "historical_manifest_rewritten": False,
        "raw_prompt_included": False,
        "raw_story_included": False,
    })


def validate_r1_d3_successor_readiness_v1(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    result = _validate_seal(value, DRAFT_SCHEMA, DRAFT_DOMAIN)
    for field in (
        "ptr3_successor_baseline_sha256", "production_mirror_build_sha256",
        "production_mirror_config_sha256", "production_mirror_runtime_sha256",
        "production_mirror_prompt_policy_sha256", "draft_initial_request_sha256",
        "draft_retry_contract_sha256", "draft_validator_sha256",
        "mixed_script_policy_sha256",
    ):
        _require_hash(result.get(field), f"{field}_invalid")
    return result
