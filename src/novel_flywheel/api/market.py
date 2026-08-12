from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel

from novel_flywheel.api.errors import safe_http_exception


router = APIRouter(prefix="/api/market", tags=["market"])


class MarketRefresh(BaseModel):
    source_id: str = "zhihu-salt"


class MarketLink(BaseModel):
    work_id: str


class MarketLengthUpdate(BaseModel):
    length_type: str | None = None


def _market(request: Request):
    return request.app.state.market


def _baselines(request: Request):
    return request.app.state.market_baselines


def _market_not_found(exc: BaseException, boundary: str) -> HTTPException:
    return safe_http_exception(
        exc, status_code=404, boundary=boundary,
        code="market.resource_not_found", family="request.resource_not_found",
        message="请求的市场数据不存在或已被删除。",
    )


def _market_invalid(exc: BaseException, boundary: str) -> HTTPException:
    return safe_http_exception(
        exc, status_code=422, boundary=boundary,
        code="market.request_invalid", family="request.domain_validation",
        message="市场数据请求未通过校验，请检查输入后重试。",
    )


@router.get("/sources")
def list_sources(request: Request) -> list[dict]:
    return _market(request).list_sources()


@router.post("/refresh")
def refresh_market(payload: MarketRefresh, request: Request) -> dict:
    try:
        return _market(request).refresh(payload.source_id)
    except ValueError as exc:
        raise _market_invalid(exc, "market.refresh") from exc


@router.get("/dashboard")
def market_dashboard(
    request: Request,
    platform: str | None = None,
    days: int = Query(default=30, ge=1, le=365),
    ranking: str | None = None,
    category: str | None = None,
    length_type: str | None = None,
) -> dict:
    return _market(request).dashboard(
        platform=platform, days=days, ranking=ranking, category=category,
        length_type=length_type,
    )


@router.get("/works")
def list_market_works(
    request: Request,
    platform: str | None = None,
    ranking: str | None = None,
    category: str | None = None,
    length_type: str | None = None,
) -> list[dict]:
    return _market(request).list_works(
        platform=platform, ranking=ranking, category=category, length_type=length_type,
    )


@router.get("/baselines")
def list_market_baselines(request: Request) -> list[dict]:
    return _baselines(request).list_cohorts()


@router.get("/baseline")
def market_baseline(
    request: Request, platform: str, ranking_name: str,
    category: str, length_type: str,
) -> dict:
    try:
        return _baselines(request).build_baseline({
            "platform": platform, "ranking_name": ranking_name,
            "category": category, "length_type": length_type,
        })
    except ValueError as exc:
        raise _market_invalid(exc, "market.baseline") from exc


@router.put("/works/{work_id:path}/length")
def update_market_work_length(
    work_id: str, payload: MarketLengthUpdate, request: Request,
) -> dict:
    try:
        return _market(request).set_length_type(work_id, payload.length_type)
    except LookupError as exc:
        raise _market_not_found(exc, "market.work.length") from exc
    except ValueError as exc:
        raise _market_invalid(exc, "market.work.length") from exc


@router.get("/works/{work_id:path}")
def market_work_detail(work_id: str, request: Request) -> dict:
    try:
        return _market(request).work_detail(work_id)
    except LookupError as exc:
        raise _market_not_found(exc, "market.work.detail") from exc


@router.get("/references/{reference_id}/match")
def match_reference(reference_id: str, request: Request) -> dict:
    try:
        return _market(request).match_reference(reference_id)
    except LookupError as exc:
        raise _market_not_found(exc, "market.reference.match") from exc


@router.put("/references/{reference_id}/link")
def link_reference(reference_id: str, payload: MarketLink, request: Request) -> dict:
    try:
        return _market(request).confirm_link(reference_id, payload.work_id)
    except LookupError as exc:
        raise _market_not_found(exc, "market.reference.link") from exc


@router.delete("/references/{reference_id}/link", status_code=status.HTTP_204_NO_CONTENT)
def unlink_reference(reference_id: str, request: Request) -> Response:
    _market(request).unlink_reference(reference_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
