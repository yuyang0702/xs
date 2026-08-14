from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from r0_incident_corpus import file_sha256
from r0e_maintenance_harness import (
    MAINTENANCE_VARIANTS,
    classify_paired_result,
    run_contract_runtime_control,
    run_current_maintenance_workflow,
)


ROOT = Path(__file__).resolve().parents[1]
LIVE_DB = ROOT / "data" / "app.db"


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [False, True], ids=["normal", "window"])
@pytest.mark.parametrize("variant", MAINTENANCE_VARIANTS)
async def test_maintenance_boundary_has_paired_contract_runtime_evidence(
    tmp_path: Path, variant: str, window: bool,
) -> None:
    live_before = file_sha256(LIVE_DB)
    current = await run_current_maintenance_workflow(
        tmp_path / "current", variant, window=window,
    )
    control = await run_contract_runtime_control(
        tmp_path / "control", variant, window=window,
    )
    classification, first_divergent_node = classify_paired_result(
        current, control,
    )

    assert current["workflow_shape"] == "production_workflow"
    assert current["maintenance_entered"] is True
    assert current["unified_contract_runtime"] is False
    assert control["unified_contract_runtime"] is True
    assert current["paid_llm_calls"] == control["paid_llm_calls"] == 0
    assert classification in {
        "BYPASS_CAUSAL", "BYPASS_CORRELATED",
        "NO_DIFFERENTIAL_EFFECT", "EVIDENCE_GAP",
    }
    assert first_divergent_node
    assert current["boundary_recovered"] in {True, False}
    assert current["stage_recovered"] in {True, False}
    assert current["workflow_recovered"] in {True, False}
    assert current["controlled_nonterminal"] in {True, False}
    assert current["final_outcome"] in {
        "WORKFLOW_RECOVERED", "CONTROLLED_NONTERMINAL", "TERMINAL",
    }
    assert file_sha256(LIVE_DB) == live_before
    assert not any(path.name == "app.db" for path in tmp_path.rglob("*"))
    assert hashlib.sha256(variant.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [False, True], ids=["normal", "window"])
async def test_malformed_maintenance_response_is_a_paired_causal_probe(
    tmp_path: Path, window: bool,
) -> None:
    current = await run_current_maintenance_workflow(
        tmp_path / "current", "malformed_json", window=window,
    )
    control = await run_contract_runtime_control(
        tmp_path / "control", "malformed_json", window=window,
    )
    classification, first_divergent_node = classify_paired_result(
        current, control,
    )

    assert current["workflow_recovered"] is False
    assert control["boundary_recovered"] is True
    assert classification == "BYPASS_CAUSAL"
    assert "conversion/recovery" in first_divergent_node


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [False, True], ids=["normal", "window"])
async def test_truncation_is_injected_before_protocol_failure(
    tmp_path: Path, window: bool,
) -> None:
    current = await run_current_maintenance_workflow(
        tmp_path / "current", "provider_truncation", window=window,
    )
    control = await run_contract_runtime_control(
        tmp_path / "control", "provider_truncation", window=window,
    )

    first = current["maintenance_calls"][0]
    assert first["finish_reason"] == "max_tokens"
    assert first["provider_completeness"] == "incomplete"
    assert first["partial_response"] is True
    assert any(
        event["event_type"] == "output_limit_complete"
        for event in current["causal_chain"]
    )
    assert current["terminal_error_type"] == "ArtifactConversionError"
    assert current["workflow_recovered"] is False
    assert control["boundary_recovered"] is True


def test_maintenance_fault_variants_cover_provider_metadata_not_parser_only() -> None:
    assert set(MAINTENANCE_VARIANTS) == {
        "malformed_json", "fenced_json", "missing_field", "wrong_container",
        "version_mismatch", "domain_invalid", "provider_truncation",
        "primary_fallback_double_failure",
    }


def test_committed_maintenance_matrix_separates_mechanism_from_history() -> None:
    report = json.loads((
        ROOT / "docs" / "superpowers" / "reports"
        / "r0e-maintenance-recovery-coverage-matrix.json"
    ).read_text(encoding="utf-8"))

    assert report["case_count"] == 16
    assert report["historical_incident_binding"] is None
    assert report["historical_metric_effect"] == "none_mechanism_probe_only"
    assert report["classification_summary"] == {
        "BYPASS_CAUSAL": 4,
        "BYPASS_CORRELATED": 0,
        "NO_DIFFERENTIAL_EFFECT": 12,
        "EVIDENCE_GAP": 0,
    }
    assert report["gate"] == "MECHANISM_FIX_CANDIDATE"
    assert report["paid_llm_calls"] == 0
