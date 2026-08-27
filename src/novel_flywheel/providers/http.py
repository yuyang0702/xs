import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Protocol

import httpx


class ToolCapabilityError(RuntimeError):
    pass


class ProviderResponseError(RuntimeError):
    pass


class SingleDispatchTransportGuardError(RuntimeError):
    pass


class SingleDispatchAttemptObserver(Protocol):
    """Optional pilot-only observer called at the actual outbound boundary."""

    def before_http_post(self) -> None: ...

    def before_network_request(self) -> None: ...


@dataclass(frozen=True)
class SingleDispatchTransportPolicyV1:
    """Non-default transport policy for an explicitly one-dispatch call."""

    schema: str = "SingleDispatchTransportPolicyV1"
    version: int = 1
    mode: str = "single_dispatch"
    max_http_post_attempts: int = 1
    sdk_retries_disabled: bool = True
    transport_request_retries_disabled: bool = True
    application_second_dispatch_allowed: bool = False

    def __post_init__(self) -> None:
        if asdict(self) != {
            "schema": "SingleDispatchTransportPolicyV1",
            "version": 1,
            "mode": "single_dispatch",
            "max_http_post_attempts": 1,
            "sdk_retries_disabled": True,
            "transport_request_retries_disabled": True,
            "application_second_dispatch_allowed": False,
        }:
            raise ValueError("single_dispatch_transport_policy_invalid")

    @classmethod
    def phase_b(cls) -> "SingleDispatchTransportPolicyV1":
        return cls()

    def definition(self) -> dict[str, Any]:
        return asdict(self)

    def definition_sha256(self) -> str:
        encoded = json.dumps(
            self.definition(), sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class HttpProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        headers: dict[str, str] | None = None,
        timeout: float = 180,
        auth_type: str | None = None,
        transport_policy: SingleDispatchTransportPolicyV1 | None = None,
        attempt_observer: SingleDispatchAttemptObserver | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = headers or {}
        self.auth_type = auth_type
        self.transport_policy = transport_policy
        self.attempt_observer = attempt_observer
        self._model_logical_calls = 0
        self._http_post_attempts = 0
        if transport_policy is None:
            self.client = httpx.AsyncClient(timeout=timeout)
        else:
            self.client = httpx.AsyncClient(
                timeout=timeout,
                transport=httpx.AsyncHTTPTransport(retries=0),
            )

    def _begin_logical_call(self) -> None:
        if self.transport_policy is None:
            return
        if self._model_logical_calls >= 1:
            raise SingleDispatchTransportGuardError(
                "single_dispatch_model_logical_call_limit_exhausted",
            )
        self._model_logical_calls += 1

    def _before_http_post_attempt(self) -> None:
        policy = self.transport_policy
        if policy is not None and self._http_post_attempts >= policy.max_http_post_attempts:
            raise SingleDispatchTransportGuardError(
                "single_dispatch_http_post_attempt_limit_exhausted",
            )
        self._http_post_attempts += 1
        if self.attempt_observer is not None:
            self.attempt_observer.before_http_post()
            self.attempt_observer.before_network_request()

    def transport_attempt_snapshot(self) -> dict[str, Any]:
        policy = self.transport_policy
        return {
            "guard_active": policy is not None,
            "max_http_post_attempts": (
                policy.max_http_post_attempts if policy is not None else None
            ),
            "model_logical_calls": self._model_logical_calls,
            "real_provider_request_attempts": self._http_post_attempts,
            "http_post_attempts": self._http_post_attempts,
            "network_request_attempts": self._http_post_attempts,
            "sdk_retries_disabled": (
                policy.sdk_retries_disabled if policy is not None else False
            ),
            "transport_request_retries_disabled": (
                policy.transport_request_retries_disabled
                if policy is not None else False
            ),
            "application_second_dispatch_allowed": (
                policy.application_second_dispatch_allowed
                if policy is not None else True
            ),
        }

    async def post(self, path: str, *, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self._begin_logical_call()
        max_attempts = 1 if self.transport_policy is not None else 2
        for attempt in range(max_attempts):
            try:
                self._before_http_post_attempt()
                response = await self.client.post(
                    f"{self.base_url}/{path.lstrip('/')}",
                    json=payload,
                    headers={**headers, **self.headers},
                )
                break
            except httpx.TransportError as exc:
                if (self.transport_policy is not None
                        or isinstance(exc, httpx.TimeoutException) or attempt):
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
        self._begin_logical_call()
        url = f"{self.base_url}/{path.lstrip('/')}"
        request_headers = {**headers, **self.headers}
        max_attempts = 1 if self.transport_policy is not None else 2
        for attempt in range(max_attempts):
            events: list[dict[str, Any]] = []
            try:
                self._before_http_post_attempt()
                async with self.client.stream("POST", url, json=payload, headers=request_headers) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        detail = response.text.lower()
                        if (self.transport_policy is None
                                and response.status_code in {400, 404, 422}
                                and "stream_options" in detail):
                            fallback = dict(payload)
                            fallback.pop("stream_options", None)
                            return await self.post_stream(path, payload=fallback, headers=headers)
                        if (self.transport_policy is None
                                and response.status_code in {400, 404, 422}
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
                if (self.transport_policy is not None
                        or isinstance(exc, httpx.TimeoutException) or events or attempt):
                    raise
                await asyncio.sleep(0.25)
        raise RuntimeError("unreachable")
