from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from tools.canary.approval_dispatch import (
    materialize_signed_canary_approval,
    validate_registered_approval_document,
)
from tools.canary.approval_profiles import (
    SHORT_COMPLETION_PROFILE_ID,
    approval_profile,
)
from tools.canary.approval_store import (
    ApprovalConsumptionStore, CanaryApprovalReplay,
    initialize_approval_ledger_v1,
)
from tools.canary.artifact_hash import file_sha256, tree_manifest
from tools.canary.contracts import CanaryContractError
from tools.canary.contracts import build_canary_experiment_plan_v1
from tools.canary.fingerprint_profiles import (
    PRODUCTION_MIRROR_SHORT_PROFILE_ID,
)
from tools.canary.ptr3_readiness import (
    SuccessorReadinessError,
    validate_ptr3_readiness_v1,
    validate_r1_d3_successor_readiness_v1,
)
from tools.canary.short_completion import completion_contract_bundle_v1
from tools.canary.short_completion_approval import (
    materialize_short_completion_patch_v1,
)
from tools.canary.short_completion_closure import (
    validate_short_completion_approval_closure,
)
from tools.canary.short_completion_materialization import (
    materialize_short_completion_1,
)


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "canary" / "short-normal-v1.json"
LIVE_DB = ROOT / "data" / "app.db"
LIVE_PROJECTS = ROOT / "data" / "projects"
NOW = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def materialized(tmp_path_factory: pytest.TempPathFactory):
    import keyring

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        keyring, "get_password",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("credential lookup during materialization")
        ),
    )
    before = {
        "db": file_sha256(LIVE_DB),
        "projects": tree_manifest(LIVE_PROJECTS)["tree_sha256"],
    }
    result = materialize_short_completion_1(
        live_database_path=LIVE_DB, live_project_root=LIVE_PROJECTS,
        fixture_path=FIXTURE,
        output_root=tmp_path_factory.mktemp("short-completion") / "outputs",
        cohort_id="short-completion-1-20260816t100000z-test",
        run_namespace="short-completion-1-20260816t100000z-test",
        artifact_root_label="docs/superpowers/reports/sc-auth-1",
        now=NOW,
    )
    after = {
        "db": file_sha256(LIVE_DB),
        "projects": tree_manifest(LIVE_PROJECTS)["tree_sha256"],
    }
    monkeypatch.undo()
    assert before == after
    return result


def test_plan_candidate_patch_and_validate_only_are_exact(materialized) -> None:
    plan = materialized["plan"]
    candidate = materialized["approval_candidate"]
    patch = materialized["authorization_patch_template"]
    receipt = materialized["validation_receipt"]
    assert plan["canary_mode"] == "short_completion"
    assert plan["workloads"][0]["success_definition"] == (
        "SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED"
    )
    assert candidate["execution_authorized"] is False
    assert patch["execution_authorized"] is False
    assert receipt["overall_status"] == "exact"
    assert len(receipt["ordered_checks"]) >= 32
    assert set(receipt["external_action_counters"].values()) == {0}
    assert materialized["network_call_count"] == 0
    assert plan["runtime_fingerprint_policy_version"] == "runtime-fingerprint-v2"
    assert receipt["approval_ledger_operational_readiness"] == "exact"
    assert materialized["ledger_readiness"]["initial_entry_count"] == 0
    assert materialized["semantic_rehearsal"]["status"] == "exact"
    assert materialized["semantic_rehearsal"]["observation_status"] == "exact"
    assert materialized["semantic_rehearsal"][
        "planning_finding_rehearsal"
    ]["convergence_status"] == "exact"
    assert materialized["semantic_rehearsal"][
        "draft_finding_rehearsal"
    ]["convergence_status"] == "exact"
    assert materialized["semantic_rehearsal"]["collection_profile_id"] == (
        PRODUCTION_MIRROR_SHORT_PROFILE_ID
    )
    assert materialized["semantic_rehearsal"][
        "collection_profile_comparison"
    ]["comparison_status"] == "exact"
    assert materialized["semantic_rehearsal"][
        "materialization_runtime_execution_sha256"
    ] == materialized["semantic_rehearsal"][
        "subprocess_runtime_execution_sha256"
    ]
    assert materialized["semantic_rehearsal"]["external_action_counters"] == {
        "credential_lookup_count": 0,
        "provider_client_creation_count": 0,
        "network_call_count": 0,
        "model_call_count": 0,
        "paid_model_call_count": 0,
        "fake_boundary_count": 2,
    }


