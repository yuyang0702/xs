from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from typing import Literal


router = APIRouter(prefix="/api", tags=["wizards"])


class WizardCreate(BaseModel):
    mode: Literal["short", "long"]
    skills: list[str] | None = None


class WizardAnswers(BaseModel):
    answers: dict


class InterviewTurn(BaseModel):
    message: str | None = None


class InterviewApply(BaseModel):
    field_ids: list[str]


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


@router.get("/wizards/{wizard_id}/interview")
def interview_history(wizard_id: str, request: Request) -> list[dict]:
    try:
        return request.app.state.interviews.history(wizard_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "wizard_not_found"}) from exc


@router.post("/wizards/{wizard_id}/interview", status_code=status.HTTP_201_CREATED)
async def interview_turn(wizard_id: str, payload: InterviewTurn, request: Request) -> dict:
    try:
        return await request.app.state.interviews.turn(wizard_id, payload.message)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "wizard_not_found", "message": str(exc)}) from exc
    except ValueError as exc:
        code = "invalid_model_output" if "valid JSON" in str(exc) else "invalid_interview"
        raise HTTPException(status_code=422 if code == "invalid_model_output" else 400,
                            detail={"code": code, "message": str(exc)}) from exc
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=422,
                            detail={"code": "interview_model_failed", "message": str(exc)}) from exc


@router.post("/wizards/{wizard_id}/interview/{message_id}/apply")
def apply_interview_suggestions(wizard_id: str, message_id: str,
                                payload: InterviewApply, request: Request) -> dict:
    try:
        return request.app.state.interviews.apply(wizard_id, message_id, payload.field_ids)
    except LookupError as exc:
        raise HTTPException(status_code=404,
                            detail={"code": "interview_message_not_found", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409,
                            detail={"code": "wizard_not_editable", "message": str(exc)}) from exc


@router.post("/projects/{project_id}/initialize-skills", status_code=status.HTTP_202_ACCEPTED)
async def initialize_project_skills(project_id: str, request: Request) -> dict:
    try:
        project = request.app.state.projects.get(project_id)
        answers = project.metadata.get("story_requirements", {})
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": str(exc)}) from exc

    async def operation(run_id: str) -> object:
        results = []
        for skill_name in project.metadata.get("initialization_skills", []):
            request.app.state.registry.db.update_run(run_id, "running", skill_name)
            request.app.state.registry.db.add_run_event(
                run_id, "info", "skill_started", f"开始执行 {skill_name}", stage=skill_name,
            )
            try:
                result = await request.app.state.skill_runtime.run(project_id, skill_name, answers)
            except Exception as exc:
                request.app.state.registry.db.add_run_event(
                    run_id, "error", "skill_failed", str(exc), stage=skill_name,
                )
                raise
            results.append(result)
            request.app.state.registry.db.add_run_event(
                run_id, "success", "skill_completed", f"{skill_name} 执行完成",
                stage=skill_name, metadata={"proposal_count": len(result.get("proposals", []))},
            )
        return results

    return request.app.state.run_tasks.start(project_id, "initialize-skills", operation)
