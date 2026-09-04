from __future__ import annotations

import asyncio
import json
import hashlib
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.route_capabilities import (
    CapabilityEvidenceV1,
    CapabilityStatus,
    RouteCapabilityRecordV1,
    RouteCapabilityRegistryV1,
)
from novel_flywheel.secrets import MemorySecretStore
from novel_flywheel.stage_capacity import CapacityAdmissionFailureV1
from novel_flywheel.skills import SkillScanner
from novel_flywheel.story_state import StoryStateStore
from tools.canary import first_trustworthy_full_short_dry_run as dry_run
from tools.canary import first_trustworthy_full_short_runner as runner


def test_authorization_stops_before_plan_discovery_for_unknown_primary_routes(
) -> None:
    from tools.canary import (
        materialize_first_trustworthy_full_short_authorization as authorization,
    )

    repo = Path(__file__).parents[2]
    with pytest.raises(
        RuntimeError, match="AUTHORIZATION_ROUTE_CAPABILITY_NOT_VERIFIED",
    ):
        authorization._require_discovery_routes_verified_v1(repo)


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
async def test_live_offline_context_manifest_fails_before_secret_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def secret_factory():
        nonlocal called
        called = True
        raise AssertionError("secret factory must not be called")

    bindings = {
        "project_id": "project",
        "logical_stage_plan": [],
        "routes": [{
            "route_context_capability_source": (
                "offline_deterministic_gateway_manifest"
            ),
        }],
    }
    document = {
        "policy": {
            "run_id": "offline-source-live-forbidden",
            "monetary_cost_cap_state": "UNKNOWN_NOT_SEALED",
        },
        "public_bindings": bindings,
    }
    raw = json.dumps(document).encode("utf-8")
    authorization = {"validated": True}
    monkeypatch.setattr(
        runner, "validate_full_short_canonical_authorization_v1",
        lambda *_args, **_kwargs: authorization,
    )
    monkeypatch.setattr(
        runner, "collect_live_bindings",
        lambda **_kwargs: ({}, bindings),
    )
    args = SimpleNamespace(
        authorization_raw=raw,
        activated_sha256=hashlib.sha256(raw).hexdigest(),
        store_root=tmp_path / "control-store",
        repo=tmp_path,
        data_dir=tmp_path,
    )

    with pytest.raises(
        runner.CapacityAdmissionFailureV1,
        match="capacity.route_capability_unknown",
    ):
        await runner.execute_full_short_control_plane(
            args, authorization, external_actions_enabled=True,
            secret_store_factory=secret_factory,
        )

    assert called is False
    receipt = json.loads(next(
        args.store_root.glob("preflight-failure-*.json")
    ).read_text(encoding="utf-8"))
    assert receipt["approval_created"] is False
    assert receipt["nonce_created"] is False
    assert receipt["credential_lookup_count"] == 0
    assert receipt["network_calls"] == 0


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
        model_name="model", context_window=32768, max_output_tokens=None,
    )
    for role in runner.FULL_SHORT_REQUIRED_EXECUTION_ROLES:
        db.save_role_binding(role, "provider", "model", None, None)
    provider = db.get_provider("provider")
    model = db.get_model("model")
    assert provider is not None and model is not None
    fingerprint = ProviderRegistry.route_fingerprint(provider, model)
    evidence_path = repo / "unit-route-capability-evidence.json"
    evidence_path.write_text(
        json.dumps({
            "context_window_tokens": 32_768,
            "max_output_tokens": 8_192,
            "reasoning_token_accounting": "INCLUDED_IN_COMPLETION_CAP",
            "reasoning_output_reservation": "WITHIN_COMPLETION_CAP",
            "route_fingerprint": fingerprint,
            "provider": "Provider",
            "provider_id_sha256": hashlib.sha256(b"provider").hexdigest(),
            "operator": "THIRD_PARTY_RELAY_UNVERIFIED_UPSTREAM",
            "destination": "https://unit.test:443/v1/messages",
            "protocol": "anthropic",
            "model": "model",
            "model_id_sha256": hashlib.sha256(b"model").hexdigest(),
        }, sort_keys=True),
        encoding="utf-8",
    )
    evidence = CapabilityEvidenceV1(
        source_kind="unit_test_fixture",
        source_locator=evidence_path.relative_to(repo).as_posix(),
        source_evidence_sha256=hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest(),
        evidence_version=1,
        evidence_date="2026-09-02",
        route_fingerprint=fingerprint,
        proved_fields=(
            "context_window_tokens", "max_output_tokens",
            "reasoning_token_accounting", "reasoning_output_reservation",
            "route_fingerprint",
            "provider", "provider_id_sha256", "operator", "destination",
            "protocol", "model", "model_id_sha256",
        ),
        provenance_available=True,
    )
    registry = RouteCapabilityRegistryV1.create(
        RouteCapabilityRecordV1.create(
            role=role,
            lane="primary",
            provider="Provider",
            provider_id_sha256=hashlib.sha256(b"provider").hexdigest(),
            operator="THIRD_PARTY_RELAY_UNVERIFIED_UPSTREAM",
            destination="https://unit.test:443/v1/messages",
            protocol="anthropic",
            model="model",
            model_id_sha256=hashlib.sha256(b"model").hexdigest(),
            route_fingerprint=fingerprint,
            context_window_tokens=32_768,
            max_output_tokens=8_192,
            reasoning_token_accounting="INCLUDED_IN_COMPLETION_CAP",
            reasoning_output_reservation="WITHIN_COMPLETION_CAP",
            capability_status=CapabilityStatus.VERIFIED_LOCAL_CONFIG_WITH_PROVENANCE,
            source_evidence=(evidence,),
        )
        for role in runner.FULL_SHORT_REQUIRED_EXECUTION_ROLES
    )
    registry_path = repo / runner._ROUTE_CAPABILITY_REGISTRY_PATH_V1
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(registry.to_document()), encoding="utf-8"
    )
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


