from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from novel_flywheel.full_short_runtime_kernel import (
    DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1,
    DEFAULT_FAULT_INJECTION_REGISTRY_V1,
    DurableExecutionJournalV1,
)
from novel_flywheel.stage_capacity import (
    CAPACITY_BOUNDARY_ID_V1,
    CAPACITY_FAILURE_IDS_V1,
    DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1,
)


SCRIPT = (
    Path(__file__).parents[2]
    / "tools"
    / "quality"
    / "full_short_capacity_fault_campaign.py"
)
SPEC = importlib.util.spec_from_file_location(
    "full_short_capacity_fault_campaign",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
CAMPAIGN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CAMPAIGN
SPEC.loader.exec_module(CAMPAIGN)


MASTER_ENUMERATED_SCENARIO_IDS = (
    "exact_ready_review_over_cap",
    "protected_layers_alone_over_budget",
    "advisory_over_budget",
    "compactor_insufficient",
    "window_count_boundary",
    "oversized_review_window",
    "hierarchical_synthesis_over_budget",
    "output_reserve_conflict",
    "rendered_size_drift_after_plan",
    "context_limit_config_missing",
    "wrong_context_limit_metadata",
    "restart_after_capacity_plan",
    "restart_during_windowed_review",
    "failed_review_window",
    "duplicate_review_window_receipt",
    "missing_global_synthesis_receipt",
)


def test_campaign_is_mechanically_bound_to_all_active_capacity_registries() -> None:
    cases = CAMPAIGN.generate_capacity_fault_cases_v2()
    assert tuple(case.scenario_id for case in cases) == (
        MASTER_ENUMERATED_SCENARIO_IDS
    )
    assert len(cases) == 16
    assert CAMPAIGN.MASTER_DECLARED_SCENARIO_COUNT_V2 == 15
    assert {case.failure_id for case in cases} == CAPACITY_FAILURE_IDS_V1

    capacity_boundary = DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.boundary(
        CAPACITY_BOUNDARY_ID_V1
    )
    source_fault_keys = {
        case.case_key for case in DEFAULT_FAULT_INJECTION_REGISTRY_V1.cases
    }
    for case in cases:
        assert case.failure_id in capacity_boundary.allowed_typed_failures
        assert case.source_case_key in source_fault_keys
        assert case.source_boundary_registry_sha256 == (
            DEFAULT_FAILURE_BOUNDARY_REGISTRY_V1.identity_sha256
        )
        assert case.source_fault_registry_sha256 == (
            DEFAULT_FAULT_INJECTION_REGISTRY_V1.identity_sha256
        )
        assert case.source_capacity_policy_registry_sha256 == (
            DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
        )


def test_unregistered_scenario_failure_blocks_instead_of_fabricating_proof() -> None:
    unregistered = CAMPAIGN.CapacityFaultScenarioSpecV2(
        "unregistered_capacity_failure",
        "capacity.not_registered",
        "capacity.test",
    )
    with pytest.raises(
        ValueError,
        match="capacity_campaign_failure_not_in_capacity_registry",
    ):
        CAMPAIGN.generate_capacity_fault_cases_v2((unregistered,))


def test_unknown_durable_api_version_blocks_instead_of_claiming_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        CAMPAIGN.DurableCapacityFaultAdapterV2,
        "required_journal_schema",
        "DurableExecutionJournalV999",
    )
    with pytest.raises(
        RuntimeError,
        match="capacity_campaign_durable_journal_api_blocked",
    ):
        CAMPAIGN.DurableCapacityFaultAdapterV2.assert_supported()


@pytest.fixture(scope="module")
def campaign_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    return CAMPAIGN.run_capacity_fault_campaign_v2(
        tmp_path_factory.mktemp("capacity-fault-campaign")
    )


@pytest.mark.parametrize("scenario_id", MASTER_ENUMERATED_SCENARIO_IDS)
def test_every_master_case_proves_required_runtime_invariants(
    scenario_id: str,
    campaign_report: dict[str, object],
) -> None:
    result = next(
        item
        for item in campaign_report["results"]
        if item["scenario_id"] == scenario_id
    )
    assert result["classification"] == "KNOWN"
    assert result["typed_failure"] is True
    assert result["durable_receipt"] is True
    assert result["denied_admission_zero_dispatch"] is True
    assert result["dispatch_attempt_count"] == 0
    assert result["dispatch_token_receipt_count"] == 0
    assert result["no_authority_mutation"] is True
    assert result["authority_gate_receipt_count"] == 0
    assert result["authority_sha256_before"] == result["authority_sha256_after"]
    assert result["explicit_recovery_or_stop"] is True
    assert result["recovery_decision"] in {"SEMANTIC_SPLIT", "FAIL_CLOSED"}
    assert result["restart_policy_id"]
    assert result["deterministic_replay"] is True
    assert result["raw_content_persisted"] is False
    assert result["status"] == "PASS"


def test_campaign_reopens_real_durable_receipts_and_is_hash_deterministic(
    tmp_path: Path,
) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first = CAMPAIGN.run_capacity_fault_campaign_v2(first_dir)
    second = CAMPAIGN.run_capacity_fault_campaign_v2(second_dir)

    assert first == second
    assert first["report_sha256"] == second["report_sha256"]
    assert first["status"] == "PASS"
    for scenario_id in MASTER_ENUMERATED_SCENARIO_IDS:
        for suffix in ("first", "replay"):
            journal_path = first_dir / f"{scenario_id}.{suffix}.json"
            reopened = DurableExecutionJournalV1.open(journal_path)
            assert len(reopened.failure_receipts) == 1
            assert reopened.failure_receipts[0].failure_envelope is not None
            assert not reopened.dispatch_token_receipts


def test_report_is_offline_complete_and_exposes_master_count_discrepancy(
    campaign_report: dict[str, object],
) -> None:
    assert campaign_report["master_declared_scenario_count"] == 15
    assert campaign_report["master_enumerated_scenario_count"] == 16
    assert "enumerates 16" in campaign_report["scenario_count_discrepancy"]
    assert campaign_report["registered_capacity_failure_coverage"] == (
        "100_PERCENT"
    )
    assert campaign_report["scenario_coverage"] == "100_PERCENT"
    assert campaign_report["external_actions_disabled"] is True
    assert campaign_report["credential_lookup_count"] == 0
    assert campaign_report["provider_client_creation_count"] == 0
    assert campaign_report["network_call_count"] == 0
    assert campaign_report["model_call_count"] == 0
    assert campaign_report["paid_call_count"] == 0
    assert campaign_report["full_short_execution_count"] == 0


def test_cli_writes_only_hash_safe_campaign_report(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "journals"
    output = tmp_path / "report.json"
    assert CAMPAIGN.main(
        ["--artifact-dir", str(artifact_dir), "--output", str(output)]
    ) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert payload["status"] == "PASS"
    assert str(tmp_path) not in serialized
    assert "credential-value" not in serialized
    assert "provider-response" not in serialized
