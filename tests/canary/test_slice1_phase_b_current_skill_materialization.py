from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from novel_flywheel.db import Database
from tools.canary.descriptors import production_route_identity
import tools.canary.slice1_phase_b_current_skill as phase_b


@pytest.fixture
def repo_root() -> Path:
    return Path.cwd().resolve()


def _write_skill(root: Path, name: str, body: str) -> None:
    target = root / name
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test\n---\n# {name}\n必须 {body}\n",
        encoding="utf-8",
    )


def _skill_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    for name in ("story-init", "plot-structure", "character-management", "worldbuilding"):
        _write_skill(root, name, f"preserve {name}")
    return root


def _route_db(tmp_path: Path) -> tuple[Path, dict[str, dict[str, str]]]:
    path = tmp_path / "app.db"
    db = Database(path)
    db.migrate()
    for suffix, protocol, structured in (
        ("primary", "anthropic", "strict_tool"),
        ("fallback", "anthropic", "plain_text"),
    ):
        db.save_provider(
            provider_id=f"provider-{suffix}", name=f"provider-{suffix}",
            protocol=protocol, base_url=f"https://{suffix}.example.invalid",
            auth_type="bearer", enabled=True, timeout_seconds=30,
            extra_headers={},
        )
        db.save_model(
            model_id=f"model-{suffix}", provider_id=f"provider-{suffix}",
            display_name=f"model-{suffix}", model_name=f"model-{suffix}",
            capabilities={"structured_output": structured},
        )
    db.save_role_binding(
        "planning", "provider-primary", "model-primary",
        "provider-fallback", "model-fallback",
    )
    expected: dict[str, dict[str, str]] = {}
    for kind, selector, provider_id, model_id in (
        ("primary", "primary", "provider-primary", "model-primary"),
        ("configured_fallback", "fallback", "provider-fallback", "model-fallback"),
    ):
        descriptor = production_route_identity(db, "planning", selector)
        expected[kind] = {
            "provider_descriptor_hash": descriptor["provider_descriptor_hash"],
            "model_binding_hash": descriptor["model_binding_hash"],
            "route_fingerprint": phase_b._route_fingerprint(
                db.get_provider(provider_id), db.get_model(model_id),
            ),
        }
    return path, expected


def test_ptr12_final_manifest_and_decision_are_exact(repo_root: Path) -> None:
    result = phase_b.verify_ptr12_final(repo_root)
    assert result["status"] == "exact"
    assert result["completed_shards"] == 3
    assert result["phase_b_ready"] is True


def test_current_skill_resolution_is_stable_across_two_runs(
    repo_root: Path, tmp_path: Path,
) -> None:
    root = _skill_root(tmp_path)
    profile, compacted = phase_b.verify_skill_resolution_twice(
        repo_root, roots=[root],
    )
    assert profile["resolution_run_count"] == 2
    assert profile["resolution_deterministic"] is True
    assert [item["skill_name"] for item in profile["resolved_skills"]] == [
        "story-init", "plot-structure", "character-management", "worldbuilding",
    ]
    assert profile["skill_v2_profile_active"] is False
    assert profile["planning_skill_profile_shadow_v1"] == "NOT_USED_FOR_MODEL_INPUT"
    assert hashlib.sha256(compacted.encode()).hexdigest() == (
        profile["combined_current_runtime_compacted_prompt_sha256"]
    )


def test_changed_skill_content_changes_profile(repo_root: Path, tmp_path: Path) -> None:
    root = _skill_root(tmp_path)
    first, _ = phase_b.verify_skill_resolution_twice(repo_root, roots=[root])
    path = root / "plot-structure" / "SKILL.md"
    path.write_text(path.read_text(encoding="utf-8") + "不得漂移\n", encoding="utf-8")
    second, _ = phase_b.verify_skill_resolution_twice(repo_root, roots=[root])
    assert first["profile_sha256"] != second["profile_sha256"]


def test_fixture_and_authority_are_repo_owned_and_deterministic(repo_root: Path) -> None:
    first, authority_a = phase_b.load_fixture_binding(repo_root)
    second, authority_b = phase_b.load_fixture_binding(repo_root)
    assert first == second
    assert authority_a == authority_b
    assert first["case_ids"] == ["valid-canonical"]
    assert first["repository_owned_sanitized_fixture"] is True
    assert first["live_database_dependency"] is False
    assert first["private_user_data"] is False


def test_slice1_contract_ownership_and_protected_authority(repo_root: Path) -> None:
    contract = phase_b.slice1_contract_binding(repo_root)
    assert contract["candidate_owned_fields"] == ["/title", "/narrative"]
    assert contract["candidate_owned_field_count"] == 2
    assert contract["authority_copy_field_count"] == 4
    assert contract["runtime_local_deterministic_field_count"] == 20
    assert contract["artifact_field_count"] == 26
    assert contract["planning_v1_production_authority"] is True
    assert contract["draft_entry_allowed"] is False