def _private_context_manifest_copy(
    tmp_path: Path, *, planning_override: bool = False,
    install_manifest: bool = True,
) -> tuple[Database, Database, str, Path]:
    repo, data, project_id, source_db = _bound_project(tmp_path)
    source_model = source_db.get_model("model")
    assert source_model is not None
    source_db.save_model(
        model_id="model",
        provider_id="provider",
        display_name=str(source_model["display_name"]),
        model_name=str(source_model["model_name"]),
        context_window=8_192,
        max_output_tokens=source_model.get("max_output_tokens"),
        capabilities={"live_source_capability": "must-survive"},
    )
    source_db.save_model(
        model_id="unbound-model",
        provider_id="provider",
        display_name="Unbound",
        model_name="unbound",
        context_window=4_096,
        max_output_tokens=1_024,
        capabilities={"unbound": True},
    )
    if planning_override:
        source_db.save_model(
            model_id="private-planning-model",
            provider_id="provider",
            display_name="Private Planning",
            model_name="private-planning",
            context_window=None,
            max_output_tokens=None,
            capabilities={"planning_override_source": True},
        )
    live_data = repo / "data"
    live_data.mkdir()
    shutil.copy2(data / "app.db", live_data / "app.db")
    live_db = Database(live_data / "app.db")
    live_project = live_db.get_project(project_id)
    assert live_project is not None
    live_database_sha256 = hashlib.sha256(
        (live_data / "app.db").read_bytes()
    ).hexdigest()
    private_data = dry_run._copy_private_data(
        repo=repo,
        source_project=Path(str(live_project["path"])),
        project_id=project_id,
        target=tmp_path / "private",
        install_offline_gateway_context_manifest=install_manifest,
        private_role_binding_overrides=((
            "planning",
            "provider",
            "private-planning-model",
            None,
            None,
        ),) if planning_override else (),
    )
    assert hashlib.sha256((live_data / "app.db").read_bytes()).hexdigest() == (
        live_database_sha256
    )
    return live_db, Database(private_data / "app.db"), project_id, repo


def test_private_copy_context_manifest_installation_is_opt_in(
    tmp_path: Path,
) -> None:
    live_db, private_db, _project_id, _repo = _private_context_manifest_copy(
        tmp_path, install_manifest=False,
    )

    live_model = live_db.get_model("model")
    private_model = private_db.get_model("model")
    assert live_model is not None and private_model is not None
    assert private_model["context_window"] == live_model["context_window"] == 8_192
    assert private_model["capabilities"] == live_model["capabilities"]
    assert dry_run.OFFLINE_CONTEXT_MANIFEST_KEY_V1 not in (
        private_model["capabilities"]
    )


def test_private_copy_context_manifest_is_exact_and_live_source_unchanged(
    tmp_path: Path,
) -> None:
    live_db, private_db, _project_id, _repo = _private_context_manifest_copy(
        tmp_path
    )

    live_model = live_db.get_model("model")
    private_model = private_db.get_model("model")
    assert live_model is not None and private_model is not None
    assert live_model["context_window"] == 8_192
    assert live_model["capabilities"] == {
        "live_source_capability": "must-survive"
    }
    assert private_model["context_window"] == 32_768
    assert private_model["capabilities"][
        "live_source_capability"
    ] == "must-survive"
    marker = private_model["capabilities"][
        dry_run.OFFLINE_CONTEXT_MANIFEST_KEY_V1
    ]
    assert marker == dry_run.OFFLINE_CONTEXT_MANIFEST_V1
    assert set(marker) == {
        "schema",
        "version",
        "context_limit_tokens",
        "capacity_policy_registry_sha256",
        "scope",
        "external_actions_enabled",
    }
    assert marker["capacity_policy_registry_sha256"] == (
        dry_run.DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
    )
    unbound = private_db.get_model("unbound-model")
    assert unbound is not None
    assert unbound["context_window"] == 4_096
    assert unbound["capabilities"] == {"unbound": True}
    dry_run._validate_offline_gateway_context_manifest_v1(private_db)


def test_private_role_override_is_applied_before_context_manifest(
    tmp_path: Path,
) -> None:
    live_db, private_db, _project_id, _repo = _private_context_manifest_copy(
        tmp_path, planning_override=True,
    )

    live_binding = live_db.get_role_binding("planning")
    private_binding = private_db.get_role_binding("planning")
    assert live_binding is not None and private_binding is not None
    assert live_binding["primary_model_id"] == "model"
    assert private_binding["primary_model_id"] == "private-planning-model"
    live_override = live_db.get_model("private-planning-model")
    private_override = private_db.get_model("private-planning-model")
    assert live_override is not None and private_override is not None
    assert live_override["context_window"] is None
    assert dry_run.OFFLINE_CONTEXT_MANIFEST_KEY_V1 not in (
        live_override["capabilities"]
    )
    assert private_override["context_window"] == 32_768
    assert private_override["capabilities"][
        dry_run.OFFLINE_CONTEXT_MANIFEST_KEY_V1
    ] == dry_run.OFFLINE_CONTEXT_MANIFEST_V1
    dry_run._validate_offline_gateway_context_manifest_v1(private_db)


