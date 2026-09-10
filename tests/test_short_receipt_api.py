from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from novel_flywheel.api.runs import ShortReceiptResume, resume_short_receipt


def _request(*, run: dict, workflow: object) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                registry=SimpleNamespace(
                    db=SimpleNamespace(get_run=lambda _run_id: run),
                ),
                workflows=workflow,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_api_receipt_resume_delegates_existing_run_without_draft_generation() -> None:
    calls: list[tuple[str, dict]] = []

    class Workflows:
        async def resume_short_receipt(self, project_id: str, **kwargs):
            calls.append((project_id, kwargs))
            return {
                "operation_kind": "semantic_receipt",
                "provider_dispatch_executed": False,
                "draft_request_count": 0,
            }

    payload = ShortReceiptResume(
        candidate_relative_path="outputs/draft-part-01-sub-1.md",
        candidate_sha256="A" * 64,
        task_id="segment-01/sub-1",
    )
    result = await resume_short_receipt(
        "run-1",
        payload,
        _request(
            run={"id": "run-1", "project_id": "project-1", "workflow": "short-story"},
            workflow=Workflows(),
        ),
    )

    assert result["operation_kind"] == "semantic_receipt"
    assert calls == [
        (
            "project-1",
            {
                "run_id": "run-1",
                "candidate_relative_path": "outputs/draft-part-01-sub-1.md",
                "candidate_sha256": "a" * 64,
                "task_id": "segment-01/sub-1",
                "execute": False,
                "max_dispatches": 0,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_api_receipt_resume_rejects_non_short_run_before_workflow_call() -> None:
    class Workflows:
        async def resume_short_receipt(self, **_kwargs):
            raise AssertionError("non-short runs must be rejected before dispatch")

    payload = ShortReceiptResume(
        candidate_relative_path="outputs/draft.md",
        candidate_sha256="a" * 64,
        task_id="segment-01/sub-1",
    )
    with pytest.raises(HTTPException) as caught:
        await resume_short_receipt(
            "run-1",
            payload,
            _request(
                run={"id": "run-1", "project_id": "project-1", "workflow": "long-setup"},
                workflow=Workflows(),
            ),
        )
    assert caught.value.status_code == 409
    assert caught.value.detail == {"code": "run_not_short_story"}
