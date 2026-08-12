from __future__ import annotations

from fastapi import HTTPException

from novel_flywheel.failure_boundary import project_safe_failure


def bounded_public_code(
    exc: BaseException, *, allowed: frozenset[str], default: str,
) -> str:
    """Convert a closed-world local code without exposing unknown text."""

    candidate = str(exc).strip().casefold()
    return candidate if candidate in allowed else default


def safe_http_exception(
    exc: BaseException, *, status_code: int, boundary: str, code: str,
    family: str, message: str, retryable: bool = False,
    recovery_action: str = "correct_request_and_retry",
) -> HTTPException:
    failure = project_safe_failure(
        exc, boundary=boundary, code=code, family=family, message=message,
        retryable=retryable, recovery_action=recovery_action,
    )
    return HTTPException(status_code=status_code, detail=failure.api_detail())
