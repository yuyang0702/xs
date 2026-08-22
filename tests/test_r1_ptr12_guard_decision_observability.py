from __future__ import annotations

import json
import hashlib

import pytest
import novel_flywheel.model_diagnostics as diagnostics

from novel_flywheel.db import Database
from novel_flywheel.domain.models import ModelResponse
from novel_flywheel.model_diagnostics import ModelDiagnosticContextV1
from novel_flywheel.models import (
    ModelGateway,
    ReasoningOnlyFinalArtifactUnavailableError,
)
from novel_flywheel.provider_output import capture_provider_raw_shape_v1
from novel_flywheel.providers.registry import ResolvedModel
from novel_flywheel.reliability_trace import (
    BestEffortTraceSink,
    read_trace,
    trace_file_for_project,
)
from novel_flywheel.structured_artifacts import StructuredArtifactContract


class CaptureAdapter:
    DIAGNOSTIC_ADAPTER_ID = "anthropic"
    DIAGNOSTIC_ADAPTER_VERSION = 1

    def __init__(self, body: dict, *, error: Exception | None = None) -> None:
        self.body = body
        self.error = error
        self.calls = 0
        self.request_semantic_sha256 = None

    async def complete(self, request):
        self.calls += 1
        self.request_semantic_sha256 = hashlib.sha256(
            json.dumps(
                request.model_dump(mode="json"), sort_keys=True,
                ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        capture_provider_raw_shape_v1(
            protocol="anthropic", body=self.body, events=[],
            requested_output_cap=request.max_output_tokens,
        )
        if self.error is not None:
            raise self.error
        content = self.body.get("content", [])
        usage = self.body.get("usage", {})
        return ModelResponse(
            text="".join(
                item.get("text", "") for item in content
                if item.get("type") == "text"
            ),
            finish_reason=self.body.get("stop_reason"),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            provider_state={
                "content": content,
                "transport_complete": self.body.get("stop_reason") is not None,
                "raw_finish_reason": self.body.get("stop_reason"),
            },
        )


class Registry:
    def __init__(self, adapter) -> None:
        self.adapter = adapter

    def resolve(self, provider_id, model_id):
        return ResolvedModel(
            provider_id, model_id, model_id, self.adapter,
            {"structured_output": "strict_json_schema"}, "a" * 64,
        )


def contract() -> StructuredArtifactContract:
    return StructuredArtifactContract(
        name="interview_planning", version=1,
        schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"], "additionalProperties": False,
        },
        runtime_authority={"test": "ptr12-offline"},
    )


def context(tmp_path) -> ModelDiagnosticContextV1:
    return ModelDiagnosticContextV1(
        project_root=tmp_path, run_id="ptr12-run", stage="planning",
        boundary="planning_semantic_v2", role="planning",
        route_kind="configured_fallback", contract_id="interview_planning",
        contract_version=1, outer_retry_ordinal=1,
    )


def gateway(tmp_path, adapter):
    trace_file_for_project(tmp_path).unlink(missing_ok=True)
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_role_binding("planning", "provider", "model", None, None)
    return db, ModelGateway(db, Registry(adapter))


async def run_case(tmp_path, monkeypatch, *, enabled: bool, body: dict):
    monkeypatch.setenv(
        "NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1" if enabled else "0",
    )
    adapter = CaptureAdapter(body)
    db, model_gateway = gateway(tmp_path, adapter)
    try:
        result = await model_gateway.complete_route(
            "primary", "planning", "PRIVATE_SYSTEM", "PRIVATE_USER",
            contract=contract(), max_output_tokens=8798,
            diagnostic_context=context(tmp_path),
        )
        outcome = ("return", result.text, result.receipt)
    except Exception as exc:
        outcome = ("raise", type(exc).__name__, str(exc), getattr(exc, "receipt", None))
    qualification = db.get_structured_route_qualification(
        provider_id="provider", model_id="model", route_fingerprint="a" * 64,
        execution_mode="final_artifact", contract_name="interview_planning",
        schema_sha256=contract().schema_sha256(),
    )
    if qualification is not None:
        qualification = {
            key: value for key, value in qualification.items()
            if key not in {"last_success_at", "last_failure_at", "updated_at"}
        }
    return outcome, qualification, adapter.calls, adapter.request_semantic_sha256


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["normal", "reasoning_only"])
async def test_observer_on_off_business_parity(monkeypatch, tmp_path, kind) -> None:
    body = (
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"message":"complete offline result"}'}], "usage": {"output_tokens": 7}}
        if kind == "normal"
        else {"stop_reason": "max_tokens", "content": [{"type": "thinking", "thinking": "PRIVATE_REASONING"}], "usage": {"output_tokens": 8798}}
    )
    off = await run_case(tmp_path / "off", monkeypatch, enabled=False, body=body)
    on = await run_case(tmp_path / "on", monkeypatch, enabled=True, body=body)
    assert off == on


