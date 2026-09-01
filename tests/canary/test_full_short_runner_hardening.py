from __future__ import annotations

import json
import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.secrets import MemorySecretStore
from novel_flywheel.skills import SkillScanner
from novel_flywheel.story_state import StoryStateStore
from tools.canary import first_trustworthy_full_short_runner as runner


@pytest.mark.asyncio
async def test_disabled_actions_reject_non_offline_factories_before_secret_lookup() -> None:
    called = False

    def secret_factory():
        nonlocal called
        called = True
        raise AssertionError("secret factory must not be called")

    with pytest.raises(
        runner.FullShortExecutionBoundaryError,
        match="DISABLED_EXTERNAL_ACTIONS_REQUIRE_EXPLICIT_OFFLINE_SEAMS",
    ):
        await runner.execute_full_short_control_plane(
            object(), {}, external_actions_enabled=False,
            secret_store_factory=secret_factory,
        )

    assert called is False


def test_runner_machine_code_reaches_exact_failure_taxonomy() -> None:
    metadata = runner._safe_failure_metadata(
        runner.FullShortExecutionBoundaryError(
            "FULL_SHORT_LEDGER_CREATED_AT_INVALID"
        ),
        boundary="full_short.postrun",
    )

    assert metadata["failure_graph"]["code"] == (
        "full_short_ledger_created_at_invalid"
    )
    assert metadata["failure_graph"]["family"] == (
        "authority.postrun_invariant"
    )
    assert metadata["failure_graph"]["dispatch_state"] == "not_reached"


def test_supervised_summary_retains_original_workflow_exception_as_child() -> None:
    root = NameError("offline_missing_name")
    failure = runner._supervised_run_not_completed_failure(
        {"status": "failed", "workflow_failure": {"safe": True}}, root,
    )

    assert failure.reason_code == "FULL_SHORT_SUPERVISED_RUN_NOT_COMPLETED"
    assert failure.__cause__ is root
    assert failure.safe_diagnostic == {
        "status": "failed", "workflow_failure": {"safe": True},
    }
    metadata = runner._safe_failure_metadata(
        failure, boundary="full_short.postrun",
    )
    assert metadata["failure_graph"]["children"][0][
        "source_exception_class"
    ] == "NameError"


@pytest.mark.asyncio
async def test_spoofed_offline_markers_cannot_enter_direct_execution() -> None:
    called = False

    def seam(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("spoofed seam must not be called")

    seam.offline_only = True
    with pytest.raises(
        runner.FullShortExecutionBoundaryError,
        match="DISABLED_EXTERNAL_ACTIONS_REQUIRE_EXPLICIT_OFFLINE_SEAMS",
    ):
        await runner.execute_full_short_control_plane(
            object(), {}, external_actions_enabled=False,
            secret_store_factory=seam,
            registry_factory=seam,
            http_transport_factory=seam,
        )
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_boundary"),
    [
        ("sha", "activated_authorization_sha256_mismatch", "full_short.execution.authorization"),
        ("object", "full_short_authorization_object_drift", "full_short.execution.authorization"),
        ("preflight", "head_drift", "full_short.execution.runtime_binding"),
    ],
)
async def test_direct_execution_preflight_failure_persists_typed_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    failure: str, expected_code: str, expected_boundary: str,
) -> None:
    raw = b"{}"
    args = SimpleNamespace(
        authorization_raw=raw,
        activated_sha256=(
            "0" * 64 if failure == "sha" else hashlib.sha256(raw).hexdigest()
        ),
        store_root=tmp_path / "control-store",
    )
    authorization = {"expected": True}
    if failure == "object":
        monkeypatch.setattr(
            runner, "preflight_full_short_control_plane",
            lambda *_args, **_kwargs: ({"different": True}, {}),
        )
    elif failure == "preflight":
        def reject(*_args, **_kwargs):
            raise runner.FullShortExecutionBoundaryError("HEAD_DRIFT")

        monkeypatch.setattr(
            runner, "preflight_full_short_control_plane", reject,
        )

    with pytest.raises(runner.FullShortExecutionBoundaryError):
        await runner.execute_full_short_control_plane(
            args, authorization, external_actions_enabled=True,
            secret_store_factory=lambda: None,
        )

    paths = list(args.store_root.glob("preflight-failure-*.json"))
    assert len(paths) == 1
    first_raw = paths[0].read_bytes()
    receipt = json.loads(first_raw.decode("utf-8"))
    graph = receipt["failure_graph"]
    assert graph["boundary"] == expected_boundary
    assert graph["code"] == expected_code
    assert graph["source_exception_class"] == (
        "FullShortExecutionBoundaryError"
    )
    assert receipt["approval_created"] is False
    assert receipt["nonce_created"] is False
    assert receipt["credential_lookup_count"] == 0
    assert receipt["network_calls"] == 0
    assert len(receipt["failure_graph_sha256"]) == 64
    assert paths[0].name == (
        "preflight-failure-"
        + receipt["failure_graph_sha256"]
        + ".json"
    )

    with pytest.raises(runner.FullShortExecutionBoundaryError):
        await runner.execute_full_short_control_plane(
            args, authorization, external_actions_enabled=True,
            secret_store_factory=lambda: None,
        )
    assert paths[0].read_bytes() == first_raw


