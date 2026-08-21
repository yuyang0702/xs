"""Successor-aware, hash-only readiness for the post R1-PTR3 Short canary."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
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
CURRENT_SCHEMA = "R1PTR3CurrentRuntimeSuccessorV1"
CURRENT_DOMAIN = "novel-flywheel-r1-ptr3-current-runtime-successor-v1"
CURRENT_PROFILE = "ptr3_successor_current_runtime_v1"
CURRENT_BASELINE_BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
CURRENT_BASELINE_HEAD = "d8fc9f4ddb13375c7c3d70c7d5adbdfed5298fc9"
CURRENT_SUCCESSOR_RELATIVE_PATH = (
    "docs/superpowers/reports/sc-succ1/"
    "sc-succ1-current-successor-binding-v1.json"
)
CURRENT_SUCCESSOR_PATH = Path(__file__).resolve().parents[2] / (
    CURRENT_SUCCESSOR_RELATIVE_PATH
)
HISTORICAL_SUCCESSOR_RELATIVE_PATH = (
    "tests/fixtures/reliability/r0f/"
    "r1-ptr3-authorized-protected-source-successor-v1.json"
)
HISTORICAL_PTR3_SHA256 = (
    "bcba49fe1b20f1b4cb1f9284b181ede224bb860ce367870e9f3c46152cedda6c"
)
HISTORICAL_PTR3_BLOB_ID = "7683bc7298dca118c53f5a72cdcc4a85cba26887"
HISTORICAL_PTR3_REPORT_TREE_ID = "f2c9f4a32d26f6b9ab64838fbf58aec1109ee1ba"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


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


def _git(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=repo_root, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SuccessorReadinessError("current_successor_ancestry_broken") from exc


def _source_sha256(repo_root: Path, relative: str) -> str:
    path = repo_root / relative
    if not path.is_file():
        raise SuccessorReadinessError("current_successor_source_missing")
    return file_sha256(path)


def _manifest_exact(
    repo_root: Path, relative: str, expected: str,
    *, allowed_changed_paths: set[str],
) -> None:
    path = repo_root / relative
    if not path.is_file() or file_sha256(path) != expected:
        raise SuccessorReadinessError("current_successor_parent_manifest_mismatch")
    value = _read(path)
    entries: list[Any] = []
    for field in ("files", "entries", "report_files", "implementation_binding"):
        candidate = value.get(field)
        if isinstance(candidate, list):
            entries.extend(candidate)
    if not entries:
        raise SuccessorReadinessError("current_successor_parent_manifest_invalid")
    for entry in entries:
        target = str(entry.get("path") or "")
        digest = entry.get("sha256")
        target_path = repo_root / target
        if target in allowed_changed_paths:
            _git(repo_root, "rev-parse", f"{CURRENT_BASELINE_HEAD}:{target}")
            continue
        if not target_path.is_file() or file_sha256(target_path) != digest:
            raise SuccessorReadinessError("current_successor_parent_manifest_entry_mismatch")


def historical_ptr3_evidence_v1(repo_root: Path) -> dict[str, Any]:
    fixture_path = repo_root / HISTORICAL_SUCCESSOR_RELATIVE_PATH
    if not fixture_path.is_file():
        raise SuccessorReadinessError("ptr3_historical_evidence_missing")
    if file_sha256(fixture_path) != HISTORICAL_PTR3_SHA256:
        raise SuccessorReadinessError("ptr3_historical_sha256_mismatch")
    successor = _read(fixture_path)
    if (
        successor.get("schema")
        != "R1PTR3AuthorizedProtectedSourceSuccessorV1"
        or successor.get("phase") != "R1-PTR3"
        or successor.get("implementation_source_head")
        != "a6d16638bdc55c5639979be7e2b50ffb0d927461"
    ):
        raise SuccessorReadinessError("ptr3_successor_identity_mismatch")
    blob_id = _git(repo_root, "rev-parse", f"HEAD:{HISTORICAL_SUCCESSOR_RELATIVE_PATH}")
    if blob_id != HISTORICAL_PTR3_BLOB_ID:
        raise SuccessorReadinessError("ptr3_historical_blob_mismatch")
    report_tree_id = _git(
        repo_root, "rev-parse", "HEAD:docs/superpowers/reports/r1-ptr3",
    )
    if report_tree_id != HISTORICAL_PTR3_REPORT_TREE_ID:
        raise SuccessorReadinessError("ptr3_historical_tree_mismatch")
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
        "blob_id": blob_id,
        "report_tree_id": report_tree_id,
        "report_sha256": file_sha256(report),
        "test_receipt_sha256": file_sha256(receipt),
        "successor": successor,
    }


def _plan_route_projection(production_plan: Mapping[str, Any]) -> dict[str, Any]:
    routes = production_plan.get("approved_routes")
    planning = next(
        (route for route in routes or () if route.get("role") == "planning"), None,
    )
    if not isinstance(planning, Mapping):
        raise SuccessorReadinessError("current_successor_route_identity_mismatch")
    return {
        "provider_descriptor_definition_sha256": production_plan.get(
            "provider_descriptor_definition_sha256"
        ),
        "role_binding_manifest_definition_sha256": production_plan.get(
            "role_binding_manifest_definition_sha256"
        ),
        "planning": {
            "role": planning.get("role"),
            "primary": deepcopy(planning.get("primary")),
            "fallback": deepcopy(planning.get("fallback")),
        },
    }


def current_successor_plan_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    fingerprints = value["current_successor_evidence"]["fingerprints"]
    routes = value["current_successor_evidence"]["route_model_identity"]
    return {
        "approved_build_fingerprint": fingerprints["build_sha256"],
        "approved_execution_config_fingerprint": fingerprints["config_sha256"],
        "expected_runtime_execution_fingerprint": fingerprints["runtime_sha256"],
        "provider_descriptor_definition_sha256": routes[
            "provider_descriptor_definition_sha256"
        ],
        "role_binding_manifest_definition_sha256": routes[
            "role_binding_manifest_definition_sha256"
        ],
        "approved_routes": [deepcopy(routes["planning"])],
        "workloads": [{
            "prompt_policy_manifest_sha256": fingerprints["prompt_policy_sha256"],
        }],
    }


def _validate_current_repository_state(
    repo_root: Path, value: Mapping[str, Any],
) -> None:
    current = value["current_successor_evidence"]
    if current.get("branch") != CURRENT_BASELINE_BRANCH:
        raise SuccessorReadinessError("current_successor_branch_mismatch")
    if current.get("baseline_head") != CURRENT_BASELINE_HEAD:
        raise SuccessorReadinessError("current_successor_head_stale")
    if _git(repo_root, "branch", "--show-current") != CURRENT_BASELINE_BRANCH:
        raise SuccessorReadinessError("current_successor_branch_mismatch")
    head = _git(repo_root, "rev-parse", "HEAD")
    if _HEX40.fullmatch(head) is None:
        raise SuccessorReadinessError("current_successor_ancestry_broken")
    _git(repo_root, "merge-base", "--is-ancestor", CURRENT_BASELINE_HEAD, head)
    allowed = set(current.get("allowed_successor_seal_paths") or ())
    committed = set(filter(None, _git(
        repo_root, "diff", "--name-only", f"{CURRENT_BASELINE_HEAD}..{head}",
    ).splitlines()))
    if not committed.issubset(allowed):
        raise SuccessorReadinessError("current_successor_head_contains_unapproved_change")
    dirty = set()
    for line in _git(repo_root, "status", "--porcelain", "--untracked-files=all").splitlines():
        offset = 3 if len(line) >= 3 and line[2] == " " else 2
        relative = line[offset:].strip().replace("\\", "/")
        if " -> " in relative:
            relative = relative.split(" -> ", 1)[1]
        dirty.add(relative.strip('"'))
    if not dirty.issubset(allowed):
        raise SuccessorReadinessError("current_successor_worktree_contains_unapproved_change")


def validate_current_ptr3_successor_v1(
    *, repo_root: Path, production_plan: Mapping[str, Any],
    successor_path: Path | None = None,
) -> dict[str, Any]:
    path = successor_path or repo_root / CURRENT_SUCCESSOR_RELATIVE_PATH
    if not path.is_file():
        raise SuccessorReadinessError("current_successor_evidence_missing")
    value = _read(path)
    if value.get("schema") != CURRENT_SCHEMA or value.get("version") != 1:
        raise SuccessorReadinessError("current_successor_schema_unknown")
    if value.get("profile") != CURRENT_PROFILE:
        raise SuccessorReadinessError("current_successor_profile_unknown")
    body = deepcopy(value)
    digest = body.pop("definition_sha256", None)
    if digest != domain_sha256(CURRENT_DOMAIN, body):
        raise SuccessorReadinessError("current_successor_hash_mismatch")
    if value.get("readiness_status") != "exact":
        raise SuccessorReadinessError("current_successor_not_exact")
    historical = historical_ptr3_evidence_v1(repo_root)
    parent = value.get("historical_parent_evidence") or {}
    if (
        parent.get("sha256") != historical["successor_sha256"]
        or parent.get("blob_id") != historical["blob_id"]
        or parent.get("report_tree_id") != historical["report_tree_id"]
    ):
        raise SuccessorReadinessError("current_successor_historical_parent_mismatch")
    _validate_current_repository_state(repo_root, value)
    for entry in value.get("sealed_commit_ancestry") or ():
        parent_head = str(entry.get("parent") or "")
        child_head = str(entry.get("commit") or "")
        if _HEX40.fullmatch(parent_head) is None or _HEX40.fullmatch(child_head) is None:
            raise SuccessorReadinessError("current_successor_ancestry_invalid")
        _git(repo_root, "merge-base", "--is-ancestor", parent_head, child_head)
    for entry in value.get("current_protected_sources") or ():
        relative = str(entry.get("path") or "")
        if _source_sha256(repo_root, relative) != entry.get("sha256"):
            raise SuccessorReadinessError("current_successor_source_mismatch")
    for manifest in value.get("parent_manifests") or ():
        _manifest_exact(
            repo_root, str(manifest.get("path") or ""),
            str(manifest.get("sha256") or ""),
            allowed_changed_paths=set(
                value["current_successor_evidence"].get(
                    "allowed_successor_seal_paths"
                ) or ()
            ),
        )
    semantic = value.get("semantic_revalidation") or {}
    if (
        semantic.get("overall_status") != "exact"
        or semantic.get("stale_finding_count") != 0
        or int(semantic.get("required_case_count") or 0) < 15
    ):
        raise SuccessorReadinessError("ptr3_semantic_revalidation_not_exact")
    semantic_path = repo_root / str(semantic.get("path") or "")
    if not semantic_path.is_file() or file_sha256(semantic_path) != semantic.get("sha256"):
        raise SuccessorReadinessError("ptr3_semantic_revalidation_hash_mismatch")
    lineage = value.get("source_lineage") or {}
    lineage_path = repo_root / str(lineage.get("path") or "")
    if not lineage_path.is_file() or file_sha256(lineage_path) != lineage.get("sha256"):
        raise SuccessorReadinessError("current_successor_lineage_hash_mismatch")
    expected = current_successor_plan_projection(value)
    fingerprint_fields = (
        "approved_build_fingerprint", "approved_execution_config_fingerprint",
        "expected_runtime_execution_fingerprint",
    )
    if any(production_plan.get(field) != expected[field] for field in fingerprint_fields):
        raise SuccessorReadinessError("current_successor_fingerprint_mismatch")
    try:
        prompt = production_plan["workloads"][0]["prompt_policy_manifest_sha256"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SuccessorReadinessError("current_successor_prompt_identity_mismatch") from exc
    if prompt != expected["workloads"][0]["prompt_policy_manifest_sha256"]:
        raise SuccessorReadinessError("current_successor_prompt_identity_mismatch")
    if _plan_route_projection(production_plan) != _plan_route_projection(expected):
        raise SuccessorReadinessError("current_successor_route_identity_mismatch")
    compatibility = value.get("compatibility") or {}
    if any(
        (compatibility.get(name) or {}).get("status") != "pass"
        for name in ("ptr9", "ptr10", "sc_ic1")
    ):
        raise SuccessorReadinessError("current_successor_compatibility_not_exact")
    if value.get("external_actions") != {
        "credential": 0, "provider_client": 0, "network": 0,
        "model": 0, "paid": 0,
    }:
        raise SuccessorReadinessError("current_successor_external_actions_nonzero")
    return deepcopy(value)


def _successor_evidence(
    repo_root: Path, production_plan: Mapping[str, Any],
) -> dict[str, Any]:
    historical = historical_ptr3_evidence_v1(repo_root)
    current = validate_current_ptr3_successor_v1(
        repo_root=repo_root, production_plan=production_plan,
    )
    return {
        **historical,
        "current_successor_sha256": file_sha256(
            repo_root / CURRENT_SUCCESSOR_RELATIVE_PATH
        ),
        "current_successor": current,
    }


def build_ptr3_readiness_v1(
    *, repo_root: Path, production_plan: Mapping[str, Any],
    planning_domain_validator_sha256: str,
) -> dict[str, Any]:
    evidence = _successor_evidence(repo_root, production_plan)
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
        "ptr3_current_successor_sha256": evidence["current_successor_sha256"],
        "ptr3_current_successor_definition_sha256": evidence[
            "current_successor"
        ]["definition_sha256"],
        "ptr3_current_source_lineage_sha256": evidence["current_successor"][
            "source_lineage"
        ]["sha256"],
        "ptr3_current_semantic_revalidation_sha256": evidence[
            "current_successor"
        ]["semantic_revalidation"]["sha256"],
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
        "ptr3_current_successor_sha256",
        "ptr3_current_successor_definition_sha256",
        "ptr3_current_source_lineage_sha256",
        "ptr3_current_semantic_revalidation_sha256",
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
    evidence = _successor_evidence(repo_root, production_plan)
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
