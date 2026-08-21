from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from tools.canary.ptr3_readiness import (
    SuccessorReadinessError,
    CURRENT_SUCCESSOR_PATH,
    build_ptr3_readiness_v1,
    build_r1_d3_successor_readiness_v1,
    current_successor_plan_projection,
    validate_ptr3_readiness_v1,
    validate_r1_d3_successor_readiness_v1,
)
from tools.canary.approval_profiles import (
    SHORT_COMPLETION_PROFILE_ID,
    approval_profile,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def readiness_pair():
    successor = json.loads(CURRENT_SUCCESSOR_PATH.read_text(encoding="utf-8"))
    plan = current_successor_plan_projection(successor)
    return (
        build_ptr3_readiness_v1(
            repo_root=ROOT, production_plan=plan,
            planning_domain_validator_sha256="e" * 64,
        ),
        build_r1_d3_successor_readiness_v1(
            repo_root=ROOT, production_plan=plan,
            draft_validator_sha256="f" * 64,
            mixed_script_sha256="1" * 64,
        ),
    )


def test_short_completion_profile_enables_only_fail_open_planning_observer() -> None:
    flags = approval_profile(SHORT_COMPLETION_PROFILE_ID).required_flags()
    assert flags == {
        "NOVEL_SHORT_CANONICAL_V2": False,
        "project_short_canonical_v2": False,
        "NOVEL_CANONICAL_SHADOW_V1": False,
        "NOVEL_RELIABILITY_TRACE": True,
        "NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1": False,
        "NOVEL_STRICT_TOOL_SHAPE_TRACE_V1": False,
        "NOVEL_PLANNING_REPAIR_EVIDENCE_TRACE_V1": True,
    }


def test_materialized_successor_readiness_is_hash_bound(readiness_pair) -> None:
    ptr3 = validate_ptr3_readiness_v1(readiness_pair[0])
    draft = validate_r1_d3_successor_readiness_v1(
        readiness_pair[1]
    )
    assert ptr3["expected_stale_finding_count"] == 0
    assert ptr3["historical_call7_primary_root_cause"] == "unclosed"
    assert ptr3["planning_repair_scope_mutation"] == "residual_unproven"
    assert draft["structured_draft_finding_propagation"] == "enabled"
    assert draft["draft_retry_scope_too_broad"] == "residual"


@pytest.mark.parametrize("kind", ["ptr3", "draft"])
def test_successor_readiness_tamper_fails_closed(readiness_pair, kind: str) -> None:
    value = deepcopy(
        readiness_pair[0] if kind == "ptr3" else readiness_pair[1]
    )
    value["readiness_status"] = "unknown"
    validator = (
        validate_ptr3_readiness_v1
        if kind == "ptr3" else validate_r1_d3_successor_readiness_v1
    )
    with pytest.raises(SuccessorReadinessError):
        validator(value)
