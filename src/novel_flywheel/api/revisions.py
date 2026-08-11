from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from novel_flywheel.revision_operations import (
    RevisionOperationError,
    RevisionOperations,
)
from novel_flywheel.narrative_contract import ensure_narrative_contract


router = APIRouter(prefix="/api", tags=["revisions"])


class StartRevisionPayload(BaseModel):
    issue_ids: list[str] = Field(min_length=1, max_length=50)


class GroupDecisionPayload(BaseModel):
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def revision_operations(request: Request) -> RevisionOperations:
    return RevisionOperations(
        request.app.state.registry.db,
        request.app.state.projects,
        request.app.state.workflows,
    )


def revision_http_error(exc: RevisionOperationError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post(
    "/projects/{project_id}/revisions",
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_revision(
    project_id: str, payload: StartRevisionPayload, request: Request,
) -> dict:
    try:
        project = request.app.state.projects.get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    narrative_contract = ensure_narrative_contract(project)
    if narrative_contract.status != "ready":
        raise HTTPException(status_code=409, detail={
            "code": "narrator_confirmation_required",
            "message": "第一人称叙述者无法唯一确定，请先选择本书中代表“我”的人物。",
            "candidates": [dict(item) for item in narrative_contract.candidates],
        })
    try:
        selected = revision_operations(request).validate_start(
            project_id, payload.issue_ids,
        )
    except RevisionOperationError as exc:
        raise revision_http_error(exc) from None

    async def operation(run_id: str) -> object:
        return await request.app.state.workflows.run_short_revision(
            project_id, selected, run_id=run_id,
        )

    return request.app.state.run_tasks.start(
        project_id, "short-revision", operation,
        resume_payload={"issue_ids": list(selected)},
    )


@router.get("/runs/{run_id}/revision")
def get_revision(run_id: str, request: Request) -> dict:
    try:
        return revision_operations(request).read(run_id)
    except RevisionOperationError as exc:
        raise revision_http_error(exc) from None


def _decide_group(
    run_id: str, group_id: str, decision: str,
    payload: GroupDecisionPayload, request: Request,
) -> dict:
    try:
        return revision_operations(request).decide_group(
            run_id, group_id, decision, payload.candidate_hash,
        )
    except RevisionOperationError as exc:
        raise revision_http_error(exc) from None


@router.post("/runs/{run_id}/revision/groups/{group_id}/adopt")
def adopt_revision_group(
    run_id: str, group_id: str, payload: GroupDecisionPayload,
    request: Request,
) -> dict:
    return _decide_group(
        run_id, group_id, "adopted", payload, request,
    )


@router.post("/runs/{run_id}/revision/groups/{group_id}/reject")
def reject_revision_group(
    run_id: str, group_id: str, payload: GroupDecisionPayload,
    request: Request,
) -> dict:
    return _decide_group(
        run_id, group_id, "rejected", payload, request,
    )


@router.post("/runs/{run_id}/revision/finalize")
async def finalize_revision(run_id: str, request: Request) -> dict:
    try:
        return await revision_operations(request).finalize(run_id)
    except RevisionOperationError as exc:
        raise revision_http_error(exc) from None
