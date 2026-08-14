from __future__ import annotations

import copy
from pathlib import Path
import subprocess

from novel_flywheel.runtime_fingerprint import (
    canary_runtime_fingerprint_preflight_v1,
    collect_build_fingerprint,
    runtime_source_revalidation,
)


def binding(kind: str) -> dict:
    runtime = "3" * 64
    return {
        "binding_definition_sha256": ("1" if kind == "origin" else "2") * 64,
        "binding_kind": kind,
        "binding_status": "exact",
        "runtime_execution_fingerprint": runtime,
        "origin_runtime_execution_fingerprint": runtime,
        "build_fingerprint_sha256": "a" * 64,
        "execution_config_fingerprint_sha256": "b" * 64,
    }


def exact_git_revalidation() -> dict:
    return {
        "deployment_mode": "git_workspace",
        "comparison_status": "exact",
        "runtime_build_status": "verified_git_workspace",
        "source_changed_after_process_start": False,
        "production_source_clean": True,
        "installed_manifest_exact": None,
        "embedded_manifest_exact": None,
    }


def test_git_canary_preflight_is_pure_and_mode_specific() -> None:
    origin = binding("origin")
    executor = binding("executor")
    inputs = {
        "deployment_mode": "git_workspace",
        "approved_build_fingerprint": "a" * 64,
        "approved_execution_config_fingerprint": "b" * 64,
        "origin_binding": origin,
        "executor_binding": executor,
        "current_source_revalidation": exact_git_revalidation(),
        "sidecar_validation": {"valid": True, "validation_status": "exact"},
    }
    before = copy.deepcopy(inputs)

    first = canary_runtime_fingerprint_preflight_v1(**inputs)
    second = canary_runtime_fingerprint_preflight_v1(**inputs)

    assert first.eligible is True
    assert first.blocked_reason_codes == ()
    assert first.validation_receipt_sha256 == second.validation_receipt_sha256
    assert inputs == before


def test_preflight_blocks_legacy_conflict_unapproved_and_source_change_before_boundary() -> None:
    paid_boundary_calls = 0
    source = exact_git_revalidation()
    source["comparison_status"] = "changed"
    source["runtime_build_status"] = "runtime_not_exact"
    source["source_changed_after_process_start"] = True
    origin = binding("origin")
    origin["binding_status"] = "unverifiable_legacy"

    receipt = canary_runtime_fingerprint_preflight_v1(
        deployment_mode="git_workspace",
        approved_build_fingerprint="f" * 64,
        approved_execution_config_fingerprint="e" * 64,
        origin_binding=origin,
        executor_binding=binding("executor"),
        current_source_revalidation=source,
        sidecar_validation={"valid": False, "validation_status": "invalid"},
        contradictory_binding=True,
    )
    if receipt.eligible:  # This is the fake paid boundary.
        paid_boundary_calls += 1

    assert receipt.eligible is False
    assert paid_boundary_calls == 0
    assert {
        "build_fingerprint_unapproved",
        "contradictory_binding",
        "current_runtime_not_exact",
        "execution_config_fingerprint_unapproved",
        "git_workspace_not_verified",
        "origin_binding_not_exact",
        "sidecar_definition_not_exact",
        "source_changed_after_process_start",
    } <= set(receipt.blocked_reason_codes)


def test_packaged_preflight_does_not_inherit_git_workspace_authorization() -> None:
    receipt = canary_runtime_fingerprint_preflight_v1(
        deployment_mode="packaged",
        approved_build_fingerprint="a" * 64,
        approved_execution_config_fingerprint="b" * 64,
        origin_binding=binding("origin"), executor_binding=binding("executor"),
        current_source_revalidation=exact_git_revalidation(),
        sidecar_validation={"valid": True, "validation_status": "exact"},
    )

    assert receipt.eligible is False
    assert "packaged_manifest_not_verified" in receipt.blocked_reason_codes
    assert "installed_manifest_not_exact" in receipt.blocked_reason_codes
    assert "embedded_manifest_not_exact" in receipt.blocked_reason_codes


def test_source_revalidation_classifies_exact_source_build_and_provenance() -> None:
    process_build, process_children = collect_build_fingerprint()
    exact = runtime_source_revalidation(
        process_build, process_build,
        process_children=process_children, current_children=process_children,
    )
    assert exact["source_changed_after_process_start"] is False
    assert exact["build_changed_after_process_start"] is False

    provenance = copy.deepcopy(process_build)
    provenance["payload"]["child_definitions"]["git_provenance"] = {
        "schema": "RuntimeGitProvenanceV1", "definition_sha256": "9" * 64,
    }
    provenance_only = runtime_source_revalidation(
        process_build, provenance,
        process_children=process_children, current_children=process_children,
    )
    assert provenance_only["provenance_changed_only"] is True
    assert provenance_only["build_changed_after_process_start"] is False

    changed = copy.deepcopy(process_build)
    changed["payload"]["build_fingerprint_sha256"] = "8" * 64
    changed["payload"]["child_definitions"]["production_source"] = {
        "schema": "RuntimeProductionSourceManifestV1",
        "definition_sha256": "7" * 64,
    }
    source_changed = runtime_source_revalidation(
        process_build, changed,
        process_children=process_children, current_children=process_children,
    )
    assert source_changed["source_changed_after_process_start"] is True
    assert source_changed["build_changed_after_process_start"] is True
    assert source_changed["runtime_build_status"] == "runtime_not_exact"


def test_process_start_revalidation_rehashes_actual_changed_source_bytes(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "editable-workspace"
    package = repository / "src" / "novel_flywheel"
    package.mkdir(parents=True)
    (repository / "baml_src").mkdir()
    module = package / "module.py"
    module.write_text("VALUE = 'process-start'\n", encoding="utf-8")
    (repository / "baml_src" / "main.baml").write_text(
        "class Fixture {}\n", encoding="utf-8",
    )
    (repository / "pyproject.toml").write_text(
        "[project]\nname='fixture'\n", encoding="utf-8",
    )
    (repository / "start-novel-console.cmd").write_text(
        "@echo off\n", encoding="utf-8",
    )
    for arguments in (
        ("init",),
        ("config", "user.email", "fixture@example.invalid"),
        ("config", "user.name", "R0F Fixture"),
        ("add", "."),
        ("commit", "-m", "fixture"),
    ):
        subprocess.run(
            ["git", *arguments], cwd=repository, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
        )

    process_build, process_children = collect_build_fingerprint(module_file=module)
    module.write_text("VALUE = 'changed-after-start'\n", encoding="utf-8")
    current_build, current_children = collect_build_fingerprint(module_file=module)
    result = runtime_source_revalidation(
        process_build, current_build,
        process_children=process_children, current_children=current_children,
    )

    assert result["deployment_mode"] == "git_workspace"
    assert result["source_changed_after_process_start"] is True
    assert result["build_changed_after_process_start"] is True
    assert result["production_source_clean"] is False
    assert result["comparison_status"] == "changed"
    assert result["runtime_build_status"] == "runtime_not_exact"