def test_route_binding_is_hash_only_stable_and_unchanged(tmp_path: Path) -> None:
    database, expected = _route_db(tmp_path)
    first = phase_b.resolve_route_binding(database, expected_routes=expected)
    second = phase_b.resolve_route_binding(database, expected_routes=expected)
    assert first == second
    assert first["selected_route"] == "primary"
    assert first["configured_route_order"] == ["primary", "configured_fallback"]
    assert first["route_model_changed"] is False
    assert first["fallback_policy_changed"] is False
    serialized = json.dumps(first)
    assert "example.invalid" not in serialized
    assert "provider-primary" not in serialized
    assert "model-primary" not in serialized


def test_route_or_model_change_invalidates_binding(tmp_path: Path) -> None:
    database, expected = _route_db(tmp_path)
    db = Database(database)
    model = db.get_model("model-primary")
    db.save_model(
        model_id="model-primary", provider_id="provider-primary",
        display_name=model["display_name"], model_name="changed-model",
        capabilities=model["capabilities"],
    )
    with pytest.raises(phase_b.Slice1PhaseBMaterializationError) as error:
        phase_b.resolve_route_binding(database, expected_routes=expected)
    assert error.value.reason_code in {
        "route_model_descriptor_mismatch", "route_fingerprint_mismatch",
    }


def _core_contracts(repo_root: Path, tmp_path: Path):
    skill_root = _skill_root(tmp_path)
    profile, compacted = phase_b.verify_skill_resolution_twice(
        repo_root, roots=[skill_root],
    )
    workload, authority = phase_b.load_fixture_binding(repo_root)
    contract = phase_b.slice1_contract_binding(repo_root)
    database, expected = _route_db(tmp_path)
    route = phase_b.resolve_route_binding(database, expected_routes=expected)
    model_input, _, _ = phase_b.build_model_input(
        repo_root, authority, compacted, profile, contract, route,
    )
    budget = phase_b.budget_contract(route, model_input)
    return workload, profile, contract, route, model_input, budget


def test_model_input_and_budget_are_deterministic_and_bounded(
    repo_root: Path, tmp_path: Path,
) -> None:
    values = _core_contracts(repo_root, tmp_path)
    model_input, budget = values[-2:]
    assert model_input["observer_state"] == "PTR12_REQUIRED_ENABLED"
    assert model_input["raw_prompt_persisted"] is False
    assert model_input["estimated_input_tokens"] <= budget["hard_max_input_tokens"]
    assert budget["hard_max_model_calls"] == 1
    assert budget["hard_max_output_tokens_per_call"] == 4624
    assert budget["hard_max_elapsed_seconds"] == 900


def test_call_graph_has_one_dispatch_and_no_repairs() -> None:
    graph = phase_b.call_graph_contract()
    assert graph["initial_creative_call_count"] == 1
    assert graph["hard_max_model_calls"] == 1
    assert graph["max_repair_calls_per_case"] == 0
    assert graph["whole_planning_regeneration_allowed"] is False
    assert graph["unbounded_retry_allowed"] is False
    assert graph["duplicate_dispatch_allowed"] is False


def test_output_isolation_and_ab_lock(repo_root: Path, tmp_path: Path) -> None:
    workload, _profile, contract, route, _input, budget = _core_contracts(
        repo_root, tmp_path,
    )
    output = phase_b.output_isolation_contract()
    quality = phase_b.quality_capture_contract()
    lock = phase_b.ab_lock_contract(workload, contract, route, budget, output, quality)
    assert output["production_database_mutation_allowed"] is False
    assert output["story_state_mutation_allowed"] is False
    assert output["canon_mutation_allowed"] is False
    assert output["draft_input_mutation_allowed"] is False
    assert output["ptr12_raw_prose_allowed"] is False
    assert lock["primary_intended_changed_variable"] == "SKILL_CONTEXT_ARM"
    assert lock["confounded_if_any_other_binding_changes"] is True


