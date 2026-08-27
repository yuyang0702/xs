from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import pytest

from tools.canary import skill_v3_character_heavy_pilot as pilot
from tools.canary import skill_v3_overnight_campaign as campaign
from tools.canary import skill_v3_pilot_approval_store as approvals
from tools.diagnostics import materialize_skill_v3_overnight_campaign_phase_a as materializer


ROOT = Path(__file__).resolve().parents[2]


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


def _v4_payload(head: str, slot: str = "B1") -> dict[str, object]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    index = {"B1": 1, "A2": 2, "B2": 2, "A3": 3, "B3": 3}.get(slot, 1)
    arm = slot[0]
    return {
        "approval_id": f"approval-{slot.lower()}",
        "repository_head": head,
        "pilot_id": pilot.PILOT_ID,
        "sample_id": f"sample-{slot.lower()}",
        "sample_slot": slot,
        "arm": arm,
        "sample_index": index,
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
        "wire_input_sha256": "8" * 64,
        "sampling_policy_sha256": "9" * 64,
        "validator_sha256": "a" * 64,
        "nonce_policy_version": pilot.NONCE_POLICY_VERSION,
        "real_dispatcher_version": pilot.REAL_DISPATCHER_VERSION,
        "destination_origin": "https://lingsuan.org",
        "destination_origin_sha256": "b" * 64,
        "destination_path_or_prefix": "/v1/messages",
        "destination_operator_class": campaign.EXPECTED_OPERATOR_CLASS,
        "egress_policy_sha256": "c" * 64,
        "cross_origin_redirect_allowed": False,
        "unbound_proxy_route_allowed": False,
        "campaign_authorization_sha256": "d" * 64,
        "campaign_authorization_context_identity_sha256": "e" * 64,
        "campaign_expires_at": (now + timedelta(hours=10)).isoformat().replace("+00:00", "Z"),
    }


def test_phase_a_snapshot_binds_all_remaining_samples_without_external_actions() -> None:
    assert campaign.validate_a1_sealed_valid_evidence(ROOT)["sample_validity"] == "SEALED_VALID"
    snapshot = campaign.phase_a_snapshot(ROOT)
    assert snapshot["status"] == "EXACT"
    assert [row["sample_slot"] for row in snapshot["remaining"]] == list(campaign.CAMPAIGN_SEQUENCE)
    assert snapshot["remaining_max_output_tokens_sum"] == 23120
    assert snapshot["remaining_max_provider_requests"] == 5
    assert snapshot["remaining_cost_cap"] == "UNKNOWN_NOT_SEALED"
    assert set(snapshot["external_actions"].values()) == {0}
    assert snapshot["all_non_skill_model_visible_bytes_identical_across_6"] is True
    assert snapshot["uncontrolled_variable_count"] == 0


def test_all_remaining_destinations_and_egress_are_exact() -> None:
    environment = campaign.canonical_real_execution_environment_v1(ROOT)
    destinations = campaign.resolve_remaining_destinations_v1(ROOT, environment.route_database)
    assert len(destinations) == 5
    assert {
        f"{value.origin}:{value.port}{value.api_path}" for value in destinations.values()
    } == {campaign.EXPECTED_DESTINATION}
    assert {value.operator_class for value in destinations.values()} == {
        campaign.EXPECTED_OPERATOR_CLASS,
    }
    for lock in campaign.remaining_locks(ROOT):
        policy = campaign.remaining_sample_egress_policy_v1(ROOT, str(lock["sample_id"]))
        assert policy["excluded"] == {
            "raw_ref_corpus_egress": False,
            "raw_distill_evidence_excerpt_egress": False,
            "learn_node_raw_evidence_egress": False,
            "prior_sample_prose_egress": False,
            "prior_sample_result_egress": False,
            "historical_blind_result_egress": False,
            "credential_egress": False,
            "local_absolute_path_egress": False,
        }