@pytest.mark.asyncio
async def test_reasoning_only_emits_raw_delta_and_guard_before_same_typed_failure(
    monkeypatch, tmp_path,
) -> None:
    body = {"stop_reason": "max_tokens", "content": [{"type": "thinking", "thinking": "PRIVATE_REASONING"}], "usage": {"output_tokens": 8798}}
    monkeypatch.setenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1")
    adapter = CaptureAdapter(body)
    _, model_gateway = gateway(tmp_path, adapter)
    with pytest.raises(ReasoningOnlyFinalArtifactUnavailableError) as caught:
        await model_gateway.complete_route(
            "primary", "planning", "PRIVATE_SYSTEM", "PRIVATE_USER",
            contract=contract(), max_output_tokens=8798,
            diagnostic_context=context(tmp_path),
        )
    report = read_trace(trace_file_for_project(tmp_path))
    events = [item.event_type for item in report.events]
    assert events == [
        "diagnostic_provider_raw_shape_v1",
        "diagnostic_provider_shape_delta_v1",
        "diagnostic_ptr9_guard_decision_v1",
    ]
    guard = report.events[-1].payload
    assert guard["guard_triggered"] is True
    assert guard["predicate_all_true"] is True
    assert guard["negative_capability_write_status"] == "RECORDED"
    serialized = "\n".join(item.model_dump_json() for item in report.events)
    for forbidden in ("PRIVATE_REASONING", "PRIVATE_SYSTEM", "PRIVATE_USER"):
        assert forbidden not in serialized
    assert str(caught.value) == (
        "reasoning-only provider output exhausted without a final artifact"
    )


@pytest.mark.asyncio
async def test_sink_exception_is_fail_open_and_result_exact(
    monkeypatch, tmp_path,
) -> None:
    body = {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"message":"complete offline result"}'}], "usage": {"output_tokens": 7}}
    baseline = await run_case(
        tmp_path / "baseline", monkeypatch, enabled=False, body=body,
    )
    monkeypatch.setattr(
        BestEffortTraceSink, "emit",
        lambda _self, _envelope: (_ for _ in ()).throw(OSError("PRIVATE_SINK")),
    )
    observed = await run_case(
        tmp_path / "observed", monkeypatch, enabled=True, body=body,
    )
    assert observed == baseline


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["schema", "hash"])
async def test_schema_and_hash_failures_are_business_fail_open(
    monkeypatch, tmp_path, failure,
) -> None:
    body = {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"message":"complete offline result"}'}], "usage": {"output_tokens": 7}}
    baseline = await run_case(
        tmp_path / "baseline", monkeypatch, enabled=False, body=body,
    )
    if failure == "schema":
        monkeypatch.setattr(
            diagnostics.ProviderRawShapeObservationV1, "model_validate",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("PRIVATE_SCHEMA")),
        )
    else:
        monkeypatch.setattr(
            diagnostics, "domain_sha256",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("PRIVATE_HASH")),
        )
    observed = await run_case(
        tmp_path / "observed", monkeypatch, enabled=True, body=body,
    )
    assert observed == baseline


@pytest.mark.asyncio
async def test_adapter_exception_type_message_and_trace_gap_are_preserved(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setenv("NOVEL_PTR12_RAW_SHAPE_GUARD_OBSERVER_V1", "1")
    original = ValueError("PRIVATE_ADAPTER_ERROR")
    adapter = CaptureAdapter(
        {"stop_reason": None, "content": [{"type": "private_unknown"}], "usage": {}},
        error=original,
    )
    _, model_gateway = gateway(tmp_path, adapter)
    with pytest.raises(ValueError) as caught:
        await model_gateway.complete_route(
            "primary", "planning", "system", "user", contract=contract(),
            diagnostic_context=context(tmp_path),
        )
    assert caught.value is original
    assert str(caught.value) == "PRIVATE_ADAPTER_ERROR"
    report = read_trace(trace_file_for_project(tmp_path))
    assert [item.event_type for item in report.events] == [
        "diagnostic_provider_raw_shape_v1",
        "diagnostic_provider_shape_delta_v1",
        "diagnostic_ptr9_guard_decision_v1",
    ]
    serialized = json.dumps([item.payload for item in report.events])
    assert "PRIVATE_ADAPTER_ERROR" not in serialized
