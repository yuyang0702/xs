import json
import os
import re
import uuid
from pathlib import Path

from novel_flywheel.db import Database
from novel_flywheel.models import ModelGateway
from novel_flywheel.memory import StoryMemory
from novel_flywheel.projects import Project, ProjectStore
from novel_flywheel.prompts import REQUIRED_SKILLS, STAGE_SYSTEM
from novel_flywheel.skills import SkillGate
from novel_flywheel.storage import ProjectSnapshot, atomic_write


class WorkflowService:
    def __init__(self, db: Database, projects: ProjectStore, gateway: ModelGateway,
                 skills: SkillGate, crewai_data_dir: Path | None = None) -> None:
        self.db = db
        self.projects = projects
        self.gateway = gateway
        self.skills = skills
        self.crewai_data_dir = crewai_data_dir or db.path.parent / "crewai"
        self.memory = StoryMemory(db)

    async def run_short(self, project_id: str, use_crewai: bool = True) -> dict:
        project = self.projects.get(project_id)
        if project.mode != "short":
            raise ValueError("Short-story workflow requires a short project")
        if use_crewai:
            return await self._run_in_crewai(lambda: self._short_pipeline(project))
        return await self._short_pipeline(project)

    async def run_chapter(self, project_id: str, chapter_goal: str,
                          use_crewai: bool = True) -> dict:
        project = self.projects.get(project_id)
        if project.mode != "long":
            raise ValueError("Long chapter workflow requires a long project")
        pipeline = lambda: self._chapter_pipeline(project, chapter_goal)
        return await self._run_in_crewai(pipeline) if use_crewai else await pipeline()

    async def run_long_setup(self, project_id: str, use_crewai: bool = True) -> dict:
        project = self.projects.get(project_id)
        if project.mode != "long":
            raise ValueError("Long setup workflow requires a long project")
        pipeline = lambda: self._long_setup_pipeline(project)
        return await self._run_in_crewai(pipeline) if use_crewai else await pipeline()

    async def _long_setup_pipeline(self, project: Project) -> dict:
        run_id = uuid.uuid4().hex
        run_path = project.path / "runs" / run_id
        (run_path / "outputs").mkdir(parents=True)
        (run_path / "receipts").mkdir()
        self.db.create_run(run_id, project.id, "long-setup")
        outline_path = project.path / "outline.md"
        canon_path = project.path / "memory" / "canon.json"
        snapshot = ProjectSnapshot.create(
            project.path, project.path / "snapshots" / run_id, [outline_path, canon_path],
        )
        try:
            constraints = self.projects.load_constraints(project.id)
            brief = (
                "Create a complete book bible with fixed ending, protagonist arc, act structure, "
                "3-5 volumes, chapter map, hooks, foreshadowing, characters, relationships, world rules, "
                "timeline and knowledge boundaries.\n\n" +
                json.dumps(project.metadata, ensure_ascii=False, indent=2)
            )
            outline = await self._stage(run_id, run_path, project, "planning", constraints, brief)
            review = self._review(await self._stage(
                run_id, run_path, project, "review", constraints, outline,
            ))
            if review["score"] < 80 or review["hard_fail"]:
                raise RuntimeError("Book setup review did not pass")
            canon = self._json_object(await self._stage(
                run_id, run_path, project, "maintenance", constraints, outline,
            ))
            if not isinstance(canon.get("facts"), list):
                raise ValueError("Maintenance output must contain a facts array")
            atomic_write(outline_path, outline)
            atomic_write(canon_path, json.dumps(canon, ensure_ascii=False, indent=2))
            for index, fact in enumerate(canon["facts"]):
                if isinstance(fact, dict):
                    key = str(fact.get("fact_key") or f"setup.{index}")
                    value = str(fact.get("value") or fact.get("fact") or "")
                    self.memory.add_fact(project.id, key, value, True, "book-setup")
            self._post_write_maintenance(run_id, project)
            self.db.update_run(run_id, "completed", "archive")
            return self.db.get_run(run_id) or {"id": run_id, "status": "completed"}
        except Exception as exc:
            snapshot.restore()
            self.db.update_run(run_id, "failed", error=str(exc))
            raise

    async def _chapter_pipeline(self, project: Project, chapter_goal: str) -> dict:
        numbers = [
            int(match.group(1)) for path in project.path.joinpath("chapters").glob("chapter-*.md")
            if (match := re.fullmatch(r"chapter-(\d+)\.md", path.name))
        ]
        chapter_number = max(numbers, default=0) + 1
        chapter_id = f"chapter-{chapter_number:02d}"
        chapter_path = project.path / "chapters" / f"{chapter_id}.md"
        canon_path = project.path / "memory" / "canon.json"
        run_id = uuid.uuid4().hex
        run_path = project.path / "runs" / run_id
        (run_path / "outputs").mkdir(parents=True)
        (run_path / "receipts").mkdir()
        self.db.create_run(run_id, project.id, "long-chapter")
        snapshot = ProjectSnapshot.create(
            project.path, project.path / "snapshots" / run_id, [chapter_path, canon_path],
        )
        try:
            constraints = self.projects.load_constraints(project.id)
            context = self.memory.context(project.id, chapter_goal)
            brief = json.dumps({
                "chapter_number": chapter_number,
                "goal": chapter_goal,
                "project": project.metadata,
                "retrieved_memory": context,
            }, ensure_ascii=False, indent=2)
            plan = await self._stage(run_id, run_path, project, "planning", constraints, brief)
            draft = await self._stage(run_id, run_path, project, "draft", constraints, plan)
            review = self._review(await self._stage(
                run_id, run_path, project, "review", constraints,
                f"MEMORY:\n{json.dumps(context, ensure_ascii=False)}\n\nDRAFT:\n{draft}",
            ))
            polished = await self._stage(
                run_id, run_path, project, "polish", constraints,
                f"DRAFT:\n{draft}\n\nREVIEW:\n{json.dumps(review, ensure_ascii=False)}",
            )
            final_review = None
            for attempt in range(3):
                final_review = self._review(await self._stage(
                    run_id, run_path, project, "final_review", constraints, polished,
                    suffix=f"-{attempt + 1}" if attempt else "",
                ))
                if final_review["score"] >= 80 and not final_review["hard_fail"]:
                    break
                if attempt < 2:
                    polished = await self._stage(
                        run_id, run_path, project, "polish", constraints,
                        f"MANUSCRIPT:\n{polished}\n\nFINAL REVIEW:\n"
                        f"{json.dumps(final_review, ensure_ascii=False)}",
                        suffix=f"-{attempt + 2}",
                    )
            if final_review is None or final_review["score"] < 80 or final_review["hard_fail"]:
                raise RuntimeError("Final review did not pass after three rounds")
            canon = self._json_object(await self._stage(
                run_id, run_path, project, "maintenance", constraints, polished,
            ))
            if not isinstance(canon.get("facts"), list):
                raise ValueError("Maintenance output must contain a facts array")
            atomic_write(chapter_path, self._chapter_file(project, polished, chapter_number))
            atomic_write(canon_path, json.dumps(canon, ensure_ascii=False, indent=2))
            self._post_write_maintenance(run_id, project)
            self.memory.index_chapter(project.id, chapter_id, chapter_number, polished, chapter_goal)
            if isinstance(canon.get("state"), dict):
                self.memory.save_state(project.id, chapter_id, canon["state"])
            self.db.update_run(run_id, "completed", "archive")
            return self.db.get_run(run_id) or {"id": run_id, "status": "completed"}
        except Exception as exc:
            snapshot.restore()
            self.db.update_run(run_id, "failed", error=str(exc))
            raise

    async def _short_pipeline(self, project: Project) -> dict:
        run_id = uuid.uuid4().hex
        run_path = project.path / "runs" / run_id
        (run_path / "outputs").mkdir(parents=True)
        (run_path / "receipts").mkdir()
        self.db.create_run(run_id, project.id, "short-story")
        formal = [
            project.path / "manuscript" / "story.md",
            project.path / "chapters" / "chapter-01.md",
            project.path / "memory" / "canon.json",
        ]
        snapshot = ProjectSnapshot.create(project.path, project.path / "snapshots" / run_id, formal)
        try:
            constraints = self.projects.load_constraints(project.id)
            brief = json.dumps(project.metadata, ensure_ascii=False, indent=2)
            plan = await self._stage(run_id, run_path, project, "planning", constraints, brief)
            draft = await self._stage(run_id, run_path, project, "draft", constraints, plan)
            review_text = await self._stage(run_id, run_path, project, "review", constraints, draft)
            review = self._review(review_text)
            polished = await self._stage(
                run_id, run_path, project, "polish", constraints,
                f"DRAFT:\n{draft}\n\nREVIEW:\n{json.dumps(review, ensure_ascii=False)}",
            )
            final_review = None
            for attempt in range(3):
                final_review_text = await self._stage(
                    run_id, run_path, project, "final_review", constraints, polished,
                    suffix=f"-{attempt + 1}" if attempt else "",
                )
                final_review = self._review(final_review_text)
                if final_review["score"] >= 80 and not final_review["hard_fail"]:
                    break
                if attempt < 2:
                    polished = await self._stage(
                        run_id, run_path, project, "polish", constraints,
                        f"MANUSCRIPT:\n{polished}\n\nFINAL REVIEW:\n"
                        f"{json.dumps(final_review, ensure_ascii=False)}",
                        suffix=f"-{attempt + 2}",
                    )
            if final_review is None or final_review["score"] < 80 or final_review["hard_fail"]:
                raise RuntimeError("Final review did not pass after three rounds")
            canon_text = await self._stage(run_id, run_path, project, "maintenance", constraints, polished)
            canon = self._json_object(canon_text)
            if not isinstance(canon.get("facts"), list):
                raise ValueError("Maintenance output must contain a facts array")
            atomic_write(formal[0], polished)
            atomic_write(formal[1], self._chapter_file(project, polished))
            atomic_write(formal[2], json.dumps(canon, ensure_ascii=False, indent=2))
            self._post_write_maintenance(run_id, project)
            self.db.update_run(run_id, "completed", "archive")
            return self.db.get_run(run_id) or {"id": run_id, "status": "completed"}
        except Exception as exc:
            snapshot.restore()
            self.db.update_run(run_id, "failed", error=str(exc))
            raise

    async def _stage(self, run_id: str, run_path: Path, project: Project, stage: str,
                     constraints: str, user: str, suffix: str = "") -> str:
        self.db.update_run(run_id, "running", stage)
        required = REQUIRED_SKILLS[stage]
        commands = None
        cwd = None
        skill = self.skills.skills().get("story-maintenance") if stage == "maintenance" else None
        if skill and skill.executable:
            commands = {"story-maintenance": ["scripts/story.js", "validate", "."]}
            cwd = project.path
        skill_run = self.skills.run_required(stage, required, commands, cwd)
        system = f"{STAGE_SYSTEM[stage]}\n\nHARD CONSTRAINTS:\n{constraints}\n\n{skill_run.prompt}"
        result = await self.gateway.complete(stage, system, user)
        name = f"{stage}{suffix}"
        atomic_write(run_path / "outputs" / f"{name}.md", result.text)
        receipt = {"model": result.receipt, "skills": [receipt.__dict__ for receipt in skill_run.receipts]}
        atomic_write(run_path / "receipts" / f"{name}.json", json.dumps(receipt, ensure_ascii=False, indent=2))
        return result.text

    def _post_write_maintenance(self, run_id: str, project: Project) -> None:
        skill = self.skills.skills().get("story-maintenance")
        if not skill or not skill.executable:
            return
        for command in (
            ["scripts/story.js", "wordcount", ".", "--write"],
            ["scripts/story.js", "reindex", "."],
            ["scripts/story.js", "validate", "."],
        ):
            self.skills.run_required("archive", ["story-maintenance"], {"story-maintenance": command}, project.path)

    async def _run_in_crewai(self, pipeline):
        self.crewai_data_dir.mkdir(parents=True, exist_ok=True)
        os.environ["CREWAI_STORAGE_DIR"] = str(self.crewai_data_dir / "storage")
        os.environ["LOCALAPPDATA"] = str(self.crewai_data_dir)
        os.environ["OTEL_SDK_DISABLED"] = "true"
        from crewai.flow.flow import Flow, start

        class RuntimeFlow(Flow):
            @start()
            async def execute(self):
                return await pipeline()

        return await RuntimeFlow().kickoff_async()

    @staticmethod
    def _json_object(text: str) -> dict:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
        value = json.loads(cleaned)
        if not isinstance(value, dict):
            raise ValueError("Model output must be a JSON object")
        return value

    @classmethod
    def _review(cls, text: str) -> dict:
        review = cls._json_object(text)
        score = review.get("score")
        if not isinstance(score, (int, float)) or not 0 <= score <= 100:
            raise ValueError("Review score must be between 0 and 100")
        review.setdefault("hard_fail", False)
        review.setdefault("issues", [])
        return review

    @staticmethod
    def _chapter_file(project: Project, text: str, number: int = 1) -> str:
        return (
            f"---\ntitle: {project.title}\nnumber: {number}\npov: {project.metadata['pov']}\n"
            "locations: []\ncharacters: []\narcs-advanced: []\nstatus: final\nword-count: 0\n---\n\n"
            f"# Chapter {number}: {project.title}\n\n## Chapter Text\n\n{text}\n"
        )
