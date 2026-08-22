"""Explicit, versioned byte provenance for offline diagnostic fixtures."""

from __future__ import annotations

import hashlib
from typing import Literal


CANONICAL_TEXT_LF_V1 = "CANONICAL_TEXT_LF_V1"
RAW_BYTES_V1 = "RAW_BYTES_V1"

FixtureProvenanceContract = Literal[
    "CANONICAL_TEXT_LF_V1",
    "RAW_BYTES_V1",
]
EolShape = Literal["LF", "CRLF", "CR", "MIXED", "NONE"]


class FixtureProvenanceError(ValueError):
    """Typed base error that never includes fixture content."""

    code = "FIXTURE_PROVENANCE_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class CanonicalTextProvenanceDecodeError(FixtureProvenanceError):
    code = "CANONICAL_TEXT_PROVENANCE_DECODE_ERROR"


class UnsupportedFixtureProvenanceContract(FixtureProvenanceError):
    code = "FIXTURE_PROVENANCE_CONTRACT_UNSUPPORTED"


def detect_eol_shape(raw: bytes) -> EolShape:
    """Classify byte-level newline forms without decoding or guessing file type."""

    forms: list[EolShape] = []
    if b"\r\n" in raw:
        forms.append("CRLF")
    without_crlf = raw.replace(b"\r\n", b"")
    if b"\r" in without_crlf:
        forms.append("CR")
    if b"\n" in without_crlf:
        forms.append("LF")
    if not forms:
        return "NONE"
    if len(forms) == 1:
        return forms[0]
    return "MIXED"


def canonicalize_fixture_bytes(
    raw: bytes,
    contract: FixtureProvenanceContract | str,
) -> bytes:
    """Return bytes owned by an explicit provenance contract.

    CANONICAL_TEXT_LF_V1 strictly decodes UTF-8, replaces CRLF and lone CR with
    LF, preserves every other code point and byte-significant whitespace, and
    never adds or removes a final newline. RAW_BYTES_V1 returns the input bytes
    unchanged. The caller must select the contract explicitly; extensions and
    operating-system names are deliberately ignored.
    """

    if contract == RAW_BYTES_V1:
        return raw
    if contract != CANONICAL_TEXT_LF_V1:
        raise UnsupportedFixtureProvenanceContract(
            "fixture provenance contract is not supported",
        )
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CanonicalTextProvenanceDecodeError(
            "canonical text fixture is not valid UTF-8",
        ) from exc
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def observe_fixture_provenance(
    raw: bytes,
    contract: FixtureProvenanceContract | str,
) -> dict[str, object]:
    """Build a hash/count-only raw diagnostic plus canonical identity inputs."""

    canonical = canonicalize_fixture_bytes(raw, contract)
    return {
        "fixture_provenance_contract": contract,
        "raw_worktree_sha256": hashlib.sha256(raw).hexdigest(),
        "canonical_fixture_sha256": hashlib.sha256(canonical).hexdigest(),
        "raw_byte_length": len(raw),
        "canonical_byte_length": len(canonical),
        "observed_eol_shape": detect_eol_shape(raw),
        "canonicalization_applied": canonical != raw,
    }
