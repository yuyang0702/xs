from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from novel_flywheel.skills import SkillGate


router = APIRouter(prefix="/api", tags=["skills"])


def _conflicts(instructions: str) -> list[dict[str, str]]:
    text = instructions.lower()
    conflicts = []
    if any(term in text for term in ("多用短句", "大量短句", "短句为主", "use short sentences")):
        conflicts.append({
            "code": "fragmented_prose",
            "message": "短句导向可能与项目的连续碎短句治理规则冲突。",
        })
    if any(term in text for term in ("模仿指定作者", "模仿某位作者", "in the style of")):
        conflicts.append({
            "code": "author_imitation",
            "message": "作者模仿要求与范文笔感的非复刻约束冲突。",
        })
    if any(term in text for term in ("直接修改正式稿", "直接覆盖正式稿", "overwrite the manuscript")):
        conflicts.append({
            "code": "direct_formal_write",
            "message": "直接写正式稿会绕过 Runtime 的候选、校验和提交流程。",
        })
    return conflicts


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
        "has_scripts": skill.has_scripts,
        "conflicts": _conflicts(skill.instructions),
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


class RuntimeRun(BaseModel):
    answers: dict = {}


@router.post("/projects/{project_id}/skill-runtime/{skill_name}")
async def run_skill_runtime(project_id: str, skill_name: str, payload: RuntimeRun,
                            request: Request) -> dict:
    try:
        return await request.app.state.skill_runtime.run(project_id, skill_name, payload.answers)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "skill_not_found", "message": str(exc)}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail={"code": "skill_contract_required", "message": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail={"code": "skill_runtime_failed", "message": str(exc)}) from exc


@router.get("/projects/{project_id}/locks")
def list_project_locks(project_id: str, request: Request) -> list[dict]:
    return get_gate(request).db.list_locks(project_id)


@router.get("/projects/{project_id}/change-requests")
def list_change_requests(project_id: str, request: Request) -> list[dict]:
    return get_gate(request).db.list_change_requests(project_id)
