import json
from pathlib import Path
import socket

import pytest
import tools.canary.isolation as isolation_module

from tools.canary.approval_store import ApprovalConsumptionStore, CanaryApprovalReplay
from tools.canary.isolation import (
    CanaryIsolationError,
    SENTINEL_NAME,
    create_canary_root,
    validate_canary_root,
)
from tools.canary.network_sentinel import CanaryNetworkBlocked, FailClosedNetworkSentinel
from tools.canary.outcomes import CanaryOutcome, blocked_outcome, infrastructure_outcome

from .test_contracts import approval_payload, h, plan_payload
from tools.canary.contracts import (
    build_canary_experiment_plan_v1,
    build_canary_plan_approval_v1,
)


def test_root_identity_sentinel_and_live_separation(tmp_path: Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    canary = tmp_path / "canary"
    plan_sha = h("plan")
    result = create_canary_root(
        canary, stable_root_identity=h("root"), plan_sha256=plan_sha,
        run_namespace="c0a-v1", live_roots=[live],
    )
    assert result["validation_status"] == "exact"
    assert validate_canary_root(
        canary, stable_root_identity=h("root"), plan_sha256=plan_sha,
        run_namespace="c0a-v1", live_roots=[live],
    )["sentinel_sha256"] == result["sentinel_sha256"]

    sentinel = canary / SENTINEL_NAME
    payload = json.loads(sentinel.read_text(encoding="utf-8"))
    payload["run_namespace"] = "tampered"
    sentinel.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CanaryIsolationError, match="canary_sentinel_mismatch"):
        validate_canary_root(
            canary, stable_root_identity=h("root"), plan_sha256=plan_sha,
            run_namespace="c0a-v1", live_roots=[live],
        )


def test_canary_root_cannot_overlap_live_root(tmp_path: Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    with pytest.raises(CanaryIsolationError, match="canary_live_root_overlap"):
        create_canary_root(
            live / "canary", stable_root_identity=h("root"),
            plan_sha256=h("plan"), run_namespace="c0a-v1",
            live_roots=[live],
        )
    assert not (live / "canary").exists()


def test_reparse_or_symlink_subdirectory_is_rejected(tmp_path: Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    canary = tmp_path / "canary"
    create_canary_root(
        canary, stable_root_identity=h("root"), plan_sha256=h("plan"),
        run_namespace="c0a-v1", live_roots=[live],
    )
    target = tmp_path / "outside-logs"
    target.mkdir()
    logs = canary / "logs"
    logs.rmdir()
    try:
        logs.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink creation is unavailable")
    with pytest.raises(CanaryIsolationError, match="canary_subdirectory_invalid"):
        validate_canary_root(
            canary, stable_root_identity=h("root"), plan_sha256=h("plan"),
            run_namespace="c0a-v1", live_roots=[live],
        )


def test_windows_reparse_attribute_is_fail_closed(tmp_path: Path, monkeypatch) -> None:
    live = tmp_path / "live"
    live.mkdir()
    canary = tmp_path / "canary"
    create_canary_root(
        canary, stable_root_identity=h("root"), plan_sha256=h("plan"),
        run_namespace="c0a-v1", live_roots=[live],
    )
    original = isolation_module._is_reparse_point
    monkeypatch.setattr(
        isolation_module, "_is_reparse_point",
        lambda path: path.name == "logs" or original(path),
    )
    with pytest.raises(CanaryIsolationError, match="canary_subdirectory_invalid"):
        validate_canary_root(
            canary, stable_root_identity=h("root"), plan_sha256=h("plan"),
            run_namespace="c0a-v1", live_roots=[live],
        )


def test_approval_store_is_single_use_and_consumption_is_hash_bound(tmp_path: Path) -> None:
    plan = build_canary_experiment_plan_v1(plan_payload())
    approval = build_canary_plan_approval_v1(approval_payload(plan))
    store = ApprovalConsumptionStore(tmp_path)
    reservation = store.reserve(approval)
    assert reservation["payload"]["approval_sha256"] == approval["approval_sha256"]
    with pytest.raises(CanaryApprovalReplay, match="approval_already_reserved"):
        store.reserve(approval)
    consumed = store.consume(approval, h("evidence"))
    assert consumed["payload"]["consumed_evidence_sha256"] == h("evidence")
    with pytest.raises(CanaryApprovalReplay, match="approval_already_consumed"):
        store.consume(approval, h("evidence-2"))


def test_network_sentinel_blocks_dns_and_restores_entry_points() -> None:
    original = socket.getaddrinfo
    sentinel = FailClosedNetworkSentinel()
    with sentinel:
        with pytest.raises(CanaryNetworkBlocked):
            socket.getaddrinfo("example.invalid", 443)
        with pytest.raises(CanaryNetworkBlocked):
            socket.create_connection(("127.0.0.1", 9))
        handle = socket.socket()
        try:
            with pytest.raises(CanaryNetworkBlocked):
                handle.connect(("127.0.0.1", 9))
        finally:
            handle.close()
    assert sentinel.network_call_count == 3
    assert socket.getaddrinfo is original


def test_canary_outcomes_do_not_pollute_workflow_or_production_incident_rates() -> None:
    blocked = blocked_outcome("build_fingerprint_unapproved")
    infra = infrastructure_outcome("launcher_crash")
    assert blocked.outcome == CanaryOutcome.CANARY_BLOCKED_PRE_PROVIDER
    assert infra.outcome == CanaryOutcome.CANARY_INFRASTRUCTURE_FAILURE
    assert not blocked.workflow_terminal_counted
    assert not blocked.production_incident_counted
    assert not infra.workflow_terminal_counted
