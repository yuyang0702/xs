import asyncio
import json
import math
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
from novel_flywheel.revision import (
    check_revision_constraints,
    compact_polish_findings,
    compact_review,
    normalize_revision_plan,
    segment_map,
)
from novel_flywheel.skill_prompts import ConstraintPromptCompactor, SkillPromptCompactor
from novel_flywheel.skills import SkillGate
from novel_flywheel.storage import ProjectSnapshot, atomic_write
from novel_flywheel.tools import StoryToolbox


class WorkflowService:
    SHORT_SEGMENT_SEPARATOR = "\n\n<!-- NOVEL_FLYWHEEL_SEGMENT -->\n\n"

    def __init__(self, db: Database, projects: ProjectStore, gateway: ModelGateway,
                 skills: SkillGate, crewai_data_dir: Path | None = None,
                 skill_prompts: SkillPromptCompactor | None = None,
                 constraint_prompts: ConstraintPromptCompactor | None = None) -> None:
        self.db = db
        self.projects = projects
        self.gateway = gateway
        self.skills = skills
        self.crewai_data_dir = crewai_data_dir or db.path.parent / "crewai"
        self.memory = StoryMemory(db)
        self.skill_prompts = skill_prompts or SkillPromptCompactor()
        self.constraint_prompts = constraint_prompts or ConstraintPromptCompactor()

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
            target_words = int(project.metadata["target_words"])
            segment_count = self._short_segment_count(target_words)
            checkpoint = self._find_short_checkpoint(project, run_id, segment_count)
            if checkpoint:
                plan = (checkpoint / "planning.md").read_text(encoding="utf-8")
                draft = (checkpoint / "draft.md").read_text(encoding="utf-8")
                atomic_write(run_path / "outputs" / "planning.md", plan)
                atomic_write(run_path / "outputs" / "draft.md", draft)
                self.db.add_run_event(
                    run_id, "success", "checkpoint_reused", "已复用上一轮完整规划和分段草稿",
                    stage="draft", metadata={"source_run": checkpoint.parent.name},
                )
            else:
                brief = json.dumps({
                    **project.metadata,
                    "generation_contract": {
                        "target_total_words": target_words,
                        "segment_count": segment_count,
                        "require_segment_map": segment_count > 1,
                    },
                }, ensure_ascii=False, indent=2)
                plan = await self._stage(run_id, run_path, project, "planning", constraints, brief)
                draft = await self._draft_short_in_segments(
                    run_id, run_path, project, constraints, plan,
                )
            review_checkpoint = self._find_short_stage_output(project, run_id, "review.md")
            review = None
            if review_checkpoint:
                try:
                    review_text = review_checkpoint.read_text(encoding="utf-8")
                    review = self._review(review_text)
                except (ValueError, json.JSONDecodeError):
                    review = None
                else:
                    atomic_write(run_path / "outputs" / "review.md", review_text)
                    self.db.add_run_event(
                        run_id, "success", "checkpoint_reused", "已复用上一轮有效编辑审核",
                        stage="review", metadata={"source_run": review_checkpoint.parent.parent.name},
                    )
            if review is None:
                review_input = (
                    f"MANUSCRIPT LENGTH: {len(draft)} characters.\n\nLABELED EXCERPTS:\n"
                    f"{reader_sample(draft, project.mode, limit=6000)}"
                )
                review_text = await self._stage_with_role_fallback(
                    run_id, run_path, project, "review", constraints, review_input,
                    fallback_role="planning", allow_tools=False,
                )
                review = self._review(review_text)
            polished, _ = await self._quality_polish(
                run_id, run_path, project, constraints, draft, review,
            )
            canon_text = await self._stage_with_role_fallback(
                run_id, run_path, project, "maintenance", constraints, polished,
                fallback_role="planning", allow_tools=False,
            )
            canon = self._json_object(canon_text)
            if not isinstance(canon.get("facts"), list):
                raise ValueError("Maintenance output must contain a facts array")
            polished = "\n\n".join(self._split_segments(polished))
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
            "best_attempt": None,
            "best_score": None,
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
            reader_role = ("reader_review"
                           if self.db.get_role_binding("reader_review") else "review")
            fallback_used = reader_role == "review"
            self.db.add_run_event(
                run_id, "info", "quality_escalated",
                "正在使用审核模型回退执行目标读者模拟" if fallback_used
                else "正在使用独立读者模型执行目标读者模拟",
                stage="review", metadata={
                    "reasons": route["reasons"],
                    "model_role": reader_role,
                    "fallback_used": fallback_used,
                },
            )
            try:
                reader_review = await self._reader_review(
                    run_id, run_path, project, constraints, draft,
                    model_role=reader_role,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if reader_role == "review":
                    raise
                self.db.add_run_event(
                    run_id, "warning", "reader_fallback",
                    "独立读者模型调用失败，已回退到审核模型",
                    stage="review", metadata={
                        "failed_role": reader_role,
                        "fallback_role": "review",
                        "error": str(exc),
                    },
                )
                reader_review = {
                    **review,
                    "reader_signals": {"unavailable": True, "fallback": "editorial_review"},
                }
            report["reader_review"] = reader_review
            self._quality_assessed_event(run_id, "target_reader", reader_review)
            self._write_quality_report(run_path, report)

        findings = {"editorial": review, "target_reader": reader_review}
        polished = await self._polish_short_segments(
            run_id, run_path, project, constraints, draft,
            json.dumps(findings, ensure_ascii=False),
        )

        reasons: list[str] = []
        best_polished = polished
        best_review: dict | None = None
        best_attempt: int | None = None
        for attempt in range(route["max_corrections"] + 1):
            reviewed_polished = polished
            final_input = (reader_sample(polished, project.mode, limit=6000)
                           if project.mode == "short" else polished)
            if attempt:
                checks_path = run_path / "outputs" / f"revision-checks-{attempt + 1}.json"
                if checks_path.is_file():
                    failures = json.loads(checks_path.read_text(encoding="utf-8")).get("failures", [])
                    if failures:
                        final_input += (
                            "\n\nRUNTIME STRUCTURAL CHECK FAILURES. Treat unresolved failures as hard "
                            f"evidence:\n{json.dumps(failures, ensure_ascii=False)}"
                        )
            final_review = self._review(await self._stage_with_role_fallback(
                run_id, run_path, project, "final_review", constraints, final_input,
                suffix=f"-{attempt + 1}" if attempt else "",
                fallback_role="planning", allow_tools=project.mode != "short",
            ))
            passed, reasons = quality_gate(final_review)
            report["final_attempts"].append({
                "attempt": attempt + 1,
                "review": final_review,
                "passed": passed,
                "reasons": reasons,
            })
            if best_review is None or final_review["score"] > best_review["score"]:
                best_review = final_review
                best_polished = reviewed_polished
                best_attempt = attempt + 1
                report["best_attempt"] = best_attempt
                report["best_score"] = final_review["score"]
            elif final_review["score"] < best_review["score"]:
                self.db.add_run_event(
                    run_id, "warning", "quality_regression",
                    "本轮评分下降，下一轮将恢复当前最高分版本",
                    stage="quality", metadata={
                        "attempt": attempt + 1,
                        "score": final_review["score"],
                        "best_attempt": best_attempt,
                        "best_score": best_review["score"],
                    },
                )
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
                polished = await self._polish_short_segments(
                    run_id, run_path, project, constraints, best_polished,
                    json.dumps(final_review, ensure_ascii=False),
                    suffix=f"-{attempt + 2}", structural=True,
                )

        report["status"] = "failed"
        report["failure_reasons"] = reasons
        atomic_write(run_path / "outputs" / "best-candidate.md", best_polished)
        self._write_quality_report(run_path, report)
        self.db.add_run_event(
            run_id, "error", "quality_gate", "达到返工上限后仍未通过质量门槛",
            stage="quality", metadata={"reasons": reasons},
        )
        raise RuntimeError("Editorial quality gate did not pass within the correction limit")

    async def _reader_review(self, run_id: str, run_path: Path, project: Project,
                             constraints: str, text: str, suffix: str = "",
                             model_role: str | None = None) -> dict:
        requirements = project.metadata.get("story_requirements") or {}
        profile = {
            "platform": requirements.get("platform") or project.metadata.get("platform") or "unspecified",
            "genre": project.metadata.get("genre") or "unspecified",
            "audience": requirements.get("audience") or project.metadata.get("audience")
            or "target genre readers",
            "mode": project.mode,
        }
        prompt = (
            "TARGET READER SIMULATION. Do not rewrite the story. Read only the labeled excerpts and "
            "judge whether this target reader would continue, pay, and feel the promised payoff. "
            "Identify abandonment points, weak hooks, fake suspense, unearned emotion,套路化表达, and "
            "AI-like prose. Return the same strict quality-review JSON schema plus reader_signals with "
            "would_continue (boolean), would_pay (boolean), abandonment_point (text), and payoff_felt "
            "(boolean). Use double quotes for every JSON key and string. Return one JSON object only, "
            "without Markdown fences or commentary.\n\n"
            f"READER PROFILE:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
            f"LABELED EXCERPTS:\n{reader_sample(text, project.mode, limit=6000)}"
        )
        output = await self._stage(
            run_id, run_path, project, "review", constraints, prompt,
            suffix=f"-reader{suffix}", model_role=model_role or "review", allow_tools=False,
        )
        try:
            return self._review(output)
        except json.JSONDecodeError:
            repaired = normalize_review(self._reader_json_object(output))
            self.db.add_run_event(
                run_id, "warning", "reader_review_repaired",
                "Reader review returned malformed JSON and was repaired locally",
                stage="review", metadata={"strategy": "conservative_json_repair"},
            )
            return repaired

    @staticmethod
    def _short_segment_count(target_words: int) -> int:
        if target_words <= 8000:
            return 1
        return min(12, max(2, math.ceil(target_words / 2500)))

    @classmethod
    def _split_segments(cls, text: str) -> list[str]:
        return [part.strip() for part in text.split(cls.SHORT_SEGMENT_SEPARATOR) if part.strip()]

    def _find_short_checkpoint(self, project: Project, current_run_id: str,
                               segment_count: int) -> Path | None:
        for run in self.db.list_runs(project.id):
            if run["id"] == current_run_id or run["workflow"] != "short-story":
                continue
            outputs = project.path / "runs" / run["id"] / "outputs"
            plan_path = outputs / "planning.md"
            draft_path = outputs / "draft.md"
            if not plan_path.is_file() or not draft_path.is_file():
                continue
            plan = plan_path.read_text(encoding="utf-8").strip()
            draft = draft_path.read_text(encoding="utf-8")
            if plan and len(self._split_segments(draft)) == segment_count:
                return outputs
        return None

    def _find_short_stage_output(self, project: Project, current_run_id: str,
                                 filename: str) -> Path | None:
        for run in self.db.list_runs(project.id):
            if run["id"] == current_run_id or run["workflow"] != "short-story":
                continue
            path = project.path / "runs" / run["id"] / "outputs" / filename
            if path.is_file() and path.stat().st_size:
                return path
        return None

    async def _draft_short_in_segments(self, run_id: str, run_path: Path, project: Project,
                                       constraints: str, plan: str) -> str:
        target_words = int(project.metadata["target_words"])
        count = self._short_segment_count(target_words)
        if count == 1:
            return await self._stage(
                run_id, run_path, project, "draft", constraints,
                f"APPROVED PLAN:\n{plan}\n\nWrite the complete story now. Do not ask questions.",
            )
        target = math.ceil(target_words / count)
        parts: list[str] = []
        for index in range(1, count + 1):
            self.db.add_run_event(
                run_id, "info", "segment_started", f"开始生成正文第 {index}/{count} 段",
                stage="draft", metadata={"segment": index, "total": count, "target_words": target},
            )
            previous_tail = parts[-1][-1200:] if parts else "这是开篇，无上一段。"
            prompt = (
                f"APPROVED COMPLETE PLAN:\n{plan}\n\n"
                f"WRITE SEGMENT {index} OF {count}. Target about {target} Chinese characters. "
                "Return only publishable fiction prose. Continue the approved causal sequence, preserve "
                "character voices and commercial hooks, and do not summarize, explain, or ask questions. "
                "All project decisions are final; infer minor details from the plan.\n\n"
                f"上一段结尾：\n{previous_tail}\n\n不要提问，直接写本段正文。"
            )
            part = await self._stage(
                run_id, run_path, project, "draft", constraints, prompt,
                suffix=f"-part-{index:02d}", allow_tools=False,
            )
            parts.append(part.strip())
            self.db.add_run_event(
                run_id, "success", "segment_completed", f"正文第 {index}/{count} 段生成完成",
                stage="draft", metadata={"segment": index, "total": count, "characters": len(part)},
            )
        draft = self.SHORT_SEGMENT_SEPARATOR.join(parts)
        atomic_write(run_path / "outputs" / "draft.md", draft)
        return draft

    async def _polish_short_segments(self, run_id: str, run_path: Path, project: Project,
                                     constraints: str, text: str, findings: str,
                                     suffix: str = "", structural: bool = False) -> str:
        parts = self._split_segments(text)
        revision_plan = None
        story_map = segment_map(parts)
        if structural and len(parts) > 1:
            revision_plan = await self._plan_structural_revision(
                run_id, run_path, project, constraints, findings, story_map, suffix,
            )
        elif not structural:
            try:
                findings = json.dumps(
                    compact_polish_findings(json.loads(findings)), ensure_ascii=False,
                )
            except (json.JSONDecodeError, TypeError):
                findings = findings[:4000]
        revision_rule = (
            "You may replace or remove implausible events and reorder material inside this segment "
            "to resolve the findings. Preserve the core premise, required ending, established facts, "
            "and approximate length."
            if structural else
            "Preserve events and length; remove AI-like phrasing and apply the findings."
        )
        if len(parts) == 1:
            return await self._stage(
                run_id, run_path, project, "polish", constraints,
                f"REVISION RULE:\n{revision_rule}\n\nMANUSCRIPT:\n{text}\n\n"
                f"STRUCTURED FINDINGS:\n{findings}", suffix=suffix,
            )
        polished_parts: list[str] = []
        fallback_only = False
        for index, part in enumerate(parts, 1):
            if revision_plan and index not in revision_plan["target_segments"]:
                polished_parts.append(part)
                continue
            previous_tail = polished_parts[-1][-800:] if polished_parts else ""
            next_head = parts[index][:800] if index < len(parts) else ""
            tasks = ([task["instruction"] for task in revision_plan["tasks"]
                      if index in task["segments"]] if revision_plan else [])
            plan_context = (
                f"GLOBAL FACTS AND LOCKS:\n{json.dumps(revision_plan['global_facts'], ensure_ascii=False)}\n\n"
                f"TASKS FOR THIS SEGMENT:\n{json.dumps(tasks, ensure_ascii=False)}\n\n"
                f"DETERMINISTIC CHECKS:\n{json.dumps(revision_plan['checks'], ensure_ascii=False)}\n\n"
                f"COMPACT FULL STORY MAP:\n{json.dumps(story_map, ensure_ascii=False)}\n\n"
                if revision_plan else f"STRUCTURED FINDINGS:\n{findings}\n\n"
            )
            prompt = (
                f"POLISH SEGMENT {index} OF {len(parts)}. Return only the revised prose for this segment. "
                f"{revision_rule}\n\n"
                f"{plan_context}PREVIOUS POLISHED END:\n{previous_tail}\n\n"
                f"NEXT ORIGINAL START:\n{next_head}\n\nMANUSCRIPT SEGMENT:\n{part}"
            )
            part_suffix = f"{suffix}-part-{index:02d}"
            if fallback_only:
                polished_part = await self._stage(
                    run_id, run_path, project, "polish", constraints, prompt,
                    suffix=f"{part_suffix}-fallback", model_role="draft", allow_tools=False,
                )
            else:
                try:
                    polished_part = await self._stage(
                        run_id, run_path, project, "polish", constraints, prompt,
                        suffix=part_suffix, allow_tools=False,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    fallback_only = True
                    self.db.add_run_event(
                        run_id, "warning", "model_fallback",
                        "polish 首选模型失败，本轮剩余分段切换到 draft 角色模型",
                        stage="polish", metadata={"fallback_role": "draft", "error": str(exc)},
                    )
                    polished_part = await self._stage(
                        run_id, run_path, project, "polish", constraints, prompt,
                        suffix=f"{part_suffix}-fallback", model_role="draft", allow_tools=False,
                    )
            ratio = len(polished_part.strip()) / max(1, len(part))
            if ratio < 0.70 or ratio > 1.60:
                self.db.add_run_event(
                    run_id, "warning", "polish_output_rejected",
                    f"润色第 {index}/{len(parts)} 段长度异常，已保留原文",
                    stage="polish", metadata={
                        "segment": index,
                        "original_characters": len(part),
                        "candidate_characters": len(polished_part.strip()),
                        "ratio": round(ratio, 3),
                    },
                )
                polished_part = part
            polished_parts.append(polished_part.strip())
        polished = self.SHORT_SEGMENT_SEPARATOR.join(polished_parts)
        if revision_plan:
            failures = check_revision_constraints(polished, revision_plan)
            atomic_write(
                run_path / "outputs" / f"revision-checks{suffix}.json",
                json.dumps({"failures": failures}, ensure_ascii=False, indent=2),
            )
            if failures:
                self.db.add_run_event(
                    run_id, "warning", "revision_checks_failed",
                    "Structural revision still violates deterministic checks",
                    stage="polish", metadata={"failures": failures},
                )
        atomic_write(run_path / "outputs" / f"polish{suffix}.md", polished)
        return polished

    async def _plan_structural_revision(self, run_id: str, run_path: Path, project: Project,
                                        constraints: str, findings: str,
                                        story_map: list[dict], suffix: str) -> dict:
        try:
            review = compact_review(json.loads(findings))
        except (json.JSONDecodeError, TypeError):
            review = {"issues": [{"action": findings}]}
        prompt = (
            "Create a minimal structural revision plan for this segmented manuscript. Map every "
            "action to the exact segment numbers that must change. Do not target unrelated segments. "
            "Return one JSON object only with: global_facts (string array), checks (array of objects "
            "using kind required_text or forbidden_text and value), and tasks (array with segments as "
            "integer array and instruction as text). Checks must be literal, unambiguous manuscript "
            "text constraints; omit checks that require semantic judgment.\n\n"
            f"COMPLETE REVIEW FINDINGS:\n{json.dumps(review, ensure_ascii=False)}\n\n"
            f"COMPACT SEGMENT MAP:\n{json.dumps(story_map, ensure_ascii=False)}"
        )
        try:
            output = await self._stage(
                run_id, run_path, project, "revision_plan", constraints, prompt,
                suffix=f"{suffix}-revision-plan", model_role="planning", allow_tools=False,
            )
            plan = normalize_revision_plan(self._json_object(output), len(story_map))
            event_type, severity = "revision_planned", "success"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            actions = [issue.get("action", "") for issue in review.get("issues", [])
                       if isinstance(issue, dict) and issue.get("action")]
            plan = {
                "global_facts": [],
                "checks": [],
                "tasks": [{
                    "segments": list(range(1, len(story_map) + 1)),
                    "instruction": "\n".join(actions) or "Resolve all supplied review findings.",
                }],
                "target_segments": list(range(1, len(story_map) + 1)),
            }
            event_type, severity = "revision_plan_fallback", "warning"
            self.db.add_run_event(
                run_id, severity, event_type,
                "Revision planner failed; using conservative all-segment correction",
                stage="revision_plan",
                metadata={"error": str(exc), "target_segments": plan["target_segments"]},
            )
        else:
            self.db.add_run_event(
                run_id, severity, event_type, "Structural revision plan created",
                stage="revision_plan", metadata={
                    "target_segments": plan["target_segments"],
                    "task_count": len(plan["tasks"]),
                    "check_count": len(plan["checks"]),
                },
            )
        atomic_write(
            run_path / "outputs" / f"revision-plan{suffix}.json",
            json.dumps(plan, ensure_ascii=False, indent=2),
        )
        return plan

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
                     constraints: str, user: str, suffix: str = "",
                     model_role: str | None = None, allow_tools: bool = True) -> str:
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
            model_skill_prompt = (
                self.skill_prompts.compact(skill_run.prompt, skill_run.receipts)
                if stage == "polish" else skill_run.prompt
            )
            model_constraints = constraints
            if stage == "polish":
                model_constraints = self.constraint_prompts.compact(constraints)
                project_constraints = (project.path / "constraints.md").read_text(encoding="utf-8")
                if project_constraints not in model_constraints:
                    model_constraints += "\n\nPROJECT-SPECIFIC CONSTRAINTS:\n" + project_constraints
            self.db.add_run_event(
                run_id, "success", "skills_loaded", f"已加载 {len(skills)} 个 Skill",
                stage=stage, metadata={
                    "skills": skills,
                    "prompt_characters": len(model_skill_prompt),
                    "source_prompt_characters": len(skill_run.prompt),
                    "compact_prompt": model_skill_prompt != skill_run.prompt,
                    "constraint_characters": len(model_constraints),
                    "source_constraint_characters": len(constraints),
                    "compact_constraints": model_constraints != constraints,
                },
            )
            system = f"{STAGE_SYSTEM[stage]}\n\nHARD CONSTRAINTS:\n{model_constraints}\n\n{model_skill_prompt}"
            gateway_role = model_role or stage
            if allow_tools and hasattr(self.gateway, "complete_with_tools"):
                toolbox = StoryToolbox(project, self.memory)
                result = await self.gateway.complete_with_tools(
                    gateway_role, system, user, toolbox,
                    fallback_context=lambda: json.dumps(
                        self.memory.context(project.id, user[:500]), ensure_ascii=False,
                    ),
                    run_id=run_id,
                    max_output_tokens=self._stage_output_budget(stage),
                )
            else:
                result = await self.gateway.complete(
                    gateway_role, system, user,
                    max_output_tokens=self._stage_output_budget(stage),
                )
            if not result.text.strip():
                raise RuntimeError(
                    f"{stage} model returned empty output "
                    f"(model={result.receipt.get('model_name', 'unknown')}, "
                    f"input_tokens={result.receipt.get('input_tokens', 0)}, "
                    f"output_tokens={result.receipt.get('output_tokens', 0)}, "
                    f"finish_reason={result.receipt.get('finish_reason', 'unknown')})"
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

    async def _stage_with_role_fallback(
        self, run_id: str, run_path: Path, project: Project, stage: str,
        constraints: str, user: str, fallback_role: str, suffix: str = "",
        allow_tools: bool = True,
    ) -> str:
        try:
            return await self._stage(
                run_id, run_path, project, stage, constraints, user,
                suffix=suffix, allow_tools=allow_tools,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.db.add_run_event(
                run_id, "warning", "model_fallback",
                f"{stage} 首选模型失败，已切换到 {fallback_role} 角色模型",
                stage=stage, metadata={"fallback_role": fallback_role, "error": str(exc)},
            )
            return await self._stage(
                run_id, run_path, project, stage, constraints, user,
                suffix=f"{suffix}-fallback", model_role=fallback_role,
                allow_tools=allow_tools,
            )

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

    @staticmethod
    def _reader_json_object(text: str) -> dict:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Reader model output does not contain a JSON object")
        candidate = cleaned[start:end + 1]
        field_names = (
            "category|severity|evidence|action|commercial|story|prose|hard_fail|decision|"
            "issues|dimensions|reader_signals|would_continue|would_pay|abandonment_point|"
            "payoff_felt"
        )
        candidate = re.sub(
            rf"['’]\s*,\s*['’]({field_names})['’]\s*:",
            lambda match: f'", "{match.group(1)}":',
            candidate,
        )
        value = json.loads(candidate)
        if not isinstance(value, dict):
            raise ValueError("Reader model output must be a JSON object")
        return value

    @classmethod
    def _review(cls, text: str) -> dict:
        return normalize_review(cls._json_object(text))

    @staticmethod
    def _stage_output_budget(stage: str) -> int | None:
        if stage in {"planning", "final_review", "maintenance"}:
            return 8192
        if stage == "polish":
            return 8192
        if stage in {"review", "revision_plan"}:
            return 4096
        return None

    @staticmethod
    def _chapter_file(project: Project, text: str, number: int = 1) -> str:
        return (
            f"---\ntitle: {project.title}\nnumber: {number}\npov: {project.metadata['pov']}\n"
            "locations: []\ncharacters: []\narcs-advanced: []\nstatus: final\nword-count: 0\n---\n\n"
            f"# Chapter {number}: {project.title}\n\n## Chapter Text\n\n{text}\n"
        )
