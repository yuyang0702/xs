"""Read-only legacy checkpoint migration for the Short reliability foundation.

The source database is opened read-only.  Only a separate destination root is
written.  Historical workflow attempts are inventory facts; they are never
treated as Provider HTTP and never become PhysicalRequestLedger records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from novel_flywheel.reliability_spine import (
    CanonicalDispatchCoordinator,
    DurableNodeStateStore,
    _sha,
)


RUN_ID = "06741882a6114b86a91730076d9626b3"
PROJECT_ID = "5592bb2d2a2a"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _source_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _snapshot(connection: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    run_row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if run_row is None:
        raise ValueError("run_not_found")
    run = dict(run_row)
    checkpoints = [
        dict(row) for row in connection.execute(
            "SELECT * FROM workflow_node_checkpoints WHERE run_id=? "
            "ORDER BY node_key,input_sha256,updated_at", (run_id,)
        ).fetchall()
    ] if _table_exists(connection, "workflow_node_checkpoints") else []
    attempts = [
        dict(row) for row in connection.execute(
            "SELECT attempt,state,action,failure_class,failure_sha256,"
            "authority_sha256,checkpoint_sha256,metadata_json,created_at "
            "FROM workflow_attempts WHERE run_id=? ORDER BY attempt", (run_id,)
        ).fetchall()
    ] if _table_exists(connection, "workflow_attempts") else []
    events = [
        dict(row) for row in connection.execute(
            "SELECT id,severity,event_type,stage,message,metadata_json,created_at "
            "FROM run_events WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
    ] if _table_exists(connection, "run_events") else []
    # Keep the migration inventory safe and bounded.  Payloads are retained as
    # hashes/keys only; the production prose and hidden model content remain in
    # their existing protected stores.
    safe_checkpoints = []
    for row in checkpoints:
        payload = {}
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {"_invalid": True}
        safe_checkpoints.append({
            "node_key": str(row.get("node_key") or ""),
            "input_sha256": str(row.get("input_sha256") or ""),
            "authority_sha256": str(row.get("authority_sha256") or ""),
            "output_sha256": str(row.get("output_sha256") or ""),
            "status": str(row.get("status") or ""),
            "validation_stage": str(row.get("validation_stage") or ""),
            "attempt": int(row.get("attempt") or 0),
            "route_fingerprint": str(row.get("route_fingerprint") or ""),
            "next_node": str(row.get("next_node") or ""),
            "payload_keys": sorted(str(key) for key in payload),
            "payload_sha256": _sha(payload),
        })
    safe_attempts = []
    unknown_attempts = 0
    confirmed_physical = 0
    for row in attempts:
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        physical = metadata.get("physical_request_id") if isinstance(metadata, dict) else None
        provider_state = metadata.get("provider_state") if isinstance(metadata, dict) else None
        is_confirmed = bool(physical and provider_state in {"DISPATCHING", "RESPONSE_RECEIVED", "TRANSPORT_UNKNOWN"})
        confirmed_physical += int(is_confirmed)
        unknown_attempts += int(not is_confirmed)
        safe_attempts.append({
            "attempt": int(row.get("attempt") or 0),
            "state": str(row.get("state") or ""),
            "action": str(row.get("action") or ""),
            "failure_class": row.get("failure_class"),
            "failure_sha256": row.get("failure_sha256"),
            "authority_sha256": row.get("authority_sha256"),
            "checkpoint_sha256": row.get("checkpoint_sha256"),
            "physical_request_id_known": bool(physical),
            "provider_state_known": bool(provider_state),
            "confirmed_physical_fact": is_confirmed,
        })
    # Existing canonical prepared work must be re-materialized against the
    # current user-saved route after a configuration change.  This map is
    # derived from the persisted binding/provider/model rows; legacy
    # checkpoint rows remain historical facts and are imported unchanged.
    current_route_fingerprints: dict[str, str] = {}
    if _table_exists(connection, "role_bindings") and _table_exists(connection, "providers") and _table_exists(connection, "models"):
        for role in ("review", "reader_review"):
            binding = connection.execute(
                "SELECT primary_provider_id,primary_model_id FROM role_bindings WHERE role=?",
                (role,),
            ).fetchone()
            if binding is None:
                continue
            provider = connection.execute(
                "SELECT protocol,base_url,auth_type,extra_headers_json FROM providers WHERE id=?",
                (binding[0],),
            ).fetchone()
            model = connection.execute(
                "SELECT model_name FROM models WHERE id=?",
                (binding[1],),
            ).fetchone()
            if provider is None or model is None:
                continue
            try:
                extra_headers = json.loads(provider[3] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                extra_headers = {}
            provider_route = {
                "protocol": provider[0],
                "base_url": str(provider[1] or "").rstrip("/"),
                "auth_type": provider[2],
                "extra_headers": extra_headers,
            }
            current_route_fingerprints[role] = hashlib.sha256(_json({
                "provider_route": provider_route,
                "model_name": model[0],
            }).encode("utf-8")).hexdigest()
    return {
        "schema": "LegacyShortCheckpointSnapshotV1",
        "project_id": str(run.get("project_id") or ""),
        "run_id": run_id,
        "workflow": str(run.get("workflow") or ""),
        "run_status": str(run.get("status") or ""),
        "current_stage": run.get("current_stage"),
        "run_error": run.get("error"),
        "checkpoints": safe_checkpoints,
        "attempts": safe_attempts,
        "event_count": len(events),
        "current_route_fingerprints": current_route_fingerprints,
        "workflow_attempt_count": len(attempts),
        "confirmed_physical_facts": confirmed_physical,
        "unknown_attempt_count": unknown_attempts,
    }


def _migrate(snapshot: dict[str, Any], destination: Path) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    spine = CanonicalDispatchCoordinator(destination, worker_fencing_id="legacy-migration-worker")
    migration_hash = _sha(snapshot)
    manifest_path = spine.root / "legacy-checkpoint-migration.json"
    previous: dict[str, Any] | None = None
    if manifest_path.exists():
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                previous = value
        except (OSError, UnicodeError, json.JSONDecodeError):
            previous = None

    imported_nodes = 0
    unchanged_nodes = 0
    for item in snapshot["checkpoints"]:
        node_key = str(item["node_key"])
        input_sha = str(item["input_sha256"])
        # Keep the filesystem key bounded; the full legacy node_key remains in
        # the inventory and is therefore still auditable.
        node_id = f"legacy:{snapshot['run_id']}:{_sha({'node_key': node_key, 'input_sha256': input_sha})[:40]}"
        candidate_sha = str(item["output_sha256"] or item["input_sha256"] or _sha(node_id))
        if len(candidate_sha) != 64:
            candidate_sha = _sha(candidate_sha)
        contract_sha = str(item["authority_sha256"] or _sha({"node_key": node_key}))
        if len(contract_sha) != 64:
            contract_sha = _sha(contract_sha)
        node_kwargs = dict(
            node_id=node_id,
            episode_id=_sha({"run_id": snapshot["run_id"], "node_id": node_id}),
            candidate_sha256=candidate_sha, contract_sha256=contract_sha,
            release_build_id=spine.release.build_id,
            cutover_version=spine.cutover.snapshot.version,
            route_fingerprint=str(item["route_fingerprint"] or ""),
        )
        try:
            node = spine.nodes.prepare(**node_kwargs)
        except Exception as exc:
            # Release cutover deliberately makes old prepared work stale.
            # Migration is the only bounded operation allowed to archive that
            # identity and rematerialize the same logical node.
            if getattr(exc, "code", None) != "stale_durable_node_identity":
                raise
            node = spine.nodes.rebind_stale_for_migration(**node_kwargs)
        target_state = (
            "RECEIPT_VALIDATED" if item["status"] == "validated" else
            "RESPONSE_CAPTURED" if item["status"] == "generated_complete" else
            "BLOCKED_RECOVERABLE"
        )
        if node.state == target_state:
            unchanged_nodes += 1
        elif node.state == "REVIEW_PREPARED":
            spine.nodes.transition(node_id, expected_state=node.state, state=target_state)
            imported_nodes += 1
        else:
            # A second run must never regress an already migrated node.
            unchanged_nodes += 1

    # Canonical nodes created by a real run (for example ``review`` and the
    # run-level failed alias) are not legacy checkpoint rows, but they still
    # carry the release identity that created them.  During a cutover they
    # must be archived and re-materialized through the same bounded migration
    # operation before dispatch can resume.  Preserve candidate, contract,
    # route and state exactly; only the release identity is advanced.
    rebound_existing_nodes = 0
    for path in sorted(spine.nodes.root.glob("*.json")):
        if ".stale." in path.name or path.name.endswith(".tmp"):
            continue
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        node_id = str(current.get("node_id") or "")
        if not node_id or node_id.startswith("legacy:"):
            continue
        if snapshot["run_id"] not in node_id and node_id != "review":
            continue
        if str(current.get("release_build_id") or "") == spine.release.build_id:
            continue
        # A canonical review node prepared under a prior binding must be
        # re-prepared with the current primary route.  Other canonical nodes
        # keep their recorded route identity until their own workflow node is
        # explicitly migrated.
        desired_route = str(current.get("route_fingerprint") or "")
        if node_id == "review":
            desired_route = str(
                (snapshot.get("current_route_fingerprints") or {}).get(
                    "review"
                ) or desired_route
            )
        state = spine.nodes.rebind_stale_for_migration(
            node_id=node_id,
            episode_id=str(current.get("episode_id") or ""),
            candidate_sha256=str(current.get("candidate_sha256") or ""),
            contract_sha256=str(current.get("contract_sha256") or ""),
            release_build_id=spine.release.build_id,
            cutover_version=spine.cutover.snapshot.version,
            route_fingerprint=desired_route,
            config_version=str(current.get("config_version") or ""),
        )
        if state.release_build_id == spine.release.build_id:
            rebound_existing_nodes += 1

    result = {
        "schema": "LegacyCheckpointMigrationReceiptV1",
        "project_id": snapshot["project_id"], "run_id": snapshot["run_id"],
        "source_snapshot_sha256": migration_hash,
        "migration_build_id": spine.release.build_id,
        "migration_policy_version": "legacy-checkpoint-to-durable-node-v1",
        "provider_http_performed": False,
        "workflow_attempt_count": snapshot["workflow_attempt_count"],
        "confirmed_physical_facts": snapshot["confirmed_physical_facts"],
        "unknown_attempt_count": snapshot["unknown_attempt_count"],
        "imported_physical_request_count": 0,
        "durable_node_count": len(snapshot["checkpoints"]),
        "nodes_changed": imported_nodes,
        "nodes_unchanged": unchanged_nodes,
        "existing_canonical_nodes_rebound": rebound_existing_nodes,
        "accepted_history_preserved": True,
        "candidate_history_preserved": True,
        "unknown_history_preserved": True,
        "idempotent_replay": bool(previous and previous.get("source_snapshot_sha256") == migration_hash and imported_nodes == 0),
        "business_changes": imported_nodes + rebound_existing_nodes,
    }
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(_json(result) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(manifest_path)
    (spine.root / "legacy-checkpoint-inventory.json").write_text(
        _json(snapshot) + "\n", encoding="utf-8", newline="\n"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--destination-root", type=Path, required=True)
    parser.add_argument("--run-id", default=RUN_ID)
    args = parser.parse_args()
    with _source_connection(args.source_db) as connection:
        snapshot = _snapshot(connection, args.run_id)
    if snapshot["project_id"] != PROJECT_ID:
        raise SystemExit("unexpected_project_id")
    result = _migrate(snapshot, args.destination_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
