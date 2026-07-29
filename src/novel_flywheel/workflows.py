import asyncio
import hashlib
import json
import math
import os
import re
import uuid
from contextlib import contextmanager, nullcontext
from collections.abc import Sequence
from pathlib import Path
from typing import Iterator

from novel_flywheel.db import Database
from novel_flywheel.causal_chain import compact_causal_chain, extract_short_causal_chain
from novel_flywheel.context_policy import (
    estimate_input_tokens,
    next_retry_action,
    patch_output_budget,
    polish_context,
    revision_patch_context,
    schema_repair_prompt,
    stage_output_budget,
)
from novel_flywheel.config import configure_runtime_environment
from novel_flywheel.errors import describe_error
from novel_flywheel.models import ModelGateway, ModelRoutesExhaustedError
from novel_flywheel.memory import StoryMemory
from novel_flywheel.manuscript_analysis import analysis_matches, analyze_manuscript, compact_analysis
from novel_flywheel.incremental_review import (
    apply_incremental_gate,
    build_review_baseline,
    diff_manuscripts,
    incremental_precheck_reasons,
    requires_full_review,
    select_review_scope,
)
from novel_flywheel.projects import Project, ProjectStore
from novel_flywheel.prompts import OPTIONAL_PROMPT_SKILLS, REQUIRED_SKILLS, STAGE_SYSTEM
from novel_flywheel.quality import (
    apply_evidence_gate,
    issue_ledger,
    normalize_review,
    quality_gate,
    quality_outcome,
    reader_sample,
    review_windows,
    select_route,
)
from novel_flywheel.quality_records import (
    checkpoint_manuscript,
    load_quality_checkpoint,
    reconcile_legacy_checkpoint,
    write_quality_checkpoint,
)
from novel_flywheel.repair_gate import evaluate_candidate_gate
from novel_flywheel.repair_records import RepairRunStore, repair_artifact_hash
from novel_flywheel.quality_profiles import (
    ZHihu_SHORT_V2,
    compare_quality_candidates,
    judge_signature,
    profile_for_project,
    quality_outcome_for_profile,
    quality_profile_prompt,
    score_review,
)
from novel_flywheel.passage_protection import (
    PassageProtectionService,
    applicable_passage_locks,
    passage_prompt_context,
    validate_passage_protections,
)
from novel_flywheel.revision import (
    apply_patch_group,
    align_revision_plan_targets,
    assess_polish_candidate,
    check_revision_constraints,
    check_source_local_constraints,
    compact_polish_findings,
    compact_review,
    normalize_repair_contract,
    normalize_chinese_prose,
    normalize_revision_plan,
    repair_mechanical_text,
    remove_consecutive_duplicate_blocks,
    segment_map,
)
from novel_flywheel.prose_quality import analyze_prose, compare_voice_metrics, prose_metrics
from novel_flywheel.style_context import character_fingerprints, ensure_style_profile
from novel_flywheel.skill_prompts import ConstraintPromptCompactor, SkillPromptCompactor
from novel_flywheel.skills import SkillGate
from novel_flywheel.storage import ProjectSnapshot, atomic_write
from novel_flywheel.story_state import StoryStateStore, validate_locked_facts
from novel_flywheel.learning import LearningSystem
from novel_flywheel.tools import StoryToolbox


class StageText(str):
    def __new__(cls, value: str, receipt: dict):
        instance = super().__new__(cls, value)
        instance.receipt = receipt
        return instance


class RevisionPlanError(RuntimeError):
    pass


class TargetedGroupError(RuntimeError):
    pass


class PolishTokenBudgetError(RuntimeError):
    pass


