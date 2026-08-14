"""Read-only, hash-only helpers for the R0 historical incident corpus."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from novel_flywheel.db import Database
from novel_flywheel.production_incidents import production_incident_catalog


FIX_EPOCHS_UTC = {
    "v3_start": "2026-08-12 04:06:08",
    "v3_declared_complete": "2026-08-12 15:06:11",
    "recovery_hardened": "2026-08-13 06:05:12",
}

HIGH_FREQUENCY_FAMILIES = frozenset({
    "planning.structure_drift",
    "parser.generated_artifact_shape",
})
HIGH_FREQUENCY_INCIDENT_KEYS = frozenset({
    "short-story:failed:planning.structure_drift",
    "short-story:failed:parser.generated_artifact_shape",
})

REPLAYABILITY_EXACT = "exact_replayable"
REPLAYABILITY_SYNTHETIC = "structurally_reconstructable"
REPLAYABILITY_STATIC = "static_path_verifiable"
REPLAYABILITY_INSUFFICIENT = "insufficient_evidence"


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    ).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def incident_catalog_version() -> str:
    return "sha256:" + canonical_sha256(production_incident_catalog())


def event_time_epoch(value: str | None) -> str:
    if not value:
        return "unknown_time"
    try:
        normalized = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "unknown_time"
    timestamp = normalized.strftime("%Y-%m-%d %H:%M:%S")
    if timestamp < FIX_EPOCHS_UTC["v3_start"]:
        return "pre_fix"
    if timestamp < FIX_EPOCHS_UTC["v3_declared_complete"]:
        return "migration_window"
    if timestamp < FIX_EPOCHS_UTC["recovery_hardened"]:
        return "post_declared_pre_hardening"
    return "post_hardening"


def _json_object(value: object) -> dict[str, Any]:
    try:
        decoded = json.loads(str(value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _runtime_build_status(events: Iterable[dict[str, Any]]) -> tuple[str, str | None]:
    keys = (
        "runtime_commit", "runtime_fingerprint", "source_commit",
        "source_fingerprint", "git_commit",
    )
    for event in events:
        metadata = _json_object(event.get("metadata_json"))
        for key in keys:
            value = str(metadata.get(key) or "").strip()
            if value:
                return "verified_commit", hashlib.sha256(
                    value.encode("utf-8"),
                ).hexdigest()
    return "unknown_runtime", None


def _first_failure(events: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    for event in events:
        metadata = _json_object(event.get("metadata_json"))
        failure_class = str(metadata.get("failure_class") or "").strip()
        failure_code = str(metadata.get("failure_code") or "").strip()
        event_type = str(event.get("event_type") or "")
        if failure_class or failure_code or event_type.endswith("_failed"):
            boundary = str(
                metadata.get("boundary") or event.get("stage") or event_type
            )
            return boundary, failure_class or None
    return None, None


def _project_root(project: dict[str, Any], database_path: Path) -> Path:
    root = Path(str(project["path"]))
    if root.is_absolute():
        return root
    conventional = database_path.parent / "projects" / root
    return conventional


def _evidence_for_run(
    run_id: str,
    project_root: Path,
    events: list[dict[str, Any]],
    checkpoint_count: int,
) -> dict[str, Any]:
    run_root = project_root / "runs" / run_id
    output_root = run_root / "outputs"
    receipt_root = run_root / "receipts"
    outputs = sorted(
        (item for item in output_root.rglob("*") if item.is_file()),
        key=lambda item: item.as_posix(),
    ) if output_root.is_dir() else []
    receipts = sorted(
        (item for item in receipt_root.rglob("*") if item.is_file()),
        key=lambda item: item.as_posix(),
    ) if receipt_root.is_dir() else []
    raw_outputs = [item for item in outputs if item.suffix.casefold() == ".md"]
    raw_manifest = [{
        "content_sha256": file_sha256(item),
        "bytes": item.stat().st_size,
    } for item in raw_outputs]
    event_types = [str(item.get("event_type") or "") for item in events]
    metadata_objects = [_json_object(item.get("metadata_json")) for item in events]
    return {
        "run_directory_present": run_root.is_dir(),
        "raw_output_count": len(raw_outputs),
        "raw_output_hash": (
            canonical_sha256(raw_manifest) if raw_manifest else None
        ),
        "raw_binding_status": (
            "ambiguous_multiple_candidates"
            if len(raw_outputs) > 1 else
            "unbound_single_candidate"
            if len(raw_outputs) == 1 else
            "missing"
        ),
        "receipt_count": len(receipts),
        "finish_reason_present": any(
            "finish_reason" in metadata for metadata in metadata_objects
        ),
        "route_trace_present": any(
            any(token in event_type for token in ("route", "fallback", "retry"))
            for event_type in event_types
        ),
        "typed_failure_present": any(
            metadata.get("failure_class") or metadata.get("failure_code")
            for metadata in metadata_objects
        ),
        "checkpoint_count": checkpoint_count,
    }


def _reclassification_reason(
    stored_key: str | None,
    stored_family: str | None,
    current_key: str,
    current_family: str,
) -> str:
    if not stored_key or not stored_family:
        return "legacy_terminal_reclassified_at_read"
    if stored_key != current_key or stored_family != current_family:
        return "incident_catalog_read_time_upgrade"
    return "unchanged"


def _replayability(
    incident_key: str,
    family: str,
    evidence: dict[str, Any],
    terminal_message: str,
) -> tuple[str, str]:
    # Legacy receipts do not bind finish reason and exact terminal attempt, so
    # R0 starts with no exact-replay claim. High-frequency structural families
    # have enough typed topology for incident-specific synthetic reconstruction.
    if incident_key in HIGH_FREQUENCY_INCIDENT_KEYS and (
        evidence["typed_failure_present"] or evidence["raw_output_count"]
    ):
        return REPLAYABILITY_SYNTHETIC, "incident_specific_structural_fixture"
    if family.startswith("unclassified.") and terminal_message == (
        "The workflow could not complete; validated progress was preserved "
        "for diagnosis and resume."
    ) and not evidence["typed_failure_present"]:
        return REPLAYABILITY_INSUFFICIENT, "generic_terminal_without_typed_chain"
    if evidence["typed_failure_present"] or not family.startswith("unclassified."):
        return REPLAYABILITY_STATIC, "current_code_path_only"
    return REPLAYABILITY_INSUFFICIENT, "insufficient_raw_or_typed_evidence"


def build_incident_manifest(database_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    projects = {
        str(row["id"]): dict(row)
        for row in connection.execute("SELECT * FROM projects")
    }
    primary_project_id = str(max(
        projects.values(), key=lambda item: str(item.get("created_at") or ""),
    )["id"])
    checkpoints = Counter(
        str(row["run_id"])
        for row in connection.execute(
            "SELECT run_id FROM workflow_node_checkpoints"
        )
    )
    events_by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in connection.execute("SELECT * FROM run_events ORDER BY id"):
        events_by_run[str(row["run_id"])].append(dict(row))
    rows = connection.execute(
        "SELECT e.*, r.project_id, r.workflow, r.current_stage "
        "FROM run_events e JOIN runs r ON r.id=e.run_id "
        "WHERE e.severity='error' AND e.event_type IN "
        "('failed', 'short_revision_failed') ORDER BY e.id"
    ).fetchall()
    result: list[dict[str, Any]] = []
    catalog_version = incident_catalog_version()
    for source_row in rows:
        row = dict(source_row)
        run_id = str(row["run_id"])
        stored = _json_object(row.get("metadata_json"))
        current = Database._incident_metadata(row)
        project = projects[str(row["project_id"])]
        run_events = events_by_run[run_id]
        evidence = _evidence_for_run(
            run_id, _project_root(project, database_path), run_events,
            checkpoints[run_id],
        )
        family = str(current["incident_family"])
        current_key = str(current["incident_key"])
        replayability, validation_method = _replayability(
            current_key, family, evidence, str(row.get("message") or ""),
        )
        first_boundary, first_class = _first_failure(run_events)
        build_status, build_hash = _runtime_build_status(run_events)
        stored_key = (
            str(stored.get("incident_key"))
            if stored.get("incident_key") else None
        )
        stored_family = (
            str(stored.get("incident_family"))
            if stored.get("incident_family") else None
        )
        incident_id = "r0-" + hashlib.sha256(
            f"{run_id}:{row['id']}".encode("utf-8"),
        ).hexdigest()[:20]
        result.append({
            "incident_id": incident_id,
            "project_scope_hash": hashlib.sha256(
                str(row["project_id"]).encode("utf-8"),
            ).hexdigest()[:16],
            "primary_live_scope": str(row["project_id"]) == primary_project_id,
            "stored_incident_key": stored_key,
            "stored_historical_family": stored_family,
            "current_incident_key": current_key,
            "current_reclassified_family": family,
            "incident_catalog_version": catalog_version,
            "reclassification_reason": _reclassification_reason(
                stored_key, stored_family,
                str(current["incident_key"]), family,
            ),
            "occurred_at_utc": row.get("created_at"),
            "event_time_epoch": event_time_epoch(row.get("created_at")),
            "runtime_build_status": build_status,
            "runtime_build_fingerprint_hash": build_hash,
            "workflow": str(row.get("workflow") or ""),
            "historical_stage": str(
                row.get("stage") or row.get("current_stage") or ""
            ),
            "first_failure_boundary": first_boundary,
            "first_failure_class": first_class,
            "terminal_boundary": "task_supervisor",
            "evidence_availability": evidence,
            "replayability": replayability,
            "raw_output_hash": evidence["raw_output_hash"],
            "expected_failure_class": str(
                stored.get("failure_class") or first_class or "unknown"
            ),
            "historical_terminal_outcome": "terminal_failed",
            "validation_method": validation_method,
            "synthetic_reconstruction": (
                replayability == REPLAYABILITY_SYNTHETIC
            ),
            "validation_status": "pending",
        })
    return {
        "schema": "HistoricalIncidentCorpusManifestV1",
        "source_database_hash": file_sha256(database_path),
        "incident_catalog_version": catalog_version,
        "fix_epochs_utc": dict(FIX_EPOCHS_UTC),
        "incident_count": len(result),
        "incidents": result,
    }


def manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    incidents = list(manifest["incidents"])
    replayability = Counter(item["replayability"] for item in incidents)
    epochs = Counter(item["event_time_epoch"] for item in incidents)
    families = Counter(
        item["current_reclassified_family"] for item in incidents
    )
    return {
        "incident_count": len(incidents),
        "stable_key_count": len({
            item["current_incident_key"] for item in incidents
        }),
        "family_count": len(families),
        "replayability": dict(sorted(replayability.items())),
        "epochs": dict(sorted(epochs.items())),
        "high_frequency_count": sum(
            1 for item in incidents
            if item["current_incident_key"] in HIGH_FREQUENCY_INCIDENT_KEYS
        ),
        "unclassified_count": sum(
            count for family, count in families.items()
            if family.startswith("unclassified.")
        ),
    }


def post_fix_exposure(database_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    results: dict[str, Any] = {}
    for label, boundary in (
        ("post_b49d87bd", FIX_EPOCHS_UTC["v3_declared_complete"]),
        ("post_d22a28f", FIX_EPOCHS_UTC["recovery_hardened"]),
    ):
        runs = [dict(row) for row in connection.execute(
            "SELECT * FROM runs WHERE workflow IN "
            "('short-story', 'short-revision') AND created_at>=?",
            (boundary,),
        )]
        run_ids = [str(row["id"]) for row in runs]
        events: list[dict[str, Any]] = []
        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            events = [dict(row) for row in connection.execute(
                f"SELECT * FROM run_events WHERE run_id IN ({placeholders}) "
                "ORDER BY id", run_ids,
            )]
        metadata = [_json_object(item.get("metadata_json")) for item in events]
        route_attempts = [
            item for item, meta in zip(events, metadata)
            if item["event_type"] == "protocol_receipt_route_failed"
            and int(meta.get("attempt_index") or 0) > 1
        ]
        fallback_attempts = [
            item for item, meta in zip(events, metadata)
            if meta.get("route") == "configured_fallback"
            or item["event_type"] in {
                "model_fallback", "protocol_receipt_model_fallback",
            }
        ]
        local_normalize_successes = sum(
            item["event_type"] == "contract_adapter_applied"
            for item in events
        )
        results[label] = {
            "boundary_utc": boundary,
            "short_workflow_started": len(runs),
            "short_workflow_completed": sum(
                row["status"] == "completed" for row in runs
            ),
            "model_stage_attempts": sum(
                item["event_type"] == "stage_started" for item in events
            ),
            "local_normalize_attempts": local_normalize_successes,
            "local_normalize_successes": local_normalize_successes,
            "protocol_retry_attempts": len(route_attempts),
            "protocol_retry_successes": sum(
                "protocol_recovered" in str(item["event_type"])
                for item in events
            ),
            "route_fallback_attempts": len(fallback_attempts),
            "route_fallback_successes": sum(
                item["event_type"] in {
                    "planning_packet_protocol_recovered",
                    "stage_completed",
                } and _json_object(item.get("metadata_json")).get(
                    "fallback_used"
                ) is True
                for item in events
            ),
            "controlled_waiting_resume": sum(
                row["status"] in {
                    "waiting_provider", "waiting_user", "recovering_protocol",
                    "recovering_semantic",
                } for row in runs
            ),
            "terminal_failures": sum(
                row["status"] == "failed" for row in runs
            ),
            "coverage_gaps": [
                "legacy conversion attempts are not emitted when no adapter audit exists",
                "fallback success is unknown unless the legacy receipt binds fallback_used",
            ],
            "production_exposure_sufficient": (
                len(runs) >= 10
                and sum(row["status"] == "completed" for row in runs) >= 3
            ),
        }
    return {
        "schema": "R0PostFixExposureV1",
        "epochs": results,
    }
