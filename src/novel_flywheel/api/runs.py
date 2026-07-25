import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api", tags=["runs"])


def _ensure_project(project_id: str, request: Request) -> None:
    try:
        request.app.state.projects.get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={
            "code": "project_not_found", "message": str(exc),
        }) from exc


@router.post("/projects/{project_id}/runs/short", status_code=status.HTTP_202_ACCEPTED)
async def start_short_run(project_id: str, request: Request) -> dict:
    _ensure_project(project_id, request)

    async def operation(run_id: str) -> object:
        return await request.app.state.workflows.run_short(project_id, run_id=run_id)

    return request.app.state.run_tasks.start(project_id, "short-story", operation)


@router.post("/projects/{project_id}/runs/setup", status_code=status.HTTP_202_ACCEPTED)
async def start_long_setup(project_id: str, request: Request) -> dict:
    _ensure_project(project_id, request)

    async def operation(run_id: str) -> object:
        return await request.app.state.workflows.run_long_setup(project_id, run_id=run_id)

    return request.app.state.run_tasks.start(project_id, "long-setup", operation)


@router.post("/projects/{project_id}/runs/materials-audit", status_code=status.HTTP_202_ACCEPTED)
async def start_materials_audit(project_id: str, request: Request) -> dict:
    _ensure_project(project_id, request)

    async def operation(run_id: str) -> object:
        return await request.app.state.workflows.run_materials_audit(project_id, run_id=run_id)

    return request.app.state.run_tasks.start(project_id, "materials-audit", operation)


@router.post("/projects/{project_id}/runs/materials-repair", status_code=status.HTTP_202_ACCEPTED)
async def start_materials_repair(project_id: str, request: Request) -> dict:
    _ensure_project(project_id, request)

    async def operation(run_id: str) -> object:
        return await request.app.state.workflows.run_materials_repair(project_id, run_id=run_id)

    return request.app.state.run_tasks.start(project_id, "materials-repair", operation)


class ChapterRun(BaseModel):
    chapter_goal: str = Field(min_length=1)


@router.post("/projects/{project_id}/runs/chapter", status_code=status.HTTP_202_ACCEPTED)
async def start_long_chapter(project_id: str, payload: ChapterRun, request: Request) -> dict:
    _ensure_project(project_id, request)

    async def operation(run_id: str) -> object:
        return await request.app.state.workflows.run_chapter(
            project_id, payload.chapter_goal, run_id=run_id,
        )

    return request.app.state.run_tasks.start(project_id, "long-chapter", operation)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, request: Request) -> dict:
    try:
        return request.app.state.run_tasks.cancel(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"}) from exc


@router.post("/runs/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_run(run_id: str, request: Request) -> dict:
    run = request.app.state.registry.db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"})
    if run["workflow"] != "short-story":
        raise HTTPException(status_code=409, detail={"code": "run_not_resumable"})

    async def operation(existing_run_id: str) -> object:
        return await request.app.state.workflows.run_short(
            run["project_id"], run_id=existing_run_id,
        )

    try:
        return request.app.state.run_tasks.resume(run_id, operation)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "run_not_resumable"}) from exc


@router.get("/projects/{project_id}/runs")
def list_runs(project_id: str, request: Request) -> list[dict]:
    return request.app.state.registry.db.list_runs(project_id)


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict:
    run = request.app.state.registry.db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"})
    run["tool_receipts"] = request.app.state.registry.db.list_tool_receipts(run_id)
    run["events"] = request.app.state.registry.db.list_run_events(run_id)
    project = request.app.state.registry.db.get_project(run["project_id"])
    if project:
        report_path = Path(project["path"]) / "runs" / run_id / "outputs" / "quality-report.json"
        conflict_path = Path(project["path"]) / "runs" / run_id / "outputs" / "conflict-report.json"
        try:
            run["quality_report"] = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            run["quality_report"] = None
        try:
            run["conflict_report"] = json.loads(conflict_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            run["conflict_report"] = None
    return run
