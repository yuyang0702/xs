import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from novel_flywheel.api.errors import safe_http_exception
from novel_flywheel.revision_operations import (
    RevisionOperationError,
    RevisionOperations,
)
from novel_flywheel.production_incidents import production_incident_catalog
from novel_flywheel.narrative_contract import ensure_narrative_contract
from novel_flywheel.skill_runtime import initialization_answers, initialization_stage_issues

router = APIRouter(prefix="/api", tags=["runs"])


class ShortReceiptResume(BaseModel):
    """Explicit binding for the immutable Draft receipt-only operation.

    ``execute`` is deliberately opt-in.  A preflight never reserves a
    Provider dispatch; execution is admitted only by the native workflow
    operation-scope gate after the candidate and run identity are rechecked.
    """

    candidate_relative_path: str = Field(min_length=1, max_length=512)
    candidate_sha256: str = Field(min_length=64, max_length=64, pattern=r"[0-9a-fA-F]{64}")
    task_id: str = Field(min_length=1, max_length=128, pattern=r"segment-[0-9]{2}/sub-1")
    execute: bool = False
    max_dispatches: int = Field(default=0, ge=0, le=32)

    @field_validator("candidate_relative_path", "task_id")
    @classmethod
    def _trim_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must contain non-whitespace text")
        return normalized

    @field_validator("candidate_sha256")
    @classmethod
    def _normalize_hash(cls, value: str) -> str:
        return value.strip().lower()


class ReliabilityFoundationAttestation(BaseModel):
    """Bind already-validated Foundation evidence to this live worker.

    Foundation evidence is intentionally re-attested after a worker starts:
    the worker fencing identity is process-scoped, so an offline receipt cannot
    be copied into the live spine without this identity-bound step.
    """

    receipt_path: str = Field(min_length=1, max_length=2048)
    core_matrix_path: str = Field(min_length=1, max_length=2048)
    migration_first_path: str = Field(min_length=1, max_length=2048)
    migration_second_path: str = Field(min_length=1, max_length=2048)


def _ensure_project(project_id: str, request: Request) -> None:
    try:
        request.app.state.projects.get(project_id)
    except LookupError as exc:
        raise safe_http_exception(
            exc, status_code=404, boundary="run.project_lookup",
            code="project.not_found", family="request.resource_not_found",
            message="作品不存在或已被删除。",
        ) from exc


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

    return request.app.state.run_tasks.start(
        project_id, "short-story", operation, resume_payload={},
    )


@router.post("/projects/{project_id}/runs/setup", status_code=status.HTTP_202_ACCEPTED)
async def start_long_setup(project_id: str, request: Request) -> dict:
    _ensure_project(project_id, request)
    _ensure_confirmed_outline(project_id, request)
    _ensure_initialized(project_id, request)
    _ensure_narrative_contract(project_id, request)

    async def operation(run_id: str) -> object:
        return await request.app.state.workflows.run_long_setup(project_id, run_id=run_id)

    return request.app.state.run_tasks.start(
        project_id, "long-setup", operation, resume_payload={},
    )


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
    return request.app.state.run_tasks.start(
        project_id, "materials-audit", operation, resume_payload={},
    )


@router.post("/projects/{project_id}/runs/materials-repair", status_code=status.HTTP_202_ACCEPTED)
async def start_materials_repair(project_id: str, request: Request) -> dict:
    _ensure_project(project_id, request)

    async def operation(run_id: str) -> object:
        return await request.app.state.workflows.run_materials_repair(project_id, run_id=run_id)

    return request.app.state.run_tasks.start(
        project_id, "materials-repair", operation, resume_payload={},
    )


