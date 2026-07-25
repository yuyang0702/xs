import asyncio
import json
from typing import Any

import httpx


class ToolCapabilityError(RuntimeError):
    pass


class ProviderResponseError(RuntimeError):
    pass


class HttpProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        headers: dict[str, str] | None = None,
        timeout: float = 180,
        auth_type: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = headers or {}
        self.auth_type = auth_type
        self.client = httpx.AsyncClient(timeout=timeout)

    async def post(self, path: str, *, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        for attempt in range(2):
            try:
                response = await self.client.post(
                    f"{self.base_url}/{path.lstrip('/')}",
                    json=payload,
                    headers={**headers, **self.headers},
                )
                break
            except httpx.TransportError as exc:
                if isinstance(exc, httpx.TimeoutException) or attempt:
                    raise
                await asyncio.sleep(0.25)
        if response.status_code in {400, 404, 422} and "tools" in payload:
            detail = response.text.lower()
            if any(term in detail for term in ("tool", "function calling", "function_call")):
                raise ToolCapabilityError(response.text[:500])
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            content_type = response.headers.get("content-type", "unknown")
            raise ProviderResponseError(
                f"Provider endpoint returned non-JSON content ({content_type}) from {response.url}"
            ) from exc

    async def post_stream(
        self, path: str, *, payload: dict[str, Any], headers: dict[str, str],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        request_headers = {**headers, **self.headers}
        for attempt in range(2):
            events: list[dict[str, Any]] = []
            try:
                async with self.client.stream("POST", url, json=payload, headers=request_headers) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        detail = response.text.lower()
                        if response.status_code in {400, 404, 422} and "stream_options" in detail:
                            fallback = dict(payload)
                            fallback.pop("stream_options", None)
                            return await self.post_stream(path, payload=fallback, headers=headers)
                        if (response.status_code in {400, 404, 422}
                                and "stream" in detail
                                and any(term in detail for term in ("unsupported", "not support", "invalid"))):
                            fallback = {**payload, "stream": False}
                            return [], await self.post(path, payload=fallback, headers=headers)
                        if (response.status_code in {400, 404, 422} and "tools" in payload
                                and any(term in detail for term in
                                        ("tool", "function calling", "function_call"))):
                            raise ToolCapabilityError(response.text[:500])
                        response.raise_for_status()

                    content_type = response.headers.get("content-type", "")
                    if "text/event-stream" not in content_type:
                        await response.aread()
                        try:
                            return [], response.json()
                        except ValueError as exc:
                            raise ProviderResponseError(
                                f"Provider endpoint returned non-JSON content ({content_type or 'unknown'}) "
                                f"from {response.url}"
                            ) from exc

                    data_lines: list[str] = []
                    async for line in response.aiter_lines():
                        if not line:
                            if data_lines:
                                raw = "\n".join(data_lines)
                                data_lines.clear()
                                if raw != "[DONE]":
                                    try:
                                        events.append(json.loads(raw))
                                    except ValueError as exc:
                                        raise ProviderResponseError(
                                            f"Provider returned invalid SSE JSON from {response.url}"
                                        ) from exc
                            continue
                        if line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
                    if data_lines:
                        raw = "\n".join(data_lines)
                        if raw != "[DONE]":
                            events.append(json.loads(raw))
                    return events, None
            except httpx.TransportError as exc:
                if isinstance(exc, httpx.TimeoutException) or events or attempt:
                    raise
                await asyncio.sleep(0.25)
        raise RuntimeError("unreachable")
