import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from novel_flywheel.revision_operations import (
    RevisionOperationError,
    RevisionOperations,
)
from novel_flywheel.production_incidents import production_incident_catalog
from novel_flywheel.narrative_contract import ensure_narrative_contract
from novel_flywheel.skill_runtime import initialization_answers, initialization_stage_issues

router = APIRouter(prefix="/api", tags=["runs"])


def _ensure_project(project_id: str, request: Request) -> None:
    try:
        request.app.state.projects.get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={
            "code": "project_not_found", "message": str(exc),
        }) from exc


def _ensure_confirmed_outline(project_id: str, request: Request) -> None:
    readiness = request.app.state.outlines.writing_readiness(project_id)
    if not request.app.state.outlines.current(project_id)["exists"]:
        raise HTTPException(status_code=409, detail={
            "code": "outline_confirmation_required",
            "message": "请先选择候选大纲并设为正式大纲，再生成正文。",
        })
    if not readiness["ready"]:
        raise HTTPException(status_code=409, detail={
            "code": "outline_canon_conflict",
            "message": readiness["message"],
            "conflicts": readiness["conflicts"],
        })


def _ensure_initialized(project_id: str, request: Request) -> None:
    project = request.app.state.projects.get(project_id)
    current = request.app.state.outlines.current(project_id)
    answers = initialization_answers(project, current)
    stage_labels = {
        "story-init": "故事资料", "character-management": "人物资料",
        "worldbuilding": "世界设定", "plot-structure": "剧情结构",
    }
    missing = []
    for skill_name in project.metadata.get("initialization_skills", []):
        issues = initialization_stage_issues(project, skill_name, answers)
        if issues:
            missing.append(f"{stage_labels.get(skill_name, skill_name)}：{issues[0]}")
    if missing:
        raise HTTPException(status_code=409, detail={
            "code": "initialization_required",
            "message": "作品资料还没有准备完整，请先点击“继续初始化”。",
            "issues": missing,
        })


def _ensure_narrative_contract(project_id: str, request: Request) -> None:
    project = request.app.state.projects.get(project_id)
    contract = ensure_narrative_contract(project)
    if contract.status == "needs_confirmation":
        raise HTTPException(status_code=409, detail={
            "code": "narrator_confirmation_required",
            "message": "第一人称叙述者无法唯一确定，请先选择本书中代表“我”的人物。",
            "candidates": [dict(item) for item in contract.candidates],
        })


@router.post("/projects/{project_id}/runs/short", status_code=status.HTTP_202_ACCEPTED)
async def start_short_run(project_id: str, request: Request) -> dict:
    _ensure_project(project_id, request)
    _ensure_confirmed_outline(project_id, request)
    _ensure_initialized(project_id, request)
    _ensure_narrative_contract(project_id, request)

    async def operation(run_id: str) -> object:
        return await request.app.state.workflows.run_short(project_id, run_id=run_id)

    return request.app.state.run_tasks.start(project_id, "short-story", operation)


@router.post("/projects/{project_id}/runs/setup", status_code=status.HTTP_202_ACCEPTED)
async def start_long_setup(project_id: str, request: Request) -> dict:
    _ensure_project(project_id, request)
    _ensure_confirmed_outline(project_id, request)
    _ensure_initialized(project_id, request)
    _ensure_narrative_contract(project_id, request)

    async def operation(run_id: str) -> object:
        return await request.app.state.workflows.run_long_setup(project_id, run_id=run_id)

    return request.app.state.run_tasks.start(project_id, "long-setup", operation)


@router.post("/projects/{project_id}/runs/materials-audit", status_code=status.HTTP_202_ACCEPTED)
async def start_materials_audit(project_id: str, request: Request) -> dict:
    _ensure_project(project_id, request)

    async def operation(run_id: str) -> object:
        return await request.app.state.workflows.run_materials_audit(project_id, run_id=run_id)

    resumable = next((run for run in request.app.state.registry.db.list_runs(project_id)
                      if run["workflow"] == "materials-audit"
                      and run["status"] in {"failed", "cancelled"}), None)
    if resumable:
        return request.app.state.run_tasks.resume(resumable["id"], operation)
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
    _ensure_confirmed_outline(project_id, request)
    _ensure_initialized(project_id, request)
    _ensure_narrative_contract(project_id, request)

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
    if run["workflow"] not in {
        "short-story", "materials-audit", "short-revision",
    }:
        raise HTTPException(status_code=409, detail={"code": "run_not_resumable"})

    revision_issue_ids = None
    if run["workflow"] == "short-revision":
        operations = RevisionOperations(
            request.app.state.registry.db,
            request.app.state.projects,
            request.app.state.workflows,
        )
        try:
            validated_run, revision_issue_ids = operations.validate_resume(run_id)
        except RevisionOperationError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from None
        if validated_run.get("status") == "completed":
            return validated_run

    async def operation(existing_run_id: str) -> object:
        if run["workflow"] == "short-revision":
            return await request.app.state.workflows.run_short_revision(
                run["project_id"], revision_issue_ids, run_id=existing_run_id,
            )
        if run["workflow"] == "materials-audit":
            return await request.app.state.workflows.run_materials_audit(
                run["project_id"], run_id=existing_run_id,
            )
        return await request.app.state.workflows.run_short(run["project_id"], run_id=existing_run_id)

    try:
        return request.app.state.run_tasks.resume(
            run_id, operation,
            allow_interrupted=run["workflow"] == "short-revision",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "run_not_resumable"}) from exc


@router.get("/projects/{project_id}/runs")
def list_runs(project_id: str, request: Request) -> list[dict]:
    return request.app.state.registry.db.list_runs(project_id)


@router.get("/projects/{project_id}/production-incidents")
def list_production_incidents(project_id: str, request: Request) -> dict:
    _ensure_project(project_id, request)
    return {
        "incidents": request.app.state.registry.db.list_production_incidents(project_id),
        "known_families": production_incident_catalog(),
    }


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
