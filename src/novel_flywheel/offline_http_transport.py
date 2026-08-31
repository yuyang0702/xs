"""In-memory HTTP boundary for deterministic offline production-path checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

import httpx


@dataclass(frozen=True)
class OfflineHttpRequestV1:
    method: str
    url: str
    content: bytes
    headers: Mapping[str, str]


@dataclass(frozen=True)
class OfflineHttpResponseV1:
    status_code: int
    json_body: Any | None = None
    content: bytes | None = None
    headers: Mapping[str, str] = field(default_factory=dict)


OfflineHandlerV1 = Callable[
    [OfflineHttpRequestV1], Awaitable[OfflineHttpResponseV1]
]


def build_offline_http_transport_v1(handler: OfflineHandlerV1) -> Any:
    """Return a MockTransport without exposing third-party imports to callers."""

    async def respond(request: httpx.Request) -> httpx.Response:
        specification = await handler(OfflineHttpRequestV1(
            method=request.method,
            url=str(request.url),
            content=request.content,
            headers=dict(request.headers),
        ))
        if specification.content is not None:
            return httpx.Response(
                specification.status_code,
                content=specification.content,
                headers=dict(specification.headers),
                request=request,
            )
        return httpx.Response(
            specification.status_code,
            json=specification.json_body,
            headers=dict(specification.headers),
            request=request,
        )

    return httpx.MockTransport(respond)


def build_offline_http_client_v1(
    transport: Any, *, timeout_seconds: float = 30,
) -> Any:
    return httpx.AsyncClient(transport=transport, timeout=timeout_seconds)


def offline_read_timeout_v1(message: str) -> BaseException:
    """Create a typed offline transport timeout without exporting httpx."""

    return httpx.ReadTimeout(message)
