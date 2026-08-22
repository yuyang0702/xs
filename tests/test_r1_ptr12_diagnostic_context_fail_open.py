import asyncio
import json
import sys

import pytest

from novel_flywheel.contract_runtime import ExecutableContractSpec
from novel_flywheel.db import Database
from novel_flywheel.model_diagnostics import PTR12_OBSERVER_FLAG
from novel_flywheel.models import ModelResult
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.structured_artifacts import StructuredArtifactContract
from novel_flywheel.workflows import WorkflowService


DIAGNOSTIC_CONTRACT = StructuredArtifactContract(
    name="r1_ptr12_diagnostic_context_test_v1",
    schema={
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    },
    version=1,
)
EXECUTION_CONTRACT = StructuredArtifactContract(
    name="interview_planning",
    schema={
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    },
    version=1,
)


class OriginalProviderError(RuntimeError):
    pass


class RecordingRouteGateway:
    def __init__(self, outcomes=None) -> None:
        self.calls: list[dict] = []
        self.outcomes = list(outcomes or [])

    async def complete_route(self, route, role, system, user, **kwargs):
        self.calls.append({
            "route": route,
            "role": role,
            "system": system,
            "user": user,
            "kwargs": kwargs,
        })
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return successful_result()


def successful_result() -> ModelResult:
    return ModelResult(json.dumps({"ok": True}), {
        "finish_reason": "stop",
        "provider_id": "provider",
        "model_id": "model",
        "model_name": "offline-model",
        "input_tokens": 7,
        "output_tokens": 3,
    })


def contract_successful_result() -> ModelResult:
    return ModelResult(json.dumps({"message": "accepted"}), {
        "finish_reason": "stop",
        "provider_id": "provider",
        "model_id": "model",
        "model_name": "offline-model",
        "input_tokens": 7,
        "output_tokens": 3,
    })


def execution_spec() -> ExecutableContractSpec:
    return ExecutableContractSpec(
        contract_name="interview_planning",
        structured_contract=EXECUTION_CONTRACT,
        semantic_normalizer=(
            lambda value: value if isinstance(value, dict) else None
        ),
        domain_validator=lambda value: value,
    )


def make_stage_service(tmp_path, *, run_id: str, gateway=None):
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_provider(
        provider_id="provider",
        name="Offline Provider",
        protocol="openai-chat",
        base_url="https://offline.invalid/v1",
        auth_type="bearer",
        timeout_seconds=30,
        extra_headers={},
    )
    db.save_model(
        model_id="model",
        provider_id="provider",
        display_name="Offline Model",
        model_name="offline-model",
        max_output_tokens=2048,
    )
    db.save_role_binding("review", "provider", "model", None, None)
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.create(ProjectCreate(
        title="PTR12 diagnostic context",
        mode="short",
        genre="suspense",
        premise="An observer failure must not alter business execution.",
        target_words=3000,
    ))
    skill_root = tmp_path / "skills"
    skill = skill_root / "revision-continuity"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: revision-continuity\n---\n\nOffline test skill.",
        encoding="utf-8",
    )
    gateway = gateway or RecordingRouteGateway()
    service = WorkflowService(
        db,
        store,
        gateway,
        SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "receipts").mkdir()
    return db, project, service, gateway, run_path


async def run_diagnostic_stage(
    service, project, run_path, *, run_id: str, primary_only: bool = True,
):
    return await service._stage(
        run_id,
        run_path,
        project,
        "review",
        "Preserve the accepted business request.",
        "Return one bounded offline receipt.",
        allow_tools=False,
        primary_only=primary_only,
        bounded_protocol_output=True,
        structured_transport_contract=DIAGNOSTIC_CONTRACT,
        diagnostic_boundary="r1_ptr12_context_fail_open_test",
        diagnostic_outer_retry_ordinal=1,
    )


async def run_contract_stage(service, project, run_path, *, run_id: str):
    return await service._stage(
        run_id,
        run_path,
        project,
        "review",
        "Preserve the accepted business request.",
        "Return one bounded offline contract artifact.",
        allow_tools=False,
        primary_only=False,
        bounded_protocol_output=True,
        execution_spec=execution_spec(),
        diagnostic_boundary="r1_ptr12_context_fail_open_contract_test",
        diagnostic_outer_retry_ordinal=1,
    )