@pytest.mark.asyncio
async def test_explicit_offline_wrapper_uses_private_capability(
    tmp_path: Path,
) -> None:
    raw = b"{}"
    args = SimpleNamespace(
        authorization_raw=raw,
        activated_sha256="0" * 64,
        store_root=tmp_path / "control-store",
    )

    with pytest.raises(
        runner.FullShortExecutionBoundaryError,
        match="ACTIVATED_AUTHORIZATION_SHA256_MISMATCH",
    ):
        await runner._execute_full_short_control_plane_offline(
            args, {}, secret_store=MemorySecretStore(),
            http_transport_factory=lambda *_args, **_kwargs: None,
        )
    assert len(list(args.store_root.glob("preflight-failure-*.json"))) == 1


@pytest.mark.asyncio
async def test_offline_wrapper_rejects_non_memory_secret_before_preflight() -> None:
    with pytest.raises(
        runner.FullShortExecutionBoundaryError,
        match="DISABLED_EXTERNAL_ACTIONS_REQUIRE_EXPLICIT_OFFLINE_SEAMS",
    ):
        await runner._execute_full_short_control_plane_offline(
            object(), {}, secret_store=object(),
            http_transport_factory=lambda *_args, **_kwargs: None,
        )


def test_receipt_sink_failure_cannot_prevent_exact_once_terminalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    class Manager:
        @staticmethod
        def fail_closed_exact_once_reservation(execution_id, *, reason_code):
            calls.append((execution_id, reason_code))
            return True

    monkeypatch.setattr(
        runner, "_persist_preflight_failure",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("receipt media unavailable")
        ),
    )
    original = runner.FullShortExecutionBoundaryError("HEAD_DRIFT")
    runner._terminalize_prelaunch_failure(
        SimpleNamespace(), original,
        boundary="full_short.prelaunch.live_authority_recheck",
        manager=Manager(), execution_id="exact-once-id",
        approval_created=False,
    )

    assert calls[0][0] == "exact-once-id"
    assert calls[0][1].startswith("FULL_SHORT_PRELAUNCH_FAILURE_GRAPH_")
    assert any("OSError" in note for note in original.__notes__)


def test_offline_registry_must_accept_and_attest_exact_transport() -> None:
    supplied_transport = object()
    called = False

    def ignores_transport(_db, _secrets, *, transport_policy, attempt_observer):
        nonlocal called
        called = True
        return object()

    with pytest.raises(
        runner.FullShortExecutionBoundaryError,
        match="OFFLINE_REGISTRY_CANNOT_BIND_HTTP_TRANSPORT",
    ):
        runner._registry_from_factory(
            ignores_transport, db=object(), secret_store=object(),
            observer=object(), http_transport_factory=supplied_transport,
        )
    assert called is False

    def lies_about_transport(_db, _secrets, **_kwargs):
        return SimpleNamespace(transport_factory=object())

    with pytest.raises(
        runner.FullShortExecutionBoundaryError,
        match="OFFLINE_REGISTRY_TRANSPORT_BINDING_NOT_EXACT",
    ):
        runner._registry_from_factory(
            lies_about_transport, db=object(), secret_store=object(),
            observer=object(), http_transport_factory=supplied_transport,
        )


