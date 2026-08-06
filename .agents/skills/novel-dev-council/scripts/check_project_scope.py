from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


EXPECTED_REPOSITORY = "novel-flywheel-console"
REQUIRED_PATHS = (
    "AGENTS.md",
    "pyproject.toml",
    "src/novel_flywheel",
    "tests",
)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main() -> int:
    script_path = Path(__file__).resolve()
    repository = script_path.parents[4]
    cwd = Path.cwd().resolve()
    errors: list[str] = []

    if repository.name != EXPECTED_REPOSITORY:
        errors.append(
            f"skill repository is {repository.name!r}, expected {EXPECTED_REPOSITORY!r}"
        )

    missing = [item for item in REQUIRED_PATHS if not (repository / item).exists()]
    if missing:
        errors.append("missing sentinels: " + ", ".join(missing))

    try:
        cwd.relative_to(repository)
    except ValueError:
        errors.append(f"current directory is outside repository: {cwd}")

    top = _git(repository, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        errors.append("repository is not a readable Git worktree")
        git_root = None
    else:
        git_root = Path(top.stdout.strip()).resolve()
        if git_root != repository:
            errors.append(f"Git root mismatch: {git_root}")

    status = _git(repository, "status", "--porcelain=v1", "--untracked-files=all")
    dirty_entries = [line for line in status.stdout.splitlines() if line.strip()]
    if status.returncode != 0:
        errors.append("unable to inspect Git status")

    payload = {
        "ok": not errors,
        "repository": str(repository),
        "git_root": str(git_root) if git_root else None,
        "cwd": str(cwd),
        "dirty_entry_count": len(dirty_entries),
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
