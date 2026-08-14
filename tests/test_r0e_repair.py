from __future__ import annotations

from pathlib import Path
import json

import pytest

from r0e_repair_harness import (
    REPAIR_VARIANTS,
    repair_reentry_matrix,
    run_repair_probe,
)


ROOT = Path(__file__).resolve().parents[1]


def test_repair_path_map_keeps_runtime_and_bypass_siblings_distinct() -> None:
    matrix = repair_reentry_matrix(ROOT)
    rows = {row["function"]: row for row in matrix["rows"]}

    assert rows["_repair_short_revision_semantic_group"][
        "all_secondary_model_outputs_reenter_contract_runtime"
    ] is True
    assert rows["_repair_polish_semantic_segment"][
        "all_secondary_model_outputs_reenter_contract_runtime"
    ] is False
    assert rows["_close_short_maintenance_window"][
        "all_secondary_model_outputs_reenter_contract_runtime"
    ] is False
    assert rows["_close_short_maintenance_authority"][
        "all_secondary_model_outputs_reenter_contract_runtime"
    ] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", REPAIR_VARIANTS)
async def test_repair_probe_preserves_best_candidate_and_checkpoint(
    tmp_path: Path, variant: str,
) -> None:
    result = await run_repair_probe(tmp_path / "r0e", variant)

    assert result["same_contract_runtime"] is False
    assert result["prior_best_preserved"] is True
    assert result["failed_repair_overwrote_best"] is False
    assert result["checkpoint_preserved"] is True
    assert result["resume_source"] == "best-candidate.md"
    assert result["controlled_containment"] is True
    assert result["paid_llm_calls"] == 0
    assert result["historical_incident_binding"] is None
    assert result["boundary_recovered"] in {True, False}
    assert result["stage_recovered"] in {True, False}
    assert result["workflow_recovered"] is None
    assert result["controlled_nonterminal"] in {True, False}


@pytest.mark.asyncio
async def test_fix_a_break_b_is_revalidated_before_acceptance(tmp_path: Path) -> None:
    result = await run_repair_probe(tmp_path / "r0e", "fix_a_break_b")

    assert result["repair_recovered"] is True
    assert len(result["repair_calls"]) == 2
    assert result["semantic_validator_calls"] == 2
    assert result["prior_best_preserved"] is True


@pytest.mark.asyncio
async def test_cleanup_secondary_exception_masks_primary_repair_failure(
    tmp_path: Path,
) -> None:
    result = await run_repair_probe(
        tmp_path / "r0e", "cleanup_secondary_exception",
    )

    assert result["final_outcome"] == "CLEANUP_SECONDARY_MASKED_PRIMARY"
    assert result["terminal_error_type"] == "OSError"
    assert result["primary_error_in_context"] == "TargetedGroupError"
    assert "ModelRoutesExhaustedError" in result["exception_chain"]
    assert result["root_cause_preserved"] is False
    assert result["prior_best_preserved"] is True


@pytest.mark.asyncio
async def test_provider_truncation_is_injected_before_repair_shape_validation(
    tmp_path: Path,
) -> None:
    result = await run_repair_probe(tmp_path / "r0e", "provider_truncation")

    first = result["repair_calls"][0]
    assert first["finish_reason"] == "max_tokens"
    assert first["partial_response"] is True
    assert result["repair_recovered"] is True


def test_six_unclassified_followups_do_not_silently_reclassify_history() -> None:
    report = json.loads((
        ROOT / "docs" / "superpowers" / "reports"
        / "r0e-six-unclassified-follow-up.json"
    ).read_text(encoding="utf-8"))

    assert report["row_count"] == 6
    assert report["conversion_summary"] == {
        "A": 0, "B": 0, "C": 6, "D": 0,
        "historical_family_converted": 0,
    }
    assert all(
        row["stored_current_family"].startswith("unclassified.")
        and row["conversion_status"] == "candidate_mapping_unverified"
        and row["gate"] == "DEVELOPMENT_NO_GO"
        for row in report["rows"]
    )