def test_lowest_offline_registry_rejects_network_capable_transport(
    tmp_path: Path,
) -> None:
    from novel_flywheel.providers.http import SingleDispatchTransportPolicyV1
    from tools.canary.first_trustworthy_full_short_dry_run import (
        _LowestHttpSeamRegistry,
    )

    _repo, data, _project_id, db = _bound_project(tmp_path)
    secrets = MemorySecretStore()
    secrets.set("provider", "offline-memory-only")

    class UnsafeFactory:
        @staticmethod
        def build(**_kwargs):
            return httpx.AsyncHTTPTransport(retries=0)

    registry = _LowestHttpSeamRegistry(
        db, secrets, http_transport_factory=UnsafeFactory(),
        transport_policy=SingleDispatchTransportPolicyV1.phase_b(),
    )
    with pytest.raises(ValueError, match="OFFLINE_HTTP_TRANSPORT_NOT_CLOSED"):
        registry.resolve(
            "provider", "model", role="planning", lane="primary",
        )


def _logical_plan() -> list[dict]:
    return [{
        "ordinal": 1,
        "stage_id": "planning",
        "logical_stage_base_id": "planning",
        "logical_stage_id": "planning",
        "role": "planning",
        "route_lane": "primary",
        "contract_name": "unstructured_text",
        "contract_version": 1,
        "contract_schema_sha256": hashlib.sha256(b"{}").hexdigest(),
        "contract_runtime_input_required": False,
        "requested_output_tokens": 128,
    }]


def _bound_project(tmp_path: Path) -> tuple[Path, Path, str, Database]:
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    db = Database(data / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider", name="Provider", protocol="anthropic",
        base_url="https://unit.test/v1", auth_type="x-api-key",
        timeout_seconds=30, extra_headers={},
    )
    db.save_model(
        model_id="model", provider_id="provider", display_name="Model",
        model_name="model", context_window=None, max_output_tokens=None,
    )
    for role in runner.FULL_SHORT_REQUIRED_EXECUTION_ROLES:
        db.save_role_binding(role, "provider", "model", None, None)
    projects = ProjectStore(db, data / "projects")
    project = projects.create(ProjectCreate(
        title="Bound", mode="short", genre="mystery",
        premise="A bound authority is verified.", target_words=13_000,
    ))
    StoryStateStore(db).ensure(project.id, project.path)
    db.set_feature_flag(
        "short_canonical_v2", True,
        scope_type="project", scope_id=project.id,
    )
    for skill in SkillScanner([
        Path.home() / ".codex" / "skills",
    ]).scan():
        if skill.executable:
            db.approve_skill(skill.name, skill.content_hash)
    return repo, data, project.id, db


def test_live_bindings_seal_v2_runtime_skill_style_and_store_source_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data, project_id, _db = _bound_project(tmp_path)
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    store_root = tmp_path / "control-store"
    monkeypatch.setattr(runner, "_git", lambda _repo, *args: (
        "a" * 40 if args == ("rev-parse", "HEAD")
        else "hardening" if args == ("branch", "--show-current")
        else ""
    ))

    actual, public = runner.collect_live_bindings(
        repo=repo, data_dir=data, project_id=project_id,
        run_id="hardening", logical_stage_plan=_logical_plan(),
        store_root=store_root,
    )

    runtime = public["runtime_authority"]
    production = public["production_path_identity"]
    assert runtime["runtime_fingerprint_policy_version"] == "runtime-fingerprint-v2"
    assert runtime["story_state_source_truth"] == "sqlite.story_states.current_revision"
    assert runtime["maintenance_source_state_sha256"]
    assert public["style_reference_authority"]["prose_baseline_state"] == "missing"
    assert "quality_reference_group_version" in public["style_reference_authority"]
    assert production["current_baseline_skill_stage_bytes"]
    assert production["prompt_compactor_configuration"][
        "skill_prompt_compactor_max_characters"
    ] == 9000
    assert production["cutover_source_truth"]["derivation"] == (
        "python_ast_and_constructor_signature"
    )
    assert public["store_root"] == str(store_root.resolve())
    assert actual["store_root_sha256"] == hashlib.sha256(
        str(store_root.resolve()).encode("utf-8")
    ).hexdigest()


