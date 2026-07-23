import asyncio
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
