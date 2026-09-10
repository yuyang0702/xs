from __future__ import annotations

import importlib
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_flywheel.models import ModelDispatchBudgetExhaustedError
from novel_flywheel.short_receipt_resume import PreparedShortReceiptResume
from novel_flywheel.workflow_coordination import WorkflowCoordinator


@pytest.mark.asyncio
async def test_actual_receipt_launcher_calls_public_resume_entry_without_draft(
    tmp_path, monkeypatch,
) -> None:
    launcher = importlib.import_module("tools.canary.short_receipt_resume")
    calls = []

    class Workflows:
        async def resume_short_receipt(self, project_id, **kwargs):
            calls.append((project_id, kwargs))
            return {
                "operation_kind": "semantic_receipt",
                "provider_dispatch_executed": False,
                "draft_request_count": 0,
            }

    monkeypatch.setattr(
        launcher, "create_app",
        lambda **_kwargs: SimpleNamespace(state=SimpleNamespace(workflows=Workflows())),
    )
    args = launcher.parser().parse_args([
        "--db", str(tmp_path / "app.db"),
        "--workspace-root", str(tmp_path / "projects"),
        "--references-root", str(tmp_path / "references"),
        "--project-id", "project-1",
        "--run-id", "run-1",
        "--candidate", "outputs/draft-part-01-sub-1.md",
        "--candidate-sha256", "a" * 64,
        "--task-id", "segment-01/sub-1",
    ])
    result = await launcher.run(args)
    assert result["operation_kind"] == "semantic_receipt"
    assert calls == [("project-1", {
        "run_id": "run-1",
        "candidate_relative_path": "outputs/draft-part-01-sub-1.md",
        "candidate_sha256": "a" * 64,
        "task_id": "segment-01/sub-1",
        "execute": False,
        "max_dispatches": 0,
    })]


@pytest.mark.asyncio
async def test_native_resume_scope_stops_local_budget_before_semantic_dispatch(
    tmp_path, monkeypatch,
) -> None:
    workflows = importlib.import_module("novel_flywheel.workflows")

    class Project:
        id = "project-1"
        mode = "short"

    class FakeGateway:
        @contextmanager
        def bind_dispatch_operation_scope(self, scope):
            assert scope.operation_kind == "semantic_receipt"
            assert scope.stage == "review"
            assert scope.contract_names == ("draft_atomic_semantic_receipt",)
            yield

    class FakeDB:
        def add_run_event(self, *_args, **_kwargs):
            raise AssertionError("budget rejection must happen before success event")

    candidate = tmp_path / "draft.md"
    candidate.write_text("候选正文", encoding="utf-8")
    prepared = SimpleNamespace(
        record={
            "candidate_prose_sha256": "a" * 64,
            "candidate_raw_sha256": "b" * 64,
            "draft_request_count": 0,
            "task_id": "segment-01/sub-1",
        },
        contract=SimpleNamespace(task_id="segment-01/sub-1"),
        prose="候选正文",
        outside_beat_ids=(),
        run_path=tmp_path,
        candidate_path=candidate,
        state_path=tmp_path / "pending.json",
        constraints="immutable",
    )
    service = workflows.WorkflowService.__new__(workflows.WorkflowService)
    service.gateway = FakeGateway()
    service.db = FakeDB()
    service.coordinator = WorkflowCoordinator(service)
    service.projects = SimpleNamespace(get=lambda _id: Project())
    monkeypatch.setattr(workflows, "prepare_short_receipt_resume", lambda *a, **k: prepared)
    async def reject(*_args, **_kwargs):
        raise ModelDispatchBudgetExhaustedError()
    monkeypatch.setattr(service, "_verify_draft_semantic_node", reject)

    with pytest.raises(ModelDispatchBudgetExhaustedError):
        await service.resume_short_receipt(
            "project-1", run_id="run-1",
            candidate_relative_path="outputs/draft.md",
            candidate_sha256="a" * 64,
            task_id="segment-01/sub-1", execute=True, max_dispatches=1,
        )