def test_live_bindings_reject_missing_ready_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data, project_id, db = _bound_project(tmp_path)
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    db.set_feature_flag(
        "short_canonical_v2", False,
        scope_type="project", scope_id=project_id,
    )
    monkeypatch.setattr(runner, "_git", lambda *_args: "")
    with pytest.raises(ValueError, match="READY authority"):
        runner.collect_live_bindings(
            repo=repo, data_dir=data, project_id=project_id,
            run_id="hardening", logical_stage_plan=_logical_plan(),
            store_root=tmp_path / "control-store",
        )


def test_completion_elapsed_is_rechecked_after_last_dispatch() -> None:
    expired = (
        datetime.now(timezone.utc) - timedelta(seconds=10)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with pytest.raises(RuntimeError, match="EXPIRED_AT_COMPLETION"):
        runner._completion_elapsed_recheck(
            {"maximum_elapsed_seconds": 1}, {"created_at": expired},
        )


def test_dry_run_has_no_test_owned_oracle_or_fixed_call_count() -> None:
    source = (
        Path(runner.__file__).with_name(
            "first_trustworthy_full_short_dry_run.py"
        ).read_text(encoding="utf-8")
    )
    assert "tests.test_" not in source
    assert "expected_stage_calls=1" not in source
    assert "_execute_full_short_control_plane_offline(" in source
    assert "run_full_short_workflow_path(" in source
    assert "expected_calls * 4" not in source
    assert (
        "discovered_plan_total_cap\n"
        "            + planning_recovery_output_token_hard_cap"
        in source
    )


def test_dry_run_failure_projection_is_hash_only() -> None:
    from tools.canary.first_trustworthy_full_short_dry_run import (
        _safe_failure_projection,
    )

    secret = "raw provider body with private story text"
    projection = _safe_failure_projection(
        RuntimeError(secret), boundary="offline-test",
    )

    assert projection["exception_type"] == "RuntimeError"
    assert len(projection["failure_sha256"]) == 64
    assert secret not in json.dumps(projection)
    assert "safe_message" not in projection


def test_pre_contract_final_artifact_rejection_needs_no_contract_capture() -> None:
    from tools.canary.first_trustworthy_full_short_dry_run import (
        _attempt_requires_contract_runtime_capture_v1,
    )

    common = {"contract_runtime_input_required": True}
    assert _attempt_requires_contract_runtime_capture_v1(common) is True
    assert _attempt_requires_contract_runtime_capture_v1({
        **common,
        "local_rejection_schema": "ContractLocalRejectionReceiptV1",
    }) is True
    assert _attempt_requires_contract_runtime_capture_v1({
        **common,
        "local_rejection_schema": "ProviderFinalArtifactRejectionReceiptV1",
    }) is False
    assert _attempt_requires_contract_runtime_capture_v1({
        "contract_runtime_input_required": False,
    }) is False


def test_discovery_mirrors_unstructured_runtime_stage_fallback() -> None:
    from types import SimpleNamespace

    from tools.canary.first_trustworthy_full_short_dry_run import (
        _LogicalStagePlanDiscoveryObserver,
    )

    observer = _LogicalStagePlanDiscoveryObserver()
    observer.bind_route(
        role="planning", lane="primary", provider_id="provider",
        model_id="model", route_fingerprint="f" * 64,
    )
    observer.bind_model_request(
        protocol="anthropic",
        request=SimpleNamespace(response_schema=None, max_output_tokens=321),
    )
    observer.before_http_dispatch()

    assert observer.logical_stage_plan == [{
        "ordinal": 1,
        "stage_id": "planning",
        "logical_stage_base_id": "planning",
        "logical_stage_id": "planning",
        "contract_name": "unstructured_text",
        "contract_version": 1,
        "contract_schema_sha256": hashlib.sha256(b"{}").hexdigest(),
        "contract_runtime_input_required": False,
        "requested_output_tokens": 321,
        "role": "planning",
        "route_lane": "primary",
    }]


def test_dry_run_adapter_fault_is_one_local_projection_only() -> None:
    from tools.canary.first_trustworthy_full_short_dry_run import (
        _OfflineHttpTransportFactory,
    )

    class Adapter:
        @staticmethod
        def _model_response_from_body(body, *, provider_state_extra=None):
            return {"body": body, "provider_state_extra": provider_state_extra}

    factory = _OfflineHttpTransportFactory(
        inject_adapter_failure_after_exact_capture_once=True,
    )
    adapter = Adapter()
    factory.install_adapter_failure_after_exact_capture_once(adapter)

    with pytest.raises(
        RuntimeError, match="local adapter failure after exact capture",
    ):
        adapter._model_response_from_body({"type": "message"})
    assert adapter._model_response_from_body({"type": "message"}) == {
        "body": {"type": "message"}, "provider_state_extra": None,
    }
    assert factory.adapter_failure_after_exact_capture_injected is True
    assert factory.adapter_projection_call_count == 2


@pytest.mark.asyncio
async def test_combined_planning_injections_own_distinct_logical_stages() -> None:
    from novel_flywheel.offline_http_transport import (
        build_offline_http_client_v1,
    )
    from tools.canary.first_trustworthy_full_short_dry_run import (
        _OfflineHttpTransportFactory,
    )

    factory = _OfflineHttpTransportFactory(
        inject_planning_business_incomplete_once=True,
        inject_planning_reasoning_only_once=True,
    )
    client = build_offline_http_client_v1(factory.build(
        protocol="anthropic",
        destination="https://api.deepseek.com/anthropic",
        bound_role="planning",
    ))

    async def send(user: str) -> dict:
        response = await client.post(
            "https://api.deepseek.com/anthropic/v1/messages",
            json={
                "model": "offline-planning",
                "system": "Return the planning contract only.",
                "messages": [{"role": "user", "content": user}],
                "max_tokens": 512,
            },
        )
        return response.json()

    try:
        packet = (
            "IR_FIRST_SHORT_PLANNING_PACKET_V2\n"
            "PACKET CONTRACT:\n"
            '{"global_event_ordinals":[1]}\n\n'
        )
        first = await send(packet)
        assert first["content"][0]["type"] == "text"
        assert factory.oracle.planning_business_incomplete_injected is True
        assert factory.planning_reasoning_only_injected is False

        second = await send(packet + "ACTIONABLE_PLANNING_SEMANTIC_FINDINGS")
        assert second["content"][0]["type"] == "text"
        assert factory.planning_reasoning_only_injected is False

        third = await send(packet)
        assert third["content"][0]["type"] == "thinking"
        assert factory.planning_reasoning_only_injected is True
    finally:
        await client.aclose()


def test_lowest_http_seam_adapter_fault_hook_is_optional() -> None:
    from types import SimpleNamespace

    from tools.canary.first_trustworthy_full_short_dry_run import (
        _LowestHttpSeamRegistry,
    )

    registry = object.__new__(_LowestHttpSeamRegistry)
    registry.transport_factory = SimpleNamespace()
    registry._install_optional_adapter_failure_hook(object())

    installed: list[object] = []
    registry.transport_factory = SimpleNamespace(
        install_adapter_failure_after_exact_capture_once=installed.append,
    )
    adapter = object()
    registry._install_optional_adapter_failure_hook(adapter)
    assert installed == [adapter]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "expected_status", "expected_error"),
    [
        ("provider_unavailable_complete_response", 503, None),
        ("ambiguous_external_completion", None, httpx.ReadTimeout),
    ],
)
async def test_production_transport_failure_injection_is_one_dispatch(
    scenario, expected_status, expected_error,
) -> None:
    from novel_flywheel.offline_http_transport import (
        build_offline_http_client_v1,
    )
    from tools.canary.full_short_transport_failure_dry_run import (
        _FailureInjectionTransportFactory,
    )

    factory = _FailureInjectionTransportFactory(scenario)
    client = build_offline_http_client_v1(factory.build(
        protocol="openai-chat", destination="https://offline.invalid/v1",
        bound_role="planning",
    ))
    try:
        if expected_error is None:
            response = await client.post(
                "https://offline.invalid/v1/chat/completions",
                json={"messages": [], "max_tokens": 32},
            )
            assert response.status_code == expected_status
        else:
            with pytest.raises(expected_error):
                await client.post(
                    "https://offline.invalid/v1/chat/completions",
                    json={"messages": [], "max_tokens": 32},
                )
    finally:
        await client.aclose()
    assert len(factory.call_plan) == 1


