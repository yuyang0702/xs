from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path

    @property
    def database_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"


def default_settings() -> Settings:
    return Settings(Path.home() / ".novel-flywheel")

