"""Hash-only Phase 0.5 evidence helpers for production-shaped offline runs."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from novel_flywheel.generated_artifacts import ReliabilityTraceEnvelopeV1
from novel_flywheel.project_transactions import (
    canonical_json_sha256,
    load_project_mutation_journal,
    project_mutation_journal_path,
)
from novel_flywheel.reliability_trace import (
    artifact_binding_matrix,
    emit_observation,
    event_type_coverage_matrix,
    projection_provenance_matrix,
    read_trace,
    trace_file_for_project,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def events_for_runs(
    project_root: Path, run_ids: Iterable[str],
) -> list[ReliabilityTraceEnvelopeV1]:
    selected = set(run_ids)
    return [
        item for item in read_trace(trace_file_for_project(project_root)).events
        if item.run_id in selected
    ]


def inject_missing_event_types(
    project_root: Path,
    *,
    correlation_id: str,
    workflow_name: str,
    run_ids: Iterable[str],
) -> list[str]:
    """Inject only missing event types and mark every record synthetic.

    The injection lives in the test harness, never in a production workflow.
    It creates no business artifact and does not claim an inferred causal edge.
    """

    current = events_for_runs(project_root, run_ids)
    missing = list(event_type_coverage_matrix(current)["coverage_gaps"])
    source_hash = _hash(f"{workflow_name}:source")
    target_hash = _hash(f"{workflow_name}:target")
    payloads: dict[str, tuple[str, dict[str, Any]]] = {
        "authority_read": (
            "occurred_current",
            {
                "authority_type": "StoryState",
                "reader": "controlled_failure_injection",
            },
        ),
        "proposed_claim": (
            "future_normative",
            {
                "claim_kind": "controlled_commitment",
                "shadow_only": True,
                "affects_business_decision": False,
            },
        ),
        "promotion_write": (
            "occurred_current",
            {"store": "SyntheticObservation", "writer": "phase05_harness"},
        ),
        "projection_read": (
            "occurred_current",
            {
                "projection": "controlled_missing_projection",
                "revision_metadata_present": False,
                "stale": "unknown",
            },
        ),
        "repair_diff": (
            "occurred_current",
            {
                "allowed_scope_source": "controlled_failure_injection",
                "changed_paths": ["$.synthetic_failure"],
                "validators_rerun": ["diagnostic_only"],
            },
        ),
        "recovery_attempt": (
            "unknown",
            {
                "attempt_id": "synthetic-attempt",
                "parent_attempt_id": None,
                "action": "controlled_failure_injection",
                "outcome": "observed_only",
                "model_call_delta": 0,
            },
        ),
        "resume_binding": (
            "occurred_current",
            {
                "artifact_type": "legacy-controlled-artifact",
                "binding_status": "unverifiable_legacy",
            },
        ),
        "authority_evidence_conflict": (
            "occurred_current",
            {
                "shadow_slot": _hash(f"{workflow_name}:slot"),
                "story_time": "controlled-comparable-time",
                "left_source_hash": source_hash,
                "right_source_hash": target_hash,
                "values_disagree": True,
                "resolution": "unresolved_phase0",
            },
        ),
    }
    for event_type in missing:
        semantic_domain, payload = payloads[event_type]
        emit_observation(
            project_root,
            event_type=event_type,
            source_component="phase05.controlled_failure_injection",
            source_writer=workflow_name,
            observation_status=(
                "confirmed"
                if event_type != "projection_read" else "unknown"
            ),
            payload={
                **payload,
                "synthetic": True,
                "synthetic_reason": (
                    "event is not naturally reachable in this successful path"
                ),
                "workflow_name": workflow_name,
            },
            run_id=correlation_id,
            stage_id="phase05_controlled_failure_injection",
            semantic_domain=semantic_domain,
            object_old_hash=(
                source_hash if event_type == "repair_diff" else None
            ),
            object_new_hash=(
                target_hash if event_type in {"repair_diff", "promotion_write"}
                else None
            ),
        )
    return missing


def workflow_coverage(
    project_root: Path, run_ids: Iterable[str],
) -> dict[str, Any]:
    return event_type_coverage_matrix(events_for_runs(project_root, run_ids))


def projection_matrix(
    project_root: Path, run_ids: Iterable[str],
) -> list[dict[str, Any]]:
    return projection_provenance_matrix(events_for_runs(project_root, run_ids))


def binding_matrix(
    project_root: Path, run_ids: Iterable[str],
) -> list[dict[str, Any]]:
    return artifact_binding_matrix(events_for_runs(project_root, run_ids))


def maintenance_baseline(
    project_root: Path, run_id: str,
) -> dict[str, Any]:
    events = events_for_runs(project_root, [run_id])
    decisions = [
        item for item in events
        if item.event_type == "promotion_write"
        and item.payload.get("store") == "MaintenanceDecision"
    ]
    rows = [{
        "input_hash": item.payload.get("input_hash"),
        "output_hash": item.payload.get("output_hash"),
        "authority_revision": item.authority_revision,
        "authority_hash": item.authority_hash,
        "candidate_hash": item.payload.get("candidate_hash"),
        "maintenance_decision": item.payload.get("decision"),
        "evidence_policy": item.payload.get("evidence_policy"),
        "projection_effects": list(item.payload.get("projection_effects") or []),
    } for item in decisions]
    return {
        "schema": "Phase05MaintenanceBaselineV1",
        "decisions": rows,
        "repeatability_sha256": canonical_json_sha256(rows),
    }


def saga_baseline(project_root: Path, run_id: str) -> dict[str, Any]:
    journal = load_project_mutation_journal(
        project_mutation_journal_path(project_root, run_id),
    )
    target = journal.story_state
    artifacts = [
        item.model_dump(mode="json") for item in journal.artifacts
    ]
    effects = [
        item.model_dump(mode="json") for item in journal.memory_effects
    ]
    stable = {
        "operation": journal.operation,
        "commit_result": journal.status,
        "authority_revision": (
            target.target_revision
            if target is not None else journal.expected_story_state_revision
        ),
        "candidate_hash": target.state_sha256 if target is not None else None,
        "journal_target_hash": canonical_json_sha256(artifacts),
        "journal_effect_hash": canonical_json_sha256(effects),
        "projection_effects": [item.kind for item in journal.memory_effects],
        "artifact_hashes": artifacts,
    }
    return {
        "schema": "Phase05SagaBaselineV1",
        "input_hash": journal.source_authority_sha256,
        "output_hash": target.state_sha256 if target is not None else (
            canonical_json_sha256(journal.model_dump(mode="json"))
        ),
        **stable,
        "repeatability_sha256": canonical_json_sha256(stable),
    }

