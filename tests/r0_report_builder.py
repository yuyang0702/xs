from __future__ import annotations

import ast
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from r0_incident_corpus import (
    HIGH_FREQUENCY_INCIDENT_KEYS,
    REPLAYABILITY_STATIC,
)


def short_stage_coverage_matrix(root: Path) -> dict[str, Any]:
    source = root / "src" / "novel_flywheel" / "workflows.py"
    text = source.read_text(encoding="utf-8")
    required_symbols = [
        "async def _plan_short_ir_first(",
        "async def _ensure_short_causal_chain(",
        "async def _generate_short_execution_fragment(",
        "async def _review_short_execution_fragment(",
        "async def _verify_draft_semantic_node(",
        "async def _verify_whole_draft_semantics(",
        "async def _reader_review(",
        "async def _close_short_maintenance_window(",
        "async def _close_short_maintenance_authority(",
        "async def _repair_short_revision_semantic_group(",
        "async def _stage(",
    ]
    missing = [symbol for symbol in required_symbols if symbol not in text]
    if missing:
        raise AssertionError(f"stage evidence symbols missing: {missing}")
    tree = ast.parse(text)
    functions = {
        node.name: node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    def stage_calls(function_name: str) -> list[tuple[str, bool]]:
        calls = []
        for node in ast.walk(functions[function_name]):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"_stage", "_stage_with_role_fallback"}:
                continue
            calls.append((
                node.func.attr,
                "execution_spec" in {item.arg for item in node.keywords},
            ))
        return calls

    assert ("_stage", True) in stage_calls("_plan_short_ir_first")
    assert ("_stage", True) in stage_calls("_ensure_short_causal_chain")
    assert ("_stage", True) in stage_calls("_generate_short_execution_fragment")
    assert ("_stage", True) in stage_calls("_verify_draft_semantic_node")
    assert ("_stage", False) in stage_calls("_draft_short_segment_task")
    for function_name in (
        "_close_short_maintenance_window",
        "_close_short_maintenance_authority",
    ):
        calls = stage_calls(function_name)
        assert ("_stage_with_role_fallback", False) in calls
        assert not any(has_spec for _callee, has_spec in calls)
    assert ("_stage", True) in stage_calls(
        "_repair_short_revision_semantic_group"
    )
    assert ("_stage", False) in stage_calls("_repair_polish_semantic_segment")

    rows = [
        _row(
            "Planning", "yes", "yes", "yes", "yes", "yes", "yes",
            "partial", "yes", "yes", "26 synthetic incident workflows",
            "WorkflowService._short_pipeline",
            "_plan_short_ir_first -> _stage -> execute_contract_runtime",
        ),
        _row(
            "Causal", "yes", "yes", "yes", "yes", "yes", "yes",
            "n/a", "yes", "no", "unknown: no bound historical incident",
            "WorkflowService._short_pipeline",
            "_ensure_short_causal_chain -> _stage -> execute_contract_runtime",
        ),
        _row(
            "Manifest", "yes", "yes", "yes", "yes", "yes", "yes",
            "yes", "yes", "no", "unknown: no bound historical incident",
            "WorkflowService._short_pipeline",
            "_generate_short_execution_fragment/_review_short_execution_fragment -> _stage -> execute_contract_runtime",
        ),
        _row(
            "Draft", "partial", "yes", "not_applicable_to_prose", "partial",
            "partial", "yes", "yes", "yes", "yes",
            "unknown: no bound historical incident",
            "WorkflowService._short_pipeline",
            "prose _stage; then _verify_draft_semantic_node through Contract Runtime",
        ),
        _row(
            "Semantic Review", "yes", "yes", "yes", "yes", "yes", "yes",
            "yes", "yes", "no", "unknown: no bound historical incident",
            "WorkflowService._short_pipeline",
            "_verify_draft_semantic_node/_verify_whole_draft_semantics -> _stage -> execute_contract_runtime",
        ),
        _row(
            "Quality", "yes", "yes", "yes", "yes", "yes", "yes",
            "yes", "yes", "yes", "unknown: no bound historical incident",
            "WorkflowService._short_pipeline",
            "_reader_review/_review_with_escalation -> _stage -> execute_contract_runtime plus local quality gates",
        ),
        _row(
            "Maintenance", "no", "yes", "partial_after_stage", "yes_after_stage",
            "no_manual_loop", "partial_role_fallback", "yes_manual_second_attempt",
            "yes", "yes", "unknown: no bound historical incident",
            "WorkflowService._short_pipeline",
            "_close_short_maintenance_authority/_window -> _stage_with_role_fallback (no execution_spec) -> local convert/adapter/domain merge",
        ),
        _row(
            "Repair", "partial", "yes", "partial", "partial", "partial",
            "partial", "partial", "yes", "yes",
            "unknown: no bound historical incident",
            "review/semantic/quality callers",
            "revision_patch_contract paths use Contract Runtime; prose and legacy planning repair sibling paths do not uniformly do so",
        ),
    ]
    return {
        "schema": "R0ShortStageCoverageMatrixV1",
        "source_file": "src/novel_flywheel/workflows.py",
        "rows": rows,
        "unknown_policy": "absence of incident-bound evidence remains unknown",
    }


