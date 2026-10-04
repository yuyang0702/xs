from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from novel_flywheel.api.errors import safe_http_exception
from novel_flywheel.api.providers import router as providers_router
from novel_flywheel.api.references import router as references_router
from novel_flywheel.api.learning import router as learning_router
from novel_flywheel.api.market import router as market_router
from novel_flywheel.api.projects import (
    recover_candidate_publications,
    recover_project_file_state_mutations,
    router as projects_router,
)
from novel_flywheel.api.revisions import router as revisions_router
from novel_flywheel.api.runs import router as runs_router
from novel_flywheel.api.skills import router as skills_router
from novel_flywheel.api.wizards import (
    build_initialize_skills_operation,
    router as wizards_router,
)
from novel_flywheel.config import default_settings
from novel_flywheel.db import Database
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.models import ModelGateway
from novel_flywheel.projects import ProjectStore
from novel_flywheel.secrets import KeyringSecretStore, SecretStore
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.workflows import WorkflowService
from novel_flywheel.wizard import SkillFormCatalog, WizardService
from novel_flywheel.skill_runtime import SkillRuntimeService
from novel_flywheel.migration import ProjectMigrator
from novel_flywheel.tasks import ProjectRunActiveError, RunTaskManager
from novel_flywheel.interviews import WizardInterviewService
from novel_flywheel.style_samples import StyleSampleService
from novel_flywheel.material_impacts import MaterialImpactService
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.quality_references import QualityReferenceService
from novel_flywheel.learning import LearningSystem
from novel_flywheel.launcher import data_dir_fingerprint, runtime_fingerprint
from novel_flywheel.nlp_backend import LocalNLPManager
from novel_flywheel.market import MarketService
from novel_flywheel.market_baseline import MarketBaselineService
from novel_flywheel.analysis_tasks import ReferenceAnalysisTaskManager
from novel_flywheel.outlines import OutlineService
from novel_flywheel.runtime_fingerprint import (
    RuntimeFingerprintRecorderV1,
    route_role_binding_definition,
)
from novel_flywheel.reliability_spine import CanonicalDispatchCoordinator


@asynccontextmanager
async def _application_lifespan(app: FastAPI):
    """Own asynchronous recovery exactly once for each application instance."""

    if not getattr(app.state, "durable_recovery_started", False):
        app.state.durable_recovery_started = True
        app.state.run_tasks.recover_due_runs()
        app.state.reference_analysis_tasks.recover_pending()
    yield


