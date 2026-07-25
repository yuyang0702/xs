from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/references", tags=["references"])


class ReferenceImport(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    source_type: Literal["paste", "txt"]
    text: str = Field(min_length=1, max_length=1_000_000)


def _library(request: Request):
    return request.app.state.references


def _public(value):
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items() if key != "storage_path"}
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("")
def list_references(request: Request) -> list[dict]:
    return _public(_library(request).list())


@router.post("", status_code=status.HTTP_201_CREATED)
def import_reference(payload: ReferenceImport, request: Request) -> dict:
    try:
        return _public(_library(request).import_text(
            title=payload.title, text=payload.text, source_type=payload.source_type,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{source_id}")
def get_reference(source_id: str, request: Request) -> dict:
    try:
        return _public(_library(request).get(source_id))
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


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reference(source_id: str, request: Request) -> Response:
    try:
        _library(request).delete(source_id)
    except (LookupError, ValueError) as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
