from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from novel_flywheel.db import Database
from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
from tools.canary.descriptors import production_route_identity
import tools.canary.slice1_phase_b_current_skill as base
import tools.canary.slice1_phase_b_single_dispatch as guarded


@pytest.fixture
def repo_root() -> Path:
    return Path.cwd().resolve()


def test_transport_guard_is_source_bound_and_exact(repo_root: Path) -> None:
    first = guarded.transport_guard_contract(repo_root)
    second = guarded.transport_guard_contract(repo_root)

    assert first == second
    assert first["policy"] == SingleDispatchTransportPolicyV1.phase_b().definition()
    assert first["max_http_post_attempts"] == 1
    assert first["max_real_provider_request_attempts"] == 1
    assert first["sdk_retries_disabled_for_phase_b"] is True
    assert first["transport_request_retries_disabled_for_phase_b"] is True
    assert first["application_second_dispatch_allowed"] is False
    assert first["route_fallback_after_dispatch_allowed"] is False
    assert first["normal_production_transport_retry_policy_changed"] is False
    assert all(first["mechanical_checks"].values())


def test_attempt_accounting_enforces_before_second_attempt(repo_root: Path) -> None:
    guard = guarded.transport_guard_contract(repo_root)
    accounting = guarded.attempt_accounting_contract(guard)

    assert accounting["hard_max_model_logical_calls"] == 1
    assert accounting["hard_max_real_provider_request_attempts"] == 1
    assert accounting["hard_max_http_post_attempts"] == 1
    assert accounting["hard_max_network_request_attempts"] == 1
    assert accounting["post_hoc_count_only"] is False
    assert "_before_http_post_attempt" in accounting["enforcement_boundary"]


def test_invalid_single_dispatch_policy_fails_closed() -> None:
    with pytest.raises(ValueError, match="single_dispatch_transport_policy_invalid"):
        SingleDispatchTransportPolicyV1(max_http_post_attempts=2)
    with pytest.raises(ValueError, match="single_dispatch_transport_policy_invalid"):
        SingleDispatchTransportPolicyV1(sdk_retries_disabled=False)


def _template(repo_root: Path) -> dict:
    guard = guarded.transport_guard_contract(repo_root)
    return {
        "execution_authorized": False,
        "named_approver": None,
        "usage_status": "unused",
        "reservation_status": "unreserved",
        "bound_hashes": {
            "materialization_head": "a" * 40,
            "transport_guard_sha256": guard["transport_guard_sha256"],
            "model_input_assembly_sha256": "b" * 64,
        },
    }


def _signed(template: dict) -> dict:
    return {
        "schema": "Slice1PhaseBSingleDispatchSignedApprovalV1",
        "execution_authorized": True,
        "named_approver": "final_user",
        "single_use_nonce": "fresh-single-use-nonce",
        "approval_scope": guarded.APPROVAL_SCOPE,
        "cohort_id": guarded.COHORT_ID,
        "bound_hashes": template["bound_hashes"],
        "full_short_authorized": False,
        "skill_v2_authorized": False,
        "draft_authorized": False,
        "execution_window": {
            "not_before": "2026-08-23T00:00:00Z",
            "not_after": "2026-08-24T00:00:00Z",
        },
    }


