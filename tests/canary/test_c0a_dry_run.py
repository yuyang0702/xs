from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

import pytest

from tools.canary.artifact_hash import tree_manifest
from tools.canary.dry_run import run_c0a_dry_run
from tools.canary.evidence import (
    CanaryEvidenceError,
    build_canary_evidence_package_v1,
)
from tools.canary.packet import prepare_c0a_packet


FIXTURE = Path(__file__).parents[1] / "fixtures" / "canary" / "short-normal-v1.json"


def _minimal_evidence() -> dict:
    return {
        "plan_sha256": "1" * 64,
        "approval_sha256": "2" * 64,
        "launcher_sha256": "3" * 64,
        "outcome": {"value": "WORKFLOW_COMPLETED"},
        "runtime_fingerprints": {},
        "origin_executor_binding": {},
        "preflight_receipts": [],
        "model_boundary_ledger": [],
        "budget_ledger": {},
        "counters": {},
        "live_parity": {},
        "canary_artifacts": {},
        "performance": {},
        "coverage_gaps": [],
        "raw_content_included": False,
    }


def test_evidence_is_hash_stable_and_rejects_raw_or_machine_specific_material() -> None:
    first = build_canary_evidence_package_v1(_minimal_evidence())
    second = build_canary_evidence_package_v1(dict(reversed(
        list(_minimal_evidence().items())
    )))
    assert first["evidence_sha256"] == second["evidence_sha256"]
    for mutation in (
        {"raw_prompt": "forbidden"},
        {"location": r"C:\\live\\project"},
    ):
        payload = _minimal_evidence()
        payload["canary_artifacts"] = mutation
        with pytest.raises(CanaryEvidenceError):
            build_canary_evidence_package_v1(payload)


def test_packet_preparation_binds_current_fake_execution_config(tmp_path: Path) -> None:
    plan_path = tmp_path / "packet" / "plan.json"
    approval_path = tmp_path / "packet" / "approval.json"
    plan, approval = prepare_c0a_packet(
        fixture_path=FIXTURE, plan_path=plan_path,
        approval_path=approval_path, cohort_id="c0a-packet-fixture-001",
    )
    assert plan["canary_mode"] == "c0a_fake_dry_run"
    assert plan["feature_flag_snapshot"]["NOVEL_SHORT_CANONICAL_V2"] is False
    assert plan["approved_dependency_manifest"]["third_party"] == []
    assert approval["approved_plan_sha256"] == plan["plan_sha256"]
    assert json.loads(plan_path.read_text(encoding="utf-8")) == plan


@pytest.mark.skipif(os.name != "nt", reason="Windows path budget is platform-specific")
@pytest.mark.asyncio
async def test_dry_run_blocks_overlong_windows_execution_root_before_creation(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="canary_root_path_budget_exceeded"):
        await run_c0a_dry_run(
            plan_path=tmp_path / "absent-plan.json",
            approval_path=tmp_path / "absent-approval.json",
            approved_plan_sha256="0" * 64,
            workload_fixture_path=FIXTURE,
            canary_root=tmp_path / ("x" * 120),
            approval_ledger_root=tmp_path,
            live_database_path=tmp_path / "live.db",
            live_project_root=tmp_path,
        )


@pytest.mark.asyncio
async def test_official_short_api_fake_dry_run_is_isolated_and_exact(tmp_path: Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    live_projects = live / "projects"
    live_projects.mkdir()
    live_incidents = live / "incidents"
    live_incidents.mkdir()
    (live_projects / "sentinel.txt").write_text("unchanged", encoding="utf-8")
    live_before = tree_manifest(live)
    packet = tmp_path / "packet"
    plan_path = packet / "plan.json"
    approval_path = packet / "approval.json"
    plan, _approval = prepare_c0a_packet(
        fixture_path=FIXTURE, plan_path=plan_path,
        approval_path=approval_path, cohort_id="c0a-full-short-fixture-001",
    )
    ledger = tmp_path / "approval-ledger"
    ledger.mkdir()
    with tempfile.TemporaryDirectory(prefix="c0a-short-") as isolated:
        result = await run_c0a_dry_run(
            plan_path=plan_path, approval_path=approval_path,
            approved_plan_sha256=plan["plan_sha256"],
            workload_fixture_path=FIXTURE,
            canary_root=Path(isolated) / "x",
            approval_ledger_root=ledger,
            live_database_path=live / "app.db",
            live_project_root=live_projects,
            live_incident_roots=[live_incidents],
        )
        evidence = result["evidence"]
        assert result["report_path"].is_file()
    assert evidence["outcome"]["value"] == "WORKFLOW_COMPLETED", (
        json.dumps(evidence["outcome"], sort_keys=True)
        + " boundaries="
        + ",".join(
            f"{item['ordinal']}:{item['role']}:{item['stage']}"
            for item in evidence["model_boundary_ledger"]
        )
    )
    assert evidence["canary_artifacts"]["official_api_status"] == 202
    assert evidence["runtime_fingerprints"]["per_boundary_status"] == "exact"
    assert evidence["origin_executor_binding"]["binding_status"] == "exact"
    assert evidence["preflight_receipts"]
    assert evidence["model_boundary_ledger"]
    assert len(evidence["preflight_receipts"]) == len(
        evidence["model_boundary_ledger"]
    ) + 1
    assert evidence["budget_ledger"]["reservation_count"] == len(
        evidence["model_boundary_ledger"]
    )
    assert evidence["counters"] == {
        "credential_lookup_count": 0,
        "provider_client_creation_count": 0,
        "network_call_count": 0,
        "fake_model_boundary_calls": len(evidence["model_boundary_ledger"]),
        "paid_model_call_count": 0,
    }
    assert evidence["live_parity"]["status"] == "exact"
    assert tree_manifest(live)["tree_sha256"] == live_before["tree_sha256"]
    assert list(ledger.glob("*.consumed.json"))