@pytest.mark.parametrize(
    "tamper",
    ("schema", "registry", "extra_field", "context_limit"),
)
def test_private_copy_context_manifest_rejects_tampering(
    tmp_path: Path, tamper: str,
) -> None:
    _live_db, private_db, _project_id, _repo = (
        _private_context_manifest_copy(tmp_path)
    )
    model = private_db.get_model("model")
    assert model is not None
    capabilities = dict(model["capabilities"])
    marker = dict(capabilities[dry_run.OFFLINE_CONTEXT_MANIFEST_KEY_V1])
    context_window = 32_768
    if tamper == "schema":
        marker["schema"] = "OfflineDeterministicGatewayContextCapabilityManifestV2"
    elif tamper == "registry":
        marker["capacity_policy_registry_sha256"] = "0" * 64
    elif tamper == "extra_field":
        marker["source"] = "unsealed"
    else:
        context_window = 65_536
    capabilities[dry_run.OFFLINE_CONTEXT_MANIFEST_KEY_V1] = marker
    private_db.save_model(
        model_id="model",
        provider_id="provider",
        display_name=str(model["display_name"]),
        model_name=str(model["model_name"]),
        context_window=context_window,
        max_output_tokens=model.get("max_output_tokens"),
        capabilities=capabilities,
    )

    with pytest.raises(ValueError, match="offline context manifest"):
        dry_run._validate_offline_gateway_context_manifest_v1(private_db)


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
    assert public["routes"]
    assert all(
        item["route_context_capability_limit_tokens"] == 32768
        and item["route_context_capability_source"] == "route_capability_registry"
        and item["route_capability_status"]
        == "VERIFIED_LOCAL_CONFIG_WITH_PROVENANCE"
        and "model_context_limit" not in item
        and "stage_operational_context_ceiling_tokens" not in item
        for item in public["routes"]
    )
    assert actual["store_root_sha256"] == hashlib.sha256(
        str(store_root.resolve()).encode("utf-8")
    ).hexdigest()
    assert (
        actual["capacity_policy_registry_sha256"]
        == public["capacity_policy_registry_sha256"]
        == dry_run.DEFAULT_STAGE_CAPACITY_POLICY_REGISTRY_V1.identity_sha256
    )


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


