from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


_FAILURE_CODE = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")
_WINDOWS_PATH = re.compile(r"(?i)\b[a-z]:[\\/][^\s\]\[(){}<>\"']+")
_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:[^\s/]+/)+[^\s\]\[(){}<>\"']+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|access[_ -]?token|refresh[_ -]?token|"
    r"client[_ -]?secret|private[_ -]?key|password|passwd|pwd|token|secret)"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_AWS_ACCESS_KEY = re.compile(
    r"(?<![A-Za-z0-9])(?:AKIA|ASIA|AIDA|AROA)[A-Z0-9]{16}(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_GITHUB_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_JWT = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{6,}\."
    r"[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}(?![A-Za-z0-9_-])"
)
_PRIVATE_KEY_MARKER = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE,
)
_HIGH_ENTROPY_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Fa-f0-9]{32,}|[A-Za-z0-9+/=_-]{32,})"
    r"(?![A-Za-z0-9])"
)
_HIGH_ENTROPY_NONSPACE = re.compile(r"\S{32,}")


def _is_high_entropy_candidate(value: str) -> bool:
    candidate = value.strip("=+-_/.,;:!?()[]{}<>\"'")
    if len(candidate) < 32:
        return False
    if re.fullmatch(r"[A-Fa-f0-9]{32,}", candidate):
        return True
    counts = {character: candidate.count(character) for character in set(candidate)}
    entropy = -sum(
        (count / len(candidate)) * math.log2(count / len(candidate))
        for count in counts.values()
    )
    has_digit = any(character.isdigit() for character in candidate)
    mixed_case = any(character.islower() for character in candidate) and any(
        character.isupper() for character in candidate
    )
    return entropy >= 4.0 and (has_digit or mixed_case)


def contains_potential_secret(value: object) -> bool:
    """Fail closed for values unsafe to copy into durable/public metadata."""

    # Compatibility normalization is detection-only: full-width labels must
    # not bypass the exact same credential rules as their ASCII forms.
    text = unicodedata.normalize("NFKC", str(value or ""))
    folded = text.casefold()
    if any((
        _SECRET_ASSIGNMENT.search(text), _BEARER_VALUE.search(text),
        _AWS_ACCESS_KEY.search(text), _GITHUB_TOKEN.search(text),
        _JWT.search(text), _PRIVATE_KEY_MARKER.search(text),
        _WINDOWS_PATH.search(text), _POSIX_PATH.search(text),
    )):
        return True
    if any(marker in folded for marker in (
        "private_credential", "secret_value", "api_key_value",
        "password_value",
    )):
        return True
    return any(
        _is_high_entropy_candidate(match.group(0))
        for match in _HIGH_ENTROPY_CANDIDATE.finditer(text)
    ) or any(
        _is_high_entropy_candidate(match.group(0))
        for match in _HIGH_ENTROPY_NONSPACE.finditer(text)
    )


def redact_potential_secrets(value: object) -> str:
    """Deterministically remove common credentials and opaque secret material."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=<redacted>", text,
    )
    for pattern in (
        _BEARER_VALUE, _AWS_ACCESS_KEY, _GITHUB_TOKEN, _JWT,
        _PRIVATE_KEY_MARKER,
    ):
        text = pattern.sub("<redacted>", text)
    text = _HIGH_ENTROPY_CANDIDATE.sub(
        lambda match: (
            "<redacted>"
            if _is_high_entropy_candidate(match.group(0)) else match.group(0)
        ),
        text,
    )
    text = _HIGH_ENTROPY_NONSPACE.sub(
        lambda match: (
            "<redacted>"
            if _is_high_entropy_candidate(match.group(0)) else match.group(0)
        ),
        text,
    )
    return text


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

    safe_fallback = redact_potential_secrets(fallback)
    safe_fallback = _WINDOWS_PATH.sub("<path>", safe_fallback)
    safe_fallback = _POSIX_PATH.sub("<path>", safe_fallback)
    safe_fallback = re.sub(r"\s+", " ", safe_fallback).strip()[:300]
    safe_fallback = safe_fallback or "输入未通过本地校验。"
    message = unicodedata.normalize("NFC", str(exc or "")).strip()
    if not message:
        return safe_fallback
    message = redact_potential_secrets(message)
    message = _WINDOWS_PATH.sub("<path>", message)
    message = _POSIX_PATH.sub("<path>", message)
    message = re.sub(r"\s+", " ", message).strip()
    return message[:300] or safe_fallback