def create_app(db: Database | None = None, secrets: SecretStore | None = None,
               skill_roots: list[Path] | None = None, workspace_root: Path | None = None,
               root_constraints: list[Path] | None = None,
               workflow_service: object | None = None,
               interview_service: object | None = None,
               style_sample_service: object | None = None,
               reference_library: object | None = None,
               market_service: object | None = None) -> FastAPI:
    app = FastAPI(title="Novel Flywheel Console", lifespan=_application_lifespan)

    @app.exception_handler(RequestValidationError)
    async def revision_validation_error(
        request: Request, exc: RequestValidationError,
    ):
        route = request.scope.get("route")
        if getattr(route, "path", None) in {
            "/api/projects/{project_id}/revisions",
            "/api/runs/{run_id}/revision/groups/{group_id}/adopt",
            "/api/runs/{run_id}/revision/groups/{group_id}/reject",
        }:
            return JSONResponse(status_code=422, content={"detail": {
                "code": "revision_payload_invalid",
                "message": "返修请求格式不正确，请检查后重试。",
            }})
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(ProjectRunActiveError)
    async def project_run_active_error(request: Request, exc: ProjectRunActiveError):
        projected = safe_http_exception(
            exc, status_code=409, boundary="run.project_writer_lease",
            code="project_run_active", family="runtime.concurrent_writer",
            message="作品当前已有活动任务，请等待完成后重试。",
            recovery_action="wait_for_active_run",
        )
        return JSONResponse(status_code=409, content={"detail": projected.detail})

    @app.middleware("http")
    async def disable_local_asset_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response
    if db is None:
        db = Database(default_settings().database_path)
    health_fingerprint = data_dir_fingerprint(db.path.parent)
    health_runtime_fingerprint = runtime_fingerprint()
    db.migrate()
    db.interrupt_active_runs()
    try:
        app.state.runtime_fingerprint_recorder = RuntimeFingerprintRecorderV1(
            db, db.path.parent,
        )
        db.set_run_lifecycle_observer(app.state.runtime_fingerprint_recorder)
        app.state.runtime_fingerprint_status = "available"
    except Exception:
        # Build identity is diagnostic for ordinary workflows. Collection and
        # storage failures must not change application startup or recovery.
        app.state.runtime_fingerprint_recorder = None
        app.state.runtime_fingerprint_status = "unknown_runtime"
    # Every production Provider request is admitted by the canonical spine.
    # Direct adapter/legacy entrypoints fail closed at the HTTP boundary.
    app.state.reliability_spine = CanonicalDispatchCoordinator(
        # Production app transport is fail-closed until the immutable
        # Foundation Gates record is present. Offline fixtures construct their
        # own coordinator and never inherit this authority.
        db.path.parent, require_release=True, require_foundation_gates=True,
        config_version=str(
            route_role_binding_definition(db).get("definition_sha256") or ""
        ),
    )
    app.state.registry = ProviderRegistry(
        db, secrets or KeyringSecretStore(), canonical_dispatch_required=True,
        canonical_runtime_path_id=(
            app.state.reliability_spine.release.runtime_path_id
        ),
        canonical_dispatch_failure_handler=(
            app.state.reliability_spine.record_old_path_invocation
        ),
    )
    settings = default_settings()
    app.state.references = reference_library or ReferenceLibrary(db, settings.data_dir / "references")
    app.state.local_nlp = LocalNLPManager(settings.data_dir / "local-nlp.json")
    app.state.market = market_service or MarketService(
        db, app.state.references, nlp_analyzer=app.state.local_nlp.analyze,
    )
    app.state.market_baselines = MarketBaselineService(db, app.state.references)
    app.state.projects = ProjectStore(
        db, workspace_root or settings.data_dir / "projects", root_constraints or _default_constraints(),
    )
    recover_candidate_publications(app.state.projects)
    recover_project_file_state_mutations(app.state.projects)
    app.state.quality_references = QualityReferenceService(
        db, app.state.references, app.state.projects,
    )
    roots = skill_roots or [Path.home() / ".codex" / "skills", Path.cwd() / ".agents" / "skills"]
    app.state.skill_gate = SkillGate(db, SkillScanner(roots))
    app.state.wizards = WizardService(
        db, app.state.projects,
        SkillFormCatalog(app.state.skill_gate, settings.data_dir / "skill-forms"),
    )
    gateway = ModelGateway(db, app.state.registry)
    gateway.dispatch_admitter = app.state.reliability_spine.admit
    app.state.learning = LearningSystem(db, app.state.references, app.state.projects, gateway)
    app.state.outlines = OutlineService(
        db, app.state.projects, gateway, local_nlp=app.state.local_nlp,
    )
    app.state.learning.outlines = app.state.outlines
    def resolve_reference_analysis(source_id: str):
        try:
            app.state.references.get(source_id)
        except LookupError:
            return None
        return lambda progress: app.state.learning.model_analyze_reference(
            source_id, progress,
        )

    app.state.reference_analysis_tasks = ReferenceAnalysisTaskManager(
        db, operation_resolver=resolve_reference_analysis,
    )
    app.state.material_impacts = MaterialImpactService(gateway)
    app.state.style_samples = style_sample_service or StyleSampleService(gateway)
    app.state.interviews = interview_service or WizardInterviewService(db, gateway)
    app.state.workflows = workflow_service or WorkflowService(
        db, app.state.projects, gateway, app.state.skill_gate,
        settings.data_dir / "crewai", local_nlp=app.state.local_nlp,
        references=app.state.references,
    )
    app.state.skill_runtime = SkillRuntimeService(
        db, app.state.projects, gateway, app.state.skill_gate,
    )
    def resolve_run_operation(run: dict, payload: dict):
        project_id = str(run["project_id"])
        workflow = str(run["workflow"])
        if workflow == "short-story":
            return lambda run_id: app.state.workflows.run_short(
                project_id, run_id=run_id,
            )
        if workflow == "long-setup":
            return lambda run_id: app.state.workflows.run_long_setup(
                project_id, run_id=run_id,
            )
        if workflow == "materials-audit":
            return lambda run_id: app.state.workflows.run_materials_audit(
                project_id, run_id=run_id,
            )
        if workflow == "materials-repair":
            return lambda run_id: app.state.workflows.run_materials_repair(
                project_id, run_id=run_id,
            )
        if workflow == "long-chapter" and str(payload.get("chapter_goal") or "").strip():
            chapter_goal = str(payload["chapter_goal"])
            return lambda run_id: app.state.workflows.run_chapter(
                project_id, chapter_goal, run_id=run_id,
            )
        if workflow == "short-revision" and isinstance(payload.get("issue_ids"), list):
            issue_ids = [str(item) for item in payload["issue_ids"]]
            return lambda run_id: app.state.workflows.run_short_revision(
                project_id, issue_ids, run_id=run_id,
            )
        if (
            workflow == "initialize-skills"
            and payload.get("version") == 1
            and isinstance(payload.get("answers"), dict)
            and isinstance(payload.get("learning_snapshot"), dict)
            and isinstance(payload.get("outline_sha256"), str)
        ):
            try:
                operation, _resume_payload = build_initialize_skills_operation(
                    project_id, SimpleNamespace(app=app),
                    frozen_answers=payload["answers"],
                    frozen_learning_snapshot=payload["learning_snapshot"],
                    expected_outline_sha256=payload["outline_sha256"],
                )
            except (HTTPException, LookupError, ValueError):
                return None
            return operation
        return None

    def evaluate_recovery_reentry(run_id: str) -> dict[str, object] | None:
        """Evaluate a blocked Short node without reopening the old run loop."""

        run = db.get_run(run_id)
        if not run or run.get("workflow") != "short-story":
            return None
        supervision = db.get_workflow_supervision(run_id)
        if not supervision:
            return None
        attempts = db.list_workflow_attempts(run_id)
        latest_metadata = {}
        for item in reversed(attempts):
            if isinstance(item.get("metadata"), dict) and item["metadata"]:
                latest_metadata = dict(item["metadata"])
                break
        stage = str(run.get("current_stage") or latest_metadata.get("stage") or "unknown")
        logical_node_id = str(
            latest_metadata.get("logical_node_id")
            or latest_metadata.get("durable_node_id")
            or f"{run_id}:{stage}"
        )
        node = app.state.reliability_spine.nodes.load(logical_node_id)
        if node is None:
            # Legacy terminal attempts may omit logical_node_id even though
            # the canonical physical ledger and durable node are complete.
            # Resolve only the ledger tail; an invalid tail remains blocked.
            node = app.state.reliability_spine.recovery_node_for_run(run_id)
            if node is None:
                return {
                    "schema": "RecoveryReentryEvaluationV1",
                    "action": "MIGRATION_REQUIRED",
                    "reason": "legacy_checkpoint_migration_required",
                    "condition_signature": str(supervision.get("last_failure_sha256") or ""),
                    "provider_intent_created": False,
                    "physical_dispatch_allowed": False,
                }
            logical_node_id = node.node_id
        bindings = db.list_role_bindings()
        config_version = hashlib.sha256(
            json.dumps(bindings, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        capability_snapshot = dict(latest_metadata.get("capability_snapshot") or {})
        # A valid checkpoint migration or prepared-work rebind is a real
        # recovery condition change. Include the durable node identity in the
        # re-entry signature so that an old signature cannot suppress the
        # first evaluation after stale prepared work has been re-materialized
        # under the current release. This keeps same-condition re-entry
        # suppression intact while allowing the documented cutover/migration
        # transition to proceed without a manual state edit.
        capability_snapshot.update({
            "durable_node_release_build_id": node.release_build_id,
            "durable_node_version": node.version,
        })
        metadata = {
            "project_id": run.get("project_id"), "run_id": run_id,
            "operation_run_id": run_id, "workflow_kind": "short-story",
            "stage": stage, "logical_node_id": logical_node_id,
            "candidate_sha256": node.candidate_sha256,
            "contract_name": latest_metadata.get("contract_name") or "short-runtime",
            "contract_version": latest_metadata.get("contract_version") or 1,
            # The durable node is the authoritative prepared-work identity.
            # A historical attempt may carry the route that created an old
            # prepared request; preferring that value would keep re-entry
            # signatures stale even after migration re-materialized the node
            # under the current user binding.
            "route_fingerprint": node.route_fingerprint or latest_metadata.get("route_fingerprint"),
            "capability_snapshot": capability_snapshot,
            "config_version": config_version,
            "failure_sha256": supervision.get("last_failure_sha256") or "",
        }
        return app.state.reliability_spine.evaluate_reentry(
            metadata, node_state=node.state,
            failure_class=str(supervision.get("last_failure_class") or ""),
            blocker_signature=str(supervision.get("last_failure_sha256") or ""),
        )

    app.state.run_tasks = RunTaskManager(
        db, operation_resolver=resolve_run_operation,
        reentry_evaluator=evaluate_recovery_reentry,
        execution_identity_binder=gateway.bind_workflow_execution_identity,
    )

    app.state.migrator = ProjectMigrator(
        lambda project, command: app.state.skill_runtime._run_story_cli(project, [command, "."]),
    )
    app.include_router(providers_router)
    app.include_router(references_router)
    app.include_router(market_router)
    app.include_router(learning_router)
    app.include_router(projects_router)
    app.include_router(revisions_router)
    app.include_router(runs_router)
    app.include_router(skills_router)
    app.include_router(wizards_router)
    static_root = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_root), name="static")

    @app.get("/", include_in_schema=False)
    def console() -> FileResponse:
        return FileResponse(static_root / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "novel-flywheel-console",
            "data_dir_fingerprint": health_fingerprint,
            "runtime_fingerprint": health_runtime_fingerprint,
        }

    return app


def _default_constraints() -> list[Path]:
    candidates = [
        Path.cwd() / "短篇小说写作约束与检查清单.md",
        Path.cwd().parent / "短篇小说写作约束与检查清单.md",
    ]
    return [path for path in candidates if path.is_file()]
