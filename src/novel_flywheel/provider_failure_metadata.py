"""Privacy-safe metadata projection for HTTP/provider route failures."""
from __future__ import annotations


def safe_http_failure_metadata(exc: BaseException) -> dict[str, object]:
    """Return bounded facts without retaining response bodies or credentials."""

    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    try:
        status = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        status = None
    provider_error_code: str | None = None
    retry_after_seconds: float | None = None
    retry_after_present = False
    usage_observed: bool | None = None
    if response is not None:
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("retry-after")
        retry_after_present = retry_after is not None
        try:
            retry_after_seconds = max(0.0, min(86400.0, float(retry_after)))
        except (TypeError, ValueError):
            retry_after_seconds = None
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            for key in ("code", "type"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    provider_error_code = value.strip()[:120]
                    break
            usage_observed = isinstance(payload.get("usage"), dict)
    return {
        "http_status": status,
        "provider_error_code": provider_error_code,
        "retry_after_present": retry_after_present,
        "retry_after_seconds": retry_after_seconds,
        "request_sent": response is not None,
        "usage_observed": usage_observed,
        "http_failure_class": (
            "credential_or_permission" if status in {401, 403}
            else "route_or_configuration" if status == 404
            else "rate_limit_or_quota" if status == 429
            else "upstream_provider" if status is not None and status >= 500
            else "http_rejection" if status is not None and status >= 400
            else None
        ),
    }
