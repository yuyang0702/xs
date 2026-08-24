from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

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
V3_MATERIALIZATION_ROOT = (
    ROOT
    / "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-materialization-v3"
)
V3_APPROVAL_SEAL_HEAD = "98cceb5f4398db3cfcea5dde460d2434ce81636a"
V3_INVALIDATION_HEAD = "672fa915e7ed4ab5becf08049995d4e20f06e443"
V3_SIGNED_APPROVAL = (
    V3_MATERIALIZATION_ROOT
    / "approval/skill-v2-b-arm-signed-authorization-v1.json"
)
V3_APPROVAL_BINDING = (
    V3_MATERIALIZATION_ROOT
    / "approval/skill-v2-b-arm-v3-approval-binding-v1.json"
)
V3_APPROVAL_MANIFEST = V3_MATERIALIZATION_ROOT / "approval/sha256-manifest-v1.json"


def _commit_file(repo: Path, relative_path: str, content: str, message: str) -> str:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    launcher.base._git(repo, "add", "--", relative_path)
    launcher.base._git(repo, "commit", "-m", message)
    return launcher.base._git(repo, "rev-parse", "HEAD")


def _git_backed_lineage(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "repo"
    repo.mkdir()
    launcher.base._git(repo, "init", "-b", launcher.EXPECTED_BRANCH)
    launcher.base._git(repo, "config", "user.name", "offline-test")
    launcher.base._git(repo, "config", "user.email", "offline@example.invalid")
    root = _commit_file(repo, "root.txt", "root\n", "root")
    implementation = _commit_file(repo, "implementation.txt", "impl\n", "implementation")
    packet_path = launcher.MATERIALIZATION_RELATIVE_ROOT + "/packet.json"
    manifest_path = launcher.MATERIALIZATION_RELATIVE_ROOT + "/sha256-manifest-v1.json"
    packet = repo / packet_path
    manifest = repo / manifest_path
    packet.parent.mkdir(parents=True, exist_ok=True)
    packet.write_text("{}\n", encoding="utf-8")
    manifest.write_text("{}\n", encoding="utf-8")
    launcher.base._git(repo, "add", "--", packet_path, manifest_path)
    launcher.base._git(repo, "commit", "-m", "materialization")
    materialization = launcher.base._git(repo, "rev-parse", "HEAD")
    return {
        "repo": repo,
        "root": root,
        "implementation": implementation,
        "materialization": materialization,
        "manifest": {"files": [{"path": packet_path}]},
    }


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


def test_git_backed_dirty_worktree_preserves_existing_policy(tmp_path: Path) -> None:
    lineage = _git_backed_lineage(tmp_path)
    repo = lineage["repo"]
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")  # type: ignore[operator]
    with pytest.raises(launcher.base.Slice1PhaseBMaterializationError) as caught:
        launcher.verify_approval_head_successor(
            repo_root=repo,  # type: ignore[arg-type]
            approval_parent_head=str(lineage["materialization"]),
            implementation_head=str(lineage["implementation"]),
            manifest=lineage["manifest"],  # type: ignore[arg-type]
        )
    assert caught.value.reason_code == "worktree_not_clean"


def test_git_backed_invalid_parents_are_typed_and_never_diffed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lineage = _git_backed_lineage(tmp_path)
    original_git = launcher.base._git
    commands: list[tuple[str, ...]] = []

    def spy_git(repo_root: Path, *args: str) -> str:
        commands.append(args)
        return original_git(repo_root, *args)

    monkeypatch.setattr(launcher.base, "_git", spy_git)
    candidates = ("0" * 40, "f" * 40, str(lineage["root"]))
    for candidate in candidates:
        for _ in range(2):
            commands.clear()
            with pytest.raises(launcher.SkillV2BArmError) as caught:
                launcher.verify_approval_head_successor(
                    repo_root=lineage["repo"],  # type: ignore[arg-type]
                    approval_parent_head=candidate,
                    implementation_head=str(lineage["implementation"]),
                    manifest=lineage["manifest"],  # type: ignore[arg-type]
                )
            assert caught.value.reason_code == "approval_parent_head_mismatch"
            assert sum(command[:1] == ("diff",) for command in commands) == 0


def test_git_backed_malformed_parent_rejects_before_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lineage = _git_backed_lineage(tmp_path)
    original_git = launcher.base._git
    commands: list[tuple[str, ...]] = []

    def spy_git(repo_root: Path, *args: str) -> str:
        commands.append(args)
        return original_git(repo_root, *args)

    monkeypatch.setattr(launcher.base, "_git", spy_git)
    with pytest.raises(launcher.SkillV2BArmError) as caught:
        launcher.verify_approval_head_successor(
            repo_root=lineage["repo"],  # type: ignore[arg-type]
            approval_parent_head="not-a-commit",
            implementation_head=str(lineage["implementation"]),
            manifest=lineage["manifest"],  # type: ignore[arg-type]
        )
    assert caught.value.reason_code == "approval_parent_head_malformed"
    assert sum(command[:1] == ("diff",) for command in commands) == 0


def test_git_backed_valid_and_invalid_successor_matrix(tmp_path: Path) -> None:
    lineage = _git_backed_lineage(tmp_path)
    repo = lineage["repo"]
    materialization = str(lineage["materialization"])
    common = {
        "repo_root": repo,
        "approval_parent_head": materialization,
        "implementation_head": str(lineage["implementation"]),
        "manifest": lineage["manifest"],
    }
    exact = launcher.verify_approval_head_successor(**common)  # type: ignore[arg-type]
    assert exact["current_head_relation"] == "EXACT_APPROVAL_PARENT"

    approval = _commit_file(repo, APPROVAL_PATH, "{}\n", "approval")  # type: ignore[arg-type]
    accepted = launcher.verify_approval_head_successor(**common)  # type: ignore[arg-type]
    assert accepted["current_head"] == approval
    assert accepted["current_head_relation"] == (
        "ONE_DIRECT_APPROVAL_EVIDENCE_ONLY_SUCCESSOR"
    )

    cases = (
        ("docs/unrelated.md", "arbitrary", "approval_successor_contains_non_approval_evidence_change"),
        (
            "tools/canary/slice1_phase_b_skill_v2_single_dispatch.py",
            "source",
            "approval_successor_contains_non_approval_evidence_change",
        ),
    )
    for path, content, reason in cases:
        launcher.base._git(repo, "reset", "--hard", materialization)  # type: ignore[arg-type]
        _commit_file(repo, path, content + "\n", content)  # type: ignore[arg-type]
        with pytest.raises(launcher.SkillV2BArmError) as caught:
            launcher.verify_approval_head_successor(**common)  # type: ignore[arg-type]
        assert caught.value.reason_code == reason

    launcher.base._git(repo, "reset", "--hard", materialization)  # type: ignore[arg-type]
    approval_path = repo / APPROVAL_PATH  # type: ignore[operator]
    unrelated_path = repo / "docs/unrelated-with-approval.md"  # type: ignore[operator]
    approval_path.parent.mkdir(parents=True, exist_ok=True)
    unrelated_path.parent.mkdir(parents=True, exist_ok=True)
    approval_path.write_text("{}\n", encoding="utf-8")
    unrelated_path.write_text("unrelated\n", encoding="utf-8")
    launcher.base._git(repo, "add", "--", APPROVAL_PATH, "docs/unrelated-with-approval.md")  # type: ignore[arg-type]
    launcher.base._git(repo, "commit", "-m", "mixed approval")  # type: ignore[arg-type]
    with pytest.raises(launcher.SkillV2BArmError) as caught:
        launcher.verify_approval_head_successor(**common)  # type: ignore[arg-type]
    assert caught.value.reason_code == "approval_successor_contains_non_approval_evidence_change"


def test_git_infrastructure_failure_is_canonical_not_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lineage = _git_backed_lineage(tmp_path)
    original_git = launcher.base._git
    commands: list[tuple[str, ...]] = []

    def fail_merge_base(repo_root: Path, *args: str) -> str:
        commands.append(args)
        if args[:1] == ("merge-base",):
            raise subprocess.CalledProcessError(129, ("git", *args))
        return original_git(repo_root, *args)

    monkeypatch.setattr(launcher.base, "_git", fail_merge_base)
    with pytest.raises(launcher.SkillV2BArmError) as caught:
        launcher.verify_approval_head_successor(
            repo_root=lineage["repo"],  # type: ignore[arg-type]
            approval_parent_head=str(lineage["materialization"]),
            implementation_head=str(lineage["implementation"]),
            manifest=lineage["manifest"],  # type: ignore[arg-type]
        )
    assert caught.value.reason_code == "approval_head_git_infrastructure_failure"
    assert sum(command[:1] == ("diff",) for command in commands) == 0


def test_git_object_database_failure_is_not_misclassified_as_parent_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lineage = _git_backed_lineage(tmp_path)
    original_git = launcher.base._git
    commands: list[tuple[str, ...]] = []

    def fail_object_lookup(repo_root: Path, *args: str) -> str:
        commands.append(args)
        if args[:1] == ("cat-file",):
            raise subprocess.CalledProcessError(128, ("git", *args))
        return original_git(repo_root, *args)

    monkeypatch.setattr(launcher.base, "_git", fail_object_lookup)
    with pytest.raises(launcher.SkillV2BArmError) as caught:
        launcher.verify_approval_head_successor(
            repo_root=lineage["repo"],  # type: ignore[arg-type]
            approval_parent_head=str(lineage["materialization"]),
            implementation_head=str(lineage["implementation"]),
            manifest=lineage["manifest"],  # type: ignore[arg-type]
        )
    assert caught.value.reason_code == "approval_head_git_infrastructure_failure"
    assert sum(command[:1] == ("diff",) for command in commands) == 0


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


def _sealed_v3_approval_parent_head() -> str:
    manifest = json.loads(V3_APPROVAL_MANIFEST.read_text(encoding="utf-8"))
    entries = {
        str(entry["path"]): str(entry["sha256"])
        for entry in manifest["files"]
    }
    for path in (V3_SIGNED_APPROVAL, V3_APPROVAL_BINDING):
        relative = path.relative_to(ROOT).as_posix()
        assert entries[relative] == hashlib.sha256(path.read_bytes()).hexdigest()
    signed = json.loads(V3_SIGNED_APPROVAL.read_text(encoding="utf-8"))
    binding = json.loads(V3_APPROVAL_BINDING.read_text(encoding="utf-8"))
    signed_parent = signed.get("approval_parent_head")
    binding_parent = binding.get("approval_parent_head")
    assert isinstance(signed_parent, str)
    assert launcher._CANONICAL_COMMIT_SHA_RE.fullmatch(signed_parent)
    assert binding_parent == signed_parent
    return signed_parent


def _historical_v3_preflight(
    tmp_path: Path,
    *,
    checkout_head: str,
    mutation: dict[str, object] | None = None,
) -> dict[str, object]:
    checkout = tmp_path / "historical-v3"
    subprocess.run(
        [
            "git",
            "-c",
            "core.longpaths=true",
            "-c",
            "core.autocrlf=false",
            "clone",
            "--quiet",
            "--shared",
            "--no-checkout",
            str(ROOT),
            str(checkout),
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "config", "core.longpaths", "true"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "config", "core.autocrlf", "false"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "checkout",
            "--quiet",
            "--detach",
            checkout_head,
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "update-ref",
            f"refs/heads/{launcher.EXPECTED_BRANCH}",
            checkout_head,
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "symbolic-ref",
            "HEAD",
            f"refs/heads/{launcher.EXPECTED_BRANCH}",
        ],
        check=True,
    )
    parent = _sealed_v3_approval_parent_head()
    script = r'''
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import tools.canary.slice1_phase_b_skill_v2_single_dispatch as launcher

repo_root = Path(sys.argv[1]).resolve()
route_database = Path(sys.argv[2]).resolve()
approval_parent = sys.argv[3]
mutation = json.loads(sys.argv[4])
packet_root = repo_root / launcher.MATERIALIZATION_RELATIVE_ROOT
template = json.loads((packet_root / launcher.FILES["approval"]).read_text(encoding="utf-8"))
manifest = json.loads((packet_root / launcher.FILES["manifest"]).read_text(encoding="utf-8"))
launcher.validate_materialized_packet = lambda *_args, **_kwargs: {
    "approval": template,
    "manifest": manifest,
}
now = datetime.now(timezone.utc)
signed = {
    "schema": "SkillV2BArmSignedApprovalV1",
    "execution_authorized": True,
    "named_approver": "USER_PROJECT_OWNER",
    "approval_scope": launcher.APPROVAL_SCOPE,
    "cohort_id": launcher.COHORT_ID,
    "ab_pair_id": launcher.AB_PAIR_ID,
    "approval_parent_head": approval_parent,
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
signed.update(mutation)
try:
    result = launcher.validate_signed_launch(
        repo_root=repo_root,
        packet_root=packet_root,
        route_database=route_database,
        signed_approval=signed,
        run_root=repo_root / launcher.EXECUTION_RELATIVE_ROOT,
    )
except launcher.SkillV2BArmError as exc:
    print(json.dumps({"status": "rejected", "reason_code": exc.reason_code}))
else:
    print(json.dumps({
        "status": result["status"],
        "current_head_relation": result["approval_head_successor"]["current_head_relation"],
    }))
'''
    environment = dict(os.environ)
    environment["NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(checkout),
            str(ROUTE_DATABASE),
            parent,
            json.dumps(mutation or {}, sort_keys=True),
        ],
        cwd=checkout,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_canonical_packet_exact_parent_preflight_if_present(
    tmp_path: Path,
) -> None:
    result = _historical_v3_preflight(
        tmp_path,
        checkout_head=V3_APPROVAL_SEAL_HEAD,
    )
    assert result["status"] == "exact"
    assert result["current_head_relation"] == (
        "ONE_DIRECT_APPROVAL_EVIDENCE_ONLY_SUCCESSOR"
    )


def test_invalidated_v3_approval_is_not_an_executable_successor(
    tmp_path: Path,
) -> None:
    result = _historical_v3_preflight(
        tmp_path,
        checkout_head=V3_INVALIDATION_HEAD,
    )
    assert result == {
        "status": "rejected",
        "reason_code": "approval_current_head_not_direct_successor",
    }


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
    tmp_path: Path,
    mutation: dict[str, object],
    reason: str,
) -> None:
    result = _historical_v3_preflight(
        tmp_path,
        checkout_head=V3_APPROVAL_SEAL_HEAD,
        mutation=mutation,
    )
    assert result == {"status": "rejected", "reason_code": reason}
    assert not (ROOT / launcher.EXECUTION_RELATIVE_ROOT).exists()
