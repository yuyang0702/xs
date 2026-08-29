from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tools.canary.skill_v3_hybrid_jit_approval import HybridJitApprovalError
from tools.canary.skill_v3_hybrid_real_campaign import (
    render_final_authorization_text_v1,
)
from tools.diagnostics import materialize_skill_v3_hybrid_final_head_authorization as final_auth
from tools.diagnostics.materialize_skill_v3_hybrid_final_head_authorization import (
    AUTHORIZATION_FILENAME,
    RECEIPT_FILENAME,
    materialize_final_head_authorization_bundle_v1,
    validate_final_head_authorization_preflight_v1,
)


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 29, 4, 0, tzinfo=timezone.utc)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True,
        text=True, encoding="utf-8",
    ).stdout.strip()


@pytest.fixture
def clean_repo(monkeypatch: pytest.MonkeyPatch) -> Path:
    head = _git(ROOT, "rev-parse", "HEAD")
    branch = _git(ROOT, "branch", "--show-current")
    monkeypatch.setattr(
        final_auth,
        "current_git_identity",
        lambda _repo, *, require_clean: (head, branch),
    )
    return ROOT


def test_final_head_bundle_is_exact_external_and_git_inert(
    clean_repo: Path, tmp_path: Path,
) -> None:
    head_before = _git(clean_repo, "rev-parse", "HEAD")
    status_before = _git(clean_repo, "status", "--porcelain=v1", "-uall")
    result = materialize_final_head_authorization_bundle_v1(
        repo_root=clean_repo,
        output_parent=tmp_path / "runtime-data",
        created_at=NOW,
    )
    bundle = Path(result["bundle_path"])
    authorization = (bundle / AUTHORIZATION_FILENAME).read_bytes()
    receipt = json.loads((bundle / RECEIPT_FILENAME).read_text(encoding="utf-8"))

    assert bundle.is_relative_to(tmp_path / "runtime-data")
    assert not bundle.is_relative_to(clean_repo)
    assert authorization == render_final_authorization_text_v1(
        clean_repo, successor_head=head_before,
    )
    assert receipt["final_execution_head"] == head_before
    assert receipt["head_after_authorization_materialization"] == head_before
    assert receipt["authorization_text_sha256"] == hashlib.sha256(
        authorization,
    ).hexdigest()
    assert receipt["real_runner_authorization_preflight"] == "PASS"
    assert receipt["post_auth_git_write_count"] == 0
    assert receipt["post_auth_git_commit_count"] == 0
    assert receipt["pilot_execution_authorized"] is False
    assert receipt["real_signed_approval_created"] is False
    assert receipt["real_nonce_created"] is False
    assert receipt["external_action_counters"] == {
        "credential_lookup_count": 0,
        "provider_client_creation_count": 0,
        "provider_request_attempts": 0,
        "http_post_attempts": 0,
        "network_calls": 0,
        "model_calls": 0,
        "paid_calls": 0,
    }
    assert _git(clean_repo, "rev-parse", "HEAD") == head_before
    assert _git(clean_repo, "status", "--porcelain=v1", "-uall") == status_before


def test_external_bundle_is_exclusive_and_never_overwritten(
    clean_repo: Path, tmp_path: Path,
) -> None:
    output = tmp_path / "runtime-data"
    first = materialize_final_head_authorization_bundle_v1(
        repo_root=clean_repo, output_parent=output, created_at=NOW,
    )
    before = (Path(first["bundle_path"]) / AUTHORIZATION_FILENAME).read_bytes()
    with pytest.raises(HybridJitApprovalError, match="FINAL_AUTHORIZATION_BUNDLE_EXISTS"):
        materialize_final_head_authorization_bundle_v1(
            repo_root=clean_repo, output_parent=output, created_at=NOW,
        )
    assert (Path(first["bundle_path"]) / AUTHORIZATION_FILENAME).read_bytes() == before


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value[:-1] + (b"X" if value[-1:] != b"X" else b"Y"),
        lambda value: value.replace(
            b"DESTINATION=https://lingsuan.org:443/v1/messages",
            b"DESTINATION=[https://lingsuan.org:443/v1/messages](https://lingsuan.org:443/v1/messages)",
            1,
        ),
        lambda value: b"\n".join(
            line for line in value.split(b"\n")
            if not line.startswith(b"SAMPLE_LOCK_SHA256S=")
        ),
        lambda value: b"\n".join(
            line for line in value.split(b"\n")
            if not line.startswith(b"EGRESS_POLICY_SHA256S=")
        ),
    ],
    ids=["one-byte", "markdown-url", "sample-lock-omission", "egress-omission"],
)
def test_authorization_mutations_fail_exact_preflight(
    clean_repo: Path, mutator,
) -> None:
    head = _git(clean_repo, "rev-parse", "HEAD")
    canonical = render_final_authorization_text_v1(
        clean_repo, successor_head=head,
    )
    with pytest.raises(HybridJitApprovalError, match="AUTHORIZATION_TEXT_EXACT_MISMATCH"):
        validate_final_head_authorization_preflight_v1(
            repo_root=clean_repo, authorization_bytes=mutator(canonical),
        )


def test_post_authorization_head_drift_is_rejected(clean_repo: Path) -> None:
    head = _git(clean_repo, "rev-parse", "HEAD")
    authorization = render_final_authorization_text_v1(
        clean_repo, successor_head=head,
    )
    with pytest.raises(HybridJitApprovalError, match="AUTHORIZATION_TEXT_EXACT_MISMATCH"):
        validate_final_head_authorization_preflight_v1(
            repo_root=clean_repo,
            authorization_bytes=authorization,
            observed_head_override="0" * 40,
        )


def test_dirty_worktree_stops_before_external_bundle(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    subprocess.run(
        ["git", "checkout", "-b", final_auth.EXPECTED_BRANCH],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@example.invalid"],
        cwd=repo, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Hybrid Test"],
        cwd=repo, check=True,
    )
    (repo / "tracked.txt").write_text("baseline", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline", "--quiet"], cwd=repo, check=True,
    )
    (repo / "UNTRACKED-BLOCKER.txt").write_text("dirty", encoding="utf-8")
    output = tmp_path / "runtime-data"
    with pytest.raises(HybridJitApprovalError, match="WORKTREE_POLICY_VIOLATION"):
        materialize_final_head_authorization_bundle_v1(
            repo_root=repo, output_parent=output, created_at=NOW,
        )
    assert not output.exists()


def test_inside_worktree_store_is_rejected(clean_repo: Path) -> None:
    output = clean_repo / ".runtime-authorization-test"
    with pytest.raises(
        HybridJitApprovalError, match="APPROVAL_STORE_INSIDE_GIT_WORKTREE",
    ):
        materialize_final_head_authorization_bundle_v1(
            repo_root=clean_repo, output_parent=output, created_at=NOW,
        )
    assert not output.exists()
