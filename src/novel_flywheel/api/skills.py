from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from novel_flywheel.api.errors import safe_http_exception
from novel_flywheel.skills import SkillGate
from novel_flywheel.prompts import OPTIONAL_PROMPT_SKILLS, REQUIRED_SKILLS


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


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _production_stages(name: str) -> list[str]:
    return sorted({
        stage for stage, names in {
            **REQUIRED_SKILLS,
            **{
                stage: [*REQUIRED_SKILLS.get(stage, []), *optional]
                for stage, optional in OPTIONAL_PROMPT_SKILLS.items()
            },
        }.items() if name in names
    })


@router.get("/skills")
def list_skills(request: Request, project_id: str | None = None) -> list[dict]:
    gate = get_gate(request)
    project_root: Path | None = None
    if project_id:
        try:
            project_root = request.app.state.projects.get(project_id).path
        except LookupError as exc:
            raise safe_http_exception(
                exc, status_code=404, boundary="skill.source.project",
                code="project.not_found", family="request.resource_not_found",
                message="作品不存在，无法解析当前 Skill 来源。",
            ) from exc
    configured_roots = [Path(root) for root in gate.scanner.roots]
    global_root = configured_roots[0] if configured_roots else None
    repo_root = configured_roots[1] if len(configured_roots) > 1 else None
    project_skill_root = (
        project_root / ".agents" / "skills" if project_root else None
    )
    skills = gate.skills(project_root)
    return [{
        "name": skill.name,
        "path": str(skill.path),
        "effective_resolved_path": str(skill.path),
        "content_hash": skill.content_hash,
        "resolved_source_sha256": skill.resolved_source_sha256,
        "primary_document_sha256": skill.primary_document_sha256,
        "global_skill_root": str(global_root) if global_root else None,
        "repo_skill_root": str(repo_root) if repo_root else None,
        "project_skill_root": (
            str(project_skill_root) if project_skill_root else None
        ),
        "global_candidate_path": (
            str(global_root / skill.name) if global_root else None
        ),
        "global_candidate_exists": bool(
            global_root and (global_root / skill.name / "SKILL.md").is_file()
        ),
        "repo_candidate_path": (
            str(repo_root / skill.name) if repo_root else None
        ),
        "repo_candidate_exists": bool(
            repo_root and (repo_root / skill.name / "SKILL.md").is_file()
        ),
        "project_candidate_path": (
            str(project_skill_root / skill.name) if project_skill_root else None
        ),
        "project_candidate_exists": bool(
            project_skill_root
            and (project_skill_root / skill.name / "SKILL.md").is_file()
        ),
        "effective_source_kind": (
            "project_override"
            if project_skill_root and _same_path(
                skill.path, project_skill_root / skill.name,
            )
            else "repo"
            if repo_root and _same_path(skill.path, repo_root / skill.name)
            else "global_fallback"
            if global_root and _same_path(skill.path, global_root / skill.name)
            else "configured_root"
        ),
        "fallback_used": bool(
            global_root and _same_path(skill.path, global_root / skill.name)
        ),
        "resolution_precedence": "global_then_repo_then_project_last_wins",
        "production_stages": _production_stages(skill.name),
        "used_by_current_production": bool(_production_stages(skill.name)),
        "selective_or_hybrid_production_active": False,
        "executable": skill.executable,
        "has_scripts": skill.has_scripts,
        "conflicts": _conflicts(skill.instructions),
        "approved": not skill.executable or gate.db.is_skill_approved(skill.name, skill.content_hash),
    } for skill in skills.values()]


class Approval(BaseModel):
    content_hash: str
    project_id: str | None = None


@router.post("/skills/{name}/approve")
def approve_skill(name: str, payload: Approval, request: Request) -> dict:
    gate = get_gate(request)
    project_root = None
    if payload.project_id:
        try:
            project_root = request.app.state.projects.get(
                payload.project_id,
            ).path
        except LookupError as exc:
            raise safe_http_exception(
                exc, status_code=404, boundary="skill.approval.project",
                code="project.not_found", family="request.resource_not_found",
                message="作品不存在，无法授权当前 Skill 来源。",
            ) from exc
    skill = gate.skills(project_root).get(name)
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
        raise safe_http_exception(
            exc, status_code=404, boundary="skill.stage.lookup",
            code="skill.required_missing", family="request.resource_not_found",
            message="必需技能不存在或版本已经变化。",
        ) from exc
    except PermissionError as exc:
        raise safe_http_exception(
            exc, status_code=409, boundary="skill.stage.approval",
            code="skill.approval_required", family="runtime.permission_required",
            message="技能版本需要重新确认后才能执行。",
        ) from exc
    except RuntimeError as exc:
        raise safe_http_exception(
            exc, status_code=424, boundary="skill.stage.execution",
            code="skill.required_failed", family="runtime.skill_failure",
            message="必需技能执行失败，已保留当前项目资料。",
            retryable=True, recovery_action="review_skill_and_retry",
        ) from exc
    return {"prompt": result.prompt, "receipts": [asdict(receipt) for receipt in result.receipts]}


class RuntimeRun(BaseModel):
    answers: dict = {}


@router.post("/projects/{project_id}/skill-runtime/{skill_name}")
async def run_skill_runtime(project_id: str, skill_name: str, payload: RuntimeRun,
                            request: Request) -> dict:
    try:
        return await request.app.state.skill_runtime.run(project_id, skill_name, payload.answers)
    except LookupError as exc:
        raise safe_http_exception(
            exc, status_code=404, boundary="skill.runtime.lookup",
            code="skill.not_found", family="request.resource_not_found",
            message="技能不存在或版本已经变化。",
        ) from exc
    except PermissionError as exc:
        raise safe_http_exception(
            exc, status_code=409, boundary="skill.runtime.contract",
            code="skill.contract_required", family="runtime.permission_required",
            message="技能写入合同尚未确认，正式资料没有变化。",
        ) from exc
    except RuntimeError as exc:
        raise safe_http_exception(
            exc, status_code=422, boundary="skill.runtime.execution",
            code="skill.runtime_failed", family="runtime.skill_failure",
            message="技能执行失败，已保留候选和正式资料。",
            retryable=True, recovery_action="resume_skill_runtime",
        ) from exc


@router.get("/projects/{project_id}/locks")
def list_project_locks(project_id: str, request: Request) -> list[dict]:
    return get_gate(request).db.list_locks(project_id)


@router.get("/projects/{project_id}/change-requests")
def list_change_requests(project_id: str, request: Request) -> list[dict]:
    return get_gate(request).db.list_change_requests(project_id)
