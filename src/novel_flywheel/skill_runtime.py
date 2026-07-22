import fnmatch
import json
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from novel_flywheel.db import Database
from novel_flywheel.domain.models import ToolDefinition
from novel_flywheel.projects import Project
from novel_flywheel.storage import ProjectSnapshot, atomic_write
from novel_flywheel.models import ModelGateway
from novel_flywheel.projects import ProjectStore
from novel_flywheel.skills import SkillGate


CONTRACT_PATHS = {
    "story-init": ("story.md", "constraints.md", "*/_index.md", "continuity/state.md", "plot/timeline.md"),
    "character-management": ("characters/*.md",),
    "worldbuilding": ("worldbuilding/*.md", "worldbuilding/**/*.md"),
    "plot-structure": ("plot/*.md", "plot/**/*.md", "continuity/promises/*.md", "continuity/questions/*.md"),
}

ENTITY_FOLDERS = {
    "character": "characters",
    "location": "worldbuilding/locations",
    "system": "worldbuilding/systems",
    "arc": "plot/arcs",
    "chapter": "chapters",
    "scene": "scenes",
    "faction": "worldbuilding/factions",
    "artifact": "worldbuilding/artifacts",
}
ENTITY_ALIASES = {**{name: name for name in ENTITY_FOLDERS}, **{
    "characters": "character", "locations": "location", "systems": "system",
    "arcs": "arc", "chapters": "chapter", "scenes": "scene",
    "factions": "faction", "artifacts": "artifact",
}}


@dataclass(frozen=True)
class SkillContract:
    skill_name: str
    writable_patterns: tuple[str, ...]

    @classmethod
    def for_skill(cls, name: str) -> "SkillContract":
        return cls(name, CONTRACT_PATHS.get(name, ()))

    def permits(self, relative_path: str) -> bool:
        return any(fnmatch.fnmatchcase(relative_path, pattern) for pattern in self.writable_patterns)


class StoryCli:
    ALLOWED = ("reindex", "links", "validate", "wordcount")

    def __init__(self, project: Project, runner: Callable[[list[str]], str]) -> None:
        self.project = project
        self.runner = runner

    def run(self, command: str, arguments: list[str] | None = None) -> str:
        if command not in self.ALLOWED:
            raise ValueError(f"Story command not allowed: {command}")
        arguments = arguments or []
        if any(item.startswith(("/", "\\")) or ".." in PurePosixPath(item).parts for item in arguments):
            raise ValueError("Story command arguments must stay inside the project")
        return self.runner([command, ".", *arguments])


