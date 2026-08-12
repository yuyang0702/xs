from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


_FAILURE_CODE = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")
_WINDOWS_PATH = re.compile(r"(?i)\b[a-z]:[\\/][^\s\]\[(){}<>\"']+")
_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:[^\s/]+/)+[^\s\]\[(){}<>\"']+")
_SECRET_VALUE = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|bearer|access[_ -]?token|secret)"
    r"\s*[:=]\s*[^\s,;]+"
)


class SafeFailureEnvelopeV1(BaseModel):
    """The only representation allowed to cross a UI or persistence boundary.

    Raw exception text is deliberately used only to derive ``failure_sha256``.
    It is never stored in this model, returned to the caller, or written to a
    run event.  Domain-specific callers provide a reviewed, static message.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    code: str = Field(min_length=3, max_length=128)
    family: str = Field(min_length=3, max_length=128)
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False
    recovery_action: str = Field(min_length=1, max_length=200)
    failure_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def api_detail(self) -> dict[str, object]:
        return {
            "version": self.version,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "recovery_action": self.recovery_action,
            "incident_id": self.failure_sha256[:16],
        }

    def persistence_summary(self) -> str:
        return (
            f"{self.message} "
            f"[code={self.code}; incident={self.failure_sha256[:16]}]"
        )

    def event_metadata(self) -> dict[str, object]:
        return {
            "failure_contract": "safe-failure-envelope-v1",
            "failure_code": self.code,
            "failure_family": self.family,
            "failure_sha256": self.failure_sha256,
            "retryable": self.retryable,
            "recovery_action": self.recovery_action,
        }


def failure_evidence_sha256(exc: BaseException, *, boundary: str) -> str:
    reliability = getattr(exc, "reliability_failure", None)
    evidence = "\n".join((
        str(boundary),
        type(exc).__name__,
        str(exc),
        str(getattr(reliability, "code", "") or ""),
        str(getattr(reliability, "failure_class", "") or ""),
    ))
    return hashlib.sha256(evidence.encode("utf-8", errors="replace")).hexdigest()


def project_safe_failure(
    exc: BaseException, *, boundary: str, code: str, family: str,
    message: str, retryable: bool = False,
    recovery_action: str = "retry_or_contact_support",
) -> SafeFailureEnvelopeV1:
    normalized_code = str(code or "").strip().casefold()
    normalized_family = str(family or "").strip().casefold()
    if not _FAILURE_CODE.fullmatch(normalized_code):
        raise ValueError("safe failure code is invalid")
    if not _FAILURE_CODE.fullmatch(normalized_family):
        raise ValueError("safe failure family is invalid")
    safe_message = str(message or "").strip()
    if not safe_message:
        raise ValueError("safe failure message is required")
    return SafeFailureEnvelopeV1(
        code=normalized_code,
        family=normalized_family,
        message=safe_message,
        retryable=bool(retryable),
        recovery_action=str(recovery_action or "retry_or_contact_support").strip(),
        failure_sha256=failure_evidence_sha256(exc, boundary=boundary),
    )


def safe_persistence_error(
    exc: BaseException, *, boundary: str, code: str, family: str,
    message: str, retryable: bool = False,
    recovery_action: str = "resume_from_checkpoint",
) -> str:
    return project_safe_failure(
        exc, boundary=boundary, code=code, family=family, message=message,
        retryable=retryable, recovery_action=recovery_action,
    ).persistence_summary()


def safe_local_validation_message(
    exc: BaseException, *, fallback: str = "输入未通过本地校验。",
) -> str:
    """Keep actionable local validator feedback after deterministic redaction."""

    message = unicodedata.normalize("NFC", str(exc or "")).strip()
    if not message:
        return fallback
    message = _SECRET_VALUE.sub(lambda match: f"{match.group(1)}=<redacted>", message)
    message = _WINDOWS_PATH.sub("<path>", message)
    message = _POSIX_PATH.sub("<path>", message)
    message = re.sub(r"\s+", " ", message).strip()
    return message[:300] or fallback