def test_guard_mismatch_rejects_before_nonce_reservation(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = _template(repo_root)
    signed = _signed(template)
    monkeypatch.setattr(
        guarded, "validate_materialized_packet",
        lambda *_args, **_kwargs: {"status": "exact", "approval": template},
    )
    monkeypatch.setattr(
        guarded, "verify_execution_head_successor",
        lambda *_args, **_kwargs: {"status": "exact"},
    )
    changed = guarded.transport_guard_contract(repo_root)
    changed["transport_guard_sha256"] = "f" * 64
    monkeypatch.setattr(guarded, "transport_guard_contract", lambda _root: changed)
    monkeypatch.setenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1")

    with pytest.raises(guarded.Slice1PhaseBSingleDispatchError) as caught:
        guarded.validate_signed_launch(
            repo_root=repo_root,
            packet_root=tmp_path / "packet",
            signed_approval=signed,
            run_root=tmp_path / "run",
            now=datetime(2026, 8, 23, 1, tzinfo=timezone.utc),
        )

    assert caught.value.reason_code == "transport_guard_binding_mismatch"
    assert not (tmp_path / "run").exists()


def test_old_approval_is_rejected_before_external_action(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = _template(repo_root)
    signed = _signed(template)
    signed["schema"] = "Slice1PhaseBCurrentSkillSignedApprovalV1"
    signed["approval_scope"] = "SLICE1_PHASE_B_CURRENT_SKILL_BASELINE_ONLY"
    signed["cohort_id"] = guarded.PREVIOUS_APPROVAL_COHORT
    monkeypatch.setattr(
        guarded, "validate_materialized_packet",
        lambda *_args, **_kwargs: {"status": "exact", "approval": template},
    )

    with pytest.raises(guarded.Slice1PhaseBSingleDispatchError) as caught:
        guarded.validate_signed_launch(
            repo_root=repo_root,
            packet_root=tmp_path / "packet",
            signed_approval=signed,
            run_root=tmp_path / "run",
            now=datetime(2026, 8, 23, 1, tzinfo=timezone.utc),
        )

    assert caught.value.reason_code == "signed_approval_schema_mismatch"
    assert not (tmp_path / "run").exists()


def test_credential_capable_imports_follow_guarded_signed_preflight(
    repo_root: Path,
) -> None:
    source = (
        repo_root / "tools/canary/slice1_phase_b_single_dispatch.py"
    ).read_text(encoding="utf-8")
    gate = source.index("gate = validate_signed_launch(")
    reservation = source.index('with reservation.open("x"')
    credential = source.index(
        "from novel_flywheel.secrets import KeyringSecretStore",
    )
    provider = source.index(
        "from novel_flywheel.providers.registry import ProviderRegistry",
    )
    dispatch = source.index("gateway.complete_route(")

    assert gate < reservation < credential < dispatch
    assert gate < reservation < provider < dispatch


def test_materializer_cannot_call_execute_path(repo_root: Path) -> None:
    source = (
        repo_root / "tools/canary/slice1_phase_b_single_dispatch.py"
    ).read_text(encoding="utf-8")
    materializer = source[
        source.index("def materialize_packet("):
        source.index("def validate_materialized_packet(")
    ]
    assert "execute_authorized_once" not in materializer
    assert "KeyringSecretStore" not in materializer
    assert "ProviderRegistry" not in materializer


def _skill_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    for name in (
        "story-init", "plot-structure", "character-management", "worldbuilding",
    ):
        path = root / name
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: test\n---\n# {name}\n必须 preserve\n",
            encoding="utf-8",
        )
    return root


def _route_db(tmp_path: Path) -> tuple[Path, dict[str, dict[str, str]]]:
    path = tmp_path / "app.db"
    db = Database(path)
    db.migrate()
    for suffix in ("primary", "fallback"):
        db.save_provider(
            provider_id=f"provider-{suffix}", name=f"provider-{suffix}",
            protocol="anthropic",
            base_url=f"https://{suffix}.example.invalid",
            auth_type="bearer", timeout_seconds=30, extra_headers={}, enabled=True,
        )
        db.save_model(
            model_id=f"model-{suffix}", provider_id=f"provider-{suffix}",
            display_name=f"model-{suffix}", model_name=f"model-{suffix}",
            capabilities={"structured_output": "plain_text"},
        )
    db.save_role_binding(
        "planning", "provider-primary", "model-primary",
        "provider-fallback", "model-fallback",
    )
    expected = {}
    for kind, selector, provider_id, model_id in (
        ("primary", "primary", "provider-primary", "model-primary"),
        ("configured_fallback", "fallback", "provider-fallback", "model-fallback"),
    ):
        descriptor = production_route_identity(db, "planning", selector)
        expected[kind] = {
            "provider_descriptor_hash": descriptor["provider_descriptor_hash"],
            "model_binding_hash": descriptor["model_binding_hash"],
            "route_fingerprint": base._route_fingerprint(
                db.get_provider(provider_id), db.get_model(model_id),
            ),
        }
    return path, expected


def test_fresh_packet_documents_are_deterministic_disabled_and_guard_bound(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    route_db, expected = _route_db(tmp_path)
    skill_root = _skill_root(tmp_path)
    monkeypatch.setattr(
        base, "verify_git_gate",
        lambda *_args, **_kwargs: {
            "branch": guarded.EXPECTED_BRANCH,
            "head": "c" * 40,
            "worktree": "clean",
        },
    )
    kwargs = {
        "repo_root": repo_root,
        "route_database": route_db,
        "expected_routes": expected,
        "skill_roots": [skill_root],
        "validation_summary": {
            "focused": "24 passed",
            "preflight": "exact",
            "related": "70 passed",
            "full_suite": "not-run-in-unit",
            "strict_l3": "pending",
            "ptr12": "exact",
            "r0f": "exact",
            "production_retry_parity": "pass",
        },
    }
    first, meta_a = guarded.build_packet_documents(**kwargs)
    second, meta_b = guarded.build_packet_documents(**kwargs)

    assert first == second
    assert meta_a == meta_b
    approval = __import__("json").loads(
        first["phase-b-current-skill-approval-template-v1.json"],
    )
    budget = __import__("json").loads(
        first["phase-b-current-skill-budget-v1.json"],
    )
    assert approval["execution_authorized"] is False
    assert approval["named_approver"] is None
    assert approval["usage_status"] == "unused"
    assert approval["reservation_status"] == "unreserved"
    assert approval["signed_approval"] == "ABSENT"
    assert approval["cohort_id"] == guarded.COHORT_ID
    assert budget["hard_max_model_calls"] == 1
    assert budget["hard_max_real_provider_request_attempts"] == 1
    assert budget["hard_max_http_post_attempts"] == 1
    assert budget["hard_max_output_tokens_per_call"] == 4624
    assert meta_a["privacy"]["materialization_privacy_match_count"] == 0
    assert all(value == 0 for value in approval["external_actions"].values())
