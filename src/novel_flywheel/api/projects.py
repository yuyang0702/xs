import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from novel_flywheel.projects import Project, ProjectCreate, ProjectStore
from novel_flywheel.prose_quality import analyze_prose
from novel_flywheel.revision import normalize_chinese_prose
from novel_flywheel.storage import atomic_write


router = APIRouter(prefix="/api", tags=["projects"])


class StyleSamplePayload(BaseModel):
    text: str = Field(min_length=1, max_length=60_000)
    source_name: str = Field(default="reference.txt", max_length=160)


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
        return request.app.state.style_samples.status(get_store(request).get(project_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc


@router.post("/projects/{project_id}/style-sample", status_code=status.HTTP_201_CREATED)
async def analyze_style_sample(project_id: str, payload: StyleSamplePayload, request: Request) -> dict:
    try:
        project = get_store(request).get(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc
    try:
        return await request.app.state.style_samples.analyze(
            project, payload.text, payload.source_name,
        )
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
        return request.app.state.style_samples.delete(project)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"}) from exc


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
