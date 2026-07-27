from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from novel_flywheel.api.providers import router as providers_router
from novel_flywheel.api.references import router as references_router
from novel_flywheel.api.learning import router as learning_router
from novel_flywheel.api.market import router as market_router
from novel_flywheel.api.projects import router as projects_router
from novel_flywheel.api.runs import router as runs_router
from novel_flywheel.api.skills import router as skills_router
from novel_flywheel.api.wizards import router as wizards_router
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
from novel_flywheel.tasks import RunTaskManager
from novel_flywheel.interviews import WizardInterviewService
from novel_flywheel.style_samples import StyleSampleService
from novel_flywheel.material_impacts import MaterialImpactService
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.learning import LearningSystem
from novel_flywheel.nlp_backend import LocalNLPManager
from novel_flywheel.market import MarketService
from novel_flywheel.market_baseline import MarketBaselineService
from novel_flywheel.analysis_tasks import ReferenceAnalysisTaskManager
from novel_flywheel.outlines import OutlineService


def create_app(db: Database | None = None, secrets: SecretStore | None = None,
               skill_roots: list[Path] | None = None, workspace_root: Path | None = None,
               root_constraints: list[Path] | None = None,
               workflow_service: object | None = None,
               interview_service: object | None = None,
               style_sample_service: object | None = None,
               reference_library: object | None = None,
               market_service: object | None = None) -> FastAPI:
    app = FastAPI(title="Novel Flywheel Console")

    @app.middleware("http")
    async def disable_local_asset_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response
    if db is None:
        db = Database(default_settings().database_path)
    db.migrate()
    db.interrupt_active_runs()
    app.state.registry = ProviderRegistry(db, secrets or KeyringSecretStore())
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
    roots = skill_roots or [Path.home() / ".codex" / "skills", Path.cwd() / ".agents" / "skills"]
    app.state.skill_gate = SkillGate(db, SkillScanner(roots))
    app.state.wizards = WizardService(
        db, app.state.projects,
        SkillFormCatalog(app.state.skill_gate, settings.data_dir / "skill-forms"),
    )
    gateway = ModelGateway(db, app.state.registry)
    app.state.learning = LearningSystem(db, app.state.references, app.state.projects, gateway)
    app.state.outlines = OutlineService(db, app.state.projects, gateway)
    app.state.learning.outlines = app.state.outlines
    app.state.reference_analysis_tasks = ReferenceAnalysisTaskManager()
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
    app.state.run_tasks = RunTaskManager(db)
    app.state.migrator = ProjectMigrator(
        lambda project, command: app.state.skill_runtime._run_story_cli(project, [command, "."]),
    )
    app.include_router(providers_router)
    app.include_router(references_router)
    app.include_router(market_router)
    app.include_router(learning_router)
    app.include_router(projects_router)
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
        return {"status": "ok"}

    return app


def _default_constraints() -> list[Path]:
    candidates = [
        Path.cwd() / "短篇小说写作约束与检查清单.md",
        Path.cwd().parent / "短篇小说写作约束与检查清单.md",
    ]
    return [path for path in candidates if path.is_file()]
