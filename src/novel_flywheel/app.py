from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from novel_flywheel.api.providers import router as providers_router
from novel_flywheel.api.projects import router as projects_router
from novel_flywheel.api.runs import router as runs_router
from novel_flywheel.api.skills import router as skills_router
from novel_flywheel.config import default_settings
from novel_flywheel.db import Database
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.models import ModelGateway
from novel_flywheel.projects import ProjectStore
from novel_flywheel.secrets import KeyringSecretStore, SecretStore
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.workflows import WorkflowService


def create_app(db: Database | None = None, secrets: SecretStore | None = None,
               skill_roots: list[Path] | None = None, workspace_root: Path | None = None,
               root_constraints: list[Path] | None = None,
               workflow_service: object | None = None) -> FastAPI:
    app = FastAPI(title="Novel Flywheel Console")
    if db is None:
        db = Database(default_settings().database_path)
    db.migrate()
    app.state.registry = ProviderRegistry(db, secrets or KeyringSecretStore())
    settings = default_settings()
    app.state.projects = ProjectStore(
        db, workspace_root or settings.data_dir / "projects", root_constraints or _default_constraints(),
    )
    roots = skill_roots or [Path.home() / ".codex" / "skills", Path.cwd() / ".agents" / "skills"]
    app.state.skill_gate = SkillGate(db, SkillScanner(roots))
    app.state.workflows = workflow_service or WorkflowService(
        db, app.state.projects, ModelGateway(db, app.state.registry), app.state.skill_gate,
        settings.data_dir / "crewai",
    )
    app.include_router(providers_router)
    app.include_router(projects_router)
    app.include_router(runs_router)
    app.include_router(skills_router)
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
