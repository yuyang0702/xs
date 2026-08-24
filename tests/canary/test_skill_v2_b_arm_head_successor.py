from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path

import pytest

import tools.canary.slice1_phase_b_skill_v2_single_dispatch as launcher


ROOT = Path(__file__).resolve().parents[2]
ROUTE_DATABASE = ROOT / "data/app.db"
IMPLEMENTATION = "1" * 40
APPROVAL_PARENT = "2" * 40
CURRENT = "3" * 40
PACKET_PATHS = (
    launcher.MATERIALIZATION_RELATIVE_ROOT + "/packet.json",
    launcher.MATERIALIZATION_RELATIVE_ROOT + "/sha256-manifest-v1.json",
)
APPROVAL_PATH = launcher.MATERIALIZATION_RELATIVE_ROOT + "/approval/signed.json"


def _relation(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "expected_branch": launcher.EXPECTED_BRANCH,
        "current_branch": launcher.EXPECTED_BRANCH,
        "implementation_head": IMPLEMENTATION,
        "approval_parent_head": APPROVAL_PARENT,
        "current_head": APPROVAL_PARENT,
        "materialization_parent_is_descendant": True,
        "materialization_parent_heads": (IMPLEMENTATION,),
        "materialization_changed_paths": PACKET_PATHS,
        "expected_materialization_paths": PACKET_PATHS,
        "current_parent_heads": (),
        "current_changed_paths": (),
    }
    values.update(overrides)
    return launcher.validate_approval_head_successor_relation(**values)  # type: ignore[arg-type]


def _reject(reason: str, **overrides: object) -> None:
    with pytest.raises(launcher.SkillV2BArmError) as caught:
        _relation(**overrides)
    assert caught.value.reason_code == reason


def test_exact_materialization_parent_passes() -> None:
    result = _relation()
    assert result["status"] == "exact"
    assert result["current_head_relation"] == "EXACT_APPROVAL_PARENT"


@pytest.mark.parametrize(
    ("parent", "reason"),
    [
        ("0" * 40, "approval_parent_head_mismatch"),
        ("f" * 40, "approval_parent_head_mismatch"),
        ("", "approval_parent_head_malformed"),
        ("abc", "approval_parent_head_malformed"),
        ("A" * 40, "approval_parent_head_malformed"),
        ("2" * 40 + " ", "approval_parent_head_malformed"),
    ],
)
def test_wrong_missing_or_noncanonical_approval_parent_rejected(
    parent: str, reason: str,
) -> None:
    _reject(
        reason,
        approval_parent_head=parent,
        materialization_parent_is_descendant=False,
    )


def test_wrong_real_commit_and_valid_manifest_still_rejected() -> None:
    _reject(
        "approval_parent_head_mismatch",
        approval_parent_head="f" * 40,
        materialization_parent_is_descendant=True,
        materialization_changed_paths=(PACKET_PATHS[0],),
    )


def test_unrelated_or_arbitrary_descendant_rejected() -> None:
    _reject(
        "approval_current_head_not_direct_successor",
        current_head=CURRENT,
        current_parent_heads=("4" * 40,),
        current_changed_paths=(APPROVAL_PATH,),
    )


def test_multi_commit_materialization_descendant_rejected() -> None:
    _reject(
        "approval_parent_head_not_direct_materialization_seal",
        materialization_parent_heads=("9" * 40,),
    )


@pytest.mark.parametrize(
    "changed",
    [
        ("src/novel_flywheel/runtime_skill_profiles.py",),
        ("tools/canary/slice1_phase_b_skill_v2_single_dispatch.py",),
        (APPROVAL_PATH, "docs/unrelated.md"),
    ],
)
def test_source_or_unrelated_mutation_successor_rejected(
    changed: tuple[str, ...],
) -> None:
    _reject(
        "approval_successor_contains_non_approval_evidence_change",
        current_head=CURRENT,
        current_parent_heads=(APPROVAL_PARENT,),
        current_changed_paths=changed,
    )


def test_one_direct_approval_evidence_only_successor_passes() -> None:
    result = _relation(
        current_head=CURRENT,
        current_parent_heads=(APPROVAL_PARENT,),
        current_changed_paths=(APPROVAL_PATH,),
    )
    assert result["current_head_relation"] == (
        "ONE_DIRECT_APPROVAL_EVIDENCE_ONLY_SUCCESSOR"
    )


def test_wrong_branch_rejected() -> None:
    _reject("approval_current_branch_mismatch", current_branch="other")


