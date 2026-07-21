from typing import Any

import httpx


class HttpProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        headers: dict[str, str] | None = None,
        timeout: float = 180,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = headers or {}
        self.client = httpx.AsyncClient(timeout=timeout)

    async def post(self, path: str, *, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        response = await self.client.post(
            f"{self.base_url}/{path.lstrip('/')}",
            json=payload,
            headers={**headers, **self.headers},
        )
        response.raise_for_status()
        return response.json()