def test_materialization_has_no_signed_approval_and_is_privacy_safe(materialized) -> None:
    assert materialized["index"]["signed_approval_materialized"] is False
    assert materialized["index"]["execution_performed"] is False
    assert not any("signed-approval" in name for name in materialized["index"]["files"])
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    serialized = json.dumps({
        key: materialized[key] for key in (
            "plan", "approval_candidate", "authorization_patch_template",
            "validation_receipt", "execution_preview", "index",
        )
    }, ensure_ascii=False)
    assert fixture["title"] not in serialized
    assert fixture["premise"] not in serialized
    assert "api_key" not in serialized.casefold()
    assert "bearer " not in serialized.casefold()


def test_candidate_and_patch_cannot_execute_or_reserve(materialized, tmp_path: Path) -> None:
    profile = approval_profile(SHORT_COMPLETION_PROFILE_ID)
    candidate = materialized["approval_candidate"]
    with pytest.raises(CanaryApprovalReplay, match="approval_candidate_not_executable"):
        ApprovalConsumptionStore(tmp_path).reserve(candidate)
    with pytest.raises(CanaryContractError, match="authorization_patch_not_executable"):
        validate_registered_approval_document(
            materialized["authorization_patch_template"],
            expected_profile_id=profile.profile_id,
            expected_scope=profile.approval_scope,
            expected_plan_sha256=materialized["plan"]["plan_sha256"],
            expected_launcher_sha256=materialized["plan"]["launcher_sha256"],
        )


def test_signed_fixture_is_exact_and_single_use(materialized, tmp_path: Path) -> None:
    candidate = materialized["approval_candidate"]
    patch = materialize_short_completion_patch_v1(
        materialized["authorization_patch_template"],
        named_approver="test_owner",
        approval_timestamp="2026-08-16T10:05:00Z",
    )
    signed = materialize_signed_canary_approval(
        SHORT_COMPLETION_PROFILE_ID, candidate, patch, now=NOW,
    )
    initialize_approval_ledger_v1(
        tmp_path,
        ledger_identity=materialized["plan"]["isolation"][
            "approval_ledger_identity"
        ],
    )
    store = ApprovalConsumptionStore(tmp_path)
    reservation = store.reserve(signed)
    assert reservation["payload"]["profile_id"] == SHORT_COMPLETION_PROFILE_ID
    with pytest.raises(CanaryApprovalReplay, match="approval_already_reserved"):
        store.reserve(signed)
    consumed = store.consume(signed, "f" * 64)
    assert consumed["payload"]["consumed_evidence_sha256"] == "f" * 64


def test_signed_validate_only_is_exact_and_executable(
    materialized, tmp_path: Path,
) -> None:
    candidate = materialized["approval_candidate"]
    patch = materialize_short_completion_patch_v1(
        materialized["authorization_patch_template"],
        named_approver="test_owner",
        approval_timestamp="2026-08-16T10:05:00Z",
    )
    signed = materialize_signed_canary_approval(
        SHORT_COMPLETION_PROFILE_ID, candidate, patch, now=NOW,
    )
    candidate_path = tmp_path / "candidate.json"
    patch_path = tmp_path / "patch.json"
    signed_path = tmp_path / "signed.json"
    for path, value in (
        (candidate_path, candidate), (patch_path, patch), (signed_path, signed),
    ):
        path.write_text(json.dumps(value), encoding="utf-8")
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    initialize_approval_ledger_v1(
        ledger,
        ledger_identity=materialized["plan"]["isolation"][
            "approval_ledger_identity"
        ],
    )
    receipt = validate_short_completion_approval_closure(
        plan_path=materialized["paths"]["plan"], approval_path=signed_path,
        source_candidate_path=candidate_path,
        source_authorization_patch_path=patch_path,
        packet_path=None, workload_fixture_path=FIXTURE,
        live_database_path=LIVE_DB, live_project_root=LIVE_PROJECTS,
        canary_root=tmp_path / "canary", approval_ledger_root=ledger,
        cli_approved_plan_sha256=materialized["plan"]["plan_sha256"], now=NOW,
    )
    assert receipt["overall_status"] == "exact"
    assert receipt["approval_state"] == "signed_approval_exact_and_executable"
    assert signed["r1_d3_production_mirror_readiness_sha256"] == (
        materialized["r1_d3_production_mirror_readiness"]["definition_sha256"]
    )


