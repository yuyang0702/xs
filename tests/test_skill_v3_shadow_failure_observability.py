from __future__ import annotations

from pathlib import Path

import pytest

import novel_flywheel.workflows as workflows_module
from novel_flywheel.failure_boundary import failure_evidence_sha256
from novel_flywheel.models import ModelResult
from novel_flywheel.reliability_trace import read_trace, trace_file_for_project
from novel_flywheel.selective_skill_compiler import (
    SectionIndexError,
    SelectionError,
    SelectiveSkillShadowObserverV1,
)
from test_phase05_evidence_closure import _service
from test_selective_skill_compiler import _compiler


class DependencyClosureFailure(SelectionError):
    pass


class RendererFailure(RuntimeError):
    pass


class MaterializationFailure(RuntimeError):
    pass


class CacheLayerFailure(RuntimeError):
    pass


class Gateway:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def complete(self, role, system, user, max_output_tokens=None):
        self.calls.append((role, system, user, max_output_tokens))
        return ModelResult("{}", {"role": role, "model_name": "offline"})


async def _run_planning(service, store, project, *, workflow: str) -> None:
    constraints = store.load_constraints(project.id)
    run_id, run_path = service._begin_run(project, "short-story", workflow)
    await service._stage(
        run_id,
        run_path,
        project,
        "planning",
        constraints,
        "same task",
        allow_tools=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_name", "failure_type"),
    (
        ("section-index-load", SectionIndexError),
        ("selector", SelectionError),
        ("dependency-closure", DependencyClosureFailure),
        ("renderer", RendererFailure),
        ("materialization", MaterializationFailure),
        ("cache-layer", CacheLayerFailure),
    ),
)
async def test_shadow_failure_emits_one_bounded_hash_only_event_and_continues(
    tmp_path: Path,
    case_name: str,
    failure_type: type[Exception],
) -> None:
    gateway = Gateway()
    _db, store, project, service = _service(
        tmp_path,
        mode="short",
        gateway=gateway,
        title=f"Skill V3 shadow failure {case_name}",
    )
    project.metadata["creative_demand_class"] = "character-heavy"
    await _run_planning(service, store, project, workflow="shadow-baseline")

    secret = f"PRIVATE_{case_name}_MESSAGE"
    failure = failure_type(secret)

    def failing_observer(_payload):
        raise failure

    service.skill_context_shadow_observer = failing_observer
    await _run_planning(service, store, project, workflow=f"shadow-{case_name}")

    assert gateway.calls[0] == gateway.calls[1]
    assert service.skill_v3_shadow_failure_count == 1
    assert service.skill_v3_shadow_failure_evidence_drop_count == 0
    assert len(service.skill_v3_shadow_failure_records) == 1
    local_record = service.skill_v3_shadow_failure_records[0]
    assert local_record["failure_count_increment"] == 1
    assert local_record["failure_count"] == 1
    assert len(local_record["shadow_invocation_id"]) == 64
    assert local_record["production_continued"] is True
    assert local_record["shadow_output_used_by_model"] is False
    assert local_record["raw_exception_persisted"] is False
    assert local_record["traceback_persisted"] is False
    assert local_record["rendered_context_sha256"] == "NOT_AVAILABLE_BY_STAGE"
    assert local_record["error_class"] == failure_type.__name__
    assert local_record["error_message_hash"] == failure_evidence_sha256(
        failure,
        boundary="WorkflowService._stage.skill_context_shadow_observer",
    )

    trace_path = trace_file_for_project(project.path)
    raw_trace = trace_path.read_text(encoding="utf-8")
    assert secret not in raw_trace
    assert "Traceback" not in raw_trace
    events = [
        event
        for event in read_trace(trace_path).events
        if event.event_type == "skill_v3_selective_compiler_shadow_failure"
    ]
    assert len(events) == 1
    assert events[0].payload["failure_event_sha256"] == local_record[
        "failure_event_sha256"
    ]


@pytest.mark.asyncio
async def test_shadow_projection_sink_failure_is_observed_and_fail_open(
    tmp_path: Path,
) -> None:
    gateway = Gateway()
    _db, store, project, service = _service(
        tmp_path,
        mode="short",
        gateway=gateway,
        title="Skill V3 projection sink failure",
    )
    project.metadata["creative_demand_class"] = "character-heavy"
    await _run_planning(service, store, project, workflow="shadow-baseline")

    secret = "PRIVATE_PROJECTION_SINK_MESSAGE"

    def failing_projection_sink(_projection):
        raise RuntimeError(secret)

    service.skill_context_shadow_observer = SelectiveSkillShadowObserverV1(
        _compiler(), sink=failing_projection_sink,
    )
    await _run_planning(service, store, project, workflow="shadow-projection-sink")

    assert gateway.calls[0] == gateway.calls[1]
    assert service.skill_v3_shadow_failure_count == 1
    assert service.skill_v3_shadow_failure_evidence_drop_count == 0
    assert secret not in trace_file_for_project(project.path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_failure_trace_sink_failure_has_bounded_counter_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = Gateway()
    _db, store, project, service = _service(
        tmp_path,
        mode="short",
        gateway=gateway,
        title="Skill V3 failure trace sink failure",
    )
    project.metadata["creative_demand_class"] = "character-heavy"
    await _run_planning(service, store, project, workflow="shadow-baseline")

    service.skill_context_shadow_observer = lambda _payload: (_ for _ in ()).throw(
        RuntimeError("PRIVATE_FAILURE_TRACE_SINK_MESSAGE")
    )

    def failing_trace_sink(*_args, **_kwargs):
        raise RuntimeError("trace sink unavailable")

    original_emit_observation = workflows_module.emit_observation

    def selective_failing_trace_sink(*args, **kwargs):
        if kwargs.get("event_type") == "skill_v3_selective_compiler_shadow_failure":
            return failing_trace_sink(*args, **kwargs)
        return original_emit_observation(*args, **kwargs)

    monkeypatch.setattr(
        workflows_module, "emit_observation", selective_failing_trace_sink,
    )
    await _run_planning(service, store, project, workflow="shadow-trace-sink-fail")

    assert gateway.calls[0] == gateway.calls[1]
    assert service.skill_v3_shadow_failure_count == 1
    assert service.skill_v3_shadow_failure_evidence_drop_count == 1
    assert len(service.skill_v3_shadow_failure_records) == 1
    assert service.skill_v3_shadow_failure_records[0]["trace_event_written"] is False
    assert not any(
        event.event_type == "skill_v3_selective_compiler_shadow_failure"
        for event in read_trace(trace_file_for_project(project.path)).events
    )
