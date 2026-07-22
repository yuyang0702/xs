import asyncio
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
from novel_flywheel.quality import normalize_review, quality_gate, reader_sample, select_route
from novel_flywheel.skills import SkillGate
from novel_flywheel.storage import ProjectSnapshot, atomic_write
from novel_flywheel.tools import StoryToolbox


class WorkflowService:
    def __init__(self, db: Database, projects: ProjectStore, gateway: ModelGateway,
                 skills: SkillGate, crewai_data_dir: Path | None = None) -> None:
        self.db = db
        self.projects = projects
        self.gateway = gateway
        self.skills = skills
        self.crewai_data_dir = crewai_data_dir or db.path.parent / "crewai"
        self.memory = StoryMemory(db)

    async def run_short(self, project_id: str, use_crewai: bool = True,
                        run_id: str | None = None) -> dict:
        project = self.projects.get(project_id)
        if project.mode != "short":
            raise ValueError("Short-story workflow requires a short project")
        if use_crewai:
            return await self._run_in_crewai(lambda: self._short_pipeline(project, run_id))
        return await self._short_pipeline(project, run_id)

    async def run_chapter(self, project_id: str, chapter_goal: str,
                          use_crewai: bool = True, run_id: str | None = None) -> dict:
        project = self.projects.get(project_id)
        if project.mode != "long":
            raise ValueError("Long chapter workflow requires a long project")
        pipeline = lambda: self._chapter_pipeline(project, chapter_goal, run_id)
        return await self._run_in_crewai(pipeline) if use_crewai else await pipeline()

    async def run_long_setup(self, project_id: str, use_crewai: bool = True,
                             run_id: str | None = None) -> dict:
        project = self.projects.get(project_id)
        if project.mode != "long":
            raise ValueError("Long setup workflow requires a long project")
        pipeline = lambda: self._long_setup_pipeline(project, run_id)
        return await self._run_in_crewai(pipeline) if use_crewai else await pipeline()

    async def _long_setup_pipeline(self, project: Project, run_id: str | None = None) -> dict:
        run_id, run_path = self._begin_run(project, "long-setup", run_id)
        outline_path = project.path / "outline.md"
        canon_path = project.path / "memory" / "canon.json"
        volumes_path = project.path / "memory" / "volumes.json"
        snapshot = ProjectSnapshot.create(
            project.path, project.path / "snapshots" / run_id, [outline_path, canon_path, volumes_path],
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
            if isinstance(canon.get("volumes"), list):
                atomic_write(volumes_path, json.dumps({"volumes": canon["volumes"]}, ensure_ascii=False, indent=2))
            for index, fact in enumerate(canon["facts"]):
                if isinstance(fact, dict):
                    key = str(fact.get("fact_key") or f"setup.{index}")
                    value = str(fact.get("value") or fact.get("fact") or "")
                    self.memory.add_fact(project.id, key, value, True, "book-setup")
            self._post_write_maintenance(run_id, project)
            self.db.update_run(run_id, "completed", "archive")
            return self.db.get_run(run_id) or {"id": run_id, "status": "completed"}
        except asyncio.CancelledError:
            snapshot.restore()
            self.db.update_run(run_id, "cancelled", error="Cancelled by user")
            raise
        except Exception as exc:
            snapshot.restore()
            self.db.update_run(run_id, "failed", error=str(exc))
            raise

    async def _chapter_pipeline(self, project: Project, chapter_goal: str,
                                run_id: str | None = None) -> dict:
        numbers = [
            int(match.group(1)) for path in project.path.joinpath("chapters").glob("chapter-*.md")
            if (match := re.fullmatch(r"chapter-(\d+)\.md", path.name))
        ]
        chapter_number = max(numbers, default=0) + 1
        chapter_id = f"chapter-{chapter_number:02d}"
        chapter_path = project.path / "chapters" / f"{chapter_id}.md"
        canon_path = project.path / "memory" / "canon.json"
        run_id, run_path = self._begin_run(project, "long-chapter", run_id)
        self._ensure_previous_volume_passed(project, chapter_number)
        snapshot = ProjectSnapshot.create(
            project.path, project.path / "snapshots" / run_id, [chapter_path, canon_path],
        )
        committed = False
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
            polished, _ = await self._quality_polish(
                run_id, run_path, project, constraints, draft, review,
                chapter_number=chapter_number,
                chapter_goal=chapter_goal,
                volume_end=self._is_volume_end(project, chapter_number),
            )
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
            committed = True
            await self._audit_volume_boundary(run_id, run_path, project, chapter_number, constraints)
            self.db.update_run(run_id, "completed", "archive")
            return self.db.get_run(run_id) or {"id": run_id, "status": "completed"}
        except asyncio.CancelledError:
            if not committed:
                snapshot.restore()
            self.db.update_run(run_id, "cancelled", error="Cancelled by user")
            raise
        except Exception as exc:
            if not committed:
                snapshot.restore()
            self.db.update_run(run_id, "failed", error=str(exc))
            raise

    async def _short_pipeline(self, project: Project, run_id: str | None = None) -> dict:
        run_id, run_path = self._begin_run(project, "short-story", run_id)
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
            polished, _ = await self._quality_polish(
                run_id, run_path, project, constraints, draft, review,
            )
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
        except asyncio.CancelledError:
            snapshot.restore()
            self.db.update_run(run_id, "cancelled", error="Cancelled by user")
            raise
        except Exception as exc:
            snapshot.restore()
            self.db.update_run(run_id, "failed", error=str(exc))
            raise

    async def _quality_polish(self, run_id: str, run_path: Path, project: Project,
                              constraints: str, draft: str, review: dict,
                              chapter_number: int | None = None,
                              chapter_goal: str = "", volume_end: bool = False) -> tuple[str, dict]:
        route = select_route(
            project.mode, chapter_number, chapter_goal, volume_end, review,
        )
        report = {
            "route": route,
            "initial_review": review,
            "reader_review": None,
            "final_attempts": [],
            "status": "running",
            "failure_reasons": [],
        }
        self._write_quality_report(run_path, report)
        self.db.add_run_event(
            run_id, "info", "quality_route",
            "已选择重点质量流程" if route["enhanced"] else "已选择标准质量流程",
            stage="quality", metadata=route,
        )
        self._quality_assessed_event(run_id, "editorial", review)

        reader_review = None
        if route["enhanced"]:
            self.db.add_run_event(
                run_id, "info", "quality_escalated", "正在执行目标读者模拟",
                stage="review", metadata={"reasons": route["reasons"]},
            )
            reader_review = await self._reader_review(
                run_id, run_path, project, constraints, draft,
            )
            report["reader_review"] = reader_review
            self._quality_assessed_event(run_id, "target_reader", reader_review)
            self._write_quality_report(run_path, report)

        findings = {"editorial": review, "target_reader": reader_review}
        polished = await self._stage(
            run_id, run_path, project, "polish", constraints,
            f"DRAFT:\n{draft}\n\nSTRUCTURED FINDINGS:\n"
            f"{json.dumps(findings, ensure_ascii=False)}",
        )

        reasons: list[str] = []
        for attempt in range(route["max_corrections"] + 1):
            final_review = self._review(await self._stage(
                run_id, run_path, project, "final_review", constraints, polished,
                suffix=f"-{attempt + 1}" if attempt else "",
            ))
            passed, reasons = quality_gate(final_review)
            report["final_attempts"].append({
                "attempt": attempt + 1,
                "review": final_review,
                "passed": passed,
                "reasons": reasons,
            })
            self._quality_assessed_event(run_id, "chief_editor", final_review, attempt + 1)
            self._write_quality_report(run_path, report)
            if passed:
                report["status"] = "passed"
                report["failure_reasons"] = []
                self._write_quality_report(run_path, report)
                self.db.add_run_event(
                    run_id, "success", "quality_gate", "质量门槛已通过",
                    stage="quality", metadata={
                        "attempt": attempt + 1,
                        "score": final_review["score"],
                        "dimensions": final_review["dimensions"],
                    },
                )
                return polished, report
            if attempt < route["max_corrections"]:
                self.db.add_run_event(
                    run_id, "warning", "quality_revision",
                    f"质量未达标，开始第 {attempt + 1} 次定向返工",
                    stage="polish", metadata={
                        "attempt": attempt + 1, "reasons": reasons,
                    },
                )
                polished = await self._stage(
                    run_id, run_path, project, "polish", constraints,
                    f"MANUSCRIPT:\n{polished}\n\nCHIEF EDITOR FINDINGS:\n"
                    f"{json.dumps(final_review, ensure_ascii=False)}",
                    suffix=f"-{attempt + 2}",
                )

        report["status"] = "failed"
        report["failure_reasons"] = reasons
        self._write_quality_report(run_path, report)
        self.db.add_run_event(
            run_id, "error", "quality_gate", "达到返工上限后仍未通过质量门槛",
            stage="quality", metadata={"reasons": reasons},
        )
        raise RuntimeError("Editorial quality gate did not pass within the correction limit")

    async def _reader_review(self, run_id: str, run_path: Path, project: Project,
                             constraints: str, text: str, suffix: str = "") -> dict:
        profile = {
            "platform": project.metadata.get("platform") or "unspecified",
            "genre": project.metadata.get("genre") or "unspecified",
            "audience": project.metadata.get("audience") or "target genre readers",
            "mode": project.mode,
        }
        prompt = (
            "TARGET READER SIMULATION. Do not rewrite the story. Read only the labeled excerpts and "
            "judge whether this target reader would continue, pay, and feel the promised payoff. "
            "Identify abandonment points, weak hooks, fake suspense, unearned emotion,套路化表达, and "
            "AI-like prose. Return the same strict quality-review JSON schema.\n\n"
            f"READER PROFILE:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
            f"LABELED EXCERPTS:\n{reader_sample(text, project.mode)}"
        )
        return self._review(await self._stage(
            run_id, run_path, project, "review", constraints, prompt,
            suffix=f"-reader{suffix}",
        ))

    @staticmethod
    def _write_quality_report(run_path: Path, report: dict) -> None:
        atomic_write(
            run_path / "outputs" / "quality-report.json",
            json.dumps(report, ensure_ascii=False, indent=2),
        )

    def _quality_assessed_event(self, run_id: str, source: str, review: dict,
                                attempt: int | None = None) -> None:
        metadata = {
            "source": source,
            "score": review["score"],
            "dimensions": review["dimensions"],
            "hard_fail": review["hard_fail"],
            "decision": review["decision"],
        }
        if attempt is not None:
            metadata["attempt"] = attempt
        self.db.add_run_event(
            run_id, "info", "quality_assessed",
            f"{source} 质量评分：{review['score']}",
            stage="quality", metadata=metadata,
        )

    async def _stage(self, run_id: str, run_path: Path, project: Project, stage: str,
                     constraints: str, user: str, suffix: str = "") -> str:
        self.db.update_run(run_id, "running", stage)
        self.db.add_run_event(run_id, "info", "stage_started", f"开始执行 {stage}", stage=stage)
        required = REQUIRED_SKILLS[stage]
        commands = None
        cwd = None
        skill = self.skills.skills(project.path).get("story-maintenance") if stage == "maintenance" else None
        if skill and skill.executable:
            commands = {"story-maintenance": ["scripts/story.js", "validate", "."]}
            cwd = project.path
        try:
            skill_run = self.skills.run_required(stage, required, commands, cwd, project.path)
            skills = [receipt.skill_name for receipt in skill_run.receipts]
            self.db.add_run_event(
                run_id, "success", "skills_loaded", f"已加载 {len(skills)} 个 Skill",
                stage=stage, metadata={"skills": skills},
            )
            system = f"{STAGE_SYSTEM[stage]}\n\nHARD CONSTRAINTS:\n{constraints}\n\n{skill_run.prompt}"
            if hasattr(self.gateway, "complete_with_tools"):
                toolbox = StoryToolbox(project, self.memory)
                result = await self.gateway.complete_with_tools(
                    stage, system, user, toolbox,
                    fallback_context=lambda: json.dumps(
                        self.memory.context(project.id, user[:500]), ensure_ascii=False,
                    ),
                    run_id=run_id,
                    max_output_tokens=self._stage_output_budget(stage),
                )
            else:
                result = await self.gateway.complete(
                    stage, system, user,
                    max_output_tokens=self._stage_output_budget(stage),
                )
            name = f"{stage}{suffix}"
            atomic_write(run_path / "outputs" / f"{name}.md", result.text)
            receipt = {"model": result.receipt, "skills": [receipt.__dict__ for receipt in skill_run.receipts]}
            atomic_write(run_path / "receipts" / f"{name}.json", json.dumps(receipt, ensure_ascii=False, indent=2))
            self.db.add_run_event(
                run_id, "success", "stage_completed", f"{stage} 执行完成", stage=stage,
                metadata={
                    "provider_id": result.receipt.get("provider_id"),
                    "model_name": result.receipt.get("model_name"),
                    "input_tokens": result.receipt.get("input_tokens", 0),
                    "output_tokens": result.receipt.get("output_tokens", 0),
                    "execution_mode": result.receipt.get("execution_mode"),
                    "skills": skills,
                },
            )
            return result.text
        except asyncio.CancelledError:
            self.db.add_run_event(run_id, "warning", "stage_cancelled", f"{stage} 已终止", stage=stage)
            raise
        except Exception as exc:
            self.db.add_run_event(run_id, "error", "stage_failed", str(exc), stage=stage)
            raise

    def _begin_run(self, project: Project, workflow: str,
                   run_id: str | None) -> tuple[str, Path]:
        run_id = run_id or uuid.uuid4().hex
        run_path = project.path / "runs" / run_id
        (run_path / "outputs").mkdir(parents=True, exist_ok=True)
        (run_path / "receipts").mkdir(exist_ok=True)
        if self.db.get_run(run_id) is None:
            self.db.create_run(run_id, project.id, workflow)
        else:
            self.db.update_run(run_id, "running", "starting")
        return run_id, run_path

    def _post_write_maintenance(self, run_id: str, project: Project) -> None:
        skill = self.skills.skills(project.path).get("story-maintenance")
        if not skill or not skill.executable:
            return
        for command in (
            ["scripts/story.js", "wordcount", ".", "--write"],
            ["scripts/story.js", "reindex", "."],
            ["scripts/story.js", "validate", "."],
        ):
            self.skills.run_required("archive", ["story-maintenance"], {"story-maintenance": command}, project.path, project.path)

    def _volume_for_chapter(self, project: Project, chapter_number: int) -> dict | None:
        path = project.path / "memory" / "volumes.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return next((volume for volume in data.get("volumes", [])
                     if int(volume.get("start_chapter", 0)) <= chapter_number <= int(volume.get("end_chapter", -1))), None)

    def _is_volume_end(self, project: Project, chapter_number: int) -> bool:
        volume = self._volume_for_chapter(project, chapter_number)
        return bool(volume and chapter_number == int(volume.get("end_chapter", -1)))

    def _ensure_previous_volume_passed(self, project: Project, chapter_number: int) -> None:
        volume = self._volume_for_chapter(project, chapter_number)
        if not volume or chapter_number != int(volume.get("start_chapter", 0)) or chapter_number == 1:
            return
        previous = int(volume["number"]) - 1
        audit = project.path / "memory" / "audits" / f"volume-{previous:02d}.json"
        if not audit.is_file() or json.loads(audit.read_text(encoding="utf-8")).get("status") != "passed":
            raise RuntimeError(f"Previous volume audit is not passed: volume {previous}")

    async def _audit_volume_boundary(self, run_id: str, run_path: Path, project: Project,
                                     chapter_number: int, constraints: str) -> None:
        volume = self._volume_for_chapter(project, chapter_number)
        if not volume or chapter_number != int(volume.get("end_chapter", -1)):
            return
        parts = []
        for number in range(int(volume["start_chapter"]), chapter_number + 1):
            path = project.path / "chapters" / f"chapter-{number:02d}.md"
            if path.is_file():
                parts.append(f"CHAPTER {number}:\n{path.read_text(encoding='utf-8')[:4000]}")
        evidence = json.dumps(volume, ensure_ascii=False) + "\n\n" + "\n\n".join(parts)
        text = await self._stage(run_id, run_path, project, "final_review", constraints, evidence,
                                 suffix=f"-volume-{int(volume['number']):02d}")
        review = self._review(text)
        passed, _ = quality_gate(review)
        report = {**review, "volume": int(volume["number"]),
                  "status": "passed" if passed else "blocked"}
        audit = project.path / "memory" / "audits" / f"volume-{int(volume['number']):02d}.json"
        atomic_write(audit, json.dumps(report, ensure_ascii=False, indent=2))
        for issue in review.get("issues", []):
            self.memory.record_drift(project.id, "volume-audit", int(100 - review["score"]), str(issue))
        if report["status"] == "blocked":
            raise RuntimeError(f"Volume audit blocked volume {volume['number']}")

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
        return normalize_review(cls._json_object(text))

    @staticmethod
    def _stage_output_budget(stage: str) -> int | None:
        if stage in {"planning", "review", "final_review", "maintenance"}:
            return 4096
        return None

    @staticmethod
    def _chapter_file(project: Project, text: str, number: int = 1) -> str:
        return (
            f"---\ntitle: {project.title}\nnumber: {number}\npov: {project.metadata['pov']}\n"
            "locations: []\ncharacters: []\narcs-advanced: []\nstatus: final\nword-count: 0\n---\n\n"
            f"# Chapter {number}: {project.title}\n\n## Chapter Text\n\n{text}\n"
        )