def test_transport_failure_private_path_components_stay_bounded() -> None:
    from tools.canary.full_short_transport_failure_dry_run import (
        _SCENARIO_SHORT_NAME,
    )

    assert _SCENARIO_SHORT_NAME == {
        "provider_unavailable_complete_response": "b",
        "ambiguous_external_completion": "c",
    }
    assert max(map(len, _SCENARIO_SHORT_NAME.values())) == 1


def test_transport_failure_dry_run_restores_canonical_environment_flag() -> None:
    from tools.canary import full_short_transport_failure_dry_run as dry_run

    source = Path(dry_run.__file__).read_text(encoding="utf-8")
    assert 'previous_canonical_flag = os.environ.get(' in source
    assert 'os.environ["NOVEL_SHORT_CANONICAL_V2"] = "1"' in source
    assert 'os.environ.pop("NOVEL_SHORT_CANONICAL_V2", None)' in source


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_id_sha256", "wrong"),
        ("workload_sha256", "wrong"),
        ("route_manifest_sha256", "z" * 64),
        ("completion_receipt_sha256", None),
        ("total_output_token_hard_cap", 1),
        ("hard_max_provider_requests", 72),
    ],
)
def test_replay_evidence_validation_rejects_stale_or_malformed_bindings(
    field: str, value: object,
) -> None:
    from tools.diagnostics.materialize_first_trustworthy_planning_business_incomplete import (
        PROJECT_SHA,
        WORKLOAD_SHA,
        _validate_replay,
    )

    head = "b" * 40
    digest = "a" * 64
    roles = [
        "planning", "draft", "review", "reader_review", "polish",
        "final_review", "maintenance",
    ]
    receipt = {
        "schema": "FirstTrustworthyFullShortPrivateDryRunV2",
        "version": 2,
        "source_head": head,
        "project_id_sha256": PROJECT_SHA,
        "workload_sha256": WORKLOAD_SHA,
        "pass": True,
        "workflow_status": "completed",
        "completion_goal_outcome": (
            "SHORT_WORKFLOW_COMPLETED_AND_FINAL_REVIEW_ACCEPTED"
        ),
        "expected_stage_calls": 70,
        "completed_stage_count": 70,
        "all_dispatches_locally_closed": True,
        "all_required_stage_roles_completed": True,
        "planning_business_incomplete_injected": False,
        "provider_request_count": 70,
        "local_rejected_attempt_count": 0,
        "hard_max_provider_requests": 71,
        "hard_max_http_posts": 71,
        "hard_max_network_attempts": 71,
        "additional_dispatch_hard_cap": 1,
        "maximum_elapsed_seconds": 36_000,
        "monetary_cost_cap_state": "UNKNOWN_NOT_SEALED",
        "dry_run_namespace": "two_isolated_temporary_copies",
        "dry_run_artifacts_cannot_be_mistaken_for_real_output": True,
        "raw_prompt_persisted": False,
        "raw_story_persisted": False,
        "raw_reference_persisted": False,
        "raw_title_persisted": False,
        "real_credential_lookup_count": 0,
        "real_provider_client_creation_count": 0,
        "real_provider_request_attempts": 0,
        "real_http_post_attempts": 0,
        "real_network_calls": 0,
        "real_model_calls": 0,
        "paid_calls": 0,
        "required_stage_roles": roles,
        "completed_stage_roles": roles,
        "discovered_call_plan_sha256": digest,
        "executed_call_plan_sha256": digest,
        "final_artifact_sha256": digest,
        "runtime_authority_sha256": digest,
        "style_reference_authority_sha256": digest,
        "route_manifest_sha256": digest,
        "destination_manifest_sha256": digest,
        "egress_policy_sha256": digest,
        "store_root_sha256": digest,
        "completion_receipt_sha256": digest,
        "per_call_output_token_hard_cap": 100,
        "discovered_plan_output_token_hard_cap": 1_000,
        "planning_single_repair_output_token_hard_cap": 100,
        "total_output_token_hard_cap": 1_100,
    }
    _validate_replay(receipt, head=head, injected=False)
    receipt[field] = value

    with pytest.raises(ValueError, match="replay receipt mismatch"):
        _validate_replay(receipt, head=head, injected=False)


