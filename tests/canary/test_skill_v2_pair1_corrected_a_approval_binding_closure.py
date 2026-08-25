from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.canary import skill_v2_pair1_corrected_a_approval_binding_closure as closure


REPO = Path(__file__).resolve().parents[2]


def _synthetic_parent_repo(tmp_path: Path) -> tuple[Path, str]:
    closure._git(tmp_path, "init")
    closure._git(tmp_path, "config", "user.email", "offline@example.invalid")
    closure._git(tmp_path, "config", "user.name", "Offline")
    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8")
    closure._git(tmp_path, "add", "base.txt"); closure._git(tmp_path, "commit", "-m", "base")
    baseline = closure._git(tmp_path, "rev-parse", "HEAD")
    src, tst = tmp_path / closure.SOURCE_PATH, tmp_path / closure.TEST_PATH
    src.parent.mkdir(parents=True); tst.parent.mkdir(parents=True)
    src.write_text("source\n", encoding="utf-8"); tst.write_text("test\n", encoding="utf-8")
    closure._git(tmp_path, "add", closure.SOURCE_PATH, closure.TEST_PATH)
    closure._git(tmp_path, "commit", "-m", "implementation")
    return tmp_path, baseline


def test_v2_is_exact_and_builder_root_cause_is_fixture_only() -> None:
    v2 = closure._load(REPO, closure.V2_PATH)
    assert v2["packet_sha256"] == closure.V2_PACKET_SHA256
    assert "approval_parent_head" not in v2
    assert "arm_role" not in v2
    assert closure.SOURCE_PATH != closure.fixture_fix.SOURCE_PATH


def test_packet_has_every_explicit_authority_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(closure, "validate_approval_parent_source_policy", lambda *_a, **_k: {
        "status": "PASS", "approval_parent_head": closure.BASELINE_HEAD,
        "source_policy": "explicit-test-parent", "changed_paths": [closure.SOURCE_PATH, closure.TEST_PATH],
        "current_head_inferred": False,
    })
    packet, bindings = closure.build_packet(REPO, approval_parent_head=closure.BASELINE_HEAD)
    assert closure.validate_packet_v3(packet) == "PASS"
    assert all(field in packet for field in closure.REQUIRED_FIELDS)
    assert packet["arm_role"] == "A_ARM"
    assert packet["skill_arm"] == "CURRENT_RUNTIME_SKILL"
    assert packet["corrected_formal_event_id"] == "EV-3D3AE01E"
    assert packet["authority_input_sha256"] == closure.AUTHORITY_SHA256
    assert packet["story_slice_sha256"] == closure.STORY_SHA256
    assert packet["pair_lock_sha256"] == closure.LOCK_SHA256
    assert bindings["tail"]["full_success_tail_offline"] == "PASS"


def test_negative_matrix_rejects_all_32(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(closure, "validate_approval_parent_source_policy", lambda *_a, **_k: {
        "status": "PASS", "approval_parent_head": closure.BASELINE_HEAD,
        "source_policy": "explicit-test-parent", "changed_paths": [closure.SOURCE_PATH, closure.TEST_PATH],
        "current_head_inferred": False,
    })
    packet, _ = closure.build_packet(REPO, approval_parent_head=closure.BASELINE_HEAD)
    result = closure.negative_matrix(packet)
    assert result["case_count"] == 32
    assert result["negative_matrix_all_fail_closed"] is True
    assert {row["status"] for row in result["results"]} == {"REJECTED_BEFORE_EXTERNAL_ACTION"}


def test_two_stage_successor_topology_and_fail_close(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, baseline = _synthetic_parent_repo(tmp_path)
    monkeypatch.setattr(closure, "BASELINE_HEAD", baseline)
    parent = closure._git(repo, "rev-parse", "HEAD")
    assert closure.validate_approval_parent_source_policy(repo, parent)["status"] == "PASS"
    material = repo / closure.OUTPUT_ROOT; material.mkdir(parents=True)
    (material / "packet.json").write_text("{}\n", encoding="utf-8")
    closure._git(repo, "add", closure.OUTPUT_ROOT); closure._git(repo, "commit", "-m", "packet")
    packet_head = closure._git(repo, "rev-parse", "HEAD")
    assert closure.validate_head_successor_v3(repo, approval_parent_head=parent, current_head=packet_head)["stage"] == "PACKET_EVIDENCE_SEAL"
    approval = repo / closure.APPROVAL_ROOT; approval.mkdir(parents=True)
    (approval / "signed.json").write_text("{}\n", encoding="utf-8")
    closure._git(repo, "add", closure.APPROVAL_ROOT); closure._git(repo, "commit", "-m", "approval")
    final = closure._git(repo, "rev-parse", "HEAD")
    assert closure.validate_head_successor_v3(repo, approval_parent_head=parent, current_head=final)["stage"] == "APPROVAL_EVIDENCE_SEAL"
    (repo / "bad.txt").write_text("bad\n", encoding="utf-8")
    closure._git(repo, "add", "bad.txt"); closure._git(repo, "commit", "-m", "bad")
    with pytest.raises(closure.ClosureError, match="bounded_successor"):
        closure.validate_head_successor_v3(repo, approval_parent_head=parent, current_head=closure._git(repo, "rev-parse", "HEAD"))


def test_offline_success_tail_dry_run_and_b_forward_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(closure, "validate_approval_parent_source_policy", lambda *_a, **_k: {
        "status": "PASS", "approval_parent_head": closure.BASELINE_HEAD,
        "source_policy": "explicit-test-parent", "changed_paths": [closure.SOURCE_PATH, closure.TEST_PATH],
        "current_head_inferred": False,
    })
    docs, result = closure.build_documents(REPO, approval_parent_head=closure.BASELINE_HEAD)
    get = lambda name: json.loads(docs[f"{closure.OUTPUT_ROOT}/{name}"].decode("utf-8"))
    assert get("approval-readiness-dry-run-v1.json")["approval_dry_run_result"] == "READY"
    assert get("full-success-tail-v1.json")["persistence_simulation"] == "PASS"
    assert get("corrected-b-forward-audit-v1.json")["corrected_b_approval_binding_complete"] is False
    assert get("privacy-scan-v1.json")["privacy_match_count"] == 0
    assert set(result["external_actions"].values()) == {0}

