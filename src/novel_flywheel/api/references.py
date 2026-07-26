import base64
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from novel_flywheel.reference_extractors import extract_docx, extract_pdf, fetch_public_url


router = APIRouter(prefix="/api/references", tags=["references"])


class ReferenceImport(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    source_type: Literal["paste", "txt"]
    text: str = Field(min_length=1, max_length=1_000_000)
    platform: str | None = Field(default=None, max_length=80)
    content_type: Literal[
        "reference_work", "platform_rule", "popular_sample", "writing_tutorial", "competitor_work",
    ] | None = None
    project_id: str | None = None


class ExtractedReferenceImport(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    source_type: Literal["docx", "pdf", "url"]
    text: str | None = Field(default=None, max_length=1_000_000)
    source_uri: str | None = Field(default=None, max_length=2000)
    data_base64: str | None = None
    warnings: list[str] = Field(default_factory=list)
    platform: str | None = Field(default=None, max_length=80)
    content_type: Literal[
        "reference_work", "platform_rule", "popular_sample", "writing_tutorial", "competitor_work",
    ] | None = None
    project_id: str | None = None


class ReferenceMetadataUpdate(BaseModel):
    platform: str | None = Field(default=None, max_length=80)
    content_type: Literal[
        "reference_work", "platform_rule", "popular_sample", "writing_tutorial", "competitor_work",
    ]
    project_id: str | None = None


def _library(request: Request):
    return request.app.state.references


def _validate_project(request: Request, project_id: str | None) -> None:
    if project_id:
        request.app.state.projects.get(project_id)


def _public(value):
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items() if key != "storage_path"}
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


def _with_market(request: Request, value):
    public = _public(value)
    market = getattr(request.app.state, "market", None)
    if market is None:
        return public
    if isinstance(public, list):
        return [_with_market(request, item) for item in public]
    if isinstance(public, dict) and public.get("id"):
        public["market_context"] = market.reference_context(public["id"])
    return public


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("")
def list_references(request: Request) -> list[dict]:
    return _with_market(request, _library(request).list())


@router.post("", status_code=status.HTTP_201_CREATED)
def import_reference(payload: ReferenceImport, request: Request) -> dict:
    try:
        _validate_project(request, payload.project_id)
        return _with_market(request, _library(request).import_text(
            title=payload.title, text=payload.text, source_type=payload.source_type,
            platform=payload.platform, content_type=payload.content_type, project_id=payload.project_id,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/import", status_code=status.HTTP_201_CREATED)
def import_extracted_reference(payload: ExtractedReferenceImport, request: Request) -> dict:
    try:
        _validate_project(request, payload.project_id)
        text, title, source_uri = payload.text, payload.title, payload.source_uri
        if payload.source_type == "url" and not text:
            fetched = fetch_public_url(source_uri or "")
            text, title, source_uri = fetched["text"], title or fetched["title"], fetched["url"]
        elif not text:
            raw = base64.b64decode(payload.data_base64 or "", validate=True)
            text = extract_docx(raw) if payload.source_type == "docx" else extract_pdf(raw)
        return _with_market(request, _library(request).import_text(
            title=title, text=text or "", source_type=payload.source_type,
            source_uri=source_uri, warnings=payload.warnings, platform=payload.platform,
            content_type=payload.content_type, project_id=payload.project_id,
        ))
    except LookupError as exc:
        raise _not_found(exc) from exc
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{source_id}")
def get_reference(source_id: str, request: Request) -> dict:
    try:
        return _with_market(request, _library(request).get(source_id))
    except (LookupError, ValueError) as exc:
        raise _not_found(exc) from exc


@router.get("/{source_id}/content")
def get_reference_content(source_id: str, request: Request) -> dict:
    try:
        return {"source_id": source_id, "text": _library(request).read_text(source_id)}
    except (LookupError, ValueError) as exc:
        raise _not_found(exc) from exc


@router.post("/{source_id}/analyze")
def analyze_reference(source_id: str, request: Request) -> dict:
    try:
        return _public(_library(request).analyze(source_id))
    except (LookupError, ValueError) as exc:
        raise _not_found(exc) from exc


@router.patch("/{source_id}/metadata")
def update_reference_metadata(
    source_id: str, payload: ReferenceMetadataUpdate, request: Request,
) -> dict:
    try:
        if payload.project_id:
            request.app.state.projects.get(payload.project_id)
        return _with_market(request, _library(request).update_metadata(
            source_id, platform=payload.platform, content_type=payload.content_type,
            project_id=payload.project_id,
        ))
    except LookupError as exc:
        raise _not_found(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{source_id}/popular-analysis")
def popular_reference_analysis(source_id: str, request: Request) -> dict:
    from novel_flywheel.popular_analysis import analyze_popular_sample
    try:
        source = _library(request).get(source_id)
        if source["content_type"] != "popular_sample":
            raise ValueError("请先将内容类型改为“爆款样本”")
        report = analyze_popular_sample(source["title"], _library(request).read_text(source_id))
        report["market_evidence"] = request.app.state.market.reference_context(source_id)
        return report
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reference(source_id: str, request: Request) -> Response:
    try:
        _library(request).delete(source_id)
    except (LookupError, ValueError) as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