@pytest.mark.parametrize(
    "xml",
    [
        "<not-junit/>",
        "<testsuites></testsuites>",
        '<testsuite tests="0" failures="0" errors="0" skipped="0"/>',
        '<testsuite tests="-1" failures="0" errors="0" skipped="0"/>',
        '<testsuite tests="1" failures="0" errors="0" skipped="2"/>',
    ],
)
def test_evidence_materializer_rejects_empty_or_non_junit_pass_receipts(
    tmp_path: Path, xml: str,
) -> None:
    from tools.diagnostics.materialize_first_trustworthy_planning_business_incomplete import (
        _git,
        _junit,
    )

    receipt = tmp_path / "receipt.xml"
    receipt.write_text(xml, encoding="utf-8")
    with pytest.raises(ValueError):
        _junit(
            receipt, command="pytest", classification="PASS",
            repo=Path.cwd(), head=_git(Path.cwd(), "rev-parse", "HEAD"),
        )


def test_evidence_materializer_rejects_junit_older_than_bound_head(
    tmp_path: Path,
) -> None:
    from tools.diagnostics.materialize_first_trustworthy_planning_business_incomplete import (
        _git,
        _junit,
    )

    repo = Path.cwd()
    head = _git(repo, "rev-parse", "HEAD")
    commit_timestamp = int(_git(repo, "show", "-s", "--format=%ct", head))
    receipt = tmp_path / "stale.xml"
    receipt.write_text(
        '<testsuite tests="1" failures="0" errors="0" skipped="0"/>',
        encoding="utf-8",
    )
    os.utime(receipt, (commit_timestamp - 1, commit_timestamp - 1))

    with pytest.raises(ValueError, match="predates"):
        _junit(
            receipt, command="pytest", classification="PASS",
            repo=repo, head=head,
        )


def test_real_runner_fail_closes_orphaned_and_prelaunch_reservations() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")

    assert "fail_closed_exact_once_reservation(" in source
    assert "ORPHANED_EXACT_ONCE_RESERVATION_NO_RESUME" in source
    assert "NEW_SINGLE_USE_AUTHORIZATION_REQUIRED" in source
    assert "FULL_SHORT_PRELAUNCH_RESERVATION_CLEANUP_FAILED" in source
    assert "FULL_SHORT_PRELAUNCH_FAILURE_GRAPH_" in source
    assert "FULL_SHORT_STORE_BINDING_FAILED_BEFORE_LAUNCH" not in source
    assert "FULL_SHORT_PERMISSION_FAILED_BEFORE_LAUNCH" not in source
