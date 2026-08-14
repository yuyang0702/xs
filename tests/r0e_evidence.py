"""Read-only builders for R0E evidence and conservative family gates."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


GATES = frozenset({
    "DEVELOPMENT_GO",
    "DEVELOPMENT_NO_GO",
    "MONITOR_ONLY",
    "NEEDS_PRODUCTION_EXPOSURE",
    "NOT_CURRENTLY_REACHABLE",
    "MECHANISM_FIX_CANDIDATE",
})

PARENT_HEAD = "5a152b097732447d4a5e1db2f9ef0215815bcb91"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path.name}")
    return value


def verify_parent_seal(root: Path) -> dict[str, Any]:
    seal_path = (
        root / "tests" / "fixtures" / "reliability" / "r0e"
        / "r0-parent-evidence-seal-v1.json"
    )
    seal = load_json(seal_path)
    mismatches = []
    for relative, expected in seal["sealed_files"].items():
        actual = file_sha256(root / relative)
        if actual != expected:
            mismatches.append({
                "path": relative, "expected": expected, "actual": actual,
            })
    return {**seal, "verified": not mismatches, "mismatches": mismatches}


def _evidence_class(rows: list[dict[str, Any]]) -> str:
    replayability = {str(row["replayability"]) for row in rows}
    if "exact_replayable" in replayability:
        return "A"
    if "structurally_reconstructable" in replayability:
        return "B"
    if replayability == {"static_path_verifiable"}:
        return "C"
    return "D"


def _runtime_boundary(family: str) -> str:
    if family.startswith("initialization."):
        return "initialization_skill_runtime"
    if family.startswith("provider."):
        return "provider_route_or_supervisor"
    if family.startswith("model.context_capacity"):
        return "stage_capacity_policy"
    if family == "model.output_truncated":
        return "provider_result_completeness"
    if family.startswith("planning."):
        return "planning_contract_or_domain_validation"
    if family.startswith("draft."):
        return "draft_semantic_or_split_merge"
    if family.startswith("runtime."):
        return "workflow_terminal_projection"
    return "unknown_legacy_boundary"


def _policy(family: str) -> tuple[str, str]:
    durable = (
        "docs/superpowers/specs/"
        "2026-08-11-durable-completion-ir-originality-r0-r6-design.md:93"
    )
    if family == "provider.credentials_unavailable":
        return "waiting_user", durable
    if family in {"provider.connection_failed", "provider.route_rejected"}:
        return "waiting_provider", durable
    if family.startswith("model.context_capacity"):
        return "resumable_failure_or_explicit_irrecoverable", (
            "docs/superpowers/specs/"
            "2026-08-04-production-incident-memory-design.md:27-31"
        )
    if family == "model.output_truncated":
        return "recover_then_resumable_or_explicit_terminal_on_exhaustion", (
            "docs/superpowers/specs/"
            "2026-08-02-adaptive-output-and-semantic-task-splitting-design.md:35"
        )
    return "unknown_requires_incident_contract", "unverified_legacy_policy"


def _priority(family: str, count: int, evidence_class: str) -> tuple[str, str]:
    if family in {
        "model.output_truncated",
        "runtime.primary_error_masked",
        "planning.review_protocol_route_exhausted",
    } or family.startswith("model.context_capacity"):
        return "P0", "shared recovery or root-cause boundary"
    if family.startswith("provider."):
        return "P0", "high exposure but policy-sensitive external failure"
    if family.startswith("unclassified.") and count >= 5:
        return "P0", "high-count generic legacy terminal evidence gap"
    if count >= 3 or evidence_class == "C":
        return "P1", "repeat count or statically reachable typed path"
    return "P2", "low-count or insufficient legacy evidence"


def _initial_gate(
    family: str, workflows: set[str], evidence_class: str,
) -> str:
    if "short-story" not in workflows:
        return "NOT_CURRENTLY_REACHABLE"
    if family.startswith("provider."):
        return "NEEDS_PRODUCTION_EXPOSURE"
    if evidence_class in {"C", "D"}:
        return "DEVELOPMENT_NO_GO"
    return "MONITOR_ONLY"


def residual_prioritization_matrix(root: Path) -> dict[str, Any]:
    report_root = root / "docs" / "superpowers" / "reports"
    residual = load_json(report_root / "r0-residual-terminal-families.json")
    incident_report = load_json(report_root / "r0-incident-level-report.json")
    manifest = load_json(report_root / "r0-incident-corpus-manifest.json")
    residual_ids = {
        str(incident["incident_id"])
        for incident in incident_report["rows"]
        if incident["final_terminal_outcome"] == "NOT_EXECUTED"
    }
    by_family: dict[str, list[dict[str, Any]]] = {}
    for incident in manifest["rows"]:
        if str(incident["incident_id"]) not in residual_ids:
            continue
        by_family.setdefault(
            str(incident["current_reclassified_family"]), [],
        ).append(incident)
    rows = []
    for residual_row in residual["rows"]:
        family = str(residual_row["family"])
        incidents = by_family[family]
        workflows = {str(item["workflow"]) for item in incidents}
        evidence_class = _evidence_class(incidents)
        expected, source = _policy(family)
        priority, reason = _priority(
            family, int(residual_row["not_executed"]), evidence_class,
        )
        short_reachability = (
            "reachable" if "short-story" in workflows
            else "not_in_short_workflow"
        )
        rows.append({
            "family": family,
            "historical_count": int(residual_row["not_executed"]),
            "current_short_reachability": short_reachability,
            "evidence_class": evidence_class,
            "executable_oracle": (
                "incident_bound_structural" if evidence_class == "B"
                else "current_static_path" if evidence_class == "C"
                else "none"
            ),
            "runtime_boundary": _runtime_boundary(family),
            "terminal_risk": (
                "high" if priority == "P0" else
                "medium" if priority == "P1" else "unknown"
            ),
            "priority": priority,
            "priority_reason": reason,
            "expected_policy_outcome": expected,
            "actual_outcome": "historical_terminal_not_replayed",
            "policy_source": source,
            "policy_violation": None,
            "gate": _initial_gate(family, workflows, evidence_class),
            "historical_incident_ids": sorted(
                str(item["incident_id"]) for item in incidents
            ),
        })
    return {
        "schema": "R0EResidualPrioritizationMatrixV1",
        "parent_head": PARENT_HEAD,
        "family_count": len(rows),
        "historical_incident_count": sum(
            int(row["historical_count"]) for row in rows
        ),
        "evidence_class_counts": dict(sorted(Counter(
            str(row["evidence_class"]) for row in rows
        ).items())),
        "rows": rows,
        "mechanism_probes": [
            {
                "probe": "maintenance_normal_window_contract_runtime_bypass",
                "historical_count": 0,
                "historical_family_binding": None,
                "classification": "EVIDENCE_GAP",
                "gate": "MECHANISM_FIX_CANDIDATE",
            },
            {
                "probe": "repair_secondary_output_contract_runtime_bypass",
                "historical_count": 0,
                "historical_family_binding": None,
                "classification": "EVIDENCE_GAP",
                "gate": "MECHANISM_FIX_CANDIDATE",
            },
        ],
    }


def primary_scope_unclassified_rows(root: Path) -> list[dict[str, Any]]:
    manifest = load_json(
        root / "docs" / "superpowers" / "reports"
        / "r0-incident-corpus-manifest.json"
    )
    return [
        row for row in manifest["rows"]
        if row["primary_live_scope"]
        and str(row["current_reclassified_family"]).startswith("unclassified.")
    ]