def test_dirty_worktree_fails_closed_before_relation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_dirty(*args: object, **kwargs: object) -> dict[str, str]:
        raise launcher.SkillV2BArmError("git_worktree_not_clean")

    monkeypatch.setattr(launcher.base, "verify_git_gate", reject_dirty)
    with pytest.raises(launcher.SkillV2BArmError) as caught:
        launcher.verify_approval_head_successor(
            repo_root=ROOT,
            approval_parent_head=APPROVAL_PARENT,
            implementation_head=IMPLEMENTATION,
            manifest={"files": []},
        )
    assert caught.value.reason_code == "git_worktree_not_clean"


def test_head_validation_precedes_scope_nonce_and_credentials() -> None:
    preflight = inspect.getsource(launcher.validate_signed_launch)
    execution = inspect.getsource(launcher.execute_authorized_once)
    assert preflight.index("verify_approval_head_successor(") < preflight.index(
        'signed_approval.get("approval_scope")'
    )
    assert execution.index("validate_signed_launch(") < execution.index(
        "run_root.mkdir(parents=True)"
    )
    assert execution.index("validate_signed_launch(") < execution.index(
        "from novel_flywheel.secrets import"
    )


def _synthetic_signed_approval(*, approval_parent_head: str) -> dict[str, object]:
    packet_root = ROOT / launcher.MATERIALIZATION_RELATIVE_ROOT
    template = json.loads(
        (packet_root / launcher.FILES["approval"]).read_text(encoding="utf-8")
    )
    now = datetime.now(timezone.utc)
    return {
        "schema": "SkillV2BArmSignedApprovalV1",
        "execution_authorized": True,
        "named_approver": "USER_PROJECT_OWNER",
        "approval_scope": launcher.APPROVAL_SCOPE,
        "cohort_id": launcher.COHORT_ID,
        "ab_pair_id": launcher.AB_PAIR_ID,
        "approval_parent_head": approval_parent_head,
        "bound_hashes": template["bound_hashes"],
        "skill_v2_authorized": True,
        "full_short_authorized": False,
        "draft_authorized": False,
        "final_review_authorized": False,
        "maintenance_authorized": False,
        "planning_v2_cutover_authorized": False,
        "story_state_mutation_allowed": False,
        "canon_mutation_allowed": False,
        "ready_mutation_allowed": False,
        "nonce_reserved": False,
        "nonce_consumed": False,
        "single_use_nonce": "offline-synthetic-not-issued",
        "execution_window": {
            "not_before": (now - timedelta(minutes=1)).isoformat(),
            "not_after": (now + timedelta(minutes=1)).isoformat(),
        },
    }


def test_canonical_packet_exact_parent_preflight_if_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet_root = ROOT / launcher.MATERIALIZATION_RELATIVE_ROOT
    if not packet_root.exists():
        pytest.skip("fresh v2 materialization is sealed after implementation commit")
    current_head = launcher.base._git(ROOT, "rev-parse", "HEAD")
    monkeypatch.setenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1")
    signed = _synthetic_signed_approval(approval_parent_head=current_head)
    result = launcher.validate_signed_launch(
        repo_root=ROOT,
        packet_root=packet_root,
        route_database=ROUTE_DATABASE,
        signed_approval=signed,
        run_root=ROOT / launcher.EXECUTION_RELATIVE_ROOT,
    )
    assert result["status"] == "exact"
    assert result["approval_head_successor"]["current_head_relation"] == (
        "EXACT_APPROVAL_PARENT"
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"approval_parent_head": None}, "approval_parent_head_missing"),
        ({"approval_parent_head": "0" * 40}, "approval_parent_head_mismatch"),
        ({"approval_scope": "OLD_OR_ALIAS_SCOPE"}, "approval_scope_mismatch"),
        ({"cohort_id": "old-cohort"}, "approval_cohort_mismatch"),
    ],
)
def test_canonical_packet_signed_preflight_rejections_if_present(
    monkeypatch: pytest.MonkeyPatch,
    mutation: dict[str, object],
    reason: str,
) -> None:
    packet_root = ROOT / launcher.MATERIALIZATION_RELATIVE_ROOT
    if not packet_root.exists():
        pytest.skip("fresh v2 materialization is sealed after implementation commit")
    current_head = launcher.base._git(ROOT, "rev-parse", "HEAD")
    monkeypatch.setenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1")
    signed = _synthetic_signed_approval(approval_parent_head=current_head)
    signed.update(mutation)
    with pytest.raises(launcher.SkillV2BArmError) as caught:
        launcher.validate_signed_launch(
            repo_root=ROOT,
            packet_root=packet_root,
            route_database=ROUTE_DATABASE,
            signed_approval=signed,
            run_root=ROOT / launcher.EXECUTION_RELATIVE_ROOT,
        )
    assert caught.value.reason_code == reason
    assert not (ROOT / launcher.EXECUTION_RELATIVE_ROOT).exists()