class WorkflowService:
    SHORT_SEGMENT_SEPARATOR = "\n\n<!-- NOVEL_FLYWHEEL_SEGMENT -->\n\n"
    INITIAL_POLISH_INPUT_CAP = 120_000
    STRUCTURAL_POLISH_INPUT_CAP = 60_000

    def __init__(self, db: Database, projects: ProjectStore, gateway: ModelGateway,
                 skills: SkillGate, crewai_data_dir: Path | None = None,
                 skill_prompts: SkillPromptCompactor | None = None,
                 constraint_prompts: ConstraintPromptCompactor | None = None,
                 local_nlp=None, references=None) -> None:
        self.db = db
        self.projects = projects
        self.gateway = gateway
        self.skills = skills
        self.crewai_data_dir = crewai_data_dir or db.path.parent / "crewai"
        self.memory = StoryMemory(db)
        self.story_states = StoryStateStore(db)
        self.skill_prompts = skill_prompts or SkillPromptCompactor()
        self.constraint_prompts = constraint_prompts or ConstraintPromptCompactor()
        self.local_nlp = local_nlp
        self.references = references

    def _analyze_manuscript(
        self, text: str, run_path: Path, project: Project, label: str,
    ) -> dict:
        output = run_path / "outputs" / f"analysis-{label}.json"
        try:
            cached = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = {}
        if analysis_matches(cached, text):
            return cached
        enabled = bool(
            self.projects.get(project.id).metadata.get("optimized_local_review_enabled", False)
        )
        nlp_analyze = self.local_nlp.analyze if enabled and self.local_nlp else None
        sources = self.references.comparison_sources(project.id) if enabled and self.references else []
        baseline = self.projects.active_learning_data(project.id, "market_baseline")
        report = analyze_manuscript(
            text, nlp_analyze=nlp_analyze, comparison_sources=sources,
            market_baseline=baseline,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(output, json.dumps(report, ensure_ascii=False, indent=2))
        return report

    def _constraints_with_platform_rules(self, project: Project, constraints: str) -> str:
        marker = "\n\nMATCHED PLATFORM RULE REFERENCES:\n"
        if marker in constraints or not self.references or not hasattr(self.references, "platform_rules"):
            return constraints
        rules = self.references.platform_rules(project.metadata.get("platform"))
        if not rules:
            return constraints
        compact = [
            {"title": item["title"], "text": item["text"][:8000]}
            for item in rules[:5]
        ]
        return constraints + marker + json.dumps(compact, ensure_ascii=False)

    async def run_short(self, project_id: str, use_crewai: bool = True,
                        run_id: str | None = None) -> dict:
        project = self.projects.get(project_id)
        if project.mode != "short":
            raise ValueError("Short-story workflow requires a short project")
        if use_crewai:
            return await self._run_in_crewai(lambda: self._short_pipeline(project, run_id))
        return await self._short_pipeline(project, run_id)

    async def run_short_revision(
        self, project_id: str, issue_ids: list[str],
        run_id: str | None = None,
    ) -> dict:
        project = self.projects.get(project_id)
        if project.mode != "short":
            raise ValueError("定向返修目前只支持短篇作品")
        return await self._short_revision_pipeline(project, issue_ids, run_id)

    async def _short_revision_pipeline(
        self, project: Project, issue_ids: list[str],
        run_id: str | None = None,
    ) -> dict:
        selected_ids = self._selected_repair_issue_ids(issue_ids)
        protected = self._protected_short_revision_source(project)
        ledger_by_id = {
            item.get("issue_id"): item
            for item in protected["issue_ledger"]
            if isinstance(item, dict) and isinstance(item.get("issue_id"), str)
        }
        unknown = [issue_id for issue_id in selected_ids if issue_id not in ledger_by_id]
        if unknown:
            raise ValueError("所选问题已不属于当前受保护最佳稿，请重新确认")
        story_state = self.story_states.get(project.id)
        if story_state is None:
            raise ValueError("当前作品缺少可校验的 StoryState，不能开始定向返修")

        run_id, run_path = self._begin_run(project, "short-revision", run_id)
        store = RepairRunStore(run_path)
        try:
            resume = (store.output / store.CHECKPOINT).is_file()
            if not resume and any(
                (store.output / name).is_file()
                for name in (store.CONTRACT, store.GROUPS, store.CANDIDATE)
            ):
                resume = True
            if resume:
                state = store.load_resume_state(protected["source_hash"])
                contract = state["contract"]
                frozen_ids = contract.get("selected_issue_ids")
                if (
                    not isinstance(frozen_ids, list)
                    or set(frozen_ids) != set(selected_ids)
                    or len(frozen_ids) != len(selected_ids)
                ):
                    raise ValueError("继续返修时所选问题必须与原返修合同一致")
                selected_ids = list(frozen_ids)
                records = state["groups"]["groups"]
                candidate = state["candidate"]
                completed = set(state["completed_groups"])
            else:
                analysis = self._analyze_manuscript(
                    protected["source"], run_path, project, "repair-source",
                )
                selected_issues = [
                    self._json_copy(ledger_by_id[issue_id])
                    for issue_id in selected_ids
                ]
                groups = [{
                    "group_id": issue_id,
                    "issue_ids": [issue_id],
                    "kind": (
                        "mechanical"
                        if self._mechanical_issue_code(ledger_by_id[issue_id])
                        else "semantic"
                    ),
                    "requires_user_confirmation": True,
                } for issue_id in selected_ids]
                contract = {
                    "version": 1,
                    "manuscript_hash": protected["source_hash"],
                    "source_run_id": protected["run_id"],
                    "terminal_reviewed_hash": protected["checkpoint"][
                        "terminal_reviewed_hash"
                    ],
                    "selected_issue_ids": selected_ids,
                    "selected_issues": selected_issues,
                    "issue_ledger": self._json_copy(protected["issue_ledger"]),
                    "review": self._json_copy(protected["review"]),
                    "story_state": {
                        "revision": story_state.revision,
                        "data": self._json_copy(story_state.data),
                    },
                    "passage_locks": self._json_copy(
                        self.db.list_locks(project.id),
                    ),
                    "analysis": analysis,
                    "required_text": self._repair_literals(
                        selected_issues, "required_text",
                    ),
                    "forbidden_text": self._repair_literals(
                        selected_issues, "forbidden_text",
                    ),
                    "groups": groups,
                }
                store.write_contract(contract)
                records = [{
                    **group,
                    "status": "pending",
                    "attempts": 0,
                    "message": "等待处理",
                } for group in groups]
                candidate = protected["source"]
                completed: set[str] = set()
                self._write_short_revision_progress(
                    store, contract, records, candidate, completed, "running",
                )

            issues = {
                item["issue_id"]: item
                for item in contract["selected_issues"]
            }
            constraints = (project.path / "constraints.md").read_text(
                encoding="utf-8",
            )
            provider_failures = False
            for group in contract["groups"]:
                group_id = group["group_id"]
                if group_id in completed:
                    continue
                record = next(
                    item for item in records if item["group_id"] == group_id
                )
                issue = issues[group_id]
                record["attempts"] = int(record.get("attempts", 0)) + 1
                record["status"] = "processing"
                record["message"] = "正在生成安全补丁"
                patch_group = None
                try:
                    if group["kind"] == "mechanical":
                        patch_group = self._mechanical_patch_group(
                            issue, candidate, group_id,
                        )
                        if patch_group is None:
                            result = {
                                "group_id": group_id,
                                "accepted": False,
                                "text": candidate,
                                "failures": [{
                                    "patch": 0,
                                    "code": "mechanical_scope_not_unique",
                                }],
                                "diffs": [],
                            }
                        else:
                            result = {
                                "group_id": group_id,
                                **apply_patch_group(
                                    candidate, patch_group,
                                    self._text_hash(candidate),
                                ),
                            }
                    else:
                        request = self._semantic_patch_request(
                            contract, issue, group_id, candidate,
                        )
                        raw = await self._stage(
                            run_id, run_path, project, "revision_plan",
                            constraints,
                            json.dumps(request, ensure_ascii=False),
                            suffix=f"-repair-{group_id}",
                            allow_tools=False,
                            output_source_characters=len(
                                request.get("target_excerpt", ""),
                            ),
                            targeted_retry=True,
                        )
                        try:
                            value = normalize_repair_contract(
                                self._json_object(raw), candidate, {group_id},
                            )
                            if len(value["groups"]) != 1:
                                raise ValueError("模型必须一次只返回一个修改组")
                            patch_group = value["groups"][0]
                            if (
                                patch_group.get("group_id") != group_id
                                or patch_group.get("issue_ids") != [group_id]
                                or patch_group.get("kind") != "semantic"
                            ):
                                raise ValueError("模型返回的修改组与当前问题不一致")
                        except ValueError:
                            record.update({
                                "status": "rejected",
                                "message": (
                                    "模型返回的修改格式未通过本地验收，"
                                    "当前修改组未应用"
                                ),
                            })
                            record.pop("patch_group", None)
                            record["patch_result"] = {
                                "group_id": group_id,
                                "accepted": False,
                                "text": candidate,
                                "failures": [{
                                    "patch": 0,
                                    "code": "repair_contract_rejected",
                                }],
                                "diffs": [],
                            }
                            self._save_short_revision_state(
                                store, contract, run_id, records, candidate,
                                completed, None, "running",
                            )
                            self.db.add_run_event(
                                run_id, "warning",
                                "short_revision_group_rejected",
                                (
                                    "模型返回的修改格式未通过本地验收，"
                                    "当前修改组未应用"
                                ),
                                stage="repair_groups",
                                metadata={
                                    "group_id": group_id,
                                    "category": "contract_validation",
                                },
                            )
                            continue
                        result = {
                            "group_id": group_id,
                            **apply_patch_group(
                                candidate, patch_group,
                                self._text_hash(candidate),
                            ),
                        }
                except asyncio.CancelledError:
                    record.update({
                        "status": "cancelled",
                        "message": "当前修改组已取消，之前完成的修改仍已保留",
                    })
                    self._save_short_revision_state(
                        store, contract, run_id, records, candidate, completed,
                        None, "cancelled",
                    )
                    self.db.update_run(
                        run_id, "cancelled", "repair_groups",
                        error="用户取消了当前返修",
                    )
                    self.db.add_run_event(
                        run_id, "warning", "short_revision_cancelled",
                        "当前返修已取消，已完成的修改组和检查点均已保留",
                        stage="repair_groups", metadata={"group_id": group_id},
                    )
                    raise
                except TargetedGroupError:
                    provider_failures = True
                    record.update({
                        "status": "failed",
                        "message": "首选和备用模型均失败，可从本修改组继续",
                    })
                    record.pop("patch_group", None)
                    record["patch_result"] = {
                        "group_id": group_id,
                        "accepted": False,
                        "text": candidate,
                        "failures": [{
                            "patch": 0, "code": "model_routes_failed",
                        }],
                        "diffs": [],
                    }
                    self._save_short_revision_state(
                        store, contract, run_id, records, candidate, completed,
                        None, "running",
                    )
                    self.db.add_run_event(
                        run_id, "warning", "short_revision_group_failed",
                        "当前修改组生成失败，已保留其他完成结果并继续处理独立问题",
                        stage="repair_groups", metadata={"group_id": group_id},
                    )
                    continue
                except Exception:
                    message = (
                        "当前修改组发生意外错误，"
                        "运行已停止并保留安全检查点"
                    )
                    record.update({
                        "status": "failed",
                        "message": message,
                    })
                    record.pop("patch_group", None)
                    record["patch_result"] = {
                        "group_id": group_id,
                        "accepted": False,
                        "text": candidate,
                        "failures": [{
                            "patch": 0,
                            "code": "unexpected_group_error",
                        }],
                        "diffs": [],
                    }
                    self._save_short_revision_state(
                        store, contract, run_id, records, candidate, completed,
                        None, "failed",
                    )
                    self.db.update_run(
                        run_id, "failed", "repair_groups", error=message,
                    )
                    self.db.add_run_event(
                        run_id, "error", "short_revision_group_error",
                        message, stage="repair_groups",
                        metadata={
                            "group_id": group_id,
                            "category": "unexpected_local_error",
                        },
                    )
                    raise

                if patch_group is not None:
                    record["patch_group"] = patch_group
                record["patch_result"] = result
                if result["accepted"]:
                    completed.add(group_id)
                    replayed, replay_failure = self._replay_repair_records(
                        protected["source"], records, completed,
                    )
                    if replay_failure is None:
                        candidate = replayed
                        record.update({
                            "status": "ready_for_confirmation",
                            "message": (
                                "机械修复已应用到候选稿"
                                if group["kind"] == "mechanical"
                                else "修改已通过本地补丁检查，等待用户确认"
                            ),
                        })
                    else:
                        completed.discard(group_id)
                        candidate, _ = self._replay_repair_records(
                            protected["source"], records, completed,
                        )
                        record.update({
                            "status": "failed",
                            "message": "当前修改与已完成修改冲突，未应用到候选稿",
                        })
                else:
                    record.update({
                        "status": "rejected",
                        "message": "修改锚点未通过本地验收，当前修改组未应用",
                    })
                self._save_short_revision_state(
                    store, contract, run_id, records, candidate, completed,
                    None, "running",
                )
                if not result["accepted"]:
                    self.db.add_run_event(
                        run_id, "warning", "short_revision_group_rejected",
                        "修改锚点未通过本地验收，当前修改组未应用",
                        stage="repair_groups",
                        metadata={
                            "group_id": group_id,
                            "category": "patch_validation",
                        },
                    )

            analysis = self._analyze_manuscript(
                candidate, run_path, project, "repair-candidate",
            )
            gate_contract, patch_results = self._repair_gate_evidence(
                contract, records,
            )
            minimum_han, maximum_han = self._short_revision_target_range(project)
            gate = evaluate_candidate_gate(
                source=protected["source"],
                candidate=candidate,
                source_hash=protected["source_hash"],
                analysis=analysis,
                contract=gate_contract,
                patch_results=patch_results,
                story_state=contract["story_state"]["data"],
                passage_locks=contract["passage_locks"],
                minimum_han=minimum_han,
                maximum_han=maximum_han,
            )
            if provider_failures:
                status = "failed"
                message = "部分返修组生成失败，已保留其他完成结果，可从失败组继续"
                self._save_short_revision_state(
                    store, contract, run_id, records, candidate, completed,
                    gate, status,
                )
                self.db.update_run(
                    run_id, status, "repair_groups", error=message,
                )
                self.db.add_run_event(
                    run_id, "error", "short_revision_failed", message,
                    stage="repair_groups",
                )
                raise RuntimeError(message)

            status = (
                "waiting_confirmation"
                if gate["passed"] else "waiting_local_fix"
            )
            report = self._save_short_revision_state(
                store, contract, run_id, records, candidate, completed,
                gate, status,
            )
            self.db.update_run(run_id, status, "repair_gate")
            if gate["passed"]:
                self.db.add_run_event(
                    run_id, "info", "short_revision_waiting_confirmation",
                    "候选稿已通过本地检查，等待你确认各修改组",
                    stage="repair_gate",
                )
            else:
                self.db.add_run_event(
                    run_id, "warning", "short_revision_gate_rejected",
                    "候选稿未通过本地检查，终审尚未调用，请先处理列出的问题",
                    stage="repair_gate",
                    metadata={
                        "blocking_codes": [
                            item["code"] for item in gate["blocking"]
                        ],
                    },
                )
            return {
                **report,
                "candidate": candidate,
                "protected_best_unchanged": True,
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            run = self.db.get_run(run_id)
            if run and run["status"] not in {"failed", "cancelled"}:
                message = (
                    str(exc)
                    if str(exc) and all(ord(char) > 127 for char in str(exc))
                    else "定向返修未完成，已保留可恢复的检查点"
                )
                self.db.update_run(
                    run_id, "failed", run.get("current_stage"), error=message,
                )
                self.db.add_run_event(
                    run_id, "error", "short_revision_failed", message,
                    stage=run.get("current_stage"),
                )
            raise

    def _protected_short_revision_source(self, project: Project) -> dict:
        for run in self.db.list_runs(project.id):
            run_path = project.path / "runs" / run["id"]
            checkpoint = load_quality_checkpoint(run_path)
            if checkpoint is None:
                continue
            source_hash = checkpoint.get("manuscript_hash")
            if checkpoint.get("terminal_reviewed_hash") != source_hash:
                continue
            source = checkpoint_manuscript(run_path, checkpoint)
            if self._text_hash(source) != source_hash:
                continue
            review = checkpoint.get("review")
            if not isinstance(review, dict):
                continue
            terminal_ledger = issue_ledger(review.get("issues", []))
            ledger = checkpoint.get("issue_ledger")
            if not isinstance(ledger, list):
                ledger = terminal_ledger
            if {
                item.get("issue_id") for item in ledger
                if isinstance(item, dict)
            } != {
                item.get("issue_id") for item in terminal_ledger
                if isinstance(item, dict)
            }:
                continue
            return {
                "run_id": run["id"],
                "checkpoint": checkpoint,
                "source": source,
                "source_hash": source_hash,
                "review": review,
                "issue_ledger": ledger,
            }
        raise ValueError("当前项目没有与终审结果绑定的受保护最佳稿")

    @staticmethod
    def _selected_repair_issue_ids(issue_ids: list[str]) -> list[str]:
        if not isinstance(issue_ids, list):
            raise ValueError("请选择需要返修的问题")
        result = []
        for issue_id in issue_ids:
            if (
                not isinstance(issue_id, str)
                or not issue_id.strip()
                or issue_id != issue_id.strip()
            ):
                raise ValueError("所选问题编号无效")
            if issue_id not in result:
                result.append(issue_id)
        if not result:
            raise ValueError("请至少选择一个需要返修的问题")
        return result

    @staticmethod
    def _json_copy(value):
        return json.loads(json.dumps(value, ensure_ascii=False))

    @staticmethod
    def _text_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _repair_literals(issues: list[dict], key: str) -> list[str]:
        result = []
        for issue in issues:
            values = issue.get(key)
            values = [values] if isinstance(values, str) else values
            for value in values if isinstance(values, list) else []:
                if isinstance(value, str) and value and value not in result:
                    result.append(value)
        return result

    @staticmethod
    def _mechanical_issue_code(issue: dict) -> str | None:
        allowed = {
            "ascii_dialogue_quotes",
            "cjk_spacing",
            "duplicate_punctuation",
            "c0_control",
            "consecutive_duplicate_blocks",
        }
        for key in ("mechanical_code", "code", "category"):
            value = issue.get(key)
            if isinstance(value, str) and value in allowed:
                return value
        return None

    def _mechanical_patch_group(
        self, issue: dict, candidate: str, group_id: str,
    ) -> dict | None:
        code = self._mechanical_issue_code(issue)
        evidence = issue.get("evidence")
        if (
            code is None
            or not isinstance(evidence, str)
            or not evidence
            or candidate.count(evidence) != 1
        ):
            return None
        repaired = repair_mechanical_text(evidence)
        applied = {
            item.get("code")
            for item in repaired.get("applied", [])
            if isinstance(item, dict)
        }
        if applied != {code} or repaired["text"] == evidence:
            return None
        return {
            "group_id": group_id,
            "issue_ids": [group_id],
            "kind": "mechanical",
            "requires_user_confirmation": True,
            "patches": [{
                "operation": "replace",
                "old_text": evidence,
                "new_text": repaired["text"],
            }],
        }

    def _semantic_patch_request(
        self, contract: dict, issue: dict, group_id: str, candidate: str,
    ) -> dict:
        evidence = issue.get("evidence")
        evidence = evidence if isinstance(evidence, str) else ""
        offset = candidate.find(evidence) if evidence else -1
        if offset < 0:
            target = evidence
            before = after = ""
        else:
            target = evidence
            before = candidate[max(0, offset - 1200):offset]
            after = candidate[offset + len(evidence):offset + len(evidence) + 1200]
        state = contract["story_state"]["data"]
        return {
            "schema": "targeted-repair-group-v1",
            "group_id": group_id,
            "candidate_hash": self._text_hash(candidate),
            "issue": issue,
            "target_excerpt": target,
            "previous_context": before,
            "next_context": after,
            "authoritative_facts": [
                *state.get("locked_facts", []),
                *state.get("confirmed_facts", []),
            ],
            "passage_locks": [{
                "id": item.get("id"),
                "label": item.get("label"),
                "mode": item.get("mode"),
            } for item in contract["passage_locks"]],
            "instructions": (
                "只返回一个 JSON 修改合同。只处理当前 issue_id；old_text 必须在候选稿中"
                "唯一出现；不得改动上下文或未选问题；语义修改必须要求用户确认。"
            ),
        }

    def _write_short_revision_progress(
        self, store: RepairRunStore, contract: dict, records: list[dict],
        candidate: str, completed: set[str], status: str,
    ) -> None:
        groups = {"groups": records}
        ordered_completed = [
            group["group_id"]
            for group in contract["groups"]
            if group["group_id"] in completed
        ]
        store.write_groups(groups)
        store.write_candidate(candidate)
        store.write_checkpoint({
            "version": 1,
            "status": status,
            "source_hash": contract["manuscript_hash"],
            "contract_hash": repair_artifact_hash(contract),
            "groups_hash": repair_artifact_hash(groups),
            "candidate_hash": repair_artifact_hash(candidate),
            "completed_groups": ordered_completed,
        })

    def _save_short_revision_state(
        self, store: RepairRunStore, contract: dict, run_id: str,
        records: list[dict], candidate: str, completed: set[str],
        gate: dict | None, status: str,
    ) -> dict:
        self._write_short_revision_progress(
            store, contract, records, candidate, completed, status,
        )
        return self._write_short_revision_report(
            store, run_id, records, candidate, gate, status,
        )

    def _replay_repair_records(
        self, source: str, records: list[dict], completed: set[str],
    ) -> tuple[str, str | None]:
        candidate = source
        for record in records:
            group_id = record["group_id"]
            if group_id not in completed:
                continue
            patch_group = record.get("patch_group")
            if not isinstance(patch_group, dict):
                return candidate, group_id
            result = {
                "group_id": group_id,
                **apply_patch_group(
                    candidate, patch_group, self._text_hash(candidate),
                ),
            }
            record["patch_result"] = result
            if not result["accepted"]:
                return candidate, group_id
            candidate = result["text"]
        return candidate, None

    @staticmethod
    def _repair_gate_evidence(
        contract: dict, records: list[dict],
    ) -> tuple[dict, list[dict]]:
        record_by_id = {record["group_id"]: record for record in records}
        groups = []
        results = []
        for group in contract["groups"]:
            record = record_by_id[group["group_id"]]
            patch_group = record.get("patch_group")
            groups.append(
                patch_group
                if isinstance(patch_group, dict)
                else {**group, "patches": []}
            )
            result = record.get("patch_result")
            results.append(
                result
                if isinstance(result, dict)
                else {
                    "group_id": group["group_id"],
                    "accepted": False,
                    "text": "",
                    "failures": [{
                        "patch": 0, "code": "group_incomplete",
                    }],
                    "diffs": [],
                }
            )
        return {
            "manuscript_hash": contract["manuscript_hash"],
            "required_text": contract.get("required_text", []),
            "forbidden_text": contract.get("forbidden_text", []),
            "groups": groups,
        }, results

    @staticmethod
    def _short_revision_target_range(project: Project) -> tuple[int, int]:
        target = max(0, int(project.metadata.get("target_words") or 0))
        if project.metadata.get("platform_profile_id") == "zhihu-salt-short":
            return int(target * 0.9), int(target * 1.1)
        return target, target

    def _write_short_revision_report(
        self, store: RepairRunStore, run_id: str, records: list[dict],
        candidate: str, gate: dict | None, status: str,
    ) -> dict:
        groups = {
            record["group_id"]: {
                "group_id": record["group_id"],
                "issue_ids": record.get("issue_ids", []),
                "kind": record.get("kind"),
                "status": record.get("status"),
                "message": record.get("message"),
                "attempts": record.get("attempts", 0),
                "patches": (
                    record.get("patch_group", {}).get("patches", [])
                    if isinstance(record.get("patch_group"), dict) else []
                ),
                "failures": (
                    record.get("patch_result", {}).get("failures", [])
                    if isinstance(record.get("patch_result"), dict) else []
                ),
            }
            for record in records
        }
        next_action = {
            "waiting_confirmation": "请查看每个语义修改组并决定采用或拒绝",
            "waiting_local_fix": "请先处理未通过的本地检查或失败修改组",
            "failed": "可从失败的修改组继续运行",
            "cancelled": "可继续本次返修，已完成结果不会丢失",
            "running": "正在继续处理其他独立修改组",
        }.get(status, "请查看返修结果")
        report = {
            "id": run_id,
            "status": status,
            "candidate_path": "outputs/candidate.md",
            "candidate_hash": repair_artifact_hash(candidate),
            "groups": groups,
            "gate": gate,
            "next_action": next_action,
            "protected_best_unchanged": True,
        }
        store.write_report(report)
        return report

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

    async def run_materials_audit(self, project_id: str, use_crewai: bool = True,
                                  run_id: str | None = None) -> dict:
        project = self.projects.get(project_id)
        pipeline = lambda: self._materials_audit_pipeline(project, run_id)
        return await self._run_in_crewai(pipeline) if use_crewai else await pipeline()

    async def run_materials_repair(self, project_id: str, use_crewai: bool = True,
                                   run_id: str | None = None) -> dict:
        project = self.projects.get(project_id)
        pipeline = lambda: self._materials_repair_pipeline(project, run_id)
        return await self._run_in_crewai(pipeline) if use_crewai else await pipeline()

    def _material_manuscript(self, project: Project) -> str:
        for run in self.db.list_runs(project.id):
            for name in ("best-candidate.md", "polish.md"):
                path = project.path / "runs" / run["id"] / "outputs" / name
                if path.is_file() and (text := path.read_text(encoding="utf-8")).strip():
                    return text
        formal = project.path / "manuscript" / "story.md"
        if formal.is_file():
            return formal.read_text(encoding="utf-8")
        return "\n\n".join(path.read_text(encoding="utf-8")
                            for path in sorted((project.path / "chapters").glob("chapter-*.md")))

    def _material_reference(self, project: Project) -> str:
        files = [project.path / "constraints.md"]
        for folder in ("characters", "worldbuilding", "plot"):
            files.extend(sorted((project.path / folder).rglob("*.md")))
        parts = []
        for path in files:
            if path.is_file() and "_index.md" not in path.name:
                parts.append(f"FILE {path.relative_to(project.path).as_posix()}\n{path.read_text(encoding='utf-8')}")
        return "\n\n".join(parts)[:60_000]

    async def _materials_audit_pipeline(self, project: Project,
                                        run_id: str | None = None) -> dict:
        run_id, run_path = self._begin_run(project, "materials-audit", run_id)
        try:
            manuscript = self._material_manuscript(project)
            if not manuscript.strip():
                raise RuntimeError("No manuscript is available for conflict checking")
            reference = self._material_reference(project)
            constraints = self.projects.load_constraints(project.id)
            issues = []
            windows = review_windows(manuscript)
            checkpoint_root = run_path / "outputs" / "materials-audit-checkpoints"
            checkpoint_root.mkdir(parents=True, exist_ok=True)
            fallback_circuit_open = any(
                event["event_type"] == "materials_audit_circuit_opened"
                for event in self.db.list_run_events(run_id)
            )
            for window in windows:
                checkpoint_path = checkpoint_root / f"window-{window['index']:03d}.json"
                source_hash = hashlib.sha256(
                    (reference + "\0" + constraints + "\0" + window["text"]
                     + f"\0{window['index']}/{len(windows)}").encode("utf-8")
                ).hexdigest()
                try:
                    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    checkpoint = {}
                if (checkpoint.get("source_hash") == source_hash
                        and isinstance(checkpoint.get("issues"), list)):
                    issues.extend(item for item in checkpoint["issues"] if isinstance(item, dict))
                    self.db.add_run_event(
                        run_id, "success", "materials_audit_checkpoint_reused",
                        f"材料审核第 {window['index']}/{len(windows)} 窗口已从检查点恢复",
                        stage="final_review", metadata={"window": window["index"]},
                    )
                    continue
                prompt = (
                    "MATERIAL CONSISTENCY AUDIT. Compare this manuscript window against the project "
                    "reference. Return JSON only: {\"issues\":[...]}. Each issue must contain category, "
                    "severity (low|medium|high|critical), evidence, location, old_setting, new_setting, "
                    "and action. Report only evidenced contradictions, not style preferences. Do not rewrite.\n\n"
                    f"PROJECT REFERENCE:\n{reference}\n\nWINDOW {window['index']}/{len(windows)} "
                    f"CHARACTERS {window['start']}-{window['end']}:\n{window['text']}"
                )
                result = await self._stage(
                    run_id, run_path, project, "final_review", constraints, prompt,
                    suffix=f"-window-{window['index']}", allow_tools=False,
                    prefer_configured_fallback=fallback_circuit_open,
                )
                if (not fallback_circuit_open
                        and getattr(result, "receipt", {}).get("fallback_used")):
                    fallback_circuit_open = True
                    self.db.add_run_event(
                        run_id, "warning", "materials_audit_circuit_opened",
                        "材料审核首选模型已回退成功，后续窗口直接使用配置备用模型",
                        stage="final_review", metadata={"window": window["index"]},
                    )
                value = self._json_object(result)
                window_issues = [item for item in value.get("issues", []) if isinstance(item, dict)]
                issues.extend(window_issues)
                atomic_write(checkpoint_path, json.dumps({
                    "source_hash": source_hash, "issues": window_issues,
                }, ensure_ascii=False, indent=2))
            report = {"project_id": project.id, "issues": issues, "count": len(issues)}
            atomic_write(run_path / "outputs" / "conflict-report.json",
                         json.dumps(report, ensure_ascii=False, indent=2))
            state = self.story_states.ensure(project.id, project.path)
            if issues:
                candidate = self.story_states.create_candidate(
                    project.id, run_id, state.revision, "materials_audit",
                    hashlib.sha256(json.dumps(issues, ensure_ascii=False).encode()).hexdigest(),
                    {"issue_count": len(issues)},
                )
                ledger = [item for item in state.data.get("issue_ledger", [])
                          if item.get("source") != "materials_audit"]
                ledger.extend({**item, "source": "materials_audit"} for item in issues)
                self.story_states.commit(candidate.id, state.revision,
                                         {**state.data, "issue_ledger": ledger})
            self.db.update_run(run_id, "completed", "archive")
            return self.db.get_run(run_id) or {"id": run_id, "status": "completed"}
        except asyncio.CancelledError:
            self.db.update_run(run_id, "cancelled", error="Cancelled by user")
            raise
        except Exception as exc:
            self.db.update_run(run_id, "failed", error=str(exc))
            raise

    async def _materials_repair_pipeline(self, project: Project,
                                         run_id: str | None = None) -> dict:
        run_id, run_path = self._begin_run(project, "materials-repair", run_id)
        try:
            audit = next((item for item in self.db.list_runs(project.id)
                          if item["workflow"] == "materials-audit" and item["status"] == "completed"), None)
            if not audit:
                raise RuntimeError("Run a material conflict audit before repair")
            report_path = project.path / "runs" / audit["id"] / "outputs" / "conflict-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            issues = report.get("issues", [])
            if not issues:
                raise RuntimeError("The latest material audit has no conflicts to repair")
            manuscript = self._material_manuscript(project)
            constraints = self.projects.load_constraints(project.id)
            repaired = await self._polish_short_segments(
                run_id, run_path, project, constraints, manuscript,
                json.dumps({"material_conflicts": issues}, ensure_ascii=False),
                suffix="-materials", structural=True,
            )
            initial = normalize_review({
                "score": 80, "dimensions": {"commercial": 80, "story": 80, "prose": 80},
                "hard_fail": False, "decision": "revise", "issues": issues,
            })
            final, evidence = await self._full_manuscript_review(
                run_id, run_path, project, constraints, repaired, initial,
                suffix="-materials",
            )
            outcome, reasons = quality_outcome(final)
            atomic_write(run_path / "outputs" / "best-candidate.md", repaired)
            atomic_write(run_path / "outputs" / "quality-report.json", json.dumps({
                "status": outcome, "failure_reasons": reasons, "final_review": final,
                "final_review_evidence": evidence, "source_audit": audit["id"],
            }, ensure_ascii=False, indent=2))
            if outcome == "failed":
                raise RuntimeError("Material conflict repair did not pass the final quality gate")
            self.db.update_run(run_id, "completed", "archive")
            return self.db.get_run(run_id) or {"id": run_id, "status": "completed"}
        except asyncio.CancelledError:
            self.db.update_run(run_id, "cancelled", error="Cancelled by user")
            raise
        except Exception as exc:
            self.db.update_run(run_id, "failed", error=str(exc))
            raise

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
            draft_analysis = self._analyze_manuscript(draft, run_path, project, "draft")
            review = self._review(await self._stage(
                run_id, run_path, project, "review", constraints,
                f"MEMORY:\n{json.dumps(context, ensure_ascii=False)}\n\nDRAFT:\n{draft}\n\n"
                "LOCAL FULL MANUSCRIPT SUMMARY:\n"
                f"{json.dumps(compact_analysis(draft_analysis), ensure_ascii=False)}",
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
        snapshot = ProjectSnapshot.create(
            project.path,
            project.path / "snapshots" / f"{run_id}-{uuid.uuid4().hex[:8]}",
            formal,
        )
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
                    "short_causal_chain_contract": {
                        "purpose": "append whole-story causal-chain JSON without replacing the outline",
                        "start_marker": "SHORT_CAUSAL_CHAIN_JSON_START",
                        "end_marker": "SHORT_CAUSAL_CHAIN_JSON_END",
                        "fields": [
                            "core_goal", "opening", "cycles", "accidents", "reversal", "ending",
                            "question_chain", "relationship_arc",
                        ],
                        "cycle_shape": [
                            "obstacle", "effort", "result", "state_change", "escalation", "next_question",
                        ],
                        "opening_shape": [
                            "pressure", "anomaly", "reader_question", "future_promise",
                        ],
                        "ending_shape": ["surface_goal", "inner_goal", "cost"],
                    },
                }, ensure_ascii=False, indent=2)
                plan = await self._stage(
                    run_id, run_path, project, "planning", constraints, brief,
                    allow_tools=self._planning_uses_tools(state),
                )
                plan, causal_chain = self._extract_and_save_short_causal_chain(
                    run_id, run_path, project, plan,
                )
                if causal_chain:
                    constraints += (
                        "\n\n# Short Story Causal Chain\n\n"
                        f"{compact_causal_chain(causal_chain)}"
                    )
                draft = await self._draft_short_in_segments(
                    run_id, run_path, project, constraints, plan,
                )
            draft_analysis = self._analyze_manuscript(
                draft, run_path, project, "draft",
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
                    f"{reader_sample(draft, project.mode, limit=6000)}\n\n"
                    "LOCAL FULL MANUSCRIPT SUMMARY:\n"
                    f"{json.dumps(compact_analysis(draft_analysis), ensure_ascii=False)}"
                )
                review_text = await self._stage(
                    run_id, run_path, project, "review", constraints, review_input,
                    allow_tools=False,
                )
                review = self._review(review_text)
            if checkpoint and checkpoint.parent.name == run_id:
                polish_parts = self._split_polish_segments(draft)
                checkpoint_root = run_path / "outputs" / "polish-checkpoints" / "initial"
                completed_parts, next_part = self._polish_checkpoint_progress(
                    checkpoint_root, polish_parts,
                    self._polish_retry_signature(self.db.get_role_binding("polish") or {}),
                )
                self.db.add_run_event(
                    run_id, "success", "polish_resume_ready",
                    f"已复用当前任务的规划、完整草稿和审核，将从润色第 {next_part}/{len(polish_parts)} 段继续",
                    stage="polish", metadata={
                        "completed_segments": completed_parts,
                        "next_segment": next_part,
                        "total_segments": len(polish_parts),
                    },
                )
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
                if isinstance(fact, dict):
                    key = str(fact.get("fact_key") or fact.get("subject") or f"generated.{index}")
                    value = fact.get("value", fact.get("fact", ""))
                elif isinstance(fact, str):
                    key, value = f"generated.{index}", fact
                else:
                    continue
                confirmed.append({
                    "key": key,
                    "value": value,
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

    def _extract_and_save_short_causal_chain(
        self, run_id: str, run_path: Path, project: Project, plan: str,
    ) -> tuple[str, dict | None]:
        try:
            outline, chain = extract_short_causal_chain(plan)
        except (ValueError, json.JSONDecodeError) as exc:
            self.db.add_run_event(
                run_id, "warning", "causal_chain_parse_failed",
                "短篇因果链解析失败，已继续使用原大纲",
                stage="planning", metadata={"error": str(exc)[:300]},
            )
            return plan, None
        if not chain:
            return plan, None
        LearningSystem(self.db, self.references, self.projects, self.gateway).build_short_causal_chain(
            project.id, chain,
        )
        atomic_write(run_path / "outputs" / "planning.md", outline)
        self.db.add_run_event(
            run_id, "success", "causal_chain_saved",
            "短篇整篇因果链已保存为项目资料",
            stage="planning", metadata={"cycles": len(chain.get("cycles") or [])},
        )
        return outline, chain

    async def _quality_polish(self, run_id: str, run_path: Path, project: Project,
                              constraints: str, draft: str, review: dict,
                              chapter_number: int | None = None,
                              chapter_goal: str = "", volume_end: bool = False) -> tuple[str, dict]:
        route = select_route(
            project.mode, chapter_number, chapter_goal, volume_end, review,
        )
        previous_best = self._previous_quality_best(run_path)
        report = {
            "route": route,
            "initial_review": review,
            "reader_review": None,
            "final_attempts": [],
            "status": "running",
            "failure_reasons": [],
            "best_attempt": previous_best["best_attempt"] if previous_best else None,
            "best_score": previous_best["score"] if previous_best else None,
        }
        self._write_quality_report(run_path, report)
        if previous_best:
            self.db.add_run_event(
                run_id, "success", "quality_best_restored",
                "已保留上次运行的最高分稿，本轮只有更高分版本才会替换它",
                stage="quality", metadata={"best_score": previous_best["score"]},
            )
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
            self._halt_quality_revision(
                run_id, run_path, report,
                previous_best["text"] if previous_best else draft, exc,
            )
        review_text = "\n\n".join(self._split_segments(polished))
        current_analysis = self._analyze_manuscript(
            review_text, run_path, project, "polish",
        )
        baseline: dict | None = None
        revision_source_hash: str | None = None
        applied_patch_groups: tuple[dict, ...] = ()
        active_profile = profile_for_project(project)

        reasons: list[str] = []
        best_polished = previous_best["text"] if previous_best else polished
        best_review: dict | None = (
            previous_best.get("review") or {"score": previous_best["score"]}
            if previous_best else None
        )
        best_attempt: int | None = (
            previous_best["best_attempt"] if previous_best else None
        )
        best_outcome = str(previous_best.get("outcome") or "") if previous_best else ""
        for attempt in range(route["max_corrections"] + 1):
            reviewed_polished = polished
            review_text = "\n\n".join(self._split_segments(polished))
            final_input = review_text
            if attempt:
                checks_path = run_path / "outputs" / f"revision-checks-{attempt + 1}.json"
                if checks_path.is_file():
                    failures = json.loads(checks_path.read_text(encoding="utf-8")).get("failures", [])
                    if failures:
                        final_input += (
                            "\n\nRUNTIME STRUCTURAL CHECK FAILURES. Treat unresolved failures as hard "
                            f"evidence:\n{json.dumps(failures, ensure_ascii=False)}"
                        )
            try:
                optimized = bool(project.metadata.get("optimized_local_review_enabled", False))
                if attempt and optimized and baseline is not None:
                    final_review, evidence_audit = await self._incremental_manuscript_review(
                        run_id, run_path, project, constraints, review_text,
                        current_analysis, baseline, review,
                        suffix=f"-{attempt + 1}",
                        revision_source_hash=revision_source_hash,
                        patch_groups=applied_patch_groups,
                    )
                    report["final_review_evidence"] = evidence_audit
                elif project.mode == "short" and len(final_input) > 6000:
                    final_review, evidence_audit = await self._full_manuscript_review(
                        run_id, run_path, project, constraints, final_input, review,
                        suffix=f"-{attempt + 1}" if attempt else "",
                    )
                    report["final_review_evidence"] = evidence_audit
                else:
                    final_input = (
                        quality_profile_prompt(active_profile)
                        + self._causal_chain_review_checks(constraints)
                        + final_input
                    )
                    raw_final_review = await self._stage(
                        run_id, run_path, project, "final_review", constraints, final_input,
                        suffix=f"-{attempt + 1}" if attempt else "", allow_tools=False,
                    )
                    final_review = self._review_for_project(
                        raw_final_review, project,
                        getattr(raw_final_review, "receipt", {}),
                    )
                    evidence_audit = {
                        "coverage": 1.0, "window_count": 1, "reviewed_windows": 1,
                        "windows": [{"index": 1, "start": 0, "end": len(polished),
                                     "summary": "single-request complete review"}],
                    }
                if attempt == 0:
                    baseline_review = {
                        **final_review,
                        "issues": [
                            *review.get("issues", []),
                            *final_review.get("issues", []),
                        ],
                    }
                    baseline = build_review_baseline(
                        review_text, current_analysis,
                        evidence_audit.get("windows", []), baseline_review,
                    )
                    atomic_write(
                        run_path / "outputs" / "final-review-baseline.json",
                        json.dumps(baseline, ensure_ascii=False, indent=2),
                    )
                report.setdefault("review_scope_history", []).append({
                    "attempt": attempt + 1,
                    "mode": evidence_audit.get("review_mode", "full"),
                    "reviewed_windows": evidence_audit.get("reviewed_windows", 1),
                    "window_count": evidence_audit.get("window_count", 1),
                    "selection_reasons": evidence_audit.get("selection_reasons", {}),
                    "fallback_reasons": evidence_audit.get("fallback_reasons", []),
                    "estimated_saved_input_characters": evidence_audit.get(
                        "estimated_saved_input_characters", 0,
                    ),
                })
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                validation_failed = isinstance(exc, ValueError)
                if validation_failed:
                    report_status = "final_review_rejected"
                    event_type = "final_review_result_rejected"
                    message = "终审模型已返回，但结果未通过系统校验，已保留最佳稿"
                else:
                    report_status = "final_review_incomplete"
                    event_type = "final_review_model_failed"
                    message = "终审模型调用失败，已保留最佳稿"
                report["status"] = report_status
                report["terminal_review_complete"] = False
                report["failure_reasons"] = [message]
                atomic_write(run_path / "outputs" / "best-candidate.md", best_polished)
                self._write_quality_report(run_path, report)
                self.db.add_run_event(
                    run_id, "error", event_type, message,
                    stage="final_review", metadata={"error": str(exc)},
                )
                raise RuntimeError(message) from exc
            final_review["issues"] = issue_ledger(final_review.get("issues", []))
            outcome, reasons = quality_outcome_for_profile(final_review, active_profile)
            passed = (
                outcome == "passed"
                if active_profile == "zhihu-short-v2"
                else outcome != "failed"
            )
            report["final_attempts"].append({
                "attempt": attempt + 1,
                "review": final_review,
                "passed": passed,
                "outcome": outcome,
                "reasons": reasons,
            })
            report["terminal_review_complete"] = True
            comparison = None
            if best_review is not None and active_profile == "zhihu-short-v2":
                comparison = compare_quality_candidates(best_review, final_review)
            promote = (
                best_review is None
                or (
                    active_profile != "zhihu-short-v2"
                    and final_review["score"] > best_review["score"]
                )
                or bool(comparison and comparison["promote"])
                or bool(
                    comparison and not comparison["comparable"]
                    and outcome == "passed"
                    and final_review.get("scoring_profile_id") == active_profile
                )
            )
            if promote:
                best_review = final_review
                best_polished = reviewed_polished
                best_attempt = attempt + 1
                best_outcome = outcome
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
                retained_previous = bool(
                    previous_best
                    and final_review["score"] < float(previous_best["score"])
                )
                selected = best_polished if retained_previous else polished
                selected_review = best_review if retained_previous else final_review
                selected_outcome = (
                    str(previous_best.get("outcome") or "passed")
                    if retained_previous else outcome
                )
                if selected_outcome not in {"passed", "conditional_pass"}:
                    selected_outcome = "passed" if float(
                        (selected_review or {}).get("score", 0)
                    ) >= 80 else "conditional_pass"
                selected_review_text = "\n\n".join(self._split_segments(selected))
                report["status"] = selected_outcome
                report["failure_reasons"] = []
                report["terminal_reviewed_hash"] = hashlib.sha256(
                    selected_review_text.encode("utf-8")
                ).hexdigest()
                if retained_previous:
                    self.db.add_run_event(
                        run_id, "success", "quality_best_retained",
                        "本轮候选达到最低门槛，但没有超过受保护最佳稿，已继续保留最佳稿",
                        stage="quality", metadata={
                            "candidate_score": final_review["score"],
                            "best_score": previous_best["score"],
                        },
                    )
                report["scoring_profile_id"] = str(
                    (selected_review or {}).get("scoring_profile_id") or "legacy-v1"
                )
                report["judge_signature"] = str(
                    (selected_review or {}).get("judge_signature") or "legacy-unknown"
                )
                report["terminal_review"] = selected_review
                if not retained_previous and selected_review:
                    self._save_quality_checkpoint(
                        run_path, selected_review_text, selected_review,
                        best_attempt, selected_outcome,
                    )
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
                return selected, report
            if attempt < route["max_corrections"]:
                self.db.add_run_event(
                    run_id, "warning", "quality_revision",
                    f"质量未达标，开始第 {attempt + 1} 次定向返工",
                    stage="polish", metadata={
                        "attempt": attempt + 1, "reasons": reasons,
                    },
                )
                try:
                    revision_source_hash = hashlib.sha256(
                        best_polished.encode("utf-8")
                    ).hexdigest()
                    polished = await self._polish_short_segments(
                        run_id, run_path, project, constraints, best_polished,
                        json.dumps(final_review, ensure_ascii=False),
                        suffix=f"-{attempt + 2}", structural=True,
                    )
                    current_analysis = self._analyze_manuscript(
                        "\n\n".join(self._split_segments(polished)),
                        run_path, project, f"polish-{attempt + 2}",
                    )
                    applied_patch_groups = ()
                except (RevisionPlanError, PolishTokenBudgetError) as exc:
                    self._halt_quality_revision(
                        run_id, run_path, report, best_polished, exc,
                    )

        if (active_profile == "zhihu-short-v2"
                and best_outcome == "conditional_pass" and best_review):
            clean_best = "\n\n".join(self._split_segments(best_polished))
            report["status"] = "conditional_pass"
            report["failure_reasons"] = []
            report["terminal_review"] = best_review
            report["scoring_profile_id"] = "zhihu-short-v2"
            report["judge_signature"] = str(
                best_review.get("judge_signature") or "legacy-unknown"
            )
            report["terminal_reviewed_hash"] = hashlib.sha256(
                clean_best.encode("utf-8")
            ).hexdigest()
            self._save_quality_checkpoint(
                run_path, clean_best, best_review, best_attempt, "conditional_pass",
            )
            self._write_quality_report(run_path, report)
            self.db.add_run_event(
                run_id, "warning", "quality_conditional_pass",
                "候选稿达到条件通过，但还不能设为正式稿",
                stage="quality", metadata={
                    "score": best_review["score"],
                    "dimensions": best_review["dimensions"],
                },
            )
            raise RuntimeError(
                "Editorial quality gate requires a full pass; preserved conditional candidate"
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

    @staticmethod
    def _save_quality_checkpoint(
        run_path: Path, manuscript: str, review: dict,
        attempt: int | None, outcome: str,
    ) -> None:
        atomic_write(run_path / "outputs" / "best-candidate.md", manuscript)
        digest = hashlib.sha256(manuscript.encode("utf-8")).hexdigest()
        write_quality_checkpoint(run_path, {
            "manuscript_path": "outputs/best-candidate.md",
            "manuscript_hash": digest,
            "score": float(review["score"]),
            "scoring_profile_id": str(
                review.get("scoring_profile_id") or "legacy-v1"
            ),
            "judge_signature": str(
                review.get("judge_signature") or "legacy-unknown"
            ),
            "best_attempt": attempt,
            "review": review,
            "issue_ledger": issue_ledger(review.get("issues", [])),
            "outcome": outcome,
            "terminal_reviewed_hash": digest,
        })

    async def _final_review_json(
        self, run_id: str, run_path: Path, project: Project, constraints: str,
        prompt: str, suffix: str,
    ) -> tuple[str, dict]:
        raw = await self._stage(
            run_id, run_path, project, "final_review", constraints, prompt,
            suffix=suffix, allow_tools=False,
        )
        try:
            return raw, self._json_object(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            binding = self.db.get_role_binding("final_review") or {}
            configured_fallback = bool(
                binding.get("fallback_provider_id") and binding.get("fallback_model_id")
                and hasattr(self.gateway, "complete_configured_fallback")
            )
            if not configured_fallback:
                raise
            self.db.add_run_event(
                run_id, "warning", "final_review_json_fallback",
                "终审模型返回内容不完整，正在用备用模型重做当前检查",
                stage="final_review", metadata={
                    "suffix": suffix, "error": str(exc)[:300],
                },
            )
            raw = await self._stage(
                run_id, run_path, project, "final_review", constraints, prompt,
                suffix=f"{suffix}-json-fallback", allow_tools=False,
                prefer_configured_fallback=True,
            )
            return raw, self._json_object(raw)

    async def _full_manuscript_review(
        self, run_id: str, run_path: Path, project: Project, constraints: str,
        manuscript: str, initial_review: dict, suffix: str = "",
    ) -> tuple[dict, dict]:
        constraints = self._constraints_with_platform_rules(project, constraints)
        causal_checks = self._causal_chain_review_checks(constraints)
        windows = review_windows(manuscript)
        ledger = issue_ledger(initial_review.get("issues", []))
        evidence = []
        previous_summary = ""
        for window in windows:
            prompt = (
                "FULL MANUSCRIPT EVIDENCE EXTRACTION. Do not score or rewrite. Return one JSON "
                "object with summary, events, character_states, timeline, promises, and issues. "
                "summary should be a concise non-empty string; structured summaries are accepted but unnecessary. "
                "Every issue must include category, severity, evidence, location, and action. "
                "Track what each character knows and when causally important actions become possible.\n\n"
                f"WINDOW {window['index']}/{len(windows)} "
                f"CHARACTERS {window['start']}-{window['end']}\n"
                f"PREVIOUS WINDOW SUMMARY:\n{previous_summary or 'None'}\n\n"
                f"INITIAL ISSUE LEDGER:\n{json.dumps(ledger, ensure_ascii=False)}\n\n"
                f"{causal_checks}"
                f"MANUSCRIPT WINDOW:\n{window['text']}"
            )
            raw, item = await self._final_review_json(
                run_id, run_path, project, constraints, prompt,
                suffix=f"{suffix}-window-{window['index']}",
            )
            summary = item.get("summary")
            if isinstance(summary, (dict, list)) and summary:
                summary = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
            if not isinstance(summary, str) or not summary.strip():
                raise ValueError(f"Final review window {window['index']} has no summary")
            item["summary"] = summary.strip()
            item["window"] = window["index"]
            item["start"] = window["start"]
            item["end"] = window["end"]
            item["receipt"] = getattr(raw, "receipt", {})
            evidence.append(item)
            previous_summary = item["summary"]

        adjudication_prompt = (
            quality_profile_prompt(profile_for_project(project))
            +
            "FULL MANUSCRIPT FINAL ADJUDICATION. Use the ordered window evidence as a global story "
            "map and perform cross-window checks for timeline, character state and knowledge, causal "
            "authority/evidence, relationship transitions, setup/payoff, and premise follow-through. "
            "Return strict quality-review JSON plus reconciliations. Each initial issue must appear once "
            "with issue_id, status (resolved, partially_resolved, unresolved, or not_found), severity, "
            "and concrete evidence. Omission never means resolved. Do not rewrite the manuscript.\n\n"
            f"INITIAL ISSUE LEDGER:\n{json.dumps(ledger, ensure_ascii=False)}\n\n"
            f"{causal_checks}"
            f"ORDERED WINDOW EVIDENCE:\n{json.dumps(evidence, ensure_ascii=False)}"
        )
        raw_final, payload = await self._final_review_json(
            run_id, run_path, project, constraints, adjudication_prompt,
            suffix=f"{suffix}-adjudication",
        )
        review = self._review_for_project(
            payload, project, getattr(raw_final, "receipt", {}),
        )
        prior_issue_ids = [item["issue_id"] for item in ledger]
        prior_issue_id_set = set(prior_issue_ids)
        raw_reconciliations = payload.get("reconciliations", [])
        valid_reconciliations = (
            isinstance(raw_reconciliations, list)
            and all(isinstance(item, dict) for item in raw_reconciliations)
        )
        reconciliation_summary = (
            raw_reconciliations if isinstance(raw_reconciliations, dict) else None
        )
        if valid_reconciliations:
            reconciliations = raw_reconciliations
        else:
            reconciliations = [
                item for item in payload.get("issues", [])
                if isinstance(item, dict) and item.get("issue_id") in prior_issue_id_set
            ]
            self.db.add_run_event(
                run_id, "warning", "final_review_reconciliation_recovered",
                "终审返回的逐项复核格式不标准，已从问题清单恢复可核对结果",
                stage="final_review", metadata={
                    "returned_type": type(raw_reconciliations).__name__,
                    "recovered_count": len(reconciliations),
                    "expected_count": len(prior_issue_ids),
                },
            )
        audit = {
            "coverage": 1.0 if windows and evidence[-1]["end"] == len(manuscript) else 0.0,
            "window_count": len(windows),
            "reviewed_windows": len(evidence),
            "evidence_count": sum(bool(item.get("summary")) for item in evidence),
            "prior_issue_ids": prior_issue_ids,
            "reconciliations": reconciliations,
            "windows": evidence,
            "adjudication_receipt": getattr(raw_final, "receipt", {}),
            "review_mode": "full",
        }
        if reconciliation_summary is not None:
            audit["reconciliation_summary"] = reconciliation_summary
        review, gate_reasons = apply_evidence_gate(review, audit)
        audit["gate_reasons"] = gate_reasons
        audit["reconciliation_counts"] = {
            status: sum(item.get("status") == status for item in audit["reconciliations"])
            for status in ("resolved", "partially_resolved", "unresolved", "not_found")
        }
        atomic_write(
            run_path / "outputs" / f"final-review-evidence{suffix}.json",
            json.dumps({"windows": evidence, "audit": audit}, ensure_ascii=False, indent=2),
        )
        return review, audit

    @staticmethod
    def _causal_chain_review_checks(constraints: str) -> str:
        if "Short Story Causal Chain" not in constraints:
            return ""
        return (
            "CAUSAL CHAIN CHECKS:\n"
            "- Verify the manuscript establishes the core goal.\n"
            "- Verify opening pressure, anomalous action, reader question, and future promise create honest pull.\n"
            "- Verify obstacle-effort-result cycles create state changes instead of repetition.\n"
            "- Verify each result escalates cost, risk, knowledge, relationship, or available choice and opens the next question.\n"
            "- Verify accidents change the situation.\n"
            "- Verify reversal reinterprets earlier evidence rather than appearing from nowhere.\n"
            "- Verify question continuity and relationship progression are caused by on-page events.\n"
            "- Verify the ending answers surface goal, inner goal, and ending cost.\n\n"
        )

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

    async def _incremental_manuscript_review(
        self, run_id: str, run_path: Path, project: Project, constraints: str,
        manuscript: str, analysis: dict, baseline: dict, initial_review: dict,
        suffix: str = "", revision_source_hash: str | None = None,
        patch_groups: Sequence[dict] = (),
    ) -> tuple[dict, dict]:
        constraints = self._constraints_with_platform_rules(project, constraints)
        baseline_reasons = incremental_precheck_reasons(
            baseline, analysis, manuscript, revision_source_hash,
        )
        if baseline_reasons:
            review, audit = await self._full_manuscript_review(
                run_id, run_path, project, constraints, manuscript, initial_review, suffix,
            )
            audit.update({
                "review_mode": "full_fallback",
                "fallback_reasons": baseline_reasons,
            })
            return review, audit
        changes = diff_manuscripts(
            baseline["manuscript"], manuscript, baseline["analysis"], analysis,
            mode="long" if project.mode == "long" else "short",
            patch_groups=patch_groups,
        )
        scope = select_review_scope(baseline, analysis, changes)
        scope_reasons = incremental_precheck_reasons(
            baseline, analysis, manuscript, revision_source_hash,
            scope=scope, changes_present=bool(changes.get("ranges")),
        )
        if scope_reasons:
            review, audit = await self._full_manuscript_review(
                run_id, run_path, project, constraints, manuscript, initial_review, suffix,
            )
            audit.update({
                "review_mode": "full_fallback",
                "fallback_reasons": scope_reasons,
                "incremental_scope": scope,
            })
            return review, audit
        full, fallback_reasons = requires_full_review(
            scope, changes, analysis, patch_groups=patch_groups,
            source_manuscript=baseline["manuscript"], current_manuscript=manuscript,
        )
        if full:
            review, audit = await self._full_manuscript_review(
                run_id, run_path, project, constraints, manuscript, initial_review, suffix,
            )
            audit.update({
                "review_mode": "full_fallback",
                "fallback_reasons": fallback_reasons,
                "incremental_scope": scope,
            })
            return review, audit

        selected = set(scope["selected_windows"])
        evidence = []
        ledger = baseline.get("issue_ledger", [])
        baseline_by_index = {
            item.get("window", item.get("index")): item
            for item in baseline.get("evidence", [])
        }
        for window in analysis.get("windows", []):
            if window["index"] not in selected:
                continue
            prompt = (
                "INCREMENTAL FINAL REVIEW EVIDENCE. Do not rewrite. Review the current window "
                "against its first-full-review baseline and the structured local change evidence. "
                "Return JSON with summary, events, character_states, timeline, promises, and issues.\n\n"
                f"SELECTION REASONS:\n{json.dumps(scope['reasons'].get(str(window['index']), []), ensure_ascii=False)}\n\n"
                f"BASELINE EVIDENCE:\n{json.dumps(baseline_by_index.get(window['index'], {}), ensure_ascii=False)}\n\n"
                f"CHANGES:\n{json.dumps(changes, ensure_ascii=False)}\n\n"
                f"CURRENT WINDOW:\n{window['text']}"
            )
            raw, item = await self._final_review_json(
                run_id, run_path, project, constraints, prompt,
                suffix=f"{suffix}-incremental-window-{window['index']}",
            )
            summary = item.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                raise ValueError(f"Incremental review window {window['index']} has no summary")
            item.update({
                "window": window["index"], "start": window["start"], "end": window["end"],
                "receipt": getattr(raw, "receipt", {}),
            })
            evidence.append(item)

        prompt = (
            quality_profile_prompt(profile_for_project(project))
            +
            "INCREMENTAL FINAL ADJUDICATION. Reconcile every prior issue and judge only whether "
            "the correction remains globally safe. Return strict quality-review JSON plus "
            "reconciliations. Every reconciliation status must be exactly resolved, unresolved, "
            "or uncertain. Set request_full_review=true if evidence is insufficient.\n\n"
            f"BASELINE REVIEW:\n{json.dumps(baseline.get('review', {}), ensure_ascii=False)}\n\n"
            f"ISSUE LEDGER:\n{json.dumps(ledger, ensure_ascii=False)}\n\n"
            f"CHANGES:\n{json.dumps(changes, ensure_ascii=False)}\n\n"
            f"SELECTED EVIDENCE:\n{json.dumps(evidence, ensure_ascii=False)}"
        )
        raw, payload = await self._final_review_json(
            run_id, run_path, project, constraints, prompt,
            suffix=f"{suffix}-incremental-adjudication",
        )
        if payload.get("request_full_review"):
            changes["reviewer_requested_full"] = True
            review, audit = await self._full_manuscript_review(
                run_id, run_path, project, constraints, manuscript, initial_review, suffix,
            )
            audit.update({"review_mode": "full_fallback",
                          "fallback_reasons": ["reviewer_requested_full"]})
            return review, audit
        review = self._review_for_project(
            payload, project, getattr(raw, "receipt", {}),
        )
        review, gate_reasons = apply_incremental_gate(
            review, baseline, scope, analysis, manuscript,
            payload.get("reconciliations", []),
        )
        if gate_reasons:
            full_review, audit = await self._full_manuscript_review(
                run_id, run_path, project, constraints, manuscript, initial_review, suffix,
            )
            audit.update({"review_mode": "full_fallback", "fallback_reasons": gate_reasons})
            return full_review, audit
        full_input = sum(len(item.get("text", "")) for item in analysis.get("windows", []))
        reviewed_input = sum(len(item.get("text", "")) for item in analysis.get("windows", [])
                             if item["index"] in selected)
        audit = {
            "coverage": 1.0,
            "review_mode": "incremental",
            "window_count": len(analysis.get("windows", [])),
            "reviewed_windows": len(evidence),
            "selected_windows": sorted(selected),
            "selection_reasons": scope["reasons"],
            "windows": evidence,
            "reconciliations": payload.get("reconciliations", []),
            "estimated_full_input_characters": full_input,
            "reviewed_input_characters": reviewed_input,
            "estimated_saved_input_characters": max(0, full_input - reviewed_input),
            "adjudication_receipt": getattr(raw, "receipt", {}),
        }
        atomic_write(
            run_path / "outputs" / f"incremental-review{suffix}.json",
            json.dumps({"changes": changes, "scope": scope, "audit": audit},
                       ensure_ascii=False, indent=2),
        )
        return review, audit

    @staticmethod
    def _planning_uses_tools(state) -> bool:
        return state.revision > 1

    @staticmethod
    def _short_segment_count(target_words: int) -> int:
        if target_words <= 8000:
            return 1
        return min(12, max(2, math.ceil(target_words / 2500)))

    @classmethod
    def _split_segments(cls, text: str) -> list[str]:
        return [part.strip() for part in text.split(cls.SHORT_SEGMENT_SEPARATOR) if part.strip()]

    @classmethod
    def _split_polish_segments(cls, text: str, target: int = 1400,
                               maximum: int = 1800) -> list[str]:
        chunks: list[str] = []
        for original in cls._split_segments(text):
            first_chunk = len(chunks)
            paragraphs = [item.strip() for item in re.split(r"\n\s*\n", original) if item.strip()]
            units: list[str] = []
            for paragraph in paragraphs:
                units.append(paragraph)
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
            if run["workflow"] != "short-story":
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
            if run["workflow"] != "short-story":
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
                                     suffix: str = "", structural: bool = False,
                                     recovery_depth: int = 0,
                                     recovery_rule: str | None = None,
                                     prepared_revision_plan: dict | None = None,
                                     round_cap_override: int | None = None,
                                     batch_number: int = 1,
                                     targeted_context: dict | None = None) -> str:
        original_parts = self._split_segments(text)

        def boundary_paragraph(segment: str, *, first: bool) -> str:
            paragraphs = [item.strip() for item in re.split(r"\n\s*\n", segment) if item.strip()]
            return (paragraphs[0] if first else paragraphs[-1]) if paragraphs else ""

        targeted = bool(structural or targeted_context)
        grouped_parts = (
            [(part, group) for group, part in enumerate(original_parts, 1)]
            if targeted else [
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
        passage_service = PassageProtectionService(self.db)
        project_passage_locks = self.db.list_locks(project.id)
        if structural and targeted_context is None and len(parts) > 1:
            if prepared_revision_plan is None:
                revision_plan = await self._plan_structural_revision(
                    run_id, run_path, project, constraints, findings, story_map, suffix,
                )
                full_plan = {
                    **revision_plan,
                    "tasks": [
                        *revision_plan["tasks"],
                        *revision_plan.get("deferred_tasks", []),
                    ],
                }
                full_plan, target_corrections = align_revision_plan_targets(
                    full_plan, original_parts,
                )
                revision_plan = self._normalized_revision_plan(
                    full_plan, len(story_map), max_target_ratio=0.4,
                    require_checks=bool(full_plan.get("checks")),
                    defer_excess_targets=True,
                )
            else:
                target_corrections = []
                revision_plan = self._normalized_revision_plan(
                    prepared_revision_plan, len(story_map), max_target_ratio=0.4,
                    require_checks=bool(prepared_revision_plan.get("checks")),
                    defer_excess_targets=True,
                )
            if target_corrections:
                atomic_write(
                    run_path / "outputs" / f"revision-plan{suffix}.json",
                    json.dumps(revision_plan, ensure_ascii=False, indent=2),
                )
                self.db.add_run_event(
                    run_id, "warning", "revision_targets_aligned",
                    "Runtime corrected revision targets using exact manuscript search",
                    stage="revision_plan", metadata={"corrections": target_corrections},
                )
        elif not targeted and recovery_rule is None:
            try:
                findings = json.dumps(
                    compact_polish_findings(json.loads(findings)), ensure_ascii=False,
                )
            except (json.JSONDecodeError, TypeError):
                findings = findings[:4000]
        revision_rule = recovery_rule or (
            "You may replace or remove implausible events and reorder material inside this segment "
            "to resolve the findings. Preserve the core premise, required ending, established facts, "
            "and approximate length."
            if targeted else
            "Preserve events and length; remove AI-like phrasing and apply the findings."
        )
        style_profile = ensure_style_profile(project)
        polished_parts: list[str] = []
        primary_circuit_open = any(
            event["event_type"] == "polish_circuit_opened"
            for event in self.db.list_run_events(run_id)
        )
        binding = self.db.get_role_binding("polish") or {}
        retry_signature = self._polish_retry_signature(binding)
        configured_fallback = bool(
            binding.get("fallback_provider_id") and binding.get("fallback_model_id")
            and hasattr(self.gateway, "complete_configured_fallback")
        )
        checkpoint_root = (
            run_path / "outputs" / "polish-checkpoints" / (suffix.strip("-") or "initial")
        )
        round_input_tokens = 0
        round_cap = (round_cap_override if round_cap_override is not None
                     else self._polish_round_input_cap(targeted, len(parts)))
        for index, part in enumerate(parts, 1):
            group = part_groups[index - 1]
            if revision_plan and group not in revision_plan["target_segments"]:
                polished_parts.append(part)
                continue
            cached = self._load_polish_checkpoint(
                checkpoint_root, index, part, retry_signature,
            )
            if cached is not None:
                polished_parts.append(cached)
                self.db.add_run_event(
                    run_id, "success", "polish_checkpoint_reused",
                    f"润色第 {index}/{len(parts)} 段已从检查点恢复",
                    stage="polish", metadata={"segment": index, "route": "checkpoint"},
                )
                continue
            if round_input_tokens >= round_cap:
                self.db.add_run_event(
                    run_id, "error", "token_budget_exhausted",
                    "Polish input token budget exhausted; stopped before the next model call",
                    stage="polish", metadata={
                        "limit": "round",
                        "round_input_tokens": round_input_tokens,
                        "round_cap": round_cap,
                        "next_segment": index,
                    },
                )
                raise PolishTokenBudgetError("Polish round input token budget exhausted")
            previous_tail = polished_parts[-1][-800:] if polished_parts else ""
            next_head = parts[index][:800] if index < len(parts) else ""
            local_report = analyze_prose(part)
            passage_locks = applicable_passage_locks(project_passage_locks, part)
            if targeted_context:
                tasks = targeted_context["tasks"]
                linked_checks = targeted_context["checks"]
                global_facts = targeted_context["global_facts"]
                previous_context = (
                    boundary_paragraph(parts[index - 2], first=False) if index > 1
                    else targeted_context["previous_paragraph"]
                )
                next_context = (
                    boundary_paragraph(parts[index], first=True) if index < len(parts)
                    else targeted_context["next_paragraph"]
                )
            elif revision_plan:
                tasks = [task for task in revision_plan["tasks"] if group in task["segments"]]
                task_issue_ids = {
                    issue_id for task in tasks for issue_id in task.get("issue_ids", [])
                }
                linked_checks = [
                    check for check in revision_plan["checks"]
                    if task_issue_ids.intersection(check.get("issue_ids", []))
                ]
                global_facts = revision_plan["global_facts"]
                previous_context = (
                    boundary_paragraph(original_parts[group - 2], first=False) if group > 1 else ""
                )
                next_context = (
                    boundary_paragraph(original_parts[group], first=True)
                    if group < len(original_parts) else ""
                )
            else:
                tasks = []
                linked_checks = []
                global_facts = []
                previous_context = previous_tail
                next_context = next_head
            positions = list(dict.fromkeys(
                task["seven_step_position"] for task in tasks
                if task.get("seven_step_position")
            ))
            seven_step_position = "；".join(positions) if positions else "未标注"
            current_targeted_context = {
                "tasks": tasks,
                "checks": linked_checks,
                "global_facts": global_facts,
                "previous_paragraph": previous_context,
                "next_paragraph": next_context,
                "seven_step_position": seven_step_position,
                "segment": (targeted_context or {}).get("segment", group),
            }
            plan_context = (
                f"GLOBAL FACTS AND LOCKS:\n{json.dumps(revision_plan['global_facts'], ensure_ascii=False)}\n\n"
                f"TASKS FOR THIS SEGMENT:\n{json.dumps(tasks, ensure_ascii=False)}\n\n"
                f"DETERMINISTIC CHECKS:\n{json.dumps(revision_plan['checks'], ensure_ascii=False)}\n\n"
                f"COMPACT FULL STORY MAP:\n{json.dumps(story_map, ensure_ascii=False)}\n\n"
                if revision_plan else f"STRUCTURED FINDINGS:\n{findings}\n\n"
            )
            preferred_minimum_ratio = 0.60 if targeted else 0.70
            minimum_ratio, maximum_ratio = ((0.50, 1.80) if targeted else (0.70, 1.60))
            minimum_characters = math.floor(len(part) * preferred_minimum_ratio)
            maximum_characters = math.ceil(len(part) * maximum_ratio)
            length_contract = (
                f" Return between {minimum_characters} and {maximum_characters} characters. "
                "Do not repeat adjacent scenes, include analysis, or rewrite material outside "
                "this manuscript segment."
            )
            if targeted and (revision_plan or targeted_context):
                prompt = (
                    f"STYLE PROFILE:\n{style_profile}\n\n"
                    f"RELEVANT CHARACTER VOICES:\n"
                    f"{character_fingerprints(project.path, part)}\n\n"
                    + revision_patch_context(
                        issue={
                            "tasks": tasks,
                            "edit_rule": revision_rule + length_contract,
                        },
                        target_paragraph=part,
                        previous_paragraph=previous_context,
                        next_paragraph=next_context,
                        evidence_summaries=linked_checks,
                        seven_step_position=seven_step_position,
                        authoritative_facts=[
                            *authoritative_state.get("locked_facts", []),
                            *authoritative_state.get("confirmed_facts", []),
                            *global_facts,
                        ],
                        protected_passages=[{
                            "id": lock.get("id"),
                            "label": lock.get("label"),
                            "mode": lock.get("mode"),
                            "allow_next_change": bool(lock.get("allow_next_change")),
                        } for lock in passage_locks],
                        allowed_range={
                            "segment": current_targeted_context["segment"],
                            "minimum_characters": minimum_characters,
                            "maximum_characters": maximum_characters,
                        },
                        word_target=len(part),
                    )
                )
            else:
                prompt = (
                    f"STYLE PROFILE:\n{style_profile}\n\n"
                    f"RELEVANT CHARACTER VOICES:\n"
                    f"{character_fingerprints(project.path, part)}\n\n"
                    f"LOCAL PROSE FINDINGS:\n"
                    f"{json.dumps(local_report['findings'], ensure_ascii=False)}\n\n"
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
                    + passage_prompt_context(passage_locks)
                )
            part_suffix = f"{suffix}-part-{index:02d}"
            priority = bool(targeted or index in {1, len(parts)} or local_report["findings"])
            prefer_configured = bool(
                configured_fallback and (primary_circuit_open or not priority)
            )
            route = (
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
            targeted_group_failed = False
            try:
                polished_part = await self._stage(
                    run_id, run_path, project, "polish", constraints, prompt,
                    suffix=part_suffix, allow_tools=False,
                    prefer_configured_fallback=prefer_configured,
                    output_source_characters=len(part),
                    targeted_retry=targeted,
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
            except TargetedGroupError as exc:
                targeted_group_failed = True
                polished_part = part
                self.db.add_run_event(
                    run_id, "warning", "targeted_group_failed",
                    "当前定向修订片段的首选和备用模型均失败，已保留原文并继续其他片段",
                    stage="polish", metadata={
                        "segment": index, "characters": len(part),
                        "error": describe_error(exc),
                    },
                )
            except Exception as exc:
                children = self._split_failed_polish_segment(part)
                if (not self._is_recoverable_polish_error(exc)
                        or recovery_depth >= 2 or children is None):
                    raise
                self.db.add_run_event(
                    run_id, "warning", "polish_segment_split",
                    "模型输出受限，正在拆分当前片段后重试",
                    stage="polish", metadata={
                        "segment": index, "characters": len(part),
                        "child_characters": [len(child) for child in children],
                        "split_depth": recovery_depth + 1, "failed_route": route,
                        "error": describe_error(exc),
                    },
                )
                polished_part = await self._polish_short_segments(
                    run_id, run_path, project, constraints,
                    self.SHORT_SEGMENT_SEPARATOR.join(children), plan_context,
                    suffix=f"{part_suffix}-split-{recovery_depth + 1}",
                    structural=False, recovery_depth=recovery_depth + 1,
                    recovery_rule=revision_rule,
                    targeted_context=current_targeted_context if targeted else None,
                )
                polished_part = polished_part.replace(self.SHORT_SEGMENT_SEPARATOR, "\n\n")
            round_input_tokens += int(
                getattr(polished_part, "receipt", {}).get("input_tokens", 0) or 0
            )
            voice = character_fingerprints(project.path, part)
            required = re.findall(r"(?m)^##\s+(.+)$", voice)
            assessment = assess_polish_candidate(
                part, polished_part, required,
                minimum_ratio=minimum_ratio, maximum_ratio=maximum_ratio,
            )
            if targeted_group_failed:
                assessment["accepted"] = False
                assessment["reasons"].append("targeted_model_routes_failed")
            rhythm_reasons = {
                "sentence_rhythm_not_improved",
                "timestamp_scene_fragment_not_improved",
                "dialogue_ping_pong_not_improved",
            }
            if targeted:
                assessment["reasons"] = [
                    reason for reason in assessment["reasons"]
                    if reason not in rhythm_reasons
                ]
                assessment["accepted"] = not assessment["reasons"]
            locked_failures = validate_locked_facts(part, polished_part, authoritative_state)
            if locked_failures:
                assessment["accepted"] = False
                assessment["reasons"].extend(locked_failures)
            passage_validation = validate_passage_protections(
                part, polished_part, passage_locks,
            )
            if passage_validation["conflicts"]:
                assessment["accepted"] = False
                assessment["reasons"].extend(
                    f"passage_protection:{item['id']}"
                    for item in passage_validation["conflicts"]
                )
            if (not targeted_group_failed and not assessment["accepted"] and configured_fallback
                    and not prefer_configured):
                self.db.add_run_event(
                    run_id, "warning", "polish_validation_fallback",
                    f"润色第 {index}/{len(parts)} 段未通过本地验收，正在改用备用模型重试",
                    stage="polish", metadata={
                        "segment": index, "reasons": assessment["reasons"],
                    },
                )
                try:
                    polished_part = await self._stage(
                        run_id, run_path, project, "polish", constraints, prompt,
                        suffix=f"{part_suffix}-validation-fallback", allow_tools=False,
                        prefer_configured_fallback=True,
                        output_source_characters=len(part),
                        targeted_retry=targeted,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.db.add_run_event(
                        run_id, "warning", "polish_validation_fallback_failed",
                        f"润色第 {index}/{len(parts)} 段的备用模型重试失败，已保留原文",
                        stage="polish", metadata={
                            "segment": index, "error": describe_error(exc),
                        },
                    )
                else:
                    round_input_tokens += int(
                        getattr(polished_part, "receipt", {}).get("input_tokens", 0) or 0
                    )
                    assessment = assess_polish_candidate(
                        part, polished_part, required,
                        minimum_ratio=minimum_ratio, maximum_ratio=maximum_ratio,
                    )
                    if targeted:
                        assessment["reasons"] = [
                            reason for reason in assessment["reasons"]
                            if reason not in rhythm_reasons
                        ]
                        assessment["accepted"] = not assessment["reasons"]
                    locked_failures = validate_locked_facts(
                        part, polished_part, authoritative_state,
                    )
                    if locked_failures:
                        assessment["accepted"] = False
                        assessment["reasons"].extend(locked_failures)
                    passage_validation = validate_passage_protections(
                        part, polished_part, passage_locks,
                    )
                    if passage_validation["conflicts"]:
                        assessment["accepted"] = False
                        assessment["reasons"].extend(
                            f"passage_protection:{item['id']}"
                            for item in passage_validation["conflicts"]
                        )
            rhythm_retried = False
            if not targeted and rhythm_reasons.intersection(assessment["reasons"]):
                rhythm_retried = True
                reason = next(item for item in (
                    "sentence_rhythm_not_improved",
                    "dialogue_ping_pong_not_improved",
                    "timestamp_scene_fragment_not_improved",
                ) if item in assessment["reasons"])
                labels = {
                    "sentence_rhythm_not_improved": "连续叙述短句未改善",
                    "dialogue_ping_pong_not_improved": "连续纯对白未改善",
                    "timestamp_scene_fragment_not_improved": "场景断句未改善",
                }
                self.db.add_run_event(
                    run_id, "warning", "polish_rhythm_retry",
                    f"润色第 {index}/{len(parts)} 段{labels[reason]}，正在定向重试",
                    stage="polish", metadata={"segment": index, "reason": reason},
                )
                rhythm_prompt = prompt + (
                    "\n\nRHYTHM RETRY: The previous revision retained four or more consecutive "
                    "short narrative sentences outside dialogue, or split one continuous beat into a timestamp "
                    "sentence followed by a static scene sentence. Merge that beat into natural "
                    "continuous prose. Also break up four or more consecutive dialogue-only "
                    "paragraphs with meaningful action, observation, hesitation, or changed subtext. "
                    "Keep dialogue and plot facts unchanged. Return only the revised segment."
                )
                polished_part = await self._stage(
                    run_id, run_path, project, "polish", constraints, rhythm_prompt,
                    suffix=f"{part_suffix}-rhythm-retry", allow_tools=False,
                    prefer_configured_fallback=prefer_configured,
                    output_source_characters=len(part),
                )
                round_input_tokens += int(
                    getattr(polished_part, "receipt", {}).get("input_tokens", 0) or 0
                )
                assessment = assess_polish_candidate(
                    part, polished_part, required,
                    minimum_ratio=minimum_ratio, maximum_ratio=maximum_ratio,
                )
                locked_failures = validate_locked_facts(
                    part, polished_part, authoritative_state,
                )
                if locked_failures:
                    assessment["accepted"] = False
                    assessment["reasons"].extend(locked_failures)
                passage_validation = validate_passage_protections(
                    part, polished_part, passage_locks,
                )
                if passage_validation["conflicts"]:
                    assessment["accepted"] = False
                    assessment["reasons"].extend(
                        f"passage_protection:{item['id']}"
                        for item in passage_validation["conflicts"]
                    )
            accepted = bool(assessment["accepted"])
            conditional_length = bool(
                accepted and targeted and assessment["ratio"] < preferred_minimum_ratio
            )
            if conditional_length and revision_plan:
                local_check_failures = check_source_local_constraints(
                    part, polished_part, revision_plan,
                )
                if local_check_failures:
                    accepted = False
                    conditional_length = False
                    assessment["accepted"] = False
                    assessment["reasons"].extend(local_check_failures)
            if conditional_length:
                self.db.add_run_event(
                    run_id, "warning", "polish_conditional_length",
                    "Compressed structural candidate accepted conditionally for final review",
                    stage="polish", metadata={
                        "segment": index,
                        "ratio": assessment["ratio"],
                        "preferred_minimum_ratio": preferred_minimum_ratio,
                        "hard_minimum_ratio": minimum_ratio,
                        "review_required": True,
                    },
                )
            if not assessment["accepted"]:
                if passage_validation["conflicts"]:
                    self.db.add_run_event(
                        run_id, "warning", "passage_protection_conflict",
                        "模型修改了受保护片段，已保留原文",
                        stage="polish", metadata={
                            "segment": index,
                            "protection_ids": [
                                item["id"] for item in passage_validation["conflicts"]
                            ],
                            "labels": [
                                item["label"] for item in passage_validation["conflicts"]
                            ],
                        },
                    )
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
            elif passage_validation["consumed"]:
                passage_service.consume_allowed_changes(
                    project.id, passage_validation["consumed"],
                )
            polished_part = polished_part.strip()
            polished_parts.append(polished_part)
            change_evidence = diff_manuscripts(
                part, polished_part,
                analyze_manuscript(part, nlp_analyze=None),
                analyze_manuscript(polished_part, nlp_analyze=None),
            )
            if accepted:
                self._save_polish_checkpoint(
                    checkpoint_root, index, part, polished_part,
                    change_evidence=change_evidence,
                )
            elif rhythm_retried:
                self._save_polish_checkpoint(
                    checkpoint_root, index, part, part,
                    status="preserved_after_retry", retry_signature=retry_signature,
                    change_evidence=change_evidence,
                )
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
            deferred_tasks = revision_plan.get("deferred_tasks", [])
            if deferred_tasks:
                remaining_plan = {
                    "global_facts": revision_plan["global_facts"],
                    "checks": revision_plan["checks"],
                    "tasks": deferred_tasks,
                }
                next_plan = self._normalized_revision_plan(
                    remaining_plan, len(original_parts), max_target_ratio=0.4,
                    require_checks=bool(remaining_plan["checks"]),
                    defer_excess_targets=True,
                )
                self.db.add_run_event(
                    run_id, "info", "revision_batch_continued",
                    "当前批次已完成，正在继续处理同一返修计划的下一批场景",
                    stage="polish", metadata={
                        "completed_segments": revision_plan["target_segments"],
                        "next_segments": next_plan["target_segments"],
                        "remaining_segments": next_plan["deferred_segments"],
                    },
                )
                polished = await self._polish_short_segments(
                    run_id, run_path, project, constraints, polished, findings,
                    suffix=f"{suffix}-batch-{batch_number + 1}", structural=True,
                    prepared_revision_plan=remaining_plan,
                    round_cap_override=max(0, round_cap - round_input_tokens),
                    batch_number=batch_number + 1,
                )
                final_failures = check_revision_constraints(polished, revision_plan)
                atomic_write(
                    run_path / "outputs" / f"revision-checks{suffix}.json",
                    json.dumps({"failures": final_failures}, ensure_ascii=False, indent=2),
                )
        atomic_write(run_path / "outputs" / f"polish{suffix}.md", polished)
        return polished

    @staticmethod
    def _is_recoverable_polish_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(marker in message for marker in (
            "502", "504", "524", "timeout", "timed out", "connecterror",
            "connection reset", "connection refused", "connection attempts failed",
            "server disconnected", "bad gateway", "gateway timeout",
            "finish_reason=max_tokens",
        ))

    @classmethod
    def _polish_round_input_cap(cls, structural: bool, segment_count: int) -> int:
        if structural:
            return cls.STRUCTURAL_POLISH_INPUT_CAP
        return max(cls.INITIAL_POLISH_INPUT_CAP, segment_count * 20_000)

    @staticmethod
    def _split_failed_polish_segment(text: str, minimum: int = 400) -> tuple[str, str] | None:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
        if len(paragraphs) < 2 or len(text) < minimum * 2:
            return None
        midpoint = len(text) / 2
        split_at = min(range(1, len(paragraphs)), key=lambda index: abs(
            len("\n\n".join(paragraphs[:index])) - midpoint
        ))
        left = "\n\n".join(paragraphs[:split_at])
        right = "\n\n".join(paragraphs[split_at:])
        return (left, right) if min(len(left), len(right)) >= minimum else None

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
            "change. Order tasks by urgency and never target unrelated scenes. The Runtime will "
            "apply at most 40% of scenes in the current batch and defer the rest. "
            "Return one JSON object only with: global_facts (string array), checks (array of objects "
            "using kind required_text or forbidden_text, value, and issue_ids), and tasks (array with "
            "segments as integer array, instruction as text, issue_ids as the exact related review "
            "issue IDs, and optional seven_step_position only when the review evidence names it). "
            "Include at least one literal deterministic check "
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
                    targeted_retry=True,
                )
                try:
                    payload = self._json_object(output)
                except json.JSONDecodeError:
                    repair = schema_repair_prompt(output, "repair_revision_plan_v1")
                    output = await self._stage(
                        run_id, run_path, project, "revision_plan", constraints, repair,
                        suffix=f"{suffix}-revision-plan-repair", model_role="planning",
                        allow_tools=False, targeted_retry=True,
                    )
                    payload = self._json_object(output)
                plan = self._normalized_revision_plan(
                    payload, len(story_map), max_target_ratio=0.4,
                    require_checks=require_checks, defer_excess_targets=True,
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
                    allow_tools=False, targeted_retry=True,
                )
                plan = self._normalized_revision_plan(
                    self._json_object(output), len(story_map),
                    max_target_ratio=0.4, require_checks=require_checks,
                    defer_excess_targets=True,
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
            if plan.get("deferred_segments"):
                self.db.add_run_event(
                    run_id, "info", "revision_plan_deferred",
                    "返修范围较大，已分批处理；其余场景将在下一轮复核后继续",
                    stage="revision_plan", metadata={
                        "current_segments": plan["target_segments"],
                        "deferred_segments": plan["deferred_segments"],
                    },
                )
            self.db.add_run_event(
                run_id, severity, event_type, "Structural revision plan created",
                stage="revision_plan", metadata={
                    "target_segments": plan["target_segments"],
                    "deferred_segments": plan.get("deferred_segments", []),
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
    def _previous_quality_best(run_path: Path) -> dict | None:
        checkpoint = reconcile_legacy_checkpoint(run_path)
        if checkpoint is None:
            return None
        return {**checkpoint, "text": checkpoint_manuscript(run_path, checkpoint)}

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
                     output_source_characters: int | None = None,
                     targeted_retry: bool = False) -> str:
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
            source_constraints = constraints
            if stage == "polish":
                project_constraints = (project.path / "constraints.md").read_text(encoding="utf-8")
                if project_constraints not in source_constraints:
                    source_constraints += (
                        "\n\nPROJECT-SPECIFIC CONSTRAINTS:\n" + project_constraints
                    )
            model_constraints = source_constraints
            if compact_context:
                model_constraints = self.constraint_prompts.compact(source_constraints)
            self.db.add_run_event(
                run_id, "success", "skills_loaded", f"已加载 {len(skills)} 个 Skill",
                stage=stage, metadata={
                    "skills": skills,
                    "prompt_characters": len(model_skill_prompt),
                    "source_prompt_characters": len(skill_run.prompt),
                    "compact_prompt": model_skill_prompt != skill_run.prompt,
                    "constraint_characters": len(model_constraints),
                    "source_constraint_characters": len(source_constraints),
                    "compact_constraints": model_constraints != source_constraints,
                },
            )
            style = (
                f"\n\nPROJECT STYLE PROFILE:\n{ensure_style_profile(project)}"
                if stage == "draft"
                and project.metadata.get("style_sample_scope") == "draft_and_polish"
                else ""
            )
            system = f"{STAGE_SYSTEM[stage]}\n\nHARD CONSTRAINTS:\n{model_constraints}\n\n{model_skill_prompt}{style}"
            estimated_input_tokens = estimate_input_tokens(system + "\n" + user)
            if stage == "polish" and estimated_input_tokens > 12_000:
                model_constraints = ConstraintPromptCompactor(max_chars=4000).compact(
                    source_constraints
                )
                model_skill_prompt = SkillPromptCompactor(max_chars=5000).compact(
                    skill_run.prompt, skill_run.receipts,
                )
                system = (
                    f"{STAGE_SYSTEM[stage]}\n\nHARD CONSTRAINTS:\n{model_constraints}"
                    f"\n\n{model_skill_prompt}{style}"
                )
                estimated_input_tokens = estimate_input_tokens(system + "\n" + user)
            if stage == "polish":
                self.db.add_run_event(
                    run_id, "info", "polish_input_sized",
                    "Polish request context sized before provider call",
                    stage=stage, metadata={
                        "estimated_input_tokens": estimated_input_tokens,
                        "user_characters": len(user), "system_characters": len(system),
                    },
                )
            gateway_role = model_role or stage
            provider_ceiling = self._provider_output_ceiling(
                gateway_role, prefer_configured_fallback,
            )
            output_budget = self._output_budget_for_call(
                stage, output_source_characters, gateway_role, prefer_configured_fallback,
            )
            fallback_ceiling = self._provider_output_ceiling(gateway_role, True)
            stage_budget = self._stage_output_budget(stage, output_source_characters)
            effective_ceiling = provider_ceiling or output_budget
            fallback_effective_ceiling = fallback_ceiling or stage_budget
            fallback_budget = (
                min(stage_budget, fallback_effective_ceiling)
                if stage_budget is not None and fallback_effective_ceiling is not None
                else stage_budget
            )
            if targeted_retry and output_source_characters is not None:
                output_budget = patch_output_budget(
                    output_source_characters, effective_ceiling or 1,
                )
                fallback_budget = patch_output_budget(
                    output_source_characters, fallback_effective_ceiling or 1,
                )
            try:
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
                elif isinstance(self.gateway, ModelGateway):
                    result = await self.gateway.complete(
                        gateway_role, system, user,
                        max_output_tokens=output_budget,
                        fallback_max_output_tokens=fallback_budget,
                    )
                else:
                    result = await self.gateway.complete(
                        gateway_role, system, user,
                        max_output_tokens=output_budget,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not targeted_retry:
                    raise
                attempt = 2 if isinstance(exc, ModelRoutesExhaustedError) else 1
                decision = next_retry_action(
                    failure_kind="execution", attempt=attempt,
                    current_limit=output_budget or 1,
                    provider_limit=effective_ceiling or output_budget or 1,
                )
                if (decision["action"] == "fallback"
                        and not prefer_configured_fallback
                        and hasattr(self.gateway, "complete_configured_fallback")):
                    try:
                        result = await self.gateway.complete_configured_fallback(
                            gateway_role, system, user,
                            max_output_tokens=fallback_budget,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as fallback_exc:
                        stop = next_retry_action(
                            failure_kind="execution", attempt=2,
                            current_limit=fallback_budget or 1,
                            provider_limit=fallback_effective_ceiling or fallback_budget or 1,
                        )
                        assert stop["action"] == "stop"
                        raise TargetedGroupError(str(fallback_exc)) from fallback_exc
                else:
                    raise TargetedGroupError(str(exc)) from exc
            if (stage == "review" and gateway_role == "review" and not allow_tools
                    and not result.text.strip()
                    and result.receipt.get("finish_reason") == "max_tokens"):
                used_fallback = bool(
                    prefer_configured_fallback
                    or result.receipt.get("fallback_used")
                    or result.receipt.get("configured_fallback_direct")
                )
                review_retry_ceiling = (
                    fallback_ceiling if used_fallback else provider_ceiling
                )
                review_retry_budget = min(8192, review_retry_ceiling or 8192)
                self.db.add_run_event(
                    run_id, "warning", "review_max_tokens_retry",
                    "Review output hit its token limit; retrying the same route with full budget",
                    stage=stage, metadata={
                        "previous_budget": output_budget,
                        "retry_budget": review_retry_budget,
                        "model_name": result.receipt.get("model_name"),
                    },
                )
                retry_system = system + (
                    "\n\nDo not expose reasoning. Return only the compact review JSON. "
                    "Keep at most five highest-severity issues per category."
                )
                if used_fallback and hasattr(self.gateway, "complete_configured_fallback"):
                    result = await self.gateway.complete_configured_fallback(
                        gateway_role, retry_system, user,
                        max_output_tokens=review_retry_budget,
                    )
                else:
                    result = await self.gateway.complete(
                        gateway_role, retry_system, user,
                        max_output_tokens=review_retry_budget,
                    )
                used_fallback = bool(
                    used_fallback
                    or result.receipt.get("fallback_used")
                    or result.receipt.get("configured_fallback_direct")
                )
                if (not result.text.strip() and not used_fallback
                        and hasattr(self.gateway, "complete_configured_fallback")):
                    self.db.add_run_event(
                        run_id, "warning", "review_configured_fallback",
                        "Review retry remained empty; using the review role configured fallback",
                        stage=stage,
                    )
                    result = await self.gateway.complete_configured_fallback(
                        gateway_role, retry_system, user,
                        max_output_tokens=min(8192, fallback_ceiling or 8192),
                    )
            if (stage == "polish" and gateway_role == "polish" and not allow_tools
                    and not result.text.strip()
                    and result.receipt.get("finish_reason") == "max_tokens"):
                used_fallback = bool(
                    prefer_configured_fallback
                    or result.receipt.get("fallback_used")
                    or result.receipt.get("configured_fallback_direct")
                )
                previous_budget = fallback_budget if used_fallback else output_budget
                if targeted_retry:
                    retry_ceiling = (
                        fallback_effective_ceiling if used_fallback else effective_ceiling
                    ) or previous_budget
                else:
                    configured_retry_ceiling = (
                        fallback_ceiling if used_fallback else provider_ceiling
                    )
                    retry_ceiling = configured_retry_ceiling or 8192
                decision = next_retry_action(
                    failure_kind="output_limit", attempt=1,
                    current_limit=previous_budget or 1,
                    provider_limit=retry_ceiling or 1,
                )
                retry_budget = (
                    decision["next_limit"] if targeted_retry
                    else min(8192, retry_ceiling or 8192)
                )
                if not targeted_retry or decision["action"] == "retry_larger":
                    self.db.add_run_event(
                        run_id, "warning", "polish_max_tokens_retry",
                        "当前片段输出不完整，正在提高输出上限后重试",
                        stage=stage, metadata={
                            "previous_budget": previous_budget,
                            "retry_budget": retry_budget,
                        },
                    )
                    if used_fallback and hasattr(
                        self.gateway, "complete_configured_fallback"
                    ):
                        result = await self.gateway.complete_configured_fallback(
                            gateway_role, system, user, max_output_tokens=retry_budget,
                        )
                    else:
                        result = await self.gateway.complete(
                            gateway_role, system, user, max_output_tokens=retry_budget,
                        )
            if (stage == "polish" and gateway_role == "polish" and not allow_tools
                    and not result.text.strip()
                    and result.receipt.get("finish_reason") in {"tool_use", "tool_calls"}):
                self.db.add_run_event(
                    run_id, "warning", "polish_tool_use_retry",
                    "Polish returned a tool call without prose; retrying once without tools",
                    stage=stage,
                )
                retry_system = system + (
                    "\n\nNo tools are available for this request. Return only the polished prose."
                )
                if prefer_configured_fallback and hasattr(
                    self.gateway, "complete_configured_fallback"
                ):
                    result = await self.gateway.complete_configured_fallback(
                        gateway_role, retry_system, user,
                        max_output_tokens=output_budget,
                    )
                else:
                    result = await self.gateway.complete(
                        gateway_role, retry_system, user,
                        max_output_tokens=output_budget,
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
            if stage == "review":
                self.db.add_run_event(
                    run_id, "error", "review_incomplete",
                    "Review primary and configured fallback did not produce usable output",
                    stage=stage, metadata={"error": str(exc)},
                )
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
    def _load_polish_checkpoint(root: Path, index: int, source: str,
                                retry_signature: str | None = None) -> str | None:
        path = root / f"part-{index:02d}.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        polished = value.get("polished")
        if (value.get("status") == "preserved_after_retry"
                and value.get("retry_signature") != retry_signature):
            return None
        return polished if value.get("source_sha256") == digest and isinstance(polished, str) else None

    @classmethod
    def _polish_checkpoint_progress(cls, root: Path, parts: list[str],
                                    retry_signature: str | None = None) -> tuple[int, int]:
        valid = [cls._load_polish_checkpoint(root, index, part, retry_signature) is not None
                 for index, part in enumerate(parts, 1)]
        return sum(valid), next((index for index, done in enumerate(valid, 1) if not done), len(parts))

    @staticmethod
    def _polish_retry_signature(binding: dict) -> str:
        return hashlib.sha256(json.dumps({
            "policy": "rhythm-v2",
            "primary_provider_id": binding.get("primary_provider_id"),
            "primary_model_id": binding.get("primary_model_id"),
            "fallback_provider_id": binding.get("fallback_provider_id"),
            "fallback_model_id": binding.get("fallback_model_id"),
        }, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _save_polish_checkpoint(root: Path, index: int, source: str, polished: str,
                                status: str = "accepted",
                                retry_signature: str | None = None,
                                change_evidence: dict | None = None) -> None:
        atomic_write(root / f"part-{index:02d}.json", json.dumps({
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "polished": polished,
            "status": status,
            "retry_signature": retry_signature,
            "change_evidence": change_evidence or {"ranges": [], "changed_ratio": 0.0},
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
        configure_runtime_environment(self.db.path.parent, self.crewai_data_dir)
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
    def _normalized_revision_plan(value: dict, segment_count: int, **kwargs) -> dict:
        def normalized_issue_ids(raw) -> list[str]:
            values = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
            return sorted({item.strip() for item in values
                           if isinstance(item, str) and item.strip()})

        plan = normalize_revision_plan(value, segment_count, **kwargs)
        raw_checks = value.get("checks") if isinstance(value.get("checks"), list) else []
        for check in plan["checks"]:
            raw = next((item for item in raw_checks if isinstance(item, dict)
                        and item.get("kind") == check["kind"]
                        and str(item.get("value", "")).strip() == check["value"]), None)
            issue_ids = normalized_issue_ids((raw or {}).get("issue_ids"))
            if issue_ids:
                check["issue_ids"] = issue_ids
        raw_tasks = value.get("tasks") if isinstance(value.get("tasks"), list) else []
        for task_list in (plan["tasks"], plan.get("deferred_tasks", [])):
            for task in task_list:
                raw = next((item for item in raw_tasks if isinstance(item, dict)
                            and str(item.get("instruction", "")).strip()
                            == task["instruction"]), None)
                position = (raw or {}).get("seven_step_position")
                if isinstance(position, str) and position.strip():
                    task["seven_step_position"] = position.strip()
                issue_ids = normalized_issue_ids((raw or {}).get("issue_ids"))
                if issue_ids:
                    task["issue_ids"] = issue_ids
                else:
                    task.pop("issue_ids", None)
        return plan

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

    @classmethod
    def _review_for_project(
        cls, value: str | dict, project: Project, receipt: dict | None = None,
    ) -> dict:
        payload = cls._json_object(value) if isinstance(value, str) else value
        profile_id = profile_for_project(project)
        criteria = payload.get("criteria") if isinstance(payload.get("criteria"), dict) else {}
        if (profile_id == ZHihu_SHORT_V2.id
                and all(name in criteria for name in ZHihu_SHORT_V2.criterion_dimensions)):
            payload = {
                **payload,
                "dimensions": {name: 0 for name in ZHihu_SHORT_V2.dimension_weights},
            }
        review = score_review(
            normalize_review(payload), profile_id,
        )
        review["judge_signature"] = judge_signature(receipt)
        return review

    @staticmethod
    def _stage_output_budget(stage: str, source_characters: int | None = None) -> int | None:
        return stage_output_budget(stage, source_characters)

    def _output_budget_for_call(self, stage: str, source_characters: int | None,
                                gateway_role: str, prefer_configured_fallback: bool) -> int | None:
        default = self._stage_output_budget(stage, source_characters)
        ceiling = self._provider_output_ceiling(
            gateway_role, prefer_configured_fallback,
        )
        if default is None or ceiling is None:
            return default
        return min(default, ceiling)

    def _provider_output_ceiling(self, gateway_role: str,
                                 prefer_configured_fallback: bool) -> int | None:
        binding = self.db.get_role_binding(gateway_role) or {}
        model_key = (
            "fallback_model_id" if prefer_configured_fallback else "primary_model_id"
        )
        model = self.db.get_model(binding.get(model_key, "")) or {}
        ceiling = model.get("max_output_tokens")
        return ceiling if isinstance(ceiling, int) and ceiling > 0 else None

    @staticmethod
    def _chapter_file(project: Project, text: str, number: int = 1) -> str:
        return (
            f"---\ntitle: {project.title}\nnumber: {number}\npov: {project.metadata['pov']}\n"
            "locations: []\ncharacters: []\narcs-advanced: []\nstatus: final\nword-count: 0\n---\n\n"
            f"# Chapter {number}: {project.title}\n\n## Chapter Text\n\n{text}\n"
        )
