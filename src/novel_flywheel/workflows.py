import asyncio
import hashlib
import json
import math
import os
import re
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Iterator

from novel_flywheel.db import Database
from novel_flywheel.context_policy import polish_context, stage_output_budget
from novel_flywheel.errors import describe_error
from novel_flywheel.models import ModelGateway
from novel_flywheel.memory import StoryMemory
from novel_flywheel.projects import Project, ProjectStore
from novel_flywheel.prompts import OPTIONAL_PROMPT_SKILLS, REQUIRED_SKILLS, STAGE_SYSTEM
from novel_flywheel.quality import (
    normalize_review,
    quality_gate,
    quality_outcome,
    reader_sample,
    select_route,
)
from novel_flywheel.revision import (
    assess_polish_candidate,
    check_revision_constraints,
    compact_polish_findings,
    compact_review,
    normalize_chinese_prose,
    normalize_revision_plan,
    remove_consecutive_duplicate_blocks,
    segment_map,
)
from novel_flywheel.prose_quality import analyze_prose, compare_voice_metrics, prose_metrics
from novel_flywheel.style_context import character_fingerprints, ensure_style_profile
from novel_flywheel.skill_prompts import ConstraintPromptCompactor, SkillPromptCompactor
from novel_flywheel.skills import SkillGate
from novel_flywheel.storage import ProjectSnapshot, atomic_write
from novel_flywheel.story_state import StoryStateStore, validate_locked_facts
from novel_flywheel.tools import StoryToolbox


class StageText(str):
    def __new__(cls, value: str, receipt: dict):
        instance = super().__new__(cls, value)
        instance.receipt = receipt
        return instance


class RevisionPlanError(RuntimeError):
    pass


class PolishTokenBudgetError(RuntimeError):
    pass


