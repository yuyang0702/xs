from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import pytest

from tools.canary import skill_v3_character_heavy_pilot as pilot
from tools.canary import skill_v3_pilot_approval_store as approvals


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_ID = "sv3s-089dd120ad568f87e7ef"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _clean_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    (repo / "sentinel.txt").write_text("sealed\n", encoding="utf-8")
    _git(repo, "add", "sentinel.txt")
    _git(repo, "commit", "-m", "baseline")
    return repo, _git(repo, "rev-parse", "HEAD")


def _payload(head: str, *, approval_id: str = "approval-one") -> dict[str, object]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "approval_id": approval_id,
        "repository_head": head,
        "pilot_id": pilot.PILOT_ID,
        "sample_id": SAMPLE_ID,
        "sample_slot": "A1",
        "arm": "A",
        "sample_index": 1,
        "sample_lock_sha256": "1" * 64,
        "parent_experiment_lock_sha256": pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        "model_input_component_binding_sha256": "2" * 64,
        "provider_descriptor_sha256": "3" * 64,
        "model_binding_sha256": "4" * 64,
        "route_fingerprint": "5" * 64,
        "max_output_tokens": 4624,
        "user_authorization_message_sha256": "6" * 64,
        "user_authorization_context_identity_sha256": "7" * 64,
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
    }


def test_successor_approval_store_is_outside_worktree_and_preserves_git_state(
    tmp_path: Path,
) -> None:
    repo, head = _clean_repo(tmp_path)
    store = tmp_path / "runtime-data" / "skill-v3-approvals"
    before = (_git(repo, "rev-parse", "HEAD"), _git(repo, "status", "--porcelain=v1"))

    signed = approvals.create_successor_signed_approval_v1(
        repo_root=repo,
        store_root=store,
        payload=_payload(head),
    )

    after = (_git(repo, "rev-parse", "HEAD"), _git(repo, "status", "--porcelain=v1"))
    assert before == after == (head, "")
    assert signed["repository_head"] == head
    assert signed["single_use"] is True
    assert signed["usage_status"] == "unused"
    assert signed["nonce_state"] == "NOT_CREATED"
    assert signed["authorized_actions"] == {
        "credential_lookup": True,
        "provider_client_creation": True,
        "network": True,
        "paid_provider_model_request": True,
        "necessary_request_data_egress": True,
    }
    assert not store.is_relative_to(repo)


def test_canonical_lookup_binds_head_sample_and_lock(tmp_path: Path) -> None:
    repo, head = _clean_repo(tmp_path)
    store = tmp_path / "runtime-data" / "skill-v3-approvals"
    payload = _payload(head)
    signed = approvals.create_successor_signed_approval_v1(
        repo_root=repo, store_root=store, payload=payload,
    )

    loaded = approvals.load_successor_signed_approval_v1(
        repo_root=repo,
        store_root=store,
        approval_id=str(signed["approval_id"]),
        expected_sample_id=SAMPLE_ID,
        expected_sample_lock_sha256=str(payload["sample_lock_sha256"]),
        expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
    )
    assert loaded == signed

    for field, value, reason in (
        ("expected_sample_id", "wrong", "APPROVAL_FOR_WRONG_SAMPLE"),
        ("expected_sample_lock_sha256", "9" * 64, "APPROVAL_FOR_WRONG_SAMPLE_LOCK"),
        ("expected_parent_experiment_lock_sha256", "8" * 64, "STALE_PARENT_EXPERIMENT_LOCK"),
    ):
        kwargs = {
            "repo_root": repo,
            "store_root": store,
            "approval_id": str(signed["approval_id"]),
            "expected_sample_id": SAMPLE_ID,
            "expected_sample_lock_sha256": str(payload["sample_lock_sha256"]),
            "expected_parent_experiment_lock_sha256": pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        }
        kwargs[field] = value
        with pytest.raises(approvals.SkillV3ApprovalStoreError, match=reason):
            approvals.load_successor_signed_approval_v1(**kwargs)


