import asyncio
import hashlib
import json
import math
import os
import re
import threading
import unicodedata
import uuid
from contextlib import contextmanager, nullcontext
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterator

from novel_flywheel.db import Database
from novel_flywheel.draft_split import (
    DraftTaskContract,
    exact_event_partition,
    render_draft_task_prompt,
    residual_target,
    semantic_receipt_issues,
    target_bounds,
    validate_semantic_receipt,
    validate_whole_draft_receipt,
)
from novel_flywheel.execution_manifest import (
    ShortExecutionManifest,
    bind_previous_exit_hashes,
    execution_manifest_issues,
    execution_manifest_receipt_binding_issues,
    execution_manifest_sha256,
    legacy_execution_index_requires_rebuild,
    parse_execution_manifest,
    validate_execution_manifest_receipt,
)
from novel_flywheel.causal_chain import (
    END as SHORT_CAUSAL_CHAIN_END,
    START as SHORT_CAUSAL_CHAIN_START,
    analyze_short_causal_chain,
    compact_causal_chain,
    extract_short_causal_chain,
)
from novel_flywheel.context_policy import (
    adaptive_output_budget,
    authority_packet_sha256,
    build_polish_authority_packet,
    classify_input_pressure,
    classify_model_failure,
    estimate_input_tokens,
    expanded_output_budget,
    invalid_terminal_output,
    next_retry_action,
    normalize_finish_reason,
    output_limited,
    patch_output_budget,
    revision_patch_context,
    render_polish_authority_packet,
    schema_repair_prompt,
    stage_output_budget,
)
from novel_flywheel.context_packet import (
    build_stage_context_packet,
    context_packet_sha256,
    render_stage_system_context,
    validate_rule_coverage,
)
from novel_flywheel.config import configure_runtime_environment
from novel_flywheel.errors import describe_error
from novel_flywheel.models import ModelGateway, ModelRoutesExhaustedError
from novel_flywheel.model_output import parse_json_object
from novel_flywheel.outlines import (
    canon_profile,
    detect_canon_conflicts,
    narrative_outline_events,
    outline_events,
)
from novel_flywheel.memory import StoryMemory
from novel_flywheel.manuscript_analysis import analysis_matches, analyze_manuscript, compact_analysis
from novel_flywheel.narrative_ledger import build_narrative_ledger
from novel_flywheel.incremental_review import (
    apply_incremental_gate,
    build_review_baseline,
    diff_manuscripts,
    incremental_precheck_reasons,
    requires_full_review,
    select_review_scope,
)
from novel_flywheel.projects import Project, ProjectStore
from novel_flywheel.prompts import (
    EXPANSION_CONTRACT,
    OPTIONAL_PROMPT_SKILLS,
    REQUIRED_SKILLS,
    STAGE_SYSTEM,
)
from novel_flywheel.quality import (
    apply_evidence_gate,
    issue_ledger,
    normalize_review,
    quality_gate,
    quality_outcome,
    reader_sample,
    reconcile_review_issues,
    review_evidence_batches,
    review_windows,
    select_route,
)
from novel_flywheel.quality_records import (
    QUALITY_CHECKPOINT_LOCK,
    checkpoint_manuscript,
    load_quality_checkpoint,
    reconcile_legacy_checkpoint,
    write_quality_checkpoint,
)
from novel_flywheel.quality_summary import effective_han_characters
from novel_flywheel.repair_gate import evaluate_candidate_gate
from novel_flywheel.repair_records import RepairRunStore, repair_artifact_hash
from novel_flywheel.revision_operations import (
    RevisionOperationError,
    RevisionOperations,
)
from novel_flywheel.scene_continuity import (
    LocationRef,
    assess_scene_transition,
    build_location_catalog,
)
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
    filter_polish_findings_for_segment,
    normalize_repair_contract,
    normalize_chinese_prose,
    normalize_revision_plan,
    parse_segment_number,
    repair_mechanical_text,
    remove_consecutive_duplicate_blocks,
    segment_map,
)
from novel_flywheel.prose_quality import analyze_prose, compare_voice_metrics, prose_metrics
from novel_flywheel.prose_policy import load_prose_validation_policy
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


class FinalReviewJSONError(ValueError):
    """Raised when all safe final-review JSON routes remain incomplete."""

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail or {}


class RevisionPlanError(RuntimeError):
    pass


class TargetedGroupError(RuntimeError):
    pass


class ExpansionRejectedError(ValueError):
    def __init__(self, code: str, category: str, message: str):
        super().__init__(message)
        self.code = code
        self.category = category


class PolishTokenBudgetError(RuntimeError):
    pass


class IncompleteModelOutputError(RuntimeError):
    """The transport finished, but the artifact did not prove completeness."""

    def __init__(self, stage: str, partial: StageText):
        super().__init__(f"{stage} output remained incomplete after output-limit recovery")
        self.stage = stage
        self.partial = partial
        self.receipt = partial.receipt


class DraftSemanticValidationError(ValueError):
    def __init__(self, task_id: str, issues: str | list[dict]):
        normalized = (
            issues if isinstance(issues, list)
            else [{"code": "semantic_contract_failed", "message": str(issues)}]
        )
        detail = "；".join(
            str(item.get("message") or item.get("code")) for item in normalized
        )
        super().__init__(f"正文语义完整性检查未通过（{task_id}）：{detail}")
        self.task_id = task_id
        self.issues = normalized


# ponytail: one local console process needs serialization, not a lock registry.
_SHORT_REVISION_LOCK = threading.Lock()


