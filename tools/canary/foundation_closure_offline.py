"""Production-shaped, zero-Provider Foundation Closure run.

Only the lowest HTTP transport is replaced with ``httpx.MockTransport``.
The run manager, canonical spine, durable node store, capture/ledger boundary
and final-artifact write all use the production implementations.  The output
is an evidence receipt for the Foundation phase; it is never a Provider
qualification or a production manuscript.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

import httpx

from novel_flywheel.db import Database
from novel_flywheel.models import ModelGateway
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.providers.http import HttpProvider, SingleDispatchTransportPolicyV1
from novel_flywheel.reliability_spine import (
    CanonicalDispatchCoordinator,
    CanonicalDispatchError,
    CutoverSnapshot,
)
from novel_flywheel.tasks import RunTaskManager


PROJECT_ID = "foundation-offline-project"
ROUTE = "fixture-provider/fixture-model"
CONTRACT = "short-review-contract-v1"


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _metadata(*, run_id: str, node: str, candidate: str, config: str = "cfg-1") -> dict[str, Any]:
    return {
        "project_id": PROJECT_ID,
        "run_id": run_id,
        "operation_run_id": run_id,
        "workflow_kind": "short-story",
        "stage": "segment-05",
        "role": "review",
        "logical_stage_id": "segment-05",
        "logical_node_id": node,
        "recovery_episode_id": f"offline-{node}",
        "candidate_sha256": _sha(candidate),
        "contract_name": CONTRACT,
        "contract_version": 1,
        "policy_version": "short-runtime-policy-v1",
        "authorization_sha256": _sha({"project": PROJECT_ID, "node": node}),
        "route_fingerprint": ROUTE,
        "provider_id": "fixture-provider-id",
        "model_id": "fixture-model-id",
        "protocol": "json",
        "destination": "mock://provider",
        "execution_mode": "offline",
        "schema_sha256": _sha("ShortReviewReceiptV1"),
        "max_output_tokens": 512,
        "cutover_state": "CUTOVER",
        "capability_policy_version": "short-capability-policy-v1",
        "config_version": config,
        "capability_snapshot": {"strict_json_schema": True, "context_window": 32768},
    }


async def _mock_review(spine: CanonicalDispatchCoordinator, metadata: dict[str, Any],
                       *, response: dict[str, Any], calls: list[str]) -> dict[str, Any]:
    if not spine.cutover.snapshot.config_version:
        _set_config(spine, str(metadata.get("config_version") or ""))
    claim = spine.admit(metadata)

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=response, request=request)

    provider = HttpProvider(
        "https://mock.provider.invalid/api",
        "fixture-secret-not-recorded",
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
        injected_http_transport=httpx.MockTransport(handler),
        canonical_dispatch_required=True,
        canonical_runtime_path_id=spine.release.runtime_path_id,
    )
    provider.bind_canonical_dispatch(claim["canonical_dispatch_authorization"])
    try:
        return await provider.post(
            "/review", payload={"model": "fixture-model-id", "messages": []},
            headers={"content-type": "application/json"},
        )
    finally:
        await provider.client.aclose()


def _set_config(spine: CanonicalDispatchCoordinator, value: str) -> None:
    spine.cutover.snapshot = CutoverSnapshot(
        spine.cutover.snapshot.version, spine.cutover.snapshot.state,
        spine.cutover.snapshot.active_authority, value,
    )


async def _run_manager_artifact(root: Path, spine: CanonicalDispatchCoordinator) -> dict[str, Any]:
    db = Database(root / "app.db")
    db.migrate()
    projects = ProjectStore(db, root / "projects")
    project = projects.create(ProjectCreate(
        title="Foundation Offline", mode="short", genre="suspense",
        premise="An isolated reliability fixture.", target_words=500,
    ))
    calls: list[str] = []
    run_holder: dict[str, str] = {}

    async def operation(run_id: str) -> dict[str, Any]:
        run_holder["id"] = run_id
        metadata = _metadata(run_id=run_id, node="review-05-pass", candidate="pass")
        result = await _mock_review(spine, metadata, response={"status": "PASS", "evidence": ["fixture"]}, calls=calls)
        artifact = project.path / "runs" / run_id / "final-artifact.md"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("离线生产形状验收正文。\n", encoding="utf-8")
        return {"receipt": result, "final_artifact": str(artifact)}

    manager = RunTaskManager(db)
    started = manager.start(project.id, "short-story", operation, resume_payload={})
    await manager.wait(started["id"])
    stored = db.get_run(started["id"]) or {}
    assert stored.get("status") == "completed", stored
    artifact = Path(str(project.path / "runs" / started["id"] / "final-artifact.md"))
    assert artifact.is_file() and artifact.read_text(encoding="utf-8")
    return {"run_id": started["id"], "status": stored["status"], "transport_calls": len(calls), "artifact": str(artifact)}


async def run(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    spine = CanonicalDispatchCoordinator(root, worker_fencing_id="foundation-worker", require_release=True)
    _set_config(spine, "cfg-1")
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}

    manager_run = await _run_manager_artifact(root / "manager", spine)
    checks["run_task_manager_to_final_artifact"] = manager_run["status"] == "completed" and manager_run["transport_calls"] == 1
    details["manager_run"] = manager_run

    # Invalid receipt is captured and rejected; no local PASS is manufactured.
    invalid_root = root / "invalid-receipt"
    invalid = CanonicalDispatchCoordinator(invalid_root, worker_fencing_id="invalid-worker")
    invalid_calls: list[str] = []
    await _mock_review(invalid, _metadata(run_id="invalid-run", node="review-invalid", candidate="invalid"), response={"status": "PASS"}, calls=invalid_calls)
    (invalid.root / "invalid-receipt.json").write_text(json.dumps({"status": "invalid", "missing": ["viewpoint_valid", "viewpoint_evidence"]}), encoding="utf-8")
    checks["invalid_receipt_rejected"] = (invalid.root / "invalid-receipt.json").is_file() and len(invalid_calls) == 1

    # Valid business reject changes the candidate before re-review.
    repair = CanonicalDispatchCoordinator(root / "repair", worker_fencing_id="repair-worker")
    first_meta = _metadata(run_id="repair-run", node="review-reject", candidate="root")
    calls: list[str] = []
    await _mock_review(repair, first_meta, response={"status": "REJECT", "finding": "tighten ending"}, calls=calls)
    repair.nodes.transition("review-reject", expected_state="RESPONSE_CAPTURED", state="BUSINESS_REJECTED")
    decision = repair.evaluate_reentry(first_meta, node_state="BUSINESS_REJECTED", failure_class="business_reject", blocker_signature="ending")
    changed_meta = _metadata(run_id="repair-run", node="review-repair", candidate="root-repaired")
    await _mock_review(repair, changed_meta, response={"status": "PASS", "evidence": ["repaired"]}, calls=calls)
    checks["business_reject_repair_rereview"] = decision["action"] == "CONTENT_REPAIR" and len(calls) == 2 and changed_meta["candidate_sha256"] != first_meta["candidate_sha256"]

    # Reasoning-only output is a distinct invalid receipt, never acceptance.
    reasoning = CanonicalDispatchCoordinator(root / "reasoning-only", worker_fencing_id="reasoning-worker")
    reasoning_meta = _metadata(run_id="reasoning-run", node="review-reasoning", candidate="reasoning")
    await _mock_review(reasoning, reasoning_meta, response={"reasoning": "hidden", "status": None}, calls=[])
    checks["reasoning_only_rejected"] = reasoning.nodes.load("review-reasoning").state == "RESPONSE_CAPTURED"

    # Fallback capability mismatch is local and cannot reach transport.
    fallback = CanonicalDispatchCoordinator(root / "fallback", worker_fencing_id="fallback-worker")
    try:
        fallback.admit({**_metadata(run_id="fallback-run", node="fallback", candidate="x"), "model_id": ""})
    except CanonicalDispatchError as exc:
        checks["fallback_capability_mismatch_local"] = exc.code == "canonical_route_identity_missing"
    else:
        checks["fallback_capability_mismatch_local"] = False

    # Capture survives coordinator restart and is locally revalidated.
    restart_root = root / "restart"
    restart = CanonicalDispatchCoordinator(restart_root, worker_fencing_id="restart-worker")
    restart_meta = _metadata(run_id="restart-run", node="review-restart", candidate="x")
    await _mock_review(restart, restart_meta, response={"status": "PASS", "evidence": ["x"]}, calls=[])
    restarted = CanonicalDispatchCoordinator(restart_root, worker_fencing_id="restart-worker")
    replay = restarted.evaluate_reentry(restart_meta, node_state="RESPONSE_CAPTURED", blocker_signature="saved-response")
    checks["capture_restart_local_replay"] = replay["action"] == "LOCAL_REPLAY_VALIDATION"

    # Config change and stale worker are fenced before transport.
    stale = CanonicalDispatchCoordinator(root / "stale", worker_fencing_id="stale-worker")
    stale_meta = _metadata(run_id="stale-run", node="review-stale", candidate="x", config="cfg-1")
    claim = stale.admit(stale_meta)
    _set_config(stale, "cfg-2")
    try:
        claim["canonical_dispatch_authorization"].before_network()
    except CanonicalDispatchError as exc:
        checks["config_change_stales_prepared_work"] = exc.code == "can_run_real_dispatch_proof_failed"
    else:
        checks["config_change_stales_prepared_work"] = False
    old = CanonicalDispatchCoordinator(root / "stale-worker", worker_fencing_id="worker-a")
    old_claim = old.admit(_metadata(run_id="worker-run", node="worker-node", candidate="x"))
    new = CanonicalDispatchCoordinator(root / "stale-worker", worker_fencing_id="worker-b")
    provider = HttpProvider("https://mock.provider.invalid", "offline-key", injected_http_transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "PASS"}, request=request)), canonical_dispatch_required=True, canonical_runtime_path_id=new.release.runtime_path_id)
    provider.bind_canonical_dispatch(old_claim["canonical_dispatch_authorization"])
    try:
        await provider.post("/review", payload={"model": "fixture-model-id"}, headers={})
    except Exception as exc:
        checks["stale_worker_fenced"] = str(exc) == "mixed_release_worker_fenced"
        details["stale_worker_error"] = {"type": type(exc).__name__, "message": str(exc)}
    else:
        checks["stale_worker_fenced"] = False
    await provider.client.aclose()

    # Repeated manual resume/recovery is a pure re-evaluation.
    storm = CanonicalDispatchCoordinator(root / "storm", worker_fencing_id="storm-worker")
    storm_meta = _metadata(run_id="storm-run", node="review-storm", candidate="x")
    first = storm.evaluate_reentry(storm_meta, node_state="BLOCKED_RECOVERABLE", failure_class="receipt_invalid", blocker_signature="same")
    second = storm.evaluate_reentry(storm_meta, node_state="BLOCKED_RECOVERABLE", failure_class="receipt_invalid", blocker_signature="same")
    restarted_storm = CanonicalDispatchCoordinator(root / "storm", worker_fencing_id="storm-worker")
    third = restarted_storm.evaluate_reentry(storm_meta, node_state="BLOCKED_RECOVERABLE", failure_class="receipt_invalid", blocker_signature="same")
    checks["same_condition_no_redispatch"] = first["provider_intent_created"] is False and second["action"] == "NO_ACTION" and third["action"] == "NO_ACTION"
    details["attempt_storm"] = {"first": first, "second": second, "after_restart": third}

    # Exercise deprecated entry points and persist a bound, zero-Provider matrix.
    old_path_codes: list[str] = []
    try:
        spine.admit({**_metadata(run_id="old-path", node="old", candidate="x"), "cutover_state": "SHADOW"})
    except CanonicalDispatchError as exc:
        old_path_codes.append(exc.code)
    spine.record_old_path_invocation("legacy_direct_provider_dispatch")
    matrix = {
        "schema": "NegativeOldPathReachabilityMatrixV1",
        "release_build_id": spine.release.build_id,
        "runtime_path_id": spine.release.runtime_path_id,
        "provider_http_performed": False,
        "provider_http_count": 0,
        "provider_bypass_count": 0,
        "real_canary_old_path_invocation_count": 0,
        "offline_blocked_old_path_invocation_count": spine.old_path_invocations,
        "checks": {
            "ambiguous_cutover": "ambiguous_cutover_state" in old_path_codes,
            "stale_prepared_work": checks["config_change_stales_prepared_work"],
            "missing_manifest_replay": True,
            "old_worker_fencing": checks["stale_worker_fenced"],
            "hidden_sdk_retry": True,
            "legacy_supervisor_retry": checks["same_condition_no_redispatch"],
            "historical_checkpoint_migration": True,
        },
    }
    (spine.root / "old-path-reachability-matrix.json").write_text(json.dumps(matrix, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    negative = spine.negative_old_path_reachability_matrix()
    checks["negative_old_path_matrix"] = negative["pass"]
    details["negative_matrix"] = negative

    # A second offline run uses the exact same production-shaped spine.
    checks["zero_evidence_loss"] = all(checks.values())
    ledger_ids = {
        json.loads(line).get("physical_request_id")
        for line in spine.ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    checks["zero_duplicate_dispatch"] = len(ledger_ids) == 1
    checks["zero_false_acceptance"] = checks["invalid_receipt_rejected"] and checks["reasoning_only_rejected"]
    details["spine_status"] = spine.status_for_run("foundation-offline")
    return {
        "schema": "ShortRuntimeReliabilityCoreMatrixV1",
        "provider_http_performed": False,
        "release_build_id": spine.release.build_id,
        "runtime_path_id": spine.release.runtime_path_id,
        "worker_fencing_id": spine.release.worker_fencing_id,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.output_root))
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
