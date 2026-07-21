from fastapi import APIRouter, HTTPException, Request, status

from novel_flywheel.projects import Project, ProjectCreate, ProjectStore


router = APIRouter(prefix="/api", tags=["projects"])


def _public(project: Project) -> dict:
    return {**project.metadata, "path": str(project.path)}


def get_store(request: Request) -> ProjectStore:
    return request.app.state.projects


@router.get("/projects")
def list_projects(request: Request) -> list[dict]:
    return [_public(project) for project in get_store(request).list()]


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request) -> dict:
    try:
        return _public(get_store(request).get(project_id))
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
    return {"project_id": project.id, "content": content}


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, request: Request) -> dict:
    try:
        return _public(get_store(request).create(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_project", "message": str(exc)}) from exc
