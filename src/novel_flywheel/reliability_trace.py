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