def _row(
    stage: str,
    unified: str,
    completeness: str,
    normalize: str,
    validation: str,
    retry: str,
    fallback: str,
    repair_reentry: str,
    root_cause: str,
    sibling: str,
    incident_evidence: str,
    caller: str,
    callee: str,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "unified_contract_runtime": unified,
        "completeness_truncation": completeness,
        "deterministic_local_normalize": normalize,
        "schema_adapter_domain_validator": validation,
        "protocol_retry_consistent": retry,
        "fallback_consistent": fallback,
        "repair_secondary_reenters_same_runtime": repair_reentry,
        "terminal_root_cause_preserved": root_cause,
        "sibling_bypass_present": sibling,
        "incident_evidence": incident_evidence,
        "caller": caller,
        "callee": callee,
    }


def incident_level_report(manifest: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for incident in manifest["incidents"]:
        executable = (
            incident["current_incident_key"] in HIGH_FREQUENCY_INCIDENT_KEYS
        )
        rows.append({
            **incident,
            "validation_status": (
                "SYNTHETIC_CURRENT_RUNTIME_WORKFLOW_RECOVERED"
                if executable else
                "STATIC_CURRENT_PATH_ONLY"
                if incident["replayability"] == REPLAYABILITY_STATIC else
                "UNVERIFIABLE_LEGACY"
            ),
            "boundary_recovered": True if executable else None,
            "stage_recovered": True if executable else None,
            "workflow_recovered": True if executable else None,
            "controlled_nonterminal": False if executable else None,
            "final_terminal_outcome": (
                "WORKFLOW_RECOVERED" if executable else "NOT_EXECUTED"
            ),
            "validation_command": (
                "pytest -q tests/test_r0_high_frequency_replay.py"
                if executable else None
            ),
        })
    return {
        "schema": "R0IncidentLevelReportV1",
        "incident_count": len(rows),
        "rows": rows,
    }


def family_level_report(incident_report: dict[str, Any]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in incident_report["rows"]:
        groups[row["current_reclassified_family"]].append(row)
    rows = []
    for family, incidents in sorted(groups.items()):
        outcomes = Counter(item["final_terminal_outcome"] for item in incidents)
        rows.append({
            "family": family,
            "incident_count": len(incidents),
            "stored_family_count": len({
                item["stored_historical_family"] for item in incidents
                if item["stored_historical_family"]
            }),
            "current_runtime_workflow_recovered": outcomes["WORKFLOW_RECOVERED"],
            "not_executed": outcomes["NOT_EXECUTED"],
            "residual_status": (
                "synthetic_replay_recovered"
                if outcomes["WORKFLOW_RECOVERED"] == len(incidents)
                else "partially_replayed_historical_terminal"
                if outcomes["WORKFLOW_RECOVERED"]
                else "historical_terminal_not_closed"
            ),
        })
    return {"schema": "R0FamilyLevelReportV1", "rows": rows}


def primary_scope_unclassified(incident_report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in incident_report["rows"]
        if row["primary_live_scope"]
        and row["current_reclassified_family"].startswith("unclassified.")
    ]


def residual_terminal_families(family_report: dict[str, Any]) -> dict[str, Any]:
    rows = [
        row for row in family_report["rows"]
        if row["residual_status"] != "synthetic_replay_recovered"
    ]
    return {
        "schema": "R0ResidualTerminalFamiliesV1",
        "family_count": len(rows),
        "incident_count": sum(row["not_executed"] for row in rows),
        "rows": rows,
    }