class SkillRuntimeToolbox:
    def __init__(self, db: Database, project: Project, execution_id: str,
                 contract: SkillContract, story_cli: StoryCli) -> None:
        self.db = db
        self.project = project
        self.execution_id = execution_id
        self.contract = contract
        self.story_cli = story_cli
        self.awaiting_question: str | None = None

    def definitions(self) -> list[ToolDefinition]:
        object_schema = {"type": "object", "additionalProperties": False}
        return [
            ToolDefinition(name="read_story_file", description="Read one project story file", input_schema={**object_schema, "properties": {"relative_path": {"type": "string"}}, "required": ["relative_path"]}),
            ToolDefinition(name="list_story_entities", description="List story entities", input_schema={**object_schema, "properties": {"entity_type": {"type": "string", "enum": list(ENTITY_FOLDERS)}}, "required": ["entity_type"]}),
            ToolDefinition(name="request_user_input", description="Request missing structured input", input_schema={"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}),
            ToolDefinition(name="create_file_proposal", description="Propose a complete story file", input_schema={"type": "object", "properties": {"relative_path": {"type": "string"}, "content": {"type": "string"}, "facts": {"type": "object"}}, "required": ["relative_path", "content"]}),
            ToolDefinition(name="update_file_proposal", description="Propose replacement content for a story file", input_schema={"type": "object", "properties": {"relative_path": {"type": "string"}, "content": {"type": "string"}, "facts": {"type": "object"}}, "required": ["relative_path", "content"]}),
            ToolDefinition(name="update_registry_proposal", description="Propose complete registry content", input_schema={"type": "object", "properties": {"relative_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["relative_path", "content"]}),
            ToolDefinition(name="check_story_links", description="Run deterministic link checks", input_schema=object_schema),
            ToolDefinition(name="run_story_command", description="Run a maintenance subcommand in the existing project. Pass only the subcommand, never the 'story' executable name and never 'init'.", input_schema={"type": "object", "properties": {"command": {"type": "string", "enum": list(StoryCli.ALLOWED)}, "arguments": {"type": "array", "items": {"type": "string"}}}, "required": ["command"]}),
            ToolDefinition(name="complete_skill", description="Mark the Skill execution complete", input_schema={"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}),
        ]

    def execute(self, name: str, arguments: dict) -> dict:
        if name == "read_story_file":
            path = self._safe_read_path(str(arguments.get("relative_path", "")))
            return {"relative_path": path.relative_to(self.project.path).as_posix(),
                    "content": path.read_text(encoding="utf-8")[:20000]}
        if name == "list_story_entities":
            entity = ENTITY_ALIASES.get(str(arguments.get("entity_type", "")).lower())
            folder = ENTITY_FOLDERS.get(entity or "")
            if not folder:
                raise ValueError(f"Unknown entity type; use one of: {', '.join(ENTITY_FOLDERS)}")
            return {"items": [path.stem for path in sorted((self.project.path / folder).glob("*.md")) if path.name != "_index.md"]}
        if name in {"create_file_proposal", "update_file_proposal", "update_registry_proposal"}:
            return self._propose(arguments)
        if name == "request_user_input":
            question = str(arguments.get("question", "")).strip()
            if not question:
                raise ValueError("Question is required")
            self.db.update_skill_execution(self.execution_id, "awaiting_user")
            self.awaiting_question = question
            return {"status": "awaiting_user", "question": question}
        if name == "check_story_links":
            return {"output": self.story_cli.run("links")}
        if name == "run_story_command":
            return {"output": self.story_cli.run(str(arguments.get("command", "")), arguments.get("arguments") or [])}
        if name == "complete_skill":
            self.db.update_skill_execution(self.execution_id, "validating")
            return {"status": "validating", "summary": str(arguments.get("summary", ""))}
        raise ValueError(f"Unknown runtime tool: {name}")

    def _propose(self, arguments: dict) -> dict:
        relative = self._normalize(str(arguments.get("relative_path", "")))
        if not self.contract.permits(relative):
            raise ValueError(f"Path not allowed for {self.contract.skill_name}: {relative}")
        content = arguments.get("content")
        if not isinstance(content, str) or not content or len(content) > 200000:
            raise ValueError("Proposal content is required and must be bounded")
        if relative.endswith(".md") and not content.startswith("---\n"):
            raise ValueError("Story markdown proposals require YAML frontmatter")
        locks = {item["key"]: item["value"] for item in self.db.list_locks(self.project.id)}
        for key, proposed in (arguments.get("facts") or {}).items():
            if key in locks and locks[key] != proposed:
                self.db.save_change_request(uuid.uuid4().hex, self.project.id, key, locks[key], proposed,
                                            f"Proposed by {self.contract.skill_name}")
                raise PermissionError(f"Proposed fact conflicts with locked value: {key}")
        proposal_id = uuid.uuid4().hex
        self.db.save_file_proposal(proposal_id, self.execution_id, relative, content, "pending")
        return {"proposal_id": proposal_id, "relative_path": relative, "status": "pending"}

    def apply(self) -> None:
        proposals = [item for item in self.db.list_file_proposals(self.execution_id) if item["status"] == "pending"]
        if not proposals:
            self.db.update_skill_execution(self.execution_id, "completed")
            return
        files = [self.project.path / item["relative_path"] for item in proposals]
        snapshot = ProjectSnapshot.create(
            self.project.path, self.project.path / "snapshots" / f"skill-{self.execution_id}", files,
        )
        try:
            for proposal, path in zip(proposals, files):
                atomic_write(path, proposal["content"])
            for command in ("reindex", "links", "validate"):
                self.story_cli.run(command)
            for proposal in proposals:
                self.db.update_file_proposal(proposal["id"], "applied")
            self.db.update_skill_execution(self.execution_id, "completed")
        except Exception as exc:
            snapshot.restore()
            for proposal in proposals:
                self.db.update_file_proposal(proposal["id"], "failed", str(exc))
            self.db.update_skill_execution(self.execution_id, "failed", str(exc))
            raise

    def finalize_on_tool_limit(self) -> str | None:
        if not self.db.list_file_proposals(self.execution_id):
            return None
        self.db.update_skill_execution(self.execution_id, "validating")
        return "Generated proposals are ready for local validation"

    def _safe_read_path(self, relative_path: str) -> Path:
        relative = self._normalize(relative_path)
        path = (self.project.path / relative).resolve()
        if not path.is_relative_to(self.project.path.resolve()) or not path.is_file():
            raise ValueError("Story file not found or outside project")
        if path.suffix not in {".md", ".json"}:
            raise ValueError("Story file type is not readable")
        return path

    @staticmethod
    def _normalize(value: str) -> str:
        if not value or "\\" in value:
            raise ValueError("Path not allowed")
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("Path not allowed")
        return pure.as_posix()


class SkillRuntimeService:
    def __init__(self, db: Database, projects: ProjectStore, gateway: ModelGateway,
                 skills: SkillGate) -> None:
        self.db = db
        self.projects = projects
        self.gateway = gateway
        self.skills = skills

    async def run(self, project_id: str, skill_name: str, answers: dict) -> dict:
        project = self.projects.get(project_id)
        skill = self.skills.skills(project.path).get(skill_name)
        if skill is None:
            raise LookupError(f"Skill not found: {skill_name}")
        contract = SkillContract.for_skill(skill_name)
        if not contract.writable_patterns:
            raise PermissionError(f"Skill contract is not approved for file operations: {skill_name}")
        execution_id = uuid.uuid4().hex
        self.db.create_skill_execution(execution_id, project.id, skill.name, skill.content_hash, "running")
        toolbox = SkillRuntimeToolbox(
            self.db, project, execution_id, contract,
            StoryCli(project, lambda command: self._run_story_cli(project, command)),
        )
        system = (
            "Execute the Skill using only the supplied runtime tools. Read existing story files, "
            "request input when essential, propose complete validated files, update registries, and "
            "call complete_skill. Never invent tool results or paths. The project structure already exists; "
            "do not initialize a new project. For run_story_command, pass only an allowed maintenance "
            "subcommand, never the 'story' executable name. If a tool returns an error, correct the call "
            "or use file proposals instead. Prefer supplied answers and existing indexes over exhaustive "
            "reads. Once the proposals are sufficient, call complete_skill immediately.\n\nSKILL:\n" + skill.instructions
        )
        try:
            result = await self.gateway.complete_with_tools(
                "planning", system, json.dumps(answers, ensure_ascii=False), toolbox,
                fallback_context=lambda: json.dumps(answers, ensure_ascii=False), run_id=execution_id,
            )
            if result.receipt.get("execution_mode") != "native_tools":
                raise RuntimeError("Skill Runtime requires native Tool Calling; prompt fallback cannot write files")
            if toolbox.awaiting_question and not self.db.list_file_proposals(execution_id):
                return {"id": execution_id, "status": "awaiting_user",
                        "question": toolbox.awaiting_question, "summary": result.text, "proposals": []}
            if not self.db.list_file_proposals(execution_id):
                raise RuntimeError("Skill completed without file proposals")
            toolbox.apply()
            return {"id": execution_id, "status": "completed", "summary": result.text,
                    "proposals": self.db.list_file_proposals(execution_id)}
        except Exception as exc:
            self.db.update_skill_execution(execution_id, "failed", str(exc))
            raise

    def _run_story_cli(self, project: Project, command: list[str]) -> str:
        skill = self.skills.skills(project.path).get("story-maintenance")
        if not skill or not skill.executable:
            raise RuntimeError("Executable story-maintenance Skill is required")
        argv = ["scripts/story.js", *command]
        result = self.skills.run_required(
            "skill-runtime", ["story-maintenance"], {"story-maintenance": argv},
            project.path, project.path,
        )
        return result.receipts[0].output