class WorkflowService:
    SHORT_SEGMENT_SEPARATOR = "\n\n<!-- NOVEL_FLYWHEEL_SEGMENT -->\n\n"
    SHORT_CHECKPOINT_VERSION = 3
    SHORT_PLAN_FIELD_ALIASES = {
        "event_id": ("事件ID", "正式事件ID"),
        "outline": ("大纲依据", "正式大纲依据"),
        "opening": ("段首承接", "开场承接"),
        "event": ("本段事件", "核心事件", "负责事件"),
        "handoff": ("段末交接", "交接状态", "段末状态"),
    }
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

    def _short_revision_lock(self, run_id: str) -> threading.Lock:
        return _SHORT_REVISION_LOCK

    def _restore_snapshot_after_failure(
        self, run_id: str, snapshot: ProjectSnapshot,
    ) -> None:
        try:
            snapshot.restore()
        except Exception as recovery_error:
            self.db.add_run_event(
                run_id, "warning", "snapshot_restore_failed",
                "项目文件恢复未完全完成，系统已保留最初的失败原因",
                stage="archive", metadata={
                    "recovery_error": str(recovery_error)[:500],
                },
            )

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

    def decide_short_revision_group(
        self, run_id: str, group_id: str, decision: str,
        candidate_hash: str,
    ) -> dict:
        with self._short_revision_lock(run_id):
            return self._decide_short_revision_group(
                run_id, group_id, decision, candidate_hash,
            )

    def _decide_short_revision_group(
        self, run_id: str, group_id: str, decision: str,
        candidate_hash: str,
    ) -> dict:
        if decision not in {"adopted", "rejected"}:
            raise ValueError("Unsupported revision decision")
        operations = RevisionOperations(self.db, self.projects, self)
        authority = operations.load_state(run_id)
        run = authority["run"]
        if run.get("status") not in {
            "waiting_confirmation", "waiting_local_fix",
        }:
            raise RevisionOperationError(
                409, "revision_run_invalid",
                "当前返修任务不在可确认修改的阶段。",
            )
        state = authority["state"]
        if candidate_hash != state.get("candidate_hash"):
            raise RevisionOperationError(
                409, "revision_candidate_changed",
                "返修候选稿已经变化，请刷新后重试。",
            )
        records_value = state["groups"].get("groups")
        if not isinstance(records_value, list):
            raise RevisionOperationError(
                409, "revision_run_invalid",
                "返修记录不完整或已经损坏，请重新开始本次返修。",
            )
        record = next(
            (
                item for item in records_value
                if isinstance(item, dict) and item.get("group_id") == group_id
            ),
            None,
        )
        if record is None:
            raise RevisionOperationError(
                404, "revision_group_not_found", "没有找到这个修改组。",
            )
        automatic_decision = (
            "adopted"
            if (
                record.get("kind") == "mechanical"
                and record.get("status") == "ready_for_confirmation"
                and record.get("patch_result", {}).get("accepted") is True
            )
            else None
        )
        existing = record.get("decision") or automatic_decision
        if existing is not None:
            if existing == decision:
                return self._short_revision_public_group(
                    operations.read(run_id), group_id,
                )
            raise RevisionOperationError(
                409, "revision_group_already_decided",
                "这个修改组已经作出相反决定，不能重复更改。",
            )
        if (
            record.get("kind") not in {"semantic", "expansion"}
            or record.get("status") != "ready_for_confirmation"
            or record.get("patch_result", {}).get("accepted") is not True
        ):
            raise RevisionOperationError(
                409, "revision_group_not_ready",
                "这个修改组尚未通过本地检查，不能确认。",
            )
        record["decision"] = decision
        record["decision_candidate_hash"] = candidate_hash
        if decision == "rejected":
            record["issue_status"] = "unresolved"

        contract = state["contract"]
        completed = set(state.get("completed_groups", []))
        report = state.get("report")
        gate = report.get("gate") if isinstance(report, dict) else None
        store = authority["store"]
        files = [
            store.output / name
            for name in (
                store.GROUPS, store.CANDIDATE, store.CHECKPOINT, store.REPORT,
            )
        ]
        snapshot = ProjectSnapshot.create(
            authority["project"].path,
            (
                authority["project"].path
                / "snapshots"
                / f"revision-decision-{uuid.uuid4().hex[:12]}"
            ),
            files,
        )
        try:
            self._save_short_revision_state(
                store, contract, run_id, records_value, state["candidate"],
                completed, gate, str(run["status"]),
            )
        except Exception:
            snapshot.restore()
            raise
        return self._short_revision_public_group(
            operations.read(run_id), group_id,
        )

    @staticmethod
    def _short_revision_public_group(summary: dict, group_id: str) -> dict:
        for group in summary["groups"]:
            if group.get("group_id") == group_id:
                return group
        raise RevisionOperationError(
            404, "revision_group_not_found", "没有找到这个修改组。",
        )

    async def finalize_short_revision(self, run_id: str) -> dict:
        try:
            return await self._finalize_short_revision(run_id)
        except RevisionOperationError:
            raise
        except asyncio.CancelledError:
            self.db.update_run(run_id, "failed", "revision_finalize")
            raise
        except Exception:
            run = self.db.get_run(run_id)
            if run is not None and run.get("status") != "completed":
                self.db.update_run(
                    run_id, "failed", "revision_finalize",
                    error="返修终审未完成，已保留修改决定，可以稍后重试。",
                )
            raise

    async def _finalize_short_revision(self, run_id: str) -> dict:
        operations = RevisionOperations(self.db, self.projects, self)
        run = self.db.get_run(run_id)
        if run is None:
            raise RevisionOperationError(
                404, "run_not_found", "没有找到这次运行。",
            )
        if run.get("workflow") != "short-revision":
            raise RevisionOperationError(
                409, "revision_run_invalid", "该任务不是定向返修任务。",
            )
        if run.get("status") == "completed":
            raise RevisionOperationError(
                409, "revision_already_finalized", "这次返修已经完成终审。",
            )

        project = self.projects.get(str(run["project_id"]))
        run_path = project.path / "runs" / run_id
        if self.recover_short_revision_promotion(run_id):
            return operations.read(run_id)

        authority = operations.load_state(run_id)
        run = authority["run"]
        if run.get("status") not in {
            "waiting_confirmation", "waiting_local_fix", "failed", "interrupted",
        }:
            raise RevisionOperationError(
                409, "revision_run_invalid", "当前返修任务不能进入终审。",
            )
        state = authority["state"]
        contract = state["contract"]
        records = state["groups"].get("groups")
        if not isinstance(records, list):
            raise RevisionOperationError(
                409, "revision_run_invalid",
                "返修记录不完整或已经损坏，请重新开始本次返修。",
            )

        adopted_records: list[dict] = []
        rejected_issue_ids: set[str] = set()
        for record in records:
            if not isinstance(record, dict):
                raise RevisionOperationError(
                    409, "revision_run_invalid",
                    "返修记录不完整或已经损坏，请重新开始本次返修。",
                )
            kind = record.get("kind")
            patch_result = record.get("patch_result")
            ready = (
                record.get("status") == "ready_for_confirmation"
                and isinstance(patch_result, dict)
                and patch_result.get("accepted") is True
                and isinstance(record.get("patch_group"), dict)
            )
            if kind == "mechanical":
                if not ready:
                    raise RevisionOperationError(
                        409, "revision_group_not_ready",
                        "仍有机械修改未通过本地检查，不能开始终审。",
                    )
                adopted_records.append(record)
                continue
            if kind not in {"semantic", "expansion"}:
                raise RevisionOperationError(
                    409, "revision_run_invalid",
                    "返修记录包含不支持的修改组。",
                )
            if not ready:
                raise RevisionOperationError(
                    409, "revision_group_not_ready",
                    "仍有语义修改未通过本地检查，不能开始终审。",
                )
            decision = record.get("decision")
            if decision not in {"adopted", "rejected"}:
                raise RevisionOperationError(
                    409, "revision_decisions_incomplete",
                    "请先确认或拒绝每一个语义修改组。",
                )
            if record.get("decision_candidate_hash") != state.get(
                "candidate_hash"
            ):
                raise RevisionOperationError(
                    409, "revision_candidate_changed",
                    "修改决定对应的候选稿已经变化，请刷新后重试。",
                )
            if decision == "adopted":
                adopted_records.append(record)
            else:
                rejected_issue_ids.update(record.get("issue_ids", []))

        candidate = authority["protected"]["source"]
        adopted_groups = []
        patch_results = []
        for record in adopted_records:
            patch_group = record["patch_group"]
            result = {
                "group_id": record["group_id"],
                **apply_patch_group(
                    candidate, patch_group, self._text_hash(candidate),
                ),
            }
            if result["accepted"] is not True:
                raise RevisionOperationError(
                    409, "revision_group_not_ready",
                    "已确认修改无法按冻结原稿完整重放，请重新开始本次返修。",
                )
            candidate = result["text"]
            adopted_groups.append(patch_group)
            patch_results.append(result)

        if not self.db.claim_run_status(
            run_id,
            {"waiting_confirmation", "waiting_local_fix", "failed", "interrupted"},
            "running",
            "revision_gate",
        ):
            current = self.db.get_run(run_id) or {}
            if current.get("status") == "completed":
                raise RevisionOperationError(
                    409, "revision_already_finalized", "这次返修已经完成终审。",
                )
            raise RevisionOperationError(
                409, "revision_run_invalid", "这次返修正在由另一个请求处理。",
            )

        analysis = self._analyze_manuscript(
            candidate, run_path, project, "repair-final",
        )
        adopted_issue_ids = {
            issue_id
            for record in adopted_records
            for issue_id in record.get("issue_ids", [])
        }
        adopted_issues = [
            item
            for item in contract.get("selected_issues", [])
            if (
                isinstance(item, dict)
                and item.get("issue_id") in adopted_issue_ids
            )
        ]
        gate_contract = {
            "manuscript_hash": contract["manuscript_hash"],
            "required_text": self._repair_literals(
                adopted_issues, "required_text",
            ),
            "forbidden_text": self._repair_literals(
                adopted_issues, "forbidden_text",
            ),
            "groups": adopted_groups,
        }
        minimum_han, maximum_han = self._short_revision_target_range(project)
        gate = evaluate_candidate_gate(
            source=authority["protected"]["source"],
            candidate=candidate,
            source_hash=authority["protected"]["source_hash"],
            analysis=analysis,
            contract=gate_contract,
            patch_results=patch_results,
            story_state=contract["story_state"]["data"],
            passage_locks=contract["passage_locks"],
            minimum_han=minimum_han,
            maximum_han=maximum_han,
        )
        report = (
            dict(state.get("report"))
            if isinstance(state.get("report"), dict) else {}
        )
        if not gate["passed"]:
            report.update({
                "status": "waiting_local_fix",
                "gate": gate,
                "next_action": "请先处理未通过的本地检查，再重新终审。",
            })
            authority["store"].write_report(report)
            self.db.update_run(
                run_id, "waiting_local_fix", "revision_gate",
            )
            raise RevisionOperationError(
                409, "revision_gate_failed",
                "候选稿未通过整篇本地检查，尚未调用终审模型。",
            )

        semantic_authority = contract.get("semantic_authority")
        if isinstance(semantic_authority, dict):
            try:
                revision_integrity = await self._verify_atomic_candidate_semantics(
                    run_id, run_path, project,
                    (project.path / "constraints.md").read_text(encoding="utf-8"),
                    str(semantic_authority.get("source_text") or ""),
                    candidate, semantic_authority,
                    suffix="-revision-final",
                    failure_stage="repair_groups", verify_whole=True,
                )
            except asyncio.CancelledError:
                raise
            except (DraftSemanticValidationError, ValueError) as exc:
                issues = (
                    exc.issues if isinstance(exc, DraftSemanticValidationError)
                    else [{"code": "whole_semantic_gate", "message": str(exc)}]
                )
                report.update({
                    "status": "waiting_local_fix",
                    "gate": gate,
                    "semantic_issues": issues,
                    "next_action": "请重新生成或拒绝破坏原子节拍的修改组，再次终审。",
                })
                authority["store"].write_report(report)
                self.db.update_run(
                    run_id, "waiting_local_fix", "revision_semantic_gate",
                )
                self.db.add_run_event(
                    run_id, "warning", "short_revision_semantic_gate_rejected",
                    "已采用的修改组合并后破坏了原子节拍或整篇因果，未调用终审",
                    stage="revision_semantic_gate", metadata={"issues": issues},
                )
                raise RevisionOperationError(
                    409, "revision_semantic_gate_failed",
                    "候选稿未通过原子节拍和整篇因果复核，尚未调用终审模型。",
                ) from exc
            except Exception as exc:
                report.update({
                    "status": "failed",
                    "gate": gate,
                    "next_action": "语义复核暂时不可用，已保留全部修改决定，可稍后重试。",
                })
                authority["store"].write_report(report)
                self.db.update_run(
                    run_id, "failed", "revision_semantic_gate",
                    error="语义复核暂时不可用，可以稍后重试。",
                )
                self.db.add_run_event(
                    run_id, "error", "short_revision_semantic_review_unavailable",
                    "原子节拍复核暂时不可用，已保留修改决定和安全检查点",
                    stage="revision_semantic_gate", metadata={
                        "failure_class": classify_model_failure(exc),
                    },
                )
                raise RevisionOperationError(
                    502, "revision_semantic_review_unavailable",
                    "原子节拍复核暂时不可用，已保留修改决定，请稍后重试。",
                ) from None
            atomic_write(
                run_path / "outputs" / "revision-integrity.json",
                json.dumps(revision_integrity, ensure_ascii=False, indent=2),
            )
            report["narrative_integrity"] = {
                "path": "outputs/revision-integrity.json",
                "sha256": hashlib.sha256(
                    (run_path / "outputs" / "revision-integrity.json").read_bytes(),
                ).hexdigest(),
            }

        protected = authority["protected"]
        baseline_review = {
            **protected["review"],
            "scoring_profile_id": protected["checkpoint"].get(
                "scoring_profile_id", "legacy-v1",
            ),
            "judge_signature": protected["checkpoint"].get(
                "judge_signature", "legacy-unknown",
            ),
        }
        baseline = build_review_baseline(
            protected["source"],
            contract["analysis"],
            [],
            baseline_review,
        )
        initial_review = {
            **baseline_review,
            "issues": [
                (
                    {**item, "status": "unresolved"}
                    if item.get("issue_id") in rejected_issue_ids else dict(item)
                )
                for item in contract.get("issue_ledger", [])
                if isinstance(item, dict)
            ],
        }
        constraints = (project.path / "constraints.md").read_text(
            encoding="utf-8",
        )
        try:
            review, review_audit = await self._incremental_manuscript_review(
                run_id, run_path, project, constraints,
                candidate, analysis, baseline, initial_review,
                suffix="-revision-final",
                revision_source_hash=protected["source_hash"],
                patch_groups=adopted_groups,
            )
        except asyncio.CancelledError:
            self.db.update_run(run_id, "failed", "final_review")
            raise
        except Exception:
            report.update({
                "status": "failed",
                "gate": gate,
                "next_action": "终审暂时不可用，可以保留现有决定后重试。",
            })
            authority["store"].write_report(report)
            self.db.update_run(
                run_id, "failed", "final_review",
                error="终审暂时不可用，可以稍后重试。",
            )
            self.db.add_run_event(
                run_id, "error", "short_revision_review_unavailable",
                "终审暂时不可用，已保留所有修改决定，可以稍后重试。",
                stage="final_review",
            )
            raise RevisionOperationError(
                502, "revision_review_unavailable",
                "终审暂时不可用，已保留修改决定，请稍后重试。",
            ) from None

        return self._commit_short_revision_promotion(
            operations, run_id, run_path, project, candidate, contract,
            records, gate, state, report, review, review_audit,
            rejected_issue_ids,
        )

    def recover_short_revision_promotion(self, run_id: str) -> bool:
        with QUALITY_CHECKPOINT_LOCK:
            run = self.db.get_run(run_id)
            if run is None or run.get("workflow") != "short-revision":
                return False
            project = self.projects.get(str(run["project_id"]))
            run_path = project.path / "runs" / run_id
            journal_path = (
                project.path / "snapshots" / f"revision-promotion-{run_id}"
            )
            marker = load_quality_checkpoint(run_path)
            promoted = bool(
                marker is not None
                and marker.get("manuscript_path") == "outputs/candidate.md"
                and marker.get("terminal_reviewed_hash")
                == marker.get("manuscript_hash")
            )
            if promoted:
                was_completed = run.get("status") == "completed"
                self.db.update_run(run_id, "completed", "revision_completed")
                if not was_completed:
                    self.db.add_run_event(
                        run_id, "success", "short_revision_completed",
                        "返修候选稿已通过检查并成为新的受保护最佳稿。",
                        stage="revision_completed",
                    )
                ProjectSnapshot(
                    project.path, journal_path, [],
                ).discard()
                return True
            if journal_path.is_dir():
                try:
                    journal = ProjectSnapshot.load(project.path, journal_path)
                except ValueError:
                    ProjectSnapshot(project.path, journal_path, []).discard()
                    return False
                journal.restore()
                journal.discard()
            return False

    def _commit_short_revision_promotion(
        self, operations: RevisionOperations, run_id: str, run_path: Path,
        project: Project, candidate: str, contract: dict, records: list[dict],
        gate: dict, state: dict, report: dict, review: dict,
        review_audit: dict, rejected_issue_ids: set[str],
    ) -> dict:
        with QUALITY_CHECKPOINT_LOCK:
            try:
                authority = operations.load_state(run_id)
            except RevisionOperationError:
                self.db.update_run(run_id, "failed", "revision_authority")
                raise
            current_state = authority["state"]
            if current_state.get("contract_hash") != state.get("contract_hash"):
                self.db.update_run(run_id, "failed", "revision_authority")
                raise RevisionOperationError(
                    409, "revision_source_changed",
                    "终审期间受保护原稿已经变化，请重新开始本次返修。",
                )
            if any(
                current_state.get(key) != state.get(key)
                for key in ("groups_hash", "candidate_hash")
            ):
                self.db.update_run(run_id, "failed", "revision_authority")
                raise RevisionOperationError(
                    409, "revision_candidate_changed",
                    "终审期间返修决定或候选稿已经变化，请刷新后重试。",
                )

            current_protected = authority["protected"]
            current_review = {
                **current_protected["review"],
                "scoring_profile_id": current_protected["checkpoint"].get(
                    "scoring_profile_id", "legacy-v1",
                ),
                "judge_signature": current_protected["checkpoint"].get(
                    "judge_signature", "legacy-unknown",
                ),
            }
            review = self._force_rejected_revision_issues(
                review, contract.get("issue_ledger", []), rejected_issue_ids,
            )
            comparison = compare_quality_candidates(current_review, review)
            review_mode = str(review_audit.get("review_mode") or "full")
            full_review_reasons = list(review_audit.get("fallback_reasons") or [])
            if not comparison["promote"]:
                report.update({
                    "status": "waiting_confirmation",
                    "gate": gate,
                    "review_mode": review_mode,
                    "full_review_reasons": full_review_reasons,
                    "comparison": comparison,
                    "next_action": "候选稿没有超过当前受保护最佳稿，请调整决定后再试。",
                })
                authority["store"].write_report(report)
                self.db.update_run(
                    run_id, "waiting_confirmation", "quality_comparison",
                )
                raise RevisionOperationError(
                    409, "revision_not_improved",
                    "候选稿没有达到替换当前受保护最佳稿的条件。",
                )

            outcome, _reasons = quality_outcome_for_profile(
                review, str(review.get("scoring_profile_id") or "legacy-v1"),
            )
            store = authority["store"]
            repair_checkpoint = {
                key: value for key, value in current_state.items()
                if key not in {"contract", "groups", "candidate", "report"}
            }
            repair_checkpoint.update({
                "status": "completed",
                "candidate_hash": repair_artifact_hash(candidate),
            })
            journal_path = (
                project.path / "snapshots" / f"revision-promotion-{run_id}"
            )
            snapshot = ProjectSnapshot.create(project.path, journal_path, [
                store.output / store.CANDIDATE,
                store.output / store.CHECKPOINT,
                store.output / store.REPORT,
                store.output / "quality-checkpoint.json",
                store.output / "short-execution-index.json",
            ])
            try:
                store.write_candidate(candidate)
                store.write_checkpoint(repair_checkpoint)
                promoted_report = self._write_short_revision_report(
                    store, run_id, records, candidate, gate, "completed", contract,
                )
                promoted_report.update({
                    "review_mode": review_mode,
                    "full_review_reasons": full_review_reasons,
                    "comparison": comparison,
                    "next_action": "返修候选稿已成为新的受保护最佳稿。",
                })
                store.write_report(promoted_report)
                digest = self._text_hash(candidate)
                semantic_authority = contract.get("semantic_authority")
                if isinstance(semantic_authority, dict):
                    atomic_write(
                        store.output / "short-execution-index.json",
                        json.dumps(
                            semantic_authority.get("execution_manifest"),
                            ensure_ascii=False, indent=2,
                        ),
                    )
                write_quality_checkpoint(run_path, {
                    "manuscript_path": "outputs/candidate.md",
                    "manuscript_hash": digest,
                    "score": float(review["score"]),
                    "scoring_profile_id": str(
                        review.get("scoring_profile_id") or "legacy-v1"
                    ),
                    "judge_signature": str(
                        review.get("judge_signature") or "legacy-unknown"
                    ),
                    "best_attempt": 1,
                    "review": review,
                    "issue_ledger": issue_ledger(review.get("issues", [])),
                    "outcome": outcome,
                    "terminal_reviewed_hash": digest,
                    **({
                        "narrative_integrity": report["narrative_integrity"],
                    } if isinstance(report.get("narrative_integrity"), dict) else {}),
                })
            except Exception:
                snapshot.restore()
                snapshot.discard()
                self.db.update_run(
                    run_id, "failed", "revision_promotion",
                    error="返修结果保存失败，可以保留决定后重试。",
                )
                raise
            self.db.update_run(run_id, "completed", "revision_completed")
            self.db.add_run_event(
                run_id, "success", "short_revision_completed",
                "返修候选稿已通过检查并成为新的受保护最佳稿。",
                stage="revision_completed",
            )
            snapshot.discard()
            return operations.read(run_id)

    @staticmethod
    def _force_rejected_revision_issues(
        review: dict, frozen_ledger: list[dict],
        rejected_issue_ids: set[str],
    ) -> dict:
        result = dict(review)
        issues = issue_ledger(result.get("issues", []))
        by_id = {
            item.get("issue_id"): index
            for index, item in enumerate(issues)
            if isinstance(item, dict)
        }
        frozen = {
            item.get("issue_id"): item
            for item in frozen_ledger
            if isinstance(item, dict)
        }
        for issue_id in rejected_issue_ids:
            if issue_id in by_id:
                index = by_id[issue_id]
                issues[index] = {**issues[index], "status": "unresolved"}
            elif issue_id in frozen:
                issues.append({**frozen[issue_id], "status": "unresolved"})
        result["issues"] = issues
        return result

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
                minimum_han, maximum_han = self._short_revision_target_range(
                    project,
                )
                current_han = effective_han_characters(protected["source"])
                deficit_han = max(0, minimum_han - current_han)
                causal_chain_artifact = LearningSystem(
                    self.db, self.references, self.projects, self.gateway,
                ).get_artifact(project.id, "short_causal_chain")
                expansion_issue_id = next((
                    issue["issue_id"] for issue in selected_issues
                    if deficit_han and self._is_length_deficit_issue(issue)
                ), None)
                groups = [{
                    "group_id": issue_id,
                    "issue_ids": [issue_id],
                    "kind": (
                        "expansion"
                        if issue_id == expansion_issue_id
                        else "mechanical"
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
                    "seven_step_causal_chain": (
                        self._json_copy(causal_chain_artifact["data"])
                        if (
                            causal_chain_artifact is not None
                            and causal_chain_artifact.get("status") == "active"
                        )
                        else None
                    ),
                    "passage_locks": self._json_copy(
                        self.db.list_locks(project.id),
                    ),
                    "semantic_authority": self._json_copy(
                        protected.get("semantic_authority"),
                    ),
                    "analysis": analysis,
                    "required_text": self._repair_literals(
                        selected_issues, "required_text",
                    ),
                    "forbidden_text": self._repair_literals(
                        selected_issues, "forbidden_text",
                    ),
                    "length_budget": {
                        "current_han": current_han,
                        "minimum_han": minimum_han,
                        "maximum_han": maximum_han,
                        "deficit_han": deficit_han,
                    },
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
                candidate_before_group = candidate
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
                    elif group["kind"] == "expansion":
                        patch_group = await self._expansion_patch_group(
                            run_id, run_path, project, constraints,
                            contract, issue, group_id, candidate,
                            record, store, records, completed,
                        )
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
                except ExpansionRejectedError as exc:
                    record.update({
                        "status": "rejected",
                        "message": str(exc),
                    })
                    record.pop("patch_group", None)
                    record["patch_result"] = {
                        "group_id": group_id,
                        "accepted": False,
                        "text": candidate,
                        "failures": [{
                            "patch": 0,
                            "code": exc.code,
                        }],
                        "diffs": [],
                    }
                    self._save_short_revision_state(
                        store, contract, run_id, records, candidate,
                        completed, None, "running",
                    )
                    self.db.add_run_event(
                        run_id, "warning",
                        "short_revision_group_rejected", str(exc),
                        stage="repair_groups",
                        metadata={
                            "group_id": group_id,
                            "category": exc.category,
                        },
                    )
                    continue
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
                        semantic_integrity = None
                        semantic_authority = contract.get("semantic_authority")
                        if (
                            group["kind"] != "mechanical"
                            and isinstance(semantic_authority, dict)
                        ):
                            try:
                                semantic_integrity = (
                                    await self._verify_atomic_candidate_semantics(
                                        run_id, run_path, project, constraints,
                                        str(semantic_authority.get("source_text") or ""),
                                        candidate, semantic_authority,
                                        suffix=f"-repair-{group_id}-candidate",
                                        failure_stage="repair_groups",
                                        verify_whole=False,
                                    )
                                )
                            except DraftSemanticValidationError as exc:
                                try:
                                    (
                                        patch_group, result, semantic_integrity,
                                    ) = await self._repair_short_revision_semantic_group(
                                        run_id, run_path, project, constraints,
                                        contract, issue, group_id,
                                        candidate_before_group, candidate,
                                        patch_group, exc,
                                    )
                                except DraftSemanticValidationError as repair_exc:
                                    completed.discard(group_id)
                                    candidate, _ = self._replay_repair_records(
                                        protected["source"], records, completed,
                                    )
                                    record.pop("patch_group", None)
                                    record["patch_result"] = {
                                        "group_id": group_id,
                                        "accepted": False,
                                        "text": candidate,
                                        "failures": [{
                                            "patch": 0,
                                            "code": "semantic_repair_exhausted",
                                        }],
                                        "diffs": [],
                                    }
                                    record.update({
                                        "status": "rejected",
                                        "message": (
                                            "当前修改组两次原子语义修复仍未通过，"
                                            "已恢复该组执行前的候选稿"
                                        ),
                                        "semantic_issues": repair_exc.issues,
                                    })
                                    self._save_short_revision_state(
                                        store, contract, run_id, records,
                                        candidate, completed, None, "running",
                                    )
                                    self.db.add_run_event(
                                        run_id, "warning",
                                        "short_revision_semantic_repair_exhausted",
                                        "当前修改组未能安全修复，已撤销该组并继续其他独立问题",
                                        stage="repair_groups", metadata={
                                            "group_id": group_id,
                                            "issues": repair_exc.issues,
                                        },
                                    )
                                    continue
                                candidate = result["text"]
                                record["patch_group"] = patch_group
                                record["patch_result"] = result
                        if semantic_integrity is not None:
                            record["semantic_integrity"] = semantic_integrity
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
        except Exception:
            run = self.db.get_run(run_id)
            if run and run["status"] not in {"failed", "cancelled"}:
                message = "定向返修未完成，已保留可恢复的检查点"
                self.db.update_run(
                    run_id, "failed", run.get("current_stage"), error=message,
                )
                self.db.add_run_event(
                    run_id, "error", "short_revision_failed", message,
                    stage=run.get("current_stage"),
                )
            raise

    def _protected_short_revision_source(self, project: Project) -> dict:
        best = None
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
            candidate = {
                "run_id": run["id"],
                "checkpoint": checkpoint,
                "source": source,
                "source_hash": source_hash,
                "review": review,
                "issue_ledger": ledger,
            }
            semantic_authority = self._quality_semantic_authority(
                project, run_path, checkpoint, source,
            )
            if semantic_authority is not None:
                candidate["semantic_authority"] = semantic_authority
            if (
                best is None
                or checkpoint["score"] > best["checkpoint"]["score"]
            ):
                best = candidate
        if best is not None:
            return best
        raise ValueError("当前项目没有与终审结果绑定的受保护最佳稿")

    def _quality_semantic_authority(
        self, project: Project, run_path: Path, checkpoint: dict, source: str,
    ) -> dict | None:
        """Load only a hash-bound, replayable atomic authority for a protected best draft."""
        reference = checkpoint.get("narrative_integrity")
        if not isinstance(reference, dict):
            return None
        relative_path = reference.get("path")
        expected_sha256 = reference.get("sha256")
        if not isinstance(relative_path, str) or not relative_path.startswith("outputs/"):
            return None
        if not isinstance(expected_sha256, str):
            return None
        try:
            integrity_path = (run_path / relative_path).resolve()
            integrity_path.relative_to(run_path.resolve())
            integrity_bytes = integrity_path.read_bytes()
            if hashlib.sha256(integrity_bytes).hexdigest() != expected_sha256:
                return None
            integrity = json.loads(integrity_bytes.decode("utf-8"))
            manifest_payload = json.loads(
                (run_path / "outputs" / "short-execution-index.json").read_text(
                    encoding="utf-8",
                )
            )
            manifest = parse_execution_manifest(manifest_payload)
        except (
            OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError,
        ):
            return None
        source_parts = self._split_segments(source)
        receipts = integrity.get("semantic_segment_receipts")
        if (
            manifest.status != "ready"
            or execution_manifest_receipt_binding_issues(manifest)
            or integrity.get("status") != "passed"
            or integrity.get("draft_sha256") != self._text_hash(source)
            or integrity.get("execution_manifest_sha256")
            != execution_manifest_sha256(manifest)
            or len(manifest.segments) != len(source_parts)
            or not isinstance(receipts, list)
            or len(receipts) != len(source_parts)
        ):
            return None
        try:
            for index, (segment, prose, receipt) in enumerate(
                zip(manifest.segments, source_parts, receipts, strict=True), 1,
            ):
                contract = self._manifest_segment_contract(
                    project, manifest, integrity, segment, prose, index,
                )
                validate_semantic_receipt(contract, prose, receipt)
        except (TypeError, ValueError):
            return None
        return {
            "execution_manifest": asdict(manifest),
            "source_integrity": integrity,
            "source_text": source,
        }

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

    @staticmethod
    def _is_length_deficit_issue(issue: dict) -> bool:
        codes = {
            "length", "length_deficit", "word_count",
            "minimum_han_not_met",
        }
        return any(
            issue.get(key) in codes
            for key in ("category", "code", "issue_type")
        )

    @staticmethod
    def _expansion_anchor_candidates(candidate: str) -> list[dict]:
        max_candidates = 24
        max_anchor_characters = 120
        max_preview_characters = 160
        candidates = []
        seen = set()

        def add_anchor(raw: str, raw_start: int) -> bool:
            anchor = raw.strip()
            if (
                len(anchor) < 4
                or len(anchor) > max_anchor_characters
                or anchor in seen
                or candidate.count(anchor) != 1
            ):
                return False
            position = raw_start + raw.index(anchor)
            preview_start = max(0, position - 48)
            preview_start = min(
                preview_start,
                max(0, len(candidate) - max_preview_characters),
            )
            candidates.append({
                "anchor": anchor,
                "position": position,
                "preview": candidate[
                    preview_start:preview_start + max_preview_characters
                ],
            })
            seen.add(anchor)
            return True

        paragraph_start = 0
        separators = [
            *re.finditer(r"(?:\r?\n){2,}", candidate),
            None,
        ]
        for separator in separators:
            paragraph_end = (
                separator.start() if separator is not None else len(candidate)
            )
            paragraph = candidate[paragraph_start:paragraph_end]
            if paragraph.strip():
                added = False
                if len(paragraph.strip()) <= max_anchor_characters:
                    added = add_anchor(paragraph, paragraph_start)
                if not added:
                    for sentence in re.finditer(
                        r"[^。！？!?；;\r\n]+"
                        r"(?:[。！？!?；;]+[”’」』]?|$)",
                        paragraph,
                    ):
                        add_anchor(
                            sentence.group(0),
                            paragraph_start + sentence.start(),
                        )
            if separator is not None:
                paragraph_start = separator.end()

        candidates.sort(key=lambda item: item["position"])
        if len(candidates) <= max_candidates:
            return candidates
        selected = []
        available = list(candidates)
        text_end = max(0, len(candidate) - 1)
        for index in range(max_candidates):
            target = text_end * index / (max_candidates - 1)
            closest = min(
                available,
                key=lambda item: (
                    abs(item["position"] - target),
                    item["position"],
                ),
            )
            selected.append(closest)
            available.remove(closest)
        return sorted(selected, key=lambda item: item["position"])

    async def _expansion_patch_group(
        self, run_id: str, run_path: Path, project: Project,
        constraints: str, contract: dict, issue: dict,
        group_id: str, candidate: str,
        record: dict, store: RepairRunStore, records: list[dict],
        completed: set[str],
    ) -> dict:
        budget = contract["length_budget"]
        anchor_candidates = self._expansion_anchor_candidates(candidate)
        if not anchor_candidates:
            raise ValueError("候选稿缺少可安全定位的扩写锚点")
        allowed_anchors = {
            item["anchor"] for item in anchor_candidates
        }
        scene_records = record.get("expansion_plan")
        if not isinstance(scene_records, list):
            request = {
                "schema": "short-expansion-plan-v1",
                "group_id": group_id,
                "candidate_hash": self._text_hash(candidate),
                "issue": issue,
                "current_han": budget["current_han"],
                "minimum_han": budget["minimum_han"],
                "maximum_han": budget["maximum_han"],
                "deficit_han": budget["deficit_han"],
                "story_state": contract["story_state"]["data"],
                "seven_step_causal_chain": contract.get(
                    "seven_step_causal_chain",
                ),
                "anchor_candidates": anchor_candidates,
                "instructions": EXPANSION_CONTRACT,
            }
            raw_plan = await self._stage(
                run_id, run_path, project, "revision_plan", constraints,
                json.dumps(request, ensure_ascii=False),
                suffix=f"-expand-plan-{group_id}", allow_tools=False,
                output_source_characters=budget["deficit_han"],
                targeted_retry=True,
            )
            try:
                scenes = self._normalize_expansion_plan(
                    self._json_object(raw_plan), candidate,
                    budget["deficit_han"], allowed_anchors,
                )
            except ValueError:
                raise ExpansionRejectedError(
                    "expansion_contract_rejected",
                    "expansion_contract_validation",
                    "扩写规划未通过本地验收，当前修改组未应用",
                ) from None
            scene_records = [{
                "scene_index": index,
                "contract": scene,
                "status": "pending",
            } for index, scene in enumerate(scenes, 1)]
            record["expansion_plan"] = scene_records
            self._save_short_revision_state(
                store, contract, run_id, records, candidate,
                completed, None, "running",
            )
        try:
            scenes = self._normalize_expansion_plan(
                {
                    "scenes": [
                        scene_record["contract"]
                        for scene_record in scene_records
                    ],
                },
                candidate,
                budget["deficit_han"],
                allowed_anchors,
            )
        except (KeyError, TypeError, ValueError):
            raise ExpansionRejectedError(
                "expansion_contract_rejected",
                "expansion_contract_validation",
                "扩写规划未通过本地验收，当前修改组未应用",
            ) from None
        patches = []
        for index, (scene, scene_record) in enumerate(
            zip(scenes, scene_records, strict=True), 1,
        ):
            draft = scene_record.get("draft")
            if scene_record.get("status") != "drafted" or not isinstance(
                draft, dict,
            ):
                draft_request = {
                    "schema": "short-expansion-scene-v1",
                    "group_id": group_id,
                    "scene_index": index,
                    "scene_count": len(scenes),
                    "contract": scene,
                    "authoritative_facts": [
                        *contract["story_state"]["data"].get(
                            "locked_facts", [],
                        ),
                        *contract["story_state"]["data"].get(
                            "confirmed_facts", [],
                        ),
                    ],
                    "seven_step_causal_chain": contract.get(
                        "seven_step_causal_chain",
                    ),
                    "instructions": (
                        "只返回严格 JSON，不得改写锚点或其他正文。"
                        "text 必须是可直接插入的场景正文，"
                        "并逐项回报合同中的状态字段。"
                    ),
                }
                raw_scene = await self._stage(
                    run_id, run_path, project, "draft", constraints,
                    json.dumps(draft_request, ensure_ascii=False),
                    suffix=f"-expand-draft-{group_id}-{index}",
                    allow_tools=False,
                    output_source_characters=scene["target_han"],
                    targeted_retry=True,
                )
                try:
                    draft = self._json_object(raw_scene)
                    self._validate_expansion_draft(draft, scene)
                except ValueError:
                    raise ExpansionRejectedError(
                        "expansion_draft_rejected",
                        "expansion_draft_validation",
                        "扩写场景未通过本地验收，当前修改组未应用",
                    ) from None
                scene_record["draft"] = draft
                scene_record["status"] = "drafted"
                self._save_short_revision_state(
                    store, contract, run_id, records, candidate,
                    completed, None, "running",
                )
            try:
                scene_text = self._validate_expansion_draft(draft, scene)
            except ValueError:
                raise ExpansionRejectedError(
                    "expansion_draft_rejected",
                    "expansion_draft_validation",
                    "扩写场景未通过本地验收，当前修改组未应用",
                ) from None
            patches.append({
                "operation": scene["operation"],
                "old_text": scene["anchor"],
                "new_text": (
                    f"\n\n{scene_text}"
                    if scene["operation"] == "insert_after"
                    else f"{scene_text}\n\n"
                ),
            })
        return {
            "group_id": group_id,
            "issue_ids": [group_id],
            "kind": "semantic",
            "requires_user_confirmation": True,
            "requires_full_review": True,
            "impact_flags": ["scene_inserted"],
            "expansion_contracts": scenes,
            "patches": patches,
        }

    @staticmethod
    def _normalize_expansion_plan(
        value: dict, candidate: str, deficit_han: int,
        allowed_anchors: set[str] | None = None,
    ) -> list[dict]:
        scenes = value.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("扩写计划必须包含至少一个场景")
        normalized = []
        anchors = set()
        for scene in scenes:
            if not isinstance(scene, dict):
                raise ValueError("扩写场景合同格式无效")
            for key in (
                "purpose", "entry_state", "exit_state", "anchor",
                "time", "evidence_source", "transition",
            ):
                if not isinstance(scene.get(key), str) or not scene[key].strip():
                    raise ValueError("扩写场景合同缺少必要状态")
            target_han = scene.get("target_han")
            if (
                not isinstance(target_han, int)
                or isinstance(target_han, bool)
                or target_han <= 0
            ):
                raise ValueError("扩写场景目标汉字数无效")
            anchor = scene["anchor"]
            if (
                anchor in anchors
                or candidate.count(anchor) != 1
                or (
                    allowed_anchors is not None
                    and anchor not in allowed_anchors
                )
            ):
                raise ValueError("扩写场景锚点必须唯一")
            if scene.get("operation") not in {"insert_before", "insert_after"}:
                raise ValueError("扩写场景只能使用插入操作")
            if scene.get("requires_full_review") is not True:
                raise ValueError("扩写场景必须要求全文复核")
            new_facts = scene.get("new_facts")
            if (
                not isinstance(new_facts, list)
                or any(
                    not isinstance(fact, str) or not fact.strip()
                    for fact in new_facts
                )
            ):
                raise ValueError("扩写场景新增事实必须是非空字符串列表")
            anchors.add(anchor)
            normalized.append({
                **scene,
                "new_facts": [fact.strip() for fact in new_facts],
            })
        if sum(scene["target_han"] for scene in normalized) != deficit_han:
            raise ValueError("扩写场景目标汉字数总和必须等于本地缺口")
        return normalized

    @staticmethod
    def _validate_expansion_draft(value: dict, contract: dict) -> str:
        text = value.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("扩写场景正文为空")
        target_han = contract["target_han"]
        actual_han = effective_han_characters(text)
        if actual_han < target_han or actual_han > math.ceil(target_han * 1.1):
            raise ValueError("扩写场景有效汉字数超出本地允许范围")
        for key in (
            "entry_state", "exit_state", "time",
            "evidence_source", "transition", "new_facts",
        ):
            if value.get(key) != contract.get(key):
                raise ValueError("扩写场景状态与规划合同不一致")
        return text.strip()

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
            store, run_id, records, candidate, gate, status, contract,
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
        contract: dict | None = None,
    ) -> dict:
        issues = {
            item.get("issue_id"): item
            for item in (contract or {}).get("selected_issues", [])
            if isinstance(item, dict) and isinstance(item.get("issue_id"), str)
        }

        def public_group(record: dict) -> dict:
            patch_group = record.get("patch_group")
            patch_result = record.get("patch_result")
            patches = (
                patch_group.get("patches", [])
                if isinstance(patch_group, dict) else []
            )
            failures = (
                patch_result.get("failures", [])
                if isinstance(patch_result, dict) else []
            )
            issue_ids = record.get("issue_ids", [])
            issue = (
                issues.get(issue_ids[0])
                if isinstance(issue_ids, list) and issue_ids else None
            )
            if isinstance(issue, dict):
                issue = dict(issue)
                if record.get("issue_status"):
                    issue["status"] = record["issue_status"]
            decision = record.get("decision")
            if (
                decision is None
                and record.get("kind") == "mechanical"
                and isinstance(patch_result, dict)
                and patch_result.get("accepted") is True
            ):
                decision = "adopted"
            before = [
                patch.get("old_text")
                for patch in patches
                if isinstance(patch, dict) and isinstance(
                    patch.get("old_text"), str,
                )
            ]
            after = [
                patch.get("new_text")
                for patch in patches
                if isinstance(patch, dict) and isinstance(
                    patch.get("new_text"), str,
                )
            ]
            return {
                "group_id": record["group_id"],
                "issue_ids": issue_ids,
                "kind": record.get("kind"),
                "status": record.get("status"),
                "decision": decision,
                "message": record.get("message"),
                "attempts": record.get("attempts", 0),
                "patches": patches,
                "failures": failures,
                "issue": issue,
                "before": before,
                "after": after,
                "related_positions": (
                    patch_group.get("related_positions", [])
                    if isinstance(patch_group, dict) else []
                ),
                "local_checks": {
                    "passed": (
                        patch_result.get("accepted") is True
                        if isinstance(patch_result, dict) else False
                    ),
                    "failures": failures,
                },
            }

        groups = {
            record["group_id"]: public_group(record)
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
        full_review_reasons = []
        for record in records:
            patch_group = record.get("patch_group")
            patch_result = record.get("patch_result")
            if (
                not isinstance(patch_group, dict)
                or not isinstance(patch_result, dict)
                or patch_result.get("accepted") is not True
            ):
                continue
            for reason in patch_group.get("impact_flags", []):
                if reason not in full_review_reasons:
                    full_review_reasons.append(reason)
        report["review_mode"] = (
            "full" if full_review_reasons else "incremental"
        )
        report["full_review_reasons"] = full_review_reasons
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
        outline_path = project.path / "memory" / "book-plan.md"
        canon_path = project.path / "memory" / "canon.json"
        volumes_path = project.path / "memory" / "volumes.json"
        snapshot = ProjectSnapshot.create(
            project.path, project.path / "snapshots" / run_id, [outline_path, canon_path, volumes_path],
        )
        try:
            constraints = self.projects.load_constraints(project.id)
            brief = (
                "Expand the immutable confirmed outline into a complete long-form execution plan with "
                "fixed ending, protagonist arc, act structure, "
                "3-5 volumes, chapter map, hooks, foreshadowing, characters, relationships, world rules, "
                "timeline and knowledge boundaries. Do not replace or contradict the confirmed outline.\n\n" +
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
            checkpoint_context = self._short_checkpoint_context(
                project, state.revision, state.data, constraints, segment_count,
            )
            readiness_conflicts = detect_canon_conflicts(
                project, state.data,
                str((state.data.get("outline") or {}).get("content") or ""),
            )
            if readiness_conflicts:
                raise ValueError(
                    f"正式大纲与项目资料有 {len(readiness_conflicts)} 处冲突，请先在作品应用中确认设定"
                )
            checkpoint = self._find_short_checkpoint(
                project, run_id, segment_count, checkpoint_context,
            )
            if checkpoint:
                checkpoint_plan = (checkpoint / "planning.md").read_text(encoding="utf-8")
                if self._short_plan_issues(project, state.data, checkpoint_plan, segment_count):
                    self.db.add_run_event(
                        run_id, "warning", "checkpoint_plan_rejected",
                        "上一轮规划没有通过新的分段与设定检查，本次将重新规划",
                        stage="planning",
                    )
                    checkpoint = None
            partial_checkpoint = (
                None if checkpoint else self._find_short_partial_checkpoint(
                    project, run_id, state.revision, state.data, constraints,
                    segment_count,
                )
            )
            resumed_best = False
            if checkpoint:
                plan, draft, source_artifact, causal_chain = self._restore_short_checkpoint(
                    checkpoint, run_path / "outputs", checkpoint_context,
                )
                resumed_best = source_artifact == "best-candidate.md"
                constraints += (
                    "\n\n# Short Story Causal Chain\n\n"
                    + compact_causal_chain(causal_chain)
                )
                self.db.add_run_event(
                    run_id, "success", "checkpoint_reused", "已复用上一轮完整规划和分段草稿",
                    stage="draft", metadata={
                        "source_run": checkpoint.parent.name,
                        "source_artifact": source_artifact,
                    },
                )
            elif partial_checkpoint:
                plan = (partial_checkpoint / "planning.md").read_text(encoding="utf-8")
                causal_chain = json.loads(
                    (partial_checkpoint / "short-causal-chain.json").read_text(
                        encoding="utf-8"
                    )
                )
                atomic_write(run_path / "outputs" / "planning.md", plan)
                atomic_write(
                    run_path / "outputs" / "short-causal-chain.json",
                    json.dumps(causal_chain, ensure_ascii=False, indent=2),
                )
                atomic_write(
                    run_path / "outputs" / "short-execution-index.json",
                    (partial_checkpoint / "short-execution-index.json").read_text(
                        encoding="utf-8",
                    ),
                )
                formal_outline = state.data.get("outline") or {}
                formal_outline_content = str(formal_outline.get("content") or "")
                formal_outline_events = (
                    outline_events(formal_outline_content)
                    if formal_outline_content.strip()
                    else formal_outline.get("events") or []
                )
                await self._ensure_short_execution_manifest(
                    run_id, run_path, project, constraints, state.revision,
                    state.data, plan, causal_chain, formal_outline_events,
                    segment_count,
                )
                for source in sorted(
                    (partial_checkpoint / "draft-checkpoints").glob("segment-*.json")
                ):
                    atomic_write(
                        run_path / "outputs" / "draft-checkpoints" / source.name,
                        source.read_text(encoding="utf-8"),
                    )
                constraints += (
                    "\n\n# Short Story Causal Chain\n\n"
                    f"{compact_causal_chain(causal_chain)}"
                )
                draft = await self._draft_short_in_segments(
                    run_id, run_path, project, constraints, plan,
                )
                self._save_short_checkpoint(
                    run_path / "outputs", checkpoint_context,
                )
                self.db.add_run_event(
                    run_id, "success", "partial_draft_checkpoint_reused",
                    "已复用上一任务通过校验的正文前缀，并从首个缺失分段继续",
                    stage="draft", metadata={
                        "source_run": partial_checkpoint.parent.name,
                    },
                )
            else:
                formal_outline = state.data.get("outline") or {}
                formal_outline_content = str(formal_outline.get("content") or "")
                formal_outline_events = (
                    outline_events(formal_outline_content)
                    if formal_outline_content.strip()
                    else formal_outline.get("events") or []
                )
                brief = json.dumps({
                    **project.metadata,
                    "formal_story_facts": canon_profile(project, state.data),
                    "formal_outline_events": narrative_outline_events(
                        formal_outline_events
                    ),
                    "generation_contract": {
                        "target_total_words": target_words,
                        "segment_count": segment_count,
                        "require_segment_map": segment_count > 1,
                        "segment_heading_format": (
                            f"### 第 1 段：标题，依次编号到 ### 第 {segment_count} 段：标题"
                        ),
                        "segment_block_fields": (
                            [
                                "事件ID：认领正式大纲事件表中的一个或多个 ID；连续分段可共同完成同一事件",
                                "大纲依据：对应的正式大纲事件名称",
                                "段首承接：上一段留下的人物位置、动作、关系和已知信息",
                                "本段事件：本段唯一负责的事件",
                                "段末交接：留给下一段的人物位置、动作、关系和已知信息",
                            ] if segment_count > 1 else []
                        ),
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
                expected_plan_characters = max(3000, 1200 * segment_count)
                proactive_split = self._route_requires_semantic_split(
                    "planning", expected_plan_characters,
                )
                try:
                    if proactive_split:
                        raise IncompleteModelOutputError(
                            "planning", StageText("", {"finish_reason": "predicted_limit"}),
                        )
                    plan = await self._stage(
                        run_id, run_path, project, "planning", constraints, brief,
                        allow_tools=self._planning_uses_tools(state),
                        expected_output_characters=expected_plan_characters,
                        completion_check=lambda value: self._short_plan_output_complete(
                            project, state.data, value, segment_count,
                        ),
                    )
                except IncompleteModelOutputError:
                    plan = await self._plan_short_in_batches(
                        run_id, run_path, project, constraints, brief,
                        state.data, segment_count,
                    )
                plan, causal_chain = self._extract_short_causal_chain(run_id, plan)
                plan_issues = self._short_plan_issues(
                    project, state.data, plan, segment_count,
                )
                if plan_issues:
                    self.db.add_run_event(
                        run_id, "warning", "planning_gate_retry",
                        "规划稿没有通过本地检查，正在修正后再进入正文",
                        stage="planning", metadata={"issues": plan_issues},
                    )
                    repair_prompt = (
                        "请修正下面的规划稿。必须保留正式大纲的故事方向，为每个分段明确分配互不重复的事件，"
                        f"必须恰好写 {segment_count} 个分段，标题依次使用“### 第 1 段：标题”"
                        f"到“### 第 {segment_count} 段：标题”；"
                        "并使用正式人物和地点名称。每段都要写明“段首承接”“本段事件”“段末交接”；"
                        "每个正式大纲事件 ID 都必须覆盖且顺序不能倒退；连续分段可以共同完成同一事件，"
                        "并写明“大纲依据”；"
                        "段首和段末必须交代人物位置、正在做什么、关系变化和已经知道什么。"
                        "只返回完整修正版规划稿。\n\n"
                        f"需要修正：{json.dumps(plan_issues, ensure_ascii=False)}\n\n"
                        f"当前规划稿：\n{plan}"
                    )
                    try:
                        repaired_plan = await self._stage(
                            run_id, run_path, project, "planning", constraints,
                            repair_prompt,
                            suffix="-gate-repair", allow_tools=False,
                            expected_output_characters=expected_plan_characters,
                            completion_check=lambda value: self._short_plan_output_complete(
                                project, state.data, value, segment_count,
                            ),
                        )
                    except IncompleteModelOutputError:
                        repaired_plan = await self._plan_short_in_batches(
                            run_id, run_path, project, constraints,
                            brief + "\n\nREPAIR REQUIREMENTS:\n" + repair_prompt,
                            state.data, segment_count,
                        )
                    plan, repaired_chain = self._extract_short_causal_chain(
                        run_id, repaired_plan,
                    )
                    causal_chain = repaired_chain or causal_chain
                    remaining = self._short_plan_issues(
                        project, state.data, plan, segment_count,
                    )
                    if remaining:
                        self.db.add_run_event(
                            run_id, "error", "planning_gate_failed",
                            "规划稿仍有设定或分段问题，已在生成正文前停止",
                            stage="planning", metadata={"issues": remaining},
                        )
                        raise ValueError("规划稿未通过设定和分段检查，尚未生成正文")
                atomic_write(run_path / "outputs" / "planning.md", plan)
                causal_chain = await self._ensure_short_causal_chain(
                    run_id, run_path, project, constraints, plan,
                    formal_outline_events, causal_chain,
                )
                self._save_short_causal_chain(run_id, project, causal_chain)
                await self._ensure_short_execution_manifest(
                    run_id, run_path, project, constraints, state.revision,
                    state.data, plan, causal_chain, formal_outline_events,
                    segment_count,
                )
                constraints += (
                    "\n\n# Short Story Causal Chain\n\n"
                    f"{compact_causal_chain(causal_chain)}"
                )
                draft = await self._draft_short_in_segments(
                    run_id, run_path, project, constraints, plan,
                )
                atomic_write(run_path / "outputs" / "draft.md", draft)
                self._save_short_checkpoint(
                    run_path / "outputs", checkpoint_context,
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
            review_checkpoint = (
                None if resumed_best or checkpoint is None else self._find_short_stage_output(
                    project, checkpoint.parent.name, "review.md",
                )
            )
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
            publish_text = "\n\n".join(self._split_segments(polished))
            publish_analysis = self._analyze_manuscript(
                publish_text, run_path, project, "publish",
            )
            publish_blockers = [
                item for item in publish_analysis.get("prose", {}).get("findings", [])
                if item.get("blocking")
            ]
            if publish_blockers:
                self.db.add_run_event(
                    run_id, "error", "publish_local_gate_failed",
                    "发布前全文检查发现正文异常，已保留最佳稿但不会写入正式稿",
                    stage="quality", metadata={"findings": publish_blockers[:12]},
                )
                raise ValueError("发布前全文检查未通过，请先处理正文完整性问题")
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
                self._restore_snapshot_after_failure(run_id, snapshot)
            if candidate_id:
                self.story_states.reject(candidate_id, "cancelled")
            if draft_candidate_id:
                self.story_states.reject(draft_candidate_id, "cancelled")
            self.db.update_run(run_id, "cancelled", error="Cancelled by user")
            raise
        except Exception as exc:
            if not state_committed:
                self._restore_snapshot_after_failure(run_id, snapshot)
            if candidate_id:
                self.story_states.reject(candidate_id, str(exc))
            if draft_candidate_id:
                self.story_states.reject(draft_candidate_id, str(exc))
            self.db.update_run(run_id, "failed", error=str(exc))
            raise

    def _extract_short_causal_chain(
        self, run_id: str, plan: str,
    ) -> tuple[str, dict | None]:
        try:
            outline, chain = extract_short_causal_chain(plan)
        except (ValueError, json.JSONDecodeError) as exc:
            self.db.add_run_event(
                run_id, "warning", "causal_chain_parse_failed",
                "短篇因果链解析失败，规划稿将先进入本地修正",
                stage="planning", metadata={"error": str(exc)[:300]},
            )
            return plan, None
        if not chain:
            return plan, None

        return outline, chain

    def _short_plan_output_complete(
        self, project: Project, state: dict, value: str, segment_count: int,
    ) -> bool:
        try:
            outline, _chain = extract_short_causal_chain(value)
        except (ValueError, json.JSONDecodeError):
            return False
        return not self._short_plan_issues(project, state, outline, segment_count)

    def _route_requires_semantic_split(
        self, role: str, expected_output_characters: int,
    ) -> bool:
        binding = self.db.get_role_binding(role) or {}
        provider_id = str(binding.get("primary_provider_id") or "")
        model_id = str(binding.get("primary_model_id") or "")
        if not provider_id or not model_id:
            return False
        stable_limits = [
            profile["suspected_stable_output_tokens"]
            for profile in (
                self.db.latest_model_output_profile(provider_id, model_id, "plain"),
                self.db.latest_model_output_profile(
                    provider_id, model_id, "native_tool_round",
                ),
            )
            if isinstance(profile.get("suspected_stable_output_tokens"), int)
            and profile["suspected_stable_output_tokens"] > 0
        ]
        if not stable_limits:
            return False
        stable = min(stable_limits)
        return estimate_input_tokens("汉" * expected_output_characters) >= int(stable * 0.75)

    async def _plan_short_in_batches(
        self, run_id: str, run_path: Path, project: Project, constraints: str,
        brief: str, state: dict, segment_count: int,
    ) -> str:
        if segment_count < 2:
            raise ValueError("单段短篇规划超过供应商可完整返回的范围，无法安全拆分")
        batch_size = max(1, math.ceil(segment_count / 2))
        ranges = [
            (start, min(segment_count, start + batch_size - 1))
            for start in range(1, segment_count + 1, batch_size)
        ]
        self.db.add_run_event(
            run_id, "warning", "planning_task_split",
            "规划单次输出可能不完整，已按连续写作段拆成内部子任务",
            stage="planning", metadata={
                "subtasks": len(ranges), "segment_count": segment_count,
            },
        )
        blocks: list[str] = []
        checkpoint_root = run_path / "outputs" / "planning-checkpoints"
        authority = hashlib.sha256(
            (brief + constraints).encode("utf-8")
        ).hexdigest()
        for batch_number, (start, end) in enumerate(ranges, 1):
            previous = "\n\n".join(blocks)
            previous_hash = hashlib.sha256(previous.encode("utf-8")).hexdigest()
            checkpoint_path = checkpoint_root / f"batch-{batch_number:02d}.json"
            try:
                cached = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, AttributeError):
                cached = {}
            block = str(cached.get("text") or "")
            if not (
                cached.get("authority_sha256") == authority
                and cached.get("previous_sha256") == previous_hash
                and cached.get("range") == [start, end]
                and cached.get("text_sha256")
                == hashlib.sha256(block.encode("utf-8")).hexdigest()
                and self._short_plan_batch_complete(block, start, end)
            ):
                prompt = (
                    f"{brief}\n\nAUTOMATIC INTERNAL PLANNING SUBTASK {batch_number}/{len(ranges)}\n"
                    f"本次只返回第 {start} 段到第 {end} 段的完整规划块，标题必须使用"
                    f"“### 第 {start} 段：标题”到“### 第 {end} 段：标题”。"
                    "每段仍须包含事件ID、大纲依据、段首承接、本段事件、段末交接。"
                    "根据正式大纲顺序认领事件，不得重写前面批次，不得提前分配后续批次。"
                    + (f"\n\n前面已验收批次：\n{previous}" if previous else "")
                )
                block = await self._stage(
                    run_id, run_path, project, "planning", constraints, prompt,
                    suffix=f"-batch-{batch_number:02d}", allow_tools=False,
                    expected_output_characters=max(1800, (end - start + 1) * 1200),
                    completion_check=lambda value, first=start, last=end: (
                        self._short_plan_batch_complete(value, first, last)
                    ),
                )
                if not self._short_plan_batch_complete(block, start, end):
                    raise ValueError(
                        f"规划内部子任务 {batch_number} 未完整返回第 {start}-{end} 段"
                    )
                atomic_write(checkpoint_path, json.dumps({
                    "version": 1, "authority_sha256": authority,
                    "previous_sha256": previous_hash, "range": [start, end],
                    "text_sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
                    "text": block,
                }, ensure_ascii=False, indent=2))
            blocks.append(block.strip())
        combined = "\n\n".join(blocks)
        if self._short_plan_issues(project, state, combined, segment_count):
            self.db.add_run_event(
                run_id, "warning", "planning_batches_need_repair",
                "规划内部子任务已合并，正在通过原有全篇检查定位事件分工问题",
                stage="planning",
            )
        return combined

    @classmethod
    def _short_plan_batch_complete(cls, value: str, start: int, end: int) -> bool:
        headings = {
            number for _match, number in cls._short_plan_headings(value)
            if number is not None
        }
        return headings == set(range(start, end + 1)) and all(
            cls._short_plan_field(block, "event")
            and cls._short_plan_field(block, "handoff")
            for block in cls._short_plan_segments_for_range(value, start, end)
        )

    @classmethod
    def _short_plan_segments_for_range(
        cls, value: str, start: int, end: int,
    ) -> list[str]:
        headings = cls._short_plan_headings(value)
        blocks: list[str] = []
        for position, (match, number) in enumerate(headings):
            if number is None or not start <= number <= end:
                continue
            boundary = headings[position + 1][0].start() if position + 1 < len(headings) else len(value)
            blocks.append(value[match.start():boundary].strip())
        return blocks

    def _save_short_causal_chain(
        self, run_id: str, project: Project, chain: dict,
    ) -> None:
        LearningSystem(self.db, self.references, self.projects, self.gateway).build_short_causal_chain(
            project.id, chain,
        )
        self.db.add_run_event(
            run_id, "success", "causal_chain_saved",
            "短篇整篇因果链已保存为项目资料",
            stage="planning", metadata={"cycles": len(chain.get("cycles") or [])},
        )

    async def _ensure_short_causal_chain(
        self, run_id: str, run_path: Path, project: Project, constraints: str,
        plan: str, formal_outline_events: list[dict], candidate: dict | None,
    ) -> dict:
        target_words = int(project.metadata["target_words"])

        def valid(value: dict | None, *, require_coverage: bool) -> bool:
            if not isinstance(value, dict):
                return False
            if analyze_short_causal_chain(value, target_words)["status"] == "invalid":
                return False
            required_ids = [
                str(item.get("id") or "").upper()
                for item in narrative_outline_events(formal_outline_events)
                if str(item.get("id") or "").strip()
            ]
            covered = [
                str(item).upper() for item in value.get("covered_event_ids", [])
                if str(item).strip()
            ]
            return not require_coverage or not required_ids or covered == required_ids

        if valid(candidate, require_coverage=False):
            # Compatibility: older combined plans did not declare coverage, but a
            # validated embedded chain is still a required checkpoint artifact.
            atomic_write(
                run_path / "outputs" / "short-causal-chain.json",
                json.dumps(candidate, ensure_ascii=False, indent=2),
            )
            return candidate

        required_events = narrative_outline_events(formal_outline_events)
        atomic_write(
            run_path / "outputs" / "short-execution-index.json",
            json.dumps({
                "version": 2,
                "status": "causal_pending",
                "planning_sha256": hashlib.sha256(plan.encode("utf-8")).hexdigest(),
                "state_revision": self.story_states.ensure(
                    project.id, project.path,
                ).revision,
                "segment_count": self._short_segment_count(target_words),
                "beats": [], "segments": [], "semantic_receipt": {},
                "repair_attempts": 0,
            }, ensure_ascii=False, indent=2),
        )
        prompt = (
            "SHORT_CAUSAL_CHAIN_STANDALONE\n"
            "根据已经通过检查的正式规划，单独生成整篇短篇因果链。只返回一个 JSON 对象，"
            "不要 Markdown 围栏或说明。必须包含 core_goal、opening、cycles、accidents、"
            "reversal、ending、question_chain、relationship_arc、covered_event_ids。"
            "covered_event_ids 必须逐项、按原顺序覆盖正式大纲事件 ID；不得补写规划中没有的事实。\n\n"
            f"正式大纲事件：\n{json.dumps(required_events, ensure_ascii=False)}\n\n"
            f"已验收规划：\n{plan}"
        )

        def complete(text: str) -> bool:
            try:
                return valid(parse_json_object(text, label="Short causal chain"), require_coverage=True)
            except (TypeError, ValueError, json.JSONDecodeError):
                return False

        raw = await self._stage(
            run_id, run_path, project, "planning", constraints, prompt,
            suffix="-causal-chain", allow_tools=False,
            expected_output_characters=max(2500, len(plan) // 2),
            completion_check=complete,
        )
        try:
            chain = parse_json_object(raw, label="Short causal chain")
        except (ValueError, json.JSONDecodeError) as exc:
            chain = None
            first_error = str(exc)
        else:
            first_error = "semantic causal-chain validation failed"
        if not valid(chain, require_coverage=True):
            self.db.add_run_event(
                run_id, "warning", "causal_chain_repair",
                "因果链未覆盖全部正式事件，正在单独修正该资料",
                stage="planning", metadata={"error": first_error[:300]},
            )
            repaired = await self._stage(
                run_id, run_path, project, "planning", constraints,
                prompt + (
                    "\n\n上次输出没有通过完整性检查。重新返回完整 JSON，尤其确保"
                    "covered_event_ids 与正式大纲事件 ID 完全同序、无缺失。"
                ),
                suffix="-causal-chain-repair", allow_tools=False,
                expected_output_characters=max(2500, len(plan) // 2),
                completion_check=complete,
            )
            chain = parse_json_object(repaired, label="Short causal chain")
        if not valid(chain, require_coverage=True):
            self.db.add_run_event(
                run_id, "error", "causal_chain_not_ready",
                "因果链尚未完整生成，已在正文开始前停止",
                stage="planning",
            )
            raise ValueError("短篇因果链未通过事件覆盖和因果完整性检查，尚未生成正文")
        atomic_write(
            run_path / "outputs" / "short-causal-chain.json",
            json.dumps(chain, ensure_ascii=False, indent=2),
        )
        return chain

    @staticmethod
    def _short_execution_authority(
        project: Project, state_revision: int, state: dict, constraints: str,
        plan: str, causal_chain: dict, formal_outline_events: list[dict],
        segment_count: int,
    ) -> tuple[dict[str, str], str, list[dict]]:
        outline = state.get("outline") if isinstance(state, dict) else {}
        outline = outline if isinstance(outline, dict) else {}
        outline_content = str(outline.get("content") or "")
        events = narrative_outline_events(formal_outline_events)
        if not events:
            plan_segments = WorkflowService._short_plan_segments(plan, segment_count)
            if not plan_segments:
                plan_segments = [plan]
            events = [{
                "id": "EV-" + hashlib.sha1(
                    f"{project.id}|{index}|{block}".encode("utf-8"),
                ).hexdigest()[:8].upper(),
                "order": index,
                "label": f"已验收规划第 {index} 段事件",
                "section": "已验收规划",
                "kind": "narrative",
                "source": "accepted_plan_fallback",
                "evidence": block,
            } for index, block in enumerate(plan_segments, 1)]
        outline_sha = hashlib.sha256(outline_content.encode("utf-8")).hexdigest()
        planning_sha = hashlib.sha256(plan.encode("utf-8")).hexdigest()
        causal_json = json.dumps(
            causal_chain, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        causal_sha = hashlib.sha256(causal_json.encode("utf-8")).hexdigest()
        authority_payload = {
            "project_id": project.id,
            "state_revision": state_revision,
            "constraints_sha256": hashlib.sha256(
                constraints.encode("utf-8"),
            ).hexdigest(),
            "outline_sha256": outline_sha,
            "planning_sha256": planning_sha,
            "causal_chain_sha256": causal_sha,
            "segment_count": segment_count,
        }
        authority_sha = hashlib.sha256(json.dumps(
            authority_payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        hashes = {
            "authority_sha256": authority_sha,
            "outline_sha256": outline_sha,
            "planning_sha256": planning_sha,
            "causal_chain_sha256": causal_sha,
        }
        authority_text = (
            "FORMAL OUTLINE:\n" + outline_content
            + "\n\nFORMAL OUTLINE EVENTS:\n"
            + json.dumps(events, ensure_ascii=False, indent=2)
            + "\n\nACCEPTED PLAN:\n" + plan
            + "\n\nCAUSAL CHAIN:\n"
            + json.dumps(causal_chain, ensure_ascii=False, indent=2)
        )
        return hashes, authority_text, events

    async def _ensure_short_execution_manifest(
        self, run_id: str, run_path: Path, project: Project, constraints: str,
        state_revision: int, state: dict, plan: str, causal_chain: dict,
        formal_outline_events: list[dict], segment_count: int,
    ) -> ShortExecutionManifest:
        hashes, authority_text, expected_events = self._short_execution_authority(
            project, state_revision, state, constraints, plan, causal_chain,
            formal_outline_events, segment_count,
        )
        expected_event_ids = [
            str(item.get("id") or "").strip().upper()
            for item in expected_events if str(item.get("id") or "").strip()
        ]
        index_path = run_path / "outputs" / "short-execution-index.json"
        try:
            existing_payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing_payload = None
        if not legacy_execution_index_requires_rebuild(existing_payload):
            try:
                existing = parse_execution_manifest(existing_payload)
                issues = execution_manifest_issues(
                    existing, expected_event_ids=expected_event_ids,
                    segment_count=segment_count, authority_hashes=hashes,
                )
                receipt = validate_execution_manifest_receipt(
                    existing, authority_text, existing.semantic_receipt,
                )
            except (TypeError, ValueError):
                pass
            else:
                if not issues and existing.status == "ready":
                    return replace(existing, semantic_receipt=receipt)

        pending = {
            "version": 2, "status": "manifest_pending", **hashes,
            "beats": [], "segments": [], "semantic_receipt": {},
            "repair_attempts": 0,
        }
        atomic_write(index_path, json.dumps(pending, ensure_ascii=False, indent=2))
        schema = {
            "beats": [{
                "beat_id": "EV-XXXXXXXX/NN",
                "source_event_id": "EV-XXXXXXXX",
                "order": 1,
                "action": "一个明确角色完成的一个原子动作",
                "preconditions": ["动作发生前已经成立的状态"],
                "postconditions": ["该动作直接产生的状态"],
                "owner_segment": 1,
                "source_evidence": "必须逐字存在于 AUTHORITY TEXT 的短证据",
            }],
            "segments": [{
                "segment": 1,
                "beat_ids": ["EV-XXXXXXXX/01"],
                "entry_state": [{
                    "state": "进入本段前已经成立的状态",
                    "inherited_from": "opening 或 segment-NN",
                }],
                "exit_state": [{
                    "state": "本段结束时成立的状态",
                    "produced_by": "必须属于本段的 EV-XXXXXXXX/NN",
                }],
                "previous_exit_sha256": "由 Runtime 绑定；模型返回空字符串即可",
                "prohibited_future_beat_ids": ["尚未轮到本段执行的节拍 ID"],
            }],
        }
        base_prompt = (
            "SHORT_EXECUTION_MANIFEST_V2\n"
            "根据已经验收的正式大纲、规划和因果链，建立本次运行专用的原子节拍执行索引。"
            "只返回一个 JSON 对象，不要 Markdown 围栏或解释；不要改写正式大纲。\n"
            "每个正式事件可拆成多个 EV-XXXXXXXX/NN 原子节拍；每个节拍只能归属一个分段。"
            "出口状态只能由当前分段拥有的节拍产生；下一段继承状态，不能再次执行动作。"
            "必须覆盖全部正式事件且保持先后顺序。source_evidence 必须逐字取自 AUTHORITY TEXT。\n\n"
            f"EXPECTED EVENT IDS:\n{json.dumps(expected_event_ids, ensure_ascii=False)}\n\n"
            f"SEGMENT COUNT: {segment_count}\n\n"
            f"OUTPUT BODY SCHEMA:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            f"AUTHORITY TEXT:\n{authority_text}"
        )
        last_issues: list[dict] = []
        last_body: dict = {}
        for attempt in range(3):
            prompt = base_prompt
            if attempt:
                prompt += (
                    "\n\nREPAIR ATTEMPT " + str(attempt)
                    + ": 修正上次全部问题，不得只修第一项。\nISSUES:\n"
                    + json.dumps(last_issues, ensure_ascii=False, indent=2)
                    + "\n\nPREVIOUS BODY:\n"
                    + json.dumps(last_body, ensure_ascii=False, indent=2)
                )
            raw = await self._stage(
                run_id, run_path, project, "planning", constraints, prompt,
                suffix=f"-execution-manifest-{attempt + 1}", allow_tools=False,
                expected_output_characters=max(3000, 1200 * segment_count),
            )
            try:
                body = parse_json_object(raw, label="Short execution manifest")
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                body = {}
                last_issues = [{
                    "code": "invalid_manifest_json", "message": str(exc)[:500],
                }]
            else:
                try:
                    body = bind_previous_exit_hashes(body)
                except (TypeError, ValueError) as exc:
                    last_body = body
                    last_issues = [{
                        "code": "invalid_segment_boundary_state",
                        "message": str(exc)[:500],
                    }]
                    body = {}
                last_body = body
                candidate_payload = {
                    **body, "version": 2, "status": "ready", **hashes,
                    "semantic_receipt": {}, "repair_attempts": attempt,
                }
                try:
                    manifest = parse_execution_manifest(candidate_payload)
                except (TypeError, ValueError) as exc:
                    last_issues = [{
                        "code": "invalid_manifest_schema", "message": str(exc)[:500],
                    }]
                else:
                    last_issues = execution_manifest_issues(
                        manifest, expected_event_ids=expected_event_ids,
                        segment_count=segment_count, authority_hashes=hashes,
                    )
                    if not last_issues:
                        review_prompt = (
                            "SHORT_EXECUTION_MANIFEST_SEMANTIC_VALIDATION\n"
                            "只返回 JSON 语义回执。逐项核对角色与动作是否与正式资料一致、"
                            "每段出口是否确由本段节拍产生、相邻边界是否连续、正式大纲是否未被改写。"
                            "每个 evidence 必须逐字摘自 AUTHORITY TEXT。\n"
                            "字段：authority_sha256、manifest_sha256、beat_receipts"
                            "[{beat_id,evidence,actor_action_valid}]、segment_receipts"
                            "[{segment,boundary_valid,evidence}]、formal_plot_unchanged、summary。\n\n"
                            "EXECUTION MANIFEST:\n"
                            + json.dumps(asdict(manifest), ensure_ascii=False, indent=2)
                            + "\n\nAUTHORITY TEXT:\n" + authority_text
                        )
                        raw_receipt = await self._stage(
                            run_id, run_path, project, "review", constraints,
                            review_prompt, suffix=f"-execution-manifest-{attempt + 1}",
                            allow_tools=False,
                            expected_output_characters=max(1800, 500 * segment_count),
                        )
                        try:
                            receipt_payload = parse_json_object(
                                raw_receipt, label="Execution manifest receipt",
                            )
                            receipt = validate_execution_manifest_receipt(
                                manifest, authority_text, receipt_payload,
                            )
                        except (TypeError, ValueError, json.JSONDecodeError) as exc:
                            last_issues = [{
                                "code": "semantic_manifest_conflict",
                                "message": str(exc)[:500],
                            }]
                        else:
                            manifest = replace(manifest, semantic_receipt=receipt)
                            atomic_write(index_path, json.dumps(
                                asdict(manifest), ensure_ascii=False, indent=2,
                            ))
                            self.db.add_run_event(
                                run_id, "success", "planning_manifest_ready",
                                "规划执行索引已通过结构与语义核对",
                                stage="planning", metadata={
                                    "repair_attempts": attempt,
                                    "beat_count": len(manifest.beats),
                                    "segment_count": len(manifest.segments),
                                },
                            )
                            return manifest
            self.db.add_run_event(
                run_id, "warning", "planning_manifest_conflict",
                "规划执行索引存在事件归属或分段边界冲突",
                stage="planning", metadata={
                    "attempt": attempt + 1, "issues": last_issues,
                },
            )
            if attempt < 2:
                self.db.add_run_event(
                    run_id, "info", "planning_manifest_repair",
                    "正在自动修正规划执行索引，正式大纲保持不变",
                    stage="planning", metadata={
                        "repair_attempt": attempt + 1, "issues": last_issues,
                    },
                )

        failed = {
            "version": 2, "status": "failed", **hashes,
            "beats": last_body.get("beats", []) if isinstance(last_body, dict) else [],
            "segments": last_body.get("segments", []) if isinstance(last_body, dict) else [],
            "semantic_receipt": {}, "repair_attempts": 2,
            "issues": last_issues,
        }
        atomic_write(index_path, json.dumps(failed, ensure_ascii=False, indent=2))
        self.db.add_run_event(
            run_id, "error", "planning_manifest_failed",
            "规划执行索引仍有事件归属或分段边界问题，已在正文开始前停止",
            stage="planning", metadata={"issues": last_issues},
        )
        raise ValueError("规划执行索引未通过结构与语义检查，尚未生成正文")

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
                    if evidence_audit.get("final_review_recovery"):
                        report["final_review_recovery"] = evidence_audit["final_review_recovery"]
                elif project.mode == "short" and len(final_input) > 6000:
                    final_review, evidence_audit = await self._full_manuscript_review(
                        run_id, run_path, project, constraints, final_input, review,
                        suffix=f"-{attempt + 1}" if attempt else "",
                        analysis=current_analysis,
                    )
                    report["final_review_evidence"] = evidence_audit
                    if evidence_audit.get("final_review_recovery"):
                        report["final_review_recovery"] = evidence_audit["final_review_recovery"]
                else:
                    ledger = issue_ledger(review.get("issues", []))
                    final_input = (
                        quality_profile_prompt(active_profile)
                        + self._causal_chain_review_checks(constraints)
                        + "SINGLE-REQUEST COMPLETE MANUSCRIPT REVIEW. Return strict quality-review "
                        "JSON plus reconciliations. Every prior issue must appear exactly once with "
                        "issue_id, status (resolved, partially_resolved, unresolved, uncertain, or "
                        "preserved), severity, and current-manuscript evidence. Omission never means "
                        "resolved. Do not rewrite the manuscript.\n\n"
                        f"INITIAL ISSUE LEDGER:\n{json.dumps(ledger, ensure_ascii=False)}\n\n"
                        f"COMPLETE MANUSCRIPT:\n{final_input}"
                    )
                    raw_final_review, final_payload = await self._final_review_json(
                        run_id, run_path, project, constraints, final_input,
                        suffix=f"-{attempt + 1}" if attempt else "",
                    )
                    final_review = self._review_for_project(
                        final_payload, project,
                        getattr(raw_final_review, "receipt", {}),
                    )
                    prior_issue_ids = [item["issue_id"] for item in ledger]
                    prior_issue_id_set = set(prior_issue_ids)
                    raw_reconciliations = final_payload.get("reconciliations", [])
                    reconciliations = (
                        raw_reconciliations
                        if (
                            isinstance(raw_reconciliations, list)
                            and all(isinstance(item, dict) for item in raw_reconciliations)
                        )
                        else [
                            item for item in final_payload.get("issues", [])
                            if isinstance(item, dict)
                            and item.get("issue_id") in prior_issue_id_set
                        ]
                    )
                    manuscript_sha256 = hashlib.sha256(
                        review_text.encode("utf-8")
                    ).hexdigest()
                    evidence_audit = {
                        "coverage": 1.0, "window_count": 1, "reviewed_windows": 1,
                        "evidence_count": 1,
                        "prior_issue_ids": prior_issue_ids,
                        "prior_issues": ledger,
                        "reconciliations": reconciliations,
                        "windows": [{
                            "index": 1, "start": 0, "end": len(review_text),
                            "summary": "single-request complete review",
                            "manuscript_sha256": manuscript_sha256,
                            "window_sha256": manuscript_sha256,
                        }],
                        "adjudication_receipt": getattr(raw_final_review, "receipt", {}),
                        "review_mode": "full",
                    }
                    final_review, gate_reasons = apply_evidence_gate(
                        final_review, evidence_audit,
                    )
                    final_review = reconcile_review_issues(
                        final_review, ledger, reconciliations,
                        reviewed_at=datetime.now(timezone.utc).isoformat(),
                    )
                    evidence_audit["gate_reasons"] = gate_reasons
                    if final_payload.get("_recovery_mode"):
                        evidence_audit["final_review_recovery"] = {
                            "attempted": True,
                            "succeeded": True,
                            "mode": "compact_recovery",
                            "count": 1,
                            "message": "终审原始报告不完整，系统已用精简格式恢复报告",
                        }
                        report["final_review_recovery"] = evidence_audit[
                            "final_review_recovery"
                        ]
                report["final_review_evidence"] = evidence_audit
                if attempt == 0:
                    # Full and direct terminal reviews already reconcile every
                    # prior issue. Re-appending the initial ledger here would
                    # manufacture duplicate identities in incremental baselines.
                    baseline_review = final_review
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
                if isinstance(exc, FinalReviewJSONError):
                    report["status"] = "final_review_incomplete"
                    report["failure_reasons"] = [str(exc)]
                    report["failure_detail"] = exc.detail
                    report["final_review_recovery"] = {
                        "attempted": True, "succeeded": False,
                        "mode": "compact_recovery",
                        "message": "终审原始返回不完整，精简报告恢复也未完成；最佳稿已保留",
                    }
                    report_status = "final_review_incomplete"
                    event_type = "final_review_model_failed"
                    message = str(exc)
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
        with QUALITY_CHECKPOINT_LOCK:
            atomic_write(run_path / "outputs" / "best-candidate.md", manuscript)
            digest = hashlib.sha256(manuscript.encode("utf-8")).hexdigest()
            narrative_integrity = None
            for path in sorted(
                (run_path / "outputs").glob("polish-integrity*.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            ):
                try:
                    candidate = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    continue
                if (
                    candidate.get("status") == "passed"
                    and candidate.get("draft_sha256") == digest
                ):
                    narrative_integrity = {
                        "path": f"outputs/{path.name}",
                        "sha256": hashlib.sha256(
                            path.read_bytes(),
                        ).hexdigest(),
                    }
                    break
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
                **({"narrative_integrity": narrative_integrity}
                   if narrative_integrity else {}),
            })

    async def _final_review_json(
        self, run_id: str, run_path: Path, project: Project, constraints: str,
        prompt: str, suffix: str, recovery_kind: str = "review",
    ) -> tuple[str, dict]:
        stage_error: RuntimeError | None = None
        try:
            raw = await self._stage(
                run_id, run_path, project, "final_review", constraints, prompt,
                suffix=suffix, allow_tools=False,
            )
        except RuntimeError as exc:
            if not str(exc).startswith("final_review model returned empty output"):
                raise
            stage_error = exc
            raw = ""
        try:
            if stage_error is not None:
                raise stage_error
            return raw, self._json_object(raw)
        except (json.JSONDecodeError, ValueError, RuntimeError) as primary_error:
            binding = self.db.get_role_binding("final_review") or {}
            configured_fallback = bool(
                binding.get("fallback_provider_id") and binding.get("fallback_model_id")
                and hasattr(self.gateway, "complete_configured_fallback")
            )
            fallback_error: Exception | None = None
            if configured_fallback:
                self.db.add_run_event(
                    run_id, "warning", "final_review_json_fallback",
                    "终审模型返回内容不完整，正在用备用模型重做当前检查",
                    stage="final_review", metadata={
                        "suffix": suffix, "error": str(primary_error)[:300],
                    },
                )
                try:
                    fallback_raw = await self._stage(
                        run_id, run_path, project, "final_review", constraints, prompt,
                        suffix=f"{suffix}-json-fallback", allow_tools=False,
                        prefer_configured_fallback=True,
                    )
                    return fallback_raw, self._json_object(fallback_raw)
                except (json.JSONDecodeError, ValueError, RuntimeError) as exc:
                    fallback_error = exc

            compact_prompt = self._final_review_compact_prompt(prompt, recovery_kind)
            self.db.add_run_event(
                run_id, "warning", "final_review_compact_recovery_started",
                "终审报告不完整，正在改用精简格式重新检查",
                stage="final_review", metadata={
                    "suffix": suffix, "kind": recovery_kind,
                    "primary_error": str(primary_error)[:300],
                    "fallback_error": str(fallback_error)[:300] if fallback_error else None,
                },
            )
            try:
                compact_raw = await self._stage(
                    run_id, run_path, project, "final_review", constraints,
                    compact_prompt, suffix=f"{suffix}-compact-recovery", allow_tools=False,
                )
                compact_payload = self._json_object(compact_raw)
            except (json.JSONDecodeError, ValueError, RuntimeError) as compact_error:
                detail = self._final_review_error_detail(
                    primary_error, fallback_error, compact_error, suffix, recovery_kind,
                )
                raise FinalReviewJSONError(
                    "终审模型返回内容不完整，精简报告恢复也未完成；已保留最佳稿",
                    detail,
                ) from compact_error
            if isinstance(compact_raw, StageText):
                compact_raw.receipt = {
                    **getattr(compact_raw, "receipt", {}),
                    "recovery_mode": "compact_recovery",
                }
            self.db.add_run_event(
                run_id, "warning", "final_review_compact_recovery",
                "终审原始报告不完整，系统已用精简格式恢复报告",
                stage="final_review", metadata={
                    "suffix": suffix, "kind": recovery_kind,
                },
            )
            compact_payload["_recovery_mode"] = "compact_recovery"
            return compact_raw, compact_payload

    @staticmethod
    def _final_review_compact_prompt(prompt: str, kind: str) -> str:
        if kind == "window":
            return (
                "终审窗口精简恢复。请重新阅读当前窗口，只返回一个 JSON 对象，不要解释。"
                "只允许两个字段：summary（不超过240字的窗口摘要）和 issues（最多4条，"
                "每条只含 category、severity、evidence、location、action）。"
                "不要返回 events、character_states、timeline、promises，不要评分，不要复述全文。\n\n"
                + prompt
            )
        if kind == "detail":
            return (
                "终审详细事件和伏笔单独分析。请只返回一个 JSON 对象，字段为 events、promises、"
                "character_states、timeline；每个数组最多8条，每条只保留必要的短句。"
                "不要评分，不要重写正文，不要返回其它字段。\n\n" + prompt
            )
        return (
            "终审结果精简恢复。请只返回一个 JSON 对象，必须包含 dimensions（commercial、story、"
            "prose，0-100）、hard_fail、decision（pass、revise 或 rewrite）和 issues（最多4条，"
            "每条只含 category、severity、evidence、action），可以省略其它字段。不要解释。\n\n"
            + prompt
        )

    @staticmethod
    def _bound_final_review_window_item(item: dict) -> dict:
        """Keep evidence small enough for the cross-window adjudication request."""
        result = dict(item)
        summary = str(result.get("summary") or "").strip()
        result["summary"] = summary[:240]
        for key in ("events", "character_states", "timeline", "promises"):
            result[key] = []
        issues = result.get("issues")
        bounded_issues = []
        for issue in issues[:4] if isinstance(issues, list) else []:
            if not isinstance(issue, dict):
                continue
            bounded_issues.append({
                **issue,
                "evidence": str(issue.get("evidence") or "")[:160],
                "location": str(issue.get("location") or "")[:120],
                "action": str(issue.get("action") or "")[:160],
            })
        result["issues"] = bounded_issues
        return result

    @staticmethod
    def _final_review_detail_plan(
        project: Project, analysis: dict | None, initial_review: dict,
        windows: list[dict],
    ) -> tuple[set[int], str]:
        all_windows = {int(window["index"]) for window in windows}
        if project.metadata.get("final_review_detail_analysis"):
            return all_windows, "已按作品设置单独复核详细事件、人物状态、时间线和伏笔"

        issue_text = json.dumps(
            initial_review.get("issues", []), ensure_ascii=False,
        ).lower()
        issue_markers = (
            "logic_continuity", "timeline", "character_state", "knowledge_state",
            "causal", "promise", "payoff", "setup", "foreshadow",
            "前后矛盾", "连续性", "时间线", "人物状态", "知情", "因果",
            "伏笔", "承诺", "兑现",
        )
        if any(marker in issue_text for marker in issue_markers):
            return all_windows, "已有终审问题涉及跨段关系，已单独复核详细事件和伏笔"

        selected: set[int] = set()
        ledger = (analysis or {}).get("narrative_ledger", {})
        for item in ledger.get("important_uncertainties", []):
            position = item.get("start") if isinstance(item, dict) else None
            if not isinstance(position, int):
                continue
            for window in windows:
                if int(window["start"]) <= position < int(window["end"]):
                    selected.add(int(window["index"]))
        if selected:
            return selected, "本地检查发现需要确认的伏笔或承诺"
        return set(), "未发现需要单独复核的跨段伏笔、人物状态或时间线问题"

    @staticmethod
    def _final_review_error_detail(
        primary: Exception, fallback: Exception | None, compact: Exception,
        suffix: str, kind: str,
    ) -> dict:
        def error_info(error: Exception | None) -> dict | None:
            if error is None:
                return None
            info = {"type": type(error).__name__, "message": str(error)[:500]}
            if isinstance(error, json.JSONDecodeError):
                info.update({"line": error.lineno, "column": error.colno})
            return info
        return {
            "kind": "malformed_json", "stage": "final_review", "suffix": suffix,
            "recovery_kind": kind, "primary": error_info(primary),
            "fallback": error_info(fallback), "compact": error_info(compact),
        }

    def _final_review_adjudication_token_limit(self) -> int:
        context_window = self._provider_context_window("final_review", False)
        effective_window = context_window or 32_768
        return max(4_000, int(effective_window * 0.45))

    @staticmethod
    def _coalesce_hierarchical_issue_evidence(items: list[dict]) -> list[dict]:
        """Keep one stable issue identity while retaining every window occurrence."""
        result = [{**item, "issues": []} for item in items]
        merged_by_id: dict[str, dict] = {}
        first_item_by_id: dict[str, int] = {}
        for item_index, item in enumerate(items):
            item_windows = (
                item.get("covered_windows")
                if isinstance(item.get("covered_windows"), list)
                else [item.get("window")]
            )
            item_windows = [
                int(window) for window in item_windows if isinstance(window, int)
            ]
            for issue in item.get("issues", []):
                if not isinstance(issue, dict) or not issue.get("issue_id"):
                    continue
                issue_id = str(issue["issue_id"])
                merged = merged_by_id.setdefault(issue_id, {
                    **issue,
                    "evidence_records": [],
                })
                first_item_by_id.setdefault(issue_id, item_index)
                records = issue.get("evidence_records")
                if not isinstance(records, list) or not records:
                    records = [{
                        "evidence": issue.get("evidence"),
                        "location": issue.get("location"),
                        "action": issue.get("action"),
                        "severity": issue.get("severity"),
                        "covered_windows": item_windows,
                    }]
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    normalized = {
                        "evidence": str(record.get("evidence") or ""),
                        "location": str(record.get("location") or ""),
                        "action": str(record.get("action") or issue.get("action") or ""),
                        "severity": str(
                            record.get("severity") or issue.get("severity") or ""
                        ),
                        "covered_windows": sorted({
                            int(window)
                            for window in (
                                record.get("covered_windows")
                                if isinstance(record.get("covered_windows"), list)
                                else item_windows
                            )
                            if isinstance(window, int)
                        }),
                    }
                    if normalized not in merged["evidence_records"]:
                        merged["evidence_records"].append(normalized)
        for issue_id, issue in merged_by_id.items():
            item_index = first_item_by_id[issue_id]
            result[item_index]["issues"].append(issue)
            evidence_windows = {
                window
                for record in issue["evidence_records"]
                for window in record["covered_windows"]
            }
            if evidence_windows and isinstance(result[item_index].get("covered_windows"), list):
                result[item_index]["covered_windows"] = sorted({
                    *result[item_index]["covered_windows"], *evidence_windows,
                })
        return result

    async def _hierarchical_final_review_evidence(
        self,
        run_id: str,
        run_path: Path,
        project: Project,
        constraints: str,
        evidence: list[dict],
        suffix: str,
    ) -> tuple[list[dict], dict]:
        token_limit = self._final_review_adjudication_token_limit()
        original_windows = sorted(int(item["window"]) for item in evidence)
        current = [
            {
                **item,
                "issues": issue_ledger(
                    item.get("issues", []) if isinstance(item.get("issues"), list) else [],
                    source=f"final-review-window-{item.get('window', 'unknown')}",
                ),
            }
            for item in evidence
        ]
        levels = []
        for level in range(1, 6):
            current_tokens = estimate_input_tokens(json.dumps(current, ensure_ascii=False))
            if current_tokens <= token_limit:
                current = self._coalesce_hierarchical_issue_evidence(current)
                current_tokens = estimate_input_tokens(json.dumps(current, ensure_ascii=False))
                return current, {
                    "performed": bool(levels),
                    "token_limit": token_limit,
                    "original_evidence_tokens": estimate_input_tokens(
                        json.dumps(evidence, ensure_ascii=False)
                    ),
                    "final_evidence_tokens": current_tokens,
                    "covered_windows": original_windows,
                    "levels": levels,
                }
            batches = review_evidence_batches(
                current, token_limit=max(512, int(token_limit * 0.75)), overlap=1,
            )
            reduced = []
            for batch_index, batch in enumerate(batches, 1):
                covered_windows = sorted({
                    int(window)
                    for item in batch
                    for window in (
                        item.get("covered_windows")
                        if isinstance(item.get("covered_windows"), list)
                        else [item.get("window")]
                    )
                    if isinstance(window, int)
                })
                source_json = json.dumps(
                    batch, ensure_ascii=False, separators=(",", ":"),
                )
                source_sha256 = hashlib.sha256(source_json.encode("utf-8")).hexdigest()
                source_issues_by_id: dict[str, dict] = {}
                for batch_item in batch:
                    issue_windows = (
                        batch_item.get("covered_windows")
                        if isinstance(batch_item.get("covered_windows"), list)
                        else [batch_item.get("window")]
                    )
                    issue_windows = [
                        int(window) for window in issue_windows
                        if isinstance(window, int)
                    ]
                    for issue in batch_item.get("issues", []):
                        if not isinstance(issue, dict) or not issue.get("issue_id"):
                            continue
                        issue_id = str(issue["issue_id"])
                        merged_issue = source_issues_by_id.setdefault(issue_id, {
                            **issue,
                            "evidence_records": [],
                        })
                        records = issue.get("evidence_records")
                        if not isinstance(records, list) or not records:
                            records = [{
                                "evidence": str(issue.get("evidence") or ""),
                                "location": str(issue.get("location") or ""),
                                "action": str(issue.get("action") or ""),
                                "severity": str(issue.get("severity") or ""),
                                "covered_windows": issue_windows,
                            }]
                        for record in records:
                            if not isinstance(record, dict):
                                continue
                            normalized_record = {
                                "evidence": str(record.get("evidence") or ""),
                                "location": str(record.get("location") or ""),
                                "action": str(record.get("action") or issue.get("action") or ""),
                                "severity": str(
                                    record.get("severity") or issue.get("severity") or ""
                                ),
                                "covered_windows": sorted({
                                    int(window)
                                    for window in (
                                        record.get("covered_windows")
                                        if isinstance(record.get("covered_windows"), list)
                                        else issue_windows
                                    )
                                    if isinstance(window, int)
                                }),
                            }
                            if normalized_record not in merged_issue["evidence_records"]:
                                merged_issue["evidence_records"].append(normalized_record)
                source_issues = list(source_issues_by_id.values())
                source_issue_ids = [str(issue["issue_id"]) for issue in source_issues]
                regional_prompt = (
                    "REGIONAL EVIDENCE REDUCTION. Do not score and do not rewrite. Preserve every "
                    "covered window and reconcile cross-window timeline, character/knowledge state, "
                    "relationships, causality, setup/payoff, and ending obligations. Return one JSON "
                    "object with summary (under 400 Chinese characters), issues (at most 4 new "
                    "cross-window issues), covered_windows, source_sha256, and source_issue_ids. "
                    "Echo the exact manifest values to prove this complete source batch was used; "
                    "the runtime carries every source issue losslessly. Do not resolve conflicts "
                    "between evidence_records; report them for global adjudication.\n\n"
                    f"LEVEL {level} BATCH {batch_index}/{len(batches)}\n"
                    f"COVERED WINDOWS: {json.dumps(covered_windows)}\n"
                    f"SOURCE SHA256: {source_sha256}\n"
                    f"SOURCE ISSUE IDS: {json.dumps(source_issue_ids)}\n"
                    f"ORDERED EVIDENCE:\n{source_json}"
                )
                raw, item = await self._final_review_json(
                    run_id, run_path, project, constraints, regional_prompt,
                    suffix=f"{suffix}-hierarchy-{level}-{batch_index}",
                    recovery_kind="window",
                )
                summary = item.get("summary")
                if not isinstance(summary, str) or not summary.strip():
                    raise ValueError("Hierarchical final review evidence has no summary")
                if item.get("covered_windows") != covered_windows:
                    raise ValueError("Hierarchical final review returned stale window coverage")
                if item.get("source_sha256") != source_sha256:
                    raise ValueError("Hierarchical final review returned a stale source hash")
                if item.get("source_issue_ids") != source_issue_ids:
                    raise ValueError("Hierarchical final review omitted source issue identities")
                new_issues = issue_ledger(
                    self._bound_final_review_window_item(item).get("issues", []),
                    source=f"final-review-hierarchy-{level}-{batch_index}",
                )
                carried_issue_ids = set(source_issue_ids)
                reduced.append({
                    "level": level,
                    "batch": batch_index,
                    "covered_windows": covered_windows,
                    "summary": summary.strip()[:400],
                    "issues": [
                        *source_issues,
                        *(issue for issue in new_issues
                          if str(issue["issue_id"]) not in carried_issue_ids),
                    ],
                    "source_issue_ids": source_issue_ids,
                    "source_sha256": source_sha256,
                    "receipt": getattr(raw, "receipt", {}),
                })
            reduced = self._coalesce_hierarchical_issue_evidence(reduced)
            covered = sorted({
                window for item in reduced for window in item["covered_windows"]
            })
            if covered != original_windows:
                raise ValueError("Hierarchical final review omitted manuscript windows")
            reduced_tokens = estimate_input_tokens(json.dumps(reduced, ensure_ascii=False))
            levels.append({
                "level": level,
                "input_items": len(current),
                "batches": len(batches),
                "input_tokens": current_tokens,
                "output_tokens": reduced_tokens,
                "covered_windows": covered,
            })
            if reduced_tokens >= current_tokens and len(reduced) >= len(current):
                raise ValueError("Hierarchical final review could not reduce complete evidence")
            current = reduced
        raise ValueError("Hierarchical final review exceeded the safe reduction depth")

    async def _full_manuscript_review(
        self, run_id: str, run_path: Path, project: Project, constraints: str,
        manuscript: str, initial_review: dict, suffix: str = "",
        analysis: dict | None = None,
    ) -> tuple[dict, dict]:
        constraints = self._constraints_with_platform_rules(project, constraints)
        causal_checks = self._causal_chain_review_checks(constraints)
        windows = review_windows(manuscript)
        manuscript_sha256 = hashlib.sha256(manuscript.encode("utf-8")).hexdigest()
        ledger = issue_ledger(initial_review.get("issues", []))
        evidence = []
        recovery_modes = []
        previous_summary = ""
        detail_windows, detail_message = self._final_review_detail_plan(
            project, analysis, initial_review, windows,
        )
        for window in windows:
            prompt = (
                "FULL MANUSCRIPT WINDOW SUMMARY. Do not score or rewrite. Return one JSON object with "
                "summary and issues only. Keep summary under 240 Chinese characters. Return at most 4 "
                "issues; each issue must include "
                "category, severity, evidence, location, and action, with each text under 160 characters. "
                "Only record changes and evidence; do not retell the window.\n\n"
                f"WINDOW {window['index']}/{len(windows)} "
                f"CHARACTERS {window['start']}-{window['end']}\n"
                f"PREVIOUS WINDOW SUMMARY:\n{previous_summary or 'None'}\n\n"
                f"INITIAL ISSUE LEDGER:\n{json.dumps(ledger, ensure_ascii=False)}\n\n"
                f"{causal_checks}"
                f"MANUSCRIPT WINDOW:\n{window['text']}"
            )
            raw, item = await self._final_review_json(
                run_id, run_path, project, constraints, prompt,
                suffix=f"{suffix}-window-{window['index']}", recovery_kind="window",
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
            item["manuscript_sha256"] = manuscript_sha256
            item["window_sha256"] = hashlib.sha256(
                window["text"].encode("utf-8")
            ).hexdigest()
            item["receipt"] = getattr(raw, "receipt", {})
            item = self._bound_final_review_window_item(item)
            item["issues"] = issue_ledger(
                item.get("issues", []), source=f"final-review-window-{window['index']}",
            )
            if item.get("_recovery_mode"):
                item["recovery_mode"] = item.pop("_recovery_mode")
            if item.get("recovery_mode"):
                recovery_modes.append(str(item["recovery_mode"]))
            if window["index"] in detail_windows:
                detail_prompt = self._final_review_compact_prompt(
                    f"WINDOW {window['index']}/{len(windows)}\n{window['text']}", "detail",
                )
                detail_raw, detail = await self._final_review_json(
                    run_id, run_path, project, constraints, detail_prompt,
                    suffix=f"{suffix}-window-{window['index']}-detail", recovery_kind="detail",
                )
                for key in ("events", "promises", "character_states", "timeline"):
                    if isinstance(detail.get(key), list):
                        item[key] = detail[key][:8]
                item["detail_receipt"] = getattr(detail_raw, "receipt", {})
            evidence.append(item)
            previous_summary = item["summary"]

        adjudication_evidence, adjudication_hierarchy = (
            await self._hierarchical_final_review_evidence(
                run_id, run_path, project, constraints, evidence, suffix,
            )
        )
        adjudication_prompt = (
            quality_profile_prompt(profile_for_project(project))
            +
            "FULL MANUSCRIPT FINAL ADJUDICATION. Use the ordered window evidence as a global story "
            "map and perform cross-window checks for timeline, character state and knowledge, causal "
            "authority/evidence, relationship transitions, setup/payoff, and premise follow-through. "
            "Return strict quality-review JSON plus reconciliations. Each initial issue must appear once "
            "with issue_id, status (resolved, partially_resolved, unresolved, uncertain, or preserved), severity, "
            "and concrete evidence. Omission never means resolved. Do not rewrite the manuscript.\n\n"
            "When one stable issue has multiple evidence_records, consider every occurrence. "
            "Contradictory occurrences must remain uncertain or unresolved rather than selecting one.\n\n"
            f"INITIAL ISSUE LEDGER:\n{json.dumps(ledger, ensure_ascii=False)}\n\n"
            f"{causal_checks}"
            f"ORDERED WINDOW EVIDENCE:\n{json.dumps(adjudication_evidence, ensure_ascii=False)}"
        )
        raw_final, payload = await self._final_review_json(
            run_id, run_path, project, constraints, adjudication_prompt,
            suffix=f"{suffix}-adjudication",
        )
        if payload.get("_recovery_mode"):
            recovery_modes.append(str(payload["_recovery_mode"]))
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
            "prior_issues": ledger,
            "reconciliations": reconciliations,
            "windows": evidence,
            "adjudication_receipt": getattr(raw_final, "receipt", {}),
            "review_mode": "full",
            "detail_mode": "separate" if detail_windows else "compact",
            "detail_analysis": {
                "performed": bool(detail_windows),
                "window_count": len(detail_windows),
                "message": (
                    f"{detail_message}，已单独复核 {len(detail_windows)} 个正文窗口"
                    if detail_windows else detail_message
                ),
            },
            "adjudication_hierarchy": adjudication_hierarchy,
        }
        if recovery_modes:
            audit["final_review_recovery"] = {
                "attempted": True,
                "succeeded": True,
                "mode": "compact_recovery",
                "count": len(recovery_modes),
                "message": "终审原始报告不完整，系统已用精简格式恢复报告",
            }
        if reconciliation_summary is not None:
            audit["reconciliation_summary"] = reconciliation_summary
        review, gate_reasons = apply_evidence_gate(review, audit)
        review = reconcile_review_issues(
            review,
            ledger,
            reconciliations,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )
        audit["gate_reasons"] = gate_reasons
        audit["reconciliation_counts"] = {
            status: sum(item.get("status") == status for item in audit["reconciliations"])
            for status in (
                "resolved", "partially_resolved", "unresolved", "uncertain", "preserved",
            )
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
                analysis=analysis,
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
                analysis=analysis,
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
                analysis=analysis,
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
                "Return JSON with summary and issues only.\n\n"
                f"SELECTION REASONS:\n{json.dumps(scope['reasons'].get(str(window['index']), []), ensure_ascii=False)}\n\n"
                f"BASELINE EVIDENCE:\n{json.dumps(baseline_by_index.get(window['index'], {}), ensure_ascii=False)}\n\n"
                f"CHANGES:\n{json.dumps(changes, ensure_ascii=False)}\n\n"
                f"CURRENT WINDOW:\n{window['text']}"
            )
            raw, item = await self._final_review_json(
                run_id, run_path, project, constraints, prompt,
                suffix=f"{suffix}-incremental-window-{window['index']}",
                recovery_kind="window",
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
            "reconciliations. Every reconciliation status must be exactly resolved, "
            "partially_resolved, unresolved, uncertain, or preserved. "
            "Set request_full_review=true if evidence is insufficient.\n\n"
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
                analysis=analysis,
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
                analysis=analysis,
            )
            audit.update({"review_mode": "full_fallback", "fallback_reasons": gate_reasons})
            return full_review, audit
        review = reconcile_review_issues(
            review,
            ledger,
            payload.get("reconciliations", []),
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )
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
    def _short_plan_segments(cls, plan: str, count: int) -> list[str]:
        if count == 1:
            return [plan.strip()] if plan.strip() else []
        headings = cls._short_plan_headings(plan)
        by_number: dict[int, str] = {}
        for position, (match, number) in enumerate(headings):
            if number is None or not 1 <= number <= count:
                continue
            level = len(match.group("marks"))
            end = len(plan)
            for following, following_number in headings[position + 1:]:
                if (following_number is not None
                        or len(following.group("marks")) <= level):
                    end = following.start()
                    break
            by_number.setdefault(number, plan[match.start():end].strip())
        return [by_number[number] for number in range(1, count + 1) if number in by_number]

    @staticmethod
    def _mask_nonsemantic_markdown(text: str) -> str:
        """Mask comments and fenced examples while preserving source offsets."""
        characters = list(str(text or ""))

        def mask(start: int, end: int) -> None:
            for index in range(start, end):
                if characters[index] not in "\r\n":
                    characters[index] = " "

        for comment in re.finditer(r"<!--.*?(?:-->|\Z)", text, flags=re.DOTALL):
            mask(comment.start(), comment.end())

        visible = "".join(characters)
        fence_character = ""
        fence_length = 0
        offset = 0
        for line in visible.splitlines(keepends=True):
            fence = re.match(r"^[ ]{0,3}(?P<mark>`{3,}|~{3,})", line)
            if fence_character:
                mask(offset, offset + len(line))
                if (fence and fence.group("mark")[0] == fence_character
                        and len(fence.group("mark")) >= fence_length):
                    fence_character = ""
                    fence_length = 0
            elif fence:
                fence_character = fence.group("mark")[0]
                fence_length = len(fence.group("mark"))
                mask(offset, offset + len(line))
            offset += len(line)
        return "".join(characters)

    @classmethod
    def _short_plan_headings(cls, plan: str) -> list[tuple[re.Match, int | None]]:
        comparison = cls._short_plan_comparison_view(plan)
        return [
            (match, parse_segment_number(match.group("title"), allow_scene=False))
            for match in re.finditer(
                r"(?m)^[ ]{0,3}(?P<marks>#{1,6})[ \t]*(?P<title>\S.*)$",
                comparison,
            )
        ]

    @classmethod
    def _short_plan_comparison_view(cls, text: str) -> str:
        """Normalize width for labels and IDs while preserving source offsets."""
        result = []
        for character in str(text or ""):
            normalized = unicodedata.normalize("NFKC", character)
            result.append(normalized if len(normalized) == 1 else character)
        return cls._mask_nonsemantic_markdown("".join(result))

    @classmethod
    def _short_plan_field(cls, segment: str, field: str) -> str:
        aliases = cls.SHORT_PLAN_FIELD_ALIASES[field]

        def flexible(label: str) -> str:
            return r"[ \t]*".join(re.escape(character) for character in label)

        labels = "|".join(flexible(label) for label in aliases)
        all_labels = "|".join(
            flexible(label)
            for values in cls.SHORT_PLAN_FIELD_ALIASES.values()
            for label in values
        )
        wrapper = r"(?:\*{1,2}|_{1,2}|`)?"
        prefix = rf"^[ \t]*(?:[-+*][ \t]+)?(?:#{{1,6}}[ \t]*)?{wrapper}[ \t]*"
        suffix = rf"[ \t]*{wrapper}[ \t]*[：:][ \t]*{wrapper}[ \t]*"
        comparison = cls._short_plan_comparison_view(segment)
        match = re.search(
            rf"(?ims){prefix}(?:{labels}){suffix}(?P<value>.*?)"
            rf"(?={prefix}(?:{all_labels}){suffix}|^[ \t]*#{{1,6}}(?:[ \t]+|$)|\Z)",
            comparison,
        )
        if not match:
            return ""
        start, end = match.span("value")
        return segment[start:end].strip()

    @classmethod
    def _short_plan_issues(cls, project: Project, state: dict, plan: str,
                           count: int) -> list[str]:
        issues = []
        if SHORT_CAUSAL_CHAIN_START in plan or SHORT_CAUSAL_CHAIN_END in plan:
            issues.append("规划稿附带的因果链 JSON 格式不完整")
        conflicts = detect_canon_conflicts(project, state, plan)
        if conflicts:
            labels = "、".join(
                f"{item['label']}（{item['current_value']} / {item['candidate_value']}）"
                for item in conflicts
            )
            issues.append(f"人物或地点与正式设定不一致：{labels}")
        if count == 1:
            return issues
        segments = cls._short_plan_segments(plan, count)
        heading_numbers = [
            number for _match, number in cls._short_plan_headings(plan)
            if number is not None
        ]
        if heading_numbers and heading_numbers != list(range(1, count + 1)):
            issues.append(f"规划稿分段标题必须恰好按第 1 至第 {count} 段各出现一次")
        if len(segments) != count:
            issues.append(f"规划稿需要明确列出第 1 至第 {count} 段各自负责的事件")
        else:
            if any(len(re.sub(r"\s+", "", segment)) < 80 for segment in segments):
                issues.append("有分段没有写清本段事件、结果和交接问题")
            missing_handoffs = []
            for index, segment in enumerate(segments, 1):
                if any(
                    not cls._short_plan_field(segment, field)
                    for field in cls.SHORT_PLAN_FIELD_ALIASES
                ):
                    missing_handoffs.append(index)
            if missing_handoffs:
                joined = "、".join(map(str, missing_handoffs))
                issues.append(
                    f"第 {joined} 段缺少事件ID、大纲依据、段首承接、本段事件或段末交接，"
                    "无法确认剧情分工与前后衔接"
                )
        formal_outline = state.get("outline") or {}
        outline = str(formal_outline.get("content") or "")
        event_map = (
            outline_events(outline)
            if outline.strip()
            else formal_outline.get("events") or []
        )
        required_events = narrative_outline_events(event_map)
        if event_map and len(segments) == count:
            valid = {str(item["id"]).upper() for item in event_map}
            claimed = [cls._short_plan_event_ids(segment) for segment in segments]
            flattened = [event_id for group in claimed for event_id in group]
            invalid = sorted(set(flattened) - valid)
            if invalid:
                issues.append(f"规划稿使用了不存在的事件 ID：{'、'.join(invalid)}")
        if required_events and len(segments) == count:
            required = {str(item["id"]).upper() for item in required_events}
            claimed = [cls._short_plan_event_ids(segment) for segment in segments]
            flattened = [event_id for group in claimed for event_id in group]
            missing = [
                str(item["id"]) for item in required_events
                if str(item["id"]).upper() not in flattened
            ]
            order = {
                str(item["id"]).upper(): index
                for index, item in enumerate(required_events)
            }
            labels = {
                str(item["id"]).upper(): str(item.get("label") or item["id"])
                for item in required_events
            }
            collapsed: list[tuple[int, str]] = []
            for segment_number, group in enumerate(claimed, 1):
                for event_id in group:
                    if event_id not in required:
                        continue
                    if not collapsed or event_id != collapsed[-1][1]:
                        collapsed.append((segment_number, event_id))
            if missing:
                issues.append(f"这些正式大纲事件还没有分配到写作段：{'、'.join(missing)}")
            reversal = next((
                (previous_segment, previous, current_segment, current)
                for (previous_segment, previous), (current_segment, current)
                in zip(collapsed, collapsed[1:])
                if order[current] < order[previous]
            ), None)
            if reversal:
                previous_segment, previous, current_segment, current = reversal
                issues.append(
                    "写作段认领的大纲事件顺序发生倒退："
                    f"第 {previous_segment} 段 {previous}（{labels[previous]}）之后，"
                    f"第 {current_segment} 段又认领 {current}（{labels[current]}）"
                )
        normalized = [re.sub(r"\W+", "", segment) for segment in segments]
        if any(
            SequenceMatcher(None, normalized[left], normalized[right]).ratio() >= 0.86
            for left in range(len(normalized)) for right in range(left + 1, len(normalized))
        ):
            issues.append("不同分段承担了过于相似的事件，需要重新分配")
        return issues

    @classmethod
    def _short_plan_handoff(cls, segment: str) -> str:
        return (cls._short_plan_field(segment, "handoff") or segment.strip())[-700:]

    @classmethod
    def _short_plan_event_ids(cls, segment: str) -> list[str]:
        field = cls._short_plan_field(segment, "event_id")
        comparison = cls._short_plan_comparison_view(field or segment)
        return list(dict.fromkeys(
            value.upper() for value in re.findall(
                r"EV-[0-9a-f]{8}", comparison,
                flags=re.IGNORECASE,
            )
        ))

    @classmethod
    def _draft_segment_findings(
        cls, part: str, target: int, previous_parts: list[str],
        location_catalog: dict[str, LocationRef] | None = None,
    ) -> list[dict]:
        findings: list[dict] = []
        han = effective_han_characters(part)
        minimum_han, maximum_han = target_bounds(target)
        if han > maximum_han:
            findings.append({
                "code": "overlength",
                "message": f"本段写了 {han} 个正文汉字，明显超过约 {target} 字的范围",
                "blocking": True,
                "han_characters": han,
                "target_characters": target,
            })
        if han < minimum_han and (han > 0 or not part.strip()):
            findings.append({
                "code": "underlength",
                "message": f"本段只有 {han} 个正文汉字，主要事件可能没有写完整",
                "blocking": True,
                "han_characters": han,
                "target_characters": target,
            })
        blocking = [
            item for item in analyze_prose(part).get("findings", [])
            if item.get("blocking")
        ]
        if blocking:
            findings.append({
                "code": "prose_invalid",
                "message": "正文夹带了写作说明、异常文字或重复内容",
                "blocking": True,
            })
        current_paragraphs = [
            re.sub(r"\s+", "", value)
            for value in re.split(r"\n\s*\n", part)
            if len(re.sub(r"\s+", "", value)) >= 60
        ]
        prior_paragraphs = [
            re.sub(r"\s+", "", value)
            for prior in previous_parts
            for value in re.split(r"\n\s*\n", prior)
            if len(re.sub(r"\s+", "", value)) >= 60
        ]
        if any(
            SequenceMatcher(None, current, prior).ratio() >= 0.92
            for current in current_paragraphs for prior in prior_paragraphs
        ):
            findings.append({
                "code": "duplicate_prose",
                "message": "本段重复了前面已经写过的场景或段落",
                "blocking": True,
            })
        if previous_parts and location_catalog:
            for finding in assess_scene_transition(
                previous_parts[-1], part, location_catalog,
            ):
                message = str(finding.get("message") or "")
                if finding.get("code") == "scene_transition_missing":
                    message = "本段开头换了场景，但没有交代时间、地点或人物如何过渡"
                findings.append({**finding, "message": message})
        return findings

    @classmethod
    def _draft_segment_issues(
        cls, part: str, target: int, previous_parts: list[str],
        location_catalog: dict[str, LocationRef] | None = None,
    ) -> list[str]:
        return [
            str(item["message"])
            for item in cls._draft_segment_findings(
                part, target, previous_parts, location_catalog,
            )
            if item.get("blocking")
        ]

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

    @classmethod
    def _short_checkpoint_context(
        cls, project: Project, state_revision: int, state: dict,
        constraints: str, segment_count: int,
    ) -> dict:
        outline = str(((state.get("outline") or {}).get("content")) or "")
        context = {
            "version": cls.SHORT_CHECKPOINT_VERSION,
            "project_id": project.id,
            "outline_sha256": hashlib.sha256(outline.encode("utf-8")).hexdigest(),
            "constraints_sha256": hashlib.sha256(
                constraints.encode("utf-8")
            ).hexdigest(),
            "story_state_revision": int(state_revision),
            "story_state_sha256": hashlib.sha256(json.dumps(
                state, ensure_ascii=False, sort_keys=True, default=str,
            ).encode("utf-8")).hexdigest(),
            "target_words": int(project.metadata["target_words"]),
            "segment_count": int(segment_count),
        }
        context["generation_context_sha256"] = hashlib.sha256(json.dumps(
            context, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        return context

    @staticmethod
    def _checkpoint_segment_events(
        execution_manifest: ShortExecutionManifest, draft_integrity: dict,
    ) -> dict:
        beat_by_id = {beat.beat_id: beat for beat in execution_manifest.beats}
        semantic_receipts = draft_integrity.get("semantic_segment_receipts")
        semantic_receipts = semantic_receipts if isinstance(semantic_receipts, list) else []
        segments = []
        for offset, contract in enumerate(execution_manifest.segments):
            beat_ids = list(contract.beat_ids)
            assignment = {
                "segment": contract.segment,
                "event_ids": beat_ids,
                "source_event_ids": list(dict.fromkeys(
                    beat_by_id[beat_id].source_event_id for beat_id in beat_ids
                )),
                "handoff": "；".join(item.state for item in contract.exit_state),
            }
            if offset < len(semantic_receipts) and isinstance(
                semantic_receipts[offset], dict,
            ):
                assignment["semantic_receipt"] = semantic_receipts[offset]
            segments.append(assignment)
        return {"segments": segments}

    @classmethod
    def _save_short_checkpoint(cls, outputs: Path, context: dict) -> None:
        plan = (outputs / "planning.md").read_text(encoding="utf-8")
        draft = (outputs / "draft.md").read_text(encoding="utf-8")
        execution_index = json.loads(
            (outputs / "short-execution-index.json").read_text(encoding="utf-8"),
        )
        execution_manifest = parse_execution_manifest(execution_index)
        causal_chain_text = (outputs / "short-causal-chain.json").read_text(
            encoding="utf-8",
        )
        causal_chain = json.loads(causal_chain_text)
        causal_chain_sha256 = hashlib.sha256(json.dumps(
            causal_chain, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        draft_integrity_text = (outputs / "draft-integrity.json").read_text(
            encoding="utf-8",
        )
        draft_integrity = json.loads(draft_integrity_text)
        planning_sha256 = hashlib.sha256(plan.encode("utf-8")).hexdigest()
        draft_sha256 = hashlib.sha256(draft.encode("utf-8")).hexdigest()
        manifest_sha256 = execution_manifest_sha256(execution_manifest)
        expected_execution_authority = hashlib.sha256(json.dumps({
            "project_id": context.get("project_id"),
            "state_revision": context.get("story_state_revision"),
            "constraints_sha256": context.get("constraints_sha256"),
            "outline_sha256": context.get("outline_sha256"),
            "planning_sha256": planning_sha256,
            "causal_chain_sha256": causal_chain_sha256,
            "segment_count": context.get("segment_count"),
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8",
        )).hexdigest()
        segment_events_text = json.dumps(
            cls._checkpoint_segment_events(execution_manifest, draft_integrity),
            ensure_ascii=False, indent=2,
        )
        checkpoint_issues = [
            code for code, invalid in (
                ("manifest_status", execution_manifest.status != "ready"),
                ("manifest_receipt", bool(
                    execution_manifest_receipt_binding_issues(execution_manifest)
                )),
                ("causal_chain_hash", execution_manifest.causal_chain_sha256 != causal_chain_sha256),
                ("planning_hash", execution_manifest.planning_sha256 != planning_sha256),
                ("outline_hash", execution_manifest.outline_sha256 != context.get("outline_sha256")),
                ("execution_authority", execution_manifest.authority_sha256 != expected_execution_authority),
                ("integrity_status", draft_integrity.get("status") != "passed"),
                ("integrity_manifest", draft_integrity.get("execution_manifest_sha256") != manifest_sha256),
                ("integrity_draft", draft_integrity.get("draft_sha256") != draft_sha256),
                ("integrity_plan", draft_integrity.get("plan_sha256") != planning_sha256),
                ("integrity_constraints", draft_integrity.get("base_constraints_sha256") != context.get("constraints_sha256")),
                ("integrity_story_state", draft_integrity.get("story_state_sha256") != context.get("story_state_sha256")),
            ) if invalid
        ]
        if checkpoint_issues:
            raise ValueError(
                "完整短篇检查点缺少已通过的执行索引或整篇核验："
                + "、".join(checkpoint_issues)
            )
        atomic_write(outputs / "segment-events.json", segment_events_text)
        receipt_text = json.dumps(
            execution_manifest.semantic_receipt,
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        atomic_write(outputs / "short-checkpoint.json", json.dumps({
            **context,
            "planning_sha256": planning_sha256,
            "draft_sha256": draft_sha256,
            "execution_manifest_sha256": manifest_sha256,
            "execution_manifest_receipt_sha256": hashlib.sha256(
                receipt_text.encode("utf-8"),
            ).hexdigest(),
            "causal_chain_artifact_sha256": hashlib.sha256(
                causal_chain_text.encode("utf-8"),
            ).hexdigest(),
            "segment_events_sha256": hashlib.sha256(
                segment_events_text.encode("utf-8"),
            ).hexdigest(),
            "draft_integrity_sha256": hashlib.sha256(
                draft_integrity_text.encode("utf-8"),
            ).hexdigest(),
        }, ensure_ascii=False, indent=2, sort_keys=True))

    def _find_short_checkpoint(self, project: Project, current_run_id: str,
                               segment_count: int, context: dict) -> Path | None:
        for run in self.db.list_runs(project.id):
            if run["workflow"] != "short-story":
                continue
            if (run["id"] != current_run_id
                    and run["status"] not in {"failed", "cancelled"}):
                continue
            outputs = project.path / "runs" / run["id"] / "outputs"
            plan_path = outputs / "planning.md"
            draft_path = outputs / "draft.md"
            manifest_path = outputs / "short-checkpoint.json"
            execution_index_path = outputs / "short-execution-index.json"
            draft_integrity_path = outputs / "draft-integrity.json"
            causal_chain_path = outputs / "short-causal-chain.json"
            segment_events_path = outputs / "segment-events.json"
            if (not plan_path.is_file() or not draft_path.is_file()
                    or not manifest_path.is_file()
                    or not execution_index_path.is_file()
                    or not draft_integrity_path.is_file()
                    or not causal_chain_path.is_file()
                    or not segment_events_path.is_file()):
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                plan_text = plan_path.read_text(encoding="utf-8")
                draft = draft_path.read_text(encoding="utf-8")
                execution_index = parse_execution_manifest(json.loads(
                    execution_index_path.read_text(encoding="utf-8"),
                ))
                draft_integrity_text = draft_integrity_path.read_text(encoding="utf-8")
                draft_integrity = json.loads(draft_integrity_text)
                causal_chain_text = causal_chain_path.read_text(encoding="utf-8")
                causal_chain = json.loads(causal_chain_text)
                causal_chain_sha256 = hashlib.sha256(json.dumps(
                    causal_chain, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                segment_events_text = segment_events_path.read_text(encoding="utf-8")
                segment_events = json.loads(segment_events_text)
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                continue
            planning_sha256 = hashlib.sha256(plan_text.encode("utf-8")).hexdigest()
            draft_sha256 = hashlib.sha256(draft.encode("utf-8")).hexdigest()
            execution_manifest_hash = execution_manifest_sha256(execution_index)
            receipt_text = json.dumps(
                execution_index.semantic_receipt,
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            )
            expected_execution_authority = hashlib.sha256(json.dumps({
                "project_id": context.get("project_id"),
                "state_revision": context.get("story_state_revision"),
                "constraints_sha256": context.get("constraints_sha256"),
                "outline_sha256": context.get("outline_sha256"),
                "planning_sha256": planning_sha256,
                "causal_chain_sha256": causal_chain_sha256,
                "segment_count": context.get("segment_count"),
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8",
            )).hexdigest()
            if (
                not isinstance(manifest, dict)
                or any(manifest.get(key) != value for key, value in context.items())
                or manifest.get("planning_sha256")
                != planning_sha256
                or manifest.get("draft_sha256")
                != draft_sha256
                or execution_index.status != "ready"
                or execution_manifest_receipt_binding_issues(execution_index)
                or execution_index.causal_chain_sha256 != causal_chain_sha256
                or execution_index.planning_sha256 != planning_sha256
                or execution_index.outline_sha256 != context.get("outline_sha256")
                or execution_index.authority_sha256 != expected_execution_authority
                or manifest.get("execution_manifest_sha256")
                != execution_manifest_hash
                or manifest.get("execution_manifest_receipt_sha256")
                != hashlib.sha256(receipt_text.encode("utf-8")).hexdigest()
                or draft_integrity.get("status") != "passed"
                or draft_integrity.get("draft_sha256")
                != draft_sha256
                or draft_integrity.get("execution_manifest_sha256")
                != execution_manifest_hash
                or draft_integrity.get("plan_sha256") != planning_sha256
                or draft_integrity.get("base_constraints_sha256")
                != context.get("constraints_sha256")
                or draft_integrity.get("story_state_sha256")
                != context.get("story_state_sha256")
                or segment_events != self._checkpoint_segment_events(
                    execution_index, draft_integrity,
                )
                or manifest.get("draft_integrity_sha256")
                != hashlib.sha256(
                    draft_integrity_text.encode("utf-8"),
                ).hexdigest()
                or manifest.get("causal_chain_artifact_sha256")
                != hashlib.sha256(causal_chain_text.encode("utf-8")).hexdigest()
                or manifest.get("segment_events_sha256")
                != hashlib.sha256(segment_events_text.encode("utf-8")).hexdigest()
            ):
                continue
            plan = plan_text.strip()
            if plan and len(self._split_segments(draft)) == segment_count:
                return outputs
        return None

    @classmethod
    def _restore_short_checkpoint(
        cls, source: Path, outputs: Path, context: dict,
    ) -> tuple[str, str, str, dict]:
        """Copy every validated full-checkpoint artifact into the current run."""
        plan = (source / "planning.md").read_text(encoding="utf-8")
        draft, source_artifact = cls._short_checkpoint_manuscript(
            source, int(context["segment_count"]),
        )
        integrity_source = source / "draft-integrity.json"
        if source_artifact == "best-candidate.md":
            quality_checkpoint = load_quality_checkpoint(source.parent) or {}
            integrity_ref = quality_checkpoint.get("narrative_integrity") or {}
            integrity_source = source.parent / str(integrity_ref.get("path") or "")
        atomic_write(outputs / "planning.md", plan)
        atomic_write(outputs / "draft.md", draft)
        for filename in (
            "short-causal-chain.json", "short-execution-index.json",
            "segment-events.json",
        ):
            atomic_write(
                outputs / filename,
                (source / filename).read_text(encoding="utf-8"),
            )
        atomic_write(
            outputs / "draft-integrity.json",
            integrity_source.read_text(encoding="utf-8"),
        )
        if source_artifact == "best-candidate.md":
            atomic_write(outputs / "best-candidate.md", draft)
        cls._save_short_checkpoint(outputs, context)
        causal_chain = json.loads(
            (outputs / "short-causal-chain.json").read_text(encoding="utf-8"),
        )
        return plan, draft, source_artifact, causal_chain

    def _find_short_partial_checkpoint(
        self, project: Project, current_run_id: str, state_revision: int,
        state: dict, constraints: str, segment_count: int,
    ) -> Path | None:
        for run in self.db.list_runs(project.id):
            if run["workflow"] != "short-story":
                continue
            if (run["id"] != current_run_id
                    and run["status"] not in {"failed", "cancelled"}):
                continue
            outputs = project.path / "runs" / run["id"] / "outputs"
            plan_path = outputs / "planning.md"
            chain_path = outputs / "short-causal-chain.json"
            index_path = outputs / "short-execution-index.json"
            checkpoint_root = outputs / "draft-checkpoints"
            if not (
                plan_path.is_file() and chain_path.is_file() and index_path.is_file()
                and checkpoint_root.is_dir()
                and any(checkpoint_root.glob("segment-*.json"))
            ):
                continue
            try:
                plan = plan_path.read_text(encoding="utf-8")
                chain = json.loads(chain_path.read_text(encoding="utf-8"))
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
                continue
            if legacy_execution_index_requires_rebuild(index):
                continue
            formal_outline = state.get("outline") or {}
            formal_outline_content = str(formal_outline.get("content") or "")
            formal_outline_events = (
                outline_events(formal_outline_content)
                if formal_outline_content.strip()
                else formal_outline.get("events") or []
            )
            hashes, authority_text, expected_events = self._short_execution_authority(
                project, state_revision, state, constraints, plan, chain,
                formal_outline_events, segment_count,
            )
            try:
                execution_manifest = parse_execution_manifest(index)
                execution_issues = execution_manifest_issues(
                    execution_manifest,
                    expected_event_ids=[
                        str(item.get("id") or "").strip().upper()
                        for item in expected_events
                        if str(item.get("id") or "").strip()
                    ],
                    segment_count=segment_count,
                    authority_hashes=hashes,
                )
                validate_execution_manifest_receipt(
                    execution_manifest, authority_text,
                    execution_manifest.semantic_receipt,
                )
            except (TypeError, ValueError):
                continue
            if (
                execution_manifest.status != "ready"
                or execution_issues
                or self._short_plan_issues(project, state, plan, segment_count)
                or analyze_short_causal_chain(
                    chain, int(project.metadata["target_words"]),
                )["status"] == "invalid"
            ):
                continue
            manifest_hash = execution_manifest_sha256(execution_manifest)
            manifest_segments = {
                item.segment: item for item in execution_manifest.segments
            }
            beat_by_id = {
                item.beat_id: item for item in execution_manifest.beats
            }
            segment_plans = self._short_plan_segments(plan, segment_count)
            target = math.ceil(
                int(project.metadata["target_words"]) / segment_count,
            )
            augmented_constraints = constraints + (
                "\n\n# Short Story Causal Chain\n\n"
                + compact_causal_chain(chain)
            )
            story_state_sha256 = hashlib.sha256(json.dumps(
                state, ensure_ascii=False, sort_keys=True, default=str,
            ).encode("utf-8")).hexdigest()
            location_catalog = build_location_catalog(project.path, state)
            draft_authority_hash = hashlib.sha256(json.dumps({
                "plan": plan,
                "constraints": augmented_constraints,
                "target_words": int(project.metadata["target_words"]),
                "segment_count": segment_count,
                "story_state_sha256": story_state_sha256,
                "execution_manifest_sha256": manifest_hash,
                "location_catalog": sorted(
                    (alias, ref.name, ref.root)
                    for alias, ref in location_catalog.items()
                ),
            }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            accepted_parts: list[str] = []
            for number in range(1, segment_count + 1):
                checkpoint_path = checkpoint_root / f"segment-{number:02d}.json"
                if not checkpoint_path.is_file():
                    break
                try:
                    checkpoint = json.loads(
                        checkpoint_path.read_text(encoding="utf-8"),
                    )
                    text = str(checkpoint.get("text") or "")
                    assignment = checkpoint.get("assignment") or {}
                    manifest_segment = manifest_segments[number]
                    beat_ids = list(manifest_segment.beat_ids)
                    source_event_ids = list(dict.fromkeys(
                        beat_by_id[beat_id].source_event_id for beat_id in beat_ids
                    ))
                    handoff = "；".join(
                        assertion.state for assertion in manifest_segment.exit_state
                    )
                    previous_sha = (
                        hashlib.sha256(accepted_parts[-1].encode("utf-8")).hexdigest()
                        if accepted_parts else ""
                    )
                    contract = DraftTaskContract(
                        authority_sha256=draft_authority_hash,
                        task_id=f"segment-{number:02d}", parent_task_id="", depth=0,
                        target_han=target, event_ids=tuple(source_event_ids),
                        scope="恢复检查点原子节拍",
                        entry_state="恢复检查点入口状态",
                        exit_requirement=handoff,
                        execution_manifest_sha256=manifest_hash,
                        beat_ids=tuple(beat_ids),
                        viewpoint=str(project.metadata.get("pov") or ""),
                        prohibited_future_beat_ids=(
                            manifest_segment.prohibited_future_beat_ids
                        ),
                    )
                    validate_semantic_receipt(
                        contract, text, checkpoint.get("semantic_receipt"),
                    )
                except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                    break
                if (
                    checkpoint.get("version") != 3
                    or checkpoint.get("authority_sha256") != draft_authority_hash
                    or checkpoint.get("execution_manifest_sha256") != manifest_hash
                    or checkpoint.get("previous_sha256") != previous_sha
                    or checkpoint.get("segment_plan_sha256") != hashlib.sha256(
                        segment_plans[number - 1].encode("utf-8"),
                    ).hexdigest()
                    or checkpoint.get("text_sha256") != hashlib.sha256(
                        text.encode("utf-8"),
                    ).hexdigest()
                    or assignment.get("segment") != number
                    or assignment.get("event_ids") != beat_ids
                    or assignment.get("source_event_ids") != source_event_ids
                    or assignment.get("handoff") != handoff
                    or self._draft_segment_issues(
                        text, target, accepted_parts, location_catalog,
                    )
                ):
                    break
                accepted_parts.append(text)
            if not accepted_parts:
                continue
            return outputs
        return None

    @classmethod
    def _short_checkpoint_manuscript(cls, outputs: Path,
                                     segment_count: int) -> tuple[str, str]:
        quality_checkpoint = load_quality_checkpoint(outputs.parent)
        protected_best = False
        if quality_checkpoint and quality_checkpoint.get("manuscript_path") == (
            "outputs/best-candidate.md"
        ):
            integrity_ref = quality_checkpoint.get("narrative_integrity")
            if isinstance(integrity_ref, dict):
                integrity_path = outputs.parent / str(integrity_ref.get("path") or "")
                try:
                    integrity_text = integrity_path.read_text(encoding="utf-8")
                    integrity = json.loads(integrity_text)
                except (OSError, UnicodeError, json.JSONDecodeError):
                    integrity = None
                protected_best = bool(
                    isinstance(integrity, dict)
                    and integrity.get("status") == "passed"
                    and integrity.get("draft_sha256")
                    == quality_checkpoint.get("manuscript_hash")
                    and hashlib.sha256(integrity_text.encode("utf-8")).hexdigest()
                    == integrity_ref.get("sha256")
                )
        filenames = (
            ("best-candidate.md", "draft.md")
            if protected_best else ("draft.md",)
        )
        for filename in filenames:
            path = outputs / filename
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            if len(cls._split_segments(text)) == segment_count:
                return text, filename
        raise ValueError("Short-story checkpoint has no complete manuscript")

    def _find_short_stage_output(self, project: Project, current_run_id: str,
                                 filename: str) -> Path | None:
        path = project.path / "runs" / current_run_id / "outputs" / filename
        return path if path.is_file() and path.stat().st_size else None

    @staticmethod
    def _compact_polish_prompt(*, authority_packet,
                               local_findings: list,
                               review_findings: dict | None = None) -> str:
        return (
            "普通润色精简恢复。只处理当前正文片段，不扩写片段外内容。"
            "只返回修改后的正文，不解释、不分析。\n\n"
            + render_polish_authority_packet(authority_packet, advisory={
                "local_findings": local_findings,
                "review_findings": review_findings or {"issues": []},
            })
        )

    @staticmethod
    def _polish_part_spans(text: str, parts: list[str]) -> list[tuple[int, int]]:
        spans = []
        cursor = 0
        for part in parts:
            start = text.find(part, cursor)
            if start < 0:
                start = cursor
            end = start + len(part)
            spans.append((start, end))
            cursor = end
        return spans

    @staticmethod
    def _polish_narrative_context(
        ledger: dict, segment: str, start: int, end: int,
        previous_handoff: str = "",
    ) -> dict:
        normalized_segment = segment.lower()

        def related(item: dict) -> bool:
            overlaps = int(item.get("start", -1)) < end and int(item.get("end", -1)) > start
            anchors = [str(value).lower() for value in item.get("anchors", []) if value]
            return overlaps or any(anchor in normalized_segment for anchor in anchors)

        def open_items(key: str) -> list[dict]:
            return [
                {
                    "text": str(item.get("text") or "")[:180],
                    "status": item.get("status", "unresolved"),
                }
                for item in ledger.get(key, [])
                if isinstance(item, dict)
                and item.get("status") == "unresolved"
                and related(item)
            ][:2]

        scenes = []
        for scene in ledger.get("scenes", []):
            if not isinstance(scene, dict) or not related(scene):
                continue
            scenes.append({
                "entry_state": scene.get("entry_state"),
                "exit_state": scene.get("exit_state"),
                "state_changes": [
                    str(item.get("evidence") or "")[:160]
                    for item in scene.get("state_changes", []) if isinstance(item, dict)
                ][:3],
            })
            if len(scenes) == 2:
                break
        items_by_id = {
            item.get("id"): item
            for key in ("questions", "promises", "setups", "payoffs")
            for item in ledger.get(key, [])
            if isinstance(item, dict) and item.get("id")
        }
        relations = []
        for relation in ledger.get("relations", []):
            if not isinstance(relation, dict) or not related(relation):
                continue
            source = items_by_id.get(relation.get("from_id"), {})
            target = items_by_id.get(relation.get("to_id"), {})
            relations.append({
                "关系": relation.get("kind"),
                "前文": str(source.get("text") or "")[:140],
                "本窗或后文": str(target.get("text") or relation.get("evidence") or "")[:140],
            })
            if len(relations) == 2:
                break
        return {
            "上一窗实际交接状态": previous_handoff[:300],
            "本窗未兑现问题": open_items("questions"),
            "本窗未兑现承诺": open_items("promises"),
            "本窗伏笔": open_items("setups"),
            "本窗关联的提问与兑现": relations,
            "本窗场景状态": scenes,
        }

    @staticmethod
    def _polish_exit_state(text: str) -> str:
        scenes = build_narrative_ledger(text).get("scenes", [])
        return next((
            str(scene.get("exit_state"))
            for scene in reversed(scenes)
            if isinstance(scene, dict) and scene.get("exit_state")
        ), "")

    @staticmethod
    def _raise_for_unusable_polish_output(
        text: str, source_characters: int, maximum_characters: int,
        minimum_characters: int = 0,
    ) -> None:
        receipt = getattr(text, "receipt", {})
        if receipt.get("finish_reason") == "max_tokens":
            raise RuntimeError("polish output incomplete (finish_reason=max_tokens)")
        if source_characters >= 200 and len(text.strip()) > maximum_characters:
            raise RuntimeError(
                f"polish output exceeds allowed maximum ({len(text.strip())} > "
                f"{maximum_characters})"
            )
        if (source_characters >= 200 and minimum_characters > 0
                and len(text.strip()) < minimum_characters):
            raise RuntimeError(
                f"polish output is below allowed minimum ({len(text.strip())} < "
                f"{minimum_characters})"
            )

    @staticmethod
    def _polish_input_tokens(value: object) -> int:
        receipt = getattr(value, "receipt", None)
        if isinstance(receipt, dict):
            try:
                return max(0, int(receipt.get("input_tokens", 0) or 0))
            except (TypeError, ValueError):
                return 0
        match = re.search(r"input_tokens=(\d+)", str(value))
        return int(match.group(1)) if match else 0

    async def _ordinary_polish_segment(
        self, run_id: str, run_path: Path, project: Project, constraints: str,
        source: str, full_prompt: str, compact_prompt: str, suffix: str,
        minimum_characters: int, maximum_characters: int, configured_fallback: bool,
        metadata: dict,
    ) -> tuple[str, bool, bool, bool, int]:
        consumed_input_tokens = 0

        async def request(*, prompt: str, fallback: bool, compact: bool,
                          attempt_suffix: str) -> str:
            nonlocal consumed_input_tokens
            try:
                polished = await self._stage(
                    run_id, run_path, project, "polish", constraints, prompt,
                    suffix=attempt_suffix, allow_tools=False,
                    prefer_configured_fallback=fallback,
                    output_source_characters=len(source),
                    primary_only=not fallback,
                    retry_polish_output_limit=True,
                    compact_input=compact,
                )
                consumed_input_tokens += int(
                    getattr(polished, "receipt", {}).get("input_tokens", 0) or 0
                )
                self._raise_for_unusable_polish_output(
                    polished, len(source), maximum_characters, minimum_characters,
                )
                return polished
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                consumed_input_tokens += self._polish_input_tokens(exc)
                raise

        prompt = full_prompt
        compact_used = False
        primary_transport_retried = False
        primary_error: Exception | None = None
        while True:
            try:
                polished = await request(
                    prompt=prompt, fallback=False, compact=compact_used,
                    attempt_suffix=(f"{suffix}-input-compact" if compact_used else suffix),
                )
                return polished, False, compact_used, False, consumed_input_tokens
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                kind = classify_model_failure(exc)
                if kind == "provider_rejection":
                    raise
                if kind == "input_context_overflow" and not compact_used:
                    compact_used = True
                    prompt = compact_prompt
                    self.db.add_run_event(
                        run_id, "warning", "polish_input_compact_retry",
                        "当前模型明确拒绝了过长输入，正在保留叙事权威后压缩建议重试",
                        stage="polish", metadata={
                            **metadata, "error": describe_error(exc)[:500],
                            "route": "primary",
                            "failure_class": "input_context_overflow",
                        },
                    )
                    continue
                if kind in {"input_context_overflow", "output_limit"}:
                    raise
                if kind == "transport_interrupted" and not primary_transport_retried:
                    primary_transport_retried = True
                    self.db.add_run_event(
                        run_id, "warning", "polish_transport_retry",
                        "润色请求因网络中断，正在同一路由使用相同内容重试一次",
                        stage="polish", metadata={
                            **metadata, "error": describe_error(exc)[:500],
                            "route": "primary",
                            "failure_class": "transport_interrupted",
                        },
                    )
                    continue
                primary_error = exc
                break

        if configured_fallback:
            fallback_compact = compact_used
            fallback_prompt = compact_prompt if fallback_compact else full_prompt
            while True:
                self.db.add_run_event(
                    run_id, "warning", "polish_configured_fallback",
                    "首选润色路由未产生可用正文，正在使用配置的备用路由",
                    stage="polish", metadata={
                        **metadata, "error": describe_error(primary_error)[:500],
                        "compact_input": fallback_compact,
                        "failure_class": classify_model_failure(primary_error),
                    },
                )
                try:
                    polished = await request(
                        prompt=fallback_prompt, fallback=True, compact=fallback_compact,
                        attempt_suffix=f"{suffix}-fallback"
                        + ("-input-compact" if fallback_compact else ""),
                    )
                    return polished, False, fallback_compact, True, consumed_input_tokens
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    kind = classify_model_failure(exc)
                    if kind == "provider_rejection":
                        raise
                    if kind == "input_context_overflow" and not fallback_compact:
                        fallback_compact = True
                        compact_used = True
                        fallback_prompt = compact_prompt
                        self.db.add_run_event(
                            run_id, "warning", "polish_input_compact_retry",
                            "备用模型明确拒绝了过长输入，正在保留叙事权威后压缩建议重试",
                            stage="polish", metadata={
                                **metadata, "error": describe_error(exc)[:500],
                                "route": "fallback",
                                "failure_class": "input_context_overflow",
                            },
                        )
                        continue
                    if kind in {"input_context_overflow", "output_limit"}:
                        raise
                    primary_error = exc
                    break

        self.db.add_run_event(
            run_id, "warning", "polish_segment_preserved",
            "本段未完成精修，已保留原文并继续",
            stage="polish", metadata={
                **metadata, "error": describe_error(primary_error)[:500],
                "failure_class": classify_model_failure(primary_error),
            },
        )
        return (
            source, True, compact_used, configured_fallback,
            consumed_input_tokens,
        )

    @staticmethod
    def _manifest_segment_contract(
        project: Project,
        manifest: ShortExecutionManifest,
        source_integrity: dict,
        manifest_segment,
        prose: str,
        index: int,
    ) -> DraftTaskContract:
        beat_by_id = {beat.beat_id: beat for beat in manifest.beats}
        beat_ids = list(manifest_segment.beat_ids)
        return DraftTaskContract(
            authority_sha256=str(
                source_integrity.get("authority_sha256")
                or manifest.authority_sha256
            ),
            task_id=f"segment-{index:02d}",
            parent_task_id="",
            depth=0,
            target_han=max(1, effective_han_characters(prose)),
            event_ids=tuple(dict.fromkeys(
                beat_by_id[beat_id].source_event_id for beat_id in beat_ids
            )),
            scope="\n".join(
                f"{beat_id}：{beat_by_id[beat_id].action}"
                for beat_id in beat_ids
            ),
            entry_state="；".join(
                item.state for item in manifest_segment.entry_state
            ),
            exit_requirement="；".join(
                item.state for item in manifest_segment.exit_state
            ),
            execution_manifest_sha256=execution_manifest_sha256(manifest),
            beat_ids=tuple(beat_ids),
            viewpoint=str(project.metadata.get("pov") or ""),
            prohibited_future_beat_ids=(
                manifest_segment.prohibited_future_beat_ids
            ),
        )

    @staticmethod
    def _semantic_authority_bundle(
        semantic_authority: object,
    ) -> tuple[ShortExecutionManifest, dict]:
        if not isinstance(semantic_authority, dict):
            raise ValueError("候选稿没有可复核的原子节拍权威资料")
        manifest = parse_execution_manifest(
            semantic_authority.get("execution_manifest"),
        )
        source_integrity = semantic_authority.get("source_integrity")
        source_text = semantic_authority.get("source_text")
        if not isinstance(source_integrity, dict):
            raise ValueError("候选稿缺少可复核的语义完整性资料")
        if (
            not isinstance(source_text, str)
            or not source_text
            or source_integrity.get("draft_sha256")
            != hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            or manifest.status != "ready"
            or execution_manifest_receipt_binding_issues(manifest)
            or source_integrity.get("status") != "passed"
            or source_integrity.get("execution_manifest_sha256")
            != execution_manifest_sha256(manifest)
        ):
            raise ValueError("候选稿绑定的原子节拍权威资料已经失效")
        return manifest, source_integrity

    async def _verify_atomic_candidate_semantics(
        self,
        run_id: str,
        run_path: Path,
        project: Project,
        constraints: str,
        source: str,
        candidate: str,
        semantic_authority: object,
        *,
        suffix: str,
        failure_stage: str,
        verify_whole: bool,
    ) -> dict:
        manifest, source_integrity = self._semantic_authority_bundle(
            semantic_authority,
        )
        source_parts = self._split_segments(source)
        candidate_parts = self._split_segments(candidate)
        if (
            len(source_parts) != len(candidate_parts)
            or len(candidate_parts) != len(manifest.segments)
        ):
            raise DraftSemanticValidationError("story-boundary", [{
                "code": "segment_boundary",
                "message": "返修或润色结果改变了正式分段边界",
                "expected_segments": len(manifest.segments),
                "actual_segments": len(candidate_parts),
            }])
        source_receipts = source_integrity.get("semantic_segment_receipts")
        if (
            not isinstance(source_receipts, list)
            or len(source_receipts) != len(source_parts)
        ):
            raise ValueError("验收前原文缺少完整的分段语义回执")
        all_beat_ids = [beat.beat_id for beat in manifest.beats]
        receipts = []
        changed_segments = []
        for index, (source_part, candidate_part, manifest_segment) in enumerate(
            zip(source_parts, candidate_parts, manifest.segments, strict=True), 1,
        ):
            contract = self._manifest_segment_contract(
                project, manifest, source_integrity, manifest_segment,
                candidate_part, index,
            )
            if candidate_part == source_part:
                receipt = validate_semantic_receipt(
                    contract, candidate_part, source_receipts[index - 1],
                )
            else:
                changed_segments.append(index)
                receipt = await self._verify_draft_semantic_node(
                    run_id, run_path, project, constraints, contract,
                    candidate_part,
                    [
                        beat_id for beat_id in all_beat_ids
                        if beat_id not in manifest_segment.beat_ids
                    ],
                    suffix=f"{suffix}-segment-{index:02d}",
                    failure_stage=failure_stage,
                )
            receipts.append(receipt)
        expected_beat_ids = [
            beat_id
            for segment in manifest.segments
            for beat_id in segment.beat_ids
        ]
        whole_receipt = None
        if verify_whole:
            whole_receipt = await self._verify_whole_draft_semantics(
                run_id, run_path, project, constraints,
                str(source_integrity.get("authority_sha256") or ""),
                candidate, candidate_parts, expected_beat_ids, receipts,
                failure_stage=failure_stage,
            )
        return {
            **source_integrity,
            "version": 5,
            "status": "passed",
            "source_draft_sha256": self._text_hash(source),
            "draft_sha256": self._text_hash(candidate),
            "execution_manifest_sha256": execution_manifest_sha256(manifest),
            "accepted_event_ids": expected_beat_ids,
            "semantic_segment_receipts": receipts,
            "whole_semantic_receipt": whole_receipt,
            "changed_segments": changed_segments,
            "issues": [],
        }

    async def _repair_short_revision_semantic_group(
        self,
        run_id: str,
        run_path: Path,
        project: Project,
        constraints: str,
        contract: dict,
        issue: dict,
        group_id: str,
        candidate_before: str,
        rejected_candidate: str,
        rejected_patch_group: dict,
        initial_error: DraftSemanticValidationError,
    ) -> tuple[dict, dict, dict]:
        semantic_authority = contract.get("semantic_authority")
        manifest, source_integrity = self._semantic_authority_bundle(
            semantic_authority,
        )
        before_parts = self._split_segments(candidate_before)
        rejected_parts = self._split_segments(rejected_candidate)
        authorized_segments: set[int] = set()
        for patch in rejected_patch_group.get("patches", []):
            if not isinstance(patch, dict):
                continue
            old_text = patch.get("old_text")
            if not isinstance(old_text, str) or not old_text:
                continue
            matches = [
                index for index, part in enumerate(before_parts, 1)
                if old_text in part
            ]
            if len(matches) == 1:
                authorized_segments.add(matches[0])
        affected_segments = []
        if (
            len(before_parts) == len(rejected_parts)
            and len(before_parts) == len(manifest.segments)
        ):
            rejected_changed_segments = {
                index
                for index, (before_part, rejected_part) in enumerate(
                    zip(before_parts, rejected_parts, strict=True), 1,
                )
                if before_part != rejected_part
            }
            if (
                not rejected_changed_segments
                or not rejected_changed_segments.issubset(authorized_segments)
            ):
                raise DraftSemanticValidationError(group_id, [{
                    "code": "semantic_repair_scope",
                    "message": "失败修改越过了原修改锚点所在的正式段，已拒绝扩大返修范围",
                }])
            for index, (before_part, rejected_part, manifest_segment) in enumerate(
                zip(before_parts, rejected_parts, manifest.segments, strict=True), 1,
            ):
                if before_part == rejected_part:
                    continue
                segment_contract = self._manifest_segment_contract(
                    project, manifest, source_integrity, manifest_segment,
                    before_part, index,
                )
                affected_segments.append({
                    "segment": index,
                    "contract": asdict(segment_contract),
                    "accepted_before": before_part,
                    "rejected_candidate": rejected_part,
                })
        if not affected_segments:
            for index in sorted(authorized_segments):
                if index < 1 or index > len(manifest.segments):
                    continue
                before_part = before_parts[index - 1]
                segment_contract = self._manifest_segment_contract(
                    project, manifest, source_integrity,
                    manifest.segments[index - 1], before_part, index,
                )
                affected_segments.append({
                    "segment": index,
                    "contract": asdict(segment_contract),
                    "accepted_before": before_part,
                    "rejected_candidate": before_part,
                })
        if not affected_segments:
            raise DraftSemanticValidationError(group_id, [{
                "code": "semantic_repair_scope",
                "message": "无法把失败修改绑定到唯一正式段，已拒绝扩大返修范围",
            }])
        authorized_segments = {
            int(item["segment"]) for item in affected_segments
        }
        latest_error = initial_error
        for attempt, mode in enumerate((
            "minimal_atomic_patch", "rewrite_affected_formal_segment",
        ), 1):
            request = {
                "schema": "targeted-atomic-semantic-repair-v1",
                "group_id": group_id,
                "candidate_hash": self._text_hash(candidate_before),
                "issue": issue,
                "repair_attempt": attempt,
                "repair_mode": mode,
                "semantic_failures": latest_error.issues,
                "rejected_patch_group": rejected_patch_group,
                "affected_segments": affected_segments,
                "instructions": (
                    "只返回一个 JSON 修改合同，并且只能处理当前 group_id 和 issue_id。"
                    "修改必须相对于 candidate_hash 对应的验收前候选稿；不得修改其他正式段，"
                    "不得增加或提前消费后续原子节拍。优先做最小补丁；当 repair_mode 要求"
                    "重写正式段时，可以完整替换 affected_segments 中的当前段，但必须保留"
                    "入口状态、出口状态、人物执行者、视角和全部已拥有节拍。"
                ),
            }
            try:
                raw = await self._stage(
                    run_id, run_path, project, "revision_plan", constraints,
                    json.dumps(request, ensure_ascii=False),
                    suffix=f"-repair-{group_id}-atomic-{attempt}",
                    allow_tools=False,
                    output_source_characters=sum(
                        len(item["accepted_before"])
                        for item in affected_segments
                    ) or len(str(issue.get("evidence") or "")),
                    targeted_retry=True,
                )
                value = normalize_repair_contract(
                    self._json_object(raw), candidate_before, {group_id},
                )
                if len(value["groups"]) != 1:
                    raise ValueError("语义返修必须一次只返回一个修改组")
                repaired_group = value["groups"][0]
                if (
                    repaired_group.get("group_id") != group_id
                    or repaired_group.get("issue_ids") != [group_id]
                    or repaired_group.get("kind") != "semantic"
                ):
                    raise ValueError("语义返修返回了未授权的修改组")
                if attempt == 1:
                    original_anchors = [
                        str(item.get("old_text") or "")
                        for item in rejected_patch_group.get("patches", [])
                        if isinstance(item, dict) and item.get("old_text")
                    ]
                    if any(
                        not any(
                            anchor == str(item.get("old_text") or "")
                            or anchor in str(item.get("old_text") or "")
                            for anchor in original_anchors
                        )
                        for item in repaired_group.get("patches", [])
                        if isinstance(item, dict)
                    ):
                        raise ValueError(
                            "最小语义返修越过了原修改锚点"
                        )
                repaired_result = {
                    "group_id": group_id,
                    **apply_patch_group(
                        candidate_before, repaired_group,
                        self._text_hash(candidate_before),
                    ),
                }
                if repaired_result.get("accepted") is not True:
                    raise ValueError("语义返修补丁未通过原子应用检查")
                repaired_integrity = await self._verify_atomic_candidate_semantics(
                    run_id, run_path, project, constraints,
                    str(contract["semantic_authority"].get("source_text") or ""),
                    repaired_result["text"], semantic_authority,
                    suffix=f"-repair-{group_id}-atomic-{attempt}",
                    failure_stage="repair_groups", verify_whole=False,
                )
                changed_segments = {
                    int(index)
                    for index in repaired_integrity.get("changed_segments", [])
                }
                if (
                    not changed_segments
                    or not changed_segments.issubset(authorized_segments)
                ):
                    raise ValueError(
                        "语义返修越过了当前修改组授权的正式段范围"
                    )
                repaired_parts = self._split_segments(repaired_result["text"])
                quality_blockers = []
                for index in sorted(changed_segments):
                    quality_assessment = assess_polish_candidate(
                        before_parts[index - 1], repaired_parts[index - 1],
                        minimum_ratio=0.60, maximum_ratio=1.60,
                    )
                    quality_blockers.extend(
                        quality_assessment.get("hard_reasons") or []
                    )
                    quality_blockers.extend(
                        reason
                        for reason in quality_assessment.get("reasons", [])
                        if "regression" in str(reason)
                    )
                quality_blockers.extend(validate_locked_facts(
                    candidate_before, repaired_result["text"],
                    contract["story_state"]["data"],
                ))
                passage_validation = validate_passage_protections(
                    candidate_before, repaired_result["text"],
                    contract["passage_locks"],
                )
                quality_blockers.extend(
                    item.get("message") or item.get("id") or "passage_lock"
                    for item in passage_validation.get("conflicts", [])
                )
                if quality_blockers:
                    raise DraftSemanticValidationError(group_id, [{
                        "code": "semantic_repair_quality",
                        "message": (
                            "语义返修造成文笔、篇幅、锁定事实或保护片段回退"
                        ),
                        "blocking_reasons": list(dict.fromkeys(
                            str(reason) for reason in quality_blockers
                        )),
                    }])
            except asyncio.CancelledError:
                raise
            except DraftSemanticValidationError as exc:
                latest_error = exc
                continue
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                latest_error = DraftSemanticValidationError(group_id, [{
                    "code": "semantic_repair_contract",
                    "message": str(exc),
                }])
                continue
            self.db.add_run_event(
                run_id, "success", "short_revision_semantic_repaired",
                "当前修改组已按原子节拍错误证据完成自动修正",
                stage="repair_groups", metadata={
                    "group_id": group_id,
                    "attempt": attempt,
                    "mode": mode,
                    "changed_segments": repaired_integrity["changed_segments"],
                },
            )
            return repaired_group, repaired_result, repaired_integrity
        raise latest_error

    async def _repair_polish_semantic_segment(
        self,
        run_id: str,
        run_path: Path,
        project: Project,
        constraints: str,
        contract: DraftTaskContract,
        accepted_source: str,
        rejected_candidate: str,
        outside_beat_ids: list[str],
        initial_error: DraftSemanticValidationError,
        *,
        suffix: str,
    ) -> tuple[str, dict] | None:
        latest_error = initial_error
        for attempt, mode in enumerate((
            "minimal_prose_repair", "rewrite_complete_formal_segment",
        ), 1):
            prompt = (
                "ATOMIC_SEMANTIC_PROSE_REPAIR. Return revised prose only. Do not explain. "
                "Repair only the current formal segment. Preserve its useful dialogue, detail, "
                "voice, pacing, and length unless they directly cause a listed failure. Never add "
                "a prohibited future beat or rewrite another segment. The result must satisfy the "
                "exact actor/action ownership, viewpoint, entry state, exit state, and causal order.\n\n"
                f"REPAIR MODE: {mode}\n"
                f"TASK CONTRACT: {json.dumps(asdict(contract), ensure_ascii=False)}\n"
                f"SEMANTIC FAILURES: {json.dumps(latest_error.issues, ensure_ascii=False)}\n"
                f"ACCEPTED SOURCE SEGMENT:\n{accepted_source}\n\n"
                f"REJECTED POLISH CANDIDATE:\n{rejected_candidate}"
            )
            try:
                repaired = str(await self._stage(
                    run_id, run_path, project, "polish", constraints, prompt,
                    suffix=f"{suffix}-semantic-repair-{attempt}",
                    allow_tools=False,
                    output_source_characters=len(accepted_source),
                    targeted_retry=True,
                )).strip()
                if (
                    not repaired
                    or self.SHORT_SEGMENT_SEPARATOR.strip() in repaired
                    or effective_han_characters(repaired)
                    < max(1, math.floor(effective_han_characters(accepted_source) * 0.60))
                    or effective_han_characters(repaired)
                    > math.ceil(effective_han_characters(accepted_source) * 1.60)
                ):
                    raise DraftSemanticValidationError(contract.task_id, [{
                        "code": "semantic_repair_shape",
                        "message": "语义修复结果为空、改变分段边界或篇幅失真",
                    }])
                receipt = await self._verify_draft_semantic_node(
                    run_id, run_path, project, constraints, contract, repaired,
                    outside_beat_ids,
                    suffix=f"{suffix}-semantic-repair-{attempt}",
                    failure_stage="polish",
                )
                quality_assessment = assess_polish_candidate(
                    accepted_source, repaired,
                    minimum_ratio=0.60, maximum_ratio=1.60,
                )
                quality_blockers = list(
                    quality_assessment.get("hard_reasons") or []
                )
                quality_blockers.extend(
                    reason
                    for reason in quality_assessment.get("reasons", [])
                    if "regression" in str(reason)
                )
                locked_failures = validate_locked_facts(
                    accepted_source, repaired,
                    self.story_states.ensure(project.id, project.path).data,
                )
                passage_validation = validate_passage_protections(
                    accepted_source, repaired,
                    applicable_passage_locks(
                        self.db.list_locks(project.id), accepted_source,
                    ),
                )
                quality_blockers.extend(locked_failures)
                quality_blockers.extend(
                    item.get("message") or item.get("id") or "passage_lock"
                    for item in passage_validation.get("conflicts", [])
                )
                if quality_blockers:
                    raise DraftSemanticValidationError(contract.task_id, [{
                        "code": "semantic_repair_quality",
                        "message": "语义修复造成文笔、锁定事实或保护片段质量回退",
                        "blocking_reasons": list(dict.fromkeys(quality_blockers)),
                    }])
            except asyncio.CancelledError:
                raise
            except DraftSemanticValidationError as exc:
                latest_error = exc
                continue
            except Exception as exc:
                self.db.add_run_event(
                    run_id, "warning", "polish_semantic_repair_unavailable",
                    "语义修复模型本轮不可用，已保留验收前原段",
                    stage="polish", metadata={
                        "task_id": contract.task_id,
                        "attempt": attempt,
                        "failure_class": classify_model_failure(exc),
                    },
                )
                return None
            self.db.add_run_event(
                run_id, "success", "polish_semantic_repaired",
                "润色段已按原子节拍错误证据完成自动修正",
                stage="polish", metadata={
                    "task_id": contract.task_id,
                    "attempt": attempt,
                    "mode": mode,
                },
            )
            return repaired, receipt
        self.db.add_run_event(
            run_id, "warning", "polish_semantic_repair_exhausted",
            "当前正式段两次语义修复仍未通过，已恢复验收前原段",
            stage="polish", metadata={
                "task_id": contract.task_id,
                "issues": latest_error.issues,
            },
        )
        return None

    async def _verify_draft_semantic_node(
        self,
        run_id: str,
        run_path: Path,
        project: Project,
        constraints: str,
        contract: DraftTaskContract,
        prose: str,
        outside_event_ids: list[str],
        *,
        suffix: str,
        failure_stage: str = "draft",
    ) -> dict:
        prose_sha256 = hashlib.sha256(prose.encode("utf-8")).hexdigest()
        atomic = bool(contract.beat_ids)
        owned_label = "beat" if atomic else "event"
        prompt = (
            "DRAFT_SEMANTIC_VALIDATION. Independently verify the immutable prose against its task "
            "contract. Do not rewrite or score. Return one JSON object with authority_sha256, "
            "execution_manifest_sha256, task_id, prose_sha256, "
            + (
                "beat_receipts (one per owned atomic beat in exact order, each with beat_id, "
                "evidence, actor_action_valid, actor_action_evidence, state_valid, state_evidence, "
                "scene_order_valid, and scene_order_evidence), outside_beat_ids, future_beat_ids, "
                "viewpoint_valid, viewpoint_evidence, "
                if atomic else
                "event_receipts (one per owned event in exact order, each with event_id and an "
                "exact prose evidence excerpt), outside_event_ids, "
            )
            + "entry and exit objects (satisfied=true and exact prose evidence), "
            "causal_order_valid, causal_order_evidence, and summary. Every evidence field must be "
            "copied exactly from PROSE. Actor/action identity must match the contract actor, not a "
            "different character performing a similar action. State validation covers location, "
            "time, knowledge, and boundary state. If a "
            "requirement is absent, report it honestly; never infer success from the contract text.\n\n"
            f"AUTHORITY SHA256: {contract.authority_sha256}\n"
            f"TASK CONTRACT: {json.dumps(contract.__dict__, ensure_ascii=False)}\n"
            f"OTHER TASK {owned_label.upper()} IDS: {json.dumps(outside_event_ids)}\n"
            f"PROSE SHA256: {prose_sha256}\n"
            f"PROSE:\n{prose}"
        )
        raw = await self._stage(
            run_id, run_path, project, "review", constraints, prompt,
            suffix=f"{suffix}-semantic", allow_tools=False,
            expected_output_characters=max(
                800, len(contract.beat_ids or contract.event_ids) * 320,
            ),
        )
        try:
            raw_receipt = self._json_object(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            receipt_issues = [{
                "code": "invalid_receipt", "message": str(exc),
            }]
        else:
            receipt_issues = semantic_receipt_issues(contract, prose, raw_receipt)
        if receipt_issues:
            event_type = {
                "draft": "draft_semantic_gate_failed",
                "polish": "polish_semantic_gate_failed",
                "repair_groups": "short_revision_semantic_gate_failed",
            }.get(failure_stage, "semantic_gate_failed")
            message = {
                "draft": "正文事件、入口或出口缺少可核对原文证据，将完整重写当前范围",
                "polish": "润色结果改变了原子节拍、状态、顺序或视角，正在定向修复当前正式段",
                "repair_groups": "定向返修改变了原子节拍、状态、顺序或视角，正在重做当前修改组",
            }.get(failure_stage, "候选正文未通过原子节拍语义复核")
            self.db.add_run_event(
                run_id, "warning", event_type, message,
                stage=failure_stage, metadata={
                    "task_id": contract.task_id,
                    "event_ids": list(contract.event_ids),
                    "beat_ids": list(contract.beat_ids),
                    "prose_sha256": prose_sha256,
                    "error": "；".join(
                        str(item.get("message") or item.get("code"))
                        for item in receipt_issues
                    ),
                    "issues": receipt_issues,
                },
            )
            raise DraftSemanticValidationError(contract.task_id, receipt_issues)
        receipt = validate_semantic_receipt(contract, prose, raw_receipt)
        return receipt

    async def _verify_whole_draft_semantics(
        self,
        run_id: str,
        run_path: Path,
        project: Project,
        constraints: str,
        authority_sha256: str,
        draft: str,
        segments: list[str],
        expected_event_ids: list[str],
        segment_receipts: list[dict],
        *,
        failure_stage: str = "draft",
    ) -> dict:
        draft_sha256 = hashlib.sha256(draft.encode("utf-8")).hexdigest()
        segment_sha256 = [
            hashlib.sha256(segment.encode("utf-8")).hexdigest() for segment in segments
        ]
        evidence_packet = [
            {
                "segment": index,
                "prose_sha256": receipt.get("prose_sha256"),
                "beat_receipts": receipt.get("beat_receipts", []),
                "event_receipts": receipt.get("event_receipts", []),
                "entry": receipt.get("entry"),
                "exit": receipt.get("exit"),
                "summary": receipt.get("summary"),
            }
            for index, receipt in enumerate(segment_receipts, 1)
        ]
        prompt = (
            "DRAFT_WHOLE_SEMANTIC_VALIDATION. Independently adjudicate the ordered, hash-bound "
            "segment evidence as one complete story. Do not rewrite or score. Return one JSON object "
            "with authority_sha256, draft_sha256, segment_sha256, event_ids, missing_event_ids, "
            "duplicate_event_ids, out_of_order_event_ids, causal_order_valid, continuity_valid, "
            "ending_valid, commitments_valid, evidence (exact excerpts already present in the draft), "
            "and summary. Do not claim success when any transition, causal step, promise, climax, or "
            "ending cannot be proven by the ordered evidence.\n\n"
            f"AUTHORITY SHA256: {authority_sha256}\n"
            f"DRAFT SHA256: {draft_sha256}\n"
            f"SEGMENT SHA256: {json.dumps(segment_sha256)}\n"
            f"EXPECTED EVENT IDS: {json.dumps(expected_event_ids)}\n"
            f"ORDERED SEGMENT EVIDENCE: {json.dumps(evidence_packet, ensure_ascii=False)}\n"
            f"OPENING EXCERPT: {draft[:1200]}\n"
            f"ENDING EXCERPT: {draft[-1600:]}"
        )
        raw = await self._stage(
            run_id, run_path, project, "review", constraints, prompt,
            suffix="-draft-whole-semantic", allow_tools=False,
            expected_output_characters=max(1200, len(expected_event_ids) * 160),
        )
        try:
            receipt = validate_whole_draft_receipt(
                authority_sha256, draft, segments, expected_event_ids,
                self._json_object(raw),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            event_type = {
                "draft": "draft_whole_semantic_gate_failed",
                "polish": "polish_whole_semantic_gate_failed",
                "repair_groups": "short_revision_whole_semantic_gate_failed",
            }.get(failure_stage, "whole_semantic_gate_failed")
            message = {
                "draft": "正文整篇因果、连续性或结局证据未通过核对，已停止进入精修",
                "polish": "润色合并稿未通过整篇因果和连续性核对，未进入质量晋升",
                "repair_groups": "定向返修合并稿未通过整篇因果和连续性核对，未调用终审",
            }.get(failure_stage, "候选稿未通过整篇语义完整性核对")
            self.db.add_run_event(
                run_id, "error", event_type, message,
                stage=failure_stage, metadata={
                    "draft_sha256": draft_sha256,
                    "event_count": len(expected_event_ids),
                    "error": str(exc),
                },
            )
            raise ValueError(f"整篇语义完整性检查未通过：{exc}") from exc
        return receipt

    async def _draft_short_in_segments(self, run_id: str, run_path: Path, project: Project,
                                        constraints: str, plan: str) -> str:
        target_words = int(project.metadata["target_words"])
        count = self._short_segment_count(target_words)
        target = math.ceil(target_words / count)
        segment_plans = self._short_plan_segments(plan, count)
        if len(segment_plans) != count:
            raise ValueError("规划稿没有明确每一段负责的事件，尚未生成正文")
        manifest_path = run_path / "outputs" / "short-execution-index.json"
        try:
            execution_manifest = parse_execution_manifest(json.loads(
                manifest_path.read_text(encoding="utf-8"),
            ))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("正文开始前缺少有效的原子节拍执行索引") from exc
        if (
            execution_manifest.status != "ready"
            or len(execution_manifest.segments) != count
        ):
            raise ValueError("原子节拍执行索引尚未就绪或分段数量不一致")
        execution_manifest_hash = execution_manifest_sha256(execution_manifest)
        manifest_segments = {
            item.segment: item for item in execution_manifest.segments
        }
        beat_by_id = {item.beat_id: item for item in execution_manifest.beats}
        authoritative_state = self.story_states.ensure(project.id, project.path).data
        story_state_sha256 = hashlib.sha256(json.dumps(
            authoritative_state, ensure_ascii=False, sort_keys=True, default=str,
        ).encode("utf-8")).hexdigest()
        location_catalog = build_location_catalog(project.path, authoritative_state)
        ownership = "\n".join(
            f"第 {index} 段：{next((line.lstrip('# ').strip() for line in block.splitlines() if line.strip()), '未命名')}"
            for index, block in enumerate(segment_plans, 1)
        )
        legacy_authority_payload = {
            "plan": plan,
            "constraints": constraints,
            "target_words": target_words,
            "segment_count": count,
        }
        authority_payload = {
            **legacy_authority_payload,
            "story_state_sha256": story_state_sha256,
            "execution_manifest_sha256": execution_manifest_hash,
        }
        authority_hash = hashlib.sha256(json.dumps({
            **authority_payload,
            "location_catalog": sorted(
                (alias, ref.name, ref.root)
                for alias, ref in location_catalog.items()
            ),
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        compatible_authority_hashes = {authority_hash}
        checkpoint_root = run_path / "outputs" / "draft-checkpoints"
        parts: list[str] = []
        event_assignments: list[dict] = []
        all_expected_event_ids = [
            beat_id
            for segment_number in range(1, count + 1)
            for beat_id in manifest_segments[segment_number].beat_ids
        ]
        segment_semantic_receipts: list[dict] = []
        for index in range(1, count + 1):
            self.db.add_run_event(
                run_id, "info", "segment_started", f"开始生成正文第 {index}/{count} 段",
                stage="draft", metadata={"segment": index, "total": count, "target_words": target},
            )
            previous_tail = parts[-1][-1200:] if parts else "这是开篇，无上一段。"
            previous_plan_tail = (
                self._short_plan_handoff(segment_plans[index - 2])
                if index > 1 else "这是开篇，无上一段交接状态。"
            )
            checkpoint_path = checkpoint_root / f"segment-{index:02d}.json"
            previous_hash = (
                hashlib.sha256(parts[-1].encode("utf-8")).hexdigest() if parts else ""
            )
            try:
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, AttributeError):
                checkpoint = {}
            cached_part = str(checkpoint.get("text") or "")
            cached_assignment = checkpoint.get("assignment") or {}
            manifest_segment = manifest_segments[index]
            expected_event_ids = list(manifest_segment.beat_ids)
            source_event_ids = list(dict.fromkeys(
                beat_by_id[beat_id].source_event_id for beat_id in expected_event_ids
            ))
            expected_handoff = "；".join(
                assertion.state for assertion in manifest_segment.exit_state
            )
            expected_entry = "；".join(
                assertion.state for assertion in manifest_segment.entry_state
            )
            prompt = (
                f"整篇分工：\n{ownership}\n\n"
                "正文必须服从正式规划、设定与因果链。不得提前写后续分段的事件，也不得重写前面已经发生的场景。"
                "人物、地点、因果和结局均以正式设定为准。开头必须承接上一段结束时的人物位置、动作、"
                "关系和知情状态；如果当前任务需要换时间或换场景，开头必须用自然过渡交代清楚。\n\n"
                "本段原子节拍契约：\n"
                + json.dumps(asdict(manifest_segment), ensure_ascii=False, indent=2)
            )
            root_contract = DraftTaskContract(
                authority_sha256=authority_hash,
                task_id=f"segment-{index:02d}",
                parent_task_id="",
                depth=0,
                target_han=target,
                event_ids=tuple(source_event_ids),
                scope=(
                    f"本次只写第 {index}/{count} 段，唯一负责的原子节拍：\n"
                    + "\n".join(
                        f"{beat_id}：{beat_by_id[beat_id].action}"
                        for beat_id in expected_event_ids
                    )
                    + "\n\n已验收规划分段：\n" + segment_plans[index - 1]
                ),
                entry_state=(
                    f"执行索引入口状态：\n{expected_entry}\n\n"
                    f"上一段计划交接：\n{previous_plan_tail}\n\n"
                    f"上一段正文结尾：\n{previous_tail}"
                ),
                exit_requirement=expected_handoff,
                execution_manifest_sha256=execution_manifest_hash,
                beat_ids=tuple(expected_event_ids),
                viewpoint=str(project.metadata.get("pov") or ""),
                prohibited_future_beat_ids=manifest_segment.prohibited_future_beat_ids,
            )
            cache_structurally_valid = (
                checkpoint.get("version") == 3
                and checkpoint.get("authority_sha256") in compatible_authority_hashes
                and checkpoint.get("execution_manifest_sha256")
                == execution_manifest_hash
                and checkpoint.get("previous_sha256") == previous_hash
                and checkpoint.get("segment_plan_sha256") == hashlib.sha256(
                    segment_plans[index - 1].encode("utf-8")
                ).hexdigest()
                and checkpoint.get("text_sha256")
                == hashlib.sha256(cached_part.encode("utf-8")).hexdigest()
                and cached_assignment.get("segment") == index
                and cached_assignment.get("event_ids") == expected_event_ids
                and cached_assignment.get("source_event_ids") == source_event_ids
                and cached_assignment.get("handoff") == expected_handoff
                and cached_part
                and not self._draft_segment_issues(
                    cached_part, target, parts, location_catalog,
                )
            )
            cached_semantic_receipt = None
            if cache_structurally_valid and expected_event_ids:
                try:
                    cached_semantic_receipt = validate_semantic_receipt(
                        root_contract, cached_part, checkpoint.get("semantic_receipt"),
                    )
                except ValueError:
                    cached_semantic_receipt = await self._verify_draft_semantic_node(
                        run_id, run_path, project, constraints, root_contract,
                        cached_part,
                        [
                            event_id for event_id in all_expected_event_ids
                            if event_id not in expected_event_ids
                        ],
                        suffix=f"-part-{index:02d}-checkpoint",
                    )
                    checkpoint = {
                        **checkpoint,
                        "version": 3,
                        "semantic_receipt": cached_semantic_receipt,
                    }
                    atomic_write(
                        checkpoint_path,
                        json.dumps(checkpoint, ensure_ascii=False, indent=2),
                    )
            if cache_structurally_valid:
                parts.append(cached_part)
                assignment = {
                    **cached_assignment,
                    **({"semantic_receipt": cached_semantic_receipt}
                       if cached_semantic_receipt else {}),
                }
                event_assignments.append(assignment)
                if cached_semantic_receipt:
                    segment_semantic_receipts.append(cached_semantic_receipt)
                atomic_write(
                    run_path / "outputs" / "segment-events.json",
                    json.dumps({"segments": event_assignments}, ensure_ascii=False, indent=2),
                )
                self.db.add_run_event(
                    run_id, "success", "draft_checkpoint_reused",
                    f"正文第 {index}/{count} 段已从内部检查点恢复",
                    stage="draft", metadata={"segment": index, "total": count},
                )
                continue
            semantic_receipt_nodes: list[tuple[DraftTaskContract, dict]] = []
            part = await self._draft_short_segment_task(
                run_id, run_path, project, constraints, prompt,
                suffix=f"-part-{index:02d}", target=target,
                previous_parts=parts, event_ids=expected_event_ids,
                location_catalog=location_catalog, contract=root_contract,
                semantic_all_event_ids=(
                    all_expected_event_ids if expected_event_ids else None
                ),
                semantic_receipt_sink=semantic_receipt_nodes,
            )
            issues = (
                self._draft_segment_issues(part, target, parts, location_catalog)
                if count > 1 else []
            )
            if issues:
                self.db.add_run_event(
                    run_id, "error", "draft_segment_gate_failed",
                    f"正文第 {index}/{count} 段未通过契约内检查，已停止后续生成",
                    stage="draft", metadata={"segment": index, "issues": issues},
                )
                raise ValueError(
                    f"正文第 {index} 段未通过本地检查，已有进度已保留"
                )
            verified_nodes = [receipt for _contract, receipt in semantic_receipt_nodes]
            root_semantic_receipt = None
            if expected_event_ids:
                for node_contract, receipt in semantic_receipt_nodes:
                    if node_contract.task_id == root_contract.task_id:
                        root_semantic_receipt = receipt
                if root_semantic_receipt is None:
                    raise ValueError(
                        f"正文第 {index} 段缺少父级语义验收回执"
                    )
                segment_semantic_receipts.append(root_semantic_receipt)
            warnings = [
                finding for finding in self._draft_segment_findings(
                    part, target, parts, location_catalog,
                ) if not finding.get("blocking")
            ]
            if warnings:
                self.db.add_run_event(
                    run_id, "warning", "draft_segment_continuity_warning",
                    f"正文第 {index}/{count} 段存在无法确定的场景衔接，已记录但不会单独阻断",
                    stage="draft", metadata={
                        "segment": index,
                        "issues": warnings,
                    },
                )
            parts.append(part.strip())
            assignment = {
                "segment": index,
                "event_ids": expected_event_ids,
                "source_event_ids": source_event_ids,
                "handoff": expected_handoff,
                **({
                    "semantic_receipt": root_semantic_receipt,
                    "semantic_node_receipts": verified_nodes,
                } if root_semantic_receipt else {}),
            }
            event_assignments.append(assignment)
            atomic_write(checkpoint_path, json.dumps({
                "version": 3,
                "authority_sha256": authority_hash,
                "execution_manifest_sha256": execution_manifest_hash,
                "previous_sha256": previous_hash,
                "segment_plan_sha256": hashlib.sha256(
                    segment_plans[index - 1].encode("utf-8")
                ).hexdigest(),
                "text_sha256": hashlib.sha256(part.strip().encode("utf-8")).hexdigest(),
                "text": part.strip(),
                "assignment": assignment,
                **({"semantic_receipt": root_semantic_receipt}
                   if root_semantic_receipt else {}),
            }, ensure_ascii=False, indent=2))
            atomic_write(
                run_path / "outputs" / "segment-events.json",
                json.dumps({"segments": event_assignments}, ensure_ascii=False, indent=2),
            )
            self.db.add_run_event(
                run_id, "success", "segment_completed", f"正文第 {index}/{count} 段生成完成",
                stage="draft", metadata={
                    "segment": index, "total": count, "characters": len(part),
                    "event_ids": assignment["event_ids"], "handoff": assignment["handoff"],
                },
            )
        draft = self.SHORT_SEGMENT_SEPARATOR.join(parts)
        expected_event_ids = all_expected_event_ids
        whole_semantic_receipt = None
        if expected_event_ids:
            if len(segment_semantic_receipts) != len(parts):
                raise ValueError("正文分段缺少完整语义验收回执")
            whole_semantic_receipt = await self._verify_whole_draft_semantics(
                run_id, run_path, project, constraints, authority_hash,
                draft, parts, expected_event_ids, segment_semantic_receipts,
            )
            accepted_event_ids = [
                str(event.get("beat_id") or event.get("event_id") or "")
                for receipt in segment_semantic_receipts
                for event in (
                    receipt.get("beat_receipts")
                    or receipt.get("event_receipts", [])
                )
            ]
        else:
            accepted_event_ids = [
                event_id
                for assignment in event_assignments
                for event_id in assignment.get("event_ids", [])
            ]
        integrity_issues = []
        current_story_state_sha256 = hashlib.sha256(json.dumps(
            self.story_states.ensure(project.id, project.path).data,
            ensure_ascii=False, sort_keys=True, default=str,
        ).encode("utf-8")).hexdigest()
        if current_story_state_sha256 != story_state_sha256:
            integrity_issues.append("正文生成期间权威 StoryState 已变化")
        if len(parts) != count or len(event_assignments) != count:
            integrity_issues.append("正文段数量与正式分工不一致")
        if accepted_event_ids != expected_event_ids:
            integrity_issues.append("正文事件覆盖发生遗漏、重复或顺序变化")
        for segment_index, part in enumerate(parts):
            segment_issues = [
                str(finding["message"])
                for finding in self._draft_segment_findings(
                    part, target, parts[:segment_index], location_catalog,
                )
                if finding.get("blocking") and finding.get("code") != "underlength"
            ]
            if segment_issues:
                integrity_issues.append(
                    f"第 {segment_index + 1} 段未通过整段复核：" + "；".join(segment_issues)
                )
        segment_receipts = []
        previous_segment_hash = ""
        for segment_index, (part, assignment) in enumerate(
            zip(parts, event_assignments), 1,
        ):
            text_hash = hashlib.sha256(part.encode("utf-8")).hexdigest()
            segment_receipts.append({
                "segment": segment_index,
                "event_ids": list(assignment.get("event_ids", [])),
                "handoff": str(assignment.get("handoff") or ""),
                "han_characters": effective_han_characters(part),
                "previous_sha256": previous_segment_hash,
                "text_sha256": text_hash,
            })
            previous_segment_hash = text_hash
        integrity = {
            "version": 3,
            "status": "failed" if integrity_issues else "passed",
            "authority_sha256": authority_hash,
            "execution_manifest_sha256": execution_manifest_hash,
            "plan_sha256": hashlib.sha256(plan.encode("utf-8")).hexdigest(),
            "constraints_sha256": hashlib.sha256(constraints.encode("utf-8")).hexdigest(),
            "base_constraints_sha256": hashlib.sha256(
                constraints.split("\n\n# Short Story Causal Chain\n\n", 1)[0].encode(
                    "utf-8",
                ),
            ).hexdigest(),
            "story_state_sha256": story_state_sha256,
            "draft_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
            "expected_event_ids": expected_event_ids,
            "accepted_event_ids": accepted_event_ids,
            "segments": segment_receipts,
            "semantic_segment_receipts": segment_semantic_receipts,
            "whole_semantic_receipt": whole_semantic_receipt,
            "issues": integrity_issues,
        }
        atomic_write(
            run_path / "outputs" / "draft-integrity.json",
            json.dumps(integrity, ensure_ascii=False, indent=2),
        )
        if integrity_issues:
            self.db.add_run_event(
                run_id, "error", "draft_integrity_failed",
                "正文整段与整篇核验未通过，已停止进入后续流程",
                stage="draft", metadata={"issues": integrity_issues},
            )
            raise ValueError("正文整篇完整性检查未通过：" + "；".join(integrity_issues))
        atomic_write(run_path / "outputs" / "draft.md", draft)
        self.db.add_run_event(
            run_id, "success", "draft_integrity_passed",
            "正文全部分段、正式事件与衔接哈希已通过整篇核验",
            stage="draft", metadata={
                "segments": len(parts), "event_count": len(accepted_event_ids),
                "draft_sha256": integrity["draft_sha256"],
            },
        )
        return draft

    async def _draft_short_segment_task(
        self, run_id: str, run_path: Path, project: Project, constraints: str,
        prompt: str, *, suffix: str, target: int, previous_parts: list[str],
        event_ids: list[str] | None = None,
        location_catalog: dict[str, LocationRef] | None = None,
        depth: int = 0,
        contract: DraftTaskContract | None = None,
        retry_count: int = 0,
        node_sink: list[tuple[DraftTaskContract, str]] | None = None,
        semantic_all_event_ids: list[str] | None = None,
        semantic_receipt_sink: list[tuple[DraftTaskContract, dict]] | None = None,
    ) -> str:
        """Generate one owned segment and split when one response cannot own it."""
        owned_event_ids = list(event_ids or [])
        node_sink_start = len(node_sink) if node_sink is not None else 0
        semantic_sink_start = (
            len(semantic_receipt_sink)
            if semantic_receipt_sink is not None else 0
        )
        if contract is None:
            authority_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            contract = DraftTaskContract(
                authority_sha256=authority_hash,
                task_id=suffix.lstrip("-") or "draft-segment",
                parent_task_id="",
                depth=depth,
                target_han=target,
                event_ids=tuple(owned_event_ids),
                scope=(
                    "完成当前写作段正式事件：" + "、".join(owned_event_ids)
                    if owned_event_ids else "完成当前写作段的入口、冲突推进与段末交接"
                ),
                entry_state=(
                    previous_parts[-1][-1200:] if previous_parts else "正文开篇，无前置正文"
                ),
                exit_requirement="完成本段状态变化，不提前写后续写作段事件",
            )
        elif (
            contract.target_han != target
            or list(contract.beat_ids or contract.event_ids) != owned_event_ids
        ):
            raise ValueError("正文子任务参数与执行契约不一致")
        rendered_prompt = render_draft_task_prompt(prompt, contract)

        async def accept_node(value: str) -> str:
            semantic_receipt = None
            if semantic_all_event_ids is not None and contract.event_ids:
                owned_semantic_ids = set(contract.beat_ids or contract.event_ids)
                semantic_receipt = await self._verify_draft_semantic_node(
                    run_id, run_path, project, constraints, contract, str(value),
                    [
                        event_id for event_id in semantic_all_event_ids
                        if event_id not in owned_semantic_ids
                    ],
                    suffix=f"{suffix}-{contract.task_id.replace('/', '-')}",
                )
            if node_sink is not None:
                node_sink.append((contract, str(value)))
            if semantic_receipt_sink is not None and semantic_receipt is not None:
                semantic_receipt_sink.append((contract, semantic_receipt))
            return value

        async def retry_same_scope(findings: list[dict]) -> str:
            if retry_count >= 2:
                semantic = any(
                    item.get("semantic") is True
                    or item.get("code") == "semantic_contract_failed"
                    for item in findings
                )
                if semantic:
                    self.db.add_run_event(
                        run_id, "error", "draft_semantic_rewrite_exhausted",
                        "当前正文范围完整重写两次后仍缺少语义证据，已保留上游合格分段并停止",
                        stage="draft", metadata={
                            "task_id": contract.task_id,
                            "beat_ids": list(contract.beat_ids),
                            "issues": findings,
                        },
                    )
                raise ValueError(
                    (
                        "正文语义完整性检查在同一事件范围自动重写两次后仍未通过："
                        if semantic else
                        "正文子任务在同一事件范围重试后仍未通过检查："
                    )
                    + "；".join(str(item.get("message") or item.get("code")) for item in findings)
                )
            if node_sink is not None:
                del node_sink[node_sink_start:]
            if semantic_receipt_sink is not None:
                del semantic_receipt_sink[semantic_sink_start:]
            self.db.add_run_event(
                run_id, "warning", "draft_task_scope_retry",
                "正文子任务未通过叶子检查，正在保持事件范围重新生成",
                stage="draft", metadata={
                    "suffix": suffix, "depth": depth,
                    "target_characters": target,
                    "target_range": list(target_bounds(target)),
                    "event_ids": owned_event_ids,
                    "issue_codes": [str(item.get("code") or "incomplete") for item in findings],
                },
            )
            retry_contract = DraftTaskContract(
                authority_sha256=contract.authority_sha256,
                task_id=contract.task_id,
                parent_task_id=contract.parent_task_id,
                depth=contract.depth,
                target_han=contract.target_han,
                event_ids=contract.event_ids,
                scope=contract.scope,
                entry_state=contract.entry_state,
                exit_requirement=(
                    contract.exit_requirement
                    + "；修正上次检查问题："
                    + "；".join(str(item.get("message") or item.get("code")) for item in findings)
                ),
                previous_sibling_sha256=contract.previous_sibling_sha256,
                execution_manifest_sha256=contract.execution_manifest_sha256,
                beat_ids=contract.beat_ids,
                viewpoint=contract.viewpoint,
                prohibited_future_beat_ids=contract.prohibited_future_beat_ids,
            )
            retried = await self._draft_short_segment_task(
                run_id, run_path, project, constraints, prompt,
                suffix=f"{suffix}-scope-retry", target=target,
                previous_parts=previous_parts, event_ids=owned_event_ids,
                location_catalog=location_catalog, depth=depth,
                contract=retry_contract, retry_count=retry_count + 1,
                node_sink=node_sink,
                semantic_all_event_ids=semantic_all_event_ids,
                semantic_receipt_sink=semantic_receipt_sink,
            )
            return retried

        async def accept_or_retry(value: str) -> str:
            try:
                return await accept_node(value)
            except DraftSemanticValidationError as exc:
                return await retry_same_scope([
                    {**item, "semantic": True} for item in exc.issues
                ])

        reason = "output_limit"
        han_characters = 0
        try:
            part = await self._stage(
                run_id, run_path, project, "draft", constraints, rendered_prompt,
                suffix=suffix, allow_tools=False,
                expected_output_characters=target,
                completion_check=lambda value: not self._draft_segment_issues(
                    value, target, previous_parts, location_catalog,
                ),
            )
        except IncompleteModelOutputError as exc:
            han_characters = effective_han_characters(str(exc.partial))
            if depth >= 2 or target < 800 or len(owned_event_ids) < 2:
                if retry_count < 1:
                    return await retry_same_scope([{
                        "code": "output_limit",
                        "message": "供应商未完整返回当前事件范围",
                    }])
                raise
        else:
            receipt = getattr(part, "receipt", {})
            finish_reason = normalize_finish_reason(
                receipt.get("finish_reason") if isinstance(receipt, dict) else None
            )
            findings = [
                finding for finding in self._draft_segment_findings(
                    part, target, previous_parts, location_catalog,
                ) if finding.get("blocking")
            ]
            if not findings:
                try:
                    return await accept_node(part)
                except DraftSemanticValidationError as exc:
                    return await retry_same_scope([
                        {**item, "semantic": True} for item in exc.issues
                    ])
            underlength = next((
                finding for finding in findings if finding.get("code") == "underlength"
            ), None)
            if any(finding.get("code") != "underlength" for finding in findings):
                return await retry_same_scope(findings)
            if finish_reason not in {"stop", "end_turn", "completed", "complete"}:
                return await retry_same_scope([{
                    **underlength,
                    "code": "unknown_terminal_underlength",
                    "message": "供应商没有提供可确认完整结束的状态，不能验收偏短正文",
                }])
            # Han-count recovery is meaningful only after the response proves it
            # contains Chinese prose. Other-language projects keep using their
            # normal prose/quality gates instead of being split on a zero metric.
            han_characters = int(underlength.get("han_characters") or 0)
            if han_characters <= 0:
                return await accept_or_retry(part)
            if depth >= 2 or target < 800 or len(owned_event_ids) < 2:
                return await retry_same_scope(findings)
            reason = "normal_finish_underlength"
        split_at = max(1, math.ceil(len(owned_event_ids) / 2))
        first_event_ids = owned_event_ids[:split_at]
        second_event_ids = owned_event_ids[split_at:]
        if owned_event_ids and not exact_event_partition(
            tuple(owned_event_ids), tuple(first_event_ids), tuple(second_event_ids),
        ):
            return await retry_same_scope([{
                "code": "indivisible_event_scope",
                "message": "当前正式事件不能无损拆成两个连续范围",
            }])

        def source_events(values: list[str]) -> tuple[str, ...]:
            return tuple(dict.fromkeys(value.split("/", 1)[0] for value in values))

        def child_scope(values: list[str], label: str) -> str:
            action_lines = [
                line.strip()
                for line in contract.scope.splitlines()
                if any(beat_id in line for beat_id in values)
            ]
            return label + "\n" + "\n".join(
                action_lines or [f"{beat_id}：仅执行该原子节拍" for beat_id in values]
            )

        child_authority = prompt.split("\n\n本段原子节拍契约：", 1)[0].rstrip() + (
            "\n\n当前为自动拆分后的原子子任务；CURRENT_TASK_CONTRACT 是唯一可执行范围。"
            "父任务只提供不可变故事背景，不授权执行父任务其余节拍。"
        )

        self.db.add_run_event(
            run_id, "warning", "draft_task_split",
            (
                "正文正常结束但篇幅不足，已按本段事件和因果推进自动拆分"
                if reason == "normal_finish_underlength"
                else "单次正文子任务无法完整返回，已按本段事件和因果推进自动拆分"
            ),
            stage="draft", metadata={
                "suffix": suffix, "depth": depth + 1, "target_characters": target,
                "target_range": list(target_bounds(target)),
                "subtasks": 2, "reason": reason,
                "han_characters": han_characters,
                "issue_codes": [
                    "underlength" if reason == "normal_finish_underlength"
                    else "output_limit"
                ],
                "event_ids": owned_event_ids,
            },
        )
        first_target = max(400, target // 2)
        first_contract = DraftTaskContract(
            authority_sha256=contract.authority_sha256,
            task_id=f"{contract.task_id}/sub-1",
            parent_task_id=contract.task_id,
            depth=depth + 1,
            target_han=first_target,
            event_ids=source_events(first_event_ids),
            scope=child_scope(first_event_ids, "内部子任务 1/2：只完成以下节拍"),
            entry_state=contract.entry_state,
            exit_requirement="在当前事件范围结束处留下自然交接，不总结且不进入第二子任务事件",
            execution_manifest_sha256=contract.execution_manifest_sha256,
            beat_ids=tuple(first_event_ids) if contract.beat_ids else (),
            viewpoint=contract.viewpoint,
            prohibited_future_beat_ids=tuple(dict.fromkeys([
                *second_event_ids, *contract.prohibited_future_beat_ids,
            ])) if contract.beat_ids else (),
        )
        first = await self._draft_short_segment_task(
            run_id, run_path, project, constraints,
            child_authority,
            suffix=f"{suffix}-sub-1", target=first_target,
            previous_parts=previous_parts, event_ids=first_event_ids,
            location_catalog=location_catalog, depth=depth + 1,
            contract=first_contract, node_sink=node_sink,
            semantic_all_event_ids=semantic_all_event_ids,
            semantic_receipt_sink=semantic_receipt_sink,
        )
        first_han = effective_han_characters(first)
        second_target = residual_target(target, first_han)
        first_hash = hashlib.sha256(first.strip().encode("utf-8")).hexdigest()
        second_contract = DraftTaskContract(
            authority_sha256=contract.authority_sha256,
            task_id=f"{contract.task_id}/sub-2",
            parent_task_id=contract.task_id,
            depth=depth + 1,
            target_han=second_target,
            event_ids=source_events(second_event_ids),
            scope=child_scope(second_event_ids, "内部子任务 2/2：只完成以下节拍并抵达父段出口"),
            entry_state=(
                f"承接已验收前半，内容哈希 {first_hash}。前半结尾：\n{first[-1200:]}"
            ),
            exit_requirement=contract.exit_requirement,
            previous_sibling_sha256=first_hash,
            execution_manifest_sha256=contract.execution_manifest_sha256,
            beat_ids=tuple(second_event_ids) if contract.beat_ids else (),
            viewpoint=contract.viewpoint,
            prohibited_future_beat_ids=contract.prohibited_future_beat_ids,
        )
        second = await self._draft_short_segment_task(
            run_id, run_path, project, constraints,
            child_authority,
            suffix=f"{suffix}-sub-2", target=second_target,
            previous_parts=[*previous_parts, first], event_ids=second_event_ids,
            location_catalog=location_catalog, depth=depth + 1,
            contract=second_contract, node_sink=node_sink,
            semantic_all_event_ids=semantic_all_event_ids,
            semantic_receipt_sink=semantic_receipt_sink,
        )
        combined = f"{first.strip()}\n\n{second.strip()}"
        remaining = self._draft_segment_issues(
            combined, target, previous_parts, location_catalog,
        )
        if remaining:
            return await retry_same_scope([{
                "code": "split_parent_contract_failed",
                "message": str(item),
            } for item in remaining])
        self.db.add_run_event(
            run_id, "success", "draft_task_split_completed",
            "自动拆分后的两个正文子任务已通过父段完整性与衔接检查",
            stage="draft", metadata={
                "suffix": suffix,
                "parent_task_id": contract.task_id,
                "authority_sha256": contract.authority_sha256,
                "child_targets": [first_target, second_target],
                "child_event_ids": [first_event_ids, second_event_ids],
                "child_sha256": [
                    hashlib.sha256(first.strip().encode("utf-8")).hexdigest(),
                    hashlib.sha256(second.strip().encode("utf-8")).hexdigest(),
                ],
                "combined_sha256": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
            },
        )
        return await accept_or_retry(combined)

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
        execution_manifest = None
        source_draft_integrity: dict = {}
        try:
            candidate_manifest = parse_execution_manifest(json.loads(
                (run_path / "outputs" / "short-execution-index.json").read_text(
                    encoding="utf-8",
                ),
            ))
            source_draft_integrity = json.loads(
                (run_path / "outputs" / "draft-integrity.json").read_text(
                    encoding="utf-8",
                )
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            candidate_manifest = None
            source_draft_integrity = {}
        if (
            candidate_manifest is not None
            and candidate_manifest.status == "ready"
            and not execution_manifest_receipt_binding_issues(candidate_manifest)
            and len(candidate_manifest.segments) == len(original_parts)
            and source_draft_integrity.get("status") == "passed"
            and source_draft_integrity.get("execution_manifest_sha256")
            == execution_manifest_sha256(candidate_manifest)
            and source_draft_integrity.get("draft_sha256")
            == hashlib.sha256(text.encode("utf-8")).hexdigest()
        ):
            execution_manifest = candidate_manifest

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
        part_spans = self._polish_part_spans(text, parts)
        narrative_ledger = (
            self._analyze_manuscript(
                text, run_path, project, f"polish-source{suffix}",
            ).get("narrative_ledger", {})
            if recovery_depth == 0 else build_narrative_ledger(text)
        )
        revision_plan = None
        compacted_findings: dict | None = None
        event_path = run_path / "outputs" / "segment-events.json"
        try:
            event_assignments = json.loads(event_path.read_text(encoding="utf-8")).get(
                "segments", [],
            )
        except (OSError, json.JSONDecodeError, AttributeError):
            event_assignments = []
        story_map = segment_map(original_parts, event_assignments=event_assignments)
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
                compacted_findings = compact_polish_findings(json.loads(findings))
                findings = json.dumps(compacted_findings, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError, AttributeError):
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
        accepted_history_metrics: list[dict[str, float]] = []
        prose_policy = load_prose_validation_policy(project.path)
        primary_circuit_open = any(
            event["event_type"] == "polish_circuit_opened"
            for event in self.db.list_run_events(run_id)
        )
        preserved_segments = 0
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
        previous_handoff_state = ""
        part_authority_hashes: dict[int, str] = {}
        for index, part in enumerate(parts, 1):
            group = part_groups[index - 1]
            if revision_plan and group not in revision_plan["target_segments"]:
                polished_parts.append(part)
                previous_handoff_state = self._polish_exit_state(part)
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
            start, end = part_spans[index - 1]
            window_findings = (
                filter_polish_findings_for_segment(compacted_findings, part)
                if compacted_findings is not None else None
            )
            narrative_context = self._polish_narrative_context(
                narrative_ledger, part, start, end, previous_handoff_state,
            )
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
            voice = character_fingerprints(project.path, part)
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
            findings_for_window = (
                json.dumps(window_findings, ensure_ascii=False)
                if window_findings is not None else findings
            )
            plan_context = (
                f"GLOBAL FACTS AND LOCKS:\n{json.dumps(revision_plan['global_facts'], ensure_ascii=False)}\n\n"
                f"TASKS FOR THIS SEGMENT:\n{json.dumps(tasks, ensure_ascii=False)}\n\n"
                f"DETERMINISTIC CHECKS:\n{json.dumps(revision_plan['checks'], ensure_ascii=False)}\n\n"
                f"COMPACT FULL STORY MAP:\n{json.dumps(story_map, ensure_ascii=False)}\n\n"
                if revision_plan else (
                    f"STRUCTURED FINDINGS FOR THIS WINDOW:\n{findings_for_window}\n\n"
                    f"NARRATIVE STATE FOR THIS WINDOW:\n"
                    f"{json.dumps(narrative_context, ensure_ascii=False)}\n\n"
                )
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
            story_entry = story_map[group - 1] if 0 < group <= len(story_map) else {}
            protected_authority = [{
                "id": lock.get("id"),
                "label": lock.get("label"),
                "mode": lock.get("mode"),
                "allow_next_change": bool(lock.get("allow_next_change")),
            } for lock in passage_locks]
            ending = authoritative_state.get("ending")
            authority_packet = build_polish_authority_packet(
                source=part,
                event_ids=story_entry.get("event_ids", []),
                causal_goal=str(story_entry.get("handoff") or ""),
                previous_exit=previous_handoff_state or previous_context,
                next_entry=next_context,
                character_state={
                    "states": authoritative_state.get("character_states", {}),
                    "voice": voice,
                },
                locked_facts=[
                    *authoritative_state.get("locked_facts", []),
                    *authoritative_state.get("confirmed_facts", []),
                    *global_facts,
                ],
                ending_constraints=[ending] if ending else [],
                narrative_state=narrative_context,
                style_rules=[style_profile],
                protected_passages=protected_authority,
                allowed_scope={
                    "segment": current_targeted_context["segment"],
                    "minimum_characters": minimum_characters,
                    "maximum_characters": maximum_characters,
                    "edit_rule": revision_rule,
                },
            )
            authority_hash = authority_packet_sha256(authority_packet)
            part_authority_hashes[index] = authority_hash
            if targeted and (revision_plan or targeted_context):
                prompt = (
                    f"STYLE PROFILE:\n{style_profile}\n\n"
                    f"RELEVANT CHARACTER VOICES:\n"
                    f"{voice}\n\n"
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
                    "POLISH THE CURRENT MANUSCRIPT SEGMENT. Return revised prose only.\n"
                    f"EDIT PERMISSION: {revision_rule + length_contract}\n\n"
                    f"LOCAL PROSE FINDINGS:\n"
                    f"{json.dumps(local_report['findings'], ensure_ascii=False)}\n\n"
                    + plan_context
                    + render_polish_authority_packet(authority_packet)
                )
            compact_prompt = self._compact_polish_prompt(
                authority_packet=authority_packet,
                local_findings=local_report["findings"],
                review_findings=window_findings,
            )
            part_suffix = f"{suffix}-part-{index:02d}"
            cached = self._load_polish_checkpoint(
                checkpoint_root, index, part, retry_signature,
                authority_hash=authority_hash,
            )
            if cached is not None:
                polished_parts.append(cached)
                accepted_history_metrics.append(prose_metrics(cached))
                previous_handoff_state = self._polish_exit_state(cached)
                self.db.add_run_event(
                    run_id, "success", "polish_checkpoint_reused",
                    f"润色第 {index}/{len(parts)} 段已从检查点恢复",
                    stage="polish", metadata={"segment": index, "route": "checkpoint"},
                )
                if not targeted:
                    self.db.add_run_event(
                        run_id, "info", "polish_segment_progress",
                        f"已完成 {index} / {len(parts)} 段，其中 {preserved_segments} 段保留原文",
                        stage="polish", metadata={
                            "segment": index, "total": len(parts),
                            "completed": index, "preserved": preserved_segments,
                        },
                    )
                continue
            priority = bool(targeted or index in {1, len(parts)} or local_report["findings"])
            prefer_configured = bool(
                targeted and configured_fallback
                and (primary_circuit_open or not priority)
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
            ordinary_preserved = False
            compact_recovery_used = False
            ordinary_input_tokens = 0
            split_recovery_used = False

            async def split_failed_segment(exc: Exception) -> str:
                nonlocal ordinary_preserved, split_recovery_used
                children = self._split_failed_polish_segment(part)
                if recovery_depth >= 2 or children is None:
                    if not targeted:
                        ordinary_preserved = True
                        self.db.add_run_event(
                            run_id, "warning", "polish_capacity_preserved",
                            "当前父段没有可安全拆分的段落边界，已保留原文并继续",
                            stage="polish", metadata={
                                "segment": index, "characters": len(part),
                                "split_depth": recovery_depth,
                                "error": describe_error(exc)[:500],
                                "failure_class": classify_model_failure(exc),
                            },
                        )
                        self.db.add_run_event(
                            run_id, "warning", "polish_segment_preserved",
                            "当前片段无法安全拆分，已保留完整父段并继续",
                            stage="polish", metadata={
                                "segment": index, "failure_kind": classify_model_failure(exc),
                            },
                        )
                        return part
                    raise exc
                self.db.add_run_event(
                    run_id, "warning", "polish_segment_split",
                    "模型输出受限，正在拆分当前片段后重试",
                    stage="polish", metadata={
                        "segment": index, "characters": len(part),
                        "child_characters": [len(child) for child in children],
                        "split_depth": recovery_depth + 1, "failed_route": route,
                        "error": describe_error(exc),
                        "failure_class": classify_model_failure(exc),
                    },
                )
                child_suffix = f"{part_suffix}-split-{recovery_depth + 1}"
                recovered = await self._polish_short_segments(
                    run_id, run_path, project, constraints,
                    self.SHORT_SEGMENT_SEPARATOR.join(children), findings_for_window,
                    suffix=child_suffix,
                    structural=False, recovery_depth=recovery_depth + 1,
                    recovery_rule=revision_rule,
                    targeted_context=current_targeted_context if targeted else None,
                )
                child_checkpoint_root = (
                    run_path / "outputs" / "polish-checkpoints" / child_suffix.strip("-")
                )
                child_checkpoints = []
                for child_index in range(1, len(children) + 1):
                    checkpoint_path = child_checkpoint_root / f"part-{child_index:02d}.json"
                    try:
                        child_checkpoints.append(json.loads(
                            checkpoint_path.read_text(encoding="utf-8")
                        ))
                    except (OSError, json.JSONDecodeError):
                        child_checkpoints.append({})
                if not all(item.get("accepted") is True for item in child_checkpoints):
                    ordinary_preserved = True
                    self.db.add_run_event(
                        run_id, "warning", "polish_split_child_rejected",
                        "拆分后的子段没有全部通过验收，整个父段已保留原文",
                        stage="polish", metadata={
                            "segment": index,
                            "child_statuses": [item.get("status") for item in child_checkpoints],
                        },
                    )
                    return part
                split_recovery_used = True
                return recovered.replace(self.SHORT_SEGMENT_SEPARATOR, "\n\n")

            try:
                if not targeted:
                    (polished_part, ordinary_preserved, compact_recovery_used,
                     _ordinary_fallback_used,
                     ordinary_input_tokens) = await self._ordinary_polish_segment(
                        run_id, run_path, project, constraints, part, prompt,
                        compact_prompt, part_suffix, minimum_characters,
                        maximum_characters, configured_fallback, {
                            "segment": index, "total": len(parts),
                            "completed": index - 1,
                            "preserved": preserved_segments,
                        },
                    )
                else:
                    polished_part = await self._stage(
                        run_id, run_path, project, "polish", constraints, prompt,
                        suffix=part_suffix, allow_tools=False,
                        prefer_configured_fallback=prefer_configured,
                        output_source_characters=len(part),
                        targeted_retry=True,
                    )
                if (targeted
                        and getattr(polished_part, "receipt", {}).get("fallback_used")):
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
                failure_kind = classify_model_failure(exc)
                if failure_kind == "provider_rejection":
                    raise
                if failure_kind in {"input_context_overflow", "output_limit"}:
                    polished_part = await split_failed_segment(exc)
                elif failure_kind == "transport_interrupted":
                    ordinary_preserved = True
                    polished_part = part
                    self.db.add_run_event(
                        run_id, "warning", "polish_segment_preserved",
                        "润色路由因网络波动全部失败，已保留当前父段且不拆分正文",
                        stage="polish", metadata={
                            "segment": index, "error": describe_error(exc)[:500],
                        },
                    )
                else:
                    raise
            round_input_tokens += (
                int(getattr(polished_part, "receipt", {}).get("input_tokens", 0) or 0)
                if targeted else ordinary_input_tokens
            )
            required = re.findall(r"(?m)^##\s+(.+)$", voice)
            assessment = assess_polish_candidate(
                part, polished_part, required,
                minimum_ratio=minimum_ratio, maximum_ratio=maximum_ratio,
                policy=prose_policy,
                history_metrics=accepted_history_metrics,
                narrative_context=narrative_context,
            )
            if targeted_group_failed:
                assessment["accepted"] = False
                assessment["reasons"].append("targeted_model_routes_failed")
            if ordinary_preserved:
                assessment["accepted"] = False
                assessment["reasons"].append("model_routes_failed")
            if split_recovery_used:
                _, duplicate_blocks = remove_consecutive_duplicate_blocks(polished_part)
                if duplicate_blocks:
                    assessment["accepted"] = False
                    assessment["hard_reasons"].append("split_parent_duplicate")
                    assessment["reasons"].append("split_parent_duplicate")
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
            if (not assessment["accepted"]
                    and assessment.get("disposition") == "targeted_repair"
                    and not assessment.get("hard_reasons")
                    and not locked_failures and not passage_validation["conflicts"]
                    and not ordinary_preserved and not split_recovery_used):
                signal_codes = {
                    code
                    for signal in assessment.get("soft_signals", [])
                    for code in signal.get("codes", [signal.get("code")])
                    if code
                }
                evidence_findings = [
                    finding for finding in local_report["findings"]
                    if finding.get("code") in signal_codes
                ]
                repair_advisory = {
                    "soft_signals": assessment.get("soft_signals", []),
                    "evidence_findings": evidence_findings,
                    "instruction": (
                        "Edit only the evidenced local spans. Preserve all other wording, "
                        "events, facts, transitions, and length."
                    ),
                }
                repair_prompt = (
                    "TARGETED LOCAL PROSE REPAIR. Return revised prose only. Do not rewrite "
                    "unrelated sentences.\n\n"
                    + render_polish_authority_packet(
                        authority_packet, advisory=repair_advisory,
                    )
                )
                repair_compact_prompt = (
                    "TARGETED LOCAL PROSE REPAIR UNDER INPUT PRESSURE. Return revised prose only.\n\n"
                    + render_polish_authority_packet(
                        authority_packet,
                        advisory={"soft_signals": assessment.get("soft_signals", [])},
                    )
                )
                self.db.add_run_event(
                    run_id, "warning", "polish_targeted_repair",
                    f"润色第 {index}/{len(parts)} 段仅对有证据的局部问题定向修复",
                    stage="polish", metadata={
                        "segment": index,
                        "signal_families": assessment.get("signal_families", []),
                        "signal_codes": sorted(signal_codes),
                        "raw_metrics": {
                            "source": local_report.get("metrics", {}),
                            "candidate": assessment.get("diagnostics", {}).get("metrics", {}),
                        },
                        "baseline": assessment.get("baseline", {}),
                        "policy_source_ids": list(prose_policy.source_ids),
                        "evidence_spans": evidence_findings,
                        "authority_hash": authority_hash,
                    },
                )
                if signal_codes.intersection(rhythm_reasons):
                    self.db.add_run_event(
                        run_id, "warning", "polish_rhythm_retry",
                        f"润色第 {index}/{len(parts)} 段韵律软信号触发局部修复",
                        stage="polish", metadata={
                            "segment": index, "reasons": sorted(
                                signal_codes.intersection(rhythm_reasons)
                            ),
                        },
                    )
                try:
                    (repair_candidate, repair_preserved, repair_compact_used,
                     _repair_fallback_used, repair_input_tokens) = (
                        await self._ordinary_polish_segment(
                            run_id, run_path, project, constraints, part,
                            repair_prompt, repair_compact_prompt,
                            f"{part_suffix}-targeted-repair",
                            minimum_characters, maximum_characters,
                            configured_fallback, {
                                "segment": index, "total": len(parts),
                                "recovery": "targeted_repair",
                            },
                        )
                    )
                    round_input_tokens += repair_input_tokens
                    ordinary_preserved = bool(ordinary_preserved or repair_preserved)
                    compact_recovery_used = bool(
                        compact_recovery_used or repair_compact_used
                    )
                    polished_part = repair_candidate
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    failure_kind = classify_model_failure(exc)
                    if failure_kind == "provider_rejection":
                        raise
                    if failure_kind in {"input_context_overflow", "output_limit"}:
                        polished_part = await split_failed_segment(exc)
                    else:
                        ordinary_preserved = True
                        polished_part = part
                assessment = assess_polish_candidate(
                    part, polished_part, required,
                    minimum_ratio=minimum_ratio, maximum_ratio=maximum_ratio,
                    policy=prose_policy,
                    history_metrics=accepted_history_metrics,
                    narrative_context=narrative_context,
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
                if ordinary_preserved:
                    assessment["accepted"] = False
                    if "model_routes_failed" not in assessment["reasons"]:
                        assessment["reasons"].append("model_routes_failed")
            if ordinary_preserved:
                assessment["accepted"] = False
                if "model_routes_failed" not in assessment["reasons"]:
                    assessment["reasons"].append("model_routes_failed")
            accepted = bool(assessment["accepted"])
            if accepted and assessment.get("disposition") == "pass_with_style_allowance":
                self.db.add_run_event(
                    run_id, "success", "polish_style_allowance",
                    f"润色第 {index}/{len(parts)} 段按项目文风规则保留局部节奏",
                    stage="polish", metadata={
                        "segment": index,
                        "style_allowances": assessment.get("style_allowances", []),
                        "policy_source_ids": list(prose_policy.source_ids),
                        "raw_metrics": {
                            "source": local_report.get("metrics", {}),
                            "candidate": assessment.get("diagnostics", {}).get("metrics", {}),
                        },
                        "baseline": assessment.get("baseline", {}),
                        "authority_hash": authority_hash,
                    },
                )
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
                if split_recovery_used:
                    self.db.add_run_event(
                        run_id, "warning", "polish_split_parent_rejected",
                        "拆分子段合并后未通过父段整体验收，已原子回退为父段原文",
                        stage="polish", metadata={
                            "segment": index, "reasons": assessment["reasons"],
                            "authority_hash": authority_hash,
                        },
                    )
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
            if accepted:
                accepted_history_metrics.append(prose_metrics(polished_part))
            previous_handoff_state = self._polish_exit_state(polished_part)
            change_evidence = diff_manuscripts(
                part, polished_part,
                analyze_manuscript(part, nlp_analyze=None),
                analyze_manuscript(polished_part, nlp_analyze=None),
            )
            if accepted:
                self._save_polish_checkpoint(
                    checkpoint_root, index, part, polished_part,
                    change_evidence=change_evidence,
                    authority_hash=authority_hash,
                )
            elif not targeted:
                if not ordinary_preserved:
                    self.db.add_run_event(
                        run_id, "warning", "polish_segment_preserved",
                        "本段未完成精修，已保留原文并继续",
                        stage="polish", metadata={
                            "segment": index, "total": len(parts),
                            "completed": index, "preserved": preserved_segments + 1,
                            "reasons": assessment["reasons"],
                        },
                    )
                preserved_segments += 1
                self._save_polish_checkpoint(
                    checkpoint_root, index, part, part,
                    status="preserved_source", retry_signature=retry_signature,
                    accepted=False,
                    change_evidence=change_evidence,
                    authority_hash=authority_hash,
                )
            if not targeted:
                self.db.add_run_event(
                    run_id, "info", "polish_segment_progress",
                    f"已完成 {index} / {len(parts)} 段，其中 {preserved_segments} 段保留原文",
                    stage="polish", metadata={
                        "segment": index, "total": len(parts),
                        "completed": index, "preserved": preserved_segments,
                    },
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
        if execution_manifest is not None:
            candidate_groups = self._split_segments(polished)
            if len(candidate_groups) != len(original_parts):
                candidate_groups = list(original_parts)
                polished = text
                self.db.add_run_event(
                    run_id, "warning", "polish_semantic_gate_failed",
                    "润色结果改变了正式分段边界，已保留验收前原文",
                    stage="polish", metadata={
                        "expected_segments": len(original_parts),
                        "actual_segments": len(self._split_segments(polished)),
                    },
                )
            beat_by_id = {
                beat.beat_id: beat for beat in execution_manifest.beats
            }
            all_beat_ids = [beat.beat_id for beat in execution_manifest.beats]
            source_receipts = source_draft_integrity.get(
                "semantic_segment_receipts",
            )
            source_receipts = (
                source_receipts if isinstance(source_receipts, list) else []
            )
            semantic_receipts: list[dict] = []
            for group, (source_group, candidate_group, manifest_segment) in enumerate(
                zip(original_parts, candidate_groups, execution_manifest.segments), 1,
            ):
                beat_ids = list(manifest_segment.beat_ids)
                contract = DraftTaskContract(
                    authority_sha256=str(
                        source_draft_integrity.get("authority_sha256")
                        or execution_manifest.authority_sha256
                    ),
                    task_id=f"segment-{group:02d}",
                    parent_task_id="",
                    depth=0,
                    target_han=max(1, effective_han_characters(candidate_group)),
                    event_ids=tuple(dict.fromkeys(
                        beat_by_id[beat_id].source_event_id for beat_id in beat_ids
                    )),
                    scope="\n".join(
                        f"{beat_id}：{beat_by_id[beat_id].action}"
                        for beat_id in beat_ids
                    ),
                    entry_state="；".join(
                        item.state for item in manifest_segment.entry_state
                    ),
                    exit_requirement="；".join(
                        item.state for item in manifest_segment.exit_state
                    ),
                    execution_manifest_sha256=execution_manifest_sha256(
                        execution_manifest,
                    ),
                    beat_ids=tuple(beat_ids),
                    viewpoint=str(project.metadata.get("pov") or ""),
                    prohibited_future_beat_ids=(
                        manifest_segment.prohibited_future_beat_ids
                    ),
                )
                receipt = None
                if candidate_group == source_group and group <= len(source_receipts):
                    try:
                        receipt = validate_semantic_receipt(
                            contract, candidate_group, source_receipts[group - 1],
                        )
                    except ValueError:
                        receipt = None
                if receipt is None:
                    try:
                        receipt = await self._verify_draft_semantic_node(
                            run_id, run_path, project, constraints, contract,
                            candidate_group,
                            [beat_id for beat_id in all_beat_ids if beat_id not in beat_ids],
                            suffix=f"{suffix}-polish-segment-{group:02d}",
                            failure_stage="polish",
                        )
                    except DraftSemanticValidationError as exc:
                        outside_beat_ids = [
                            beat_id for beat_id in all_beat_ids
                            if beat_id not in beat_ids
                        ]
                        repaired = await self._repair_polish_semantic_segment(
                            run_id, run_path, project, constraints, contract,
                            source_group, candidate_group, outside_beat_ids, exc,
                            suffix=f"{suffix}-polish-segment-{group:02d}",
                        )
                        group_part_indexes = [
                            part_index
                            for part_index, part_group in enumerate(part_groups, 1)
                            if part_group == group
                        ]
                        if repaired is not None:
                            repaired_group, receipt = repaired
                            candidate_groups[group - 1] = repaired_group
                            if len(group_part_indexes) == 1:
                                part_index = group_part_indexes[0]
                                self._save_polish_checkpoint(
                                    checkpoint_root, part_index,
                                    parts[part_index - 1], repaired_group,
                                    status="semantic_repaired",
                                    retry_signature=retry_signature, accepted=True,
                                    authority_hash=part_authority_hashes.get(part_index),
                                )
                            else:
                                for part_index in group_part_indexes:
                                    self._save_polish_checkpoint(
                                        checkpoint_root, part_index,
                                        parts[part_index - 1], parts[part_index - 1],
                                        status="semantic_repaired_requires_replay",
                                        retry_signature=retry_signature, accepted=False,
                                        authority_hash=part_authority_hashes.get(part_index),
                                    )
                        else:
                            candidate_groups[group - 1] = source_group
                            for part_index in group_part_indexes:
                                self._save_polish_checkpoint(
                                    checkpoint_root, part_index,
                                    parts[part_index - 1], parts[part_index - 1],
                                    status="semantic_drift_preserved",
                                    retry_signature=retry_signature, accepted=False,
                                    authority_hash=part_authority_hashes.get(part_index),
                                )
                            try:
                                receipt = validate_semantic_receipt(
                                    contract, source_group,
                                    source_receipts[group - 1],
                                )
                            except (IndexError, ValueError):
                                receipt = await self._verify_draft_semantic_node(
                                    run_id, run_path, project, constraints, contract,
                                    source_group, outside_beat_ids,
                                    suffix=f"{suffix}-polish-source-{group:02d}",
                                    failure_stage="polish",
                                )
                            self.db.add_run_event(
                                run_id, "warning", "polish_segment_preserved",
                                "润色候选两次语义修复仍未通过，已恢复完整验收原段",
                                stage="polish", metadata={
                                    "segment": group, "issues": exc.issues,
                                },
                            )
                semantic_receipts.append(receipt)
            polished = self.SHORT_SEGMENT_SEPARATOR.join(candidate_groups)
            expected_beat_ids = [
                beat_id
                for segment in execution_manifest.segments
                for beat_id in segment.beat_ids
            ]
            whole_receipt = await self._verify_whole_draft_semantics(
                run_id, run_path, project, constraints,
                str(source_draft_integrity.get("authority_sha256") or ""),
                polished, candidate_groups, expected_beat_ids, semantic_receipts,
                failure_stage="polish",
            )
            segment_integrity = []
            previous_hash = ""
            for group, (candidate_group, manifest_segment) in enumerate(
                zip(candidate_groups, execution_manifest.segments), 1,
            ):
                text_hash = hashlib.sha256(candidate_group.encode("utf-8")).hexdigest()
                segment_integrity.append({
                    "segment": group,
                    "event_ids": list(manifest_segment.beat_ids),
                    "handoff": "；".join(
                        item.state for item in manifest_segment.exit_state
                    ),
                    "han_characters": effective_han_characters(candidate_group),
                    "previous_sha256": previous_hash,
                    "text_sha256": text_hash,
                })
                previous_hash = text_hash
            polish_integrity = {
                **source_draft_integrity,
                "version": 4,
                "status": "passed",
                "source_draft_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "draft_sha256": hashlib.sha256(polished.encode("utf-8")).hexdigest(),
                "segments": segment_integrity,
                "accepted_event_ids": expected_beat_ids,
                "semantic_segment_receipts": semantic_receipts,
                "whole_semantic_receipt": whole_receipt,
                "issues": [],
            }
            atomic_write(
                run_path / "outputs" / f"polish-integrity{suffix}.json",
                json.dumps(polish_integrity, ensure_ascii=False, indent=2),
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
                except (json.JSONDecodeError, ValueError):
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
    def _stage_context_labels(constraints: str, user: str = "") -> list[str]:
        combined = f"{constraints}\n{user}"
        markers = (
            ("CONFIRMED STORY FACTS", "已确认事实"),
            ("Program-enforced locked story facts", "锁定事实"),
            ("Current Confirmed Outline", "正式大纲"),
            ("Confirmed Long-form Execution Plan", "长篇执行计划"),
            ("Executable Prose Baseline", "基础文笔"),
            ("Confirmed Creative Blueprint", "创作蓝图"),
            ("Short Story Causal Chain", "七步剧情结构"),
            ("Advisory Market Baseline", "同类市场基线"),
            ("Character Voice Profiles", "人物说话方式"),
            ("RELEVANT CHARACTER VOICES", "人物说话方式"),
            ("Character Knowledge Boundaries", "人物认知边界"),
            ("Scene Briefs", "场景安排"),
            ("COMPACT FULL STORY MAP", "全文剧情位置图"),
            ("NARRATIVE STATE FOR THIS WINDOW", "伏笔与场景状态"),
            ("PROJECT STYLE PROFILE", "作品文风"),
            ("STYLE PROFILE", "作品文风"),
        )
        return list(dict.fromkeys(
            label for marker, label in markers if marker in combined
        ))

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

    def _stage_story_skeleton(
        self, project: Project, constraints: str, run_path: Path | None = None,
    ) -> str:
        state = self.story_states.ensure(project.id, project.path).data
        outline = state.get("outline") if isinstance(state.get("outline"), dict) else {}
        marker = "# Short Story Causal Chain"
        causal = ""
        if marker in constraints:
            causal = constraints.split(marker, 1)[1].strip()
        execution_manifest = None
        draft_integrity = None
        if run_path is not None:
            try:
                execution_manifest = json.loads(
                    (run_path / "outputs" / "short-execution-index.json").read_text(
                        encoding="utf-8",
                    )
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                execution_manifest = None
            if isinstance(execution_manifest, dict):
                try:
                    parsed_manifest = parse_execution_manifest(execution_manifest)
                except (TypeError, ValueError):
                    execution_manifest = None
                else:
                    if (
                        parsed_manifest.status != "ready"
                        or execution_manifest_receipt_binding_issues(parsed_manifest)
                    ):
                        execution_manifest = None
                    else:
                        receipt = parsed_manifest.semantic_receipt
                        execution_manifest = {
                            **execution_manifest,
                            "semantic_receipt": {
                                "formal_plot_unchanged": receipt.get(
                                    "formal_plot_unchanged"
                                ),
                                "summary": receipt.get("summary"),
                            },
                        }
            try:
                draft_integrity = json.loads(
                    (run_path / "outputs" / "draft-integrity.json").read_text(
                        encoding="utf-8",
                    )
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                draft_integrity = None
            if isinstance(draft_integrity, dict):
                draft_integrity = {
                    key: draft_integrity.get(key)
                    for key in (
                        "version", "status", "authority_sha256",
                        "execution_manifest_sha256", "draft_sha256",
                        "expected_event_ids", "accepted_event_ids", "segments", "issues",
                    )
                }
        payload = {
            "project": {
                key: project.metadata.get(key)
                for key in (
                    "title", "genre", "premise", "pov", "tone",
                    "target_words", "must_include", "must_avoid",
                )
                if project.metadata.get(key) not in (None, "")
            },
            "formal_outline": str(outline.get("content") or ""),
            "confirmed_facts": state.get("confirmed_facts", []),
            "locked_facts": state.get("locked_facts", []),
            "ending": state.get("ending"),
            "character_states": state.get("character_states", {}),
            "causal_chain": causal,
            "execution_manifest": execution_manifest,
            "draft_integrity": draft_integrity,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _stage_contract_envelope(stage: str, user: str) -> dict:
        envelope = {
            "stage": stage,
            "user_sha256": hashlib.sha256(user.encode("utf-8")).hexdigest(),
        }
        for pattern in (
            r"CURRENT_TASK_CONTRACT:\s*(\{[^\n]+\})",
            r"TASK CONTRACT:\s*(\{[^\n]+\})",
        ):
            match = re.search(pattern, user)
            if not match:
                continue
            try:
                contract = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if isinstance(contract, dict):
                envelope.update({
                    key: contract.get(key)
                    for key in (
                        "task_id", "beat_ids", "event_ids", "entry_state",
                        "exit_requirement", "prohibited_future_beat_ids",
                        "execution_manifest_sha256", "viewpoint",
                    )
                    if contract.get(key) not in (None, "", [], {})
                })
            break
        return envelope

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
                     targeted_retry: bool = False,
                     primary_only: bool = False,
                     retry_polish_output_limit: bool = True,
                     expected_output_characters: int | None = None,
                     completion_check: Callable[[str], bool] | None = None,
                     compact_input: bool = False) -> str:
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
            layered_context = stage in {
                "planning", "draft", "polish", "review",
                "revision_plan", "final_review",
            }
            gateway_role = model_role or stage
            preliminary_output_budget = self._output_budget_for_call(
                stage, output_source_characters, gateway_role,
                prefer_configured_fallback,
                expected_output_characters=expected_output_characters,
            )
            compact_context = layered_context
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
                model_constraints = self.constraint_prompts.compact_for_stage(
                    source_constraints, stage=stage, focus=user,
                )
            style = (
                f"\n\nPROJECT STYLE PROFILE:\n{ensure_style_profile(project)}"
                if stage == "draft"
                and project.metadata.get("style_sample_scope") == "draft_and_polish"
                else ""
            )
            context_packet = None
            if layered_context:
                story_state = self.story_states.ensure(project.id, project.path).data
                explicit_invariants = {
                    "viewpoint": project.metadata.get("pov"),
                    "tone": project.metadata.get("tone"),
                    "must_include": project.metadata.get("must_include"),
                    "must_avoid": project.metadata.get("must_avoid"),
                    "confirmed_ending": story_state.get("ending"),
                    "knowledge_boundaries": story_state.get("character_states"),
                    "formal_plot_unchanged": "不得改写已经确认的正式大纲和因果结局。",
                    "whole_story_logic": (
                        "任何拆分、重试、润色、审核和返修都不得破坏整篇因果、人物状态、"
                        "时间线、伏笔兑现和结局逻辑。"
                    ),
                    "atomic_beat_ownership": (
                        "当前任务只能执行自己拥有的原子节拍，不得提前执行后续节拍或重复已完成节拍。"
                    ),
                }
                advisory = (
                    model_constraints + "\n\nSkill instructions (advisory):\n"
                    + model_skill_prompt + style
                )
                context_packet = build_stage_context_packet(
                    stage=stage,
                    current_contract=self._stage_contract_envelope(stage, user),
                    constraints=source_constraints,
                    skill_prompt=skill_run.prompt,
                    explicit_invariants=explicit_invariants,
                    relevant_context=user,
                    global_skeleton=self._stage_story_skeleton(
                        project, source_constraints, run_path,
                    ),
                    advisory=advisory,
                    output_reserve=preliminary_output_budget or 0,
                    advisory_max_chars=3000 if compact_input else 8000,
                )
                coverage_issues = validate_rule_coverage(context_packet)
                if coverage_issues:
                    raise ValueError(
                        "模型上下文缺少强制叙事规则："
                        + json.dumps(coverage_issues, ensure_ascii=False)
                    )
                system = (
                    f"{STAGE_SYSTEM[stage]}\n\n"
                    "Skill instructions and story authority are supplied in the layered context.\n\n"
                    + render_stage_system_context(context_packet)
                )
            else:
                system = (
                    f"{STAGE_SYSTEM[stage]}\n\nHARD CONSTRAINTS:\n{model_constraints}"
                    f"\n\n{model_skill_prompt}{style}"
                )
            estimated_input_tokens = estimate_input_tokens(system + "\n" + user)
            if stage == "polish" and compact_input and not layered_context:
                model_constraints = ConstraintPromptCompactor(max_chars=4000).compact_for_stage(
                    source_constraints, stage=stage, focus=user,
                )
                model_skill_prompt = SkillPromptCompactor(max_chars=5000).compact(
                    skill_run.prompt, skill_run.receipts,
                )
                system = (
                    f"{STAGE_SYSTEM[stage]}\n\nHARD CONSTRAINTS:\n{model_constraints}"
                    f"\n\n{model_skill_prompt}{style}"
                )
                estimated_input_tokens = estimate_input_tokens(system + "\n" + user)
            provider_ceiling = self._provider_output_ceiling(
                gateway_role, prefer_configured_fallback,
            )
            output_budget = self._output_budget_for_call(
                stage, output_source_characters, gateway_role,
                prefer_configured_fallback,
                expected_output_characters=expected_output_characters,
                input_tokens=estimated_input_tokens,
            )
            if context_packet is not None:
                context_packet = replace(context_packet, metrics={
                    **context_packet.metrics,
                    "output_reserve_tokens": output_budget or 0,
                })
            context_window = self._provider_context_window(
                gateway_role, prefer_configured_fallback,
            )
            if layered_context and context_window:
                authority_input_tokens = sum(
                    item["estimated_tokens"]
                    for name, item in context_packet.metrics["layers"].items()
                    if name != "advisory"
                ) if context_packet is not None else estimated_input_tokens
                pressure = classify_input_pressure(
                    full_input_tokens=estimated_input_tokens,
                    authority_input_tokens=authority_input_tokens,
                    output_reserve=output_budget or 0,
                    context_window=context_window,
                )
                if pressure in {"compact", "split"}:
                    raise RuntimeError(
                        "input context overflow preflight: lossless story authority plus "
                        f"output reserve requires {estimated_input_tokens + (output_budget or 0)} "
                        f"tokens for context window {context_window}; topology={pressure}"
                    )
            confirmed_context = self._stage_context_labels(
                model_constraints, user + style,
            )
            self.db.add_run_event(
                run_id, "success", "skills_loaded", f"已加载 {len(skills)} 个 Skill",
                stage=stage, metadata={
                    "skills": skills,
                    "prompt_characters": len(model_skill_prompt),
                    "source_prompt_characters": len(skill_run.prompt),
                    "compact_prompt": model_skill_prompt != skill_run.prompt,
                    "compact_input": compact_input,
                    "constraint_characters": len(model_constraints),
                    "source_constraint_characters": len(source_constraints),
                    "compact_constraints": model_constraints != source_constraints,
                    "confirmed_context": confirmed_context,
                    **({
                        "context_packet_sha256": context_packet_sha256(context_packet),
                        "context_layers": context_packet.metrics["layers"],
                        "removed_duplicate_rules": context_packet.metrics[
                            "removed_duplicate_rules"
                        ],
                        "filtered_advisory_characters": context_packet.metrics[
                            "filtered_advisory_characters"
                        ],
                    } if context_packet else {}),
                },
            )
            if stage == "polish":
                self.db.add_run_event(
                    run_id, "info", "polish_input_sized",
                    "Polish request context sized before provider call",
                    stage=stage, metadata={
                        "estimated_input_tokens": estimated_input_tokens,
                        "user_characters": len(user), "system_characters": len(system),
                    },
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
            output_limit_expanded_once = False
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
                elif primary_only and hasattr(self.gateway, "complete_primary"):
                    result = await self.gateway.complete_primary(
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
            result.receipt.setdefault("requested_max_output_tokens", output_budget)
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
                result.receipt.setdefault(
                    "requested_max_output_tokens", review_retry_budget,
                )
                output_limit_expanded_once = True
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
                    result.receipt.setdefault(
                        "requested_max_output_tokens", min(8192, fallback_ceiling or 8192),
                    )
            if (retry_polish_output_limit and stage == "polish"
                    and gateway_role == "polish" and not allow_tools
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
                result.receipt.setdefault("requested_max_output_tokens", output_budget)
            if (not retry_polish_output_limit and stage == "polish"
                    and gateway_role == "polish" and output_limited(result.receipt)):
                error = RuntimeError(
                    "polish output incomplete (finish_reason=max_tokens)"
                )
                error.receipt = result.receipt
                raise error
            if output_limited(result.receipt):
                complete_at_limit = False
                if completion_check is not None:
                    try:
                        complete_at_limit = bool(completion_check(result.text))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        complete_at_limit = False
                if complete_at_limit:
                    result.receipt["completion_status"] = "complete_at_limit"
                    self.db.add_run_event(
                        run_id, "warning", "output_limit_complete",
                        f"{stage} reached the route output limit but passed an independent completeness check",
                        stage=stage, metadata={
                            "requested_max_output_tokens": result.receipt.get(
                                "requested_max_output_tokens"
                            ),
                            "model_name": result.receipt.get("model_name"),
                        },
                    )
                else:
                    actual_model = self.db.get_model(
                        str(result.receipt.get("model_id") or "")
                    ) or {}
                    if not actual_model:
                        binding = self.db.get_role_binding(gateway_role) or {}
                        selected_key = (
                            "fallback_model_id"
                            if prefer_configured_fallback
                            or result.receipt.get("fallback_used")
                            or result.receipt.get("configured_fallback_direct")
                            else "primary_model_id"
                        )
                        actual_model = self.db.get_model(
                            str(binding.get(selected_key) or "")
                        ) or {}
                    previous_budget = int(
                        result.receipt.get("requested_max_output_tokens")
                        or output_budget or 1
                    )
                    retry_budget = expanded_output_budget(
                        previous_budget,
                        input_tokens=estimated_input_tokens,
                        context_window=actual_model.get("context_window"),
                        declared_output_ceiling=actual_model.get("max_output_tokens"),
                    )
                    if (not output_limit_expanded_once
                            and retry_budget and retry_budget > previous_budget):
                        self.db.add_run_event(
                            run_id, "warning", (
                                "polish_output_limit_retry"
                                if stage == "polish" else "output_limit_expanded"
                            ),
                            f"{stage} output may be truncated; retrying the same route with more headroom",
                            stage=stage, metadata={
                                "previous_budget": previous_budget,
                                "retry_budget": retry_budget,
                                "model_name": result.receipt.get("model_name"),
                                "failure_class": "output_limit",
                            },
                        )
                        used_fallback = bool(
                            prefer_configured_fallback
                            or result.receipt.get("fallback_used")
                            or result.receipt.get("configured_fallback_direct")
                        )
                        if used_fallback and hasattr(
                            self.gateway, "complete_configured_fallback"
                        ):
                            result = await self.gateway.complete_configured_fallback(
                                gateway_role, system, user,
                                max_output_tokens=retry_budget,
                            )
                        elif allow_tools and hasattr(self.gateway, "complete_with_tools"):
                            toolbox = StoryToolbox(project, self.memory)
                            result = await self.gateway.complete_with_tools(
                                gateway_role, system, user, toolbox,
                                fallback_context=lambda: json.dumps(
                                    self.memory.context(project.id, user[:500]),
                                    ensure_ascii=False,
                                ),
                                run_id=run_id,
                                max_output_tokens=retry_budget,
                            )
                        elif hasattr(self.gateway, "complete_primary"):
                            result = await self.gateway.complete_primary(
                                gateway_role, system, user,
                                max_output_tokens=retry_budget,
                            )
                        else:
                            result = await self.gateway.complete(
                                gateway_role, system, user,
                                max_output_tokens=retry_budget,
                            )
                        result.receipt.setdefault(
                            "requested_max_output_tokens", retry_budget,
                        )
                    retry_complete = not output_limited(result.receipt)
                    if not retry_complete and completion_check is not None:
                        try:
                            retry_complete = bool(completion_check(result.text))
                        except (TypeError, ValueError, json.JSONDecodeError):
                            retry_complete = False
                    if not retry_complete:
                        partial = StageText(result.text, {
                            **result.receipt, "completion_status": "recoverable_partial",
                        })
                        raise IncompleteModelOutputError(stage, partial)
                    result.receipt["completion_status"] = (
                        "complete_at_limit" if output_limited(result.receipt) else "complete"
                    )
            if invalid_terminal_output(result.receipt):
                error = RuntimeError(
                    f"{stage} provider returned terminal state "
                    f"{result.receipt.get('finish_reason')}"
                )
                error.receipt = result.receipt
                raise error
            if not result.text.strip():
                error = RuntimeError(
                    f"{stage} model returned empty output "
                    f"(model={result.receipt.get('model_name', 'unknown')}, "
                    f"input_tokens={result.receipt.get('input_tokens', 0)}, "
                    f"output_tokens={result.receipt.get('output_tokens', 0)}, "
                    f"finish_reason={result.receipt.get('finish_reason', 'unknown')})"
                )
                error.receipt = result.receipt
                raise error
            if result.receipt.get("fallback_used"):
                fallback_metadata = {
                    "fallback_type": "configured",
                    "provider_id": result.receipt.get("provider_id"),
                    "model_id": result.receipt.get("model_id"),
                    "model_name": result.receipt.get("model_name"),
                    "primary_provider_id": result.receipt.get(
                        "fallback_from_provider_id"
                    ),
                    "primary_model_id": result.receipt.get(
                        "fallback_from_model_id"
                    ),
                }
                if (self.db.get_run(run_id) or {}).get(
                    "workflow"
                ) != "short-revision":
                    fallback_metadata["primary_error"] = result.receipt.get(
                        "primary_error"
                    )
                self.db.add_run_event(
                    run_id, "warning", "model_fallback",
                    f"{stage} 首选模型失败，已使用该角色配置的备用模型",
                    stage=stage, metadata=fallback_metadata,
                )
            name = f"{stage}{suffix}"
            atomic_write(run_path / "outputs" / f"{name}.md", result.text)
            receipt = {"model": result.receipt, "skills": [receipt.__dict__ for receipt in skill_run.receipts]}
            atomic_write(run_path / "receipts" / f"{name}.json", json.dumps(receipt, ensure_ascii=False, indent=2))
            stage_completed_message = (
                "模型已返回，正在校验终审格式"
                if stage == "final_review" else f"{stage} 执行完成"
            )
            self.db.add_run_event(
                run_id, "success", "stage_completed", stage_completed_message, stage=stage,
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
            if isinstance(exc, IncompleteModelOutputError):
                if stage == "review":
                    self.db.add_run_event(
                        run_id, "error", "review_incomplete",
                        "审核模型已返回但内容仍不完整，未生成审核分数",
                        stage=stage, metadata={
                            "finish_reason": exc.receipt.get("finish_reason"),
                        },
                    )
                self.db.add_run_event(
                    run_id, "warning", "stage_recoverable_partial",
                    f"{stage} 返回了可恢复但不完整的内容，等待拆分或续跑",
                    stage=stage, metadata={
                        "finish_reason": exc.receipt.get("finish_reason"),
                        "model_name": exc.receipt.get("model_name"),
                    },
                )
                raise
            short_revision = (self.db.get_run(run_id) or {}).get(
                "workflow"
            ) == "short-revision"
            if stage == "review":
                self.db.add_run_event(
                    run_id, "error", "review_incomplete",
                    (
                        "终审模型未返回可用结果。"
                        if short_revision else
                        "Review primary and configured fallback did not produce usable output"
                    ),
                    stage=stage,
                    metadata={} if short_revision else {"error": str(exc)},
                )
            self.db.add_run_event(
                run_id, "error", "stage_failed",
                (
                    "定向返修模型阶段未完成，已保留可恢复进度。"
                    if short_revision else describe_error(exc)
                ),
                stage=stage,
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
            short_revision = (self.db.get_run(run_id) or {}).get(
                "workflow"
            ) == "short-revision"
            self.db.add_run_event(
                run_id, "warning", "model_fallback",
                f"{stage} 首选模型失败，已切换到 {fallback_role} 角色模型",
                stage=stage, metadata={
                    "fallback_role": fallback_role,
                    **({} if short_revision else {"error": str(exc)}),
                },
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
                                 retry_signature: str | None = None,
                                 authority_hash: str | None = None) -> str | None:
        path = root / f"part-{index:02d}.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        polished = value.get("polished")
        if "accepted" in value and value["accepted"] is not True:
            return None
        if (value.get("status") == "preserved_after_retry"
                and value.get("retry_signature") != retry_signature):
            return None
        if authority_hash is not None and value.get("authority_hash") != authority_hash:
            return None
        source_hash = value.get("source_sha256", value.get("source_hash"))
        return polished if source_hash == digest and isinstance(polished, str) else None

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
                                 accepted: bool = True,
                                 change_evidence: dict | None = None,
                                 authority_hash: str | None = None) -> None:
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        checkpoint = {
            "polished": polished,
            "accepted": accepted,
            "status": status,
            "retry_signature": retry_signature,
            "authority_hash": authority_hash,
            "change_evidence": change_evidence or {"ranges": [], "changed_ratio": 0.0},
        }
        checkpoint["source_sha256" if accepted else "source_hash"] = source_hash
        atomic_write(
            root / f"part-{index:02d}.json",
            json.dumps(checkpoint, ensure_ascii=False, indent=2),
        )

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
        return parse_json_object(text)

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

    def _output_budget_for_call(
        self, stage: str, source_characters: int | None,
        gateway_role: str, prefer_configured_fallback: bool,
        *, expected_output_characters: int | None = None,
        input_tokens: int = 0,
    ) -> int | None:
        binding = self.db.get_role_binding(gateway_role) or {}
        model_key = (
            "fallback_model_id" if prefer_configured_fallback else "primary_model_id"
        )
        model = self.db.get_model(binding.get(model_key, "")) or {}
        expected = (
            expected_output_characters
            if expected_output_characters is not None else source_characters
        )
        return adaptive_output_budget(
            stage,
            expected_output_characters=expected,
            input_tokens=input_tokens,
            context_window=model.get("context_window"),
            declared_output_ceiling=model.get("max_output_tokens"),
        )

    def _provider_output_ceiling(self, gateway_role: str,
                                 prefer_configured_fallback: bool) -> int | None:
        binding = self.db.get_role_binding(gateway_role) or {}
        model_key = (
            "fallback_model_id" if prefer_configured_fallback else "primary_model_id"
        )
        model = self.db.get_model(binding.get(model_key, "")) or {}
        ceiling = model.get("max_output_tokens")
        return ceiling if isinstance(ceiling, int) and ceiling > 0 else None

    def _provider_context_window(self, gateway_role: str,
                                 prefer_configured_fallback: bool) -> int | None:
        binding = self.db.get_role_binding(gateway_role) or {}
        model_key = (
            "fallback_model_id" if prefer_configured_fallback else "primary_model_id"
        )
        model = self.db.get_model(binding.get(model_key, "")) or {}
        window = model.get("context_window")
        return window if isinstance(window, int) and window > 0 else None

    @staticmethod
    def _chapter_file(project: Project, text: str, number: int = 1) -> str:
        return (
            f"---\ntitle: {project.title}\nnumber: {number}\npov: {project.metadata['pov']}\n"
            "locations: []\ncharacters: []\narcs-advanced: []\nstatus: final\nword-count: 0\n---\n\n"
            f"# Chapter {number}: {project.title}\n\n## Chapter Text\n\n{text}\n"
        )
