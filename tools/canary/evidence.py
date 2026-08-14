"""Hash-only CanaryEvidencePackageV1 creation and validation."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    domain_sha256,
)


EVIDENCE_SCHEMA = "CanaryEvidencePackageV1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CanaryEvidenceError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _scan(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).casefold()
            if lowered in {
                "api_key", "credential", "secret", "raw_prompt", "prompt",
                "prose", "story_text", "absolute_path", "headers", "endpoint",
            }:
                raise CanaryEvidenceError("evidence_raw_or_secret_field")
            _scan(child)
    elif isinstance(value, list):
        for child in value:
            _scan(child)
    elif isinstance(value, str):
        if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("\\\\", "file://")):
            raise CanaryEvidenceError("evidence_absolute_path")


def build_canary_evidence_package_v1(payload: Mapping[str, Any]) -> dict:
    body = {
        "schema": EVIDENCE_SCHEMA,
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        **deepcopy(dict(payload)),
    }
    required = {
        "plan_sha256", "approval_sha256", "launcher_sha256", "outcome",
        "runtime_fingerprints", "origin_executor_binding", "preflight_receipts",
        "model_boundary_ledger", "budget_ledger", "counters", "live_parity",
        "canary_artifacts", "performance", "coverage_gaps",
        "raw_content_included",
    }
    if required.difference(body):
        raise CanaryEvidenceError("evidence_fields_missing")
    for field in ("plan_sha256", "approval_sha256", "launcher_sha256"):
        if not isinstance(body[field], str) or _HEX64.fullmatch(body[field]) is None:
            raise CanaryEvidenceError(f"evidence_{field}_invalid")
    if body["raw_content_included"] is not False:
        raise CanaryEvidenceError("evidence_raw_content_forbidden")
    _scan(body)
    package = {
        **body,
        "evidence_sha256": domain_sha256(
            "novel-flywheel-canary-evidence-v1", body,
        ),
    }
    return package