def test_old_repo_report_approval_cannot_authorize_successor_head(tmp_path: Path) -> None:
    old = json.loads((
        ROOT / "docs/superpowers/reports/skill-v3-character-heavy-pilot-sample1-fresh-user-approval-v1/"
        "sample1-signed-approval-v1.json"
    ).read_text(encoding="utf-8"))
    with pytest.raises(
        approvals.SkillV3ApprovalStoreError,
        match="SIGNED_APPROVAL_SCHEMA_MISMATCH",
    ):
        approvals.validate_successor_signed_approval_v1(
            old,
            expected_head="a" * 40,
            expected_sample_id=SAMPLE_ID,
            expected_sample_lock_sha256="1" * 64,
            expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        )


def test_approval_reuse_and_duplicate_active_approval_are_rejected(tmp_path: Path) -> None:
    repo, head = _clean_repo(tmp_path)
    store = tmp_path / "runtime-data" / "skill-v3-approvals"
    first = approvals.create_successor_signed_approval_v1(
        repo_root=repo, store_root=store, payload=_payload(head),
    )
    with pytest.raises(
        approvals.SkillV3ApprovalStoreError, match="ACTIVE_APPROVAL_ALREADY_EXISTS",
    ):
        approvals.create_successor_signed_approval_v1(
            repo_root=repo,
            store_root=store,
            payload=_payload(head, approval_id="approval-two"),
        )

    approvals.consume_successor_signed_approval_v1(
        store_root=store,
        approval_id=str(first["approval_id"]),
        execution_receipt_sha256="8" * 64,
    )
    with pytest.raises(
        approvals.SkillV3ApprovalStoreError, match="APPROVAL_REUSE",
    ):
        approvals.load_successor_signed_approval_v1(
            repo_root=repo,
            store_root=store,
            approval_id=str(first["approval_id"]),
            expected_sample_id=SAMPLE_ID,
            expected_sample_lock_sha256="1" * 64,
            expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        )


def test_creation_rejects_dirty_head_and_store_inside_worktree(tmp_path: Path) -> None:
    repo, head = _clean_repo(tmp_path)
    with pytest.raises(
        approvals.SkillV3ApprovalStoreError, match="APPROVAL_STORE_INSIDE_GIT_WORKTREE",
    ):
        approvals.create_successor_signed_approval_v1(
            repo_root=repo,
            store_root=repo / "approval-store",
            payload=_payload(head),
        )

    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(
        approvals.SkillV3ApprovalStoreError, match="WORKTREE_NOT_CLEAN",
    ):
        approvals.create_successor_signed_approval_v1(
            repo_root=repo,
            store_root=tmp_path / "outside",
            payload=_payload(head),
        )


def test_head_change_invalidates_approval_without_nonce_or_dispatch(tmp_path: Path) -> None:
    repo, head = _clean_repo(tmp_path)
    store = tmp_path / "runtime-data" / "skill-v3-approvals"
    signed = approvals.create_successor_signed_approval_v1(
        repo_root=repo, store_root=store, payload=_payload(head),
    )
    (repo / "next.txt").write_text("next\n", encoding="utf-8")
    _git(repo, "add", "next.txt")
    _git(repo, "commit", "-m", "next")
    with pytest.raises(
        approvals.SkillV3ApprovalStoreError, match="STALE_APPROVAL_HEAD",
    ):
        approvals.load_successor_signed_approval_v1(
            repo_root=repo,
            store_root=store,
            approval_id=str(signed["approval_id"]),
            expected_sample_id=SAMPLE_ID,
            expected_sample_lock_sha256="1" * 64,
            expected_parent_experiment_lock_sha256=pilot.PARENT_EXPERIMENT_LOCK_SHA256,
        )


def test_approval_creation_has_no_external_or_nonce_capability() -> None:
    source = Path(approvals.__file__).read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "Anthropic" not in source
    assert "requests." not in source
    assert "nonce_state\": \"NOT_CREATED" in source
