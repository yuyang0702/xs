from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api", tags=["learning"])


class RevisionPayload(BaseModel):
    action: Literal["confirm", "reject", "correct", "note"]
    data: dict[str, Any] = Field(default_factory=dict)


class AdoptionPayload(BaseModel):
    edits: dict[str, Any] = Field(default_factory=dict)


class RejectPayload(BaseModel):
    reason: str = Field(default="", max_length=1000)


class ArtifactPayload(BaseModel):
    data: dict[str, Any]


class SceneBriefPayload(BaseModel):
    outline: str = Field(min_length=1, max_length=500_000)


class OutlineCandidatePayload(BaseModel):
    outline: str = Field(min_length=1, max_length=500_000)


class OutlineGeneratePayload(BaseModel):
    brief: str = Field(default="", max_length=20_000)


class LineEditPayload(BaseModel):
    source: str = Field(min_length=1, max_length=30_000)
    candidate: str = Field(min_length=1, max_length=30_000)
    issues: list[str] = Field(min_length=1, max_length=20)
    locked_facts: list[str] = Field(default_factory=list, max_length=100)


class ModelLineEditPayload(BaseModel):
    source: str = Field(min_length=1, max_length=30_000)
    issues: list[str] = Field(min_length=1, max_length=20)
    locked_facts: list[str] = Field(default_factory=list, max_length=100)
    adjacent_context: str = Field(default="", max_length=10_000)


class MaterialChangePayload(BaseModel):
    source_path: str = Field(min_length=1, max_length=500)
    changes: list[str] = Field(min_length=1, max_length=100)


class NLPEnablePayload(BaseModel):
    enabled: bool


class WorkflowAnalysisPayload(BaseModel):
    enabled: bool


class DeleteMechanismsPayload(BaseModel):
    node_ids: list[str] = Field(min_length=1, max_length=500)


def _learning(request: Request):
    return request.app.state.learning


def _handle(call):
    try:
        return call()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _preflight_reference_roles(request: Request) -> None:
    labels = {
        "reference_analysis": "参考资料分窗分析",
        "reference_synthesis": "参考资料全文汇总",
    }
    registry = request.app.state.registry
    for role, label in labels.items():
        binding = registry.db.get_role_binding(role)
        if not binding:
            raise ValueError(f"{label}尚未配置主模型，请先到“模型与 API”完成角色绑定")
        provider = registry.db.get_provider(binding["primary_provider_id"])
        provider_name = provider["name"] if provider else "已绑定供应商"
        if not registry.secrets.get(binding["primary_provider_id"]):
            raise ValueError(f"{label}使用的 {provider_name} 缺少 API Key，请先到“模型与 API”补充密钥")
        registry.resolve(binding["primary_provider_id"], binding["primary_model_id"])


@router.post("/references/{source_id}/learn")
def analyze_reference(source_id: str, request: Request) -> dict:
    return _handle(lambda: _learning(request).analyze_reference(source_id))