def test_live_bindings_reject_missing_route_capability_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data, project_id, db = _bound_project(tmp_path)
    (repo / runner._ROUTE_CAPABILITY_REGISTRY_PATH_V1).unlink()
    monkeypatch.setattr(runner, "_git", lambda *_args: "")
    with pytest.raises(CapacityAdmissionFailureV1) as caught:
        runner.collect_live_bindings(
            repo=repo,
            data_dir=data,
            project_id=project_id,
            run_id="hardening",
            logical_stage_plan=_logical_plan(),
            store_root=tmp_path / "control-store",
        )
    assert caught.value.failure_id == "capacity.route_capability_unknown"


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    (
        ("context_window_tokens", 1),
        ("route_fingerprint", "f" * 64),
        ("operator", "DEEPSEEK_OFFICIAL"),
    ),
)
def test_verified_capability_rejects_hash_valid_but_wrong_semantic_value(
    tmp_path: Path, field: str, wrong_value: object,
) -> None:
    repo, _data, _project_id, _db = _bound_project(tmp_path)
    path = repo / runner._ROUTE_CAPABILITY_REGISTRY_PATH_V1
    original = RouteCapabilityRegistryV1.from_document(
        json.loads(path.read_text(encoding="utf-8"))
    )
    evidence_path = repo / "unit-route-capability-evidence.json"
    evidence_document = {
        "context_window_tokens": original.records[0].context_window_tokens,
        "max_output_tokens": 8_192,
        "reasoning_token_accounting": "INCLUDED_IN_COMPLETION_CAP",
        "reasoning_output_reservation": "WITHIN_COMPLETION_CAP",
        "route_fingerprint": original.records[0].route_fingerprint,
        "provider": original.records[0].provider,
        "provider_id_sha256": original.records[0].provider_id_sha256,
        "operator": original.records[0].operator,
        "destination": original.records[0].destination,
        "protocol": original.records[0].protocol,
        "model": original.records[0].model,
        "model_id_sha256": original.records[0].model_id_sha256,
    }
    evidence_document[field] = wrong_value
    evidence_path.write_text(
        json.dumps(evidence_document, sort_keys=True), encoding="utf-8",
    )
    rebuilt = []
    for record in original.records:
        evidence = CapabilityEvidenceV1(
            source_kind="unit_test_fixture",
            source_locator="unit-route-capability-evidence.json",
            source_evidence_sha256=hashlib.sha256(
                evidence_path.read_bytes()
            ).hexdigest(),
            evidence_version=1,
            evidence_date="2026-09-02",
            route_fingerprint=record.route_fingerprint,
            proved_fields=(
                "context_window_tokens", "max_output_tokens",
                "reasoning_token_accounting",
                "reasoning_output_reservation",
                "route_fingerprint",
                "provider", "provider_id_sha256", "operator",
                "destination", "protocol", "model", "model_id_sha256",
            ),
            provenance_available=True,
        )
        rebuilt.append(RouteCapabilityRecordV1.create(
            role=record.role, lane=record.lane,
            provider=record.provider,
            provider_id_sha256=record.provider_id_sha256,
            operator=record.operator,
            destination=record.destination,
            protocol=record.protocol,
            model=record.model,
            model_id_sha256=record.model_id_sha256,
            route_fingerprint=record.route_fingerprint,
            context_window_tokens=record.context_window_tokens,
            max_output_tokens=record.max_output_tokens,
            reasoning_token_accounting=record.reasoning_token_accounting,
            reasoning_output_reservation=record.reasoning_output_reservation,
            capability_status=record.capability_status,
            source_evidence=(evidence,),
        ))
    path.write_text(
        json.dumps(
            RouteCapabilityRegistryV1.create(rebuilt).to_document()
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="verified route capability evidence values not proven",
    ):
        runner._load_route_capability_registry_v1(repo)


def test_verified_capability_rejects_cross_object_field_aggregation(
    tmp_path: Path,
) -> None:
    repo, _data, _project_id, _db = _bound_project(tmp_path)
    registry_path = repo / runner._ROUTE_CAPABILITY_REGISTRY_PATH_V1
    original = RouteCapabilityRegistryV1.from_document(
        json.loads(registry_path.read_text(encoding="utf-8"))
    )
    record = original.records[0]
    expected = {
        "context_window_tokens": record.context_window_tokens,
        "max_output_tokens": record.max_output_tokens,
        "reasoning_token_accounting": record.reasoning_token_accounting,
        "reasoning_output_reservation": record.reasoning_output_reservation,
        "route_fingerprint": record.route_fingerprint,
        "provider": record.provider,
        "provider_id_sha256": record.provider_id_sha256,
        "operator": record.operator,
        "destination": record.destination,
        "protocol": record.protocol,
        "model": record.model,
        "model_id_sha256": record.model_id_sha256,
    }
    evidence_path = repo / "unit-route-capability-evidence.json"
    evidence_path.write_text(
        json.dumps([{field: value} for field, value in expected.items()]),
        encoding="utf-8",
    )
    rebuilt = []
    for item in original.records:
        evidence = CapabilityEvidenceV1(
            source_kind="unit_test_cross_object_fixture",
            source_locator=evidence_path.relative_to(repo).as_posix(),
            source_evidence_sha256=hashlib.sha256(
                evidence_path.read_bytes()
            ).hexdigest(),
            evidence_version=1,
            evidence_date="2026-09-03",
            route_fingerprint=item.route_fingerprint,
            proved_fields=tuple(expected),
            provenance_available=True,
        )
        rebuilt.append(RouteCapabilityRecordV1.create(
            role=item.role, lane=item.lane, provider=item.provider,
            provider_id_sha256=item.provider_id_sha256,
            operator=item.operator, destination=item.destination,
            protocol=item.protocol, model=item.model,
            model_id_sha256=item.model_id_sha256,
            route_fingerprint=item.route_fingerprint,
            context_window_tokens=item.context_window_tokens,
            max_output_tokens=item.max_output_tokens,
            reasoning_token_accounting=item.reasoning_token_accounting,
            reasoning_output_reservation=item.reasoning_output_reservation,
            capability_status=item.capability_status,
            source_evidence=(evidence,),
        ))
    registry_path.write_text(
        json.dumps(RouteCapabilityRegistryV1.create(rebuilt).to_document()),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="verified route capability evidence values not proven",
    ):
        runner._load_route_capability_registry_v1(repo)


def _add_unknown_planning_fallback(
    *, repo: Path, db: Database,
) -> None:
    path = repo / runner._ROUTE_CAPABILITY_REGISTRY_PATH_V1
    registry = RouteCapabilityRegistryV1.from_document(
        json.loads(path.read_text(encoding="utf-8"))
    )
    provider = db.get_provider("provider")
    model = db.get_model("model")
    assert provider is not None and model is not None
    fingerprint = ProviderRegistry.route_fingerprint(provider, model)
    fallback = RouteCapabilityRecordV1.create(
        role="planning",
        lane="fallback",
        provider="Provider",
        provider_id_sha256=hashlib.sha256(b"provider").hexdigest(),
        operator="THIRD_PARTY_RELAY_UNVERIFIED_UPSTREAM",
        destination="https://unit.test:443/v1/messages",
        protocol="anthropic",
        model="model",
        model_id_sha256=hashlib.sha256(b"model").hexdigest(),
        route_fingerprint=fingerprint,
        context_window_tokens=None,
        max_output_tokens=None,
        capability_status=CapabilityStatus.UNKNOWN_BLOCKED,
        blocking_reason_codes=("NO_TRUSTWORTHY_EVIDENCE",),
    )
    updated = RouteCapabilityRegistryV1.create(
        (*registry.records, fallback)
    )
    path.write_text(json.dumps(updated.to_document()), encoding="utf-8")
    db.save_role_binding(
        "planning", "provider", "model", "provider", "model"
    )


def test_unknown_unused_fallback_is_visible_but_does_not_block_primary_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data, project_id, db = _bound_project(tmp_path)
    _add_unknown_planning_fallback(repo=repo, db=db)
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    monkeypatch.setattr(runner, "_git", lambda *_args: "")

    _actual, public = runner.collect_live_bindings(
        repo=repo,
        data_dir=data,
        project_id=project_id,
        run_id="hardening",
        logical_stage_plan=_logical_plan(),
        store_root=tmp_path / "control-store",
    )

    fallback = next(
        item for item in public["routes"]
        if item["role"] == "planning" and item["lane"] == "fallback"
    )
    assert fallback["required_by_logical_stage_plan"] is False
    assert fallback["route_capability_status"] == "UNKNOWN_BLOCKED"
    assert fallback["route_context_capability_limit_tokens"] is None
    assert public["authorization_eligible"] is True


def test_selected_route_output_request_above_verified_max_blocks_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data, project_id, _db = _bound_project(tmp_path)
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    monkeypatch.setattr(runner, "_git", lambda *_args: "")
    plan = _logical_plan()
    plan[0]["requested_output_tokens"] = 8_193

    with pytest.raises(CapacityAdmissionFailureV1) as caught:
        runner.collect_live_bindings(
            repo=repo,
            data_dir=data,
            project_id=project_id,
            run_id="hardening",
            logical_stage_plan=plan,
            store_root=tmp_path / "control-store",
        )

    assert caught.value.failure_id == "capacity.output_reserve_unsatisfied"


def test_unknown_selected_fallback_blocks_before_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, data, project_id, db = _bound_project(tmp_path)
    _add_unknown_planning_fallback(repo=repo, db=db)
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    monkeypatch.setattr(runner, "_git", lambda *_args: "")
    plan = _logical_plan()
    plan[0]["route_lane"] = "configured_fallback"

    with pytest.raises(CapacityAdmissionFailureV1) as caught:
        runner.collect_live_bindings(
            repo=repo,
            data_dir=data,
            project_id=project_id,
            run_id="hardening",
            logical_stage_plan=plan,
            store_root=tmp_path / "control-store",
        )
    assert caught.value.failure_id == "capacity.route_capability_unknown"


def test_verified_route_evidence_file_hash_is_revalidated(
    tmp_path: Path,
) -> None:
    repo, _data, _project_id, _db = _bound_project(tmp_path)
    evidence = repo / "unit-route-capability-evidence.json"
    evidence.write_text("tampered", encoding="utf-8")

    with pytest.raises(
        ValueError, match="route capability evidence hash mismatch"
    ):
        runner._load_route_capability_registry_v1(repo)


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
    assert "discovered_plan_total_cap" in source
    assert "LOGICAL_STAGE_RECOVERY_POLICY_V1" in source
    assert "planning_recovery_output_token_hard_cap" in source


def test_existing_runtime_journal_reconciles_before_approval_or_nonce() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    existing = source.index("if runtime_journal_path.exists():")
    reconcile = source.index("FullShortRestartReconcilerV1().reconcile(")
    permission = source.index("store.create_permission(")
    approval = source.index("store.create_jit_approval(")
    predispatch = source.index("prepare_predispatch_with_kernel")
    assert existing < reconcile < permission < approval < predispatch
    assert "AMBIGUOUS_OR_UNCLOSED_DISPATCH_NO_RESTART" in source[
        existing:permission
    ]


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


def test_private_dry_run_oracle_distinguishes_semantic_subwindows() -> None:
    from tools.canary.first_trustworthy_full_short_dry_run import (
        _PrivateDryRunOracle,
    )

    def prompt(task_id: str, *, exit_requirement: str = "close scope") -> str:
        contract = json.dumps({
            "task_id": task_id,
            "target_han": 600,
            "exit_requirement": exit_requirement,
        })
        return f"CURRENT_TASK_CONTRACT:\n{contract}\n\n"

    first = _PrivateDryRunOracle._draft(prompt("draft-short-segment-02/sub-1"))
    replay = _PrivateDryRunOracle._draft(prompt("draft-short-segment-02/sub-1"))
    sibling = _PrivateDryRunOracle._draft(prompt("draft-short-segment-02/sub-2"))
    corrected = _PrivateDryRunOracle._draft(prompt(
        "draft-short-segment-02/sub-1",
        exit_requirement="close scope and correct the sealed finding",
    ))

    assert first == replay
    assert first != sibling
    assert first != corrected
    first_paragraph = first.split("\n\n", 1)[0]
    sibling_paragraph = sibling.split("\n\n", 1)[0]
    corrected_paragraph = corrected.split("\n\n", 1)[0]
    assert SequenceMatcher(None, first_paragraph, sibling_paragraph).ratio() < 0.92
    assert SequenceMatcher(None, first_paragraph, corrected_paragraph).ratio() < 0.92


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
async def test_offline_registry_close_attempts_every_client_and_aggregates() -> None:
    closed: list[str] = []

    class Client:
        def __init__(self, name: str, failure: Exception | None = None) -> None:
            self.name = name
            self.failure = failure

        async def aclose(self) -> None:
            closed.append(self.name)
            if self.failure is not None:
                raise self.failure

    registry = object.__new__(dry_run._LowestHttpSeamRegistry)
    registry.open_clients = [
        Client("first", ValueError("first close")),
        Client("second"),
        Client("third", RuntimeError("third close")),
    ]
    registry.transport_factory = SimpleNamespace()

    with pytest.raises(ExceptionGroup) as caught:
        await registry.close()

    assert closed == ["first", "second", "third"]
    assert registry.open_clients == []
    assert [type(item) for item in caught.value.exceptions] == [
        ValueError, RuntimeError,
    ]
    assert registry.transport_factory.registry_close_failure is caught.value


@pytest.mark.asyncio
async def test_registry_close_failure_is_secondary_to_business_failure() -> None:
    business_failure = ValueError("business failed")
    close_failure = RuntimeError("close failed")

    class Registry:
        async def close(self) -> None:
            raise close_failure

    async def operation() -> None:
        raise business_failure

    with pytest.raises(ValueError) as caught:
        await dry_run._await_with_registry_close(operation, Registry())

    assert caught.value is business_failure
    assert caught.value.__cause__ is close_failure


def test_private_workspace_closes_after_asyncio_run_teardown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class TemporaryDirectory:
        name = str(tmp_path)

        def cleanup(self) -> None:
            events.append("temporary_directory_cleanup")

    async def fake_run(_args, *, private_root: Path) -> dict:
        assert private_root == tmp_path
        events.append("async_operation")
        return {"pass": True}

    def run_async(awaitable) -> dict:
        events.append("asyncio_run_enter")
        result = asyncio.run(awaitable)
        events.append("asyncio_run_teardown_complete")
        return result

    monkeypatch.setattr(dry_run, "_run", fake_run)
    result = dry_run._run_with_private_workspace(
        SimpleNamespace(),
        temporary_directory_factory=lambda **_kwargs: TemporaryDirectory(),
        async_runner=run_async,
        event_bus_shutdown=lambda: events.append("event_bus_shutdown_wait"),
    )

    assert result == {"pass": True}
    assert events == [
        "asyncio_run_enter",
        "async_operation",
        "asyncio_run_teardown_complete",
        "event_bus_shutdown_wait",
        "temporary_directory_cleanup",
    ]


def test_crewai_event_bus_shutdown_waits_for_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[bool] = []
    event_bus = SimpleNamespace(
        shutdown=lambda wait=True: waits.append(wait),
    )
    monkeypatch.setitem(
        sys.modules, "crewai.events.event_bus",
        SimpleNamespace(crewai_event_bus=event_bus),
    )

    dry_run._shutdown_crewai_event_bus()

    assert waits == [True]


def test_private_workspace_close_errors_fail_success_and_do_not_mask_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_called = False

    class TemporaryDirectory:
        name = str(tmp_path)

        def cleanup(self) -> None:
            nonlocal cleanup_called
            cleanup_called = True
            raise PermissionError("directory close failed")

    primary = ValueError("business failed")

    async def fail(_args, *, private_root: Path) -> dict:
        raise primary

    monkeypatch.setattr(dry_run, "_run", fail)
    with pytest.raises(ValueError) as caught:
        dry_run._run_with_private_workspace(
            SimpleNamespace(),
            temporary_directory_factory=lambda **_kwargs: TemporaryDirectory(),
            event_bus_shutdown=lambda: (_ for _ in ()).throw(
                RuntimeError("event bus close failed")
            ),
        )

    assert caught.value is primary
    assert cleanup_called is True
    assert isinstance(caught.value.__cause__, ExceptionGroup)
    assert [type(item) for item in caught.value.__cause__.exceptions] == [
        RuntimeError, PermissionError,
    ]


def test_private_workspace_success_fails_when_resource_close_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TemporaryDirectory:
        name = str(tmp_path)

        def cleanup(self) -> None:
            return None

    async def succeed(_args, *, private_root: Path) -> dict:
        return {"pass": True}

    monkeypatch.setattr(dry_run, "_run", succeed)
    with pytest.raises(ExceptionGroup) as caught:
        dry_run._run_with_private_workspace(
            SimpleNamespace(),
            temporary_directory_factory=lambda **_kwargs: TemporaryDirectory(),
            event_bus_shutdown=lambda: (_ for _ in ()).throw(
                RuntimeError("event bus close failed")
            ),
        )

    assert [type(item) for item in caught.value.exceptions] == [RuntimeError]


def test_private_workspace_retries_only_verified_winerror_145_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "full-short-private-cleanup-race"
    root.mkdir()
    (root / "late-capacity-receipt.json").write_text(
        "{}", encoding="utf-8",
    )

    class TemporaryDirectory:
        name = str(root)

        def cleanup(self) -> None:
            error = OSError("directory is not empty")
            error.winerror = 145
            raise error

    async def succeed(_args, *, private_root: Path) -> dict:
        assert private_root == root
        return {"pass": True}

    monkeypatch.setattr(dry_run, "_run", succeed)
    result = dry_run._run_with_private_workspace(
        SimpleNamespace(),
        temporary_directory_factory=lambda **_kwargs: TemporaryDirectory(),
        event_bus_shutdown=lambda: None,
    )

    assert result == {"pass": True}
    assert not root.exists()


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


def test_v3_historical_search_covers_mandated_sources_and_nonpreset_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.diagnostics import (
        materialize_full_short_runtime_architecture_redesign_v3 as materializer,
    )

    files = {
        "config/provider.json": '{"context_window_tokens": 32768}',
        "tests/fixtures/capacity.json": '{"max_output_tokens": 4096}',
        "src/runtime_notes.py": "# manually recorded output cap 11,524 tokens",
        "docs/route-manifest.md": "declared completion token limit: 20K",
        "baml_src/artifact_parser.baml": "provider model 1M context",
        "docs/old-provider-observation.jsonl": (
            '{"note":"384K max output"}\n'
        ),
        "docs/status-capability.json": (
            '{"context":"VERIFIED_372K",'
            '"max_output":"VERIFIED_384K",'
            '"pricing":"BOUNDED_256K_PRICE_TIERS"}'
        ),
        "README.md": (
            "circuit breakers: 120,000 tokens, 60,000 per pass, "
            "and 220,000 across the run; 8,192 output limit"
        ),
        "docs/superpowers/reports/empty-capability.md": "no numeric claim",
        (
            "docs/superpowers/reports/"
            "full-short-execution-runtime-architecture-redesign-v3-"
            "evidence-migration-v1/generated.json"
        ): '{"max_tokens": 999999}',
    }
    for relative, body in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    binary_files = {
        "docs/nul-marked.md": b"binary\x00max output 999998",
        "docs/non-utf8.txt": b"\xffmax output 999997",
    }
    for relative, body in binary_files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    screenshot = tmp_path / "docs" / "old-provider-capability.png"
    screenshot.write_bytes(b"not-a-real-image")
    tracked = [
        relative for relative in files
        if "full-short-execution-runtime-architecture-redesign-v3-" not in relative
    ] + [*binary_files, "docs/old-provider-capability.png"]
    monkeypatch.setattr(materializer, "_baseline_tree_entries", lambda repo: [
        {
            "path": relative,
            "object_type": "blob",
            "object_id": "0" * 40,
            "blob": (repo / relative).read_bytes(),
        }
        for relative in tracked
    ])
    monkeypatch.setattr(
        materializer, "git", lambda _repo, *args: "0" * 40
        if args == ("rev-parse", f"{materializer.BASELINE_HEAD}^{{tree}}")
        else "",
    )

    result = materializer._historical_search_inventory(tmp_path)

    values = {item["value"] for item in result["discovered_value_records"]}
    assert {
        4096, 8192, 11524, 20000, 32768, 220000, 256000, 372000,
        384000, 1000000,
    } <= values
    assert 999999 not in values
    assert {999997, 999998}.isdisjoint(values)
    readme_records = [
        item for item in result["discovered_value_records"]
        if item["original_source_path"] == "README.md"
    ]
    assert {item["value"] for item in readme_records} == {
        8192, 60000, 120000, 220000,
    }
    assert all(item["source_line_number"] == 1 for item in readme_records)
    assert all(
        item["source_evidence_sha256"] == hashlib.sha256(
            files["README.md"].encode("utf-8")
        ).hexdigest()
        and item["classification_code"] == "B"
        and item["eligible_for_verified_registry"] is False
        for item in readme_records
    )
    assert result["category_summary"]["test_fixtures"][
        "candidate_occurrence_count"
    ] >= 1
    assert result["category_summary"]["tracked_screenshots_images"] == {
        "tracked_file_count": 1,
        "text_scanned_file_count": 1,
        "binary_inventory_file_count": 0,
        "candidate_occurrence_count": 0,
    }
    assert result["category_summary"]["capability_budget_reports"][
        "tracked_file_count"
    ] >= 1
    assert result["searched_file_count"] == len(tracked)
    assert result["tracked_repository_file_count"] == len(tracked)
    assert result["historical_source_commit"] == materializer.BASELINE_HEAD
    methods = {
        item["path"]: item["scan_method"]
        for item in result["searched_file_inventory"]
    }
    assert methods["baml_src/artifact_parser.baml"] == (
        "BASELINE_UTF8_CAPACITY_BIDIRECTIONAL_SCAN"
    )
    assert methods["docs/old-provider-observation.jsonl"] == (
        "BASELINE_UTF8_CAPACITY_BIDIRECTIONAL_SCAN"
    )
    assert methods["docs/nul-marked.md"] == "NON_UTF8_OR_NUL_HASH_INVENTORY"
    assert methods["docs/non-utf8.txt"] == "NON_UTF8_OR_NUL_HASH_INVENTORY"
    assert all(
        item["classification_code"] == "B"
        and item["eligible_for_verified_registry"] is False
        and item["provenance_available"] is False
        for item in result["discovered_value_records"]
    )


def test_v3_historical_value_classification_and_external_stop_loss_contract() -> None:
    from tools.diagnostics import (
        materialize_full_short_runtime_architecture_redesign_v3 as materializer,
    )

    records = materializer._historical_value_records(Path.cwd())

    assert len(records) == 9
    assert {item["classification_code"] for item in records} == {"A", "B"}
    verified = [
        item for item in records if item["classification_code"] == "A"
    ]
    assert {
        (item["capability_field"], item["value"])
        for item in verified
    } == {
        ("context_window_tokens", 1_000_000),
        ("max_output_tokens", 384_000),
    }
    assert all(
        item["eligible_for_verified_registry"]
        and item["provenance_available"]
        and item["route_fingerprint"]
        == materializer.DEEPSEEK_ROUTE_FINGERPRINT
        for item in verified
    )
    claim = next(item for item in records if item["value"] == 372_000)
    assert claim["classification"] == "HISTORICAL_BUT_UNPROVEN"
    assert claim["original_source_path"].endswith(
        "historical-provider-screenshot-evidence-v1.json"
    )
    assert claim["provenance_available"] is True
    assert claim["eligible_for_verified_registry"] is False


def test_v3_registry_promotes_only_route_exact_complete_historical_evidence() -> None:
    from tools.diagnostics import (
        materialize_full_short_runtime_architecture_redesign_v3 as materializer,
    )

    registry = materializer.build_registry(Path.cwd())
    verified = [
        item for item in registry.records
        if item.capability_status is CapabilityStatus.VERIFIED_HISTORICAL_EVIDENCE
    ]

    assert {
        (item.role, item.lane) for item in verified
    } == {
        ("planning", "fallback"),
        ("review", "primary"),
        ("final_review", "fallback"),
        ("maintenance", "fallback"),
    }
    assert all(
        item.route_fingerprint == materializer.DEEPSEEK_ROUTE_FINGERPRINT
        and item.context_window_tokens == 1_000_000
        and item.max_output_tokens == 384_000
        for item in verified
    )
    required_unknown = registry.unknown_required_count(
        (role, "primary") for role in materializer.ROLES
    )
    assert required_unknown == 6
    lingsuan = registry.require_record(role="planning", lane="primary")
    assert lingsuan.capability_status is CapabilityStatus.UNKNOWN_BLOCKED
    assert lingsuan.context_window_tokens is None
    assert lingsuan.max_output_tokens is None
    assert any(
        "context_window_tokens" in evidence.proved_fields
        and evidence.source_kind
        == "user_supplied_historical_screenshot_manifest"
        for evidence in lingsuan.source_evidence
    )


def test_v3_historical_screenshot_manifest_is_hash_bound_and_non_inferential() -> None:
    evidence_root = (
        Path.cwd()
        / "docs"
        / "superpowers"
        / "reports"
        / "full-short-execution-runtime-architecture-redesign-v3-evidence-migration-v1"
    )
    manifest = json.loads(
        (evidence_root / "historical-provider-screenshot-evidence-v1.json")
        .read_text(encoding="utf-8")
    )

    assert manifest["source_bundle_sha256"] == (
        "84dbd766cf3b700c2b9b16f98012988d59f7a8afdfd9de2b4723f7da4a9ed4f4"
    )
    assert manifest["source_bundle_entry_count"] == 15
    assert len(manifest["entries"]) == 15
    for crop in manifest["privacy_safe_crops"]:
        crop_path = evidence_root / crop["path"]
        assert crop_path.is_file()
        assert hashlib.sha256(crop_path.read_bytes()).hexdigest() == crop["sha256"]

    gpt_claim = next(
        item for item in manifest["observations"]
        if item["provider"] == "lingsuan_gpt"
        and item["model"] == "gpt-5.6-sol"
    )
    assert gpt_claim["context_window_tokens"] == 372_000
    assert gpt_claim["max_output_tokens"] is None
    assert gpt_claim["disposition"] == "PARTIAL_ONLY_UNKNOWN_BLOCKED"
    assert all(
        item["disposition"].endswith("UNKNOWN_BLOCKED")
        for item in manifest["observations"]
    )
    assert manifest["numeric_capacity_values_not_visible_are_not_inferred"] is True
    assert set(manifest["external_boundary"].values()) == {0}


def test_v3_historical_capacity_parser_uses_nearest_unambiguous_field() -> None:
    from tools.diagnostics import (
        materialize_full_short_runtime_architecture_redesign_v3 as materializer,
    )

    records = materializer._capacity_values_in_text(
        "1M context, 384K max output\n"
        "context 2026 roadmap says 8,192 output limit\n"
        "version 1 max output 384K\n"
        "context window 8,192; max output 8,192\n"
    )
    by_line = {
        line: [(item["value"], item["capability_field"]) for item in records
               if item["line_number"] == line]
        for line in (1, 2, 3, 4)
    }

    assert by_line[1] == [(384000, "max_output"), (1000000, "context")]
    assert by_line[2] == [(8192, "output_limit")]
    assert by_line[3] == [(384000, "max_output")]
    assert by_line[4] == [
        (8192, "context_window"), (8192, "max_output"),
    ]
    assert {
        "real_credential_lookup_count",
        "real_secret_read_count",
        "real_provider_client_creation_count",
        "real_provider_request_attempts",
        "http_post_attempts",
        "http_calls",
        "network_calls",
        "model_calls",
        "paid_calls",
        "full_short_execution_count",
        "real_full_short_runs",
    } <= materializer.EXTERNAL_ZERO.keys()
    assert set(materializer.EXTERNAL_ZERO.values()) == {0}


def test_v3_historical_capacity_parser_recalls_status_encoded_claims() -> None:
    from tools.diagnostics import (
        materialize_full_short_runtime_architecture_redesign_v3 as materializer,
    )

    records = materializer._capacity_values_in_text(
        '{"context":"VERIFIED_372K"}\n'
        '{"max_output":"VERIFIED_384K"}\n'
        '("provider", "model", "VERIFIED_1M", "UNKNOWN")\n'
        '{"context":"BOUNDED_256K_PRICE_TIERS"}\n'
        'release_status="VERIFIED_2026"\n'
    )

    assert [(item["value"], item["capability_field"]) for item in records] == [
        (372_000, "context_historical_status_assertion"),
        (384_000, "max_output_historical_status_assertion"),
        (1_000_000, "verified_historical_capacity_assertion"),
        (256_000, "price_tier_boundary_marker_not_context"),
    ]


def test_v3_materializer_writes_cross_checkout_stable_lf_bytes(
    tmp_path: Path,
) -> None:
    from tools.diagnostics import (
        materialize_full_short_runtime_architecture_redesign_v3 as materializer,
    )

    json_path = tmp_path / "receipt.json"
    text_path = tmp_path / "report.md"
    materializer.write_json(json_path, {"status": "PASS"})
    materializer.write_text_lf(text_path, "line one\nline two\n")

    assert b"\r\n" not in json_path.read_bytes()
    assert b"\r\n" not in text_path.read_bytes()