def test_v4_jit_approval_is_single_sample_and_external(tmp_path: Path) -> None:
    repo, head = _clean_repo(tmp_path)
    store = tmp_path / "runtime" / "approvals"
    payload = _v4_payload(head, "B1")
    signed = approvals.create_remaining_campaign_signed_approval_v4(
        repo_root=repo, store_root=store, payload=payload,
    )
    assert signed["sample_slot"] == "B1"
    assert signed["single_use"] is True
    assert signed["other_samples_authorized"] is False
    assert signed["nonce_state"] == "NOT_CREATED"
    assert not store.is_relative_to(repo)
    loaded = approvals.load_remaining_campaign_signed_approval_v4(
        repo_root=repo,
        store_root=store,
        approval_id=str(signed["approval_id"]),
        expected=payload,
    )
    assert loaded == signed


def test_v4_jit_approval_does_not_weaken_historical_a1_scope(tmp_path: Path) -> None:
    repo, head = _clean_repo(tmp_path)
    with pytest.raises(approvals.SkillV3ApprovalStoreError, match="APPROVAL_FOR_WRONG_SAMPLE"):
        approvals.create_remaining_campaign_signed_approval_v4(
            repo_root=repo,
            store_root=tmp_path / "runtime" / "approvals",
            payload=_v4_payload(head, "A1"),
        )

    wrong_arm = _v4_payload(head, "B1")
    wrong_arm["arm"] = "A"
    with pytest.raises(approvals.SkillV3ApprovalStoreError, match="APPROVAL_FOR_WRONG_SAMPLE"):
        approvals.create_remaining_campaign_signed_approval_v4(
            repo_root=repo,
            store_root=tmp_path / "runtime-two" / "approvals",
            payload=wrong_arm,
        )


def test_permission_requires_exact_generated_sentence_and_creates_no_nonce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, head = _clean_repo(tmp_path)
    locks = tuple(
        {"sample_slot": slot, "sample_id": f"sample-{slot.lower()}"}
        for slot in campaign.CAMPAIGN_SEQUENCE
    )
    monkeypatch.setattr(campaign, "remaining_locks", lambda _repo: locks)
    exact = campaign.authorization_sentence(repo)
    store = tmp_path / "runtime" / "permissions"
    receipt = campaign.create_campaign_permission_receipt_v1(
        repo_root=repo,
        authorization_message=exact,
        authorization_context_identity_sha256="f" * 64,
        store_root=store,
    )
    assert receipt["executable_signed_approval"] is False
    assert receipt["usage_status"] == "unused"
    assert list(store.glob("*.permission.json"))
    assert not list(store.rglob("*.nonce.json"))
    with pytest.raises(campaign.SkillV3OvernightCampaignError, match="CAMPAIGN_PERMISSION_TEXT_MISMATCH"):
        campaign.create_campaign_permission_receipt_v1(
            repo_root=repo,
            authorization_message=exact + " changed",
            authorization_context_identity_sha256="f" * 64,
            store_root=tmp_path / "other",
        )


def test_campaign_source_has_no_prompt_or_response_persistence() -> None:
    source = Path(campaign.__file__).read_text(encoding="utf-8")
    assert "raw_ref_corpus_egress\": False" in source
    assert "prior_sample_prose_egress\": False" in source
    assert "prior_sample_result_egress\": False" in source
    assert "authorization_message\": authorization_message" not in source
    assert "raw_provider_content" not in source


def test_phase_a_materializer_emits_required_hash_bound_evidence(tmp_path: Path) -> None:
    result = materializer.materialize(
        repo_root=ROOT,
        output_root=tmp_path / "evidence",
        focused="6 passed",
        related="106 passed",
        full_suite="PASS",
        strict_l3="PASS",
    )
    assert result["status"] == "EXACT"
    root = Path(result["root"])
    assert all((root / name).is_file() for name in materializer.REQUIRED_FILES)
    manifest = result["manifest"]
    assert manifest["entry_count"] == len(list(root.iterdir())) - 1
    privacy = json.loads((root / "privacy-scan-phase-a-v1.json").read_text(encoding="utf-8"))
    assert privacy["status"] == "PASS"
    assert privacy["total_matches"] == 0