def test_disabled_approval_is_inert(repo_root: Path, tmp_path: Path) -> None:
    workload, profile, contract, route, model_input, budget = _core_contracts(
        repo_root, tmp_path,
    )
    output = phase_b.output_isolation_contract()
    quality = phase_b.quality_capture_contract()
    ab = phase_b.ab_lock_contract(workload, contract, route, budget, output, quality)
    bound = {
        "materialization_head": "a" * 40,
        "plan_sha256": "a" * 64,
        "workload_sha256": workload["workload_sha256"],
        "authority_input_sha256": workload["authority_input_sha256"],
        "current_skill_profile_sha256": profile["profile_sha256"],
        "model_input_assembly_sha256": model_input["model_input_assembly_sha256"],
        "route_binding_sha256": route["route_binding_sha256"],
        "budget_sha256": budget["budget_sha256"],
        "ptr12_manifest_sha256": "b" * 64,
        "output_isolation_sha256": output["output_isolation_sha256"],
        "call_graph_sha256": phase_b.call_graph_contract()["call_graph_sha256"],
        "quality_capture_contract_sha256": quality["quality_capture_contract_sha256"],
        "ab_comparison_lock_sha256": ab["ab_comparison_lock_sha256"],
    }
    approval = phase_b.approval_template(bound)
    assert approval["execution_authorized"] is False
    assert approval["named_approver"] is None
    assert approval["usage_status"] == "unused"
    assert approval["reservation_status"] == "unreserved"
    assert approval["full_short_authorized"] is False
    assert approval["skill_v2_authorized"] is False
    assert approval["draft_authorized"] is False
    assert all(value == 0 for value in approval["external_actions"].values())


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("execution_authorized", False, "execution_not_authorized"),
        ("named_approver", None, "named_approver_missing"),
        ("single_use_nonce", None, "single_use_nonce_missing"),
        ("full_short_authorized", True, "full_short_authorization_forbidden"),
        ("skill_v2_authorized", True, "skill_v2_authorization_forbidden"),
        ("draft_authorized", True, "draft_authorization_forbidden"),
    ],
)
def test_signed_launch_fail_closed_before_any_external_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    field: str, value: object, reason: str,
) -> None:
    packet_root = tmp_path / "packet"
    packet_root.mkdir()
    template = {
        "schema": "Slice1PhaseBCurrentSkillApprovalTemplateV1",
        "execution_authorized": False, "named_approver": None,
        "usage_status": "unused", "reservation_status": "unreserved",
        "bound_hashes": {"materialization_head": "a" * 40,
                          "current_skill_profile_sha256": "b" * 64},
    }
    monkeypatch.setattr(
        phase_b, "validate_materialized_packet",
        lambda *_args, **_kwargs: {"status": "exact", "approval": template},
    )
    signed = {
        "schema": "Slice1PhaseBCurrentSkillSignedApprovalV1",
        "execution_authorized": True,
        "named_approver": "final_user",
        "single_use_nonce": "nonce",
        "approval_scope": phase_b.APPROVAL_SCOPE,
        "cohort_id": phase_b.COHORT_ID,
        "bound_hashes": template["bound_hashes"],
        "full_short_authorized": False,
        "skill_v2_authorized": False,
        "draft_authorized": False,
        "execution_window": {
            "not_before": "2026-08-23T00:00:00Z",
            "not_after": "2026-08-24T00:00:00Z",
        },
    }
    signed[field] = value
    with pytest.raises(phase_b.Slice1PhaseBMaterializationError) as error:
        phase_b.validate_signed_launch(
            repo_root=tmp_path, packet_root=packet_root,
            signed_approval=signed, run_root=tmp_path / "run",
            now=datetime(2026, 8, 23, 1, tzinfo=timezone.utc),
        )
    assert error.value.reason_code == reason
    assert not (tmp_path / "run").exists()
    assert all(value == 0 for value in phase_b.ZERO_COUNTERS.values())


def test_credential_capable_imports_are_below_complete_gate(repo_root: Path) -> None:
    source = (repo_root / "tools/canary/slice1_phase_b_current_skill.py").read_text(
        encoding="utf-8",
    )
    gate = source.index("gate = validate_signed_launch(")
    credential = source.index("from novel_flywheel.secrets import KeyringSecretStore")
    provider = source.index("from novel_flywheel.providers.registry import ProviderRegistry")
    assert gate < credential
    assert gate < provider


def test_execution_head_accepts_only_evidence_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        phase_b, "verify_git_gate",
        lambda *_args, **_kwargs: {
            "branch": phase_b.EXPECTED_BRANCH, "head": "b" * 40,
            "worktree": "clean",
        },
    )
    monkeypatch.setattr(
        phase_b, "_git",
        lambda _root, *args: (
            "" if args[:2] == ("merge-base", "--is-ancestor")
            else phase_b.REPORT_RELATIVE_ROOT + "/sha256-manifest-v1.json"
        ),
    )
    result = phase_b.verify_execution_head_successor(tmp_path, "a" * 40)
    assert result["evidence_only_successor"] is True

    monkeypatch.setattr(
        phase_b, "_git",
        lambda _root, *args: (
            "" if args[:2] == ("merge-base", "--is-ancestor")
            else "src/novel_flywheel/workflows.py"
        ),
    )
    with pytest.raises(phase_b.Slice1PhaseBMaterializationError) as error:
        phase_b.verify_execution_head_successor(tmp_path, "a" * 40)
    assert error.value.reason_code == (
        "materialization_head_successor_contains_non_evidence_change"
    )


def test_materialization_privacy_scan_rejects_private_absolute_paths() -> None:
    safe = phase_b._privacy_scan({"safe.json": b'{"hash":"' + b"a" * 64 + b'"}'})
    bad = phase_b._privacy_scan({"bad.json": b'{"path":"C:/Users/private/file"}'})
    assert safe["overall_status"] == "exact"
    assert safe["materialization_privacy_match_count"] == 0
    assert bad["overall_status"] == "blocked"


def test_no_materialization_function_calls_execute_path(repo_root: Path) -> None:
    source = (repo_root / "tools/canary/slice1_phase_b_current_skill.py").read_text(
        encoding="utf-8",
    )
    materializer = source[source.index("def materialize_packet("):
                          source.index("def validate_materialized_packet(")]
    assert "execute_authorized_once" not in materializer
    assert "KeyringSecretStore" not in materializer
    assert "ProviderRegistry" not in materializer
