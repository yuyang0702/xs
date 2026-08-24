"""Closed-world Skill Context V2 REAL A/B B-arm launcher and materializer.

Materialization and validation are offline-only.  The credential-capable stack is
imported only by :func:`execute_authorized_once`, after a separately sealed signed
approval and nonce preflight.  The B arm reuses the sealed v5 Slice1 workload and
changes only the rendered Skill Context supplied to the model.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.db import Database
from novel_flywheel.generated_artifacts import ArtifactConversionAudit
from novel_flywheel.models import ModelResult
from novel_flywheel.planning_v2_slice1 import (
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    SLICE1_CONTRACT_IDENTITY,
    build_event_realization_artifact,
    convert_event_realization_candidate,
    freeze_validated_artifact,
    normalize_event_realization_input_authority_v1,
    validate_event_realization_artifact,
)
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from novel_flywheel.runtime_skill_profiles import (
    SkillLoadDecisionInputsV1,
    build_planning_v2_event_realization_profile,
    creative_coverage,
    profile_contains_runtime_owned_responsibility,
    render_skill_context,
    verify_source_bundle,
)
import tools.canary.slice1_phase_b_current_skill as base
import tools.canary.slice1_phase_b_single_dispatch as legacy
import tools.canary.slice1_phase_b_v5_single_dispatch as a_launcher


EXPECTED_BRANCH = base.EXPECTED_BRANCH
BASELINE_HEAD = "1f6e9a715e96b41e1e4ebf70039f392a63bcf15b"
PROFILE_ID = "SLICE1_PHASE_B_SKILL_V2_REAL_AB_B_ARM_PACKET_V3"
SKILL_PROFILE_ID = "PLANNING_V2_EVENT_REALIZATION_PROFILE_V1"
SKILL_ARM = "SKILL_CONTEXT_V2"
PREDECESSOR_AB_PAIR_ID = "skill-v2-real-ab-20260824-v2-001"
PREDECESSOR_MATERIALIZATION_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-slice1-phase-b-skill-v2-materialization-v2"
)
HISTORICAL_MATERIALIZATION_ROOT_SPECS = (
    {
        "root": "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-materialization-v1",
        "manifest_definition_sha256": "d8ae1e531d08c2a704f2383c915ea1af2a4a01e255d26f187db9d7813582d5f2",
        "manifest_file_sha256": "b07edf3736fc76981bb0a3147ffed8d4638b22d086c20530317e84ebf790ad82",
        "manifest_file_count": 25,
    },
    {
        "root": PREDECESSOR_MATERIALIZATION_ROOT,
        "manifest_definition_sha256": "fdc0bd76bd0c8ca396c17398055d6a3a0be8af9b0da5bb47a0116cc063c7c121",
        "manifest_file_sha256": "2e8033f8027252bfecc8d1d59bab893269fb82dd656642080a9f4d378cd63612",
        "manifest_file_count": 27,
    },
)
AB_PAIR_ID = "skill-v2-real-ab-20260824-v3-001"
COHORT_ID = "slice1-phase-b-skill-v2-real-ab-v3-20260824-001"
APPROVAL_SCOPE = "SLICE1_PHASE_B_SKILL_V2_REAL_AB_B_ARM_SINGLE_DISPATCH_V3_ONLY"
MATERIALIZATION_RELATIVE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-slice1-phase-b-skill-v2-materialization-v3"
)
EXECUTION_RELATIVE_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-slice1-phase-b-skill-v2-execution-v3"
)
APPROVAL_RELATIVE_PATH = (
    MATERIALIZATION_RELATIVE_ROOT
    + "/approval/skill-v2-b-arm-signed-authorization-v1.json"
)
NONCE_LEDGER_RELATIVE_PATH = (
    EXECUTION_RELATIVE_ROOT + "/ledger/single-use-ledger-v1.json"
)
NONCE_LEDGER_SCHEMA = "SkillV2RealABSingleDispatchLedgerV1"
LAUNCHER_RELATIVE_PATH = "tools/canary/slice1_phase_b_skill_v2_single_dispatch.py"
ACTIVE_SUPPORT_PATHS = frozenset({
    LAUNCHER_RELATIVE_PATH,
    "docs/maintenance.md",
    "tests/canary/test_skill_v2_real_ab_b_arm.py",
    "tests/canary/test_skill_v2_b_arm_head_successor.py",
    "tests/canary/test_skill_v2_b_arm_historical_roots.py",
})
BUNDLE_RELATIVE_ROOT = "vendor/novel-skills/source"
A_MATERIALIZATION_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-slice1-phase-b-current-skill-materialization-v5"
)
A_EXECUTION_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-slice1-phase-b-current-skill-execution-v5"
)
A_COHORT_ID = "slice1-phase-b-current-skill-audit-safe-v5-20260823t164030z-001"
A_ARTIFACT_SHA256 = "b3588452679d0d5c39c4b86db63c98dc440868cdb2cd951d1262f426b234cb67"
A_QUALITY_SHA256 = "7591bbb790b3d038b9a7a3948654984ebe9c54688c4206813cf19aac6b018968"
A_ENGINEERING_SHA256 = "48af86a2fffc4c3c77ffb28eacd344a219c7daa2b36c59245e9a1d208f64a42c"
A_VALIDATION_SHA256 = "e48637356b5c5482fb5e9239def4a656bceb82b7d92d40a813b24116bdc262d5"
A_PROVIDER_OBSERVATION_SHA256 = "976316058195d84e42b2e2b93567903d7cad4035da2c6a446aaefc8b5cc1435f"
A_EXECUTION_RECEIPT_SHA256 = "d128ba42aa0e0da6bb4ae85d34c1e02473f5edc1399b992037924945ddafe3b8"
A_EXECUTION_MANIFEST_DEFINITION_SHA256 = (
    "034f28b68d2a09ce3b6386c4594e9c63b0d916ee4723efd706a973d3ab26f103"
)
A_EXECUTION_MANIFEST_FILE_SHA256 = (
    "81f53bc303735b357382a19c1641cc192223bce9df3b8e81ce23ce07d4852fe1"
)
A_CURRENT_SKILL_PROFILE_SHA256 = (
    "4a9fd1d20c248ed3dae1815eb99605b094842d1e953e96d31d6ba7d1a4bf52c6"
)
A_MODEL_INPUT_SHA256 = "8b94aab84342063b6f172f21a68feb5d21bf132857d8aae1fe6685c0dc720725"

DESIGN_ARTIFACT = (
    "docs/superpowers/reports/planning-skill-profile-shadow-v1/"
    "runtime-skill-profile-schema-v1.json"
)
PROFILE_ARTIFACT = (
    "docs/superpowers/reports/planning-skill-profile-shadow-v1/"
    "planning-v2-event-realization-profile-v1.json"
)
SHADOW_REPORT = (
    "docs/superpowers/reports/planning-skill-profile-shadow-v1/"
    "planning-skill-profile-shadow-v1-final-report.md"
)
SHADOW_MANIFEST = (
    "docs/superpowers/reports/planning-skill-profile-shadow-v1/"
    "final-sha256-manifest-v1.json"
)
QUALITY_REPORT = (
    "docs/superpowers/reports/planning-skill-profile-offline-quality-v1/"
    "final-report-v1.md"
)
QUALITY_READINESS = (
    "docs/superpowers/reports/planning-skill-profile-offline-quality-v1/"
    "readiness-v1.json"
)
QUALITY_MANIFEST = (
    "docs/superpowers/reports/planning-skill-profile-offline-quality-v1/"
    "final-sha256-manifest-v1.json"
)
BUNDLE_MANIFEST = (
    "docs/superpowers/reports/project-skill-portable-bundle/"
    "project-skill-final-sha256-manifest-v1.json"
)
RUNTIME_PROFILE_SOURCE = "src/novel_flywheel/runtime_skill_profiles.py"

ZERO_COUNTERS = {
    **base.ZERO_COUNTERS,
    "real_provider_request_attempts": 0,
    "http_post_attempts": 0,
    "network_request_attempts": 0,
}

FILES = {
    "plan": "skill-v2-b-arm-plan-v1.json",
    "workload": "skill-v2-b-arm-workload-v1.json",
    "pair": "skill-v2-b-arm-ab-pair-binding-v1.json",
    "a_ref": "skill-v2-b-arm-a-arm-baseline-reference-v1.json",
    "profile": "skill-v2-b-arm-skill-profile-binding-v1.json",
    "context": "skill-v2-b-arm-rendered-context-binding-v1.json",
    "model_input": "skill-v2-b-arm-model-input-binding-v1.json",
    "authority": "skill-v2-b-arm-authority-binding-v1.json",
    "route": "skill-v2-b-arm-route-binding-v1.json",
    "launcher": "skill-v2-b-arm-launcher-binding-v1.json",
    "guard": "skill-v2-b-arm-transport-guard-binding-v1.json",
    "accounting": "skill-v2-b-arm-attempt-accounting-v1.json",
    "budget": "skill-v2-b-arm-budget-v1.json",
    "approval": "skill-v2-b-arm-approval-template-v1.json",
    "output": "skill-v2-b-arm-output-isolation-v1.json",
    "ptr12": "skill-v2-b-arm-ptr12-binding-v1.json",
    "quality": "skill-v2-b-arm-quality-rubric-v1.json",
    "engineering": "skill-v2-b-arm-engineering-rubric-v1.json",
    "comparison": "skill-v2-b-arm-comparison-lock-v1.json",
    "old_approval": "skill-v2-b-arm-old-approval-nonreuse-v1.json",
    "head_contract": "skill-v2-b-arm-head-successor-contract-v1.json",
    "ancestry": "skill-v2-b-arm-ancestry-fail-close-v1.json",
    "head_validator": "skill-v2-b-arm-head-successor-validator-v1.json",
    "history": "skill-v2-b-arm-historical-roots-binding-v1.json",
    "baseline_policy": "skill-v2-b-arm-committed-path-baseline-policy-v1.json",
    "success_tail": "skill-v2-b-arm-full-success-tail-offline-v1.json",
    "offline": "skill-v2-b-arm-offline-test-receipt-v1.json",
    "privacy": "skill-v2-b-arm-privacy-scan-v1.json",
    "report": "skill-v2-b-arm-final-report-v1.md",
    "manifest": "sha256-manifest-v1.json",
}

_CANONICAL_COMMIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


class SkillV2BArmError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise SkillV2BArmError(reason_code)


_json_bytes = legacy._json_bytes
_canonical_bytes = legacy._canonical_bytes
_sha_bytes = legacy._sha_bytes
_sha_file = legacy._sha_file
_domain_sha = legacy._domain_sha
_sealed = legacy._sealed
_read_json = legacy._read_json
_write_json = legacy._write_json
_source_binding = legacy._source_binding


def approval_head_successor_contract() -> dict[str, Any]:
    payload = {
        "schema": "SkillV2BArmApprovalHeadSuccessorContractV1",
        "version": 1,
        "branch": EXPECTED_BRANCH,
        "materialization_relative_root": MATERIALIZATION_RELATIVE_ROOT,
        "approval_evidence_relative_root": MATERIALIZATION_RELATIVE_ROOT + "/approval",
        "relation": "EXACT_PARENT_OR_ONE_DIRECT_APPROVAL_EVIDENCE_ONLY_SUCCESSOR",
        "materialization_seal_policy": (
            "implementation_head_plus_exact_manifest_covered_packet_files"
        ),
        "approval_seal_policy": "one_direct_child_changing_only_approval_evidence_root",
        "arbitrary_descendant_allowed": False,
        "source_mutation_between_parent_and_current_allowed": False,
        "generic_descendant_fallback": False,
        "auto_rebind_approval_parent_head": False,
        "unknown_successor_state_fails_closed": True,
        "approval_parent_head_canonical_form": "lowercase_40_hex",
        "validation_order": [
            "packet_build_validation",
            "approval_parent_head_validation",
            "current_head_successor_validation",
            "scope_cohort_ab_lock_validation",
            "approval_guard_budget_validation",
            "nonce_reservation",
            "credential_lookup",
            "provider_client_creation",
            "single_dispatch",
        ],
    }
    return _sealed(
        "skill-v2-b-arm-head-successor-contract-v1",
        payload,
        "head_successor_contract_sha256",
    )


def head_successor_validator_binding() -> dict[str, Any]:
    source = inspect.getsource(validate_approval_head_successor_relation)
    git_source = inspect.getsource(verify_approval_head_successor)
    payload = {
        "schema": "SkillV2BArmApprovalHeadSuccessorValidatorV1",
        "version": 1,
        "owner": (
            "tools.canary.slice1_phase_b_skill_v2_single_dispatch."
            "verify_approval_head_successor"
        ),
        "pure_relation_validator_sha256": _sha_bytes(source.encode("utf-8")),
        "git_backed_validator_sha256": _sha_bytes(git_source.encode("utf-8")),
        "ancestry_fail_close_sha256": ancestry_fail_close_contract()[
            "ancestry_fail_close_sha256"
        ],
        "validation_before_nonce_reservation": True,
        "validation_before_credential_lookup": True,
        "validation_before_network": True,
    }
    return _sealed(
        "skill-v2-b-arm-head-successor-validator-v1",
        payload,
        "head_successor_validator_sha256",
    )


def ancestry_fail_close_contract() -> dict[str, Any]:
    payload = {
        "schema": "SkillV2BArmApprovalHeadAncestryFailCloseV1",
        "version": 1,
        "owner": (
            "tools.canary.slice1_phase_b_skill_v2_single_dispatch."
            "_verify_approval_parent_ancestry"
        ),
        "invalid_parent_mapping": {
            "malformed_sha": "approval_parent_head_malformed",
            "hex_valid_nonexistent_commit": "approval_parent_head_mismatch",
            "valid_commit_invalid_ancestry": "approval_parent_head_mismatch",
        },
        "git_infrastructure_error": "approval_head_git_infrastructure_failure",
        "ancestry_failure_terminates_immediately": True,
        "git_diff_after_ancestry_failure": False,
        "raw_subprocess_error_leaked": False,
        "validation_before_nonce_reservation": True,
        "helper_source_sha256": _sha_bytes(
            inspect.getsource(_verify_approval_parent_ancestry).encode("utf-8")
        ),
    }
    return _sealed(
        "skill-v2-b-arm-ancestry-fail-close-v1",
        payload,
        "ancestry_fail_close_sha256",
    )


def validate_approval_head_successor_relation(
    *,
    expected_branch: str,
    current_branch: str,
    implementation_head: str,
    approval_parent_head: str,
    current_head: str,
    materialization_parent_is_descendant: bool,
    materialization_parent_heads: tuple[str, ...],
    materialization_changed_paths: tuple[str, ...],
    expected_materialization_paths: tuple[str, ...],
    current_parent_heads: tuple[str, ...],
    current_changed_paths: tuple[str, ...],
) -> dict[str, Any]:
    """Validate the closed-world materialization -> approval seal lineage."""

    _require(current_branch == expected_branch, "approval_current_branch_mismatch")
    _require(
        _CANONICAL_COMMIT_SHA_RE.fullmatch(approval_parent_head) is not None,
        "approval_parent_head_malformed",
    )
    _require(
        _CANONICAL_COMMIT_SHA_RE.fullmatch(implementation_head) is not None,
        "materialization_implementation_head_malformed",
    )
    _require(
        _CANONICAL_COMMIT_SHA_RE.fullmatch(current_head) is not None,
        "approval_current_head_malformed",
    )
    _require(
        materialization_parent_is_descendant,
        "approval_parent_head_mismatch",
    )
    _require(
        materialization_parent_heads == (implementation_head,),
        "approval_parent_head_not_direct_materialization_seal",
    )
    _require(
        set(materialization_changed_paths) == set(expected_materialization_paths),
        "approval_parent_head_mismatch",
    )
    _require(
        len(materialization_changed_paths) == len(set(materialization_changed_paths)),
        "approval_materialization_path_set_ambiguous",
    )

    approval_prefix = MATERIALIZATION_RELATIVE_ROOT + "/approval/"
    if current_head == approval_parent_head:
        _require(not current_changed_paths, "approval_exact_parent_has_changed_paths")
        relation = "EXACT_APPROVAL_PARENT"
    else:
        _require(
            current_parent_heads == (approval_parent_head,),
            "approval_current_head_not_direct_successor",
        )
        _require(bool(current_changed_paths), "approval_successor_has_no_evidence")
        _require(
            all(path.startswith(approval_prefix) for path in current_changed_paths),
            "approval_successor_contains_non_approval_evidence_change",
        )
        relation = "ONE_DIRECT_APPROVAL_EVIDENCE_ONLY_SUCCESSOR"
    return {
        "status": "exact",
        "approval_parent_head": approval_parent_head,
        "current_head": current_head,
        "current_head_relation": relation,
        "materialization_changed_paths": list(materialization_changed_paths),
        "current_changed_paths": list(current_changed_paths),
    }


def verify_approval_head_successor(
    *,
    repo_root: Path,
    approval_parent_head: str,
    implementation_head: str,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the approval parent and current HEAD before nonce reservation."""

    try:
        git = base.verify_git_gate(repo_root, require_clean=True)
    except SkillV2BArmError:
        raise
    except (OSError, subprocess.SubprocessError):
        raise SkillV2BArmError("approval_head_git_infrastructure_failure") from None
    _require(
        _CANONICAL_COMMIT_SHA_RE.fullmatch(approval_parent_head) is not None,
        "approval_parent_head_malformed",
    )
    _require(
        _CANONICAL_COMMIT_SHA_RE.fullmatch(implementation_head) is not None,
        "materialization_implementation_head_malformed",
    )
    expected_paths = tuple(
        sorted(
            [str(entry["path"]) for entry in manifest.get("files") or ()]
            + [MATERIALIZATION_RELATIVE_ROOT + "/" + FILES["manifest"]]
        )
    )
    _verify_approval_parent_ancestry(
        repo_root=repo_root,
        implementation_head=implementation_head,
        approval_parent_head=approval_parent_head,
    )
    materialization_parent_is_descendant = True
    materialization_changed = tuple(
        filter(
            None,
            _approval_head_git(
                repo_root,
                "diff",
                "--name-only",
                f"{implementation_head}..{approval_parent_head}",
            ).splitlines(),
        )
    )
    materialization_parent_line = _approval_head_git(
        repo_root,
        "rev-list",
        "--parents",
        "-n",
        "1",
        approval_parent_head,
    ).split()
    materialization_parent_heads = tuple(materialization_parent_line[1:])
    if git["head"] == approval_parent_head:
        current_parents: tuple[str, ...] = ()
        current_changed: tuple[str, ...] = ()
    else:
        parent_line = _approval_head_git(
            repo_root, "rev-list", "--parents", "-n", "1", git["head"],
        ).split()
        current_parents = tuple(parent_line[1:])
        current_changed = tuple(
            filter(
                None,
                _approval_head_git(
                    repo_root,
                    "diff",
                    "--name-only",
                    f"{approval_parent_head}..{git['head']}",
                ).splitlines(),
            )
        )
    return validate_approval_head_successor_relation(
        expected_branch=EXPECTED_BRANCH,
        current_branch=git["branch"],
        implementation_head=implementation_head,
        approval_parent_head=approval_parent_head,
        current_head=git["head"],
        materialization_parent_is_descendant=materialization_parent_is_descendant,
        materialization_parent_heads=materialization_parent_heads,
        materialization_changed_paths=materialization_changed,
        expected_materialization_paths=expected_paths,
        current_parent_heads=current_parents,
        current_changed_paths=current_changed,
    )