class WorkflowService:
    SHORT_SEGMENT_SEPARATOR = "\n\n<!-- NOVEL_FLYWHEEL_SEGMENT -->\n\n"
    INITIAL_POLISH_INPUT_CAP = 120_000
    STRUCTURAL_POLISH_INPUT_CAP = 60_000
    TOTAL_POLISH_INPUT_CAP = 220_000

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
        self.story_states = StoryStateStore(db)
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
            self._record_voice_drift(run_id, project, chapter_number, polished)
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

    def _record_voice_drift(self, run_id: str, project: Project, chapter_number: int,
                            text: str) -> None:
        folder = project.path / "memory" / "style-metrics"
        history = []
        for path in sorted(folder.glob("chapter-*.json"))[-5:]:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                history.append(value.get("metrics", value))
        metrics = prose_metrics(text)
        drift = compare_voice_metrics(metrics, history)
        atomic_write(folder / f"chapter-{chapter_number:02d}.json", json.dumps(
            {"chapter": chapter_number, "metrics": metrics, "drift": drift},
            ensure_ascii=False, indent=2,
        ))
        self.db.add_run_event(
            run_id, "warning" if drift["drifted"] else "success", "voice_drift",
            "检测到跨章文风漂移，已记录为优化建议" if drift["drifted"] else "跨章文风指标稳定",
            stage="quality", metadata=drift,
        )

    async def _short_pipeline(self, project: Project, run_id: str | None = None) -> dict:
        run_id, run_path = self._begin_run(project, "short-story", run_id)
        state = self.story_states.ensure(project.id, project.path)
        candidate_id = None
        draft_candidate_id = None
        state_committed = False
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
            resumed_best = False
            if checkpoint:
                plan = (checkpoint / "planning.md").read_text(encoding="utf-8")
                draft, source_artifact = self._short_checkpoint_manuscript(
                    checkpoint, segment_count,
                )
                resumed_best = source_artifact == "best-candidate.md"
                atomic_write(run_path / "outputs" / "planning.md", plan)
                atomic_write(run_path / "outputs" / "draft.md", draft)
                self.db.add_run_event(
                    run_id, "success", "checkpoint_reused", "已复用上一轮完整规划和分段草稿",
                    stage="draft", metadata={
                        "source_run": checkpoint.parent.name,
                        "source_artifact": source_artifact,
                    },
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
            draft_candidate = self.story_states.create_candidate(
                project.id, run_id, state.revision, "draft",
                hashlib.sha256(draft.encode("utf-8")).hexdigest(),
                {"artifact": "outputs/draft.md"},
            )
            draft_candidate_id = draft_candidate.id
            review_checkpoint = (None if resumed_best else
                                 self._find_short_stage_output(project, run_id, "review.md"))
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
            candidate = self.story_states.create_candidate(
                project.id, run_id, state.revision, "polish",
                hashlib.sha256(polished.encode("utf-8")).hexdigest(),
                {"artifact": "outputs/polish.md"},
            )
            candidate_id = candidate.id
            atomic_write(formal[0], polished)
            atomic_write(formal[1], self._chapter_file(project, polished))
            atomic_write(formal[2], json.dumps(canon, ensure_ascii=False, indent=2))
            self._post_write_maintenance(run_id, project)
            confirmed = []
            for index, fact in enumerate(canon.get("facts", [])):
                if not isinstance(fact, dict):
                    continue
                confirmed.append({
                    "key": str(fact.get("fact_key") or fact.get("subject") or f"generated.{index}"),
                    "value": fact.get("value", fact.get("fact", "")),
                    "level": "confirmed",
                    "source": run_id,
                })
            next_data = {
                **state.data,
                "confirmed_facts": confirmed or state.data.get("confirmed_facts", []),
                "character_states": canon.get("state", state.data.get("character_states", {})),
                "world_rules": canon.get("world_rules", state.data.get("world_rules", [])),
                "timeline_events": canon.get("timeline", state.data.get("timeline_events", [])),
                "manuscript_revision": int(state.data.get("manuscript_revision", 0)) + 1,
            }
            committed = self.story_states.commit(candidate.id, state.revision, next_data)
            state_committed = True
            self.story_states.reject(draft_candidate.id, "superseded by accepted polish")
            self.db.add_run_event(
                run_id, "success", "story_state_committed", "正式稿与权威故事状态已提交",
                stage="archive", metadata={
                    "candidate_id": candidate.id,
                    "base_revision": state.revision,
                    "revision": committed.revision,
                },
            )
            self.db.update_run(run_id, "completed", "archive")
            return self.db.get_run(run_id) or {"id": run_id, "status": "completed"}
        except asyncio.CancelledError:
            if not state_committed:
                snapshot.restore()
            if candidate_id:
                self.story_states.reject(candidate_id, "cancelled")
            if draft_candidate_id:
                self.story_states.reject(draft_candidate_id, "cancelled")
            self.db.update_run(run_id, "cancelled", error="Cancelled by user")
            raise
        except Exception as exc:
            if not state_committed:
                snapshot.restore()
            if candidate_id:
                self.story_states.reject(candidate_id, str(exc))
            if draft_candidate_id:
                self.story_states.reject(draft_candidate_id, str(exc))
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
        try:
            polished = await self._polish_short_segments(
                run_id, run_path, project, constraints, draft,
                json.dumps(findings, ensure_ascii=False),
            )
        except (RevisionPlanError, PolishTokenBudgetError) as exc:
            self._halt_quality_revision(run_id, run_path, report, draft, exc)

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
            outcome, reasons = quality_outcome(final_review)
            passed = outcome != "failed"
            report["final_attempts"].append({
                "attempt": attempt + 1,
                "review": final_review,
                "passed": passed,
                "outcome": outcome,
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
                report["status"] = outcome
                report["failure_reasons"] = []
                self._write_quality_report(run_path, report)
                self.db.add_run_event(
                    run_id, "success", "quality_gate",
                    "质量审核通过" if outcome == "passed" else "质量条件通过，建议小修",
                    stage="quality", metadata={
                        "attempt": attempt + 1,
                        "outcome": outcome,
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
                try:
                    polished = await self._polish_short_segments(
                        run_id, run_path, project, constraints, best_polished,
                        json.dumps(final_review, ensure_ascii=False),
                        suffix=f"-{attempt + 2}", structural=True,
                    )
                except (RevisionPlanError, PolishTokenBudgetError) as exc:
                    self._halt_quality_revision(
                        run_id, run_path, report, best_polished, exc,
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

    @classmethod
    def _split_polish_segments(cls, text: str, target: int = 2000,
                               maximum: int = 2400) -> list[str]:
        chunks: list[str] = []
        for original in cls._split_segments(text):
            first_chunk = len(chunks)
            paragraphs = [item.strip() for item in re.split(r"\n\s*\n", original) if item.strip()]
            units: list[str] = []
            for paragraph in paragraphs:
                if len(paragraph) <= maximum:
                    units.append(paragraph)
                    continue
                sentences = re.findall(r"[^。！？!?]+[。！？!?]?", paragraph)
                for sentence in sentences:
                    sentence = sentence.strip()
                    while len(sentence) > maximum:
                        units.append(sentence[:maximum])
                        sentence = sentence[maximum:]
                    if sentence:
                        units.append(sentence)
            current: list[str] = []
            size = 0
            for unit in units:
                added = len(unit) + (2 if current else 0)
                if current and size + added > maximum:
                    chunks.append("\n\n".join(current))
                    current, size = [], 0
                current.append(unit)
                size += len(unit) + (2 if len(current) > 1 else 0)
                if size >= target:
                    chunks.append("\n\n".join(current))
                    current, size = [], 0
            if current:
                chunks.append("\n\n".join(current))
            if len(chunks) - first_chunk > 1 and len(chunks[-1]) < 800:
                merged = chunks[-2] + "\n\n" + chunks[-1]
                if len(merged) <= maximum + 400:
                    chunks[-2:] = [merged]
        return chunks

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

    @classmethod
    def _short_checkpoint_manuscript(cls, outputs: Path,
                                     segment_count: int) -> tuple[str, str]:
        for filename in ("best-candidate.md", "draft.md"):
            path = outputs / filename
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            if len(cls._split_segments(text)) == segment_count:
                return text, filename
        raise ValueError("Short-story checkpoint has no complete manuscript")

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
        original_parts = self._split_segments(text)
        grouped_parts = (
            [(part, group) for group, part in enumerate(original_parts, 1)]
            if structural else [
                (part, group)
                for group, original in enumerate(original_parts, 1)
                for part in self._split_polish_segments(original)
            ]
        )
        parts = [item[0] for item in grouped_parts]
        part_groups = [item[1] for item in grouped_parts]
        revision_plan = None
        story_map = segment_map(original_parts)
        authoritative_state = self.story_states.ensure(project.id, project.path).data
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
        style_profile = ensure_style_profile(project)
        polished_parts: list[str] = []
        fallback_only = False
        primary_circuit_open = any(
            event["event_type"] == "polish_circuit_opened"
            for event in self.db.list_run_events(run_id)
        )
        binding = self.db.get_role_binding("polish") or {}
        configured_fallback = bool(
            binding.get("fallback_provider_id") and binding.get("fallback_model_id")
            and hasattr(self.gateway, "complete_configured_fallback")
        )
        checkpoint_root = (
            run_path / "outputs" / "polish-checkpoints" / (suffix.strip("-") or "initial")
        )
        round_input_tokens = 0
        prior_input_tokens = sum(
            int(event.get("metadata", {}).get("input_tokens", 0) or 0)
            for event in self.db.list_run_events(run_id)
            if event["event_type"] == "stage_completed" and event.get("stage") == "polish"
        )
        round_cap = (
            self.STRUCTURAL_POLISH_INPUT_CAP if structural else self.INITIAL_POLISH_INPUT_CAP
        )
        for index, part in enumerate(parts, 1):
            group = part_groups[index - 1]
            if revision_plan and group not in revision_plan["target_segments"]:
                polished_parts.append(part)
                continue
            cached = self._load_polish_checkpoint(checkpoint_root, index, part)
            if cached is not None:
                polished_parts.append(cached)
                self.db.add_run_event(
                    run_id, "success", "polish_checkpoint_reused",
                    f"润色第 {index}/{len(parts)} 段已从检查点恢复",
                    stage="polish", metadata={"segment": index, "route": "checkpoint"},
                )
                continue
            if round_input_tokens >= round_cap or (
                prior_input_tokens + round_input_tokens >= self.TOTAL_POLISH_INPUT_CAP
            ):
                limit = "round" if round_input_tokens >= round_cap else "total"
                self.db.add_run_event(
                    run_id, "error", "token_budget_exhausted",
                    "Polish input token budget exhausted; stopped before the next model call",
                    stage="polish", metadata={
                        "limit": limit,
                        "round_input_tokens": round_input_tokens,
                        "total_input_tokens": prior_input_tokens + round_input_tokens,
                        "round_cap": round_cap,
                        "total_cap": self.TOTAL_POLISH_INPUT_CAP,
                        "next_segment": index,
                    },
                )
                raise PolishTokenBudgetError(f"Polish {limit} input token budget exhausted")
            previous_tail = polished_parts[-1][-800:] if polished_parts else ""
            next_head = parts[index][:800] if index < len(parts) else ""
            local_report = analyze_prose(part)
            tasks = ([task["instruction"] for task in revision_plan["tasks"]
                      if group in task["segments"]] if revision_plan else [])
            plan_context = (
                f"GLOBAL FACTS AND LOCKS:\n{json.dumps(revision_plan['global_facts'], ensure_ascii=False)}\n\n"
                f"TASKS FOR THIS SEGMENT:\n{json.dumps(tasks, ensure_ascii=False)}\n\n"
                f"DETERMINISTIC CHECKS:\n{json.dumps(revision_plan['checks'], ensure_ascii=False)}\n\n"
                f"COMPACT FULL STORY MAP:\n{json.dumps(story_map, ensure_ascii=False)}\n\n"
                if revision_plan else f"STRUCTURED FINDINGS:\n{findings}\n\n"
            )
            minimum_ratio, maximum_ratio = ((0.60, 1.80) if structural else (0.70, 1.60))
            minimum_characters = math.floor(len(part) * minimum_ratio)
            maximum_characters = math.ceil(len(part) * maximum_ratio)
            length_contract = (
                f" Return between {minimum_characters} and {maximum_characters} characters. "
                "Do not repeat adjacent scenes, include analysis, or rewrite material outside "
                "this manuscript segment."
            )
            prompt = (
                f"STYLE PROFILE:\n{style_profile}\n\n"
                f"RELEVANT CHARACTER VOICES:\n{character_fingerprints(project.path, part)}\n\n"
                f"LOCAL PROSE FINDINGS:\n{json.dumps(local_report['findings'], ensure_ascii=False)}\n\n"
                + polish_context(
                    state=authoritative_state,
                    story_map=story_map,
                    segment_index=index,
                    segment_count=len(parts),
                    segment=part,
                    previous_tail=previous_tail,
                    next_head=next_head,
                    findings=plan_context,
                    edit_rule=revision_rule + length_contract,
                )
            )
            part_suffix = f"{suffix}-part-{index:02d}"
            priority = bool(structural or index in {1, len(parts)} or local_report["findings"])
            prefer_configured = bool(
                configured_fallback and (primary_circuit_open or not priority)
            )
            route = (
                "draft_fallback" if fallback_only else
                "circuit_fallback" if primary_circuit_open and prefer_configured else
                "configured_fallback" if prefer_configured else "primary"
            )
            self.db.add_run_event(
                run_id, "info", "polish_segment_route",
                f"润色第 {index}/{len(parts)} 段路由：{route}",
                stage="polish", metadata={
                    "segment": index, "total": len(parts), "route": route,
                    "priority": priority, "characters": len(part),
                },
            )
            if fallback_only:
                polished_part = await self._stage(
                    run_id, run_path, project, "polish", constraints, prompt,
                    suffix=f"{part_suffix}-fallback", model_role="draft", allow_tools=False,
                    output_source_characters=len(part),
                )
            else:
                try:
                    polished_part = await self._stage(
                        run_id, run_path, project, "polish", constraints, prompt,
                        suffix=part_suffix, allow_tools=False,
                        prefer_configured_fallback=prefer_configured,
                        output_source_characters=len(part),
                    )
                    if getattr(polished_part, "receipt", {}).get("fallback_used"):
                        primary_circuit_open = True
                        self.db.add_run_event(
                            run_id, "warning", "polish_circuit_opened",
                            "润色主模型已回退成功，本轮后续重点段直接使用配置备用模型",
                            stage="polish", metadata={"segment": index},
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    fallback_only = True
                    self.db.add_run_event(
                        run_id, "warning", "model_fallback",
                        "polish 当前路由失败，本轮剩余分段切换到 draft 角色模型",
                        stage="polish", metadata={
                            "fallback_role": "draft", "failed_route": route, "error": str(exc),
                        },
                    )
                    polished_part = await self._stage(
                        run_id, run_path, project, "polish", constraints, prompt,
                        suffix=f"{part_suffix}-fallback", model_role="draft", allow_tools=False,
                        output_source_characters=len(part),
                    )
            round_input_tokens += int(
                getattr(polished_part, "receipt", {}).get("input_tokens", 0) or 0
            )
            voice = character_fingerprints(project.path, part)
            required = re.findall(r"(?m)^##\s+(.+)$", voice)
            assessment = assess_polish_candidate(
                part, polished_part, required,
                minimum_ratio=minimum_ratio, maximum_ratio=maximum_ratio,
            )
            locked_failures = validate_locked_facts(part, polished_part, authoritative_state)
            if locked_failures:
                assessment["accepted"] = False
                assessment["reasons"].extend(locked_failures)
            accepted = bool(assessment["accepted"])
            if not assessment["accepted"]:
                self.db.add_run_event(
                    run_id, "warning", "polish_output_rejected",
                    f"润色第 {index}/{len(parts)} 段未通过本地验收，已保留原文",
                    stage="polish", metadata={
                        "segment": index,
                        "original_characters": len(part),
                        "candidate_characters": len(polished_part.strip()),
                        "ratio": assessment["ratio"],
                        "minimum_characters": minimum_characters,
                        "maximum_characters": maximum_characters,
                        "candidate_preview": polished_part.strip()[:240],
                        "reasons": assessment["reasons"],
                    },
                )
                polished_part = part
            polished_part = polished_part.strip()
            polished_parts.append(polished_part)
            if accepted:
                self._save_polish_checkpoint(checkpoint_root, index, part, polished_part)
        restored_groups: list[str] = []
        for group in range(1, len(original_parts) + 1):
            restored_groups.append("\n\n".join(
                part for part, part_group in zip(polished_parts, part_groups)
                if part_group == group
            ))
        polished = self.SHORT_SEGMENT_SEPARATOR.join(restored_groups)
        polished, duplicate_removals = remove_consecutive_duplicate_blocks(polished)
        polished, repairs = normalize_chinese_prose(polished)
        if duplicate_removals:
            repairs.append("consecutive_duplicate_blocks")
        if repairs:
            self.db.add_run_event(
                run_id, "success", "local_format_repair",
                "已在本地修复机械格式问题",
                stage="polish", metadata={"repairs": repairs},
            )
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
        hard_categories = {
            "canon", "canon_conflict", "logic_continuity", "manuscript_corruption",
            "missing_required_content", "production_text", "story_structure",
        }
        require_checks = any(
            issue.get("severity") == "critical" or issue.get("category") in hard_categories
            for issue in review.get("issues", []) if isinstance(issue, dict)
        )
        prompt = (
            "Create a minimal structural revision plan for this segmented manuscript. Map every "
            "review issue to one separate task and the exact scene_id/segment numbers that must "
            "change. Target no more than 40% of scenes and never target unrelated scenes. "
            "Return one JSON object only with: global_facts (string array), checks (array of objects "
            "using kind required_text or forbidden_text and value), and tasks (array with segments as "
            "integer array and instruction as text). Include at least one literal deterministic check "
            "for hard fact, canon, duplication, or required-content issues. Do not combine all review "
            "issues into one instruction. Checks must be unambiguous manuscript text constraints; "
            "semantic judgments belong in the scene task.\n\n"
            f"COMPLETE REVIEW FINDINGS:\n{json.dumps(review, ensure_ascii=False)}\n\n"
            f"COMPACT SEGMENT MAP:\n{json.dumps(story_map, ensure_ascii=False)}"
        )
        try:
            try:
                output = await self._stage(
                    run_id, run_path, project, "revision_plan", constraints, prompt,
                    suffix=f"{suffix}-revision-plan", model_role="planning", allow_tools=False,
                )
                plan = normalize_revision_plan(
                    self._json_object(output), len(story_map),
                    max_target_ratio=0.4, require_checks=require_checks,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.db.add_run_event(
                    run_id, "warning", "model_fallback",
                    "Revision planning model failed; retrying with the review role",
                    stage="revision_plan", metadata={
                        "fallback_role": "review", "error": str(exc),
                    },
                )
                output = await self._stage(
                    run_id, run_path, project, "revision_plan", constraints, prompt,
                    suffix=f"{suffix}-revision-plan-fallback", model_role="review",
                    allow_tools=False,
                )
                plan = normalize_revision_plan(
                    self._json_object(output), len(story_map),
                    max_target_ratio=0.4, require_checks=require_checks,
                )
            event_type, severity = "revision_planned", "success"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.db.add_run_event(
                run_id, "error", "revision_plan_blocked",
                "Structural revision plan is invalid; revision stopped to preserve the best candidate",
                stage="revision_plan",
                metadata={"error": str(exc)},
            )
            raise RevisionPlanError(f"Structural revision plan failed: {exc}") from exc
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

    def _halt_quality_revision(self, run_id: str, run_path: Path, report: dict,
                               candidate: str, error: Exception) -> None:
        reason = (
            "revision_plan_invalid" if isinstance(error, RevisionPlanError)
            else "token_budget_exhausted"
        )
        report["status"] = "halted"
        report["halt_reason"] = reason
        report["failure_reasons"] = [str(error)]
        atomic_write(run_path / "outputs" / "best-candidate.md", candidate)
        self._write_quality_report(run_path, report)
        self.db.add_run_event(
            run_id, "error", "quality_revision_halted",
            "Quality revision stopped and preserved the best candidate",
            stage="quality", metadata={"reason": reason, "error": str(error)},
        )
        raise RuntimeError(
            f"Quality revision halted; preserved best candidate ({reason})"
        ) from error

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
                     model_role: str | None = None, allow_tools: bool = True,
                     prefer_configured_fallback: bool = False,
                     output_source_characters: int | None = None) -> str:
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
            identity = (
                self._maintenance_story_identity(project)
                if stage == "maintenance" and skill and skill.executable
                else nullcontext()
            )
            with identity:
                skill_run = self.skills.run_required(stage, required, commands, cwd, project.path)
            if OPTIONAL_PROMPT_SKILLS.get(stage) and hasattr(self.skills, "load_optional_prompts"):
                optional = self.skills.load_optional_prompts(
                    stage, OPTIONAL_PROMPT_SKILLS[stage], project.path,
                )
                skill_run = type(skill_run)(
                    "\n\n".join(item for item in (skill_run.prompt, optional.prompt) if item),
                    [*skill_run.receipts, *optional.receipts],
                )
            skills = [receipt.skill_name for receipt in skill_run.receipts]
            compact_context = stage in {"polish", "revision_plan"}
            model_skill_prompt = (
                self.skill_prompts.compact(skill_run.prompt, skill_run.receipts)
                if compact_context else skill_run.prompt
            )
            model_constraints = constraints
            if compact_context:
                model_constraints = self.constraint_prompts.compact(constraints)
            if stage == "polish":
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
            output_budget = self._output_budget_for_call(
                stage, output_source_characters, gateway_role, prefer_configured_fallback,
            )
            if allow_tools and hasattr(self.gateway, "complete_with_tools"):
                toolbox = StoryToolbox(project, self.memory)
                result = await self.gateway.complete_with_tools(
                    gateway_role, system, user, toolbox,
                    fallback_context=lambda: json.dumps(
                        self.memory.context(project.id, user[:500]), ensure_ascii=False,
                    ),
                    run_id=run_id,
                    max_output_tokens=output_budget,
                )
            elif prefer_configured_fallback and hasattr(
                self.gateway, "complete_configured_fallback"
            ):
                result = await self.gateway.complete_configured_fallback(
                    gateway_role, system, user,
                    max_output_tokens=output_budget,
                )
            else:
                result = await self.gateway.complete(
                    gateway_role, system, user,
                    max_output_tokens=output_budget,
                )
            if (stage == "polish" and gateway_role == "polish" and not allow_tools
                    and not result.text.strip()
                    and result.receipt.get("finish_reason") == "max_tokens"
                    and output_budget != 8192):
                previous_budget = output_budget
                self.db.add_run_event(
                    run_id, "warning", "polish_max_tokens_retry",
                    "Polish output hit its token limit; retrying with full budget",
                    stage=stage, metadata={
                        "previous_budget": previous_budget, "retry_budget": 8192,
                    },
                )
                if prefer_configured_fallback and hasattr(
                    self.gateway, "complete_configured_fallback"
                ):
                    result = await self.gateway.complete_configured_fallback(
                        gateway_role, system, user, max_output_tokens=8192,
                    )
                else:
                    result = await self.gateway.complete(
                        gateway_role, system, user, max_output_tokens=8192,
                    )
            if not result.text.strip():
                raise RuntimeError(
                    f"{stage} model returned empty output "
                    f"(model={result.receipt.get('model_name', 'unknown')}, "
                    f"input_tokens={result.receipt.get('input_tokens', 0)}, "
                    f"output_tokens={result.receipt.get('output_tokens', 0)}, "
                    f"finish_reason={result.receipt.get('finish_reason', 'unknown')})"
                )
            if result.receipt.get("fallback_used"):
                self.db.add_run_event(
                    run_id, "warning", "model_fallback",
                    f"{stage} 首选模型失败，已使用该角色配置的备用模型",
                    stage=stage, metadata={
                        "fallback_type": "configured",
                        "provider_id": result.receipt.get("provider_id"),
                        "model_id": result.receipt.get("model_id"),
                        "model_name": result.receipt.get("model_name"),
                        "primary_provider_id": result.receipt.get("fallback_from_provider_id"),
                        "primary_model_id": result.receipt.get("fallback_from_model_id"),
                        "primary_error": result.receipt.get("primary_error"),
                    },
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
            return StageText(result.text, result.receipt)
        except asyncio.CancelledError:
            self.db.add_run_event(run_id, "warning", "stage_cancelled", f"{stage} 已终止", stage=stage)
            raise
        except Exception as exc:
            self.db.add_run_event(
                run_id, "error", "stage_failed", describe_error(exc), stage=stage,
            )
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

    @staticmethod
    def _load_polish_checkpoint(root: Path, index: int, source: str) -> str | None:
        path = root / f"part-{index:02d}.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        polished = value.get("polished")
        return polished if value.get("source_sha256") == digest and isinstance(polished, str) else None

    @staticmethod
    def _save_polish_checkpoint(root: Path, index: int, source: str, polished: str) -> None:
        atomic_write(root / f"part-{index:02d}.json", json.dumps({
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "polished": polished,
        }, ensure_ascii=False, indent=2))

    def _post_write_maintenance(self, run_id: str, project: Project) -> None:
        skill = self.skills.skills(project.path).get("story-maintenance")
        if not skill or not skill.executable:
            return
        with self._maintenance_story_identity(project):
            for command in (
                ["scripts/story.js", "wordcount", ".", "--write"],
                ["scripts/story.js", "reindex", "."],
                ["scripts/story.js", "validate", "."],
            ):
                self.skills.run_required("archive", ["story-maintenance"], {"story-maintenance": command}, project.path, project.path)

    @staticmethod
    @contextmanager
    def _maintenance_story_identity(project: Project) -> Iterator[None]:
        story_path = project.path / "story.md"
        original = story_path.read_text(encoding="utf-8")
        compatible, count = re.subn(
            r"(?m)^title:.*$", f"title: {project.id}", original, count=1,
        )
        if count != 1:
            raise ValueError("story.md requires a title field")
        atomic_write(story_path, compatible)
        try:
            yield
        finally:
            atomic_write(story_path, original)

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
    def _stage_output_budget(stage: str, source_characters: int | None = None) -> int | None:
        return stage_output_budget(stage, source_characters)

    def _output_budget_for_call(self, stage: str, source_characters: int | None,
                                gateway_role: str, prefer_configured_fallback: bool) -> int | None:
        if stage == "polish" and gateway_role == "polish" and not prefer_configured_fallback:
            binding = self.db.get_role_binding("polish") or {}
            model = self.db.get_model(binding.get("primary_model_id", "")) or {}
            identity = f"{model.get('display_name', '')} {model.get('model_name', '')}".lower()
            if "claude" in identity:
                return 8192
        return self._stage_output_budget(stage, source_characters)

    @staticmethod
    def _chapter_file(project: Project, text: str, number: int = 1) -> str:
        return (
            f"---\ntitle: {project.title}\nnumber: {number}\npov: {project.metadata['pov']}\n"
            "locations: []\ncharacters: []\narcs-advanced: []\nstatus: final\nword-count: 0\n---\n\n"
            f"# Chapter {number}: {project.title}\n\n## Chapter Text\n\n{text}\n"
        )
