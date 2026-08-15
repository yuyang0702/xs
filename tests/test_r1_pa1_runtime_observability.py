from __future__ import annotations

import json
import traceback
from dataclasses import dataclass

import pytest

from novel_flywheel.context_policy import classify_model_failure, expanded_output_budget
from novel_flywheel.contract_runtime import (
    ExecutableContractSpec,
    execute_contract_runtime,
)
from novel_flywheel.db import Database
from novel_flywheel.domain.models import ModelResponse, ToolCall
from novel_flywheel.model_diagnostics import (
    ModelDiagnosticContextV1,
    attach_exception_snapshot,
    diagnostic_metrics_snapshot,
    provider_tool_shape_snapshot,
    reset_diagnostic_metrics_for_tests,
)
from novel_flywheel.models import ModelGateway, ModelResult
from novel_flywheel.providers.registry import ResolvedModel
from novel_flywheel.providers.anthropic import AnthropicAdapter
from novel_flywheel.providers.openai_chat import OpenAIChatAdapter
from novel_flywheel.providers.openai_responses import OpenAIResponsesAdapter
from novel_flywheel.production_incidents import classify_production_failure
from novel_flywheel.reliability_trace import read_trace, trace_file_for_project
from novel_flywheel.structured_artifacts import StructuredArtifactContract


CONTRACT = StructuredArtifactContract(
    name="planning_adaptation_whole",
    version=1,
    schema={
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    },
)


def context(project_root, *, outer=1, provider_limit=None):
    return ModelDiagnosticContextV1(
        project_root=project_root,
        run_id="controlled-run",
        stage="review",
        boundary="planning_adaptation_whole_receipt",
        role="review",
        route_kind="configured_fallback",
        contract_id=CONTRACT.name,
        contract_version=CONTRACT.version,
        outer_retry_ordinal=outer,
        provider_declared_output_limit=provider_limit,
        provider_limit_status="verified" if provider_limit else "unknown",
        request_parameter_name="max_tokens",
    )


def snapshot(*, calls, status="snapshot_exact", text=False, finish="tool_use"):
    return provider_tool_shape_snapshot(
        adapter_id="anthropic",
        adapter_version=1,
        provider_body={"shape_fixture": len(calls), "finish": finish},
        provider_request_id="private-request-id",
        content_block_count=len(calls) + int(text),
        text_present=text,
        tool_use_present=bool(calls),
        finish_reason=finish,
        calls=calls,
        snapshot_status=status,
    )


def normalized_call(name=CONTRACT.name, call_id="call-1"):
    return ToolCall(id=call_id, name=name, arguments={"ok": True})


@dataclass
class ShapeCase:
    case_id: str
    raw_calls: list[dict]
    normalized_calls: list[ToolCall]
    snapshot_status: str
    text: str
    finish: str
    expected_failure_code: str | None
    succeeds: bool


CASES = [
    ShapeCase("zero", [], [], "snapshot_exact", "", "stop", "zero_tool_calls", False),
    ShapeCase("one_correct", [{"call_id": "r1", "name": CONTRACT.name, "arguments_present": True, "arguments": {"ok": True}}], [normalized_call()], "snapshot_exact", "", "tool_use", None, True),
    ShapeCase("one_wrong", [{"call_id": "r1", "name": "wrong", "arguments_present": True, "arguments": {"ok": True}}], [normalized_call("wrong")], "snapshot_exact", "", "tool_use", "wrong_tool_identity", False),
    ShapeCase("multiple_one_correct", [{"call_id": "r1", "name": CONTRACT.name, "arguments_present": True, "arguments": {"ok": True}}, {"call_id": "r2", "name": "wrong", "arguments_present": True, "arguments": {"ok": True}}], [normalized_call(), normalized_call("wrong", "call-2")], "snapshot_exact", "", "tool_use", "multiple_tool_calls", False),
    ShapeCase("multiple_correct", [{"call_id": "r1", "name": CONTRACT.name, "arguments_present": True, "arguments": {"ok": True}}, {"call_id": "r2", "name": CONTRACT.name, "arguments_present": True, "arguments": {"ok": True}}], [normalized_call(), normalized_call(CONTRACT.name, "call-2")], "snapshot_exact", "", "tool_use", "duplicate_expected_tool", False),
    ShapeCase("multiple_wrong", [{"call_id": "r1", "name": "wrong-a", "arguments_present": True, "arguments": {"ok": True}}, {"call_id": "r2", "name": "wrong-b", "arguments_present": True, "arguments": {"ok": True}}], [normalized_call("wrong-a"), normalized_call("wrong-b", "call-2")], "snapshot_exact", "", "tool_use", "multiple_tool_calls", False),
    ShapeCase("mixed_text_tool", [{"call_id": "r1", "name": CONTRACT.name, "arguments_present": True, "arguments": {"ok": True}}], [normalized_call()], "snapshot_exact", "provider-text-not-persisted", "tool_use", None, True),
    ShapeCase("partial_max_tokens", [{"call_id": "r1", "name": CONTRACT.name, "arguments_present": False, "arguments": None, "partial": True}], [], "snapshot_partial", "", "max_tokens", "snapshot_unavailable_or_partial", False),
    ShapeCase("finish_stop", [{"call_id": "r1", "name": CONTRACT.name, "arguments_present": True, "arguments": {"ok": True}}], [normalized_call()], "snapshot_exact", "", "stop", None, True),
    ShapeCase("adapter_drop", [{"call_id": "r1", "name": CONTRACT.name, "arguments_present": True, "arguments": {"ok": True}}], [], "snapshot_exact", "", "tool_use", "adapter_tool_drop", False),
    ShapeCase("adapter_duplicate", [{"call_id": "r1", "name": CONTRACT.name, "arguments_present": True, "arguments": {"ok": True}}], [normalized_call(call_id="same"), normalized_call(call_id="same")], "snapshot_exact", "", "tool_use", "adapter_tool_duplicate", False),
]