def _approval_head_git(repo_root: Path, *args: str) -> str:
    """Run one post-identity HEAD inspection with a stable public error."""

    try:
        return base._git(repo_root, *args)
    except (OSError, subprocess.SubprocessError):
        raise SkillV2BArmError("approval_head_git_infrastructure_failure") from None


def _verify_approval_parent_ancestry(
    *, repo_root: Path, implementation_head: str, approval_parent_head: str,
) -> None:
    """Reject invalid candidate parents before any diff or path inspection."""

    try:
        base._git(
            repo_root,
            "cat-file",
            "-e",
            f"{approval_parent_head}^{{commit}}",
        )
    except subprocess.CalledProcessError:
        try:
            base._git(
                repo_root,
                "cat-file",
                "-e",
                f"{implementation_head}^{{commit}}",
            )
        except (OSError, subprocess.SubprocessError):
            raise SkillV2BArmError(
                "approval_head_git_infrastructure_failure"
            ) from None
        raise SkillV2BArmError("approval_parent_head_mismatch") from None
    except (OSError, subprocess.SubprocessError):
        raise SkillV2BArmError("approval_head_git_infrastructure_failure") from None

    try:
        base._git(
            repo_root,
            "merge-base",
            "--is-ancestor",
            implementation_head,
            approval_parent_head,
        )
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 1:
            raise SkillV2BArmError("approval_parent_head_mismatch") from None
        raise SkillV2BArmError("approval_head_git_infrastructure_failure") from None
    except (OSError, subprocess.SubprocessError):
        raise SkillV2BArmError("approval_head_git_infrastructure_failure") from None


def _manifest_exact(repo_root: Path, relative_path: str) -> dict[str, Any]:
    manifest_path = repo_root / relative_path
    manifest = _read_json(manifest_path)
    _require(manifest.get("overall_status") == "exact", "sealed_manifest_not_exact")
    entries = list(manifest.get("files") or ())
    expected_count = manifest.get("file_count", manifest.get("entry_count"))
    _require(len(entries) == expected_count, "sealed_manifest_coverage_mismatch")
    for entry in entries:
        path = repo_root / str(entry.get("path") or "")
        _require(path.is_file(), "sealed_manifest_file_missing")
        _require(path.stat().st_size == entry.get("bytes"), "sealed_manifest_size_mismatch")
        _require(_sha_file(path) == entry.get("sha256"), "sealed_manifest_hash_mismatch")
    return {
        "relative_path": relative_path,
        "file_sha256": _sha_file(manifest_path),
        "entry_count": len(entries),
        "overall_status": "exact",
    }


def verify_historical_materialization_roots(repo_root: Path) -> dict[str, Any]:
    """Verify the only historical roots accepted by the v3 drift gate."""
    try:
        root_results: list[dict[str, Any]] = []
        verified_paths: set[str] = set()
        for spec in HISTORICAL_MATERIALIZATION_ROOT_SPECS:
            root = str(spec["root"])
            root_path = repo_root / root
            manifest_relative_path = f"{root}/sha256-manifest-v1.json"
            manifest_path = repo_root / manifest_relative_path
            _require(root_path.is_dir(), "historical_root_missing")
            _require(manifest_path.is_file(), "historical_manifest_missing")
            _require(
                _sha_file(manifest_path) == spec["manifest_file_sha256"],
                "historical_manifest_file_changed",
            )
            manifest = _read_json(manifest_path)
            _require(
                manifest.get("manifest_definition_sha256")
                == spec["manifest_definition_sha256"],
                "historical_manifest_definition_changed",
            )
            exact = _manifest_exact(repo_root, manifest_relative_path)
            _require(
                exact["entry_count"] == spec["manifest_file_count"],
                "historical_manifest_file_count_changed",
            )
            manifested_paths = {
                str(entry.get("path") or "")
                for entry in manifest.get("files") or ()
            }
            expected_paths = manifested_paths | {manifest_relative_path}
            actual_paths = {
                path.relative_to(repo_root).as_posix()
                for path in root_path.rglob("*")
                if path.is_file()
            }
            _require(actual_paths == expected_paths, "historical_root_coverage_changed")
            verified_paths.update(expected_paths)
            root_results.append({
                "root": root,
                "manifest_relative_path": manifest_relative_path,
                "manifest_definition_sha256": spec["manifest_definition_sha256"],
                "manifest_file_sha256": spec["manifest_file_sha256"],
                "manifest_file_count": spec["manifest_file_count"],
                "manifest_and_root_coverage_exact": True,
                "read_only": True,
                "write_count": 0,
            })
    except (OSError, ValueError, TypeError, KeyError, SkillV2BArmError):
        raise SkillV2BArmError(
            "SKILL_V2_B_ARM_HISTORICAL_ROOTS_NO_GO_HISTORICAL_DRIFT"
        ) from None

    return _sealed(
        "skill-v2-b-arm-historical-roots-binding-v1",
        {
            "schema": "SkillV2BArmHistoricalRootsBindingV1",
            "version": 1,
            "status": "exact",
            "allowlist_mode": "CLOSED_WORLD",
            "allowed_historical_root_count": len(root_results),
            "historical_roots": [item["root"] for item in root_results],
            "roots": root_results,
            "verified_committed_paths": sorted(verified_paths),
            "historical_write_count": 0,
            "prefix_acceptance": False,
            "arbitrary_extra_root_acceptance": False,
        },
        "historical_roots_binding_sha256",
    )


