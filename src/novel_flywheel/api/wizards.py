from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from typing import Literal


router = APIRouter(prefix="/api", tags=["wizards"])


class WizardCreate(BaseModel):
    mode: Literal["short", "long"]
    skills: list[str] | None = None


class WizardAnswers(BaseModel):
    answers: dict


def _service(request: Request):
    return request.app.state.wizards


@router.get("/wizards")
def list_wizards(request: Request) -> list[dict]:
    return _service(request).list()


@router.post("/wizards", status_code=status.HTTP_201_CREATED)
def create_wizard(payload: WizardCreate, request: Request) -> dict:
    return _service(request).create(payload.mode, payload.skills)


@router.get("/wizards/{wizard_id}")
def get_wizard(wizard_id: str, request: Request) -> dict:
    try:
        return _service(request).get(wizard_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "wizard_not_found"}) from exc


@router.put("/wizards/{wizard_id}/answers")
def save_answers(wizard_id: str, payload: WizardAnswers, request: Request) -> dict:
    try:
        return _service(request).save_answers(wizard_id, payload.answers)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "wizard_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_answers", "message": str(exc)}) from exc


@router.post("/wizards/{wizard_id}/confirm", status_code=status.HTTP_201_CREATED)
def confirm_wizard(wizard_id: str, request: Request) -> dict:
    try:
        project = _service(request).confirm(wizard_id)
        return {**project.metadata, "path": str(project.path)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "wizard_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "wizard_incomplete", "message": str(exc)}) from exc


@router.post("/wizards/{wizard_id}/analyze")
def analyze_wizard(wizard_id: str, request: Request) -> dict:
    try:
        return _service(request).analyze_gaps(wizard_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "wizard_not_found"}) from exc


@router.post("/projects/{project_id}/initialize-skills")
async def initialize_project_skills(project_id: str, request: Request) -> dict:
    try:
        project = request.app.state.projects.get(project_id)
        answers = project.metadata.get("story_requirements", {})
        results = []
        for skill_name in project.metadata.get("initialization_skills", []):
            results.append(await request.app.state.skill_runtime.run(project_id, skill_name, answers))
        return {"project_id": project_id, "status": "completed", "skills": results}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_or_skill_not_found", "message": str(exc)}) from exc
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "initialization_failed", "message": str(exc)}) from exc
