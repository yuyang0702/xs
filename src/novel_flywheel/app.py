from pathlib import Path

from fastapi import FastAPI

from novel_flywheel.api.providers import router as providers_router
from novel_flywheel.api.skills import router as skills_router
from novel_flywheel.config import default_settings
from novel_flywheel.db import Database
from novel_flywheel.providers.registry import ProviderRegistry
from novel_flywheel.secrets import KeyringSecretStore, SecretStore
from novel_flywheel.skills import SkillGate, SkillScanner


def create_app(db: Database | None = None, secrets: SecretStore | None = None,
               skill_roots: list[Path] | None = None) -> FastAPI:
    app = FastAPI(title="Novel Flywheel Console")
    if db is None:
        db = Database(default_settings().database_path)
    db.migrate()
    app.state.registry = ProviderRegistry(db, secrets or KeyringSecretStore())
    roots = skill_roots or [Path.home() / ".codex" / "skills", Path.cwd() / ".agents" / "skills"]
    app.state.skill_gate = SkillGate(db, SkillScanner(roots))
    app.include_router(providers_router)
    app.include_router(skills_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
