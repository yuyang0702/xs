from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path

import pytest

from tools.canary.artifact_hash import live_parity_manifest
from tools.canary.provider_reasoning_capability_probe_materialization import (
    ProviderReasoningProbeMaterializationError,
    materialize_provider_reasoning_probe_packet,
    verify_parent_evidence_exact,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 20, 14, 40, 46, tzinfo=timezone.utc)
COHORT = "r1-ptr7-reasoning-probe-20260820t144046z-001"
HEAD = "941b1fbf9a2e9d361098e69baedfaf01c3425f6c"


@pytest.fixture(scope="module")
def packet(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("ptr7-reasoning-probe") / COHORT
    before = live_parity_manifest(
        database_path=REPO_ROOT / "data/app.db",
        project_root=REPO_ROOT / "data/projects",
    )
    result = materialize_provider_reasoning_probe_packet(
        repo_root=REPO_ROOT,
        live_database_path=REPO_ROOT / "data/app.db",
        live_project_root=REPO_ROOT / "data/projects",
        cohort_root=root,
        artifact_root_label=(
            "docs/superpowers/reports/r1-ptr7-reasoning-probe-mat/" + COHORT
        ),
        cohort_id=COHORT,
        branch="r1-ptr3/planning-repair-finding-propagation-20260817",
        source_head=HEAD,
        now=NOW,
    )
    after = live_parity_manifest(
        database_path=REPO_ROOT / "data/app.db",
        project_root=REPO_ROOT / "data/projects",
    )
    assert before["parity_sha256"] == after["parity_sha256"]
    return result


def test_parent_gate_is_exact():
    evidence = verify_parent_evidence_exact(REPO_ROOT)
    assert evidence["status"] == "exact"
    assert len(evidence["manifests"]) == 5


def test_definition_binds_exact_target_and_four_capabilities(packet):
    target = packet["definition"]["target"]
    assert target["route_kind"] == "configured_fallback"
    assert target["protocol"] == "anthropic"
    assert len(target["provider_identity_sha256"]) == 64
    assert len(target["route_identity_sha256"]) == 64
    assert len(target["model_identity_sha256"]) == 64
    assert packet["definition"]["capabilities_under_test"] == [
        "reasoning_budget_cap",
        "final_output_reservation",
        "reasoning_output_token_separation",
        "capability_bound_output_allocation",
    ]


def test_fixture_is_synthetic_non_business_and_hash_bound(packet):
    fixture = packet["fixture"]
    assert fixture["fixture_kind"] == "non_business_deterministic_checksum"
    assert fixture["raw_prompt_embedded"] is False
    assert fixture["raw_story_embedded"] is False
    assert fixture["synthetic_recipe"]["item_count"] == 512
    assert len(fixture["fixture_sha256"]) == 64


def test_observer_is_fail_closed_about_unknown_support(packet):
    rules = packet["observer"]["fields"]["rules"]
    assert "reasoning/final token accounting is not separately exposed" in rules["UNKNOWN"]
    assert packet["observer"]["raw_content_allowed"] is False
    assert set(packet["observer"]["fields"]["classifications"]) == {
        "SUPPORTED", "UNSUPPORTED", "IGNORED", "UNKNOWN",
    }


def test_budget_and_stop_conditions_are_single_use(packet):
    budget = packet["budget"]
    stop = packet["stop_conditions"]
    assert budget["maximum_runs"] == 1
    assert budget["maximum_total_model_calls"] == 1
    assert budget["maximum_input_tokens"] == 128000
    assert budget["maximum_output_tokens"] == 16000
    assert budget["maximum_output_tokens_per_call"] == 16000
    assert budget["maximum_usd_cost"] == 5
    assert budget["maximum_cny_cost"] == 10
    assert budget["maximum_elapsed_seconds"] == 1800
    assert stop["stop_on_first_terminal"] is True
    assert stop["no_retry"] is True
    assert stop["no_resume"] is True
    assert stop["no_second_run"] is True


def test_candidate_patch_ledger_and_canary_root_are_inert(packet):
    candidate = packet["candidate"]
    assert candidate["execution_authorized"] is False
    assert candidate["usage_status"] == "unused"
    assert candidate["reservation_status"] == "unreserved"
    assert candidate["signed_approval_status"] == "ABSENT"
    assert candidate["confirmed_patch_status"] == "ABSENT"
    assert packet["patch_template"]["confirmed_patch_materialized"] is False
    assert packet["ledger"]["entry_count"] == 0
    assert packet["canary_root"]["status"] == "unused"


def test_validate_only_is_exact_and_external_actions_are_zero(packet):
    receipt = packet["validate_only"]
    assert receipt["overall_status"] == "exact"
    assert all(item["status"] == "exact" for item in receipt["ordered_checks"])
    assert all(value == 0 for value in receipt["external_action_counters"].values())
    assert receipt["live_parity_before_sha256"] == receipt["live_parity_after_sha256"]


def test_fake_prelaunch_covers_all_classifications(packet):
    rehearsal = packet["prelaunch"]
    assert rehearsal["status"] == "exact"
    assert {item["classification"] for item in rehearsal["cases"]} == {
        "SUPPORTED", "UNSUPPORTED", "IGNORED", "UNKNOWN",
    }
    assert rehearsal["provider_capability_evidence_status"] == "fake_rehearsal_only"
    assert rehearsal["real_provider_probe"] == "NOT_EXECUTED"


def test_index_binds_every_materialized_file(packet):
    root = packet["index_path"].parent.parent
    index = packet["index"]
    assert index["contract_status"] == (
        "R1_PTR7_PROVIDER_REASONING_CAPABILITY_PROBE_APPROVAL_PACKET_READY"
    )
    assert index["status"] == (
        "R1_PTR7_PROVIDER_REASONING_CAPABILITY_PROBE_WAITING_FOR_FINAL_USER_AUTHORIZATION"
    )
    for relative, expected in index["files"].items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected


def test_signed_approval_and_confirmed_patch_are_absent(packet):
    root = packet["index_path"].parent.parent
    names = {path.name.casefold() for path in root.rglob("*") if path.is_file()}
    assert not any("signed-approval" in name for name in names)
    assert not any("confirmed" in name and "patch" in name for name in names)


def test_repository_materialization_matches_builder_exactly(packet):
    generated_root = packet["index_path"].parent.parent
    repository_root = (
        REPO_ROOT / "docs/superpowers/reports/r1-ptr7-reasoning-probe-mat"
        / COHORT
    )
    owned_roots = {"materialization-v1", "ledger", "canary-root"}
    generated_files = sorted(
        path.relative_to(generated_root) for path in generated_root.rglob("*")
        if path.is_file()
    )
    repository_files = sorted(
        path.relative_to(repository_root) for path in repository_root.rglob("*")
        if path.is_file()
        and path.relative_to(repository_root).parts[0] in owned_roots
    )
    assert repository_files == generated_files
    for relative in generated_files:
        assert (repository_root / relative).read_bytes() == (
            generated_root / relative
        ).read_bytes()


def test_materializer_refuses_reuse(packet):
    with pytest.raises(
        ProviderReasoningProbeMaterializationError,
        match="materialization_target_not_empty",
    ):
        materialize_provider_reasoning_probe_packet(
            repo_root=REPO_ROOT,
            live_database_path=REPO_ROOT / "data/app.db",
            live_project_root=REPO_ROOT / "data/projects",
            cohort_root=packet["index_path"].parent.parent,
            artifact_root_label="unused",
            cohort_id=COHORT,
            branch="branch",
            source_head=HEAD,
            now=NOW,
        )
