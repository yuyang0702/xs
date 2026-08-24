from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

import tools.canary.slice1_phase_b_skill_v2_single_dispatch as launcher


ROOT = Path(__file__).resolve().parents[2]
V1_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-slice1-phase-b-skill-v2-materialization-v1"
)
V2_ROOT = (
    "docs/superpowers/reports/"
    "short-plan-v2-slice1-phase-b-skill-v2-materialization-v2"
)


def _copy_history(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for relative_root in (V1_ROOT, V2_ROOT):
        source = ROOT / relative_root
        target = repo / relative_root
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    return repo


def _tree_hashes(repo: Path) -> dict[str, str]:
    return {
        path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for relative_root in (V1_ROOT, V2_ROOT)
        for path in sorted((repo / relative_root).rglob("*"))
        if path.is_file()
    }


def _expect_historical_drift(repo: Path) -> None:
    with pytest.raises(launcher.SkillV2BArmError) as caught:
        launcher.verify_historical_materialization_roots(repo)
    assert caught.value.reason_code == (
        "SKILL_V2_B_ARM_HISTORICAL_ROOTS_NO_GO_HISTORICAL_DRIFT"
    )


def test_exact_v1_v2_roots_are_verified_read_only(tmp_path: Path) -> None:
    repo = _copy_history(tmp_path)
    before = _tree_hashes(repo)
    result = launcher.verify_historical_materialization_roots(repo)
    after = _tree_hashes(repo)
    assert result["status"] == "exact"
    assert result["allowlist_mode"] == "CLOSED_WORLD"
    assert result["allowed_historical_root_count"] == 2
    assert result["historical_roots"] == [V1_ROOT, V2_ROOT]
    assert result["roots"][0]["manifest_definition_sha256"] == (
        "d8ae1e531d08c2a704f2383c915ea1af2a4a01e255d26f187db9d7813582d5f2"
    )
    assert result["roots"][0]["manifest_file_sha256"] == (
        "b07edf3736fc76981bb0a3147ffed8d4638b22d086c20530317e84ebf790ad82"
    )
    assert result["roots"][0]["manifest_file_count"] == 25
    assert result["roots"][1]["manifest_definition_sha256"] == (
        "fdc0bd76bd0c8ca396c17398055d6a3a0be8af9b0da5bb47a0116cc063c7c121"
    )
    assert result["roots"][1]["manifest_file_sha256"] == (
        "2e8033f8027252bfecc8d1d59bab893269fb82dd656642080a9f4d378cd63612"
    )
    assert result["roots"][1]["manifest_file_count"] == 27
    assert before == after


@pytest.mark.parametrize("relative_root", [V1_ROOT, V2_ROOT])
def test_missing_historical_root_rejected(
    tmp_path: Path, relative_root: str,
) -> None:
    repo = _copy_history(tmp_path)
    shutil.rmtree(repo / relative_root)
    _expect_historical_drift(repo)


@pytest.mark.parametrize("relative_root", [V1_ROOT, V2_ROOT])
def test_mutated_historical_manifest_rejected(
    tmp_path: Path, relative_root: str,
) -> None:
    repo = _copy_history(tmp_path)
    manifest = repo / relative_root / "sha256-manifest-v1.json"
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    _expect_historical_drift(repo)


@pytest.mark.parametrize("relative_root", [V1_ROOT, V2_ROOT])
def test_mutated_manifested_file_rejected(
    tmp_path: Path, relative_root: str,
) -> None:
    repo = _copy_history(tmp_path)
    manifest = json.loads(
        (repo / relative_root / "sha256-manifest-v1.json").read_text(encoding="utf-8")
    )
    target = repo / manifest["files"][0]["path"]
    target.write_bytes(target.read_bytes() + b"mutation")
    _expect_historical_drift(repo)


@pytest.mark.parametrize("relative_root", [V1_ROOT, V2_ROOT])
def test_unmanifested_historical_file_rejected(
    tmp_path: Path, relative_root: str,
) -> None:
    repo = _copy_history(tmp_path)
    (repo / relative_root / "unexpected.json").write_text("{}\n", encoding="utf-8")
    _expect_historical_drift(repo)


def test_committed_path_policy_accepts_only_exact_verified_history(
    tmp_path: Path,
) -> None:
    repo = _copy_history(tmp_path)
    history = launcher.verify_historical_materialization_roots(repo)
    active = (
        launcher.LAUNCHER_RELATIVE_PATH,
        "docs/maintenance.md",
        "tests/canary/test_skill_v2_real_ab_b_arm.py",
        "tests/canary/test_skill_v2_b_arm_head_successor.py",
        "tests/canary/test_skill_v2_b_arm_historical_roots.py",
    )
    committed = tuple(history["verified_committed_paths"]) + active
    result = launcher.validate_committed_path_baseline(
        committed_paths=committed,
        historical_roots=history,
    )
    assert result["status"] == "exact"
    assert result["active_support_paths"] == sorted(active)
    assert result["historical_path_exclusion_requires_manifest_exact"] is True


@pytest.mark.parametrize(
    "unexpected_path",
    [
        "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-materialization-v4/README.md",
        "docs/superpowers/reports/short-plan-v2-slice1-phase-b-skill-v2-materialization-v10/README.md",
        V1_ROOT + "-lookalike/README.md",
        V1_ROOT + "/unexpected.json",
        "src/novel_flywheel/runtime_skill_profiles.py",
    ],
)
def test_arbitrary_prefix_extra_and_active_source_drift_rejected(
    tmp_path: Path, unexpected_path: str,
) -> None:
    repo = _copy_history(tmp_path)
    history = launcher.verify_historical_materialization_roots(repo)
    committed = tuple(history["verified_committed_paths"]) + (unexpected_path,)
    with pytest.raises(launcher.SkillV2BArmError) as caught:
        launcher.validate_committed_path_baseline(
            committed_paths=committed,
            historical_roots=history,
        )
    assert caught.value.reason_code == (
        "SKILL_V2_REAL_AB_B_ARM_MATERIALIZATION_NO_GO_BASELINE_DRIFT"
    )
