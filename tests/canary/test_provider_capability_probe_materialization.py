from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from tools.canary.artifact_hash import live_parity_manifest
from tools.canary.provider_capability_probe_materialization import (
    EXPECTED_PTR4_CANONICAL_SHA256,
    EXPECTED_PTR4_V1_CANONICAL_SHA256,
    ProviderCapabilityProbeMaterializationError,
    materialize_provider_capability_probe_packet,
    verify_probe_materialization_parent_gate,
    verify_sha_manifest_exact,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_DATABASE = REPO_ROOT / "data/app.db"
LIVE_PROJECTS = REPO_ROOT / "data/projects"
NOW = datetime(2026, 8, 20, 11, 7, 21, tzinfo=timezone.utc)
COHORT = "r1-ptr4-probe-20260820t110721z-001"
SOURCE_HEAD = "f7f67095a72ede2bce62a583fac1cf43fb620e80"


@pytest.fixture(scope="module")
def packet(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("ptr4-probe-mat") / COHORT
    parity_before = live_parity_manifest(
        database_path=LIVE_DATABASE, project_root=LIVE_PROJECTS,
    )
    result = materialize_provider_capability_probe_packet(
        repo_root=REPO_ROOT,
        live_database_path=LIVE_DATABASE,
        live_project_root=LIVE_PROJECTS,
        output_root=root / "materialization-v1",
        ledger_root=root / "ledger",
        canary_root=root / "canary-root",
        artifact_root_label=(
            "docs/superpowers/reports/r1-ptr4-probe-mat/" + COHORT
        ),
        cohort_id=COHORT,
        run_namespace=COHORT,
        branch="r1-ptr3/planning-repair-finding-propagation-20260817",
        source_head=SOURCE_HEAD,
        now=NOW,
    )
    parity_after = live_parity_manifest(
        database_path=LIVE_DATABASE, project_root=LIVE_PROJECTS,
    )
    assert parity_before["parity_sha256"] == parity_after["parity_sha256"]
    return result


def test_parent_evidence_gate_is_exact():
    parent = verify_probe_materialization_parent_gate(REPO_ROOT)
    assert parent["status"] == "exact"
    assert parent["ptr4"]["canonical_sha256"] == (
        EXPECTED_PTR4_CANONICAL_SHA256
    )
    assert parent["ptr4_v1"]["canonical_sha256"] == (
        EXPECTED_PTR4_V1_CANONICAL_SHA256
    )
    assert parent["privacy_violation_count"] == 0


def test_candidate_is_disabled_unused_and_unreserved(packet):
    candidate = packet["candidate"]
    assert candidate["candidate_status"] == "disabled"
    assert candidate["execution_authorized"] is False
    assert candidate["usage_status"] == "unused"
    assert candidate["reservation_status"] == "unreserved"
    assert candidate["signed_approval_materialized"] is False
    assert candidate["confirmed_patch_materialized"] is False
    assert candidate["execution_performed"] is False
    for field in (
        "authorize_credential_lookup",
        "authorize_provider_client_creation",
        "authorize_network",
        "authorize_model_call",
        "authorize_paid_model_call",
    ):
        assert candidate[field] is False


def test_formal_probe_budget_applies_stricter_one_call_limit(packet):
    budget = packet["budget_definition"]
    assert budget["maximum_runs"] == 1
    assert budget["expected_model_calls"] == 1
    assert budget["maximum_total_model_calls"] == 1
    assert budget["maximum_output_tokens_per_call"] == 8798
    assert budget["maximum_input_tokens"] == 128000
    assert budget["maximum_output_tokens"] == 8798
    assert budget["maximum_usd_cost"] == 5
    assert budget["maximum_cny_cost"] == 10
    assert budget["maximum_elapsed_seconds"] == 1800
    assert budget["first_terminal_stop"] is True
    assert budget["resume_after_terminal"] is False
    assert budget["second_run_allowed"] is False


def test_boundary_12_target_and_fixture_are_exactly_bound(packet):
    target = packet["target_definition"]["target"]
    fixture = packet["fixture_definition"]["source_fixture"]
    assert target["boundary"] == 12
    assert target["route_kind"] == "configured_fallback"
    assert target["protocol"] == "anthropic"
    assert target["execution_mode"] == "plain"
    assert target["requested_max_output_tokens"] == 8798
    assert target["identity_sha256"] == (
        "851b447afba31d2296ebafc223ea4189464920e332693a5a03d5cf0b821675f0"
    )
    assert fixture["fixture_sha256"] == (
        "22ac37e6494de79f542596cd16d5c14b8b25229af5cc1f451957e101b1c87e64"
    )
    assert fixture["target_boundary_identity_sha256"] == target["identity_sha256"]
    assert fixture["input_content_embedded"] is False


def test_observer_and_lineage_bind_every_required_identity(packet):
    observer = packet["observer_bundle"]
    lineage = packet["lineage_definition"]
    assert observer["observation_schema_sha256"] == (
        "d88652767f2d5fe72fce529cdc51c51e7897daa9b16fd869092aa20b30d7dfa3"
    )
    assert observer["raw_content_allowed"] is False
    assert len(observer["classifications"]) == 10
    for field in (
        "adapter_identity_sha256",
        "parser_identity_sha256",
        "strict_tool_identity_sha256",
        "output_limit_observer_identity_sha256",
    ):
        assert len(lineage[field]) == 64
    assert lineage["lineage_receipt_required"] is True


def test_validate_only_receipt_is_exact(packet):
    receipt = packet["validate_only_receipt"]
    assert receipt["overall_status"] == "exact"
    assert all(item["status"] == "exact" for item in receipt["ordered_checks"])
    assert receipt["approval_state"] == "disabled_candidate"
    assert receipt["approval_reservation_status"] == "unreserved"
    assert receipt["cohort_usage_status"] == "unused"
    assert receipt["ledger_entry_count"] == 0
    assert receipt["execution_performed"] is False


def test_ledger_canary_root_and_cohort_are_unused(packet):
    assert packet["ledger"]["entry_count"] == 0
    assert packet["ledger"]["entries"] == []
    assert packet["ledger"]["reservation_status"] == "unreserved"
    assert packet["canary_root"]["status"] == "unused"
    assert packet["canary_root"]["entry_count"] == 0
    assert packet["cohort"]["usage_status"] == "unused"


def test_patch_and_execution_preview_are_inert(packet):
    patch = packet["patch_template"]
    preview = packet["execution_preview"]
    assert patch["template_status"] == "unconfirmed"
    assert patch["execution_authorized"] is False
    assert patch["confirmed_patch_materialized"] is False
    assert preview["candidate_is_executable"] is False
    assert preview["execution_authorized"] is False
    assert preview["do_not_execute"] is True
    assert preview["future_command"] == "ABSENT_UNTIL_SIGNED_APPROVAL"


def test_fake_rehearsal_is_not_provider_capability_evidence(packet):
    rehearsal = packet["prelaunch_rehearsal"]
    assert rehearsal["status"] == "exact"
    assert rehearsal["provider_capability_evidence_status"] == (
        "fake_rehearsal_only"
    )
    assert rehearsal["observer_receipt_generated"] is True
    assert rehearsal["goal_stop_verified"] is True
    assert rehearsal["control_plane_binding_verified"] is True
    assert rehearsal["real_provider_probe"] == "NOT_EXECUTED"


def test_privacy_and_external_actions_are_zero(packet):
    privacy = packet["privacy"]
    assert privacy["status"] == "exact"
    assert privacy["violation_count"] == 0
    assert all(value == 0 for value in packet["external_action_counters"].values())
    fixture = json.loads((
        REPO_ROOT / "tests/fixtures/canary/short-normal-v1.json"
    ).read_text(encoding="utf-8"))
    serialized = json.dumps(packet["index"], ensure_ascii=False)
    for field in ("title", "premise", "outline"):
        assert fixture[field] not in serialized


def test_materialization_index_binds_every_written_file(packet):
    index = packet["index"]
    assert index["contract_status"] == (
        "R1_PTR4_PROVIDER_CAPABILITY_PROBE_APPROVAL_PACKET_READY"
    )
    assert index["status"] == (
        "R1_PTR4_PROVIDER_CAPABILITY_PROBE_WAITING_FOR_FINAL_USER_AUTHORIZATION"
    )
    assert index["ledger_entry_count"] == 0
    assert index["signed_approval_materialized"] is False
    assert index["confirmed_patch_materialized"] is False
    assert index["real_provider_probe"] == "NOT_EXECUTED"
    for relative, expected in index["files"].items():
        path = packet["paths"]["index"].parent.parent / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_signed_approval_and_confirmed_patch_files_are_absent(packet):
    cohort_root = packet["paths"]["index"].parent.parent
    names = {path.name.casefold() for path in cohort_root.rglob("*") if path.is_file()}
    assert not any("signed-approval" in name for name in names)
    assert not any("confirmed" in name and "patch" in name for name in names)


def test_repository_materialization_matches_builder_exactly(packet):
    generated_root = packet["paths"]["index"].parent.parent
    repository_root = (
        REPO_ROOT / "docs/superpowers/reports/r1-ptr4-probe-mat" / COHORT
    )
    generated_files = sorted(
        path.relative_to(generated_root) for path in generated_root.rglob("*")
        if path.is_file()
    )
    repository_files = sorted(
        path.relative_to(repository_root) for path in repository_root.rglob("*")
        if path.is_file()
        and path.relative_to(repository_root).parts[0] in {
            "materialization-v1", "ledger", "canary-root",
        }
    )
    assert repository_files == generated_files
    for relative in generated_files:
        assert (repository_root / relative).read_bytes() == (
            generated_root / relative
        ).read_bytes()


def test_materializer_refuses_reuse(packet):
    cohort_root = packet["paths"]["index"].parent.parent
    with pytest.raises(
        ProviderCapabilityProbeMaterializationError,
        match="materialization_target_not_empty",
    ):
        materialize_provider_capability_probe_packet(
            repo_root=REPO_ROOT,
            live_database_path=LIVE_DATABASE,
            live_project_root=LIVE_PROJECTS,
            output_root=cohort_root / "materialization-v1",
            ledger_root=cohort_root / "ledger",
            canary_root=cohort_root / "canary-root",
            artifact_root_label="unused",
            cohort_id=COHORT,
            run_namespace=COHORT,
            branch="branch",
            source_head=SOURCE_HEAD,
            now=NOW,
        )


def test_manifest_verifier_fails_closed_on_tamper(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}\n", encoding="utf-8")
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    row = f"evidence.json|{evidence.stat().st_size}|{digest}"
    canonical = hashlib.sha256(row.encode("utf-8")).hexdigest()
    manifest = {
        "files": [{
            "path": "evidence.json",
            "bytes": evidence.stat().st_size,
            "sha256": digest,
        }],
        "evidence_canonical_sha256": canonical,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_sha_manifest_exact(
        tmp_path, Path("manifest.json"), canonical,
    )["status"] == "exact"
    evidence.write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(
        ProviderCapabilityProbeMaterializationError,
        match="R1_PTR4_PROBE_MAT_NO_GO_PARENT_EVIDENCE_CHANGED",
    ):
        verify_sha_manifest_exact(tmp_path, Path("manifest.json"), canonical)