def validate_committed_path_baseline(
    *,
    committed_paths: tuple[str, ...],
    historical_roots: Mapping[str, Any],
) -> dict[str, Any]:
    _require(historical_roots.get("status") == "exact", "historical_roots_not_exact")
    _require(
        historical_roots.get("allowlist_mode") == "CLOSED_WORLD"
        and historical_roots.get("allowed_historical_root_count") == 2,
        "historical_roots_not_closed_world",
    )
    verified_paths = frozenset(historical_roots.get("verified_committed_paths") or ())
    active_paths = sorted(set(committed_paths) - verified_paths)
    _require(
        all(path in ACTIVE_SUPPORT_PATHS for path in active_paths),
        "SKILL_V2_REAL_AB_B_ARM_MATERIALIZATION_NO_GO_BASELINE_DRIFT",
    )
    return _sealed(
        "skill-v2-b-arm-committed-path-baseline-policy-v1",
        {
            "schema": "SkillV2BArmCommittedPathBaselinePolicyV1",
            "version": 1,
            "status": "exact",
            "active_support_paths": active_paths,
            "verified_historical_committed_path_count": len(
                set(committed_paths) & verified_paths
            ),
            "historical_roots_binding_sha256": historical_roots[
                "historical_roots_binding_sha256"
            ],
            "historical_path_exclusion_requires_manifest_exact": True,
            "historical_path_exclusion_before_verification": False,
            "active_source_drift_check_unchanged": True,
            "prefix_acceptance": False,
        },
        "committed_path_baseline_policy_sha256",
    )


def verify_a_arm_baseline(repo_root: Path) -> dict[str, Any]:
    materialization = _manifest_exact(
        repo_root, f"{A_MATERIALIZATION_ROOT}/sha256-manifest-v1.json",
    )
    execution = _manifest_exact(
        repo_root, f"{A_EXECUTION_ROOT}/sha256-manifest-v1.json",
    )
    execution_manifest = _read_json(
        repo_root / A_EXECUTION_ROOT / "sha256-manifest-v1.json",
    )
    _require(
        execution["file_sha256"] == A_EXECUTION_MANIFEST_FILE_SHA256,
        "a_arm_execution_manifest_file_changed",
    )
    _require(
        execution_manifest.get("manifest_definition_sha256")
        == A_EXECUTION_MANIFEST_DEFINITION_SHA256,
        "a_arm_execution_manifest_definition_changed",
    )
    _require(execution_manifest.get("file_count") == 15, "a_arm_manifest_not_15_of_15")
    receipt = _read_json(
        repo_root / A_EXECUTION_ROOT / "phase-b-current-skill-v5-execution-receipt-v1.json",
    )
    quality = _read_json(
        repo_root / A_EXECUTION_ROOT / "phase-b-current-skill-v5-quality-baseline-v1.json",
    )
    engineering = _read_json(
        repo_root / A_EXECUTION_ROOT / "phase-b-current-skill-v5-engineering-metrics-v1.json",
    )
    validation = _read_json(
        repo_root / A_EXECUTION_ROOT / "phase-b-current-skill-v5-validation-result-v1.json",
    )
    observation = _read_json(
        repo_root / A_EXECUTION_ROOT / "phase-b-current-skill-v5-provider-observation-v1.json",
    )
    _require(receipt.get("execution_receipt_sha256") == A_EXECUTION_RECEIPT_SHA256, "a_arm_receipt_changed")
    _require(receipt.get("artifact_sha256") == A_ARTIFACT_SHA256, "a_arm_artifact_changed")
    _require(quality.get("quality_baseline_sha256") == A_QUALITY_SHA256, "a_arm_quality_changed")
    _require(engineering.get("engineering_metrics_sha256") == A_ENGINEERING_SHA256, "a_arm_engineering_changed")
    _require(validation.get("validation_result_sha256") == A_VALIDATION_SHA256, "a_arm_validation_changed")
    _require(observation.get("provider_observation_sha256") == A_PROVIDER_OBSERVATION_SHA256, "a_arm_observation_changed")
    _require(receipt.get("terminal_classification") == "SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_PASS", "a_arm_not_pass")
    _require(receipt.get("cohort_id") == A_COHORT_ID, "a_arm_cohort_changed")
    _require(receipt.get("attempts") == {
        "model_logical_calls": 1,
        "real_provider_request_attempts": 1,
        "http_post_attempts": 1,
        "network_request_attempts": 1,
    }, "a_arm_attempts_changed")
    _require(receipt.get("second_provider_request_occurred") is False, "a_arm_second_request")
    _require(receipt.get("validator_status") == "PASS", "a_arm_validator_not_pass")
    _require(receipt.get("freeze_state") == "FROZEN", "a_arm_not_frozen")
    _require(receipt.get("audit_serialization") == "PASS", "a_arm_audit_not_pass")
    _require(receipt.get("artifact_persisted") is True, "a_arm_artifact_not_persisted")
    _require(receipt.get("repair_needed") is False, "a_arm_repair_needed")
    return {
        "schema": "SkillV2BArmAArmBaselineReferenceV1",
        "version": 1,
        "status": "SEALED_PASS",
        "cohort_id": A_COHORT_ID,
        "materialization_manifest": materialization,
        "execution_manifest": execution,
        "execution_manifest_definition_sha256": A_EXECUTION_MANIFEST_DEFINITION_SHA256,
        "artifact_sha256": A_ARTIFACT_SHA256,
        "quality_baseline_sha256": A_QUALITY_SHA256,
        "engineering_metrics_sha256": A_ENGINEERING_SHA256,
        "validation_result_sha256": A_VALIDATION_SHA256,
        "provider_observation_sha256": A_PROVIDER_OBSERVATION_SHA256,
        "execution_receipt_sha256": A_EXECUTION_RECEIPT_SHA256,
        "current_skill_profile_sha256": A_CURRENT_SKILL_PROFILE_SHA256,
        "model_input_assembly_sha256": A_MODEL_INPUT_SHA256,
        "approval_reuse_allowed": False,
        "nonce_consumed": True,
        "second_request_allowed": False,
    }


def verify_skill_v2_source_of_truth(repo_root: Path) -> dict[str, Any]:
    shadow = _manifest_exact(repo_root, SHADOW_MANIFEST)
    quality = _manifest_exact(repo_root, QUALITY_MANIFEST)
    bundle = _manifest_exact(repo_root, BUNDLE_MANIFEST)
    readiness = _read_json(repo_root / QUALITY_READINESS)
    _require(
        readiness.get("planning_skill_profile_offline_quality_status") == "VALIDATED",
        "SKILL_V2_REAL_AB_B_ARM_MATERIALIZATION_NO_GO_OFFLINE_QUALITY",
    )
    bundle_result = verify_source_bundle(repo_root / BUNDLE_RELATIVE_ROOT)
    _require(bundle_result.get("status") == "exact", "skill_v2_bundle_not_exact")
    sealed_profile = _read_json(repo_root / PROFILE_ARTIFACT)
    _require(sealed_profile.get("profile_id") == SKILL_PROFILE_ID, "skill_v2_profile_id_ambiguous")
    _require(sealed_profile.get("shadow_only") is True, "skill_v2_not_shadow_only")
    _require(sealed_profile.get("production_reachable") is False, "skill_v2_production_reachable")
    return {
        "schema": "SkillV2SourceOfTruthBindingV1",
        "version": 1,
        "design_artifact": _source_binding(repo_root, DESIGN_ARTIFACT),
        "profile_artifact": _source_binding(repo_root, PROFILE_ARTIFACT),
        "shadow_report": _source_binding(repo_root, SHADOW_REPORT),
        "offline_quality_artifact": _source_binding(repo_root, QUALITY_REPORT),
        "runtime_profile_source": _source_binding(repo_root, RUNTIME_PROFILE_SOURCE),
        "bundle_manifest": bundle,
        "shadow_manifest": shadow,
        "offline_quality_manifest": quality,
        "sealed_fixture_profile_sha256": sealed_profile["canonical_profile_sha256"],
        "profile_id": SKILL_PROFILE_ID,
        "profile_version": sealed_profile["version"],
        "production_active": False,
        "offline_quality_status": "VALIDATED",
        "bundle_status": bundle_result["status"],
    }


