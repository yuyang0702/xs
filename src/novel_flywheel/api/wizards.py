from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from typing import Literal
import asyncio
import json

from novel_flywheel.db import WIZARD_MUTATION_LOCK
from novel_flywheel.errors import describe_error
from novel_flywheel.skill_runtime import initialization_answers, initialization_stage_issues
from novel_flywheel.storage import ProjectSnapshot


router = APIRouter(prefix="/api", tags=["wizards"])


class WizardCreate(BaseModel):
    mode: Literal["short", "long"]
    skills: list[str] | None = None
    reference_source_ids: list[str] = Field(default_factory=list)


class WizardAnswers(BaseModel):
    answers: dict


class InterviewTurn(BaseModel):
    message: str | None = None


class InterviewApply(BaseModel):
    field_ids: list[str]


class WizardConfirm(BaseModel):
    selected_mechanism_ids: list[str] = []


def _service(request: Request):
    return request.app.state.wizards


def _wizard_or_404(request: Request, wizard_id: str) -> dict:
    try:
        return _service(request).get(wizard_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "wizard_not_found"},
        ) from exc


def _reference_creation_sources(request: Request, source_ids: list[str]) -> list[dict]:
    sources = []
    for source_id in dict.fromkeys(source_ids):
        try:
            source = request.app.state.references.get(source_id)
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={
                "code": "reference_not_found",
                "message": "有一篇所选资料不存在，请重新选择。",
            }) from exc
        if source.get("content_type") not in {"reference_work", "popular_sample"}:
            raise HTTPException(status_code=400, detail={
                "code": "reference_type_not_supported",
                "message": "所选资料不能用于创建作品，请选择参考作品或爆款样本。",
            })
        sources.append(source)
    return sources


@router.get("/wizards")
def list_wizards(request: Request) -> list[dict]:
    return _service(request).list()


@router.post("/wizards", status_code=status.HTTP_201_CREATED)
def create_wizard(payload: WizardCreate, request: Request) -> dict:
    with WIZARD_MUTATION_LOCK:
        source_ids = [source["id"] for source in _reference_creation_sources(
            request, payload.reference_source_ids,
        )]
        return _service(request).create(payload.mode, payload.skills, source_ids)


@router.get("/wizards/{wizard_id}")
def get_wizard(wizard_id: str, request: Request) -> dict:
    try:
        return _service(request).get(wizard_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "wizard_not_found"}) from exc


@router.delete("/wizards/{wizard_id}")
def delete_wizard(wizard_id: str, request: Request) -> dict:
    try:
        return _service(request).delete(wizard_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={
            "code": "wizard_not_found",
            "message": "草稿不存在或已经删除。",
        }) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={
            "code": "wizard_has_project",
            "message": "这份开书资料已经创建作品，不能从草稿列表删除。",
        }) from exc


@router.put("/wizards/{wizard_id}/answers")
def save_answers(wizard_id: str, payload: WizardAnswers, request: Request) -> dict:
    try:
        return _service(request).save_answers(wizard_id, payload.answers)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "wizard_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_answers", "message": str(exc)}) from exc


def _confirmed_mechanisms(request: Request, wizard: dict) -> list[dict]:
    source_ids = wizard.get("schema", {}).get("creation_context", {}).get(
        "reference_source_ids", [],
    )
    scoped_sources = _reference_creation_sources(request, source_ids)
    scoped_by_id = {source["id"]: source for source in scoped_sources}
    mechanisms_by_source = {source_id: [] for source_id in scoped_by_id}
    result = []
    for item in request.app.state.learning.list_mechanisms(view="active"):
        if item.get("status") != "confirmed" or item.get("node_type") != "mechanism":
            continue
        if scoped_sources:
            source = scoped_by_id.get(item.get("source_id"))
            if source is None:
                continue
        else:
            try:
                source = request.app.state.references.get(item["source_id"])
            except (LookupError, ValueError):
                continue
        if not scoped_sources and source.get("content_type") == "competitor_work":
            continue
        choice = {
            "id": item["id"],
            "name": item.get("data", {}).get("name") or "已确认写法",
            "use": item.get("data", {}).get("transfer_guidance") or "用于后续创作规则",
            "confidence": item.get("data", {}).get("confidence"),
            "source_id": source["id"],
            "source_title": source.get("title") or "参考资料",
        }
        if scoped_sources:
            mechanisms_by_source[source["id"]].append(choice)
            continue
        result.append(choice)
        if len(result) >= 12:
            break
    if scoped_sources:
        return [
            item
            for source in scoped_sources
            for item in mechanisms_by_source[source["id"]]
        ]
    return result


@router.get("/wizards/{wizard_id}/confirmed-mechanisms")
def confirmed_wizard_mechanisms(wizard_id: str, request: Request) -> list[dict]:
    with WIZARD_MUTATION_LOCK:
        return _confirmed_mechanisms(request, _wizard_or_404(request, wizard_id))


