from __future__ import annotations

import json
from pathlib import Path


SPECS = Path(__file__).parents[1] / "docs" / "superpowers" / "specs"
A = SPECS / "r1-pa-strict-tool-obs-1-canary-draft-v1.json"
B = SPECS / "r1-pa-budget-counterfactual-1-future-contract-v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_canary_a_is_one_run_observation_draft_without_execution_authority() -> None:
    draft = _load(A)

    assert draft["status"] == "draft_unapproved_not_executable"
    assert draft["run_limit"] == 1
    assert draft["authorization"] == {
        "named_approver": None,
        "approval_id": None,
        "signature": None,
        "execution_authorized": False,
    }
    assert draft["execution_command"] is None
    assert draft["launcher"] is None
    assert draft["diagnostic_flags"] == {
        "NOVEL_STRICT_TOOL_SHAPE_TRACE_V1": True,
        "NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1": False,
    }
    assert draft["behavior_contract"]["budget_behavior"] == "current_unchanged"
    assert draft["evidence_contract"]["raw_content_storage_allowed"] is False


def test_canary_b_is_a_future_contract_not_an_implemented_override() -> None:
    contract = _load(B)

    assert contract["status"] == "future_contract_not_executable"
    assert contract["authorization"]["execution_authorized"] is False
    assert contract["single_changed_variable"] == (
        "retain_approved_expansion_across_outer_runtime_reconstruction"
    )
    assert "canary-only behavior override" in contract["not_implemented_in_r1_pa1"]
    assert contract["execution_command"] is None
    assert contract["launcher"] is None
    assert contract["cohort_id"] is None
    assert contract["offline_evidence"]["paid_model_calls"] == 0


def test_canary_a_and_b_cannot_share_an_approval_or_cohort() -> None:
    a = _load(A)
    b = _load(B)

    assert a["canary_id"] != b["canary_id"]
    assert a["authorization"]["approval_id"] is None
    assert b["authorization"]["approval_id"] is None
    assert a["evidence_contract"]["cohort_id"] is None
    assert b["cohort_id"] is None
    assert "distinct" in " ".join(b["preconditions"]).casefold()