class ShapeAdapter:
    DIAGNOSTIC_ADAPTER_ID = "anthropic"
    DIAGNOSTIC_ADAPTER_VERSION = 1

    def __init__(self, case: ShapeCase):
        self.case = case
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        provider_shape = snapshot(
            calls=self.case.raw_calls,
            status=self.case.snapshot_status,
            text=bool(self.case.text),
            finish=self.case.finish,
        )
        return ModelResponse(
            text=self.case.text,
            tool_calls=self.case.normalized_calls,
            finish_reason=self.case.finish,
            raw_request_id="private-request-id",
            provider_state={
                "transport_complete": True,
                "raw_finish_reason": self.case.finish,
                "_r1_pa1_tool_shape_snapshot": provider_shape.model_dump(
                    mode="json", by_alias=True,
                ),
            },
        )


class Registry:
    def __init__(self, adapter):
        self.adapter = adapter

    def resolve(self, provider_id, model_id):
        return ResolvedModel(
            provider_id, model_id, "controlled-model", self.adapter,
            {"structured_output": "strict_tool"},
        )


def gateway(tmp_path, adapter):
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding(
        "review", "primary-provider", "primary-model",
        "fallback-provider", "fallback-model",
    )
    return ModelGateway(db, Registry(adapter))


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda value: value.case_id)
async def test_gateway_observes_three_layers_before_preserving_current_decision(
    case, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("NOVEL_RELIABILITY_TRACE", "1")
    monkeypatch.setenv("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1", "1")
    reset_diagnostic_metrics_for_tests()
    project_root = tmp_path / "data" / "projects" / "controlled"
    project_root.mkdir(parents=True)
    adapter = ShapeAdapter(case)
    model_gateway = gateway(tmp_path, adapter)

    if case.succeeds:
        result = await model_gateway.complete_route(
            "configured_fallback", "review", "system", "user",
            max_output_tokens=1276, contract=CONTRACT,
            diagnostic_context=context(project_root),
        )
        assert json.loads(result.text) == {"ok": True}
    else:
        with pytest.raises(RuntimeError) as caught:
            await model_gateway.complete_route(
                "configured_fallback", "review", "system", "user",
                max_output_tokens=1276, contract=CONTRACT,
                diagnostic_context=context(project_root),
            )
        assert str(caught.value) == (
            "strict structured tool route returned no unique artifact"
        )

    report = read_trace(trace_file_for_project(project_root))
    event = [
        item for item in report.events
        if item.event_type == "diagnostic_strict_tool_shape"
    ][0]
    payload = event.payload
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["strict_tool_failure_code"] == case.expected_failure_code
    assert payload["request_declared_tool_count"] == 1
    assert payload["tool_choice_policy"] == "forced_exact_tool"
    assert payload["provider_shape"]["shape_correlation_sha256"] == (
        payload["shape_correlation_sha256"]
    )
    assert payload["normalized_tool_call_count"] == len(case.normalized_calls)
    assert "provider-text-not-persisted" not in serialized
    assert "private-request-id" not in serialized
    assert report.coverage_gaps == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("protocol", "adapter_class", "body", "expected_adapter_id"),
    [
        (
            "anthropic", AnthropicAdapter,
            {
                "id": "request", "stop_reason": "tool_use", "usage": {},
                "content": [{
                    "type": "tool_use", "id": "call", "name": CONTRACT.name,
                    "input": {"ok": True},
                }],
            },
            "anthropic",
        ),
        (
            "openai-chat", OpenAIChatAdapter,
            {
                "id": "request", "usage": {},
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": None, "tool_calls": [{
                        "id": "call", "function": {
                            "name": CONTRACT.name,
                            "arguments": json.dumps({"ok": True}),
                        },
                    }]},
                }],
            },
            "openai_chat",
        ),
        (
            "openai-responses", OpenAIResponsesAdapter,
            {
                "id": "request", "status": "completed", "usage": {},
                "output": [{
                    "type": "function_call", "call_id": "call",
                    "name": CONTRACT.name,
                    "arguments": json.dumps({"ok": True}),
                }],
            },
            "openai_responses",
        ),
    ],
)
async def test_each_production_adapter_reaches_gateway_with_exact_three_layer_binding(
    protocol, adapter_class, body, expected_adapter_id, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("NOVEL_RELIABILITY_TRACE", "1")
    monkeypatch.setenv("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1", "1")
    project_root = tmp_path / "data" / "projects" / "controlled"
    project_root.mkdir(parents=True)
    adapter = adapter_class("https://relay.invalid/v1", "secret")

    async def fake_post_stream(*_args, **_kwargs):
        return [], body

    monkeypatch.setattr(adapter, "post_stream", fake_post_stream)
    result = await gateway(tmp_path, adapter).complete_route(
        "configured_fallback", "review", "system", "user",
        max_output_tokens=1276, contract=CONTRACT,
        diagnostic_context=context(project_root),
    )
    report = read_trace(trace_file_for_project(project_root))
    payload = report.events[0].payload

    assert json.loads(result.text) == {"ok": True}
    assert payload["request_protocol"] == expected_adapter_id
    assert payload["provider_shape"]["snapshot_status"] == "snapshot_exact"
    assert payload["provider_shape"]["raw_tool_call_count"] == 1
    assert payload["normalized_tool_call_count"] == 1
    assert payload["gateway_matching_count"] == 1
    assert payload["strict_tool_decision"] == "accept_unique_expected"
    assert payload["provider_shape"]["shape_correlation_sha256"] == (
        payload["shape_correlation_sha256"]
    )


class ExceptionAdapter:
    DIAGNOSTIC_ADAPTER_ID = "openai_chat"
    DIAGNOSTIC_ADAPTER_VERSION = 1

    def __init__(self):
        self.last_exception = None

    async def complete(self, _request):
        exc = json.JSONDecodeError("same-message", "{", 1)
        attached = snapshot(
            calls=[{
                "call_id": "call", "name": CONTRACT.name,
                "arguments_present": True, "arguments": "{malformed",
                "partial": True,
            }],
            status="adapter_exception_with_snapshot",
        )
        attach_exception_snapshot(exc, attached)
        self.last_exception = exc
        raise exc


async def exception_run(tmp_path, monkeypatch, *, enabled):
    monkeypatch.setenv("NOVEL_RELIABILITY_TRACE", "1")
    monkeypatch.setenv("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1", "1" if enabled else "0")
    project_root = tmp_path / ("enabled" if enabled else "disabled") / "projects" / "p"
    project_root.mkdir(parents=True)
    adapter = ExceptionAdapter()
    model_gateway = gateway(tmp_path / ("db-on" if enabled else "db-off"), adapter)
    with pytest.raises(json.JSONDecodeError) as caught:
        await model_gateway.complete_route(
            "configured_fallback", "review", "system", "user",
            max_output_tokens=1276, contract=CONTRACT,
            diagnostic_context=context(project_root),
        )
    return caught.value, adapter.last_exception, project_root


@pytest.mark.asyncio
async def test_adapter_exception_identity_traceback_classification_and_chain_are_unchanged(
    tmp_path, monkeypatch,
) -> None:
    disabled, disabled_original, _ = await exception_run(
        tmp_path, monkeypatch, enabled=False,
    )
    enabled, enabled_original, project_root = await exception_run(
        tmp_path, monkeypatch, enabled=True,
    )

    assert disabled is disabled_original
    assert enabled is enabled_original
    assert type(enabled) is type(disabled)
    assert str(enabled) == str(disabled)
    assert enabled.__cause__ is disabled.__cause__ is None
    assert enabled.__context__ is disabled.__context__ is None
    assert classify_model_failure(enabled) == classify_model_failure(disabled)
    assert classify_production_failure(
        str(enabled), workflow="short", stage="review",
    ) == classify_production_failure(
        str(disabled), workflow="short", stage="review",
    )
    disabled_frames = [item.name for item in traceback.extract_tb(disabled.__traceback__)]
    enabled_frames = [item.name for item in traceback.extract_tb(enabled.__traceback__)]
    assert enabled_frames == disabled_frames
    report = read_trace(trace_file_for_project(project_root))
    assert report.events[0].payload["strict_tool_decision"] == (
        "adapter_exception_before_uniqueness"
    )


@pytest.mark.asyncio
async def test_observer_sink_failure_does_not_change_gateway_failure(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("NOVEL_RELIABILITY_TRACE", "1")
    monkeypatch.setenv("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1", "1")
    project_root = tmp_path / "data" / "projects" / "controlled"
    project_root.mkdir(parents=True)
    adapter = ShapeAdapter(CASES[0])
    model_gateway = gateway(tmp_path, adapter)
    monkeypatch.setattr(
        "novel_flywheel.reliability_trace.BestEffortTraceSink.emit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("sink failed")),
    )

    with pytest.raises(RuntimeError, match="no unique artifact"):
        await model_gateway.complete_route(
            "configured_fallback", "review", "system", "user",
            max_output_tokens=1276, contract=CONTRACT,
            diagnostic_context=context(project_root),
        )

    assert len(adapter.requests) == 1


@pytest.mark.asyncio
async def test_non_target_strict_tool_call_is_counted_without_full_shape_record(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("NOVEL_STRICT_TOOL_SHAPE_TRACE_V1", "1")
    reset_diagnostic_metrics_for_tests()
    adapter = ShapeAdapter(CASES[1])
    model_gateway = gateway(tmp_path, adapter)

    result = await model_gateway.complete_route(
        "configured_fallback", "review", "system", "user",
        max_output_tokens=1276, contract=CONTRACT,
    )

    assert json.loads(result.text) == {"ok": True}
    assert "_r1_pa1_tool_shape_snapshot" not in adapter.requests[0].model_dump()
    assert diagnostic_metrics_snapshot()["strict_tool_excluded_not_target"] == 1


class OutputLimitedGateway:
    def __init__(self):
        self.budgets = []

    @staticmethod
    def has_configured_fallback(_role):
        return False

    async def complete_route(self, _route, _role, _system, _user, **kwargs):
        self.budgets.append(kwargs["max_output_tokens"])
        return ModelResult(
            "{invalid",
            {"finish_reason": "max_tokens", "transport_complete": True},
        )


def runtime_spec():
    return ExecutableContractSpec(
        contract_name=CONTRACT.name,
        structured_contract=CONTRACT,
        semantic_normalizer=lambda value: value,
        domain_validator=lambda value: value,
    )


@pytest.mark.asyncio
async def test_three_outer_runtimes_explain_1276_sequence_and_cap_lineage(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("NOVEL_RELIABILITY_TRACE", "1")
    monkeypatch.setenv("NOVEL_PA_OUTPUT_BUDGET_LINEAGE_V1", "1")
    project_root = tmp_path / "data" / "projects" / "controlled"
    project_root.mkdir(parents=True)
    gateway_value = OutputLimitedGateway()

    for outer in (1, 2, 3):
        with pytest.raises(Exception):
            await execute_contract_runtime(
                gateway_value,
                role="review",
                system="same-system",
                user="same-user",
                execution_spec=runtime_spec(),
                max_output_tokens=1276,
                same_route_attempts=1,
                fallback_attempts=0,
                attempt_routes=("primary",),
                diagnostic_context=context(
                    project_root, outer=outer, provider_limit=2000,
                ).__class__(**{
                    **context(project_root, outer=outer, provider_limit=2000).__dict__,
                    "route_kind": "primary",
                }),
            )

    assert gateway_value.budgets == [1276, 1276, 1276]
    report = read_trace(trace_file_for_project(project_root))
    events = [item.payload for item in report.events]
    created = [item for item in events if item["lineage_event"] == "runtime_created"]
    expanded = [item for item in events if item["lineage_event"] == "expansion_decided"]

    assert len({item["contract_runtime_instance_id"] for item in created}) == 3
    assert [item["current_requested_output_budget"] for item in created] == [1276] * 3
    assert [item["runtime_reconstructed"] for item in created] == [False, True, True]
    assert [item["expansion_target_before_cap"] for item in expanded] == [
        expanded_output_budget(1276),
    ] * 3
    assert [item["effective_budget_after_provider_cap"] for item in expanded] == [
        2000, 2000, 2000,
    ]
    assert all(item["cap_applied"] is True for item in expanded)
    assert all(item["expansion_applied"] is False for item in expanded)
    assert all(item["retained_expansion_state"] is False for item in expanded)
    assert report.coverage_gaps == []