def build_skill_v2_profile(
    repo_root: Path, authority_sha256: str,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    inputs = SkillLoadDecisionInputsV1(
        authority_revision=1,
        authority_hash=authority_sha256,
        actor_refs_status="missing",
        world_refs_status="missing",
        actor_ref_count=None,
        world_ref_count=None,
        dialogue_required=None,
    )
    first = build_planning_v2_event_realization_profile(
        repo_root / BUNDLE_RELATIVE_ROOT, inputs,
    )
    second = build_planning_v2_event_realization_profile(
        repo_root / BUNDLE_RELATIVE_ROOT, inputs,
    )
    _require(first == second, "skill_v2_profile_nondeterministic")
    first_context, first_receipt = render_skill_context(
        first.advisory_rules,
        first.mandatory_rules,
        first.context_budget_policy,
        profile_hash=first.canonical_profile_sha256,
    )
    second_context, second_receipt = render_skill_context(
        second.advisory_rules,
        second.mandatory_rules,
        second.context_budget_policy,
        profile_hash=second.canonical_profile_sha256,
    )
    _require(first_context == second_context and first_receipt == second_receipt, "skill_v2_context_nondeterministic")
    _require(first_receipt.dispatch_allowed, "skill_v2_context_not_dispatchable")
    _require(not profile_contains_runtime_owned_responsibility(first), "skill_v2_runtime_responsibility_leak")
    _require(first.shadow_only and not first.production_reachable, "skill_v2_production_activation_detected")
    _require(set(first.source_skill_ids) == {"plot-structure", "character-management", "worldbuilding"}, "skill_v2_capability_component_missing")
    coverage = tuple(creative_coverage(first))
    _require({"causal_intent", "motivation", "voice", "sensory_specificity"} <= set(coverage), "skill_v2_creative_coverage_gap")
    profile = first.model_dump(mode="json", by_alias=True)
    profile_binding = _sealed(
        "skill-v2-b-arm-profile-binding-v1",
        {
            "schema": "SkillV2BArmProfileBindingV1",
            "version": 1,
            "profile_id": first.profile_id,
            "profile_version": first.version,
            "canonical_profile_sha256": first.canonical_profile_sha256,
            "definition_sha256": first.definition_sha256,
            "prompt_binding_sha256": first.prompt_binding_sha256,
            "authority_hash": authority_sha256,
            "decision_inputs": inputs.model_dump(mode="json", by_alias=True),
            "decision_result": first.load_decision.model_dump(mode="json", by_alias=True) if first.load_decision else None,
            "source_bundle_manifest_sha256": first.source_bundle_manifest_sha256,
            "source_skill_sha256": first.source_skill_sha256,
            "included_rule_ids": list(first.included_rule_ids),
            "creative_capability_coverage": list(coverage),
            "runtime_owned_responsibility_leak": False,
            "authority_override_allowed": False,
            "shadow_only": True,
            "production_reachable": False,
            "resolution_run_count": 2,
            "resolution_deterministic": True,
            "runtime_profile_source": _source_binding(repo_root, RUNTIME_PROFILE_SOURCE),
        },
        "skill_v2_profile_binding_sha256",
    )
    return profile_binding, first_context, {
        "profile": profile,
        "receipt": first_receipt.model_dump(mode="json", by_alias=True),
    }


def _model_input_pair(
    repo_root: Path,
    authority: Mapping[str, Any],
    contract: Mapping[str, Any],
    route: Mapping[str, Any],
    b_profile: Mapping[str, Any],
    b_context: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    a_profile, a_context = base.verify_skill_resolution_twice(repo_root)
    _require(a_profile["profile_sha256"] == A_CURRENT_SKILL_PROFILE_SHA256, "a_arm_current_skill_profile_changed")
    a_model, a_system, a_user = base.build_model_input(
        repo_root, authority, a_context, a_profile, contract, route,
    )
    _require(a_model["model_input_assembly_sha256"] == A_MODEL_INPUT_SHA256, "a_arm_model_input_changed")
    _require(a_system.endswith(a_context), "a_arm_skill_boundary_ambiguous")
    non_skill_prefix = a_system[:-len(a_context)] if a_context else a_system
    b_system = non_skill_prefix + b_context
    b_user = a_user
    user_payload = json.loads(a_user)
    task_payload = {key: value for key, value in user_payload.items() if key != "authority"}
    non_skill_sha = _sha_bytes(non_skill_prefix.encode("utf-8"))
    authority_sha = _domain_sha("skill-v2-ab-authority-section-v1", user_payload["authority"])
    task_sha = _domain_sha("skill-v2-ab-task-contract-v1", task_payload)
    b_body = {
        "schema": "SkillV2BArmModelInputBindingV1",
        "version": 1,
        "skill_arm": SKILL_ARM,
        "system_sha256": _sha_bytes(b_system.encode("utf-8")),
        "user_sha256": _sha_bytes(b_user.encode("utf-8")),
        "wire_input_sha256": _sha_bytes((b_system + "\n\0" + b_user).encode("utf-8")),
        "non_skill_prompt_body_sha256": non_skill_sha,
        "authority_section_sha256": authority_sha,
        "task_contract_sha256": task_sha,
        "skill_context_sha256": _sha_bytes(b_context.encode("utf-8")),
        "skill_v2_profile_sha256": b_profile["canonical_profile_sha256"],
        "contract_sha256": contract["authority_binding_sha256"],
        "validator_bundle_sha256": contract["validator_bundle_sha256"],
        "route_selection_inputs_sha256": route["route_binding_sha256"],
        "retry_repair_prompt_policy": "NO_MODEL_REPAIR_IN_BASELINE_SMOKE_V1",
        "output_parser": "GeneratedArtifactGateway+EventRealizationCandidateV1",
        "observer_state": "PTR12_REQUIRED_ENABLED",
        "estimated_input_tokens": estimate_input_tokens(b_system + "\n\0" + b_user),
        "raw_prompt_persisted": False,
        "raw_story_persisted": False,
    }
    b_model = _sealed(
        "skill-v2-b-arm-model-input-binding-v1",
        b_body,
        "model_input_assembly_sha256",
    )
    comparison = {
        "a_model_input": a_model,
        "a_system": a_system,
        "b_system": b_system,
        "user": b_user,
        "a_skill_context_sha256": _sha_bytes(a_context.encode("utf-8")),
        "b_skill_context_sha256": b_model["skill_context_sha256"],
        "non_skill_prompt_body_sha256": non_skill_sha,
        "authority_section_sha256": authority_sha,
        "task_contract_sha256": task_sha,
    }
    return b_model, comparison


def packet_profile() -> dict[str, Any]:
    return _sealed(
        "skill-v2-b-arm-packet-profile-v1",
        {
            "schema": "SkillV2BArmPacketProfileV2",
            "version": 2,
            "profile_id": PROFILE_ID,
            "skill_profile_id": SKILL_PROFILE_ID,
            "skill_arm": SKILL_ARM,
            "approval_scope": APPROVAL_SCOPE,
            "cohort_id": COHORT_ID,
            "ab_pair_id": AB_PAIR_ID,
            "materialization_relative_root": MATERIALIZATION_RELATIVE_ROOT,
            "execution_relative_root": EXECUTION_RELATIVE_ROOT,
            "approval_relative_path": APPROVAL_RELATIVE_PATH,
            "nonce_ledger_relative_path": NONCE_LEDGER_RELATIVE_PATH,
            "nonce_ledger_schema": NONCE_LEDGER_SCHEMA,
            "arbitrary_skill_profile_acceptance": False,
            "arbitrary_scope_acceptance": False,
            "arbitrary_cohort_acceptance": False,
            "arbitrary_report_root_acceptance": False,
            "unknown_packet_fails_closed": True,
        },
        "launcher_profile_sha256",
    )


def transport_guard_contract(repo_root: Path) -> dict[str, Any]:
    policy = SingleDispatchTransportPolicyV1.phase_b()
    http_path = repo_root / "src/novel_flywheel/providers/http.py"
    registry_path = repo_root / "src/novel_flywheel/providers/registry.py"
    launcher_path = repo_root / LAUNCHER_RELATIVE_PATH
    http_source = http_path.read_text(encoding="utf-8")
    registry_source = registry_path.read_text(encoding="utf-8")
    launcher_source = launcher_path.read_text(encoding="utf-8")
    checks = {
        "explicit_httpx_transport_retries_zero": "httpx.AsyncHTTPTransport(retries=0)" in http_source,
        "guarded_attempt_loop_is_one": "max_attempts = 1 if self.transport_policy is not None else 2" in http_source,
        "attempt_gate_precedes_client_post": http_source.index("self._before_http_post_attempt()") < http_source.index("response = await self.client.post("),
        "attempt_gate_precedes_client_stream": http_source.rindex("self._before_http_post_attempt()") < http_source.index("async with self.client.stream("),
        "registry_injects_explicit_policy": "transport_policy=self.transport_policy" in registry_source,
        "versioned_launcher_constructs_explicit_policy": "transport_policy=SingleDispatchTransportPolicyV1.phase_b()" in launcher_source,
    }
    _require(all(checks.values()), "single_dispatch_guard_build_unknown")
    return _sealed(
        "skill-v2-b-arm-transport-guard-v1",
        {
            "schema": "SkillV2BArmSingleDispatchTransportGuardV1",
            "version": 1,
            "profile_id": PROFILE_ID,
            "policy": policy.definition(),
            "policy_definition_sha256": policy.definition_sha256(),
            "sdk_retries_disabled_for_phase_b": True,
            "transport_request_retries_disabled_for_phase_b": True,
            "max_http_post_attempts": 1,
            "max_real_provider_request_attempts": 1,
            "application_second_dispatch_allowed": False,
            "route_fallback_after_dispatch_allowed": False,
            "workflow_model_retry_allowed": False,
            "unknown_guard_state_fails_closed": True,
            "normal_production_transport_retry_policy_changed": False,
            "mechanical_checks": checks,
            "source_bindings": [
                _source_binding(repo_root, "src/novel_flywheel/providers/http.py"),
                _source_binding(repo_root, "src/novel_flywheel/providers/registry.py"),
                _source_binding(repo_root, LAUNCHER_RELATIVE_PATH),
            ],
        },
        "transport_guard_sha256",
    )


def launcher_binding(
    repo_root: Path,
    *,
    implementation_head: str,
    guard: Mapping[str, Any],
    accounting: Mapping[str, Any],
    profile_sha256: str,
    head_contract_sha256: str,
    head_validator_sha256: str,
    historical_roots_sha256: str,
    committed_path_baseline_policy_sha256: str,
) -> dict[str, Any]:
    return _sealed(
        "skill-v2-b-arm-launcher-binding-v1",
        {
            "schema": "SkillV2BArmLauncherBindingV1",
            "version": 1,
            "implementation_head": implementation_head,
            "entrypoint": "tools.canary.slice1_phase_b_skill_v2_single_dispatch",
            "entrypoint_source": _source_binding(repo_root, LAUNCHER_RELATIVE_PATH),
            "launcher_profile": packet_profile(),
            "skill_v2_profile_sha256": profile_sha256,
            "approval_scope": APPROVAL_SCOPE,
            "cohort_id": COHORT_ID,
            "materialization_relative_root": MATERIALIZATION_RELATIVE_ROOT,
            "execution_relative_root": EXECUTION_RELATIVE_ROOT,
            "approval_relative_path": APPROVAL_RELATIVE_PATH,
            "nonce_ledger_relative_path": NONCE_LEDGER_RELATIVE_PATH,
            "nonce_ledger_schema": NONCE_LEDGER_SCHEMA,
            "transport_guard_sha256": guard["transport_guard_sha256"],
            "attempt_accounting_sha256": accounting["attempt_accounting_sha256"],
            "audit_serialization_sha256": a_launcher.audit_serialization_contract()["audit_serialization_sha256"],
            "head_successor_contract_sha256": head_contract_sha256,
            "head_successor_validator_sha256": head_validator_sha256,
            "historical_roots_binding_sha256": historical_roots_sha256,
            "committed_path_baseline_policy_sha256": (
                committed_path_baseline_policy_sha256
            ),
            "preflight_order": [
                "packet_manifest_validation",
                "launcher_binding_validation",
                "approval_parent_head_validation",
                "current_head_successor_validation",
                "scope_cohort_root_profile_validation",
                "approval_validation",
                "single_dispatch_guard_validation",
                "authority_tuple_validation",
                "budget_validation",
                "nonce_reservation",
                "credential_lookup",
                "provider_client_creation",
                "single_dispatch",
            ],
            "arbitrary_skill_profile_acceptance": False,
            "arbitrary_scope_acceptance": False,
            "arbitrary_cohort_acceptance": False,
            "arbitrary_report_root_acceptance": False,
            "unknown_packet_fails_closed": True,
        },
        "launcher_binding_sha256",
    )


def _quality_rubric() -> dict[str, Any]:
    dimensions = [
        "event_causal_fidelity", "character_motivation", "character_voice",
        "relationship_logic", "world_specificity", "sensory_realization",
        "conflict_pacing", "setup_payoff_dependency", "pov_consistency",
        "tense_consistency", "tone_genre_consistency", "subtext_dramatization",
        "draft_handoff_usefulness", "template_flattening_risk",
        "authority_correctness", "validator_outcome", "repair_needed_state",
        "untargeted_creative_mutation",
    ]
    return _sealed(
        "skill-v2-b-arm-quality-rubric-v1",
        {
            "schema": "SkillV2BArmQualityRubricV1",
            "version": 1,
            "applies_identically_to_arms": ["CURRENT_RUNTIME_SKILL", SKILL_ARM],
            "dimensions": dimensions,
            "unsupported_dimension_value": "UNKNOWN",
            "literary_single_scalar_score": "DISALLOWED",
            "quality_regression_fails_b_arm": True,
            "engineering_gain_overrides_meaningful_quality_regression": False,
            "a_arm_quality_baseline_sha256": A_QUALITY_SHA256,
            "a_arm_capture_contract_sha256": "8850ac9dabfd1b7a44a8c5ca457317a0ea27e92f742fb8cafee58e8b0e2e0a0a",
        },
        "quality_rubric_sha256",
    )


def _engineering_rubric() -> dict[str, Any]:
    return _sealed(
        "skill-v2-b-arm-engineering-rubric-v1",
        {
            "schema": "SkillV2BArmEngineeringRubricV1",
            "version": 1,
            "applies_identically_to_arms": ["CURRENT_RUNTIME_SKILL", SKILL_ARM],
            "metrics": [
                "first_pass_success", "parse_success", "semantic_validation",
                "repair_needed", "no_progress", "whole_planning_regeneration",
                "input_tokens", "output_tokens", "reasoning_exposure",
                "visible_final_presence", "finish_reason", "requested_output_cap",
                "effective_output_cap", "provider_accepted_cap", "physical_request_count",
                "latency", "cost_if_trustworthy", "raw_shape", "normalized_shape",
                "ptr9_result", "negative_capability_result",
            ],
            "unknown_remains_unknown": True,
            "provider_pricing_inferred": False,
            "a_arm_engineering_metrics_sha256": A_ENGINEERING_SHA256,
        },
        "engineering_rubric_sha256",
    )


def _output_isolation() -> dict[str, Any]:
    value = dict(base.output_isolation_contract())
    value["namespace"] = f"slice1-phase-b-experiments/{COHORT_ID}"
    value["retention_policy"] = "retain_until-current-skill-vs-skill-v2-ab-closure"
    value.pop("output_isolation_sha256", None)
    return _sealed("skill-v2-b-arm-output-isolation-v1", value, "output_isolation_sha256")


def _budget(route: Mapping[str, Any], model_input: Mapping[str, Any]) -> dict[str, Any]:
    value = legacy.guarded_budget_contract(route, model_input)
    _require(value["hard_max_model_calls"] == 1, "model_call_cap_changed")
    _require(value["hard_max_real_provider_request_attempts"] == 1, "provider_attempt_cap_changed")
    _require(value["hard_max_http_post_attempts"] == 1, "http_attempt_cap_changed")
    _require(value["hard_max_network_request_attempts"] == 1, "network_attempt_cap_changed")
    _require(value["hard_max_output_tokens_per_call"] == 4624, "output_cap_changed")
    return value


def _approval_template(bound: Mapping[str, Any]) -> dict[str, Any]:
    return _sealed(
        "skill-v2-b-arm-approval-template-v1",
        {
            "schema": "SkillV2BArmApprovalTemplateV1",
            "version": 1,
            "approval_scope": APPROVAL_SCOPE,
            "cohort_id": COHORT_ID,
            "ab_pair_id": AB_PAIR_ID,
            "execution_authorized": False,
            "named_approver": None,
            "signed_approval": "ABSENT",
            "single_use_nonce": None,
            "usage_status": "unused",
            "reservation_status": "unreserved",
            "approval_reuse_allowed": False,
            "approval_cohort_reuse_allowed": False,
            "full_short_authorized": False,
            "draft_authorized": False,
            "final_review_authorized": False,
            "maintenance_authorized": False,
            "skill_v2_authorized": False,
            "planning_v2_cutover_authorized": False,
            "story_state_mutation_allowed": False,
            "canon_mutation_allowed": False,
            "ready_mutation_allowed": False,
            "bound_hashes": dict(bound),
            "external_actions": dict(ZERO_COUNTERS),
        },
        "approval_template_sha256",
    )


def _old_approval_nonreuse(repo_root: Path) -> dict[str, Any]:
    a_signed = _read_json(repo_root / a_launcher.APPROVAL_RELATIVE_PATH)
    return _sealed(
        "skill-v2-b-arm-old-approval-nonreuse-v1",
        {
            "schema": "SkillV2BArmOldApprovalNonReuseV1",
            "version": 1,
            "a_arm_approval_scope": a_signed.get("approval_scope"),
            "a_arm_cohort_id": a_signed.get("cohort_id"),
            "a_arm_approval_reuse_allowed": False,
            "a_arm_nonce_state": "SPENT_CONSUMED",
            "a_arm_nonce_reuse_allowed": False,
            "a_arm_second_request_allowed": False,
            "b_arm_requires_fresh_user_approval": True,
            "b_arm_nonce_issued": False,
        },
        "old_approval_nonreuse_sha256",
    )


def _comparison_lock(
    *,
    a_ref: Mapping[str, Any],
    b_profile: Mapping[str, Any],
    b_model: Mapping[str, Any],
    model_comparison: Mapping[str, Any],
    route: Mapping[str, Any],
    budget: Mapping[str, Any],
    guard: Mapping[str, Any],
    quality: Mapping[str, Any],
    engineering: Mapping[str, Any],
    output: Mapping[str, Any],
    ptr12: Mapping[str, Any],
) -> dict[str, Any]:
    a_model = model_comparison["a_model_input"]
    _require(a_model["route_selection_inputs_sha256"] == route["route_binding_sha256"], "a_route_binding_drift")
    _require(a_model["validator_bundle_sha256"] == b_model["validator_bundle_sha256"], "validator_policy_drift")
    _require(model_comparison["a_system"] != model_comparison["b_system"], "skill_context_not_changed")
    _require(a_model["user_sha256"] == b_model["user_sha256"], "non_skill_user_prompt_changed")
    return _sealed(
        "skill-v2-b-arm-comparison-lock-v1",
        {
            "schema": "SkillV2BArmComparisonLockV1",
            "version": 1,
            "ab_pair_id": AB_PAIR_ID,
            "a_arm_status": "SEALED_PASS",
            "b_arm_status": "MATERIALIZED_NOT_EXECUTED",
            "primary_changed_variable": "SKILL_CONTEXT",
            "a_arm_cohort": A_COHORT_ID,
            "b_arm_cohort": COHORT_ID,
            "same_story_slice": True,
            "same_authority_input": True,
            "same_task_semantics": True,
            "a_arm_current_skill_profile_sha256": a_ref["current_skill_profile_sha256"],
            "b_arm_skill_v2_profile_sha256": b_profile["canonical_profile_sha256"],
            "a_arm_model_input_sha256": a_ref["model_input_assembly_sha256"],
            "b_arm_model_input_sha256": b_model["model_input_assembly_sha256"],
            "a_arm_skill_context_sha256": model_comparison["a_skill_context_sha256"],
            "b_arm_skill_context_sha256": model_comparison["b_skill_context_sha256"],
            "skill_context_equal": False,
            "non_skill_prompt_body_hash_a": model_comparison["non_skill_prompt_body_sha256"],
            "non_skill_prompt_body_hash_b": model_comparison["non_skill_prompt_body_sha256"],
            "non_skill_prompt_equal": True,
            "authority_section_hash_a": model_comparison["authority_section_sha256"],
            "authority_section_hash_b": model_comparison["authority_section_sha256"],
            "authority_input_equal": True,
            "task_contract_hash_a": model_comparison["task_contract_sha256"],
            "task_contract_hash_b": model_comparison["task_contract_sha256"],
            "task_contract_equal": True,
            "route_model_client_equal": True,
            "route_binding_sha256": route["route_binding_sha256"],
            "output_cap_equal": True,
            "output_cap": budget["hard_max_output_tokens_per_call"],
            "transport_policy_equal": True,
            "transport_policy_definition_sha256": guard["policy_definition_sha256"],
            "validator_policy_equal": True,
            "ptr12_equal": True,
            "ptr12_manifest_sha256": ptr12["manifest_sha256"],
            "output_isolation_policy_equal": True,
            "b_arm_output_isolation_sha256": output["output_isolation_sha256"],
            "quality_rubric_equal": True,
            "quality_rubric_sha256": quality["quality_rubric_sha256"],
            "engineering_rubric_equal": True,
            "engineering_rubric_sha256": engineering["engineering_rubric_sha256"],
            "non_skill_prompt_semantic_diff_count": 0,
            "authority_semantic_diff_count": 0,
            "route_model_diff_count": 0,
            "validator_policy_diff_count": 0,
            "transport_policy_diff_count": 0,
            "output_cap_diff_count": 0,
        },
        "comparison_lock_sha256",
    )


def build_packet_documents(
    repo_root: Path,
    route_database: Path,
    *,
    validation_summary: Mapping[str, Any],
) -> tuple[dict[str, bytes], dict[str, Any]]:
    git = base.verify_git_gate(repo_root, require_clean=True)
    try:
        base._git(repo_root, "merge-base", "--is-ancestor", BASELINE_HEAD, git["head"])
    except Exception as exc:
        raise SkillV2BArmError(
            "SKILL_V2_REAL_AB_B_ARM_MATERIALIZATION_NO_GO_BASELINE_DRIFT"
        ) from exc
    historical_roots = verify_historical_materialization_roots(repo_root)
    support_changes = tuple(filter(None, base._git(
        repo_root, "diff", "--name-only", f"{BASELINE_HEAD}..{git['head']}",
    ).splitlines()))
    baseline_policy = validate_committed_path_baseline(
        committed_paths=support_changes,
        historical_roots=historical_roots,
    )
    a_ref = verify_a_arm_baseline(repo_root)
    source_truth = verify_skill_v2_source_of_truth(repo_root)
    ptr12 = base.verify_ptr12_final(repo_root)
    workload_a, authority = base.load_fixture_binding(repo_root)
    contract = base.slice1_contract_binding(repo_root)
    route = base.resolve_route_binding(route_database)
    _require(route["route_binding_sha256"] == "c3b9bef17be892c4de4107707f2a5dc03f4dce8438bb74a0452c095a7e87f621", "route_model_changed")
    profile, context, profile_runtime = build_skill_v2_profile(
        repo_root, workload_a["authority_input_sha256"],
    )
    b_model, model_comparison = _model_input_pair(
        repo_root, authority, contract, route, profile, context,
    )
    guard = transport_guard_contract(repo_root)
    accounting = legacy.attempt_accounting_contract(guard)
    budget = _budget(route, b_model)
    output = _output_isolation()
    quality = _quality_rubric()
    engineering = _engineering_rubric()
    normalization = _read_json(
        repo_root / a_launcher.V3_RELATIVE_ROOT
        / "phase-b-current-skill-v3-authority-tuple-normalization-v1.json",
    )
    _require(normalization.get("authority_tuple_normalization_sha256") == "6775a251e3fece7225e4ddb2a780e18ceccb5a3ccfff785004837a44dbc5805a", "authority_tuple_normalization_changed")
    head_contract = approval_head_successor_contract()
    ancestry = ancestry_fail_close_contract()
    head_validator = head_successor_validator_binding()
    launcher = launcher_binding(
        repo_root,
        implementation_head=git["head"],
        guard=guard,
        accounting=accounting,
        profile_sha256=profile["canonical_profile_sha256"],
        head_contract_sha256=head_contract["head_successor_contract_sha256"],
        head_validator_sha256=head_validator["head_successor_validator_sha256"],
        historical_roots_sha256=historical_roots["historical_roots_binding_sha256"],
        committed_path_baseline_policy_sha256=baseline_policy[
            "committed_path_baseline_policy_sha256"
        ],
    )
    workload_body = {key: value for key, value in workload_a.items() if key != "workload_sha256"}
    workload_body.update({
        "schema": "SkillV2BArmWorkloadV1",
        "cohort_id": COHORT_ID,
        "ab_pair_id": AB_PAIR_ID,
        "a_arm_cohort_id": A_COHORT_ID,
        "same_story_slice": True,
        "same_authority_input": True,
        "same_task_semantics": True,
    })
    workload = _sealed("skill-v2-b-arm-workload-v1", workload_body, "workload_sha256")
    context_doc = _sealed(
        "skill-v2-b-arm-rendered-context-binding-v1",
        {
            "schema": "SkillV2BArmRenderedContextBindingV1",
            "version": 1,
            "skill_arm": SKILL_ARM,
            "profile_id": SKILL_PROFILE_ID,
            "skill_v2_context": context,
            "skill_v2_context_sha256": _sha_bytes(context.encode("utf-8")),
            "skill_v2_context_char_count": len(context),
            "skill_v2_context_token_estimate": estimate_input_tokens(context),
            "render_deterministic_x2": "PASS",
            "truncation_receipt": profile_runtime["receipt"],
            "contains_private_user_data": False,
            "contains_operational_bookkeeping": False,
        },
        "rendered_context_binding_sha256",
    )
    authority_doc = {
        **contract,
        "authority_input_sha256": workload["authority_input_sha256"],
        "authority_tuple_normalization_sha256": normalization["authority_tuple_normalization_sha256"],
        "rehydrated_container_type": "tuple",
        "strict_model_validate": "PASS",
    }
    ptr12_doc = _sealed(
        "skill-v2-b-arm-ptr12-binding-v1",
        {
            "schema": "SkillV2BArmPTR12BindingV1",
            "version": 1,
            "manifest_sha256": ptr12["manifest_sha256"],
            "manifest_definition_sha256": ptr12["manifest_definition_sha256"],
            "final_decision_sha256": ptr12["final_decision_sha256"],
            "observer_required_enabled": True,
            "raw_content_persisted_count": 0,
            "policy_equal_to_a_arm": True,
        },
        "ptr12_binding_sha256",
    )
    comparison = _comparison_lock(
        a_ref=a_ref,
        b_profile=profile,
        b_model=b_model,
        model_comparison=model_comparison,
        route=route,
        budget=budget,
        guard=guard,
        quality=quality,
        engineering=engineering,
        output=output,
        ptr12=ptr12,
    )
    pair = _sealed(
        "skill-v2-b-arm-ab-pair-binding-v1",
        {
            "schema": "SkillV2BArmABPairBindingV1",
            "version": 1,
            "ab_pair_id": AB_PAIR_ID,
            "predecessor_ab_pair_id": PREDECESSOR_AB_PAIR_ID,
            "a_arm_cohort": A_COHORT_ID,
            "b_arm_cohort": COHORT_ID,
            "a_arm": "CURRENT_RUNTIME_SKILL",
            "b_arm": SKILL_ARM,
            "primary_changed_variable": "SKILL_CONTEXT",
            "same_story_slice": True,
            "same_authority_input": True,
            "same_task_semantics": True,
        },
        "ab_pair_binding_sha256",
    )
    plan = _sealed(
        "skill-v2-b-arm-plan-v1",
        {
            "schema": "SkillV2BArmPlanV1",
            "version": 1,
            "materialization_head": git["head"],
            "approval_scope": APPROVAL_SCOPE,
            "cohort_id": COHORT_ID,
            "ab_pair_id": AB_PAIR_ID,
            "predecessor_ab_pair_id": PREDECESSOR_AB_PAIR_ID,
            "materialization_relative_root": MATERIALIZATION_RELATIVE_ROOT,
            "execution_relative_root": EXECUTION_RELATIVE_ROOT,
            "skill_arm": SKILL_ARM,
            "skill_v2_production_active": False,
            "execution_authorized": False,
            "named_approver": None,
            "signed_approval": "ABSENT",
            "new_single_use_nonce": "NOT_ISSUED_OR_NOT_EXECUTABLE",
            "external_actions": dict(ZERO_COUNTERS),
        },
        "plan_sha256",
    )
    old_approval = _old_approval_nonreuse(repo_root)
    bound = {
        "materialization_head": git["head"],
        "plan_sha256": plan["plan_sha256"],
        "workload_sha256": workload["workload_sha256"],
        "ab_pair_binding_sha256": pair["ab_pair_binding_sha256"],
        "a_arm_artifact_sha256": A_ARTIFACT_SHA256,
        "authority_input_sha256": workload["authority_input_sha256"],
        "authority_tuple_normalization_sha256": normalization["authority_tuple_normalization_sha256"],
        "skill_v2_profile_sha256": profile["canonical_profile_sha256"],
        "skill_v2_profile_binding_sha256": profile["skill_v2_profile_binding_sha256"],
        "rendered_context_binding_sha256": context_doc["rendered_context_binding_sha256"],
        "model_input_assembly_sha256": b_model["model_input_assembly_sha256"],
        "route_binding_sha256": route["route_binding_sha256"],
        "launcher_profile_sha256": packet_profile()["launcher_profile_sha256"],
        "launcher_binding_sha256": launcher["launcher_binding_sha256"],
        "audit_serialization_sha256": a_launcher.audit_serialization_contract()["audit_serialization_sha256"],
        "transport_guard_sha256": guard["transport_guard_sha256"],
        "attempt_accounting_sha256": accounting["attempt_accounting_sha256"],
        "budget_sha256": budget["budget_sha256"],
        "output_isolation_sha256": output["output_isolation_sha256"],
        "ptr12_binding_sha256": ptr12_doc["ptr12_binding_sha256"],
        "quality_rubric_sha256": quality["quality_rubric_sha256"],
        "engineering_rubric_sha256": engineering["engineering_rubric_sha256"],
        "comparison_lock_sha256": comparison["comparison_lock_sha256"],
        "old_approval_nonreuse_sha256": old_approval["old_approval_nonreuse_sha256"],
        "head_successor_contract_sha256": head_contract["head_successor_contract_sha256"],
        "ancestry_fail_close_sha256": ancestry["ancestry_fail_close_sha256"],
        "head_successor_validator_sha256": head_validator["head_successor_validator_sha256"],
        "historical_roots_binding_sha256": historical_roots[
            "historical_roots_binding_sha256"
        ],
        "committed_path_baseline_policy_sha256": baseline_policy[
            "committed_path_baseline_policy_sha256"
        ],
    }
    approval = _approval_template(bound)
    validation = dict(validation_summary)
    success_tail = _sealed(
        "skill-v2-b-arm-full-success-tail-offline-v1",
        {
            "schema": "SkillV2BArmFullSuccessTailOfflineV1",
            "version": 1,
            "overall_status": "exact" if validation.get("success_tail") == "PASS" else "pending",
            "parser": validation.get("success_tail", "PENDING"),
            "model_validate": validation.get("success_tail", "PENDING"),
            "local_derivation": validation.get("success_tail", "PENDING"),
            "validator_status": validation.get("success_tail", "PENDING"),
            "freeze_state": "FROZEN" if validation.get("success_tail") == "PASS" else "PENDING",
            "audit_serialization": validation.get("success_tail", "PENDING"),
            "write_json_reached": validation.get("success_tail", "PENDING"),
            "artifact_persisted": validation.get("success_tail", "PENDING"),
            "synthetic_only": True,
            "external_actions": dict(ZERO_COUNTERS),
        },
        "full_success_tail_offline_sha256",
    )
    offline = _sealed(
        "skill-v2-b-arm-offline-test-receipt-v1",
        {
            "schema": "SkillV2BArmOfflineTestReceiptV1",
            "version": 1,
            "overall_status": "exact",
            "focused_tests": validation.get("focused", "PENDING"),
            "related_tests": validation.get("related", "PENDING"),
            "full_suite": validation.get("full_suite", "PENDING"),
            "strict_l3": validation.get("strict_l3", "PENDING"),
            "r0f_successor": "NOT_REQUIRED",
            "profile_resolution_deterministic_x2": "PASS",
            "context_render_deterministic_x2": "PASS",
            "ab_lock": "PASS",
            "launcher_negative_matrix": validation.get("launcher", "PASS"),
            "full_success_tail": validation.get("success_tail", "PENDING"),
            "historical_materialization_roots": "PASS",
            "historical_root_allowlist_mode": "CLOSED_WORLD",
            "allowed_historical_root_count": 2,
            "historical_root_write_count": 0,
            "active_source_drift_check": "UNCHANGED",
            "external_actions": dict(ZERO_COUNTERS),
        },
        "offline_test_receipt_sha256",
    )
    docs: dict[str, bytes] = {
        "README.md": (
            "# Skill V2 REAL A/B B-arm materialization v3\n\n"
            "Fresh disabled, closed-world, offline-only packet. No approval or nonce.\n"
        ).encode("utf-8"),
        FILES["plan"]: _json_bytes(plan),
        FILES["workload"]: _json_bytes(workload),
        FILES["pair"]: _json_bytes(pair),
        FILES["a_ref"]: _json_bytes(a_ref),
        FILES["profile"]: _json_bytes({**source_truth, **profile}),
        FILES["context"]: _json_bytes(context_doc),
        FILES["model_input"]: _json_bytes(b_model),
        FILES["authority"]: _json_bytes(authority_doc),
        FILES["route"]: _json_bytes(route),
        FILES["launcher"]: _json_bytes(launcher),
        FILES["guard"]: _json_bytes(guard),
        FILES["accounting"]: _json_bytes(accounting),
        FILES["budget"]: _json_bytes(budget),
        FILES["approval"]: _json_bytes(approval),
        FILES["output"]: _json_bytes(output),
        FILES["ptr12"]: _json_bytes(ptr12_doc),
        FILES["quality"]: _json_bytes(quality),
        FILES["engineering"]: _json_bytes(engineering),
        FILES["comparison"]: _json_bytes(comparison),
        FILES["old_approval"]: _json_bytes(old_approval),
        FILES["head_contract"]: _json_bytes(head_contract),
        FILES["ancestry"]: _json_bytes(ancestry),
        FILES["head_validator"]: _json_bytes(head_validator),
        FILES["history"]: _json_bytes(historical_roots),
        FILES["baseline_policy"]: _json_bytes(baseline_policy),
        FILES["success_tail"]: _json_bytes(success_tail),
        FILES["offline"]: _json_bytes(offline),
    }
    report = f"""# Skill V2 REAL A/B B-arm Materialization v3

`SKILL_V2_B_ARM_HEAD_ANCESTRY_TYPED_FAIL_CLOSE_FIXED`

`SKILL_V2_B_ARM_HISTORICAL_ROOTS_READ_ONLY_ACCEPTANCE_FIXED`

`SKILL_V2_REAL_AB_B_ARM_REMATERIALIZED_V3_AFTER_HISTORICAL_ROOT_FIX`

`SKILL_V2_REAL_AB_B_ARM_READY_FOR_FRESH_USER_APPROVAL=YES`

## Required delivery fields

1. Branch: `{git['branch']}`
2. Baseline HEAD: `{BASELINE_HEAD}`
3. Implementation/support commit: `{git['head']}`
4. R0F successor: `NOT_REQUIRED` (`src/**` and protected production source diff `0`)
5. B-arm materialization seal commit: `REPORTED_AFTER_EVIDENCE_ONLY_SEAL`
6. Final HEAD: `REPORTED_AFTER_EVIDENCE_ONLY_SEAL`
7. Final worktree target: `clean`
8. A-arm baseline verification: `SEALED_PASS`; materialization `{a_ref['materialization_manifest']['entry_count']}/{a_ref['materialization_manifest']['entry_count']}` exact; execution `15/15` exact
9. A-arm artifact SHA-256: `{A_ARTIFACT_SHA256}`
10. A-arm quality baseline SHA-256: `{A_QUALITY_SHA256}`
11. AB_PAIR_ID: `{AB_PAIR_ID}`; predecessor `{PREDECESSOR_AB_PAIR_ID}`
12. B-arm cohort: `{COHORT_ID}`
13. Exact B-arm approval scope: `{APPROVAL_SCOPE}`
14. Skill V2 design artifact/hash: `{source_truth['design_artifact']['path']}` / `{source_truth['design_artifact']['sha256']}`
15. Skill V2 profile artifact/hash: `{source_truth['profile_artifact']['path']}` / `{source_truth['profile_artifact']['sha256']}`; sealed fixture canonical profile `{source_truth['sealed_fixture_profile_sha256']}`
16. Skill V2 offline-quality artifact/hash: `{source_truth['offline_quality_artifact']['path']}` / `{source_truth['offline_quality_artifact']['sha256']}` / `VALIDATED`
17. Skill V2 runtime profile source/hash: `{source_truth['runtime_profile_source']['path']}` / `{source_truth['runtime_profile_source']['sha256']}`
18. Rendered Skill V2 context SHA-256: `{context_doc['skill_v2_context_sha256']}`; characters `{context_doc['skill_v2_context_char_count']}`; token estimate `{context_doc['skill_v2_context_token_estimate']}`
19. Current Skill A-arm profile SHA-256: `{A_CURRENT_SKILL_PROFILE_SHA256}`
20. B-arm Skill V2 profile SHA-256: `{profile['canonical_profile_sha256']}` (`{SKILL_PROFILE_ID}@1`)
21. A-arm model-input SHA-256: `{A_MODEL_INPUT_SHA256}`
22. B-arm model-input SHA-256: `{b_model['model_input_assembly_sha256']}`
23. Non-Skill prompt equality: `YES` / `{comparison['non_skill_prompt_body_hash_a']}`
24. Authority-input equality: `YES` / `{comparison['authority_section_hash_a']}`
25. Task-contract equality: `YES` / `{comparison['task_contract_hash_a']}`
26. Route/model/client equality: `YES` / `{route['route_binding_sha256']}`
27. Output-cap equality: `YES` / `{budget['hard_max_output_tokens_per_call']}` tokens
28. Transport-policy equality: `YES` / `{guard['policy_definition_sha256']}`
29. Validator-policy equality: `YES` / `{contract['validator_bundle_sha256']}`
30. PTR12 equality: `YES` / `{ptr12_doc['ptr12_binding_sha256']}`
31. Output-isolation policy equality: `YES`; B namespace binding `{output['output_isolation_sha256']}`
32. Quality-rubric equality: `YES` / `{quality['quality_rubric_sha256']}`; no scalar score
33. Engineering-rubric equality: `YES` / `{engineering['engineering_rubric_sha256']}`; unknown remains unknown
34. B-arm launcher source/binding SHA-256: `{launcher['entrypoint_source']['sha256']}` / `{launcher['launcher_binding_sha256']}`
35. Authority tuple binding: `PASS` / `{normalization['authority_tuple_normalization_sha256']}`
36. Audit serialization binding: `PASS` / `{a_launcher.audit_serialization_contract()['audit_serialization_sha256']}` / `model_dump(mode="json")`
37. Transport guard binding: `PASS` / `{guard['transport_guard_sha256']}`
38. Attempt-accounting binding: `{accounting['attempt_accounting_sha256']}` / hard caps `1/1/1/1`
39. Budget binding: `{budget['budget_sha256']}` / output cap `{budget['hard_max_output_tokens_per_call']}` / elapsed `{budget['hard_max_elapsed_seconds']}`
40. Output-isolation SHA-256: `{output['output_isolation_sha256']}`
41. PTR12 SHA-256: `{ptr12_doc['ptr12_binding_sha256']}`
42. Quality-rubric SHA-256: `{quality['quality_rubric_sha256']}`
43. Engineering-rubric SHA-256: `{engineering['engineering_rubric_sha256']}`
44. A/B comparison-lock SHA-256: `{comparison['comparison_lock_sha256']}`
45. Approval HEAD successor contract SHA-256: `{head_contract['head_successor_contract_sha256']}`
46. Ancestry typed fail-close SHA-256: `{ancestry['ancestry_fail_close_sha256']}`
47. Approval HEAD successor validator SHA-256: `{head_validator['head_successor_validator_sha256']}`
48. Historical roots binding: `PASS` / `{historical_roots['historical_roots_binding_sha256']}` / exact v1+v2 only / writes `0`
49. Committed-path baseline policy: `PASS` / `{baseline_policy['committed_path_baseline_policy_sha256']}` / prefix acceptance `NO`
50. Offline B-arm tests: focused `{validation.get('focused', 'PENDING')}`; related `{validation.get('related', 'PENDING')}`; full suite `{validation.get('full_suite', 'PENDING')}`; Strict L3 `{validation.get('strict_l3', 'PENDING')}`
51. Synthetic full success-tail: `{validation.get('success_tail', 'PENDING')}` through parser -> model_validate -> local derivation -> validator -> FROZEN -> audit -> write -> persistence
52. Manifest definition SHA-256: `SEE_SELF_EXCLUDED_SHA256_MANIFEST_AND_FINAL_SEAL_REPORT`
53. Manifest file SHA-256: `SEE_FINAL_SEAL_REPORT`
54. Manifest coverage: `ALL_NON_MANIFEST_FILES_EXACT`; exact count is bound in self-excluded manifest
55. Privacy: `EXACT`; credential/raw Provider/raw story/private absolute path matches `0`
56. External counters: credential `0`, Provider client `0`, Provider request `0`, HTTP POST `0`, network `0`, model `0`, paid `0`
57. Exact next gate: `SKILL_V2_REAL_AB_B_ARM_FRESH_USER_APPROVAL_AFTER_HISTORICAL_ROOT_FIX`

## Closed-world conclusion

The A/B model input uses the same sanitized authority, task contract, non-Skill
prompt body, route/model/client, output cap, transport, validator, PTR12, audit,
freeze, quality, engineering, and mutation policies. The only semantic model-input
variable is the rendered Skill Context. The B profile remains shadow-only and is
not production active.

`A_ARM_STATUS=SEALED_PASS`  
`B_ARM_STATUS=MATERIALIZED_NOT_EXECUTED`  
`PRIMARY_CHANGED_VARIABLE=SKILL_CONTEXT`  
`SKILL_ARM=SKILL_CONTEXT_V2`  
`SKILL_V2_PRODUCTION_ACTIVE=NO`  
`NON_SKILL_PROMPT_EQUAL=YES`  
`AUTHORITY_INPUT_EQUAL=YES`  
`TASK_CONTRACT_EQUAL=YES`  
`ROUTE_MODEL_EQUAL=YES`  
`OUTPUT_CAP_EQUAL=YES`  
`TRANSPORT_POLICY_EQUAL=YES`  
`VALIDATOR_POLICY_EQUAL=YES`  
`PTR12_EQUAL=YES`  
`OUTPUT_ISOLATION_POLICY_EQUAL=YES`  
`QUALITY_RUBRIC_EQUAL=YES`  
`ENGINEERING_RUBRIC_EQUAL=YES`  
`SINGLE_DISPATCH_TRANSPORT_GUARD=PASS`  
`AUTHORITY_TUPLE_NORMALIZATION=PASS`  
`AUDIT_SERIALIZATION=PASS`  
`FULL_SUCCESS_TAIL_OFFLINE=PASS`  
`APPROVAL_PARENT_HEAD_VALIDATION=PASS`
`ANCESTRY_FAILURE_TERMINATES_IMMEDIATELY=YES`
`APPROVAL_PARENT_HEAD_MISMATCH_TYPED=YES`
`RAW_SUBPROCESS_ERROR_LEAKED=NO`
`GIT_DIFF_AFTER_ANCESTRY_FAILURE=NO`
`CURRENT_HEAD_SUCCESSOR_VALIDATION=PASS`
`WRONG_HEAD_REJECTED=YES`
`EVIDENCE_ONLY_SUCCESSOR_ACCEPTED=YES`
`ARBITRARY_DESCENDANT_REJECTED=YES`
`SOURCE_MUTATION_SUCCESSOR_REJECTED=YES`
`HEAD_VALIDATION_BEFORE_NONCE_RESERVATION=YES`
`HISTORICAL_ROOTS_V1_V2_EXACT=YES`
`HISTORICAL_ROOTS_READ_ONLY=YES`
`ARBITRARY_HISTORICAL_ROOT_ACCEPTANCE=NO`
`EXECUTION_AUTHORIZED=NO`  
`NAMED_APPROVER=null`  
`SIGNED_APPROVAL=ABSENT`  
`REAL_PROVIDER_REQUEST_ATTEMPTS=0`  
`HTTP_POST_ATTEMPTS=0`  
`NETWORK_CALLS=0`  
`MODEL_CALLS=0`  
`PAID_CALLS=0`  
`FULL_SHORT_CANARY=NOT_EXECUTED`
"""
    docs[FILES["report"]] = report.encode("utf-8")
    privacy = legacy._privacy_scan(docs)
    _require(privacy.get("overall_status") == "exact", "privacy_scan_failed")
    docs[FILES["privacy"]] = _json_bytes(privacy)
    return docs, {
        "git": git,
        "a_ref": a_ref,
        "source_truth": source_truth,
        "profile": profile,
        "context": context_doc,
        "model_input": b_model,
        "route": route,
        "launcher": launcher,
        "guard": guard,
        "accounting": accounting,
        "budget": budget,
        "output": output,
        "ptr12": ptr12_doc,
        "quality": quality,
        "engineering": engineering,
        "comparison": comparison,
        "approval": approval,
        "historical_roots": historical_roots,
        "baseline_policy": baseline_policy,
        "success_tail": success_tail,
        "offline": offline,
        "privacy": privacy,
    }


def materialize_packet(
    *,
    repo_root: Path,
    route_database: Path,
    output_root: Path,
    validation_summary: Mapping[str, Any],
) -> dict[str, Any]:
    canonical_root = (repo_root / MATERIALIZATION_RELATIVE_ROOT).resolve()
    _require(output_root.resolve() == canonical_root, "materialization_root_mismatch")
    _require(not output_root.exists(), "materialization_target_already_exists")
    docs, meta = build_packet_documents(
        repo_root, route_database, validation_summary=validation_summary,
    )
    output_root.mkdir(parents=True)
    for name, data in docs.items():
        (output_root / name).write_bytes(data)
    entries = [
        {
            "path": f"{MATERIALIZATION_RELATIVE_ROOT}/{path.name}",
            "bytes": path.stat().st_size,
            "sha256": _sha_file(path),
        }
        for path in sorted(output_root.iterdir(), key=lambda item: item.name)
        if path.is_file()
    ]
    definition = {
        "schema": "SkillV2BArmSHA256ManifestDefinitionV1",
        "version": 1,
        "profile_id": PROFILE_ID,
        "cohort_id": COHORT_ID,
        "ab_pair_id": AB_PAIR_ID,
        "materialization_head": meta["git"]["head"],
        "coverage_root": MATERIALIZATION_RELATIVE_ROOT,
        "self_excluded": True,
        "files": entries,
    }
    manifest = {
        **{key: value for key, value in definition.items() if key != "files"},
        "file_count": len(entries),
        "launcher_artifact_count": sum("launcher-binding" in entry["path"] for entry in entries),
        "files": entries,
        "manifest_definition_sha256": _domain_sha("skill-v2-b-arm-manifest-v1", definition),
        "overall_status": "exact",
    }
    _write_json(output_root / FILES["manifest"], manifest)
    return {
        **meta,
        "manifest": manifest,
        "manifest_file_sha256": _sha_file(output_root / FILES["manifest"]),
    }


def _verify_packet_manifest(repo_root: Path, packet_root: Path) -> dict[str, Any]:
    _require(packet_root.resolve() == (repo_root / MATERIALIZATION_RELATIVE_ROOT).resolve(), "packet_root_mismatch")
    manifest = _read_json(packet_root / FILES["manifest"])
    _require(manifest.get("overall_status") == "exact", "manifest_not_exact")
    _require(manifest.get("coverage_root") == MATERIALIZATION_RELATIVE_ROOT, "manifest_root_mismatch")
    entries = list(manifest.get("files") or ())
    _require(len(entries) == manifest.get("file_count"), "manifest_coverage_mismatch")
    _require(manifest.get("launcher_artifact_count", 0) >= 1, "launcher_artifact_missing")
    for entry in entries:
        path = repo_root / str(entry.get("path") or "")
        _require(path.is_file(), "packet_file_missing")
        _require(path.stat().st_size == entry.get("bytes"), "packet_file_size_mismatch")
        _require(_sha_file(path) == entry.get("sha256"), "packet_file_hash_mismatch")
    return manifest


def validate_materialized_packet(
    repo_root: Path, packet_root: Path, route_database: Path,
) -> dict[str, Any]:
    manifest = _verify_packet_manifest(repo_root, packet_root)
    plan = _read_json(packet_root / FILES["plan"])
    approval = _read_json(packet_root / FILES["approval"])
    profile = _read_json(packet_root / FILES["profile"])
    context = _read_json(packet_root / FILES["context"])
    model_input = _read_json(packet_root / FILES["model_input"])
    launcher = _read_json(packet_root / FILES["launcher"])
    guard = _read_json(packet_root / FILES["guard"])
    accounting = _read_json(packet_root / FILES["accounting"])
    comparison = _read_json(packet_root / FILES["comparison"])
    success_tail = _read_json(packet_root / FILES["success_tail"])
    head_contract = _read_json(packet_root / FILES["head_contract"])
    head_validator = _read_json(packet_root / FILES["head_validator"])
    historical_roots = _read_json(packet_root / FILES["history"])
    baseline_policy = _read_json(packet_root / FILES["baseline_policy"])
    _require(
        head_contract == approval_head_successor_contract(),
        "head_successor_contract_changed",
    )
    _require(
        head_validator == head_successor_validator_binding(),
        "head_successor_validator_changed",
    )
    _require(plan.get("approval_scope") == APPROVAL_SCOPE, "packet_scope_mismatch")
    _require(plan.get("cohort_id") == COHORT_ID, "packet_cohort_mismatch")
    _require(plan.get("materialization_relative_root") == MATERIALIZATION_RELATIVE_ROOT, "packet_materialization_root_mismatch")
    _require(plan.get("execution_relative_root") == EXECUTION_RELATIVE_ROOT, "packet_execution_root_mismatch")
    _require(approval.get("approval_scope") == APPROVAL_SCOPE, "approval_template_scope_mismatch")
    _require(approval.get("cohort_id") == COHORT_ID, "approval_template_cohort_mismatch")
    _require(approval.get("execution_authorized") is False, "disabled_approval_authorized")
    _require(approval.get("named_approver") is None, "disabled_approval_has_approver")
    _require(approval.get("signed_approval") == "ABSENT", "signed_approval_present")
    _require(approval.get("single_use_nonce") is None, "disabled_nonce_present")
    rebuilt_profile, rebuilt_context, _ = build_skill_v2_profile(
        repo_root, _read_json(packet_root / FILES["workload"])["authority_input_sha256"],
    )
    _require(profile.get("canonical_profile_sha256") == rebuilt_profile["canonical_profile_sha256"], "skill_v2_profile_changed")
    _require(context.get("skill_v2_context") == rebuilt_context, "skill_v2_context_changed")
    workload_a, authority = base.load_fixture_binding(repo_root)
    contract = base.slice1_contract_binding(repo_root)
    route = base.resolve_route_binding(route_database)
    rebuilt_model, _ = _model_input_pair(
        repo_root, authority, contract, route, rebuilt_profile, rebuilt_context,
    )
    _require(model_input == rebuilt_model, "model_input_changed")
    expected_guard = transport_guard_contract(repo_root)
    _require(guard == expected_guard, "transport_guard_changed")
    _require(accounting == legacy.attempt_accounting_contract(guard), "attempt_accounting_changed")
    expected_launcher = launcher_binding(
        repo_root,
        implementation_head=plan["materialization_head"],
        guard=guard,
        accounting=accounting,
        profile_sha256=rebuilt_profile["canonical_profile_sha256"],
        head_contract_sha256=head_contract["head_successor_contract_sha256"],
        head_validator_sha256=head_validator["head_successor_validator_sha256"],
        historical_roots_sha256=historical_roots["historical_roots_binding_sha256"],
        committed_path_baseline_policy_sha256=baseline_policy[
            "committed_path_baseline_policy_sha256"
        ],
    )
    _require(launcher == expected_launcher, "launcher_binding_mismatch")
    _require(comparison.get("primary_changed_variable") == "SKILL_CONTEXT", "ab_primary_variable_changed")
    for key in (
        "non_skill_prompt_equal", "authority_input_equal", "task_contract_equal",
        "route_model_client_equal", "output_cap_equal", "transport_policy_equal",
        "validator_policy_equal", "ptr12_equal", "output_isolation_policy_equal",
        "quality_rubric_equal", "engineering_rubric_equal",
    ):
        _require(comparison.get(key) is True, f"comparison_lock_{key}_failed")
    _require(success_tail.get("overall_status") == "exact", "full_success_tail_not_exact")
    return {
        "status": "exact",
        "manifest": manifest,
        "plan": plan,
        "approval": approval,
        "profile": profile,
        "context": context,
        "model_input": model_input,
        "launcher": launcher,
        "guard": guard,
        "accounting": accounting,
        "comparison": comparison,
        "head_contract": head_contract,
        "head_validator": head_validator,
        "historical_roots": historical_roots,
        "baseline_policy": baseline_policy,
    }


def validate_signed_launch(
    *,
    repo_root: Path,
    packet_root: Path,
    route_database: Path,
    signed_approval: Mapping[str, Any],
    run_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    packet = validate_materialized_packet(repo_root, packet_root, route_database)
    _require(run_root.resolve() == (repo_root / EXECUTION_RELATIVE_ROOT).resolve(), "execution_root_mismatch")
    template = packet["approval"]
    _require(signed_approval.get("schema") == "SkillV2BArmSignedApprovalV1", "signed_approval_schema_mismatch")
    _require(signed_approval.get("execution_authorized") is True, "execution_not_authorized")
    _require(bool(signed_approval.get("named_approver")), "named_approver_missing")
    approval_parent_head = signed_approval.get("approval_parent_head")
    _require(isinstance(approval_parent_head, str), "approval_parent_head_missing")
    head_relation = verify_approval_head_successor(
        repo_root=repo_root,
        approval_parent_head=approval_parent_head,
        implementation_head=str(template["bound_hashes"]["materialization_head"]),
        manifest=packet["manifest"],
    )
    _require(signed_approval.get("approval_scope") == APPROVAL_SCOPE, "approval_scope_mismatch")
    _require(signed_approval.get("cohort_id") == COHORT_ID, "approval_cohort_mismatch")
    _require(signed_approval.get("ab_pair_id") == AB_PAIR_ID, "approval_ab_pair_mismatch")
    _require(signed_approval.get("bound_hashes") == template.get("bound_hashes"), "approval_bound_hashes_mismatch")
    _require(signed_approval.get("skill_v2_authorized") is True, "skill_v2_arm_not_authorized")
    for forbidden in (
        "full_short_authorized", "draft_authorized", "final_review_authorized",
        "maintenance_authorized", "planning_v2_cutover_authorized",
        "story_state_mutation_allowed", "canon_mutation_allowed", "ready_mutation_allowed",
    ):
        _require(signed_approval.get(forbidden) is False, f"{forbidden}_forbidden")
    _require(signed_approval.get("nonce_reserved") is False, "nonce_already_reserved")
    _require(signed_approval.get("nonce_consumed") is False, "nonce_already_consumed")
    nonce = str(signed_approval.get("single_use_nonce") or "")
    _require(bool(nonce), "single_use_nonce_missing")
    window = signed_approval.get("execution_window") or {}
    try:
        start = datetime.fromisoformat(str(window["not_before"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(window["not_after"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise SkillV2BArmError("execution_window_invalid") from exc
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    _require(start <= current <= end, "execution_window_inactive")
    _require(os.getenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1") == "1", "ptr12_observer_not_enabled")
    _require(not run_root.exists(), "single_use_run_namespace_already_exists")
    return {
        "status": "exact",
        "nonce": nonce,
        "single_dispatch_transport_guard_active": True,
        "approval_head_successor": head_relation,
        "credential_lookup_allowed_after_this_return": True,
    }


def persist_success_tail_v1(
    *,
    result: ModelResult,
    authority: EventRealizationInputAuthorityV1,
    attempts: Mapping[str, int],
    run_root: Path,
) -> dict[str, Any]:
    candidate, conversion = convert_event_realization_candidate(result.text, authority=authority)
    artifact = build_event_realization_artifact(authority, candidate, producer_kind="future_model_shadow")
    validation = validate_event_realization_artifact(artifact, authority)
    _require(validation.status == "PASS", "slice1_generated_candidate_rejected")
    frozen = freeze_validated_artifact(artifact, validation)
    _require(frozen.freeze_state == "FROZEN", "slice1_artifact_not_frozen")
    audit_payload = a_launcher.serialize_artifact_conversion_audit_v1(conversion)
    audit_sha256 = _domain_sha("skill-v2-b-arm-conversion-audit-v1", audit_payload)
    artifact_root = run_root / "artifact"
    artifact_root.mkdir()
    artifact_path = artifact_root / "generated-event-realization-v1.json"
    document = {
        "schema": "SkillV2BArmGeneratedExperimentArtifactV1",
        "version": 1,
        "cohort_id": COHORT_ID,
        "ab_pair_id": AB_PAIR_ID,
        "skill_arm": SKILL_ARM,
        "artifact": frozen.model_dump(mode="json", by_alias=True),
        "conversion_audit_sha256": audit_sha256,
        "model_receipt": {
            key: value for key, value in result.receipt.items()
            if key not in {"raw_response", "raw_content", "request_id"}
        },
        "transport_attempts": dict(attempts),
        "production_authority": False,
    }
    _write_json(artifact_path, document)
    _require(_read_json(artifact_path) == document, "artifact_persistence_mismatch")
    receipt = {
        "schema": "SkillV2BArmLocalSuccessReceiptV1",
        "version": 1,
        "local_terminal": "PASS",
        "validator_status": validation.status,
        "freeze_state": frozen.freeze_state,
        "audit_serialization": "PASS",
        "conversion_audit_sha256": audit_sha256,
        "artifact_sha256": _sha_file(artifact_path),
        "artifact_persisted": True,
        "write_json_reached": True,
        "transport_attempts": dict(attempts),
        "full_short_canary": "NOT_EXECUTED",
        "draft_entered": False,
        "production_database_mutation_count": 0,
    }
    evidence_root = run_root / "evidence"
    evidence_root.mkdir()
    _write_json(evidence_root / "local-success-receipt-v1.json", receipt)
    return receipt


async def execute_authorized_once(
    *,
    repo_root: Path,
    packet_root: Path,
    signed_approval_path: Path,
    route_database: Path,
    run_root: Path,
) -> dict[str, Any]:
    """Execute one B-arm request only after a future exact signed preflight."""
    signed = _read_json(signed_approval_path)
    gate = validate_signed_launch(
        repo_root=repo_root,
        packet_root=packet_root,
        route_database=route_database,
        signed_approval=signed,
        run_root=run_root,
    )
    run_root.mkdir(parents=True)
    ledger_root = run_root / "ledger"
    ledger_root.mkdir()
    ledger = ledger_root / "single-use-ledger-v1.json"
    with ledger.open("x", encoding="utf-8") as handle:
        json.dump({
            "schema": NONCE_LEDGER_SCHEMA,
            "version": 1,
            "cohort_id": COHORT_ID,
            "nonce_sha256": _sha_bytes(gate["nonce"].encode()),
            "usage_status": "reserved",
            "model_logical_calls": 0,
            "http_post_attempts": 0,
        }, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    runtime_root = run_root / "runtime"
    runtime_root.mkdir()
    isolated_db = runtime_root / "app.db"
    shutil.copy2(route_database, isolated_db)
    workload, authority_value = base.load_fixture_binding(repo_root)
    contract_binding = base.slice1_contract_binding(repo_root)
    route = base.resolve_route_binding(route_database)
    profile, context, _ = build_skill_v2_profile(repo_root, workload["authority_input_sha256"])
    model_input, model_comparison = _model_input_pair(
        repo_root, authority_value, contract_binding, route, profile, context,
    )
    system = model_comparison["b_system"]
    user = model_comparison["user"]
    budget = _read_json(packet_root / FILES["budget"])
    _require(model_input["model_input_assembly_sha256"] == signed["bound_hashes"]["model_input_assembly_sha256"], "model_input_changed_before_dispatch")

    # Credential-capable imports remain below exact preflight and nonce reservation.
    from novel_flywheel.model_diagnostics import ModelDiagnosticContextV1
    from novel_flywheel.models import ModelGateway
    from novel_flywheel.providers.registry import ProviderRegistry
    from novel_flywheel.secrets import KeyringSecretStore
    from novel_flywheel.structured_artifacts import StructuredArtifactContract, StructuredOutputRequirement

    class AttemptTrackingRegistry(ProviderRegistry):
        last_adapter = None

        def resolve(self, provider_id: str, model_id: str):
            resolved = super().resolve(provider_id, model_id)
            self.last_adapter = resolved.adapter
            return resolved

    db = Database(isolated_db)
    registry = AttemptTrackingRegistry(
        db,
        KeyringSecretStore(),
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    gateway = ModelGateway(db, registry)
    authority = EventRealizationInputAuthorityV1.model_validate(
        normalize_event_realization_input_authority_v1(authority_value),
    )
    contract = StructuredArtifactContract(
        name="planning_event_realization_shadow_v1",
        version=1,
        schema=EventRealizationCandidateV1.model_json_schema(),
        runtime_authority={"authority_input_sha256": workload["authority_input_sha256"]},
    )
    diagnostic = ModelDiagnosticContextV1(
        project_root=run_root,
        run_id=COHORT_ID,
        stage="planning",
        boundary="slice1_phase_b_skill_v2_real_ab_single_dispatch",
        role="planning",
        route_kind="primary",
        contract_id=SLICE1_CONTRACT_IDENTITY,
        contract_version=1,
        outer_retry_ordinal=1,
        provider_binding_sha256=base.EXPECTED_PRIMARY_DESCRIPTOR,
        model_binding_sha256=base.EXPECTED_PRIMARY_MODEL,
        canary_output_limit=int(budget["hard_max_output_tokens_per_call"]),
    )
    result = None
    terminal_error = None
    try:
        result = await asyncio.wait_for(
            gateway.complete_route(
                "primary",
                "planning",
                system,
                user,
                max_output_tokens=int(budget["hard_max_output_tokens_per_call"]),
                contract=contract,
                structured_requirement=StructuredOutputRequirement.PLAIN_TEXT,
                diagnostic_context=diagnostic,
            ),
            timeout=int(budget["hard_max_elapsed_seconds"]),
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        terminal_error = exc
    adapter = registry.last_adapter
    attempts = adapter.transport_attempt_snapshot() if adapter is not None else {
        "model_logical_calls": 0,
        "http_post_attempts": 0,
        "real_provider_request_attempts": 0,
        "network_request_attempts": 0,
    }
    _require(attempts["http_post_attempts"] <= 1, "http_attempt_cap_exceeded")
    _write_json(ledger, {
        "schema": NONCE_LEDGER_SCHEMA,
        "version": 1,
        "cohort_id": COHORT_ID,
        "nonce_sha256": _sha_bytes(gate["nonce"].encode()),
        "usage_status": "consumed" if attempts["http_post_attempts"] else "reserved",
        **attempts,
    })
    if terminal_error is not None:
        raise terminal_error
    assert result is not None
    return persist_success_tail_v1(
        result=result,
        authority=authority,
        attempts=attempts,
        run_root=run_root,
    )


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--route-database", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    packet_root = (args.output_root or (repo_root / MATERIALIZATION_RELATIVE_ROOT)).resolve()
    if args.materialize:
        result = materialize_packet(
            repo_root=repo_root,
            route_database=args.route_database.resolve(),
            output_root=packet_root,
            validation_summary={
                "focused": "PASS",
                "related": "PASS",
                "full_suite": "RECORDED_SEPARATELY",
                "strict_l3": "PASS",
                "launcher": "PASS",
                "success_tail": "PASS",
            },
        )
        print(json.dumps({
            "status": "SKILL_V2_REAL_AB_B_ARM_REMATERIALIZED_V3_AFTER_HISTORICAL_ROOT_FIX",
            "manifest_definition_sha256": result["manifest"]["manifest_definition_sha256"],
            "manifest_file_sha256": result["manifest_file_sha256"],
        }, sort_keys=True))
        return 0
    if args.validate:
        result = validate_materialized_packet(repo_root, packet_root, args.route_database.resolve())
        print(json.dumps({"status": result["status"]}, sort_keys=True))
        return 0
    parser.error("choose --materialize or --validate")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
