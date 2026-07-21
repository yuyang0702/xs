from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api", tags=["runs"])


@router.post("/projects/{project_id}/runs/short", status_code=status.HTTP_201_CREATED)
async def start_short_run(project_id: str, request: Request) -> dict:
    try:
        return await request.app.state.workflows.run_short(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_or_model_not_found", "message": str(exc)}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail={"code": "skill_approval_required", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_workflow", "message": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail={"code": "workflow_failed", "message": str(exc)}) from exc


@router.post("/projects/{project_id}/runs/setup", status_code=status.HTTP_201_CREATED)
async def start_long_setup(project_id: str, request: Request) -> dict:
    try:
        return await request.app.state.workflows.run_long_setup(project_id)
    except (LookupError, ValueError, PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail={"code": "workflow_failed", "message": str(exc)}) from exc


class ChapterRun(BaseModel):
    chapter_goal: str = Field(min_length=1)


@router.post("/projects/{project_id}/runs/chapter", status_code=status.HTTP_201_CREATED)
async def start_long_chapter(project_id: str, payload: ChapterRun, request: Request) -> dict:
    try:
        return await request.app.state.workflows.run_chapter(project_id, payload.chapter_goal)
    except (LookupError, ValueError, PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail={"code": "workflow_failed", "message": str(exc)}) from exc


@router.get("/projects/{project_id}/runs")
def list_runs(project_id: str, request: Request) -> list[dict]:
    return request.app.state.registry.db.list_runs(project_id)


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict:
    run = request.app.state.registry.db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"})
    run["tool_receipts"] = request.app.state.registry.db.list_tool_receipts(run_id)
    return run
