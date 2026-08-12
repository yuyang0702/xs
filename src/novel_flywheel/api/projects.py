import platform
import subprocess
import json
import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import (
    BaseModel, Field, ValidationError, field_validator, model_validator,
)

from novel_flywheel.api.errors import safe_http_exception
from novel_flywheel.db import WIZARD_MUTATION_LOCK
from novel_flywheel.projects import Project, ProjectCreate, ProjectStore
from novel_flywheel.publication import build_zhihu_package, preview_zhihu_package
from novel_flywheel.manuscript_analysis import (
    EMPTY_REFERENCE_CORPUS_SHA256,
    analysis_matches,
    analyze_manuscript,
)
from novel_flywheel.narrative_contract import (
    confirm_narrative_contract,
    ensure_narrative_contract,
)
from novel_flywheel.prose_quality import analyze_prose
from novel_flywheel.quality_records import reconcile_legacy_checkpoint
from novel_flywheel.quality_summary import build_quality_summary, effective_han_characters
from novel_flywheel.quality_profiles import profile_for_project
from novel_flywheel.passage_protection import PassageProtectionService
from novel_flywheel.outlines import local_outline_manifest, normalize_outline_manifest
from novel_flywheel.learning_artifacts import (
    plan_learning_artifact_invalidations,
    write_learning_artifact_sidecar_targets,
)
from novel_flywheel.project_transactions import (
    ProjectMutationJournalV1,
    ProjectMutationStoryStateV1,
    abort_project_mutation_request,
    canonical_json_sha256,
    complete_project_mutation,
    project_mutation_journal_path,
    recover_project_mutations,
    stage_project_mutation_targets,
    write_project_mutation_journal,
)
from novel_flywheel.revision import normalize_chinese_prose
from novel_flywheel.storage import ProjectSnapshot, atomic_write
from novel_flywheel.story_state import StaleStoryState, StoryStateStore


router = APIRouter(prefix="/api", tags=["projects"])


def _project_failure(
    exc: BaseException, *, status_code: int, boundary: str, code: str,
    message: str, family: str = "request.domain_validation",
    retryable: bool = False, recovery_action: str = "refresh_and_retry",
) -> HTTPException:
    return safe_http_exception(
        exc, status_code=status_code, boundary=boundary, code=code,
        family=family, message=message, retryable=retryable,
        recovery_action=recovery_action,
    )
