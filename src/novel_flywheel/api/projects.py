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
from pydantic import BaseModel, Field

from novel_flywheel.projects import Project, ProjectCreate, ProjectStore
from novel_flywheel.prose_quality import analyze_prose
from novel_flywheel.revision import normalize_chinese_prose
from novel_flywheel.storage import ProjectSnapshot, atomic_write
from novel_flywheel.story_state import StaleStoryState, StoryStateStore


router = APIRouter(prefix="/api", tags=["projects"])
HAN_CHARACTER = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
WORD_TOKEN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]|[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+(?:[.,]\d+)*")

MATERIAL_GROUPS = (
    ("characters", "人物档案", ("characters/*.md",), {"_index.md"}),
    ("world", "世界设定", ("worldbuilding/*.md", "worldbuilding/systems/**/*.md", "worldbuilding/factions/**/*.md", "worldbuilding/artifacts/**/*.md"), set()),
    ("locations", "地点资料", ("worldbuilding/locations/**/*.md",), {"_index.md"}),
    ("plot", "剧情结构", ("plot/_index.md", "plot/arcs/**/*.md"), set()),
    ("timeline", "时间线", ("plot/timeline.md",), set()),
    ("issues", "伏笔与问题", ("continuity/promises/**/*.md", "continuity/questions/**/*.md"), set()),
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
    "thriving": "正常", "active": "活跃", "planned": "规划中", "none": "无",
    "main": "主线", "character": "人物线", "three-act": "三幕式",
}
MATERIAL_META_LABELS = {
    "type": "类型", "region": "区域", "population": "人数", "controlled-by": "控制者",
    "status": "状态", "structure": "结构",
}


class StyleSamplePayload(BaseModel):
    text: str = Field(min_length=1, max_length=60_000)
    source_name: str = Field(default="reference.txt", max_length=160)


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
        outputs = project.path / "runs" / run["id"] / "outputs"
        for name in ("best-candidate.md", "polish.md"):
            path = outputs / name
            if path.is_file() and path.resolve().is_relative_to(root):
                return path, run["id"]
    return None


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
        await request.app.state.style_samples.analyze(
            project, payload.text, payload.source_name,
        )
        return _style_sample_status(project, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_style_sample", "message": str(exc),
        }) from exc
    except (LookupError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail={
            "code": "style_analysis_failed", "message": str(exc),
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
                relative = path.relative_to(project.path).as_posix()
                items.append({
                    "path": relative, "title": _material_title(path, text),
                    "content": text, "display": _material_display(path, text),
                    "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                })
        documents.append({"id": group_id, "label": label, "documents": items})
    return documents


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
    return {
        "project": {"id": project.id, "title": project.title, "mode": project.mode,
                    "genre": project.metadata.get("genre"),
                    "target_words": project.metadata.get("target_words"),
                    "premise": project.metadata.get("premise", "")},
        "characters": profiles,
        "groups": _material_documents(project),
        "material_impacts": request.app.state.material_impacts.list(project.path),
    }


@router.put("/projects/{project_id}/materials/{relative_path:path}")
def update_project_material(project_id: str, relative_path: str,
                            payload: MaterialEditPayload, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
        group_id, path = _material_lookup(project, relative_path)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "material_not_found"}) from exc
    if get_store(request).db.has_active_runs(project_id):
        raise HTTPException(status_code=409, detail={"code": "project_run_active"})
    previous = path.read_text(encoding="utf-8")
    if hashlib.sha256(previous.encode("utf-8")).hexdigest() != payload.expected_hash:
        raise HTTPException(status_code=409, detail={"code": "material_stale"})
    content = payload.content.replace("\r\n", "\n").rstrip() + "\n"
    atomic_write(path, content)
    store = StoryStateStore(get_store(request).db)
    current = store.ensure(project.id, project.path)
    next_data = _synced_material_state(project, group_id, current.data)
    revision = current.revision
    if next_data != current.data:
        candidate = store.create_candidate(
            project.id, None, current.revision, "material_edit",
            hashlib.sha256(content.encode("utf-8")).hexdigest(),
            {"path": relative_path, "group": group_id},
        )
        try:
            revision = store.commit(candidate.id, current.revision, next_data).revision
        except Exception:
            atomic_write(path, previous)
            raise
    try:
        impact = request.app.state.material_impacts.record(
            project.id, project.path, relative_path, previous, content,
            retire_removed_settings=payload.retire_removed_settings,
        )
    except OSError:
        impact = None
    return {
        "path": relative_path, "group": group_id,
        "hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "story_state_revision": revision,
        "material_impact": impact,
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
        raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc


@router.post("/projects/{project_id}/material-impacts/{impact_id}/dismiss")
def dismiss_material_impact(project_id: str, impact_id: str, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
        return request.app.state.material_impacts.resolve(project.path, impact_id, "dismissed")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc


@router.post("/projects/{project_id}/material-impacts/{impact_id}/apply")
def apply_material_impact(
    project_id: str, impact_id: str, payload: MaterialImpactApplyPayload, request: Request,
) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    if get_store(request).db.has_active_runs(project_id):
        raise HTTPException(status_code=409, detail={"code": "project_run_active"})
    try:
        impact, updates = request.app.state.material_impacts.prepare_apply(
            project.path, impact_id, payload.proposal_ids,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    snapshot = ProjectSnapshot.create(
        project.path, project.path / "snapshots" / f"material-impact-{impact_id}-{uuid.uuid4().hex[:8]}",
        list(updates),
    )
    store = StoryStateStore(get_store(request).db)
    current = store.ensure(project.id, project.path)
    try:
        for path, content in updates.items():
            atomic_write(path, content)
        next_data = current.data
        for path in updates:
            group_id, _ = _material_lookup(project, path.relative_to(project.path).as_posix())
            next_data = _synced_material_state(project, group_id, next_data)
        revision = current.revision
        if next_data != current.data:
            candidate = store.create_candidate(
                project.id, None, current.revision, "material_impact",
                hashlib.sha256(json.dumps(impact, ensure_ascii=False).encode()).hexdigest(),
                {"impact_id": impact_id, "proposal_ids": payload.proposal_ids},
            )
            revision = store.commit(candidate.id, current.revision, next_data).revision
        resolved = request.app.state.material_impacts.resolve(project.path, impact_id, "applied")
    except Exception:
        snapshot.restore()
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

    for run in get_store(request).db.list_runs(project.id):
        outputs = project.path / "runs" / run["id"] / "outputs"
        for name in ("best-candidate.md", "polish.md", "draft.md"):
            candidate = outputs / name
            if candidate.is_file():
                content = candidate.read_text(encoding="utf-8")
                if content.strip():
                    return {
                        "project_id": project.id,
                        "content": content,
                        "source": "run_candidate",
                        "run_id": run["id"],
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
    return {"project_id": project.id, "available": bool(text.strip()), "run_id": run_id,
            "path": str(path.resolve()), "characters": len(text),
            "han_characters": len(HAN_CHARACTER.findall(text)),
            "effective_words": len(WORD_TOKEN.findall(text)),
            "diagnostics": analyze_prose(text)}


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
    text, repairs = normalize_chinese_prose(path.read_text(encoding="utf-8").strip())
    diagnostics = analyze_prose(text)
    if not text or diagnostics["blocking_count"]:
        raise HTTPException(status_code=409, detail={"code": "candidate_blocked",
            "message": "候选稿包含生产说明或正文损坏，不能发布"})
    formal = project.path / "manuscript" / "story.md"
    chapter = project.path / "chapters" / "chapter-01.md"
    atomic_write(formal, text)
    atomic_write(chapter, text)
    published_at = datetime.now(timezone.utc).isoformat()
    atomic_write(project.path / "manuscript" / "publication.json", (
        f'{{"source_run":"{run_id}","source_file":"{path.name}",'
        f'"published_at":"{published_at}","mechanical_repairs":{len(repairs)}}}\n'
    ))
    return {"status": "published", "project_id": project.id, "run_id": run_id,
            "path": str(formal.resolve()), "diagnostics": diagnostics}


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
        raise HTTPException(status_code=400, detail={"code": "invalid_project", "message": str(exc)}) from exc


@router.delete("/projects/{project_id}")
def trash_project(project_id: str, request: Request) -> dict:
    try:
        item = get_store(request).trash(project_id)
        return {**item, "path": str(item["path"]), "original_path": str(item["original_path"])}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "trash_failed", "message": str(exc)}) from exc


@router.post("/projects/{project_id}/restore")
def restore_project(project_id: str, request: Request) -> dict:
    try:
        return _public(get_store(request).restore(project_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "trashed_project_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "restore_failed", "message": str(exc)}) from exc


@router.delete("/projects/{project_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_permanently(project_id: str, request: Request) -> None:
    try:
        get_store(request).delete_permanently(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "trashed_project_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "delete_failed", "message": str(exc)}) from exc


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
        raise HTTPException(status_code=422, detail={"code": "migration_failed", "message": str(exc)}) from exc
