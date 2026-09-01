import asyncio
from contextlib import aclosing
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Protocol

import httpx

from novel_flywheel.execution_failure_architecture import (
    AuthorityEffect,
    DispatchState,
    ExecutionBoundaryFailure,
    FailureLayer,
    ProviderRequestBuildFailure,
    RestartBehavior,
)
from novel_flywheel.provider_response_capture import (
    ProviderResponseCaptureError,
    parse_provider_protocol_input_bytes_v1,
    provider_protocol_input_has_terminal_bytes_v1,
)
from novel_flywheel.recovery_engine import FailureClass, ReliabilityFailure


class ToolCapabilityError(RuntimeError):
    pass


class ProviderResponseError(RuntimeError):
    def __init__(self, message: str) -> None:
        self.reliability_failure = ReliabilityFailure(
            code="provider_response_projection_failure",
            failure_class=FailureClass.SYNTAX_PROTOCOL,
            boundary="provider_response_projection",
            message=message,
            retryable=False,
        )
        super().__init__(message)


class SingleDispatchTransportGuardError(ExecutionBoundaryFailure):
    """Typed fail-closed guard for a source-predictable extra dispatch."""

    def __init__(self, code: str) -> None:
        credential_reflection = code == "credential_reflection_rejected"
        super().__init__(
            code,
            layer=(
                FailureLayer.PROVIDER_REQUEST_BUILD
                if credential_reflection
                else FailureLayer.WORKFLOW_RECOVERY
            ),
            boundary=(
                "provider_http.request_materialization"
                if credential_reflection
                else "provider_http.single_dispatch_guard"
            ),
            failure_class=FailureClass.OWNERSHIP_EVIDENCE,
            dispatch_state=DispatchState.NOT_REACHED,
            authority_effect=AuthorityEffect.BLOCKS_ACCEPTANCE,
            restart_behavior=(
                RestartBehavior.FRESH_AUTHORIZATION_REQUIRED
                if credential_reflection
                else RestartBehavior.NO_REDISPATCH
            ),
            recovery_action=(
                "remove_credential_reflection_then_fresh_authorization"
                if credential_reflection
                else "stop_without_additional_dispatch"
            ),
        )


_MAX_CONTENT_TYPE_PROVENANCE_CHARS = 128