@router.post("/wizards/{wizard_id}/confirm", status_code=status.HTTP_201_CREATED)
def confirm_wizard(wizard_id: str, request: Request, payload: WizardConfirm | None = None) -> dict:
    try:
        with WIZARD_MUTATION_LOCK:
            wizard = _wizard_or_404(request, wizard_id)
            context = wizard.get("schema", {}).get("creation_context", {})
            recovering = bool(wizard.get("project_id"))
            if recovering and context.get("confirmation_effects_completed") is True:
                project = request.app.state.projects.get(wizard["project_id"])
                return {**project.metadata, "path": str(project.path)}
            values = {key: item.get("value") for key, item in wizard.get("answers", {}).items()}
            enabled = values.get("market_baseline_enabled") != "disabled"
            raw_key = values.get("market_baseline_key")
            try:
                key = json.loads(raw_key) if enabled and raw_key else None
            except (json.JSONDecodeError, TypeError) as exc:
                raise HTTPException(status_code=400, detail={
                    "code": "invalid_market_baseline", "message": "市场基线选择无效，请重新选择。",
                }) from exc
            if key is not None and not isinstance(key, dict):
                raise HTTPException(status_code=400, detail={
                    "code": "invalid_market_baseline", "message": "市场基线选择无效，请重新选择。",
                })
            if recovering:
                selected_ids = list(dict.fromkeys(
                    context.get("selected_mechanism_ids", []),
                ))
                project = request.app.state.projects.get(wizard["project_id"])
            else:
                selected_ids = list(dict.fromkeys(
                    (payload or WizardConfirm()).selected_mechanism_ids,
                ))
                if len(selected_ids) > 12:
                    raise HTTPException(status_code=400, detail={
                        "code": "invalid_learning_selection",
                        "message": "一次最多选择 12 条已确认写法。",
                    })
                choices = _confirmed_mechanisms(request, wizard)
                source_ids = context.get("reference_source_ids", [])
                confirmed_source_ids = {item["source_id"] for item in choices}
                if any(source_id not in confirmed_source_ids for source_id in source_ids):
                    raise HTTPException(status_code=400, detail={
                        "code": "reference_learning_not_ready",
                        "message": "有一篇所选资料还没有已确认写法，请先确认候选写法。",
                    })
                allowed = {item["id"] for item in choices}
                if any(node_id not in allowed for node_id in selected_ids):
                    raise HTTPException(status_code=400, detail={
                        "code": "invalid_learning_selection",
                        "message": "所选写法已失效，请返回确认页重新选择。",
                    })
                project = _service(request).confirm(wizard_id, selected_ids)
            learning = request.app.state.learning
            if key:
                baseline = request.app.state.market_baselines.build_baseline(key)
                current = learning.get_artifact(project.id, "market_baseline")
                if not current or current["status"] != "active" or current["data"] != baseline:
                    learning.save_artifact(project.id, "market_baseline", baseline)
            project = request.app.state.projects.set_market_baseline_selection(
                project.id, enabled=bool(enabled and key), key=key,
            )
            try:
                learning.ensure_adoptions(project.id, selected_ids)
            except (LookupError, ValueError) as exc:
                raise HTTPException(status_code=409, detail={
                    "code": "wizard_confirmation_recovery_blocked",
                    "message": "作品和已落地写法已保留；请前往学习库为该作品重新选择补充写法。",
                }) from exc
            _service(request).mark_confirmation_effects_completed(wizard_id)
            return {**project.metadata, "path": str(project.path)}
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "wizard_confirmation_changed",
            "message": "创建作品所需的数据已发生变化，请返回检查后重试。",
        }) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "wizard_incomplete", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail={
            "code": "wizard_confirmation_incomplete",
            "message": "作品已经保留，但创建收尾还没有完成。请再次点击确认继续。",
        }) from exc


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
    except Exception as exc:
        raise HTTPException(status_code=422, detail={
            "code": "interview_model_failed", "message": describe_error(exc),
        }) from exc


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
        current_outline = request.app.state.outlines.current(project_id)
        answers = initialization_answers(project, current_outline)
        learning_snapshot = request.app.state.learning.initialization_contexts(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": str(exc)}) from exc
    readiness = request.app.state.outlines.writing_readiness(project_id)
    if not current_outline["exists"]:
        raise HTTPException(status_code=409, detail={
            "code": "outline_confirmation_required",
            "message": "请先在“作品应用”中选择候选大纲并设为正式大纲，再准备人物和设定。",
        })
    if not readiness["ready"]:
        raise HTTPException(status_code=409, detail={
            "code": "outline_canon_conflict",
            "message": readiness["message"],
            "conflicts": readiness["conflicts"],
        })

    async def operation(run_id: str) -> object:
        results = []
        manifest = await request.app.state.outlines.material_manifest(project_id)
        runtime_answers = {**answers, "outline_manifest": manifest}
        learning_summary = learning_snapshot["summary"]
        versions = learning_snapshot["versions"]
        request.app.state.registry.db.add_run_event(
            run_id, "info", "initialization_learning_snapshot",
            "已固定本次使用的文笔和创作方法；正式大纲不会重新生成。",
            stage="starting", metadata={**versions, **learning_summary},
        )
        request.app.state.registry.db.add_run_event(
            run_id,
            "success" if manifest.get("_review", {}).get("status") == "model_confirmed" else "warning",
            "outline_manifest_ready",
            manifest.get("_review", {}).get("message")
            or "已核对正式大纲中的人物、地点、剧情、时间线、伏笔和创作约束。",
            stage="starting", metadata={
                key: len(value) for key, value in manifest.items() if isinstance(value, list)
            },
        )
        available = request.app.state.skill_gate.skills(project.path)
        managed_roots = (
            "characters", "worldbuilding", "plot", "continuity",
            "chapters", "glossary", "scenes",
        )
        managed_files = (project.path / "story.md", project.path / "constraints.md")
        before_paths = {
            path.resolve() for root in managed_roots
            for path in (project.path / root).rglob("*.md")
        }
        before_paths.update(path.resolve() for path in managed_files if path.is_file())
        batch_snapshot = ProjectSnapshot.create(
            project.path,
            project.path / "snapshots" / f"initialization-{run_id}",
            sorted(before_paths),
        )

        def rollback_batch(reason: str) -> None:
            batch_snapshot.restore()
            for root in managed_roots:
                for path in (project.path / root).rglob("*.md"):
                    if path.resolve() not in before_paths:
                        path.unlink()
            for path in managed_files:
                if path.is_file() and path.resolve() not in before_paths:
                    path.unlink()
            for completed in results:
                execution_id = completed.get("id") if isinstance(completed, dict) else None
                if not execution_id:
                    continue
                request.app.state.registry.db.update_file_proposals_status(
                    execution_id, "applied", "retained", reason,
                )
                request.app.state.registry.db.update_skill_execution(
                    execution_id, "recoverable", reason,
                )

        for skill_name in project.metadata.get("initialization_skills", []):
            skill = available.get(skill_name)
            completed_before = skill and request.app.state.registry.db.has_completed_skill_execution(
                project_id, skill_name, skill.content_hash,
            )
            issues = initialization_stage_issues(project, skill_name, runtime_answers)
            if completed_before and not issues:
                request.app.state.registry.db.add_run_event(
                    run_id, "success", "skill_skipped",
                    f"{skill_name} 已完整完成，本次无需重复生成。", stage=skill_name,
                )
                continue
            if completed_before and issues:
                request.app.state.registry.db.add_run_event(
                    run_id, "warning", "skill_incomplete",
                    f"发现此前资料不完整，正在继续补齐：{'；'.join(issues)}",
                    stage=skill_name, metadata={"issues": issues},
                )
            request.app.state.registry.db.update_run(run_id, "running", skill_name)
            request.app.state.registry.db.add_run_event(
                run_id, "info", "skill_started", f"开始执行 {skill_name}", stage=skill_name,
            )
            try:
                stage_context = learning_snapshot["stages"].get(skill_name, {
                    "source_versions": dict(versions), "prose_rules": [],
                    "creative_methods": [],
                })
                request.app.state.registry.db.add_run_event(
                    run_id, "info", "learning_context_loaded",
                    f"本阶段参考 {len(stage_context['prose_rules'])} 条文笔规则、"
                    f"{len(stage_context['creative_methods'])} 条创作方法。",
                    stage=skill_name, metadata={
                        "prose_rules": len(stage_context["prose_rules"]),
                        "creative_methods": len(stage_context["creative_methods"]),
                        "source_versions": stage_context.get("source_versions", {}),
                    },
                )
                result = await request.app.state.skill_runtime.run(
                    project_id, skill_name,
                    {**runtime_answers, "confirmed_learning_context": stage_context},
                    bootstrap=True,
                )
                if result.get("status") != "completed":
                    raise RuntimeError(
                        f"{skill_name} did not complete: {result.get('status', 'unknown')}"
                    )
            except asyncio.CancelledError:
                rollback_batch("初始化被取消，已保留可继续使用的候选资料")
                request.app.state.registry.db.add_run_event(
                    run_id, "warning", "initialization_rolled_back",
                    "初始化已停止，正式人物、设定和剧情资料已恢复；候选资料会在下次继续时复用。",
                    stage=skill_name,
                )
                raise
            except Exception as exc:
                rollback_batch("后续初始化阶段失败，已恢复批次开始前的正式资料")
                proposal_summary = getattr(exc, "proposal_summary", None)
                request.app.state.registry.db.add_run_event(
                    run_id, "error", "skill_failed", str(exc), stage=skill_name,
                    metadata={"proposal_summary": proposal_summary}
                    if isinstance(proposal_summary, dict) else None,
                )
                request.app.state.registry.db.add_run_event(
                    run_id, "warning", "initialization_rolled_back",
                    "本次初始化没有完整通过，已恢复开始前的人物、设定和剧情资料。",
                    stage=skill_name,
                )
                raise
            results.append(result)
            request.app.state.registry.db.add_run_event(
                run_id, "success", "skill_completed", f"{skill_name} 执行完成",
                stage=skill_name, metadata={"proposal_count": len(result.get("proposals", []))},
            )
        batch_snapshot.discard()
        return results

    return request.app.state.run_tasks.start(project_id, "initialize-skills", operation)
