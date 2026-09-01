from __future__ import annotations

import json
import logging
from pathlib import Path
import traceback
from types import SimpleNamespace

import pytest

from novel_flywheel.execution_failure_architecture import (
    OBSERVER_ISOLATION_POLICY_V1,
    ObserverGuard,
)
from novel_flywheel.workflows import WorkflowService


class _RaisingLoggingHandler(logging.Handler):
    def emit(self, _record: logging.LogRecord) -> None:
        raise OSError("offline logging sink failure")


class _BusinessRootCause(RuntimeError):
    pass


def _gbk_emoji_failure() -> None:
    "🌊".encode("gbk")


def _logging_sink_failure() -> None:
    logger = logging.Logger("phase10-observer-isolation")
    logger.propagate = False
    logger.addHandler(_RaisingLoggingHandler())
    logger.info("accepted business result")


def _telemetry_serialization_failure() -> None:
    json.dumps({"accepted": object()})


def _bind_offline_crewai_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVEL_FLYWHEEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREWAI_STORAGE_DIR", str(tmp_path / "crewai" / "storage"))
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")


@pytest.mark.parametrize(
    "observer_operation, expected_exception",
    [
        pytest.param(_gbk_emoji_failure, UnicodeEncodeError, id="gbk-emoji"),
        pytest.param(_logging_sink_failure, OSError, id="logging-sink"),
        pytest.param(
            _telemetry_serialization_failure,
            TypeError,
            id="telemetry-serialization",
        ),
    ],
)
def test_phase10_best_effort_faults_preserve_exact_business_root_cause(
    observer_operation,
    expected_exception,
) -> None:
    observer_failures: list[type[BaseException]] = []
    guard = ObserverGuard(lambda exc: observer_failures.append(type(exc)))
    primary = _BusinessRootCause("authoritative business failure")

    with pytest.raises(_BusinessRootCause) as caught:
        try:
            raise primary
        except _BusinessRootCause:
            assert guard.emit(observer_operation) is False
            raise

    assert caught.value is primary
    assert caught.value.args == ("authoritative business failure",)
    assert observer_failures == [expected_exception]


@pytest.mark.asyncio
async def test_phase10_observer_business_coupling_count_is_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted = {
        "status": "accepted",
        "authority_sha256": "a" * 64,
    }
    business_coupling_count = 0

    for observer_operation in (
        _gbk_emoji_failure,
        _logging_sink_failure,
        _telemetry_serialization_failure,
    ):
        before = dict(accepted)
        result = accepted
        assert ObserverGuard().emit(observer_operation) is False
        business_coupling_count += int(result is not accepted or result != before)

    service = SimpleNamespace(
        crewai_data_dir=tmp_path / "crewai",
        db=SimpleNamespace(path=tmp_path / "runtime.sqlite3"),
    )
    _bind_offline_crewai_storage(tmp_path, monkeypatch)
    from crewai.flow.flow import Flow

    async def event_handler_fails_after_business_success(self):
        await self.execute()
        raise RuntimeError("offline CrewAI event-handler failure")

    async def pipeline():
        return accepted

    monkeypatch.setattr(Flow, "kickoff_async", event_handler_fails_after_business_success)
    result = await WorkflowService._run_in_crewai(service, pipeline)
    business_coupling_count += int(result is not accepted)

    assert business_coupling_count == 0  # OBSERVER_BUSINESS_COUPLING_COUNT
    assert OBSERVER_ISOLATION_POLICY_V1["business_outcome_mutation_allowed"] is False


@pytest.mark.asyncio
async def test_phase10_crewai_event_handler_failure_keeps_original_root_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        crewai_data_dir=tmp_path / "crewai",
        db=SimpleNamespace(path=tmp_path / "runtime.sqlite3"),
    )
    _bind_offline_crewai_storage(tmp_path, monkeypatch)
    from crewai.flow.flow import Flow

    primary = _BusinessRootCause("authoritative business failure")

    async def event_handler_fails_after_business_failure(self):
        try:
            await self.execute()
        except _BusinessRootCause:
            raise OSError("offline CrewAI event-handler failure")

    async def pipeline():
        raise primary

    monkeypatch.setattr(Flow, "kickoff_async", event_handler_fails_after_business_failure)

    with pytest.raises(_BusinessRootCause) as caught:
        await WorkflowService._run_in_crewai(service, pipeline)

    assert caught.value is primary
    assert caught.value.args == ("authoritative business failure",)
    assert isinstance(caught.value.__cause__, OSError)
    assert caught.value.__cause__.args == ("offline CrewAI event-handler failure",)
    assert caught.value.__traceback__ is not None
    traceback_functions = [
        frame.name for frame in traceback.extract_tb(caught.value.__traceback__)
    ]
    assert traceback_functions[-1] == "pipeline"
    assert "_run_in_crewai" in traceback_functions
