from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from novel_flywheel.skills import SkillGate


router = APIRouter(prefix="/api", tags=["skills"])


def get_gate(request: Request) -> SkillGate:
    return request.app.state.skill_gate


@router.get("/skills")
def list_skills(request: Request) -> list[dict]:
    gate = get_gate(request)
    return [{
        "name": skill.name,
        "path": str(skill.path),
        "content_hash": skill.content_hash,
        "executable": skill.executable,
        "approved": not skill.executable or gate.db.is_skill_approved(skill.name, skill.content_hash),
    } for skill in gate.skills().values()]


class Approval(BaseModel):
    content_hash: str


@router.post("/skills/{name}/approve")
def approve_skill(name: str, payload: Approval, request: Request) -> dict:
    gate = get_gate(request)
    skill = gate.skills().get(name)
    if skill is None:
        raise HTTPException(status_code=404, detail={"code": "skill_not_found"})
    if skill.content_hash != payload.content_hash:
        raise HTTPException(status_code=409, detail={"code": "skill_version_changed"})
    gate.db.approve_skill(name, skill.content_hash)
    return {"name": name, "content_hash": skill.content_hash, "approved": True}


class StageRun(BaseModel):
    required: list[str]
    commands: dict[str, list[str]] = {}


@router.post("/skill-stages/{stage}/run")
def run_stage(stage: str, payload: StageRun, request: Request) -> dict:
    try:
        result = get_gate(request).run_required(stage, payload.required, payload.commands)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "required_skill_missing", "message": str(exc)}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail={"code": "skill_approval_required", "message": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=424, detail={"code": "required_skill_failed", "message": str(exc)}) from exc
    return {"prompt": result.prompt, "receipts": [asdict(receipt) for receipt in result.receipts]}
