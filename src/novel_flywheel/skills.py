import hashlib
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from novel_flywheel.db import Database


@dataclass(frozen=True)
class Skill:
    name: str
    path: Path
    instructions: str
    content_hash: str
    executable: bool


@dataclass(frozen=True)
class SkillReceipt:
    skill_name: str
    content_hash: str
    status: str
    output: str


@dataclass(frozen=True)
class SkillRun:
    prompt: str
    receipts: list[SkillReceipt]


class SkillScanner:
    def __init__(self, roots: list[Path]) -> None:
        self.roots = roots

    def scan(self, extra_roots: list[Path] | None = None) -> list[Skill]:
        found: dict[str, Skill] = {}
        for root in [*self.roots, *(extra_roots or [])]:
            if not root.exists():
                continue
            for manifest in sorted(root.glob("*/SKILL.md")):
                instructions = manifest.read_text(encoding="utf-8")
                match = re.search(r"(?m)^name:\s*['\"]?([^'\"\r\n]+)", instructions)
                name = match.group(1).strip() if match else manifest.parent.name
                files = sorted(path for path in manifest.parent.rglob("*") if path.is_file())
                digest = hashlib.sha256()
                for path in files:
                    digest.update(path.relative_to(manifest.parent).as_posix().encode())
                    digest.update(path.read_bytes())
                executable = any(path.parts[-2:-1] == ("scripts",) for path in files)
                found[name] = Skill(name, manifest.parent, instructions, digest.hexdigest(), executable)
        return list(found.values())


class SkillGate:
    def __init__(self, db: Database, scanner: SkillScanner,
                 node_executable: Path | None = None) -> None:
        self.db = db
        self.scanner = scanner
        self.node_executable = node_executable or self._find_node()

    def skills(self, project_root: Path | None = None) -> dict[str, Skill]:
        extra = [project_root / ".agents" / "skills"] if project_root else []
        return {skill.name: skill for skill in self.scanner.scan(extra)}

    def run_required(self, stage: str, required: list[str],
                     commands: dict[str, list[str]] | None = None,
                     cwd: Path | None = None, project_root: Path | None = None) -> SkillRun:
        available = self.skills(project_root)
        missing = [name for name in required if name not in available]
        if missing:
            raise LookupError(f"Required Skills missing: {', '.join(missing)}")

        prompt: list[str] = []
        receipts: list[SkillReceipt] = []
        for name in required:
            skill = available[name]
            if not skill.executable:
                prompt.append(skill.instructions)
                receipts.append(self._record(stage, skill, "succeeded", "instructions-loaded"))
                continue
            if not self.db.is_skill_approved(name, skill.content_hash):
                raise PermissionError(f"Skill requires approval: {name}")
            argv = (commands or {}).get(name)
            if not argv:
                raise RuntimeError(f"Required executable Skill has no command: {name}")
            try:
                output = self._execute(skill, argv, cwd)
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or str(exc)).strip()[:8000]
                self._record(stage, skill, "failed", detail)
                raise RuntimeError(f"Required Skill failed: {name}: {detail}") from exc
            except Exception as exc:
                self._record(stage, skill, "failed", str(exc))
                raise RuntimeError(f"Required Skill failed: {name}") from exc
            receipts.append(self._record(stage, skill, "succeeded", output))
        return SkillRun("\n\n".join(prompt), receipts)

    def _execute(self, skill: Skill, argv: list[str], cwd: Path | None) -> str:
        target = (skill.path / argv[0]).resolve()
        if not target.is_relative_to(skill.path.resolve()) or not target.is_file():
            raise ValueError("Skill command must reference a file inside the Skill directory")
        command = [str(target), *argv[1:]]
        if target.suffix == ".py":
            command.insert(0, sys.executable)
        elif target.suffix == ".js":
            if self.node_executable is None:
                raise RuntimeError("Node.js runtime not found")
            command.insert(0, str(self.node_executable))
        completed = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=300, check=True,
        )
        return completed.stdout.strip()

    @staticmethod
    def _find_node() -> Path | None:
        configured = os.getenv("NOVEL_FLYWHEEL_NODE")
        if configured:
            return Path(configured)
        installed = shutil.which("node")
        if installed:
            return Path(installed)
        bundled = sorted((Path.home() / ".cache" / "codex-runtimes").glob(
            "*/dependencies/node/bin/node.exe"
        ))
        return bundled[-1] if bundled else None

    def _record(self, stage: str, skill: Skill, status: str, output: str) -> SkillReceipt:
        receipt = SkillReceipt(skill.name, skill.content_hash, status, output)
        self.db.save_skill_receipt(
            str(uuid.uuid4()), stage, skill.name, skill.content_hash, status, output,
        )
        return receipt