HAN_CHARACTER = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
WORD_TOKEN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]|[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+(?:[.,]\d+)*")

MATERIAL_GROUPS = (
    ("characters", "人物档案", ("characters/*.md",), {"_index.md"}),
    ("world", "世界设定", ("worldbuilding/*.md", "worldbuilding/systems/**/*.md", "worldbuilding/factions/**/*.md", "worldbuilding/artifacts/**/*.md"), set()),
    ("locations", "地点资料", ("worldbuilding/locations/**/*.md",), {"_index.md"}),
    ("plot", "剧情结构", ("plot/_index.md", "plot/arcs/**/*.md"), set()),
    ("timeline", "时间线", ("plot/timeline.md",), set()),
    ("issues", "伏笔与问题", ("continuity/promises/**/*.md", "continuity/questions/**/*.md"), {"_index.md"}),
    ("constraints", "创作约束", ("constraints.md",), set()),
)
MATERIAL_LABELS = {
    "Worldbuilding": "世界设定", "World Overview": "世界概览", "Locations": "地点",
    "Systems": "规则体系", "Factions": "势力", "Artifacts": "重要物品",
    "Plot Structure": "剧情结构", "Story Structure": "故事结构", "Arcs": "剧情弧线",
    "Theme Tracking": "主题追踪", "Story Timeline": "故事时间线",
    "Promises And Payoffs": "伏笔与回收", "Continuity Questions": "连续性问题",
    "Project Constraints": "创作约束", "Must Include": "必须包含", "Must Avoid": "必须避免",
    "Description": "描述", "History": "历史", "Culture & Customs": "文化与习俗",
    "Notable Features": "显著特征", "Current State": "当前状态", "Overview": "概览",
    "Rules & Limitations": "规则与限制", "Practitioners": "参与者",
    "Impact on Society": "社会影响", "Purpose": "目标", "Power Base": "权力基础",
    "Members": "成员", "Conflicts": "冲突", "Registry": "资料索引",
    "Name": "名称", "Type": "类型", "Region": "区域", "File": "文件",
    "Status": "状态", "Description": "描述", "When": "时间", "Event": "事件",
    "Arc": "剧情弧线", "Chapter": "章节", "Beat": "节拍", "Act": "幕",
    "Day": "日期", "Theme": "主题", "Arcs": "剧情弧线", "Chapters": "章节",
    "Promise": "伏笔", "Planted": "埋设位置",
}
MATERIAL_VALUE_LABELS = {
    "building": "建筑", "landmark": "地标", "wilderness": "自然区域",
    "town": "城镇", "city": "城市", "village": "村落", "manor": "宅邸",
    "document": "文书", "family": "家族", "social": "社会规则", "economic": "经济规则",
    "thriving": "正常", "active": "活跃", "planned": "规划中", "none": "无",
    "hidden": "隐藏", "common": "常见", "unknown": "未确认",
    "main": "主线", "character": "人物线", "three-act": "三幕式",
}
MATERIAL_META_LABELS = {
    "type": "类型", "region": "区域", "population": "人数", "controlled-by": "控制者",
    "status": "状态", "structure": "结构",
}


class StyleSamplePayload(BaseModel):
    """Transport DTO; the API converts it into its validated command below."""

    text: str
    source_name: str = "reference.txt"


class StyleSampleAnalysisInputV1(BaseModel):
    """API-owned input contract, independent from provider/parser exceptions."""

    version: Literal[1] = 1
    text: str = Field(min_length=200, max_length=60_000)
    source_name: str = Field(min_length=1, max_length=160)

    @field_validator("text", "source_name", mode="before")
    @classmethod
    def strip_input(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CandidatePublicationAuthorityV1(BaseModel):
    """Content-addressed identity of the exact candidate selected for promotion."""

    version: Literal[1] = 1
    project_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    source_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manuscript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidatePublicationArtifactAuthorityV1(BaseModel):
    """Expected byte identities for the complete formal publication write set."""

    version: Literal[1] = 1
    formal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chapter_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidatePublicationJournalV2(BaseModel):
    """Durable Saga journal; version 1 journals remain readable for recovery."""

    version: Literal[1, 2, 3]
    status: Literal["prepared", "committed", "rolled_back"]
    publication_run_id: str = Field(min_length=1)
    snapshot_path: str = Field(min_length=1)
    source_run_id: str | None = None
    source_authority: CandidatePublicationAuthorityV1 | None = None
    reference_corpus_sha256: str | None = None
    manuscript_sha256: str | None = None
    artifact_authority: CandidatePublicationArtifactAuthorityV1 | None = None

    @model_validator(mode="after")
    def require_v3_artifact_authority(self) -> "CandidatePublicationJournalV2":
        if self.version == 3 and self.artifact_authority is None:
            raise ValueError("Publication journal v3 requires artifact authority")
        return self


class StyleSampleScopePayload(BaseModel):
    application_scope: Literal["polish", "draft_and_polish"]


class StoryStateEditPayload(BaseModel):
    expected_revision: int = Field(ge=1)
    section: Literal[
        "locked_facts", "confirmed_facts", "provisional_facts", "world_rules",
        "character_states", "timeline_events", "issue_ledger",
    ]
    value: Any


class MaterialEditPayload(BaseModel):
    content: str = Field(max_length=200_000)
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    retire_removed_settings: bool = False


class MaterialImpactApplyPayload(BaseModel):
    proposal_ids: list[str] = Field(min_length=1, max_length=100)


class ZhihuPublicationPayload(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    alternate_titles: list[str] = Field(default_factory=list, max_length=10)
    selling_point: str = Field(min_length=1, max_length=300)
    introduction: str = Field(min_length=1, max_length=2000)
    content_type: str = Field(min_length=1, max_length=80)
    audience: str = Field(min_length=1, max_length=200)
    expected_manuscript_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class PlatformProfilePayload(BaseModel):
    profile_id: Literal["zhihu-salt-short"] | None = None


class ProjectRolloutFlagPayload(BaseModel):
    enabled: bool
    reason: str = Field(default="", max_length=300)


class QualityReferenceConfirmationPayload(BaseModel):
    accepted_ids: list[str] = Field(default_factory=list, max_length=20)
    rejected_ids: list[str] = Field(default_factory=list, max_length=20)


class PassageProtectionPayload(BaseModel):
    excerpt: str = Field(min_length=1, max_length=30_000)
    mode: Literal["soft", "exact"]
    label: str = Field(default="保护片段", max_length=80)


class NarrativeContractPayload(BaseModel):
    narrator_character_id: str = Field(min_length=1, max_length=160)


def _style_sample_status(project: Project, request: Request) -> dict:
    return {
        **request.app.state.style_samples.status(project),
        "application_scope": project.metadata.get("style_sample_scope", "polish"),
    }


def _public(project: Project) -> dict:
    return {**project.metadata, "path": str(project.path)}


def get_store(request: Request) -> ProjectStore:
    return request.app.state.projects


LOCATION_LABELS = {
    "project": "项目目录",
    "formal": "正式成品",
    "draft": "最新草稿",
    "best_candidate": "最高分候选",
    "latest_run": "最近运行",
}


def resolve_project_locations(project: Project, store: ProjectStore) -> list[dict]:
    runs = store.db.list_runs(project.id)
    formal = (project.path / "manuscript" / "story.md" if project.mode == "short"
              else project.path / "chapters")
    resolved: dict[str, Path | None] = {
        "project": project.path,
        "formal": formal,
        "draft": None,
        "best_candidate": None,
        "latest_run": project.path / "runs" / runs[0]["id"] if runs else None,
    }
    for run in runs:
        outputs = project.path / "runs" / run["id"] / "outputs"
        if resolved["draft"] is None and (outputs / "draft.md").is_file():
            resolved["draft"] = outputs / "draft.md"
        if resolved["best_candidate"] is None:
            checkpoint = reconcile_legacy_checkpoint(project.path / "runs" / run["id"])
            if checkpoint:
                candidate = project.path / "runs" / run["id"] / checkpoint["manuscript_path"]
                if candidate.is_file():
                    resolved["best_candidate"] = candidate
                    continue
            for name in ("best-candidate.md", "polish.md"):
                candidate = outputs / name
                if candidate.is_file():
                    resolved["best_candidate"] = candidate
                    break
        if resolved["draft"] is not None and resolved["best_candidate"] is not None:
            break
    root = project.path.resolve()
    locations = []
    for kind, label in LOCATION_LABELS.items():
        target = resolved[kind]
        if target is not None and not target.resolve().is_relative_to(root):
            target = None
        locations.append({
            "kind": kind,
            "label": label,
            "path": str(target.resolve()) if target is not None else None,
            "exists": bool(target is not None and target.exists()),
            "is_file": bool(target is not None and target.is_file()),
        })
    return locations


def _location(project: Project, store: ProjectStore, kind: str) -> dict:
    if kind not in LOCATION_LABELS:
        raise LookupError("Unknown project location")
    return next(item for item in resolve_project_locations(project, store) if item["kind"] == kind)


def _candidate(project: Project, store: ProjectStore) -> tuple[Path, str] | None:
    root = project.path.resolve()
    for run in store.db.list_runs(project.id):
        run_path = project.path / "runs" / run["id"]
        outputs = run_path / "outputs"
        checkpoint = reconcile_legacy_checkpoint(run_path)
        if checkpoint:
            path = run_path / checkpoint["manuscript_path"]
            if path.is_file() and path.resolve().is_relative_to(root):
                return path, run["id"]
        for name in ("best-candidate.md", "polish.md"):
            path = outputs / name
            if path.is_file() and path.resolve().is_relative_to(root):
                return path, run["id"]
    return None


def _candidate_analysis(request: Request, project: Project, run_id: str, text: str) -> dict:
    path = project.path / "runs" / run_id / "outputs" / "analysis-candidate.json"
    enabled = bool(project.metadata.get("optimized_local_review_enabled", False))
    local_nlp = getattr(request.app.state, "local_nlp", None)
    references = getattr(request.app.state, "references", None)
    reference_corpus_sha256 = EMPTY_REFERENCE_CORPUS_SHA256
    reference_corpus_authority = None
    if (
        enabled and references
        and hasattr(references, "reference_corpus_authority")
    ):
        reference_corpus_authority = references.reference_corpus_authority(
            project.id,
        )
        reference_corpus_sha256 = str(reference_corpus_authority["sha256"])
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cached = {}
    if analysis_matches(cached, text, reference_corpus_sha256):
        return cached
    report = analyze_manuscript(
        text,
        nlp_analyze=(local_nlp.analyze if enabled and local_nlp else None),
        comparison_sources=(
            references.comparison_sources(
                project.id, authority=reference_corpus_authority,
            )
            if enabled and references and reference_corpus_authority is not None
            else references.comparison_sources(project.id)
            if enabled and references and hasattr(references, "comparison_sources")
            else []
        ),
        reference_corpus_sha256=reference_corpus_sha256,
        market_baseline=request.app.state.projects.active_learning_data(
            project.id, "market_baseline",
        ),
    )
    try:
        current = get_store(request).get(project.id)
    except (LookupError, OSError):
        return report
    if current.path.resolve() != project.path.resolve():
        return report
    atomic_write(path, json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _quality_report(project: Project, run_id: str) -> dict:
    path = project.path / "runs" / run_id / "outputs" / "quality-report.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _candidate_quality_summary(project: Project, run_id: str, text: str) -> dict:
    run_path = project.path / "runs" / run_id
    return build_quality_summary(
        project, run_id, text, _quality_report(project, run_id),
        reconcile_legacy_checkpoint(run_path),
    )


def _candidate_publication_authority(
    project: Project, path: Path, run_id: str, source_text: str,
    manuscript: str,
) -> CandidatePublicationAuthorityV1:
    project_root = project.path.resolve()
    source_path = path.resolve()
    if not source_path.is_relative_to(project_root):
        raise ValueError("Candidate source is outside the project")
    return CandidatePublicationAuthorityV1(
        project_id=project.id,
        source_run_id=run_id,
        source_path=source_path.relative_to(project_root).as_posix(),
        source_text_sha256=hashlib.sha256(
            source_text.encode("utf-8"),
        ).hexdigest(),
        manuscript_sha256=hashlib.sha256(
            manuscript.encode("utf-8"),
        ).hexdigest(),
    )


def _write_candidate_publication_journal(
    path: Path, journal: CandidatePublicationJournalV2,
) -> None:
    atomic_write(
        path,
        json.dumps(
            journal.model_dump(mode="json"), ensure_ascii=False,
            indent=2, sort_keys=True,
        ),
    )


def _persist_candidate_publication_terminal(
    store: ProjectStore, run_id: str, terminal_status: Literal["completed", "failed"],
    *, error: str | None = None,
) -> None:
    current_stage = "archive" if terminal_status == "completed" else None
    store.db.update_run(
        run_id, terminal_status, current_stage, error=error,
    )
    current = store.db.get_run(run_id)
    if current is None or current.get("status") != terminal_status:
        raise RuntimeError("Candidate publication terminal state was not durable")


def _rollback_candidate_publication(
    journal_path: Path, journal: CandidatePublicationJournalV2,
    snapshot: ProjectSnapshot,
) -> CandidatePublicationJournalV2:
    snapshot.restore()
    rolled_back = journal.model_copy(update={"status": "rolled_back"})
    _write_candidate_publication_journal(journal_path, rolled_back)
    return rolled_back


def _candidate_publication_artifacts_match(
    project: Project, journal: CandidatePublicationJournalV2,
) -> bool:
    """Prove the complete committed write set before finalizing its DB state."""

    if (
        not journal.manuscript_sha256
        or not journal.source_run_id
        or not journal.reference_corpus_sha256
    ):
        return False
    formal = project.path / "manuscript" / "story.md"
    chapter = project.path / "chapters" / "chapter-01.md"
    receipt_path = project.path / "manuscript" / "publication.json"
    try:
        formal_bytes = formal.read_bytes()
        chapter_bytes = chapter.read_bytes()
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(receipt, dict):
        return False
    manuscript_sha256 = journal.manuscript_sha256
    if (
        hashlib.sha256(formal_bytes).hexdigest() != manuscript_sha256
        or hashlib.sha256(chapter_bytes).hexdigest() != manuscript_sha256
    ):
        return False
    if journal.artifact_authority is not None and (
        hashlib.sha256(formal_bytes).hexdigest()
        != journal.artifact_authority.formal_sha256
        or hashlib.sha256(chapter_bytes).hexdigest()
        != journal.artifact_authority.chapter_sha256
        or hashlib.sha256(receipt_bytes).hexdigest()
        != journal.artifact_authority.receipt_sha256
    ):
        return False
    source_file = (
        Path(journal.source_authority.source_path).name
        if journal.source_authority is not None else None
    )
    return (
        receipt.get("version") == 2
        and receipt.get("source_run") == journal.source_run_id
        and receipt.get("manuscript_sha256") == manuscript_sha256
        and receipt.get("reference_corpus_sha256")
        == journal.reference_corpus_sha256
        and (source_file is None or receipt.get("source_file") == source_file)
    )


def _abort_candidate_publication(
    store: ProjectStore, run_id: str, snapshot: ProjectSnapshot | None,
    journal_path: Path | None, journal: CandidatePublicationJournalV2 | None,
    *, error: str,
) -> bool:
    """Roll back a pre-commit Saga and durably release its writer lease.

    A committed journal is the filesystem commit point.  Such a Saga must be
    finalized as completed by recovery; it must never be relabelled failed or
    restored to the snapshot after its authoritative writes were committed.
    """

    if journal is not None and journal.status == "committed":
        return False
    if snapshot is not None:
        snapshot.restore()
        if journal is not None and journal_path is not None:
            journal = journal.model_copy(update={"status": "rolled_back"})
            _write_candidate_publication_journal(journal_path, journal)
    _persist_candidate_publication_terminal(
        store, run_id, "failed", error=error,
    )
    if snapshot is not None:
        snapshot.discard()
    return True


def recover_candidate_publications(store: ProjectStore) -> list[str]:
    """Recover interrupted manual publication sagas before serving requests."""

    recovered: list[str] = []
    with WIZARD_MUTATION_LOCK:
        for run in store.db.list_nonterminal_workflow_runs("candidate-publish"):
            try:
                project = store.get(str(run["project_id"]))
            except (LookupError, OSError, UnicodeError, json.JSONDecodeError):
                store.db.update_run(
                    str(run["id"]), "failed", error=(
                        "Candidate publication project metadata is unavailable."
                    ),
                )
                continue
            journal_path = (
                project.path / "runs" / str(run["id"]) / "outputs"
                / "candidate-publication-journal.json"
            )
            try:
                journal = CandidatePublicationJournalV2.model_validate_json(
                    journal_path.read_text(encoding="utf-8"),
                )
                if journal.publication_run_id != str(run["id"]):
                    raise ValueError("Publication journal run identity is stale")
                snapshot_path = (
                    project.path / journal.snapshot_path
                ).resolve()
                snapshot = ProjectSnapshot.load(project.path, snapshot_path)
            except (
                OSError, UnicodeError, json.JSONDecodeError,
                KeyError, TypeError, ValueError, ValidationError,
            ):
                store.db.update_run(
                    str(run["id"]), "failed", error=(
                        "Candidate publication recovery metadata is invalid."
                    ),
                )
                continue
            if journal.status == "committed":
                if not _candidate_publication_artifacts_match(project, journal):
                    journal = _rollback_candidate_publication(
                        journal_path, journal, snapshot,
                    )
                    _persist_candidate_publication_terminal(
                        store, str(run["id"]), "failed", error=(
                            "Committed candidate publication artifacts failed "
                            "integrity recovery."
                        ),
                    )
                    snapshot.discard()
                    recovered.append(str(run["id"]))
                    continue
                _persist_candidate_publication_terminal(
                    store, str(run["id"]), "completed",
                )
                snapshot.discard()
                recovered.append(str(run["id"]))
                continue
            if journal.status != "rolled_back":
                journal = _rollback_candidate_publication(
                    journal_path, journal, snapshot,
                )
            else:
                snapshot.restore()
            _persist_candidate_publication_terminal(
                store, str(run["id"]), "failed", error=(
                    "Interrupted candidate publication was rolled back."
                ),
            )
            snapshot.discard()
            recovered.append(str(run["id"]))
    return recovered


def recover_project_file_state_mutations(store: ProjectStore) -> list[str]:
    """Resume or roll back durable project-file/StoryState Sagas at startup."""

    with WIZARD_MUTATION_LOCK:
        recovered = []
        for workflow in (
            "material-impact-apply", "material-edit", "outline-apply",
            "materials-audit", "long-setup",
        ):
            recovered.extend(
                recover_project_mutations(store, workflow=workflow),
            )
        return recovered


@router.get("/projects")
def list_projects(request: Request) -> list[dict]:
    return [_public(project) for project in get_store(request).list()]


@router.get("/projects/trash")
def list_trashed_projects(request: Request) -> list[dict]:
    return [{**item, "path": str(item["path"]), "original_path": str(item["original_path"])}
            for item in get_store(request).list_trash()]


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request) -> dict:
    try:
        return _public(get_store(request).get(project_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc


@router.get("/projects/{project_id}/style-sample")
def get_style_sample(project_id: str, request: Request) -> dict:
    try:
        return _style_sample_status(get_store(request).get(project_id), request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc


@router.post("/projects/{project_id}/style-sample", status_code=status.HTTP_201_CREATED)
async def analyze_style_sample(project_id: str, payload: StyleSamplePayload, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    try:
        command = StyleSampleAnalysisInputV1.model_validate(
            payload.model_dump(),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_style_sample",
            "message": (
                "Style sample must contain 200 to 60000 non-blank characters."
            ),
        }) from exc
    try:
        await request.app.state.style_samples.analyze(
            project, command.text, command.source_name,
        )
        return _style_sample_status(project, request)
    except Exception as exc:
        raise HTTPException(status_code=502, detail={
            "code": "style_analysis_failed",
            "message": "Style analysis provider is temporarily unavailable.",
        }) from exc


@router.delete("/projects/{project_id}/style-sample")
def delete_style_sample(project_id: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
        request.app.state.style_samples.delete(project)
        return _style_sample_status(project, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc


@router.put("/projects/{project_id}/style-sample/scope")
def update_style_sample_scope(project_id: str, payload: StyleSampleScopePayload,
                              request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    metadata = {**project.metadata, "style_sample_scope": payload.application_scope}
    atomic_write(
        project.path / "project.json",
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    )
    return _style_sample_status(get_store(request).get(project_id), request)


@router.get("/projects/{project_id}/story-state")
def get_story_state(project_id: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    state = StoryStateStore(get_store(request).db).ensure(project.id, project.path)
    return {"project_id": state.project_id, "revision": state.revision, "data": state.data}


def _character_profile(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    frontmatter = parts[1] if len(parts) == 3 else ""
    body = parts[2] if len(parts) == 3 else text
    fields = {
        key: value.strip().strip('"\'')
        for key, value in re.findall(r"(?m)^(name|role|age|status|arc):\s*(.+)$", frontmatter)
    }
    tags_match = re.search(r"(?ms)^tags:\s*\n(?P<items>(?:\s+-\s+.*\n?)*)", frontmatter)
    tags = re.findall(r"(?m)^\s+-\s+(.+)$", tags_match.group("items")) if tags_match else []
    matches = list(re.finditer(r"(?m)^##\s+(.+)$", body))
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append({"title": match.group(1).strip(), "content": body[match.end():end].strip()})
    return {**fields, "tags": tags, "sections": sections, "file": path.name}


def _material_title(path: Path, text: str) -> str:
    heading = re.search(r"(?m)^#\s+(.+)$", text)
    return heading.group(1).strip() if heading else path.stem.replace("-", " ")


def _localized(value: str) -> str:
    return MATERIAL_LABELS.get(value, MATERIAL_VALUE_LABELS.get(value.lower(), value))


def _clean_markdown(text: str) -> str:
    text = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"(?<!\*)\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    return text.strip()


def _material_table(lines: list[str]) -> dict | None:
    rows = [[_clean_markdown(cell.strip()) for cell in line.strip().strip("|").split("|")]
            for line in lines if line.strip().startswith("|")]
    if len(rows) < 2 or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
        return None
    return {"kind": "table", "columns": [_localized(cell) for cell in rows[0]],
            "rows": rows[2:]}


def _material_blocks(body: str) -> list[dict]:
    lines = body.strip().splitlines()
    blocks = []
    text_lines = []

    def flush_text() -> None:
        text = _clean_markdown("\n".join(text_lines))
        if text:
            blocks.append({"kind": "text", "content": text})
        text_lines.clear()

    index = 0
    while index < len(lines):
        if lines[index].strip().startswith("|"):
            flush_text()
            end = index
            while end < len(lines) and lines[end].strip().startswith("|"):
                end += 1
            table = _material_table(lines[index:end])
            if table:
                blocks.append(table)
            else:
                text_lines.extend(lines[index:end])
            index = end
            continue
        text_lines.append(lines[index])
        index += 1
    flush_text()
    return blocks


def _material_display(path: Path, text: str) -> dict:
    parts = text.split("---", 2)
    frontmatter = parts[1] if len(parts) == 3 else ""
    body = parts[2] if len(parts) == 3 else text
    fields = dict(re.findall(r"(?m)^([\w-]+):\s*([^\n]+)$", frontmatter))
    heading = re.search(r"(?m)^#\s+(.+)$", body)
    title = fields.get("name") or (heading.group(1).strip() if heading else _material_title(path, text))
    metadata = [{"label": label, "value": _localized(fields[key].strip().strip('"\''))}
                for key, label in MATERIAL_META_LABELS.items() if fields.get(key)]
    matches = list(re.finditer(r"(?m)^##\s+(.+)$", body))
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        blocks = _material_blocks(body[match.end():end])
        section = {"title": _localized(match.group(1).strip()), "blocks": blocks}
        if len(blocks) == 1:
            section.update(blocks[0])
        sections.append(section)
    if not sections:
        content = re.sub(r"(?m)^#\s+.+$", "", body, count=1)
        blocks = _material_blocks(content)
        if blocks:
            sections.append({"title": "内容", "blocks": blocks, **(blocks[0] if len(blocks) == 1 else {})})
    return {"title": _localized(title.strip().strip('"\'')), "metadata": metadata, "sections": sections}


def _material_documents(project: Project) -> list[dict]:
    documents = []
    seen: set[Path] = set()
    for group_id, label, patterns, excluded in MATERIAL_GROUPS:
        items = []
        for pattern in patterns:
            for path in sorted(project.path.glob(pattern)):
                resolved = path.resolve()
                if (not path.is_file() or path.name in excluded or resolved in seen
                        or not resolved.is_relative_to(project.path.resolve())):
                    continue
                seen.add(resolved)
                text = path.read_text(encoding="utf-8")
                if not _meaningful_material_document(group_id, path, text):
                    continue
                relative = path.relative_to(project.path).as_posix()
                items.append({
                    "path": relative, "title": _material_title(path, text),
                    "content": text, "display": _material_display(path, text),
                    "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                })
        documents.append({"id": group_id, "label": label, "documents": items})
    return documents


def _meaningful_material_document(group_id: str, path: Path, text: str) -> bool:
    if group_id not in {"world", "plot", "timeline"}:
        return True
    if path.name != "_index.md" and group_id != "timeline":
        return bool(text.strip())
    body = re.sub(r"\A---\s*\n.*?\n---\s*", "", text, count=1, flags=re.S)
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("**Model:**"):
            continue
        if re.search(r"\*No .+ yet\*", line, flags=re.I):
            continue
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(
                not cell or cell in MATERIAL_LABELS or re.fullmatch(r":?-{3,}:?", cell)
                for cell in cells
            ):
                continue
        return True
    return False


def _display_outline_manifest(project: Project, request: Request) -> dict:
    current = request.app.state.outlines.current(project.id)
    content = str(current.get("content") or "")
    manifest = local_outline_manifest(content) if content else {}
    try:
        saved = json.loads(
            (project.path / "memory" / "outline-manifest.json").read_text(encoding="utf-8")
        )
        if (
            saved.get("outline_hash") == hashlib.sha256(content.encode("utf-8")).hexdigest()
            and isinstance(saved.get("manifest"), dict)
        ):
            manifest = saved["manifest"]
    except (OSError, json.JSONDecodeError):
        pass
    return normalize_outline_manifest(manifest)


def _material_coverage(groups: list[dict], manifest: dict) -> dict[str, dict]:
    manifest_keys = {
        "characters": ("characters",), "world": ("world",),
        "locations": ("locations",), "plot": ("plot_arcs",),
        "timeline": ("timeline",), "issues": ("promises", "questions"),
        "constraints": ("constraints",),
    }
    result = {}
    for group in groups:
        group_id = group["id"]
        expected = [
            item for key in manifest_keys[group_id]
            for item in manifest.get(key, []) if isinstance(item, dict)
        ]
        titles = [
            str((item.get("display") or {}).get("title") or item.get("title") or "").strip()
            for item in group["documents"]
        ]
        duplicates = sorted({title for title in titles if title and titles.count(title) > 1})
        combined = "\n".join(str(item.get("content") or "") for item in group["documents"])
        missing = []
        for item in expected:
            identity = str(
                item.get("text") if group_id == "constraints" else item.get("name") or ""
            ).strip()
            evidence = str(item.get("evidence") or "").strip()
            covered = identity in titles if group_id in {"characters", "world", "locations"} else (
                bool(identity) and (identity in combined or bool(evidence) and evidence in combined)
            )
            if identity and not covered:
                missing.append({"name": identity, "evidence": evidence})
        if duplicates:
            message = f"发现同名资料：{'、'.join(duplicates)}。请只保留一份正确内容。"
        elif missing:
            labels = [
                item["name"] if len(item["name"]) <= 22 else item["name"][:22] + "…"
                for item in missing[:4]
            ]
            message = f"还缺 {len(missing)} 项正式大纲资料：{'、'.join(labels)}"
        elif group["documents"]:
            message = f"已有 {len(group['documents'])} 份有效资料。"
        else:
            message = "目前只有空模板，还没有可用于写作的资料。"
        result[group_id] = {
            "status": "needs_attention" if duplicates or missing or not group["documents"] else "ready",
            "message": message, "missing": missing, "duplicates": duplicates,
            "expected_count": len(expected), "document_count": len(group["documents"]),
        }
    return result


def _material_lookup(project: Project, relative_path: str) -> tuple[str, Path]:
    normalized = relative_path.replace("\\", "/").strip("/")
    for group in _material_documents(project):
        if any(item["path"] == normalized for item in group["documents"]):
            return group["id"], project.path / Path(normalized)
    raise LookupError("Material document not found")


def _markdown_bullets(text: str) -> list[str]:
    return [value.strip() for value in re.findall(r"(?m)^[-*]\s+(.+)$", text)
            if value.strip() and not value.strip().startswith("*")]


def _synced_material_state(project: Project, group_id: str,
                           current: dict[str, Any]) -> dict[str, Any]:
    imported = StoryStateStore._import(project.path)
    section = {"characters": "character_states", "timeline": "timeline_events"}.get(group_id)
    if section:
        return {**current, section: imported[section]}
    if group_id == "world":
        rules = list(imported.get("world_rules", []))
        for path in project.path.glob("worldbuilding/**/*.md"):
            if "locations" not in path.parts:
                rules.extend(_markdown_bullets(path.read_text(encoding="utf-8")))
        return {**current, "world_rules": list(dict.fromkeys(rules))}
    if group_id == "constraints":
        text = (project.path / "constraints.md").read_text(encoding="utf-8")
        values = {}
        for key, title in (("must_include", "Must Include"), ("must_avoid", "Must Avoid")):
            match = re.search(rf"(?ms)^##\s+{title}\s*$\n(?P<body>.*?)(?=^##\s|\Z)", text)
            if match and match.group("body").strip():
                values[key] = match.group("body").strip()
        locked = [item for item in current.get("locked_facts", [])
                  if item.get("key") not in values]
        locked.extend({"key": key, "value": value, "source": "constraints.md"}
                      for key, value in values.items())
        return {**current, "locked_facts": locked}
    return current


@router.get("/projects/{project_id}/materials")
def get_project_materials(project_id: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    profiles = sorted(
        (_character_profile(path) for path in (project.path / "characters").glob("*.md")
         if path.name != "_index.md"),
        key=lambda item: (item.get("role") != "protagonist", item.get("name", "")),
    )
    groups = _material_documents(project)
    manifest = _display_outline_manifest(project, request)
    return {
        "project": {"id": project.id, "title": project.title, "mode": project.mode,
                    "genre": project.metadata.get("genre"),
                    "target_words": project.metadata.get("target_words"),
                    "premise": project.metadata.get("premise", "")},
        "characters": profiles,
        "groups": groups,
        "coverage": _material_coverage(groups, manifest),
        "outline_conflicts": request.app.state.outlines.writing_readiness(project_id)["conflicts"],
        "manifest_review": manifest.get("_review", {}),
        "material_impacts": request.app.state.material_impacts.list(project.path),
    }


@router.put("/projects/{project_id}/materials/{relative_path:path}")
def update_project_material(project_id: str, relative_path: str,
                            payload: MaterialEditPayload, request: Request) -> dict:
    project_store = get_store(request)
    try:
        project = project_store.get(project_id)
        group_id, path = _material_lookup(project, relative_path)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "material_not_found"}) from exc
    run_id = f"med-{uuid.uuid4().hex}"
    if not project_store.db.create_run_if_idle(
        run_id, project_id, "material-edit", status="running",
    ):
        raise HTTPException(
            status_code=409, detail={"code": "project_run_active"},
        )
    snapshot: ProjectSnapshot | None = None
    journal_path: Path | None = None
    journal: ProjectMutationJournalV1 | None = None
    try:
        with WIZARD_MUTATION_LOCK:
            project = project_store.get(project_id)
            try:
                group_id, path = _material_lookup(project, relative_path)
            except LookupError as exc:
                raise HTTPException(
                    status_code=404, detail={"code": "material_not_found"},
                ) from exc
            previous = path.read_text(encoding="utf-8")
            previous_hash = hashlib.sha256(previous.encode("utf-8")).hexdigest()
            if previous_hash != payload.expected_hash:
                raise HTTPException(
                    status_code=409, detail={"code": "material_stale"},
                )
            content = payload.content.replace("\r\n", "\n").rstrip() + "\n"
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            state_store = StoryStateStore(project_store.db)
            current = state_store.ensure(project.id, project.path)
            invalidations = plan_learning_artifact_invalidations(
                project_store.db, project.id,
            )
            impact_record = request.app.state.material_impacts.prepare_record(
                project.id, relative_path, previous, content,
                retire_removed_settings=payload.retire_removed_settings,
            )
            sidecar_paths = [
                project.path / "learning" / f"{artifact_type}.json"
                for artifact_type in sorted(invalidations.sidecars)
            ]
            impact_path = (
                request.app.state.material_impacts.impact_path(
                    project.path, str(impact_record["id"]),
                )
                if impact_record is not None else None
            )
            managed_paths = [
                path, *sidecar_paths,
                *([impact_path] if impact_path is not None else []),
            ]
            snapshot_root = project.path / "snapshots" / run_id
            snapshot = ProjectSnapshot.create(
                project.path, snapshot_root, managed_paths,
            )
            changed_lines = sorted({
                line.strip()
                for line in (previous + "\n" + content).splitlines()
                if line.strip()
                and ((line in previous) != (line in content))
            })
            source_authority = canonical_json_sha256({
                "path": relative_path,
                "group": group_id,
                "before_sha256": previous_hash,
                "after_sha256": content_hash,
                "retire_removed_settings": payload.retire_removed_settings,
                "changed_lines": changed_lines,
            })
            journal_path = project_mutation_journal_path(project.path, run_id)
            journal = ProjectMutationJournalV1(
                status="prepared",
                operation="material-edit",
                run_id=run_id,
                project_id=project.id,
                snapshot_path=snapshot_root.relative_to(
                    project.path,
                ).as_posix(),
                source_authority_sha256=source_authority,
                expected_story_state_revision=current.revision,
                managed_paths=tuple(
                    item.relative_to(project.path).as_posix()
                    for item in managed_paths
                ),
                learning_artifact_invalidations=invalidations.effects,
            )
            write_project_mutation_journal(journal_path, journal)

            atomic_write(path, content)
            write_learning_artifact_sidecar_targets(
                project.path, invalidations,
            )
            if impact_record is not None:
                request.app.state.material_impacts.save(
                    project.path, impact_record,
                )
            next_data = _synced_material_state(
                project, group_id, current.data,
            )
            story_state_target = None
            if next_data != current.data:
                candidate = state_store.create_candidate(
                    project.id, run_id, current.revision, "material_edit",
                    content_hash, {"path": relative_path, "group": group_id},
                )
                story_state_target = ProjectMutationStoryStateV1(
                    candidate_id=candidate.id,
                    expected_revision=current.revision,
                    target_revision=current.revision + 1,
                    state_sha256=canonical_json_sha256(next_data),
                    data=next_data,
                )
            artifacts = stage_project_mutation_targets(
                project.path, snapshot, managed_paths,
            )
            journal = ProjectMutationJournalV1.model_validate(
                journal.model_copy(update={
                    "status": "artifacts_committed",
                    "artifacts": artifacts,
                    "story_state": story_state_target,
                }).model_dump(mode="python"),
            )
            write_project_mutation_journal(journal_path, journal)
            completed = complete_project_mutation(project_store, run_id)
            revision = (
                completed.story_state.target_revision
                if completed.story_state is not None
                else completed.expected_story_state_revision
            )
            impact = (
                request.app.state.material_impacts.public(impact_record)
                if impact_record is not None else None
            )
            learning_impact = {
                "source_path": relative_path,
                "changes": changed_lines or ["项目资料内容已修改"],
                "affected": [{
                    "artifact_type": item.artifact_type,
                    "version": item.artifact_version,
                    "severity": "review",
                } for item in invalidations.effects],
                "formal_files_changed": False,
            }
    except HTTPException:
        abort_project_mutation_request(
            project_store, run_id, snapshot, journal_path, journal,
            error="Material edit was rejected.",
        )
        raise
    except Exception:
        abort_project_mutation_request(
            project_store, run_id, snapshot, journal_path, journal,
            error="Material edit failed and was rolled back.",
        )
        raise
    return {
        "path": relative_path,
        "group": group_id,
        "hash": content_hash,
        "story_state_revision": revision,
        "material_impact": impact,
        "learning_impact": learning_impact,
    }


def _impact_documents(project: Project) -> list[dict[str, str]]:
    return [
        {"path": document["path"], "content": document["content"]}
        for group in _material_documents(project)
        for document in group["documents"]
    ]


@router.post("/projects/{project_id}/material-impacts/{impact_id}/analyze")
async def analyze_material_impact(project_id: str, impact_id: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
        return await request.app.state.material_impacts.analyze(
            project.path, impact_id, _impact_documents(project),
        )
    except LookupError as exc:
        raise _project_failure(
            exc, status_code=404, boundary="project.material_impact.analyze",
            code="material_impact.not_found", family="request.resource_not_found",
            message="材料影响记录不存在或已发生变化。",
        ) from exc


@router.post("/projects/{project_id}/material-impacts/{impact_id}/dismiss")
def dismiss_material_impact(project_id: str, impact_id: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
        return request.app.state.material_impacts.resolve(project.path, impact_id, "dismissed")
    except LookupError as exc:
        raise _project_failure(
            exc, status_code=404, boundary="project.material_impact.dismiss",
            code="material_impact.not_found", family="request.resource_not_found",
            message="材料影响记录不存在或已发生变化。",
        ) from exc


@router.post("/projects/{project_id}/material-impacts/{impact_id}/apply")
def apply_material_impact(
    project_id: str, impact_id: str, payload: MaterialImpactApplyPayload, request: Request,
) -> dict:
    project_store = get_store(request)
    try:
        project = project_store.get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    # Keep filesystem-backed Saga paths below legacy Windows MAX_PATH while
    # the run's workflow column retains the descriptive operation name.
    run_id = f"mia-{uuid.uuid4().hex}"
    if not project_store.db.create_run_if_idle(
        run_id, project_id, "material-impact-apply", status="running",
    ):
        raise HTTPException(
            status_code=409, detail={"code": "project_run_active"},
        )
    snapshot: ProjectSnapshot | None = None
    journal_path: Path | None = None
    journal: ProjectMutationJournalV1 | None = None
    try:
        with WIZARD_MUTATION_LOCK:
            project = project_store.get(project_id)
            try:
                impact, updates = request.app.state.material_impacts.prepare_apply(
                    project.path, impact_id, payload.proposal_ids,
                )
            except LookupError as exc:
                raise _project_failure(
                    exc, status_code=404, boundary="project.material_impact.apply.lookup",
                    code="material_impact.not_found", family="request.resource_not_found",
                    message="材料影响记录或提案不存在。",
                ) from exc
            except ValueError as exc:
                raise _project_failure(
                    exc, status_code=409, boundary="project.material_impact.apply.state",
                    code="material_impact.stale", family="runtime.stale_authority",
                    message="材料影响提案已经变化，请刷新后重新选择。",
                ) from exc
            impact_path = request.app.state.material_impacts.impact_path(
                project.path, impact_id,
            )
            managed_paths = sorted(
                [*updates, impact_path], key=lambda path: path.as_posix(),
            )
            snapshot_root = project.path / "snapshots" / run_id
            snapshot = ProjectSnapshot.create(
                project.path, snapshot_root, managed_paths,
            )
            state_store = StoryStateStore(project_store.db)
            current = state_store.ensure(project.id, project.path)
            journal_path = project_mutation_journal_path(project.path, run_id)
            source_authority = canonical_json_sha256({
                "impact": impact,
                "proposal_ids": sorted(payload.proposal_ids),
            })
            journal = ProjectMutationJournalV1(
                status="prepared",
                operation="material-impact-apply",
                run_id=run_id,
                project_id=project.id,
                snapshot_path=snapshot_root.relative_to(
                    project.path,
                ).as_posix(),
                source_authority_sha256=source_authority,
                expected_story_state_revision=current.revision,
                managed_paths=tuple(
                    path.resolve().relative_to(
                        project.path.resolve(),
                    ).as_posix()
                    for path in managed_paths
                ),
            )
            write_project_mutation_journal(journal_path, journal)

            for path, content in updates.items():
                atomic_write(path, content)
            next_data = current.data
            for path in updates:
                group_id, _ = _material_lookup(
                    project, path.relative_to(project.path).as_posix(),
                )
                next_data = _synced_material_state(project, group_id, next_data)
            resolved = request.app.state.material_impacts.resolve(
                project.path, impact_id, "applied",
            )
            story_state_target = None
            if next_data != current.data:
                candidate = state_store.create_candidate(
                    project.id, run_id, current.revision, "material_impact",
                    source_authority,
                    {
                        "impact_id": impact_id,
                        "proposal_ids": payload.proposal_ids,
                    },
                )
                story_state_target = ProjectMutationStoryStateV1(
                    candidate_id=candidate.id,
                    expected_revision=current.revision,
                    target_revision=current.revision + 1,
                    state_sha256=canonical_json_sha256(next_data),
                    data=next_data,
                )
            artifacts = stage_project_mutation_targets(
                project.path, snapshot, managed_paths,
            )
            journal = journal.model_copy(update={
                "status": "artifacts_committed",
                "artifacts": artifacts,
                "story_state": story_state_target,
            })
            journal = ProjectMutationJournalV1.model_validate(
                journal.model_dump(mode="python"),
            )
            write_project_mutation_journal(journal_path, journal)
            journal = complete_project_mutation(project_store, run_id)
            revision = (
                journal.story_state.target_revision
                if journal.story_state is not None
                else journal.expected_story_state_revision
            )
            resolved = request.app.state.material_impacts.public(
                request.app.state.material_impacts.get(project.path, impact_id),
            )
    except HTTPException:
        abort_project_mutation_request(
            project_store, run_id, snapshot, journal_path, journal,
            error="Material impact application was rejected.",
        )
        raise
    except Exception:
        abort_project_mutation_request(
            project_store, run_id, snapshot, journal_path, journal,
            error="Material impact application failed and was rolled back.",
        )
        raise
    return {"material_impact": resolved, "story_state_revision": revision}


@router.get("/projects/{project_id}/story-state/history")
def get_story_state_history(project_id: str, request: Request) -> list[dict]:
    try:
        get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    return [
        {"project_id": item.project_id, "revision": item.revision, "data": item.data}
        for item in StoryStateStore(get_store(request).db).history(project_id)
    ]


@router.put("/projects/{project_id}/story-state")
def update_story_state(project_id: str, payload: StoryStateEditPayload,
                       request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    if get_store(request).db.has_active_runs(project_id):
        raise HTTPException(status_code=409, detail={"code": "project_run_active"})
    store = StoryStateStore(get_store(request).db)
    current = store.ensure(project.id, project.path)
    serialized = json.dumps(payload.value, ensure_ascii=False, sort_keys=True)
    candidate = store.create_candidate(
        project_id, None, payload.expected_revision, "manual_edit",
        hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        {"section": payload.section},
    )
    try:
        updated = store.commit(
            candidate.id, payload.expected_revision,
            {**current.data, payload.section: payload.value},
        )
    except StaleStoryState as exc:
        raise HTTPException(status_code=409, detail={"code": "story_state_stale"}) from exc
    return {"project_id": updated.project_id, "revision": updated.revision, "data": updated.data}


@router.get("/projects/{project_id}/manuscript")
def get_manuscript(project_id: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    if project.mode == "short":
        files = [project.path / "manuscript" / "story.md"]
    else:
        files = sorted(project.path.joinpath("chapters").glob("chapter-*.md"))
    content = "\n\n".join(path.read_text(encoding="utf-8") for path in files if path.is_file())
    if content.strip() or project.mode != "short":
        return {"project_id": project.id, "content": content, "source": "formal", "run_id": None}

    resolved = _candidate(project, get_store(request))
    if resolved:
        candidate, run_id = resolved
        content = candidate.read_text(encoding="utf-8")
        if content.strip():
            return {
                "project_id": project.id,
                "content": content,
                "source": "run_candidate",
                "run_id": run_id,
            }
    return {"project_id": project.id, "content": "", "source": "none", "run_id": None}


@router.get("/projects/{project_id}/locations")
def get_project_locations(project_id: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    return {"project_id": project.id,
            "locations": resolve_project_locations(project, get_store(request))}


@router.get("/projects/{project_id}/candidate")
def get_candidate(project_id: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    resolved = _candidate(project, get_store(request))
    if resolved is None:
        return {"project_id": project.id, "available": False, "diagnostics": None}
    path, run_id = resolved
    text = path.read_text(encoding="utf-8")
    analysis = _candidate_analysis(request, project, run_id, text)
    quality_summary = _candidate_quality_summary(project, run_id, text)
    return {"project_id": project.id, "available": bool(text.strip()), "run_id": run_id,
            "path": str(path.resolve()), "content": text, "characters": len(text),
            "han_characters": effective_han_characters(text),
            "effective_words": len(WORD_TOKEN.findall(text)),
            "diagnostics": analyze_prose(text), "analysis": analysis,
            "analysis_status": "complete" if analysis.get("coverage") == 1.0 else "incomplete",
            "review_scope": analysis.get("originality", {}).get("scope"),
            "quality_summary": quality_summary}


@router.post("/projects/{project_id}/candidate/publish", status_code=status.HTTP_201_CREATED)
def publish_candidate(project_id: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    if project.mode != "short":
        raise HTTPException(status_code=409, detail={"code": "candidate_mode_unsupported"})
    resolved = _candidate(project, get_store(request))
    if resolved is None:
        raise HTTPException(status_code=409, detail={"code": "candidate_not_generated"})
    path, run_id = resolved
    source_text = path.read_text(encoding="utf-8")
    text, repairs = normalize_chinese_prose(source_text.strip())
    candidate_authority = _candidate_publication_authority(
        project, path, run_id, source_text, text,
    )
    diagnostics = analyze_prose(text)
    if not text or diagnostics["blocking_count"]:
        raise HTTPException(status_code=409, detail={"code": "candidate_blocked",
            "message": "候选稿包含生产说明或正文损坏，不能发布"})
    analysis = _candidate_analysis(request, project, run_id, text)
    expected_hash = candidate_authority.manuscript_sha256
    if analysis.get("coverage") != 1.0 or analysis.get("text_hash") != expected_hash:
        raise HTTPException(status_code=409, detail={"code": "candidate_analysis_stale"})
    quality_summary = _candidate_quality_summary(project, run_id, text)
    authority = quality_summary["publication_authority"]
    if not authority["can_set_formal"]:
        raise HTTPException(status_code=409, detail={
            "code": "candidate_quality_blocked",
            "message": "当前候选稿还不能设为正式稿",
            "reasons": authority["blocking_reasons"],
        })
    publication_run_id = f"candidate-publish-{uuid.uuid4().hex}"
    if not get_store(request).db.create_run_if_idle(
        publication_run_id, project.id, "candidate-publish", status="running",
    ):
        raise HTTPException(
            status_code=409, detail={"code": "project_run_active"},
        )
    formal = project.path / "manuscript" / "story.md"
    chapter = project.path / "chapters" / "chapter-01.md"
    publication_receipt = project.path / "manuscript" / "publication.json"
    snapshot: ProjectSnapshot | None = None
    journal_path: Path | None = None
    journal: CandidatePublicationJournalV2 | None = None
    try:
        with WIZARD_MUTATION_LOCK:
            current_project = get_store(request).get(project.id)
            current_resolved = _candidate(
                current_project, get_store(request),
            )
            if current_resolved is None:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "candidate_analysis_stale"},
                )
            current_path, current_run_id = current_resolved
            try:
                current_source_text = current_path.read_text(encoding="utf-8")
                current_text, _current_repairs = normalize_chinese_prose(
                    current_source_text.strip(),
                )
                current_authority = _candidate_publication_authority(
                    current_project, current_path, current_run_id,
                    current_source_text, current_text,
                )
            except (OSError, UnicodeError, ValueError) as exc:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "candidate_analysis_stale"},
                ) from exc
            if (
                current_project.path.resolve() != project.path.resolve()
                or current_authority != candidate_authority
            ):
                raise HTTPException(
                    status_code=409,
                    detail={"code": "candidate_analysis_stale"},
                )
            references = getattr(request.app.state, "references", None)
            optimized = bool(
                current_project.metadata.get("optimized_local_review_enabled", False)
            )
            current_corpus_sha256 = EMPTY_REFERENCE_CORPUS_SHA256
            if (
                optimized and references
                and hasattr(references, "reference_corpus_authority")
            ):
                current_corpus_sha256 = str(
                    references.reference_corpus_authority(project.id)["sha256"]
                )
            if analysis.get("reference_corpus_sha256") != current_corpus_sha256:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "candidate_analysis_stale"},
                )
            current_quality = _candidate_quality_summary(
                current_project, current_run_id, current_text,
            )["publication_authority"]
            if not current_quality["can_set_formal"]:
                raise HTTPException(status_code=409, detail={
                    "code": "candidate_quality_blocked",
                    "reasons": current_quality["blocking_reasons"],
                })

            snapshot_root = (
                project.path / "snapshots" / publication_run_id
            )
            snapshot = ProjectSnapshot.create(
                project.path, snapshot_root,
                [formal, chapter, publication_receipt],
            )
            journal_path = (
                project.path / "runs" / publication_run_id / "outputs"
                / "candidate-publication-journal.json"
            )
            published_at = datetime.now(timezone.utc).isoformat()
            receipt_payload = {
                "version": 2,
                "source_run": current_run_id,
                "source_file": current_path.name,
                "published_at": published_at,
                "mechanical_repairs": len(repairs),
                "manuscript_sha256": expected_hash,
                "reference_corpus_sha256": current_corpus_sha256,
            }
            receipt_text = json.dumps(
                receipt_payload, ensure_ascii=False, indent=2, sort_keys=True,
            ) + "\n"
            journal = CandidatePublicationJournalV2(
                version=3,
                status="prepared",
                publication_run_id=publication_run_id,
                source_run_id=current_run_id,
                source_authority=current_authority,
                snapshot_path=snapshot_root.relative_to(
                    project.path,
                ).as_posix(),
                reference_corpus_sha256=current_corpus_sha256,
                manuscript_sha256=expected_hash,
                artifact_authority=CandidatePublicationArtifactAuthorityV1(
                    formal_sha256=expected_hash,
                    chapter_sha256=expected_hash,
                    receipt_sha256=hashlib.sha256(
                        receipt_text.encode("utf-8"),
                    ).hexdigest(),
                ),
            )
            _write_candidate_publication_journal(journal_path, journal)
            try:
                atomic_write(formal, text, preserve_newlines=True)
                atomic_write(chapter, text, preserve_newlines=True)
                atomic_write(
                    publication_receipt,
                    receipt_text,
                    preserve_newlines=True,
                )
                committed = journal.model_copy(update={"status": "committed"})
                _write_candidate_publication_journal(
                    journal_path, committed,
                )
                journal = committed
            except Exception:
                journal = _rollback_candidate_publication(
                    journal_path, journal, snapshot,
                )
                raise
            _persist_candidate_publication_terminal(
                get_store(request), publication_run_id, "completed",
            )
            snapshot.discard()
            snapshot = None
    except HTTPException as exc:
        _abort_candidate_publication(
            get_store(request), publication_run_id, snapshot,
            journal_path, journal, error=str(
                exc.detail.get("code") if isinstance(exc.detail, dict)
                else "candidate_publication_rejected"
            ),
        )
        raise
    except Exception:
        _abort_candidate_publication(
            get_store(request), publication_run_id, snapshot,
            journal_path, journal,
            error="Candidate publication failed and was rolled back.",
        )
        raise
    return {"status": "published", "project_id": project.id, "run_id": run_id,
            "path": str(formal.resolve()), "diagnostics": diagnostics}


def _quality_reference_scope(project_id: str, request: Request) -> tuple[Project, str]:
    project = get_store(request).get(project_id)
    return project, profile_for_project(project)


@router.get("/projects/{project_id}/quality-references/recommendations")
def recommend_quality_references(project_id: str, request: Request) -> dict:
    try:
        project, profile_id = _quality_reference_scope(project_id, request)
        return request.app.state.quality_references.recommend(project.id, profile_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc


@router.get("/projects/{project_id}/rollout-flags")
def get_project_rollout_flags(project_id: str, request: Request) -> dict:
    try:
        get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    return {
        "planning_ir_first": {
            "key": "planning_ir_first",
            "enabled": True,
            "scope_type": "system",
            "scope_id": None,
            "config": {
                "reason": "rollout_complete",
                "immutable": True,
            },
        },
    }


@router.put("/projects/{project_id}/rollout-flags/planning-ir-first")
def set_project_planning_rollout(
    project_id: str, payload: ProjectRolloutFlagPayload, request: Request,
) -> dict:
    try:
        get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    if not payload.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "planning_ir_rollout_complete"},
        )
    return get_project_rollout_flags(project_id, request)["planning_ir_first"]


@router.get("/projects/{project_id}/narrative-contract")
def get_narrative_contract(project_id: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    return ensure_narrative_contract(project).payload()


@router.put("/projects/{project_id}/narrative-contract")
def update_narrative_contract(
    project_id: str, payload: NarrativeContractPayload, request: Request,
) -> dict:
    try:
        project = get_store(request).get(project_id)
        return confirm_narrative_contract(
            project, payload.narrator_character_id,
        ).payload()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    except ValueError as exc:
        raise _project_failure(
            exc, status_code=409, boundary="project.narrative_contract",
            code="narrative.confirmation_invalid", family="runtime.stale_authority",
            message="叙述者确认与当前项目资料不一致，请刷新后重试。",
        ) from exc


@router.get("/projects/{project_id}/quality-references")
def get_quality_reference_group(project_id: str, request: Request) -> dict:
    try:
        project, profile_id = _quality_reference_scope(project_id, request)
        return request.app.state.quality_references.list_group(project.id, profile_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc


@router.post("/projects/{project_id}/quality-references/confirm")
def confirm_quality_references(
    project_id: str, payload: QualityReferenceConfirmationPayload, request: Request,
) -> dict:
    try:
        project, profile_id = _quality_reference_scope(project_id, request)
        return request.app.state.quality_references.confirm(
            project.id, profile_id,
            accepted_ids=payload.accepted_ids, rejected_ids=payload.rejected_ids,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    except ValueError as exc:
        raise _project_failure(
            exc, status_code=409, boundary="project.quality_references.confirm",
            code="quality_references.changed", family="runtime.stale_authority",
            message="质量参考项已经变化，请刷新后重新确认。",
        ) from exc


@router.delete("/projects/{project_id}/quality-references/{item_id:path}")
def remove_quality_reference(project_id: str, item_id: str, request: Request) -> dict:
    try:
        project, profile_id = _quality_reference_scope(project_id, request)
        return request.app.state.quality_references.remove(project.id, profile_id, item_id)
    except LookupError as exc:
        raise _project_failure(
            exc, status_code=404, boundary="project.quality_references.remove",
            code="quality_reference.not_found", family="request.resource_not_found",
            message="质量参考项不存在或已被删除。",
        ) from exc


@router.get("/projects/{project_id}/quality-references/history")
def get_quality_reference_history(project_id: str, request: Request) -> dict:
    try:
        project, profile_id = _quality_reference_scope(project_id, request)
        return {
            "project_id": project.id, "profile_id": profile_id,
            "versions": request.app.state.quality_references.history(
                project.id, profile_id,
            ),
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc


@router.get("/projects/{project_id}/passage-protections")
def list_passage_protections(project_id: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    return {
        "project_id": project.id,
        "items": PassageProtectionService(get_store(request).db).list(project.id),
    }


@router.post(
    "/projects/{project_id}/passage-protections",
    status_code=status.HTTP_201_CREATED,
)
def create_passage_protection(
    project_id: str, payload: PassageProtectionPayload, request: Request,
) -> dict:
    try:
        project = get_store(request).get(project_id)
        resolved = _candidate(project, get_store(request))
        if resolved is None:
            raise ValueError("还没有候选稿，暂时不能保护片段")
        text = resolved[0].read_text(encoding="utf-8")
        return PassageProtectionService(get_store(request).db).create(
            project.id, text, excerpt=payload.excerpt,
            mode=payload.mode, label=payload.label,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    except ValueError as exc:
        raise _project_failure(
            exc, status_code=409, boundary="project.passage_protection.create",
            code="passage.selection_invalid", family="request.domain_validation",
            message="保护片段无法在当前候选稿中唯一定位，请重新选择。",
        ) from exc


@router.post("/projects/{project_id}/passage-protections/{protection_id}/allow-next-change")
def allow_protected_passage_change(
    project_id: str, protection_id: str, request: Request,
) -> dict:
    try:
        get_store(request).get(project_id)
        return PassageProtectionService(get_store(request).db).allow_next_change(
            project_id, protection_id,
        )
    except LookupError as exc:
        raise _project_failure(
            exc, status_code=404, boundary="project.passage_protection.allow.lookup",
            code="passage_protection.not_found", family="request.resource_not_found",
            message="片段保护记录不存在或已发生变化。",
        ) from exc
    except ValueError as exc:
        raise _project_failure(
            exc, status_code=409, boundary="project.passage_protection.allow.state",
            code="passage_protection.inactive", family="runtime.stale_authority",
            message="片段保护已失效，请刷新后重试。",
        ) from exc


@router.delete("/projects/{project_id}/passage-protections/{protection_id}")
def remove_passage_protection(
    project_id: str, protection_id: str, request: Request,
) -> dict:
    try:
        get_store(request).get(project_id)
        return PassageProtectionService(get_store(request).db).remove(
            project_id, protection_id,
        )
    except LookupError as exc:
        raise _project_failure(
            exc, status_code=404, boundary="project.passage_protection.remove",
            code="passage_protection.not_found", family="request.resource_not_found",
            message="片段保护记录不存在或已发生变化。",
        ) from exc


@router.post("/projects/{project_id}/locations/{kind}/open")
def open_project_location(project_id: str, kind: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
        location = _location(project, get_store(request), kind)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "location_not_found"}) from exc
    if not location["exists"]:
        raise HTTPException(status_code=409, detail={"code": "location_not_generated"})
    if platform.system() != "Windows":
        raise HTTPException(status_code=501, detail={"code": "explorer_not_supported"})
    path = location["path"]
    command = (["explorer.exe", f"/select,{path}"] if location["is_file"]
               else ["explorer.exe", path])
    subprocess.Popen(command, close_fds=True)
    return {"status": "opened", "kind": kind, "path": path}


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, request: Request) -> dict:
    try:
        return _public(get_store(request).create(payload))
    except ValueError as exc:
        raise _project_failure(
            exc, status_code=400, boundary="project.create",
            code="project.invalid", message="作品参数未通过校验，请检查后重试。",
        ) from exc


@router.delete("/projects/{project_id}")
def trash_project(project_id: str, request: Request) -> dict:
    try:
        item = get_store(request).trash(project_id)
        return {**item, "path": str(item["path"]), "original_path": str(item["original_path"])}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    except ValueError as exc:
        raise _project_failure(
            exc, status_code=409, boundary="project.trash",
            code="project.trash_failed", family="runtime.stale_authority",
            message="作品当前无法移入回收站，请确认没有活动任务后重试。",
        ) from exc


@router.post("/projects/{project_id}/restore")
def restore_project(project_id: str, request: Request) -> dict:
    try:
        return _public(get_store(request).restore(project_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "trashed_project_not_found"}) from exc
    except ValueError as exc:
        raise _project_failure(
            exc, status_code=409, boundary="project.restore",
            code="project.restore_failed", family="runtime.stale_authority",
            message="原位置属于其他作品；两份内容均已保留，请选择新的恢复位置后重试。",
        ) from exc


@router.delete("/projects/{project_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_permanently(project_id: str, request: Request) -> None:
    try:
        get_store(request).delete_permanently(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "trashed_project_not_found"}) from exc
    except ValueError as exc:
        raise _project_failure(
            exc, status_code=409, boundary="project.delete_permanently",
            code="project.delete_failed", family="runtime.stale_authority",
            message="作品当前无法永久删除，请确认状态后重试。",
        ) from exc


@router.get("/projects/{project_id}/migration")
def migration_preview(project_id: str, request: Request) -> dict:
    try:
        return request.app.state.migrator.dry_run(get_store(request).get(project_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc


@router.post("/projects/{project_id}/migration")
def migrate_project(project_id: str, request: Request) -> dict:
    try:
        return request.app.state.migrator.migrate(get_store(request).get(project_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    except (ValueError, RuntimeError, PermissionError) as exc:
        raise _project_failure(
            exc, status_code=422, boundary="project.migration",
            code="project.migration_failed", family="runtime.migration_failure",
            message="项目迁移未完成，原项目资料已保留。",
            retryable=True, recovery_action="review_migration_and_retry",
        ) from exc


@router.get("/projects/{project_id}/publication/zhihu/preview")
def preview_zhihu_publication(project_id: str, request: Request) -> dict:
    try:
        return preview_zhihu_package(get_store(request).get(project_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    except ValueError as exc:
        raise _project_failure(
            exc, status_code=422, boundary="project.publication.preview",
            code="publication.not_ready", family="request.domain_validation",
            message="正式稿尚未满足发布预览条件。",
        ) from exc


@router.post("/projects/{project_id}/publication/zhihu", status_code=status.HTTP_201_CREATED)
def create_zhihu_publication(
    project_id: str, payload: ZhihuPublicationPayload, request: Request,
) -> dict:
    try:
        return build_zhihu_package(
            get_store(request).get(project_id), payload.model_dump(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    except ValueError as exc:
        raise _project_failure(
            exc, status_code=422, boundary="project.publication.create",
            code="publication.failed", family="request.domain_validation",
            message="发布包生成失败，正式稿没有变化。",
        ) from exc


@router.post("/projects/{project_id}/platform-profile/preview")
def preview_platform_profile(
    project_id: str, payload: PlatformProfilePayload, request: Request,
) -> dict:
    try:
        return get_store(request).preview_platform_profile(project_id, payload.profile_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    except ValueError as exc:
        raise _project_failure(
            exc, status_code=422, boundary="project.platform_profile.preview",
            code="platform_profile.not_available", family="request.domain_validation",
            message="目标平台配置不可用，请刷新配置后重试。",
        ) from exc


@router.put("/projects/{project_id}/platform-profile")
def apply_platform_profile(
    project_id: str, payload: PlatformProfilePayload, request: Request,
) -> dict:
    try:
        return _public(get_store(request).apply_platform_profile(project_id, payload.profile_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    except ValueError as exc:
        raise _project_failure(
            exc, status_code=422, boundary="project.platform_profile.apply",
            code="platform_profile.not_available", family="request.domain_validation",
            message="目标平台配置不可用，请刷新配置后重试。",
        ) from exc
