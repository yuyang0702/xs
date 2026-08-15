"""Read-only Canary observation of existing checkpoint/artifact lineage."""

from __future__ import annotations

import json
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import domain_sha256


def observe_last_legal_bindings(
    db: Any, *, run_id: str, executor_binding: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Never creates or promotes state; unknown epoch linkage stays unverifiable."""

    executor = dict(executor_binding or {})
    epoch = executor.get("execution_epoch")
    runtime_hash = executor.get("runtime_execution_fingerprint")
    with db.connect() as connection:
        row = connection.execute(
            "SELECT * FROM workflow_node_checkpoints WHERE run_id=? "
            "AND status IN ('validated','generated_complete') "
            "AND validation_stage IN ('local_semantics','whole_story','promoted') "
            "ORDER BY updated_at DESC, attempt DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    if row is None:
        return {
            "current_executor_epoch": epoch,
            "checkpoint": {"kind": "checkpoint", "binding_status": "none_available"},
            "last_legal_artifact": {"kind": "artifact", "binding_status": "none_available"},
            "last_legal_authority_boundary": None,
        }
    record = dict(row)
    try:
        payload = json.loads(record.pop("payload_json") or "{}")
    except ValueError:
        payload = {}
    checkpoint_identity = domain_sha256(
        "novel-flywheel-canary-checkpoint-reference-v1", {
            key: record.get(key) for key in (
                "run_id", "node_key", "authority_sha256", "input_sha256",
                "output_sha256", "status", "checkpoint_version",
                "validation_stage", "attempt", "route_fingerprint", "next_node",
            )
        },
    )
    payload_epoch = payload.get("execution_epoch")
    payload_runtime = payload.get("runtime_execution_fingerprint")
    exact = bool(
        epoch and runtime_hash and payload_epoch == epoch
        and payload_runtime == runtime_hash
    )
    binding_status = "exact" if exact else "unverifiable"
    authority = record.get("authority_sha256")
    checkpoint = {
        "kind": "checkpoint", "reference": checkpoint_identity,
        "identity_sha256": checkpoint_identity,
        "revision": record.get("attempt"), "execution_epoch": payload_epoch,
        "authority_boundary": authority,
        "binding_receipt_sha256": (
            checkpoint_identity if exact else None
        ),
        "binding_status": binding_status,
    }
    artifact = {
        "kind": str(record.get("node_key") or "workflow_artifact"),
        "reference": record.get("output_sha256"),
        "identity_sha256": record.get("output_sha256"),
        "revision": record.get("attempt"), "execution_epoch": payload_epoch,
        "authority_boundary": authority,
        "binding_receipt_sha256": checkpoint_identity if exact else None,
        "binding_status": binding_status,
    }
    return {
        "current_executor_epoch": epoch,
        "checkpoint": checkpoint,
        "last_legal_artifact": artifact,
        "last_legal_authority_boundary": authority,
    }