class ChapterRun(BaseModel):
    chapter_goal: str = Field(min_length=1, pattern=r".*\S.*")

    @field_validator("chapter_goal")
    @classmethod
    def _normalize_chapter_goal(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("chapter_goal must contain non-whitespace text")
        return normalized


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

    return request.app.state.run_tasks.start(
        project_id, "long-chapter", operation,
        resume_payload={"chapter_goal": payload.chapter_goal},
    )


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, request: Request) -> dict:
    try:
        return request.app.state.run_tasks.cancel(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"}) from exc


@router.post("/runs/{run_id}/short-receipt-resume")
async def resume_short_receipt(
    run_id: str, payload: ShortReceiptResume, request: Request,
) -> dict:
    """Use the normal API to resume one immutable Draft receipt boundary.

    This endpoint does not create a run and never invokes Draft generation.
    The service remains the sole owner of candidate binding, semantic receipt
    validation, operation scope, dispatch accounting, and checkpoint writes.
    """

    run = request.app.state.registry.db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"})
    if run.get("workflow") != "short-story":
        raise HTTPException(status_code=409, detail={"code": "run_not_short_story"})
    try:
        return await request.app.state.workflows.resume_short_receipt(
            str(run["project_id"]),
            run_id=run_id,
            candidate_relative_path=payload.candidate_relative_path,
            candidate_sha256=payload.candidate_sha256,
            task_id=payload.task_id,
            execute=payload.execute,
            max_dispatches=payload.max_dispatches,
        )
    except ValueError as exc:
        raise safe_http_exception(
            exc, status_code=422, boundary="run.short_receipt_resume.preflight",
            code="run.short_receipt_resume_invalid",
            family="request.domain_validation",
            message="候选稿或回执恢复边界未通过校验，未生成新的 Draft。",
        ) from exc


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
        # A resume already has durable task supervision and validated
        # checkpoints.  Re-enter the native pipeline directly so optional
        # CrewAI console/event rendering (which is encoding-sensitive on
        # Windows) cannot block recovery before the first business stage.
        return await request.app.state.workflows.run_short(
            run["project_id"], use_crewai=False, run_id=existing_run_id,
        )

    try:
        allow_waiting_user_credential = False
        allow_waiting_user_recoverable = False
        allow_interrupted_recoverable = False
        if run["status"] == "waiting_user":
            events = request.app.state.registry.db.list_run_events(run_id)
            allow_waiting_user_credential = any(
                isinstance(event.get("metadata"), dict)
                and event["metadata"].get("incident_family")
                == "provider.credentials_unavailable"
                for event in reversed(events[-8:])
            )
            supervision = request.app.state.registry.db.get_workflow_supervision(run_id)
            # A capability quarantine is an internal, bounded recovery state,
            # not a request for business authorization.  The native resume
            # path remains responsible for route validation and will fail
            # closed again if the configured routes are still unusable.
            allow_waiting_user_recoverable = bool(
                supervision
                and supervision.get("last_failure_class") == "capability"
            )
        elif run["status"] == "interrupted":
            supervision = request.app.state.registry.db.get_workflow_supervision(run_id)
            # A worker-outcome commit interruption is a restart-recoverable
            # internal state. Resume the validated checkpoint for short-story
            # runs; do not treat arbitrary interrupted workflows as resumable.
            allow_interrupted_recoverable = bool(
                run["workflow"] == "short-story"
                and supervision
                and supervision.get("state") == "interrupted"
                and supervision.get("restart_policy") == "recoverable"
            )
        return request.app.state.run_tasks.resume(
            run_id, operation,
            allow_interrupted=(
                run["workflow"] == "short-revision"
                or allow_interrupted_recoverable
            ),
            allow_waiting_user_credential=allow_waiting_user_credential,
            allow_waiting_user_recoverable=allow_waiting_user_recoverable,
            resume_payload=(
                {"issue_ids": list(revision_issue_ids or [])}
                if run["workflow"] == "short-revision" else {}
            ),
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
    run["supervision"] = request.app.state.registry.db.get_workflow_supervision(run_id)
    run["recovery_attempts"] = request.app.state.registry.db.list_workflow_attempts(run_id)
    reliability_spine = getattr(request.app.state, "reliability_spine", None)
    status_for_run = getattr(reliability_spine, "status_for_run", None)
    run["reliability"] = (
        status_for_run(run_id) if callable(status_for_run) else None
    )
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


@router.post("/reliability/foundation-attest")
def attest_live_foundation(
    payload: ReliabilityFoundationAttestation, request: Request,
) -> dict:
    """Bind Foundation Closure evidence to the currently loaded worker.

    The endpoint only accepts the already-produced, zero-Provider Foundation
    artifacts and delegates persistence to ``CanonicalDispatchCoordinator``;
    it never changes run state or creates a Provider intent.
    """

    paths = {
        "receipt": Path(payload.receipt_path),
        "core_matrix": Path(payload.core_matrix_path),
        "migration_first": Path(payload.migration_first_path),
        "migration_second": Path(payload.migration_second_path),
    }
    try:
        evidence = {
            key: json.loads(path.read_text(encoding="utf-8"))
            for key, path in paths.items()
        }
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise safe_http_exception(
            exc, status_code=422,
            boundary="run.foundation_attestation.evidence_read",
            code="foundation_evidence_unreadable",
            family="request.domain_validation",
            message="Foundation 验收证据无法读取或格式无效。",
        ) from exc
    receipt = evidence["receipt"]
    core = evidence["core_matrix"]
    first = evidence["migration_first"]
    second = evidence["migration_second"]
    required_receipt = {
        "FOUNDATION_CLOSURE": "PASS",
        "FULL_SHORT_CANONICAL_SPINE_OFFLINE": "PASS",
        "NEGATIVE_OLD_PATH_REACHABILITY_MATRIX": "PASS",
        "LEGACY_CHECKPOINT_MIGRATION_DRY_RUN": "PASS",
        "CUTOVER_RECEIPT_VALID": "YES",
        "RELEVANT_TEST_FAILURES_OPEN": 0,
        "UNKNOWN_TEST_FAILURE_IMPACT": 0,
    }
    if any(receipt.get(key) != value for key, value in required_receipt.items()):
        raise HTTPException(status_code=422, detail={
            "code": "foundation_evidence_not_pass",
        })
    if core.get("schema") != "ShortRuntimeReliabilityCoreMatrixV1" or core.get("all_checks_pass") is not True:
        raise HTTPException(status_code=422, detail={"code": "foundation_core_matrix_not_pass"})
    spine = request.app.state.reliability_spine
    current_release = spine.release.build_id
    if str(core.get("release_build_id") or "") != current_release:
        raise HTTPException(status_code=422, detail={
            "code": "foundation_core_matrix_stale_release",
            "current_release_build_id": current_release,
            "evidence_release_build_id": core.get("release_build_id"),
        })
    migration_ok = all((
        first.get("schema") == "LegacyCheckpointMigrationReceiptV1",
        second.get("schema") == "LegacyCheckpointMigrationReceiptV1",
        first.get("provider_http_performed") is False,
        second.get("provider_http_performed") is False,
        first.get("imported_physical_request_count") == 0,
        second.get("imported_physical_request_count") == 0,
        second.get("idempotent_replay") is True,
        second.get("business_changes") == 0,
    ))
    if not migration_ok:
        raise HTTPException(status_code=422, detail={"code": "foundation_migration_not_pass"})
    if any(str(item.get("migration_build_id") or "") != current_release for item in (first, second)):
        raise HTTPException(status_code=422, detail={
            "code": "foundation_migration_stale_release",
            "current_release_build_id": current_release,
        })
    gates = {key: "PASS" for key in (
        "F1_CANONICAL_EPISODE_IDENTITY", "F2_PHYSICAL_REQUEST_LEDGER",
        "F3_TYPED_FAILURE_GRAPH", "F4_NODE_LEVEL_DURABLE_STATE",
        "F5_CAPTURE_MANIFEST", "F6_SINGLE_RECOVERY_COORDINATOR",
        "F7_RELEASE_BUILD_IDENTITY_AND_WORKER_FENCING",
        "F8_PRODUCTION_SHAPED_CORE_MATRIX",
    )}
    try:
        spine.mark_foundation_gates(gates, evidence_refs=tuple(str(path) for path in paths.values()))
    except Exception as exc:
        raise safe_http_exception(
            exc, status_code=409,
            boundary="run.foundation_attestation.commit",
            code="foundation_attestation_conflict",
            family="execution.foundation_attestation",
            message="Foundation 验收证据与当前运行身份不一致。",
            recovery_action="rebuild_foundation_evidence_for_current_release",
        ) from exc
    return {
        "schema": "LiveFoundationAttestationV1",
        "foundation_gates": spine.foundation_gates(),
        "attestation": spine.attest(),
        "provider_http_performed": False,
    }
