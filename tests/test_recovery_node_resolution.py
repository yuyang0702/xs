import json

import pytest

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.reliability_spine import CanonicalDispatchCoordinator
from novel_flywheel.secrets import MemorySecretStore


def prepared_node(spine, node_id="receipt-node", candidate="a" * 64):
    return spine.nodes.prepare(
        node_id=node_id, episode_id="episode", candidate_sha256=candidate,
        contract_sha256="b" * 64, release_build_id=spine.release.build_id,
        cutover_version=spine.cutover.snapshot.version, route_fingerprint="c" * 64,
    )


def ledger_row(node, run_id="run", **changes):
    return {
        "schema": "PhysicalRequestLedgerV1", "run_id": run_id,
        "logical_node_id": node.node_id, "candidate_sha256": node.candidate_sha256,
        "route_fingerprint": node.route_fingerprint, "state": "RESPONSE_RECEIVED",
        **changes,
    }


def write_rows(spine, *rows):
    spine.ledger_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
    )


def test_ledger_node_resolution_uses_run_order_without_directory_guessing(tmp_path):
    spine = CanonicalDispatchCoordinator(tmp_path)
    old = prepared_node(spine, "old-node")
    last = prepared_node(spine, "latest-node")
    unrelated = prepared_node(spine, "other-node")
    write_rows(spine, ledger_row(old), ledger_row(last), ledger_row(unrelated, "other-run"))
    assert spine.recovery_node_for_run("run") == last
    assert spine.recovery_node_for_run("absent") is None


@pytest.mark.parametrize("damage", ["missing", "candidate", "route", "malformed"])
def test_ledger_resolution_never_falls_back_past_invalid_latest_identity(tmp_path, damage):
    spine = CanonicalDispatchCoordinator(tmp_path)
    old = prepared_node(spine, "old")
    latest = prepared_node(spine, "latest")
    row = ledger_row(latest)
    if damage == "missing":
        row["logical_node_id"] = "not-present"
    elif damage == "candidate":
        row["candidate_sha256"] = "d" * 64
    elif damage == "route":
        row["route_fingerprint"] = "d" * 64
    write_rows(spine, ledger_row(old), row)
    if damage == "malformed":
        with spine.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write('{"incomplete":')
    assert spine.recovery_node_for_run("run") is None


def test_terminal_attempt_without_node_id_reaches_existing_local_boundary(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("book", "Book", "short", tmp_path / "book")
    db.create_run("run", "book", "short-story", status="failed")
    db.save_workflow_supervision(
        run_id="run", state="irrecoverable", resume_payload={},
        retry_budgets={}, used_budgets={}, last_failure_class="syntax_protocol",
        last_failure_sha256="f" * 64, last_error_summary="blocked",
    )
    db.update_run("run", "failed", "failed")
    db.record_workflow_attempt(
        run_id="run", state="irrecoverable", action="automatic_recovery_exhausted",
        failure_class="syntax_protocol", metadata={"failure_graph": {"boundary": "draft_receipt_validation"}},
    )
    app = create_app(db, MemorySecretStore(), skill_roots=[], workspace_root=tmp_path)
    spine = app.state.reliability_spine
    node = prepared_node(spine)
    spine.nodes.transition(node.node_id, expected_state="REVIEW_PREPARED", state="RESPONSE_CAPTURED")
    write_rows(spine, ledger_row(node))
    before = len(db.list_workflow_attempts("run"))
    first = app.state.run_tasks.reentry_evaluator("run")
    assert first["action"] == "LOCAL_REPLAY_VALIDATION"
    assert first["provider_intent_created"] is False
    second = app.state.run_tasks.reentry_evaluator("run")
    assert second["action"] == "NO_ACTION"
    assert len(db.list_workflow_attempts("run")) == before


def test_unknown_node_keeps_reconciliation_authority(tmp_path):
    spine = CanonicalDispatchCoordinator(tmp_path)
    node = prepared_node(spine)
    write_rows(spine, ledger_row(node, state="QUARANTINED_UNRESOLVED"))
    assert spine.recovery_node_for_run("run") == node
    decision = spine.evaluate_reentry(
        {"run_id": "run", "logical_node_id": node.node_id},
        node_state="REVIEW_SENT_OR_UNKNOWN", failure_class="transport_unknown",
    )
    assert decision["action"] == "RECONCILE_UNKNOWN_DISPATCH"
    assert decision["physical_dispatch_allowed"] is False