@router.post("/references/{source_id}/model-learn", status_code=status.HTTP_202_ACCEPTED)
async def model_analyze_reference(source_id: str, request: Request) -> dict:
    try:
        request.app.state.references.get(source_id)
        _preflight_reference_roles(request)
        return request.app.state.reference_analysis_tasks.start(
            source_id,
            lambda progress: _learning(request).model_analyze_reference(source_id, progress),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/references/{source_id}/attraction-map")
def reference_attraction_map(source_id: str, request: Request):
    request.app.state.references.get(source_id)
    return _learning(request).attraction_map(source_id)


@router.get("/references/{source_id}/model-learn/status")
def model_analysis_status(source_id: str, request: Request) -> dict:
    request.app.state.references.get(source_id)
    return request.app.state.reference_analysis_tasks.get_for_source(source_id) or {
        "source_id": source_id, "status": "idle", "phase": "idle",
        "completed_windows": 0, "total_windows": 0,
    }


@router.delete("/references/{source_id}/model-learn/{task_id}")
def cancel_model_analysis(source_id: str, task_id: str, request: Request) -> dict:
    task = request.app.state.reference_analysis_tasks.cancel(task_id)
    if task["source_id"] != source_id:
        raise HTTPException(status_code=404, detail="analysis_task_not_found")
    return task


@router.post("/references/{source_id}/nlp")
def nlp_analyze_reference(source_id: str, request: Request) -> dict:
    try:
        text = request.app.state.references.read_text(source_id)
        return request.app.state.local_nlp.analyze(text)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/learning/mechanisms")
def list_mechanisms(
    request: Request, source_id: str | None = None,
    view: Literal["active", "rejected", "all"] = "active",
) -> list[dict]:
    return _learning(request).list_mechanisms(source_id, view)


@router.delete("/learning/mechanisms")
def delete_mechanisms(payload: DeleteMechanismsPayload, request: Request) -> dict:
    return _handle(lambda: _learning(request).delete_rejected_nodes(payload.node_ids))


@router.post("/learning/nodes/{node_id}/revisions")
def revise_node(node_id: str, payload: RevisionPayload, request: Request) -> dict:
    return _handle(lambda: _learning(request).revise_node(node_id, payload.action, payload.data))


@router.get("/projects/{project_id}/learning")
def project_learning(project_id: str, request: Request) -> dict:
    def result():
        migration = _learning(request).migrate_legacy_style(project_id)
        return {
            "adoptions": _learning(request).list_adoptions(project_id),
            "adoption_reviews": _learning(request).list_adoption_reviews(project_id),
            "artifacts": _learning(request).list_artifacts(project_id),
            "legacy_style_migration": migration,
        }
    return _handle(result)


@router.get("/projects/{project_id}/learning/workflow-analysis")
def workflow_analysis(project_id: str, request: Request) -> dict:
    project = request.app.state.projects.get(project_id)
    return {"enabled": bool(project.metadata.get("optimized_local_review_enabled", False))}


@router.put("/projects/{project_id}/learning/workflow-analysis")
def update_workflow_analysis(
    project_id: str, payload: WorkflowAnalysisPayload, request: Request,
) -> dict:
    project = request.app.state.projects.set_optimized_local_review(project_id, payload.enabled)
    return {"enabled": bool(project.metadata["optimized_local_review_enabled"])}


@router.get("/projects/{project_id}/learning/recommend/{node_id}")
def recommend(project_id: str, node_id: str, request: Request) -> dict:
    return _handle(lambda: _learning(request).recommend(project_id, node_id))


@router.post("/projects/{project_id}/learning/adoptions/{node_id}", status_code=status.HTTP_201_CREATED)
def adopt(project_id: str, node_id: str, payload: AdoptionPayload, request: Request) -> dict:
    return _handle(lambda: _learning(request).adopt(project_id, node_id, payload.edits))


@router.post("/projects/{project_id}/learning/rejections/{node_id}")
def reject(project_id: str, node_id: str, payload: RejectPayload, request: Request) -> dict:
    return _handle(lambda: _learning(request).reject_adoption(project_id, node_id, payload.reason))


@router.put("/projects/{project_id}/learning/prose-baseline")
def prose_baseline(project_id: str, payload: ArtifactPayload, request: Request) -> dict:
    return _handle(lambda: _learning(request).build_prose_baseline(project_id, payload.data))


@router.put("/projects/{project_id}/learning/voice-profiles")
def voice_profiles(project_id: str, payload: ArtifactPayload, request: Request) -> dict:
    return _handle(lambda: _learning(request).save_voice_profiles(project_id, payload.data))


@router.put("/projects/{project_id}/learning/epistemic-state")
def epistemic_state(project_id: str, payload: ArtifactPayload, request: Request) -> dict:
    return _handle(lambda: _learning(request).save_epistemic_state(project_id, payload.data.get("states", [])))


@router.post("/projects/{project_id}/learning/scene-briefs")
def scene_briefs(project_id: str, payload: SceneBriefPayload, request: Request) -> dict:
    return _handle(lambda: _learning(request).build_scene_briefs(project_id, payload.outline))


@router.post("/projects/{project_id}/learning/outline-candidates", status_code=status.HTTP_201_CREATED)
def outline_candidate(project_id: str, payload: OutlineCandidatePayload, request: Request) -> dict:
    return _handle(lambda: _learning(request).create_outline_candidate(project_id, payload.outline))


@router.post("/projects/{project_id}/learning/generate-outline", status_code=status.HTTP_201_CREATED)
async def generate_outline(project_id: str, payload: OutlineGeneratePayload, request: Request) -> dict:
    try:
        return await _learning(request).generate_outline_candidate(project_id, payload.brief)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/projects/{project_id}/learning/line-edits", status_code=status.HTTP_201_CREATED)
def line_edit(project_id: str, payload: LineEditPayload, request: Request) -> dict:
    return _handle(lambda: _learning(request).create_line_edit_candidate(
        project_id, payload.source, payload.candidate, issues=payload.issues,
        locked_facts=payload.locked_facts,
    ))


@router.post("/projects/{project_id}/learning/model-line-edit", status_code=status.HTTP_201_CREATED)
async def model_line_edit(project_id: str, payload: ModelLineEditPayload, request: Request) -> dict:
    try:
        return await _learning(request).model_line_edit(
            project_id, payload.source, issues=payload.issues, locked_facts=payload.locked_facts,
            adjacent_context=payload.adjacent_context,
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/projects/{project_id}/learning/material-change")
def material_change(project_id: str, payload: MaterialChangePayload, request: Request) -> dict:
    return _handle(lambda: _learning(request).mark_material_change(project_id, payload.source_path, payload.changes))


@router.get("/learning/feedback/metrics")
def feedback_metrics(request: Request) -> dict:
    return _learning(request).feedback_metrics()


@router.get("/settings/local-nlp")
def nlp_status(request: Request) -> dict:
    return request.app.state.local_nlp.status()


@router.post("/settings/local-nlp/install")
def nlp_install(request: Request) -> dict:
    return _handle(request.app.state.local_nlp.install)


@router.post("/settings/local-nlp/uninstall")
def nlp_uninstall(request: Request) -> dict:
    return _handle(request.app.state.local_nlp.uninstall)


@router.put("/settings/local-nlp")
def nlp_enable(payload: NLPEnablePayload, request: Request) -> dict:
    return _handle(lambda: request.app.state.local_nlp.enable(payload.enabled))
