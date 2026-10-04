"""Durable authority binding for generated-root semantic receipt recovery.

This module contains only deterministic identity and reconciliation rules. It
never chooses a provider route or performs I/O. Callers may persist the
returned payload alongside a pending receipt and must reconcile it again before
dispatch or promotion.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping


SCHEMA = "GeneratedRootRecoveryAuthorityV1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ROOT_RE = re.compile(r"^segment-([0-9]{2})$")
_CHILD_RE = re.compile(r"^segment-([0-9]{2})/sub-([0-9]+)$")
_WINDOW_RE = re.compile(r"^segment-([0-9]{2})-receipt-window-([0-9]+)$")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: object) -> str:
    return _sha256(_canonical(value))


def _digest(value: object, label: str, *, allow_empty: bool = False) -> str:
    text = str(value or "")
    if allow_empty and not text:
        return ""
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _sequence(values: Iterable[object], label: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item:
            raise ValueError(f"{label} cannot contain empty values")
        if item not in result:
            result.append(item)
    return tuple(result)


def normalize_generated_root_task_id(task_id: str) -> str:
    """Return the root segment identity for a root, child, or receipt-window task."""

    value = str(task_id or "").strip()
    match = _ROOT_RE.fullmatch(value) or _CHILD_RE.fullmatch(value) or _WINDOW_RE.fullmatch(value)
    if match is None:
        raise ValueError("task_id is outside the generated-root recovery namespace")
    segment = int(match.group(1))
    if segment <= 0:
        raise ValueError("task_id segment must be positive")
    return f"segment-{segment:02d}"


def _output_path(value: str) -> str:
    text = str(value or "").replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or not text.startswith("outputs/"):
        raise ValueError("candidate_relative_path must stay under outputs/")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("candidate_relative_path contains an unsafe component")
    if path.suffix.casefold() != ".md":
        raise ValueError("candidate_relative_path must identify a Markdown artifact")
    return path.as_posix()


def _dispatch_identity_required(state: str) -> bool:
    return state in {
        "claimed", "dispatching", "provider_returned", "deterministic_failure",
        "transient_failure", "qualified", "local_not_dispatched",
    }


@dataclass(frozen=True)
class GeneratedRootRecoveryAuthority:
    run_id: str
    project_id: str
    observed_task_id: str
    root_task_id: str
    task_scope_kind: str
    candidate_relative_path: str
    candidate_prose_sha256: str
    candidate_raw_sha256: str
    source_prose_sha256: str
    contract_authority_sha256: str
    execution_manifest_sha256: str
    repair_scope_task_id: str
    event_ids: tuple[str, ...]
    beat_ids: tuple[str, ...]
    scope_sha256: str
    checkpoint_input_sha256: str
    route_identity_sha256: str
    request_condition_sha256: str
    state: str
    authority_sha256: str
    schema: str = SCHEMA
    version: int = 1

    def payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "run_id": self.run_id,
            "project_id": self.project_id,
            "observed_task_id": self.observed_task_id,
            "root_task_id": self.root_task_id,
            "task_scope_kind": self.task_scope_kind,
            "candidate_relative_path": self.candidate_relative_path,
            "candidate_prose_sha256": self.candidate_prose_sha256,
            "candidate_raw_sha256": self.candidate_raw_sha256,
            "source_prose_sha256": self.source_prose_sha256,
            "contract_authority_sha256": self.contract_authority_sha256,
            "execution_manifest_sha256": self.execution_manifest_sha256,
            "repair_scope_task_id": self.repair_scope_task_id,
            "event_ids": list(self.event_ids),
            "beat_ids": list(self.beat_ids),
            "scope_sha256": self.scope_sha256,
            "checkpoint_input_sha256": self.checkpoint_input_sha256,
            "route_identity_sha256": self.route_identity_sha256,
            "request_condition_sha256": self.request_condition_sha256,
            "state": self.state,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "authority_sha256": self.authority_sha256}


def build_generated_root_authority(
    *,
    run_id: str,
    project_id: str,
    task_id: str,
    candidate_relative_path: str,
    candidate_prose_sha256: str,
    candidate_raw_sha256: str,
    contract: Mapping[str, Any],
    repair_scope_task_id: str,
    source_prose_sha256: str = "",
    checkpoint_input_sha256: str = "",
    route_identity_sha256: str = "",
    request_condition_sha256: str = "",
    state: str = "prepared",
) -> GeneratedRootRecoveryAuthority:
    """Build a hash-bound authority record without performing dispatch."""

    observed_task_id = str(task_id or "").strip()
    root_task_id = normalize_generated_root_task_id(observed_task_id)
    if not str(run_id).strip() or not str(project_id).strip():
        raise ValueError("run_id and project_id are required")
    path = _output_path(candidate_relative_path)
    prose_sha256 = _digest(candidate_prose_sha256, "candidate_prose_sha256")
    raw_sha256 = _digest(candidate_raw_sha256, "candidate_raw_sha256")
    source_sha256 = _digest(source_prose_sha256, "source_prose_sha256", allow_empty=True)
    contract_authority = _digest(
        contract.get("authority_sha256"), "contract.authority_sha256",
    )
    manifest_sha256 = _digest(
        contract.get("execution_manifest_sha256"),
        "contract.execution_manifest_sha256", allow_empty=True,
    )
    checkpoint_input = _digest(
        checkpoint_input_sha256, "checkpoint_input_sha256", allow_empty=True,
    )
    route_identity = _digest(
        route_identity_sha256, "route_identity_sha256", allow_empty=True,
    )
    request_condition = _digest(
        request_condition_sha256, "request_condition_sha256", allow_empty=True,
    )
    state_value = str(state or "").strip()
    if not state_value:
        raise ValueError("state is required")
    if _dispatch_identity_required(state_value) and not (route_identity and request_condition):
        raise ValueError("dispatch states require route and request identities")
    repair_scope = str(repair_scope_task_id or "").strip()
    if not repair_scope:
        raise ValueError("repair_scope_task_id is required")
    event_ids = _sequence(contract.get("event_ids") or (), "event_ids")
    beat_ids = _sequence(contract.get("beat_ids") or (), "beat_ids")
    task_scope_kind = "root" if observed_task_id == root_task_id else (
        "child" if "/sub-" in observed_task_id else "receipt_window"
    )
    scope_payload = {
        "root_task_id": root_task_id,
        "observed_task_id": observed_task_id,
        "repair_scope_task_id": repair_scope,
        "event_ids": list(event_ids),
        "beat_ids": list(beat_ids),
        "contract_authority_sha256": contract_authority,
        "execution_manifest_sha256": manifest_sha256,
    }
    scope_sha256 = canonical_sha256(scope_payload)
    authority_payload = {
        "schema": SCHEMA,
        "version": 1,
        "run_id": str(run_id),
        "project_id": str(project_id),
        "observed_task_id": observed_task_id,
        "root_task_id": root_task_id,
        "task_scope_kind": task_scope_kind,
        "candidate_relative_path": path,
        "candidate_prose_sha256": prose_sha256,
        "candidate_raw_sha256": raw_sha256,
        "source_prose_sha256": source_sha256,
        "contract_authority_sha256": contract_authority,
        "execution_manifest_sha256": manifest_sha256,
        "repair_scope_task_id": repair_scope,
        "event_ids": list(event_ids),
        "beat_ids": list(beat_ids),
        "scope_sha256": scope_sha256,
        "checkpoint_input_sha256": checkpoint_input,
        "route_identity_sha256": route_identity,
        "request_condition_sha256": request_condition,
        "state": state_value,
    }
    return GeneratedRootRecoveryAuthority(
        run_id=str(run_id), project_id=str(project_id), observed_task_id=observed_task_id,
        root_task_id=root_task_id, task_scope_kind=task_scope_kind,
        candidate_relative_path=path, candidate_prose_sha256=prose_sha256,
        candidate_raw_sha256=raw_sha256, source_prose_sha256=source_sha256,
        contract_authority_sha256=contract_authority,
        execution_manifest_sha256=manifest_sha256, repair_scope_task_id=repair_scope,
        event_ids=event_ids, beat_ids=beat_ids, scope_sha256=scope_sha256,
        checkpoint_input_sha256=checkpoint_input, route_identity_sha256=route_identity,
        request_condition_sha256=request_condition, state=state_value,
        authority_sha256=canonical_sha256(authority_payload),
    )


def _authority_from_mapping(value: Mapping[str, Any]) -> GeneratedRootRecoveryAuthority:
    payload = dict(value)
    if payload.get("schema") != SCHEMA or payload.get("version") != 1:
        raise ValueError("unsupported generated-root authority schema")
    authority_sha256 = _digest(payload.pop("authority_sha256", ""), "authority_sha256")
    observed_task_id = str(payload.get("observed_task_id") or payload.get("root_task_id") or "")
    expected_root_task_id = normalize_generated_root_task_id(observed_task_id)
    if payload.get("root_task_id") != expected_root_task_id:
        raise ValueError("root_task_id does not match observed_task_id")
    expected_scope_kind = (
        "root" if observed_task_id == expected_root_task_id
        else "child" if "/sub-" in observed_task_id else "receipt_window"
    )
    if payload.get("task_scope_kind") != expected_scope_kind:
        raise ValueError("task_scope_kind does not match observed_task_id")
    built = build_generated_root_authority(
        run_id=str(payload.get("run_id") or ""), project_id=str(payload.get("project_id") or ""),
        task_id=observed_task_id,
        candidate_relative_path=str(payload.get("candidate_relative_path") or ""),
        candidate_prose_sha256=str(payload.get("candidate_prose_sha256") or ""),
        candidate_raw_sha256=str(payload.get("candidate_raw_sha256") or ""),
        source_prose_sha256=str(payload.get("source_prose_sha256") or ""),
        checkpoint_input_sha256=str(payload.get("checkpoint_input_sha256") or ""),
        route_identity_sha256=str(payload.get("route_identity_sha256") or ""),
        request_condition_sha256=str(payload.get("request_condition_sha256") or ""),
        contract={
            "authority_sha256": payload.get("contract_authority_sha256"),
            "execution_manifest_sha256": payload.get("execution_manifest_sha256") or "",
            "event_ids": payload.get("event_ids") or (),
            "beat_ids": payload.get("beat_ids") or (),
        },
        repair_scope_task_id=str(payload.get("repair_scope_task_id") or ""),
        state=str(payload.get("state") or ""),
    )
    if built.authority_sha256 != authority_sha256:
        raise ValueError("authority_sha256 does not match canonical payload")
    return built


@dataclass(frozen=True)
class AuthorityReconciliation:
    ok: bool
    dispatch_ready: bool
    issues: tuple[str, ...]
    candidate_event_ids: tuple[str, ...]
    exhaustion_event_ids: tuple[str, ...]
    matching_checkpoint_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "dispatch_ready": self.dispatch_ready,
            "issues": list(self.issues),
            "candidate_event_ids": list(self.candidate_event_ids),
            "exhaustion_event_ids": list(self.exhaustion_event_ids),
            "matching_checkpoint_count": self.matching_checkpoint_count,
        }


def reconcile_generated_root_authority(
    authority: GeneratedRootRecoveryAuthority | Mapping[str, Any],
    *,
    filesystem_candidate_prose_sha256: str,
    events: Iterable[Mapping[str, Any]],
    checkpoints: Iterable[Mapping[str, Any]],
    require_event_pair: bool = True,
    require_dispatch_identity: bool = True,
) -> AuthorityReconciliation:
    """Reconcile durable events/checkpoints before any dispatch or promotion."""

    issues: list[str] = []
    try:
        bound = authority if isinstance(authority, GeneratedRootRecoveryAuthority) else _authority_from_mapping(authority)
    except (TypeError, ValueError) as exc:
        return AuthorityReconciliation(False, False, (str(exc),), (), (), 0)
    try:
        filesystem_hash = _digest(
            filesystem_candidate_prose_sha256, "filesystem_candidate_prose_sha256",
        )
    except ValueError as exc:
        return AuthorityReconciliation(False, False, (str(exc),), (), (), 0)
    if filesystem_hash != bound.candidate_prose_sha256:
        issues.append("candidate_filesystem_hash_mismatch")
    candidate_event_ids: list[str] = []
    exhaustion_event_ids: list[str] = []
    for event in events:
        metadata = event.get("metadata") if isinstance(event.get("metadata"), Mapping) else event
        event_type = str(event.get("event_type") or metadata.get("event_type") or "")
        try:
            root_task = normalize_generated_root_task_id(str(metadata.get("task_id") or ""))
        except ValueError:
            continue
        event_hash = str(
            metadata.get("candidate_prose_sha256")
            or metadata.get("prose_sha256")
            or ""
        )
        event_path = str(metadata.get("candidate_relative_path") or "").replace("\\", "/")
        if root_task != bound.root_task_id or event_hash != bound.candidate_prose_sha256:
            continue
        if event_path and event_path != bound.candidate_relative_path:
            continue
        event_id = str(event.get("id") or event.get("event_id") or "")
        if "candidate_generated" in event_type or "candidate" in event_type and "exhausted" not in event_type:
            candidate_event_ids.append(event_id)
        if "exhausted" in event_type:
            exhaustion_event_ids.append(event_id)
    if require_event_pair:
        if not candidate_event_ids:
            issues.append("missing_root_candidate_event")
        if not exhaustion_event_ids:
            issues.append("missing_root_exhaustion_event")
    matching_checkpoints: list[Mapping[str, Any]] = []
    for checkpoint in checkpoints:
        output_hash = str(checkpoint.get("output_sha256") or "")
        if output_hash == bound.candidate_prose_sha256:
            matching_checkpoints.append(checkpoint)
    if not matching_checkpoints:
        issues.append("missing_candidate_checkpoint")
    elif bound.checkpoint_input_sha256:
        matching_checkpoints = [
            row for row in matching_checkpoints
            if str(row.get("input_sha256") or "") == bound.checkpoint_input_sha256
        ]
        if not matching_checkpoints:
            issues.append("checkpoint_input_hash_mismatch")
    elif len(matching_checkpoints) > 1:
        issues.append("duplicate_checkpoint_identity")
    dispatch_ready = bool(
        bound.route_identity_sha256 and bound.request_condition_sha256
    )
    if require_dispatch_identity and not dispatch_ready:
        issues.append("dispatch_route_or_request_identity_missing")
    return AuthorityReconciliation(
        ok=not issues,
        dispatch_ready=dispatch_ready and not issues,
        issues=tuple(dict.fromkeys(issues)),
        candidate_event_ids=tuple(dict.fromkeys(candidate_event_ids)),
        exhaustion_event_ids=tuple(dict.fromkeys(exhaustion_event_ids)),
        matching_checkpoint_count=len(matching_checkpoints),
    )