def _bounded_content_type_provenance(content_type: str) -> str:
    """Return a bounded, single-line copy of response media-type metadata."""

    sanitized = "".join(
        character if character.isprintable() and character not in "\r\n" else "?"
        for character in content_type
    ) or "unknown"
    if len(sanitized) <= _MAX_CONTENT_TYPE_PROVENANCE_CHARS:
        return sanitized
    return sanitized[:_MAX_CONTENT_TYPE_PROVENANCE_CHARS - 3] + "..."


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
        injected_http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = headers or {}
        self.auth_type = auth_type
        self.transport_policy = transport_policy
        self.attempt_observer = attempt_observer
        self._model_logical_calls = 0
        self._http_post_attempts = 0
        self._last_protocol_input_v1: tuple[bytes, str, str] | None = None
        if injected_http_transport is not None:
            if type(injected_http_transport) is not httpx.MockTransport:
                raise ValueError("offline_http_transport_must_be_mock_transport")
            self.client = httpx.AsyncClient(
                timeout=timeout, transport=injected_http_transport,
            )
        elif transport_policy is None:
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

    def _bind_model_request(self, protocol: str, request: Any) -> None:
        if self.attempt_observer is None:
            return
        callback = getattr(self.attempt_observer, "bind_model_request", None)
        if callable(callback):
            callback(protocol=protocol, request=request)

    @staticmethod
    def _contains_exact_scalar(value: Any, forbidden: str) -> bool:
        if isinstance(value, dict):
            return any(
                forbidden in str(key)
                or HttpProvider._contains_exact_scalar(item, forbidden)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(
                HttpProvider._contains_exact_scalar(item, forbidden)
                for item in value
            )
        return isinstance(value, str) and forbidden in value

    def _build_http_post_request(
        self, *, url: str, payload: dict[str, Any], headers: dict[str, str],
    ) -> httpx.Request:
        """Materialize deterministic wire bytes before dispatch authority."""

        self._last_protocol_input_v1 = None
        policy = self.transport_policy
        if policy is not None and self._http_post_attempts >= policy.max_http_post_attempts:
            raise SingleDispatchTransportGuardError(
                "single_dispatch_http_post_attempt_limit_exhausted",
            )
        if self.api_key and self._contains_exact_scalar(payload, self.api_key):
            raise SingleDispatchTransportGuardError(
                "credential_reflection_rejected",
            )
        try:
            return self.client.build_request(
                "POST", url, json=payload, headers={**headers, **self.headers},
            )
        except Exception as exc:
            # Request serialization/materialization is local and precedes the
            # dispatch-authority transition.  Preserve it as a typed owned
            # failure instead of letting an arbitrary SDK exception escape.
            raise ProviderRequestBuildFailure() from exc

    def _before_http_post_attempt(
        self, *, url: str, payload: dict[str, Any], request_bytes: bytes,
    ) -> None:
        # The local one-call ceiling is knowable before the observer may
        # reserve dispatch authority or a durable nonce.
        self._begin_logical_call()
        if self.attempt_observer is not None:
            before_dispatch = getattr(
                self.attempt_observer, "before_http_dispatch", None,
            )
            if callable(before_dispatch):
                before_dispatch(
                    method="POST", url=url, payload=payload,
                    request_bytes=request_bytes,
                )
        self._http_post_attempts += 1
        if self.attempt_observer is not None:
            self.attempt_observer.before_http_post()
            self.attempt_observer.before_network_request()

    def _after_http_response(self, status_code: int) -> None:
        if self.attempt_observer is None:
            return
        callback = getattr(self.attempt_observer, "after_http_response", None)
        if callable(callback):
            callback(status_code=status_code)

    def _after_http_failure(self, exc: BaseException) -> None:
        if self.attempt_observer is None:
            return
        callback = getattr(self.attempt_observer, "after_http_failure", None)
        if callable(callback):
            callback(failure_kind=type(exc).__name__)

    def _capture_provider_protocol_input(
        self, data: bytes, *, status_code: int, content_type: str,
        encoding: str, transport_complete: bool,
    ) -> None:
        if self.attempt_observer is None:
            return
        callback = getattr(
            self.attempt_observer, "capture_provider_protocol_input", None,
        )
        if callable(callback):
            callback(
                data=data, status_code=status_code,
                content_type=content_type or "application/octet-stream",
                encoding=encoding or "utf-8",
                transport_complete=transport_complete,
            )

    def capture_contract_runtime_input(
        self, text: str, *, adapter_id: str, adapter_version: int,
        finish_reason: str | None, transport_complete: bool,
    ) -> None:
        """Persist the exact UTF-8 text passed toward Contract Runtime."""

        if self.attempt_observer is None:
            return
        callback = getattr(
            self.attempt_observer, "capture_contract_runtime_input", None,
        )
        if callable(callback):
            callback(
                data=text.encode("utf-8"), adapter_id=adapter_id,
                adapter_version=adapter_version,
                finish_reason=finish_reason,
                transport_complete=transport_complete,
            )

    def _replay_last_protocol_input_v1(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None] | None:
        """Reparse the last complete entity locally without another dispatch."""

        captured = self._last_protocol_input_v1
        if captured is None:
            return None
        data, content_type, encoding = captured
        return parse_provider_protocol_input_bytes_v1(
            data, content_type=content_type, encoding=encoding,
        )

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
        url = f"{self.base_url}/{path.lstrip('/')}"
        max_attempts = 1 if self.transport_policy is not None else 2
        for attempt in range(max_attempts):
            try:
                request = self._build_http_post_request(
                    url=url, payload=payload, headers=headers,
                )
                self._before_http_post_attempt(
                    url=url, payload=payload, request_bytes=request.content,
                )
                response = await self.client.send(request)
                break
            except httpx.TransportError as exc:
                self._after_http_failure(exc)
                if (self.transport_policy is not None
                        or isinstance(exc, httpx.TimeoutException) or attempt):
                    raise
                await asyncio.sleep(0.25)
        try:
            # A received HTTP entity is evidence even when its status is not
            # successful.  Capture before capability/error interpretation so
            # the exact terminal response remains replayable after restart.
            self._capture_provider_protocol_input(
                response.content,
                status_code=response.status_code,
                content_type=response.headers.get("content-type", ""),
                encoding=response.encoding or "utf-8",
                transport_complete=True,
            )
            if response.status_code in {400, 404, 422} and "tools" in payload:
                detail = response.text.lower()
                if any(term in detail for term in ("tool", "function calling", "function_call")):
                    raise ToolCapabilityError(response.text[:500])
            response.raise_for_status()
            try:
                result = response.json()
            except ValueError as exc:
                content_type = _bounded_content_type_provenance(
                    response.headers.get("content-type", ""),
                )
                raise ProviderResponseError(
                    "Provider endpoint returned non-JSON content "
                    f"(content-type={content_type}) from {response.url}"
                ) from exc
        except Exception as exc:
            self._after_http_failure(exc)
            raise
        # A response is successful only after HTTP and protocol parsing.  This
        # prevents an error response from being rewritten as a completed local
        # stage by a later observer callback.
        self._after_http_response(response.status_code)
        return result

    async def post_stream(
        self, path: str, *, payload: dict[str, Any], headers: dict[str, str],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        request_headers = {**headers, **self.headers}
        max_attempts = 1 if self.transport_policy is not None else 2
        for attempt in range(max_attempts):
            events: list[dict[str, Any]] = []
            request = self._build_http_post_request(
                url=url, payload=payload, headers=request_headers,
            )
            try:
                self._before_http_post_attempt(
                    url=url, payload=payload, request_bytes=request.content,
                )
                async with aclosing(
                    await self.client.send(request, stream=True)
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        self._capture_provider_protocol_input(
                            response.content,
                            status_code=response.status_code,
                            content_type=response.headers.get(
                                "content-type", "",
                            ),
                            encoding=response.encoding or "utf-8",
                            transport_complete=True,
                        )
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
                    encoding = response.encoding or "utf-8"
                    chunks: list[bytes] = []
                    try:
                        async for chunk in response.aiter_bytes():
                            chunks.append(chunk)
                    except (
                        asyncio.CancelledError, httpx.TransportError,
                    ) as exc:
                        partial = b"".join(chunks)
                        terminal_bytes_received = (
                            provider_protocol_input_has_terminal_bytes_v1(
                                partial, content_type=content_type,
                                encoding=encoding,
                            )
                        )
                        self._capture_provider_protocol_input(
                            partial, status_code=response.status_code,
                            content_type=content_type,
                            encoding=encoding,
                            transport_complete=terminal_bytes_received,
                        )
                        if (
                            terminal_bytes_received
                            and (
                                isinstance(exc, httpx.TimeoutException)
                                or isinstance(exc, asyncio.CancelledError)
                            )
                        ):
                            self._last_protocol_input_v1 = (
                                partial, content_type, encoding,
                            )
                            try:
                                events, result = (
                                    parse_provider_protocol_input_bytes_v1(
                                        partial, content_type=content_type,
                                        encoding=encoding,
                                    )
                                )
                            except ProviderResponseCaptureError as exc:
                                raise ProviderResponseError(
                                    "Provider returned invalid terminal "
                                    "response bytes "
                                    "(content-type="
                                    f"{_bounded_content_type_provenance(content_type)}) "
                                    f"from {response.url}"
                                ) from exc
                            self._after_http_response(response.status_code)
                            return events, result
                        raise
                    entity = b"".join(chunks)
                    self._capture_provider_protocol_input(
                        entity, status_code=response.status_code,
                        content_type=content_type, encoding=encoding,
                        transport_complete=True,
                    )
                    self._last_protocol_input_v1 = (
                        entity, content_type, encoding,
                    )
                    try:
                        events, result = parse_provider_protocol_input_bytes_v1(
                            entity, content_type=content_type,
                            encoding=encoding,
                        )
                    except ProviderResponseCaptureError as exc:
                        raise ProviderResponseError(
                            "Provider returned invalid response bytes "
                            "(content-type="
                            f"{_bounded_content_type_provenance(content_type)}) "
                            f"from {response.url}"
                        ) from exc
                    self._after_http_response(response.status_code)
                    return events, result
            except httpx.TransportError as exc:
                self._after_http_failure(exc)
                if (self.transport_policy is not None
                        or isinstance(exc, httpx.TimeoutException) or events or attempt):
                    raise
                await asyncio.sleep(0.25)
            except asyncio.CancelledError as exc:
                self._after_http_failure(exc)
                raise
            except Exception as exc:
                self._after_http_failure(exc)
                raise
        raise RuntimeError("unreachable")