def patch_context_operation_failure(
    monkeypatch,
    service,
    operation: str,
    *,
    exception_factory=lambda: LookupError("PRIVATE observer context failure"),
) -> dict[str, int]:
    counts = {"role_binding": 0, "provider": 0, "domain_hash": 0}
    original_role = service.db.get_role_binding
    original_provider = service.db.get_provider

    def in_context_helper() -> bool:
        return sys._getframe(2).f_code.co_name == "_stage_diagnostic_context"

    def role_binding(role):
        if in_context_helper():
            counts["role_binding"] += 1
            if operation in {"role_binding", "multiple"}:
                raise exception_factory()
        return original_role(role)

    def provider(provider_id):
        if in_context_helper():
            counts["provider"] += 1
            if operation in {"provider", "multiple"}:
                raise exception_factory()
        return original_provider(provider_id)

    def domain_hash(*_args, **_kwargs):
        counts["domain_hash"] += 1
        if operation in {"domain_hash", "multiple"}:
            raise exception_factory()
        import novel_flywheel.model_diagnostics as model_diagnostics
        return model_diagnostics.domain_sha256(*_args, **_kwargs)

    monkeypatch.setattr(service.db, "get_role_binding", role_binding)
    monkeypatch.setattr(service.db, "get_provider", provider)
    monkeypatch.setattr(
        "novel_flywheel.workflows.diagnostic_domain_sha256",
        domain_hash,
    )
    return counts


def structured_route_state_count(db) -> int:
    with db.connect() as connection:
        return int(connection.execute(
            "SELECT COUNT(*) FROM structured_route_qualifications",
        ).fetchone()[0])


def checkpoint_projection(db) -> list[dict]:
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT node_key, input_sha256, output_sha256, "
            "status, checkpoint_version, validation_stage, attempt, "
            "route_fingerprint, next_node, payload_json "
            "FROM workflow_node_checkpoints ORDER BY node_key",
        ).fetchall()
    return [dict(row) for row in rows]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ("role_binding", "provider", "domain_hash", "multiple"),
)
async def test_observer_context_failure_preserves_exact_business_dispatch(
    tmp_path, monkeypatch, operation,
) -> None:
    monkeypatch.setenv(PTR12_OBSERVER_FLAG, "0")
    off_db, off_project, off_service, off_gateway, off_path = make_stage_service(
        tmp_path / operation / "off",
        run_id="observer-off",
    )
    patch_context_operation_failure(monkeypatch, off_service, operation)
    off_result = await run_diagnostic_stage(
        off_service,
        off_project,
        off_path,
        run_id="observer-off",
    )

    monkeypatch.setenv(PTR12_OBSERVER_FLAG, "1")
    on_db, on_project, on_service, on_gateway, on_path = make_stage_service(
        tmp_path / operation / "on",
        run_id="observer-on",
    )
    counts = patch_context_operation_failure(monkeypatch, on_service, operation)
    on_result = await run_diagnostic_stage(
        on_service,
        on_project,
        on_path,
        run_id="observer-on",
    )

    assert str(off_result) == str(on_result) == json.dumps({"ok": True})
    assert len(off_gateway.calls) == len(on_gateway.calls) == 1
    assert off_gateway.calls == on_gateway.calls
    assert (off_path / "outputs" / "review.md").read_bytes() == (
        on_path / "outputs" / "review.md"
    ).read_bytes()
    assert (off_path / "receipts" / "review.json").read_bytes() == (
        on_path / "receipts" / "review.json"
    ).read_bytes()
    assert checkpoint_projection(off_db) == checkpoint_projection(on_db)
    assert structured_route_state_count(off_db) == 0
    assert structured_route_state_count(on_db) == 0
    assert counts["role_binding"] == 1
    assert counts["provider"] == (
        0 if operation in {"role_binding", "multiple"} else 1
    )
    assert counts["domain_hash"] == (
        0 if operation in {"role_binding", "provider", "multiple"} else 1
    )


