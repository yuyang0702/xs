"""Small, fail-open diagnostics for the reference-analysis boundary.

The normal reliability trace stays hash-only.  When the explicitly enabled
private capture flag is present, the same attempt identity also gets a 0600
local replay record containing only the final visible candidate/tool input (no
reasoning, prompts, headers, credentials, or unrelated source material).
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from novel_flywheel.reliability_trace import emit_observation


CAPTURE_FLAG = "NOVEL_REFERENCE_ANALYSIS_CAPTURE_V1"
TRACE_FLAG = "NOVEL_REFERENCE_ANALYSIS_TRACE_V1"
_UTF8 = "utf-8"


def _sha(value: Any) -> str:
    if isinstance(value, bytes):
        raw = value
    else:
        raw = json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str,
        ).encode(_UTF8)
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ReferenceAnalysisDiagnosticContextV1:
    project_root: Path
    source_id: str
    source_version_id: str
    source_content_sha256: str
    task_id: str
    run_id: str
    role: str = "reference_synthesis"
    lane: str = "primary"
    attempt: int = 1
    request_id_sha256: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    model_name: str | None = None
    endpoint: str | None = None
    route_fingerprint: str | None = None
    contract_name: str = "reference_distillation_region"
    contract_version: int = 2
    schema_sha256: str = ""
    source_code_version: str = "working-tree"

    def for_attempt(self, *, lane: str, attempt: int, receipt: Mapping[str, Any] | None = None) -> "ReferenceAnalysisDiagnosticContextV1":
        receipt = receipt or {}
        provider_id = str(receipt.get("provider_id") or self.provider_id or "") or None
        model_id = str(receipt.get("model_id") or self.model_id or "") or None
        model_name = str(receipt.get("model_name") or self.model_name or "") or None
        request_id = str(receipt.get("request_id") or "")
        endpoint = None
        if provider_id:
            try:
                providers = getattr(self, "_providers", None)
                if providers:
                    endpoint = providers.get(provider_id)
            except Exception:
                endpoint = None
        return replace(
            self, lane=lane, attempt=max(1, int(attempt)),
            request_id_sha256=_sha(request_id) if request_id else self.request_id_sha256,
            provider_id=provider_id, model_id=model_id, model_name=model_name,
            endpoint=endpoint or self.endpoint,
            route_fingerprint=str(receipt.get("route_fingerprint") or self.route_fingerprint or "") or None,
        )


_active: contextvars.ContextVar[ReferenceAnalysisDiagnosticContextV1 | None] = (
    contextvars.ContextVar("reference_analysis_diagnostic_context", default=None)
)
_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "reference_analysis_task_id", default=None,
)


def bind_task_id(task_id: str) -> contextvars.Token[str | None]:
    return _task_id.set(str(task_id))


def reset_task_id(token: contextvars.Token[str | None]) -> None:
    _task_id.reset(token)


def active_task_id() -> str | None:
    return _task_id.get()


def bind_context(context: ReferenceAnalysisDiagnosticContextV1) -> contextvars.Token[ReferenceAnalysisDiagnosticContextV1 | None]:
    return _active.set(context)


def reset_context(token: contextvars.Token[ReferenceAnalysisDiagnosticContextV1 | None]) -> None:
    _active.reset(token)


def active_context() -> ReferenceAnalysisDiagnosticContextV1 | None:
    return _active.get()


def _trace_root(context: ReferenceAnalysisDiagnosticContextV1) -> Path:
    # Keep private captures beside the daily data root, never in the repo.
    root = context.project_root.resolve() / "runtime" / "reference-analysis-captures"
    return root / hashlib.sha256(context.source_id.encode(_UTF8)).hexdigest()[:24]


def _private_capture_enabled() -> bool:
    return os.environ.get(CAPTURE_FLAG, "0") == "1"


def observe_stage(
    context: ReferenceAnalysisDiagnosticContextV1 | None,
    *, stage: str, status: str, rule_code: str | None = None,
    field_path: str | None = None, child_ids: tuple[str, ...] = (),
    candidate_sha256: str | None = None, normalized_sha256: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> bool:
    """Emit a safe stage record; diagnostic failure never affects business state."""
    if context is None or os.environ.get(TRACE_FLAG, "1") == "0":
        return False
    payload = {
        "schema": "ReferenceAnalysisBoundaryDiagnosticV1",
        "version": 1,
        "source_id_sha256": _sha(context.source_id),
        "source_version_id_sha256": _sha(context.source_version_id),
        "source_content_sha256": context.source_content_sha256,
        "analysis_task_id_sha256": _sha(context.task_id),
        "run_id_sha256": _sha(context.run_id),
        "logical_operation": "model_analysis",
        "attempt": context.attempt,
        "role": context.role,
        "lane": context.lane,
        "provider_id": context.provider_id,
        "model_id": context.model_id,
        "model_name": context.model_name,
        "endpoint": context.endpoint,
        "route_fingerprint": context.route_fingerprint,
        "contract_name": context.contract_name,
        "contract_version": context.contract_version,
        "schema_sha256": context.schema_sha256,
        "source_code_version": context.source_code_version,
        "stage": stage,
        "status": status,
        "rule_code": rule_code,
        "field_path": field_path,
        "child_ids": list(child_ids[:8]),
        "candidate_sha256": candidate_sha256,
        "normalized_sha256": normalized_sha256,
        "details": dict(details or {}),
    }
    try:
        return emit_observation(
            context.project_root,
            event_type="diagnostic_reference_analysis_boundary_v1",
            source_component="reference_analysis",
            source_writer="ReferenceAnalysisBoundaryObserverV1",
            observation_status="confirmed",
            correlation_id=context.task_id + ":" + str(context.attempt),
            stage_id=stage,
            semantic_domain="unknown",
            payload=payload,
        )
    except Exception:
        return False


def capture_candidate(
    context: ReferenceAnalysisDiagnosticContextV1 | None, *,
    phase: str, visible_text: str, receipt: Mapping[str, Any] | None = None,
    parsed_object: Any = None,
) -> tuple[str, str | None]:
    """Record hashes always; optionally write a private exact replay payload."""
    if context is None:
        return _sha(visible_text), None
    candidate_sha = _sha(visible_text)
    normalized_sha = _sha(parsed_object) if parsed_object is not None else None
    if not _private_capture_enabled():
        return candidate_sha, normalized_sha
    try:
        root = _trace_root(context)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{context.task_id}-{context.attempt:03d}-{context.lane}-{phase}.json"
        data: dict[str, Any] = {
            "schema": "ReferenceAnalysisPrivateReplayV1",
            "version": 1,
            "source_version_id_sha256": _sha(context.source_version_id),
            "analysis_task_id_sha256": _sha(context.task_id),
            "attempt": context.attempt,
            "lane": context.lane,
            "phase": phase,
            "visible_text": visible_text,
            "candidate_sha256": candidate_sha,
            "normalized_sha256": normalized_sha,
            "parsed_object": parsed_object,
            "receipt": {
                key: value for key, value in dict(receipt or {}).items()
                if key not in {"request_id", "raw_finish_reason", "authorization", "api_key"}
            },
        }
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(_UTF8)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, encoded)
        finally:
            os.close(fd)
        return candidate_sha, normalized_sha
    except Exception:
        return candidate_sha, normalized_sha


__all__ = [
    "CAPTURE_FLAG", "TRACE_FLAG", "ReferenceAnalysisDiagnosticContextV1",
    "active_context", "active_task_id", "bind_context", "bind_task_id",
    "capture_candidate", "observe_stage", "reset_context", "reset_task_id",
]