@pytest.mark.parametrize("kind", ["ptr3", "draft"])
def test_successor_readiness_blocks_non_execution_identity_drift(
    materialized, kind: str,
) -> None:
    value = deepcopy(
        materialized["ptr3_readiness"] if kind == "ptr3"
        else materialized["r1_d3_production_mirror_readiness"]
    )
    value["production_mirror_build_sha256" if kind == "draft"
          else "current_build_sha256"] = "f" * 64
    validator = (
        validate_ptr3_readiness_v1 if kind == "ptr3"
        else validate_r1_d3_successor_readiness_v1
    )
    with pytest.raises(SuccessorReadinessError):
        validator(value)


def test_legacy_short_completion_plan_without_readiness_remains_readable(
    materialized,
) -> None:
    payload = deepcopy(materialized["plan"])
    payload.pop("plan_sha256")
    policy = payload["short_completion_policy"]
    policy.pop("execution_collection_profile_id")
    policy.pop("r1_d3_production_mirror_readiness_sha256")
    policy.pop("r1_d3_production_mirror_readiness")

    legacy = build_canary_experiment_plan_v1(payload)

    assert legacy["canary_mode"] == "short_completion"


@pytest.mark.parametrize("mutation", [
    "phase1b", "pa_trace", "stop", "prompt", "route", "mixed_script",
])
def test_validate_only_blocks_policy_and_route_drift(
    materialized, tmp_path: Path, mutation: str,
) -> None:
    plan = deepcopy(materialized["plan"])
    if mutation == "phase1b":
        plan["feature_flag_snapshot"]["NOVEL_SHORT_CANONICAL_V2"] = True
    elif mutation == "pa_trace":
        plan["feature_flag_snapshot"]["NOVEL_STRICT_TOOL_SHAPE_TRACE_V1"] = True
    elif mutation == "stop":
        plan["stop_conditions"] = plan["stop_conditions"][:-1]
    elif mutation == "prompt":
        plan["workloads"][0]["prompt_policy_manifest_sha256"] = "b" * 64
    elif mutation == "route":
        plan["approved_routes"][0]["primary"]["model_binding_hash"] = "b" * 64
    else:
        plan["short_completion_policy"]["mixed_script_policy_sha256"] = "b" * 64
    plan["plan_sha256"] = "b" * 64
    plan_path = tmp_path / f"{mutation}.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    receipt = validate_short_completion_approval_closure(
        plan_path=plan_path, approval_path=materialized["paths"]["candidate"],
        source_candidate_path=None, source_authorization_patch_path=None,
        packet_path=None, workload_fixture_path=FIXTURE,
        live_database_path=LIVE_DB, live_project_root=LIVE_PROJECTS,
        canary_root=tmp_path / "canary", approval_ledger_root=tmp_path,
        cli_approved_plan_sha256=plan["plan_sha256"], now=NOW,
    )
    assert receipt["overall_status"] == "blocked"


def test_materialization_gate_is_ready_but_waiting_for_user(materialized) -> None:
    assert materialized["index"]["contract_status"] == (
        "SHORT_COMPLETION_APPROVAL_PROFILE_READY"
    )
    assert materialized["index"]["status"] == (
        "SHORT_COMPLETION_CANARY_WAITING_FOR_FINAL_USER_AUTHORIZATION"
    )