@pytest.mark.asyncio
async def test_normal_observer_context_uses_one_bounded_lookup_pair(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv(PTR12_OBSERVER_FLAG, "1")
    _, project, service, gateway, run_path = make_stage_service(
        tmp_path,
        run_id="normal-observer",
    )
    counts = patch_context_operation_failure(monkeypatch, service, "none")

    result = await run_diagnostic_stage(
        service,
        project,
        run_path,
        run_id="normal-observer",
    )

    assert str(result) == json.dumps({"ok": True})
    assert len(gateway.calls) == 1
    assert counts == {"role_binding": 1, "provider": 1, "domain_hash": 2}


@pytest.mark.asyncio
async def test_context_failure_preserves_original_provider_exception_and_privacy(
    tmp_path, monkeypatch,
) -> None:
    original = OriginalProviderError("PRIVATE original provider failure")

    monkeypatch.setenv(PTR12_OBSERVER_FLAG, "0")
    off_gateway = RecordingRouteGateway([original])
    off_db, off_project, off_service, _, off_path = make_stage_service(
        tmp_path / "off",
        run_id="provider-error-off",
        gateway=off_gateway,
    )
    with pytest.raises(OriginalProviderError) as off_caught:
        await run_diagnostic_stage(
            off_service,
            off_project,
            off_path,
            run_id="provider-error-off",
        )

    monkeypatch.setenv(PTR12_OBSERVER_FLAG, "1")
    on_gateway = RecordingRouteGateway([original])
    on_db, on_project, on_service, _, on_path = make_stage_service(
        tmp_path / "on",
        run_id="provider-error-on",
        gateway=on_gateway,
    )
    patch_context_operation_failure(monkeypatch, on_service, "domain_hash")
    with pytest.raises(OriginalProviderError) as on_caught:
        await run_diagnostic_stage(
            on_service,
            on_project,
            on_path,
            run_id="provider-error-on",
        )

    assert off_caught.value is on_caught.value is original
    assert off_gateway.calls == on_gateway.calls
    assert len(on_gateway.calls) == 1
    persisted = json.dumps(
        on_db.list_run_events("provider-error-on"),
        ensure_ascii=False,
    )
    assert "PRIVATE original provider failure" not in persisted
    assert "PRIVATE observer context failure" not in persisted
    assert structured_route_state_count(off_db) == 0
    assert structured_route_state_count(on_db) == 0


@pytest.mark.asyncio
async def test_context_failure_does_not_add_retry_or_fallback(
    tmp_path, monkeypatch,
) -> None:
    transient_off = OriginalProviderError("offline transient")
    transient_on = OriginalProviderError("offline transient")

    monkeypatch.setenv(PTR12_OBSERVER_FLAG, "0")
    off_gateway = RecordingRouteGateway([transient_off, successful_result()])
    _, off_project, off_service, _, off_path = make_stage_service(
        tmp_path / "off",
        run_id="retry-off",
        gateway=off_gateway,
    )
    off_result = await run_diagnostic_stage(
        off_service, off_project, off_path, run_id="retry-off",
        primary_only=False,
    )

    monkeypatch.setenv(PTR12_OBSERVER_FLAG, "1")
    on_gateway = RecordingRouteGateway([transient_on, successful_result()])
    _, on_project, on_service, _, on_path = make_stage_service(
        tmp_path / "on",
        run_id="retry-on",
        gateway=on_gateway,
    )
    patch_context_operation_failure(monkeypatch, on_service, "provider")
    on_result = await run_diagnostic_stage(
        on_service, on_project, on_path, run_id="retry-on",
        primary_only=False,
    )

    assert str(off_result) == str(on_result)
    assert off_gateway.calls == on_gateway.calls
    assert len(on_gateway.calls) == 2
    assert {call["route"] for call in on_gateway.calls} == {"primary"}


@pytest.mark.asyncio
async def test_multi_attempt_correlation_degrades_by_omission_without_business_diff(
    tmp_path, monkeypatch,
) -> None:
    transient_control = OriginalProviderError("offline transient")
    monkeypatch.setenv(PTR12_OBSERVER_FLAG, "1")
    control_gateway = RecordingRouteGateway([
        transient_control,
        contract_successful_result(),
    ])
    _, control_project, control_service, _, control_path = make_stage_service(
        tmp_path / "control",
        run_id="correlation-control",
        gateway=control_gateway,
    )
    control_result = await run_contract_stage(
        control_service,
        control_project,
        control_path,
        run_id="correlation-control",
    )

    transient_failure = OriginalProviderError("offline transient")
    failure_gateway = RecordingRouteGateway([
        transient_failure,
        contract_successful_result(),
    ])
    _, failure_project, failure_service, _, failure_path = make_stage_service(
        tmp_path / "context-failure",
        run_id="correlation-context-failure",
        gateway=failure_gateway,
    )
    patch_context_operation_failure(monkeypatch, failure_service, "domain_hash")
    failure_result = await run_contract_stage(
        failure_service,
        failure_project,
        failure_path,
        run_id="correlation-context-failure",
    )

    control_contexts = [
        call["kwargs"]["diagnostic_context"] for call in control_gateway.calls
    ]
    assert [context.inner_attempt_ordinal for context in control_contexts] == [1, 2]
    assert control_contexts[1].parent_attempt_id == control_contexts[0].inner_attempt_id
    assert all(
        "diagnostic_context" not in call["kwargs"]
        for call in failure_gateway.calls
    )
    business_projection = lambda call: {
        key: value for key, value in call.items() if key != "kwargs"
    } | {
        "kwargs": {
            key: value for key, value in call["kwargs"].items()
            if key != "diagnostic_context"
        },
    }
    assert [business_projection(call) for call in control_gateway.calls] == [
        business_projection(call) for call in failure_gateway.calls
    ]
    assert str(control_result) == str(failure_result)
    assert len(control_gateway.calls) == len(failure_gateway.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ("before_context", "during_context", "dispatch"))
async def test_cancellation_is_never_swallowed(
    tmp_path, monkeypatch, phase,
) -> None:
    monkeypatch.setenv(PTR12_OBSERVER_FLAG, "1")
    gateway = RecordingRouteGateway(
        [asyncio.CancelledError()] if phase == "dispatch" else None,
    )
    _, project, service, _, run_path = make_stage_service(
        tmp_path / phase,
        run_id=f"cancel-{phase}",
        gateway=gateway,
    )
    if phase == "before_context":
        monkeypatch.setattr(
            service.skills,
            "run_required",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                asyncio.CancelledError(),
            ),
        )
    elif phase == "during_context":
        patch_context_operation_failure(
            monkeypatch,
            service,
            "role_binding",
            exception_factory=asyncio.CancelledError,
        )

    with pytest.raises(asyncio.CancelledError):
        await run_diagnostic_stage(
            service,
            project,
            run_path,
            run_id=f"cancel-{phase}",
        )

    assert len(gateway.calls) == (1 if phase == "dispatch" else 0)


@pytest.mark.parametrize("control_exception", (KeyboardInterrupt, SystemExit))
def test_process_control_exceptions_are_not_swallowed(
    tmp_path, monkeypatch, control_exception,
) -> None:
    monkeypatch.setenv(PTR12_OBSERVER_FLAG, "1")
    _, project, service, _, _ = make_stage_service(
        tmp_path / control_exception.__name__,
        run_id=f"control-{control_exception.__name__}",
    )
    patch_context_operation_failure(
        monkeypatch,
        service,
        "role_binding",
        exception_factory=control_exception,
    )

    with pytest.raises(control_exception):
        service._stage_diagnostic_context(
            project=project,
            run_id=f"control-{control_exception.__name__}",
            stage="review",
            boundary="r1_ptr12_context_fail_open_test",
            role="review",
            selected_route="primary",
            structured_contract=DIAGNOSTIC_CONTRACT,
            outer_retry_ordinal=1,
            provider_ceiling=2048,
            fallback_ceiling=None,
        )
