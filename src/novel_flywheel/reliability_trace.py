"""Physically isolated, fail-open Phase 0 reliability observations."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from novel_flywheel.generated_artifacts import ReliabilityTraceEnvelopeV1


CANONICALIZATION_VERSION = "phase0-canonical-json-v1"
TRACE_BASENAME = "_reliability-trace-v1.jsonl"
TRACE_DIRECTORY = "reliability-traces"
UTF8 = "utf-8"
TRACE_EVENT_TYPES = (
    "authority_read",
    "proposed_claim",
    "promotion_write",
    "projection_read",
    "repair_diff",
    "recovery_attempt",
    "resume_binding",
    "authority_evidence_conflict",
)
DIAGNOSTIC_TRACE_EVENT_TYPES = (
    "diagnostic_strict_tool_shape",
    "diagnostic_output_budget_lineage",
)
VOLATILE_KEYS = frozenset({
    "created_at", "updated_at", "timestamp", "started_at", "finished_at",
    "event_id", "correlation_id", "run_id", "candidate_id", "trace_id",
})
FORBIDDEN_TRACE_KEYS = frozenset({
    "prompt", "system_prompt", "user_prompt", "prose", "text", "content",
    "excerpt", "raw", "credential", "credentials", "secret", "api_key",
    "authorization", "absolute_path", "error_text", "exception_text",
})
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


def trace_root_for_project(project_root: Path) -> Path:
    """Return a sibling of ``projects``; never a descendant of a project."""
    resolved = project_root.resolve()
    data_root = resolved.parent.parent
    identity = hashlib.sha256(resolved.name.encode(UTF8)).hexdigest()[:24]
    result = data_root / "runtime" / TRACE_DIRECTORY / identity
    if result.resolve().is_relative_to(resolved):
        raise ValueError("reliability trace storage must be outside the project")
    return result


def trace_file_for_project(project_root: Path) -> Path:
    return trace_root_for_project(project_root) / TRACE_BASENAME


def _normalize_path_text(value: str, root: Path | None) -> str:
    normalized = value.replace("\\", "/")
    if root is not None:
        root_text = str(root.resolve()).replace("\\", "/").rstrip("/")
        if normalized.casefold().startswith(root_text.casefold() + "/"):
            return "<ROOT>/" + normalized[len(root_text) + 1 :]
    if _WINDOWS_ABSOLUTE.match(normalized) or normalized.startswith("/"):
        return "<ABS>/" + normalized.rstrip("/").rsplit("/", 1)[-1]
    return normalized


def canonicalize(
    value: Any,
    *,
    root: Path | None = None,
    exclude_keys: frozenset[str] = VOLATILE_KEYS,
    field_name: str | None = None,
) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str) and field_name and (
            field_name == "path" or field_name.endswith("_path")
        ):
            return _normalize_path_text(value, root)
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite numbers are not canonical JSON")
        return value
    if isinstance(value, Path):
        return _normalize_path_text(str(value), root)
    if isinstance(value, dict):
        return {
            str(key): canonicalize(
                item, root=root, exclude_keys=exclude_keys, field_name=str(key),
            )
            for key, item in value.items()
            if str(key) not in exclude_keys
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize(item, root=root, exclude_keys=exclude_keys) for item in value]
    if hasattr(value, "model_dump"):
        return canonicalize(value.model_dump(mode="json"), root=root, exclude_keys=exclude_keys)
    raise TypeError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_bytes(value: Any, *, root: Path | None = None) -> bytes:
    return json.dumps(
        canonicalize(value, root=root), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode(UTF8)


def canonical_hash(value: Any, *, root: Path | None = None) -> str:
    return hashlib.sha256(canonical_bytes(value, root=root)).hexdigest()


def hash_observation(value: Any, *, root: Path | None = None) -> dict[str, str]:
    return {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "sha256": canonical_hash(value, root=root),
    }


def _validate_trace_privacy(value: Any, *, key: str | None = None) -> None:
    if key and key.casefold() in FORBIDDEN_TRACE_KEYS:
        raise ValueError(f"forbidden reliability trace field: {key}")
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            _validate_trace_privacy(child_value, key=str(child_key))
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_trace_privacy(item)
        return
    if isinstance(value, str) and (
        _WINDOWS_ABSOLUTE.match(value) or value.startswith("/")
    ):
        raise ValueError("absolute paths are forbidden in reliability traces")


class _InterprocessLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def acquire(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = self.path.open("a+b")
            self.handle.seek(0, os.SEEK_END)
            if self.handle.tell() == 0:
                self.handle.write(b"\0")
                self.handle.flush()
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, BlockingIOError):
            self.release()
            return False

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self.handle.close()
        except OSError:
            pass
        self.handle = None

    def __enter__(self) -> "_InterprocessLock":
        if not self.acquire():
            raise BlockingIOError("reliability trace lock unavailable")
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


@dataclass
class TraceSinkMetrics:
    attempted: int = 0
    written: int = 0
    dropped: int = 0
    bytes_written: int = 0

    @property
    def failure_rate(self) -> float:
        return self.dropped / self.attempted if self.attempted else 0.0


@dataclass
class TraceReadReport:
    events: list[ReliabilityTraceEnvelopeV1] = field(default_factory=list)
    coverage_gaps: list[dict[str, Any]] = field(default_factory=list)


class BestEffortTraceSink:
    """Append complete JSON records without participating in business state."""

    def __init__(self, path: Path, *, enabled: bool | None = None) -> None:
        self.path = path
        self.enabled = (
            os.environ.get("NOVEL_RELIABILITY_TRACE", "1") != "0"
            if enabled is None else enabled
        )
        self.metrics = TraceSinkMetrics()
        self._thread_lock = threading.Lock()

    @classmethod
    def for_project(
        cls, project_root: Path, *, enabled: bool | None = None,
    ) -> "BestEffortTraceSink":
        return cls(trace_file_for_project(project_root), enabled=enabled)

    def _next_sequence(self, correlation_id: str) -> int:
        maximum = 0
        if not self.path.is_file():
            return 1
        with self.path.open("rb") as handle:
            for raw_line in handle:
                try:
                    payload = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if payload.get("correlation_id") == correlation_id:
                    sequence = payload.get("sequence")
                    if isinstance(sequence, int):
                        maximum = max(maximum, sequence)
        return maximum + 1

    def emit(self, envelope: ReliabilityTraceEnvelopeV1) -> bool:
        self.metrics.attempted += 1
        if not self.enabled:
            return False
        lock = _InterprocessLock(self.path.with_suffix(self.path.suffix + ".lock"))
        try:
            _validate_trace_privacy(envelope.model_dump(mode="json", by_alias=True))
            with self._thread_lock:
                if not lock.acquire():
                    self.metrics.dropped += 1
                    return False
                try:
                    sequence = self._next_sequence(envelope.correlation_id)
                    record = envelope.model_copy(update={"sequence": sequence})
                    line = (
                        json.dumps(
                            record.model_dump(mode="json", by_alias=True), ensure_ascii=False,
                            sort_keys=True, separators=(",", ":"),
                        ) + "\n"
                    ).encode(UTF8)
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    descriptor = os.open(
                        self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                        0o600,
                    )
                    try:
                        start = os.lseek(descriptor, 0, os.SEEK_END)
                        written = os.write(descriptor, line)
                        if written != len(line):
                            os.ftruncate(descriptor, start)
                            raise OSError("partial reliability trace append")
                    finally:
                        os.close(descriptor)
                finally:
                    lock.release()
            self.metrics.written += 1
            self.metrics.bytes_written += len(line)
            return True
        except Exception:
            self.metrics.dropped += 1
            return False


def read_trace(path: Path) -> TraceReadReport:
    report = TraceReadReport()
    if not path.is_file():
        return report
    expected: dict[str, int] = {}
    try:
        raw_lines = path.read_bytes().splitlines(keepends=True)
    except OSError as exc:
        report.coverage_gaps.append({"line": None, "reason": type(exc).__name__})
        return report
    for line_number, raw_line in enumerate(raw_lines, start=1):
        if not raw_line.endswith(b"\n"):
            report.coverage_gaps.append({"line": line_number, "reason": "incomplete_tail"})
            continue
        try:
            event = ReliabilityTraceEnvelopeV1.model_validate_json(raw_line)
        except Exception as exc:
            report.coverage_gaps.append({
                "line": line_number, "reason": "invalid_record",
                "error_class": type(exc).__name__,
            })
            continue
        next_expected = expected.get(event.correlation_id, 1)
        if event.sequence != next_expected:
            report.coverage_gaps.append({
                "line": line_number, "reason": "sequence_gap",
                "correlation_id_hash": hashlib.sha256(
                    event.correlation_id.encode(UTF8)
                ).hexdigest(),
                "expected": next_expected, "actual": event.sequence,
            })
        expected[event.correlation_id] = event.sequence + 1
        report.events.append(event)
    return report


def new_event_id() -> str:
    return uuid.uuid4().hex


def safe_canonical_hash(value: Any, *, root: Path | None = None) -> str | None:
    try:
        return canonical_hash(value, root=root)
    except Exception:
        return None


def changed_paths(before: Any, after: Any, prefix: str = "$") -> list[str]:
    """Return changed JSON paths without retaining either value."""
    if hasattr(before, "model_dump"):
        before = before.model_dump(mode="json")
    if hasattr(after, "model_dump"):
        after = after.model_dump(mode="json")
    if isinstance(before, dict) and isinstance(after, dict):
        paths: list[str] = []
        for key in sorted(set(before) | set(after), key=str):
            child = f"{prefix}.{key}"
            if key not in before or key not in after:
                paths.append(child)
            else:
                paths.extend(changed_paths(before[key], after[key], child))
        return paths
    if isinstance(before, (list, tuple)) and isinstance(after, (list, tuple)):
        paths = []
        for index in range(max(len(before), len(after))):
            child = f"{prefix}[{index}]"
            if index >= len(before) or index >= len(after):
                paths.append(child)
            else:
                paths.extend(changed_paths(before[index], after[index], child))
        return paths
    return [] if before == after else [prefix]


def emit_observation(
    project_root: Path,
    *,
    event_type: str,
    source_component: str,
    source_writer: str,
    observation_status: str,
    payload: dict[str, Any],
    run_id: str | None = None,
    correlation_id: str | None = None,
    stage_id: str | None = None,
    semantic_domain: str = "unknown",
    authority_revision: int | None = None,
    authority_hash: str | None = None,
    object_old_hash: str | None = None,
    object_new_hash: str | None = None,
) -> bool:
    """Construct and append one observation; never raise into business code."""
    try:
        resolved_correlation = correlation_id or run_id
        if not resolved_correlation:
            resolved_correlation = "manual-" + hashlib.sha256(
                project_root.resolve().name.encode(UTF8)
            ).hexdigest()[:24]
        envelope = ReliabilityTraceEnvelopeV1.model_validate({
            "schema": "ReliabilityTraceEnvelopeV1",
            "event_id": new_event_id(),
            "correlation_id": resolved_correlation,
            "run_id": run_id,
            "stage_id": stage_id,
            "event_type": event_type,
            "source_component": source_component,
            "source_writer": source_writer,
            "semantic_domain": semantic_domain,
            "authority_revision": authority_revision,
            "authority_hash": authority_hash,
            "object_old_hash": object_old_hash,
            "object_new_hash": object_new_hash,
            "observation_status": observation_status,
            "payload": payload,
        })
        return BestEffortTraceSink.for_project(project_root).emit(envelope)
    except Exception:
        return False


def shadow_slot_identity(
    *,
    entity_hash: str,
    predicate: str,
    semantic_domain: str,
    perspective: str | None = None,
    knowledge_owner_hash: str | None = None,
    relationship_direction: str | None = None,
) -> str:
    """Derive shadow identity without using or replacing a legacy fact key."""
    return "slot-" + canonical_hash({
        "entity_hash": entity_hash,
        "predicate": predicate,
        "semantic_domain": semantic_domain,
        "perspective": perspective,
        "knowledge_owner_hash": knowledge_owner_hash,
        "relationship_direction": relationship_direction,
    })[:32]


def assess_authority_evidence_conflict(
    left: dict[str, Any], right: dict[str, Any],
) -> dict[str, Any]:
    """Confirm a conflict only when all user-required evidence is explicit."""
    required = ("shadow_slot", "story_time", "semantic_domain", "value_sha256", "source_hash")
    if any(not left.get(key) or not right.get(key) for key in required):
        return {"observation_status": "unknown", "conflict": False}
    comparable = (
        left["shadow_slot"] == right["shadow_slot"]
        and left["story_time"] == right["story_time"]
        and left["semantic_domain"] == right["semantic_domain"]
    )
    if not comparable:
        return {"observation_status": "unknown", "conflict": False}
    disagrees = left["value_sha256"] != right["value_sha256"]
    return {
        "observation_status": "confirmed",
        "conflict": disagrees,
        "semantic_domain": left["semantic_domain"],
        "payload": ({
            "shadow_slot": left["shadow_slot"],
            "story_time": left["story_time"],
            "left_source_hash": left["source_hash"],
            "right_source_hash": right["source_hash"],
            "values_disagree": True,
            "resolution": "unresolved_phase0",
        } if disagrees else None),
    }


def authority_lineage(events: Iterable[ReliabilityTraceEnvelopeV1]) -> list[dict[str, Any]]:
    selected = {
        "authority_read", "promotion_write", "proposed_claim",
        "authority_evidence_conflict",
    }
    return [
        {
            "correlation_id_hash": hashlib.sha256(
                item.correlation_id.encode(UTF8)
            ).hexdigest(),
            "sequence": item.sequence,
            "event_type": item.event_type,
            "stage_id": item.stage_id,
            "source_component": item.source_component,
            "source_writer": item.source_writer,
            "semantic_domain": item.semantic_domain,
            "authority_revision": item.authority_revision,
            "authority_hash": item.authority_hash,
            "object_old_hash": item.object_old_hash,
            "object_new_hash": item.object_new_hash,
            "observation_status": item.observation_status,
        }
        for item in events if item.event_type in selected
    ]


def projection_reconciliation(
    events: Iterable[ReliabilityTraceEnvelopeV1],
) -> list[dict[str, Any]]:
    return [
        {
            "sequence": item.sequence,
            "projection": item.payload.get("projection"),
            "requested_revision": item.payload.get("requested_revision"),
            "actual_revision": item.payload.get("actual_revision"),
            "revision_metadata_present": item.payload.get("revision_metadata_present"),
            "stale": item.payload.get("stale"),
            "observation_status": item.observation_status,
            "result_sha256": item.payload.get("result_sha256"),
            "source_authority_hash": item.payload.get("source_authority_hash"),
            "source_commit_id": item.payload.get("source_commit_id"),
            "projection_hash": item.payload.get("projection_hash")
            or item.payload.get("result_sha256"),
            "writer": item.payload.get("writer"),
            "source_artifact": item.payload.get("source_artifact"),
            "source_artifact_hash": item.payload.get("source_artifact_hash"),
            "provenance_schema": item.payload.get("provenance_schema"),
            "provenance_version": item.payload.get("provenance_version"),
            "projection_sources": list(item.payload.get("projection_sources") or []),
        }
        for item in events if item.event_type == "projection_read"
    ]


def projection_provenance_matrix(
    events: Iterable[ReliabilityTraceEnvelopeV1],
) -> list[dict[str, Any]]:
    """Return declared projection writes and reads without inferring lineage."""

    rows: list[dict[str, Any]] = []
    for item in events:
        projection = item.payload.get("projection")
        if item.event_type not in {"promotion_write", "projection_read"} or not projection:
            continue
        rows.append({
            "sequence": item.sequence,
            "event_type": item.event_type,
            "projection": projection,
            "requested_authority_revision": item.payload.get(
                "requested_authority_revision",
                item.payload.get("requested_revision"),
            ),
            "actual_source_revision": item.payload.get(
                "actual_source_revision",
                item.payload.get("actual_revision"),
            ),
            "source_authority_hash": item.payload.get("source_authority_hash")
            or item.authority_hash,
            "source_commit_id": item.payload.get("source_commit_id"),
            "projection_hash": item.payload.get("projection_hash")
            or item.payload.get("result_sha256")
            or item.object_new_hash,
            "writer": item.payload.get("writer") or item.source_writer,
            "source_artifact": item.payload.get("source_artifact"),
            "source_artifact_hash": item.payload.get("source_artifact_hash"),
            "provenance_schema": item.payload.get("provenance_schema"),
            "provenance_version": item.payload.get("provenance_version"),
            "freshness": item.payload.get("freshness")
            or item.payload.get("stale")
            or "unknown",
            "observation_status": item.observation_status,
        })
    return rows


def resolve_projection_provenance(
    project_root: Path,
    *,
    projections: Iterable[str],
    requested_authority_revision: int | None,
    requested_authority_hash: str | None,
) -> dict[str, Any]:
    """Resolve only explicit trace-backed projection writers.

    Missing legacy metadata remains unknown.  Multiple source revisions are
    reported losslessly and are never collapsed into a guessed aggregate.
    """

    required = list(dict.fromkeys(str(item) for item in projections if str(item)))
    report = read_trace(trace_file_for_project(project_root))
    latest: dict[str, ReliabilityTraceEnvelopeV1] = {}
    for item in report.events:
        projection = str(item.payload.get("projection") or "")
        if item.event_type == "promotion_write" and projection in required:
            latest[projection] = item
    sources = []
    for projection in required:
        item = latest.get(projection)
        if item is None:
            sources.append({
                "projection": projection,
                "actual_source_revision": None,
                "source_authority_hash": None,
                "source_commit_id": None,
                "projection_hash": None,
                "writer": None,
                "source_artifact": None,
                "source_artifact_hash": None,
                "provenance_schema": None,
                "provenance_version": None,
                "freshness": "unknown",
                "observation_status": "unknown",
            })
            continue
        revision = item.payload.get("actual_source_revision")
        authority_hash = item.payload.get("source_authority_hash") or item.authority_hash
        if revision is None or authority_hash is None:
            freshness = "unknown"
        elif (
            requested_authority_revision == revision
            and requested_authority_hash == authority_hash
        ):
            freshness = "fresh"
        else:
            freshness = "stale"
        sources.append({
            "projection": projection,
            "actual_source_revision": revision,
            "source_authority_hash": authority_hash,
            "source_commit_id": item.payload.get("source_commit_id"),
            "projection_hash": item.payload.get("projection_hash")
            or item.object_new_hash,
            "writer": item.payload.get("writer") or item.source_writer,
            "source_artifact": item.payload.get("source_artifact"),
            "source_artifact_hash": item.payload.get("source_artifact_hash"),
            "provenance_schema": item.payload.get("provenance_schema"),
            "provenance_version": item.payload.get("provenance_version"),
            "freshness": freshness,
            "observation_status": item.observation_status,
        })
    revisions = {
        item["actual_source_revision"] for item in sources
        if item["actual_source_revision"] is not None
    }
    hashes = {
        item["source_authority_hash"] for item in sources
        if item["source_authority_hash"] is not None
    }
    complete = bool(required) and len(sources) == len(required) and all(
        item["actual_source_revision"] is not None
        and item["source_authority_hash"] is not None
        and item["projection_hash"] is not None
        and item["source_artifact_hash"] is not None
        and item["source_commit_id"] is not None
        for item in sources
    )
    if complete and all(item["freshness"] == "fresh" for item in sources):
        freshness = "fresh"
    elif any(item["freshness"] == "stale" for item in sources):
        freshness = "stale"
    else:
        freshness = "unknown"
    return {
        "requested_authority_revision": requested_authority_revision,
        "requested_authority_hash": requested_authority_hash,
        "actual_source_revision": next(iter(revisions)) if len(revisions) == 1 else None,
        "source_authority_hash": next(iter(hashes)) if len(hashes) == 1 else None,
        "revision_metadata_present": complete,
        "freshness": freshness,
        "projection_sources": sources,
        "reader_coverage_gaps": list(report.coverage_gaps),
    }


def artifact_binding_matrix(
    events: Iterable[ReliabilityTraceEnvelopeV1],
) -> list[dict[str, Any]]:
    """Render exact and legacy artifact bindings from explicit observations."""

    rows: list[dict[str, Any]] = []
    for item in events:
        if item.event_type == "resume_binding":
            payload = item.payload
            rows.append({
                "sequence": item.sequence,
                "artifact_type": payload.get("artifact_type"),
                "binding_status": payload.get("binding_status"),
                "binding_lane": payload.get("binding_lane") or (
                    "legacy" if payload.get("binding_status") == "unverifiable_legacy"
                    else "exact_v2"
                ),
                "input_object_hash": payload.get("input_object_hash")
                or payload.get("expected_input_sha256"),
                "actual_input_object_hash": payload.get("actual_input_sha256")
                or payload.get("input_object_hash"),
                "output_object_hash": payload.get("output_object_hash")
                or item.object_new_hash,
                "reviewed_object_hash": payload.get("reviewed_object_hash"),
                "authority_revision": item.authority_revision,
                "authority_hash": item.authority_hash,
                "policy": payload.get("policy"),
                "policy_version": payload.get("policy_version"),
                "validator_set": list(payload.get("validator_set") or []),
                "parent_artifact": payload.get("parent_artifact"),
                "superseded_artifact": payload.get("superseded_artifact"),
                "observation_status": item.observation_status,
            })
        elif item.event_type == "repair_diff":
            rows.append({
                "sequence": item.sequence,
                "artifact_type": "repair_output",
                "binding_status": (
                    "exact" if item.object_old_hash and item.object_new_hash else "unknown"
                ),
                "binding_lane": (
                    "exact_v2" if item.object_old_hash and item.object_new_hash
                    else "unknown"
                ),
                "input_object_hash": item.object_old_hash,
                "actual_input_object_hash": item.object_old_hash,
                "output_object_hash": item.object_new_hash,
                "reviewed_object_hash": item.payload.get("reviewed_object_hash"),
                "authority_revision": item.authority_revision,
                "authority_hash": item.authority_hash,
                "policy": item.payload.get("allowed_scope_source"),
                "policy_version": item.payload.get("policy_version"),
                "validator_set": list(item.payload.get("validators_rerun") or []),
                "parent_artifact": item.object_old_hash,
                "superseded_artifact": item.object_old_hash,
                "observation_status": item.observation_status,
            })
        elif (
            item.event_type == "promotion_write"
            and item.payload.get("input_object_hash")
        ):
            payload = item.payload
            rows.append({
                "sequence": item.sequence,
                "artifact_type": payload.get("store"),
                "binding_status": "exact",
                "binding_lane": "exact_v2",
                "input_object_hash": payload.get("input_object_hash"),
                "actual_input_object_hash": payload.get("input_object_hash"),
                "output_object_hash": payload.get("output_object_hash")
                or item.object_new_hash,
                "reviewed_object_hash": payload.get("reviewed_object_hash"),
                "authority_revision": item.authority_revision,
                "authority_hash": item.authority_hash,
                "policy": payload.get("policy"),
                "policy_version": payload.get("policy_version"),
                "validator_set": list(payload.get("validator_set") or []),
                "parent_artifact": payload.get("parent_artifact"),
                "superseded_artifact": payload.get("superseded_artifact"),
                "observation_status": item.observation_status,
            })
    return rows


def canonical_shadow_comparison_matrix(
    events: Iterable[ReliabilityTraceEnvelopeV1],
) -> list[dict[str, Any]]:
    """Render hash-only Phase 1A claim and mutation evaluations."""

    rows = []
    for item in events:
        if (
            item.event_type != "proposed_claim"
            or item.source_component
            != "canonical_shadow.observe_maintenance_shadow"
        ):
            continue
        payload = item.payload
        rows.append({
            "sequence": item.sequence,
            "workflow": payload.get("workflow") or item.source_writer,
            "claim_kind": payload.get("claim_kind"),
            "claim_id": payload.get("claim_id"),
            "slot_id": payload.get("slot_id"),
            "competition_key": payload.get("competition_key"),
            "identity_status": payload.get("identity_status"),
            "grounding": payload.get("grounding"),
            "mutation_id": payload.get("mutation_id"),
            "operation": payload.get("operation"),
            "eligibility": payload.get("eligibility"),
            "authority_slice_hash": payload.get("authority_slice_hash"),
            "expected_current_hash": payload.get("expected_current_hash"),
            "receipt_hash": payload.get("receipt_hash"),
            "legacy_comparison": payload.get("legacy_comparison"),
            "claim_count": payload.get("claim_count"),
            "eligible_count": payload.get("eligible_count"),
            "evidence_gap_count": payload.get("evidence_gap_count"),
            "identity_ambiguous_count": payload.get(
                "identity_ambiguous_count"
            ),
            "commit_performed": payload.get("commit_performed"),
            "observation_status": item.observation_status,
        })
    return rows


def event_type_coverage_matrix(
    events: Iterable[ReliabilityTraceEnvelopeV1],
) -> dict[str, Any]:
    """Report normal and explicitly synthetic coverage for all eight events."""

    materialized = list(events)
    rows = []
    for event_type in TRACE_EVENT_TYPES:
        selected = [item for item in materialized if item.event_type == event_type]
        synthetic = sum(bool(item.payload.get("synthetic")) for item in selected)
        rows.append({
            "event_type": event_type,
            "observed": len(selected),
            "normal_observed": len(selected) - synthetic,
            "synthetic_observed": synthetic,
            "covered": bool(selected),
        })
    gaps = [row["event_type"] for row in rows if not row["covered"]]
    return {
        "rows": rows,
        "covered": len(rows) - len(gaps),
        "expected": len(rows),
        "coverage_ratio": (len(rows) - len(gaps)) / len(rows),
        "coverage_gaps": gaps,
    }


def repair_diff_view(events: Iterable[ReliabilityTraceEnvelopeV1]) -> list[dict[str, Any]]:
    return [
        {
            "sequence": item.sequence,
            "stage_id": item.stage_id,
            "old_sha256": item.object_old_hash,
            "new_sha256": item.object_new_hash,
            "changed_paths": list(item.payload.get("changed_paths") or []),
            "validators_rerun": list(item.payload.get("validators_rerun") or []),
            "unauthorized_change": item.payload.get("unauthorized_change"),
        }
        for item in events if item.event_type == "repair_diff"
    ]


def recovery_attempt_dag(events: Iterable[ReliabilityTraceEnvelopeV1]) -> dict[str, Any]:
    nodes = []
    edges = []
    for item in events:
        if item.event_type != "recovery_attempt":
            continue
        attempt_id = str(item.payload["attempt_id"])
        nodes.append({
            "attempt_id": attempt_id,
            "route": item.payload.get("route"),
            "action": item.payload["action"],
            "outcome": item.payload["outcome"],
            "model_call_delta": item.payload["model_call_delta"],
        })
        parent = item.payload.get("parent_attempt_id")
        if parent is not None:
            # Never infer an edge from sequence or a missing record.
            edges.append({"from": str(parent), "to": attempt_id, "explicit": True})
    return {"nodes": nodes, "edges": edges}


TRACE_COVERAGE_POINTS: dict[str, tuple[str, str]] = {
    "stage_authority_read": ("authority_read", "workflows.WorkflowService._stage"),
    "normal_maintenance_read": ("authority_read", "workflows._close_short_maintenance_authority"),
    "projection_read": ("projection_read", "long_workflow.run_chapter"),
    "repair_diff": ("repair_diff", "workflows._ensure_short_execution_manifest"),
    "runtime_attempt": ("recovery_attempt", "contract_runtime"),
    "resume_binding": ("resume_binding", "workflows._short_pipeline"),
    "saga_promotion": ("promotion_write", "project_transactions"),
    "manual_story_state": ("promotion_write", "api.projects.update_story_state"),
}


def trace_coverage_matrix(
    events: Iterable[ReliabilityTraceEnvelopeV1],
) -> dict[str, Any]:
    materialized = list(events)
    rows = []
    for point, (event_type, component) in TRACE_COVERAGE_POINTS.items():
        count = sum(
            item.event_type == event_type and item.source_component == component
            for item in materialized
        )
        rows.append({"trace_point": point, "observed": count, "covered": count > 0})
    gaps = [row["trace_point"] for row in rows if not row["covered"]]
    return {
        "rows": rows,
        "covered": len(rows) - len(gaps),
        "expected": len(rows),
        "coverage_ratio": (len(rows) - len(gaps)) / len(rows),
        "coverage_gaps": gaps,
    }
