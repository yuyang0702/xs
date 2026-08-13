"""Hash-only before/after harness for Phase 0 reliability instrumentation.

This module deliberately lives under ``tests``.  It can inspect an isolated or
read-only project tree, but production code cannot import it.  Its output never
contains manuscript or prompt text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CANONICALIZATION_VERSION = "phase0-canonical-json-v1"
TRACE_BASENAME = "_reliability-trace-v1.jsonl"
UTF8 = "utf-8"
VOLATILE_KEYS = frozenset({
    "created_at", "updated_at", "timestamp", "started_at", "finished_at",
    "event_id", "correlation_id", "run_id", "candidate_id", "trace_id",
})
EXCLUDED_DIRECTORY_NAMES = frozenset({
    ".git", ".pytest_cache", "__pycache__", "trash", "backups",
})
BUSINESS_SUFFIXES = frozenset({".json", ".md", ".txt"})
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


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
    """Return the JSON-compatible Phase 0 canonical representation.

    Rules are versioned above: UTF-8, sorted object keys at serialization,
    explicit null preservation, native JSON numbers/booleans, root-relative
    path fields, and removal of the declared volatile observation fields.
    """
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str) and field_name and (
            field_name == "path" or field_name.endswith("_path")
        ):
            return _normalize_path_text(value, root)
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
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
        canonicalize(value, root=root),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode(UTF8)


def canonical_hash(value: Any, *, root: Path | None = None) -> str:
    return hashlib.sha256(canonical_bytes(value, root=root)).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_business_artifact(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if path.name == TRACE_BASENAME:
        return False
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts):
        return False
    if "runs" in relative.parts and "outputs" not in relative.parts:
        return False
    return path.suffix.casefold() in BUSINESS_SUFFIXES


def artifact_manifest(root: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_file() and is_business_artifact(path, root):
            artifacts.append({
                "path": path.relative_to(root).as_posix(),
                "sha256": file_hash(path),
                "size": path.stat().st_size,
            })
    return artifacts


def story_state_manifest(database: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT project_id, revision, state_json FROM story_states ORDER BY project_id"
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "project_id_hash": hashlib.sha256(project_id.encode(UTF8)).hexdigest(),
            "revision": revision,
            "canonical_hash": canonical_hash(json.loads(state_json)),
        }
        for project_id, revision, state_json in rows
    ]


def model_call_manifest(calls: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for ordinal, call in enumerate(calls, start=1):
        system = str(call.get("system", ""))
        user = str(call.get("user", ""))
        result.append({
            "ordinal": ordinal,
            "role": call.get("role"),
            "route": call.get("route"),
            "system_sha256": hashlib.sha256(system.encode(UTF8)).hexdigest(),
            "user_sha256": hashlib.sha256(user.encode(UTF8)).hexdigest(),
            "input_tokens": call.get("input_tokens"),
            "output_tokens": call.get("output_tokens"),
            "max_output_tokens": call.get("max_output_tokens"),
        })
    return result


def capture(
    workspace: Path,
    *,
    database: Path | None = None,
    model_calls: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    artifacts = artifact_manifest(workspace)
    calls = model_call_manifest(model_calls)
    payload: dict[str, Any] = {
        "schema": "Phase0ParityBaselineV1",
        "canonicalization_version": CANONICALIZATION_VERSION,
        "artifacts": artifacts,
        "artifact_set_sha256": canonical_hash(artifacts),
        "model_calls": calls,
        "model_calls_sha256": canonical_hash(calls),
        "model_call_count": len(calls),
    }
    if database is not None:
        states = story_state_manifest(database)
        payload["story_states"] = states
        payload["story_states_sha256"] = canonical_hash(states)
    return payload


@dataclass(frozen=True)
class Comparison:
    equal: bool
    differences: tuple[str, ...]


def compare(before: dict[str, Any], after: dict[str, Any]) -> Comparison:
    keys = (
        "canonicalization_version", "artifacts", "artifact_set_sha256",
        "story_states", "story_states_sha256", "model_calls",
        "model_calls_sha256", "model_call_count",
    )
    differences = tuple(key for key in keys if before.get(key) != after.get(key))
    return Comparison(not differences, differences)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--workspace", type=Path, required=True)
    capture_parser.add_argument("--database", type=Path)
    capture_parser.add_argument("--model-calls", type=Path)
    capture_parser.add_argument("--output", type=Path, required=True)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--before", type=Path, required=True)
    compare_parser.add_argument("--after", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "capture":
        calls = []
        if args.model_calls:
            calls = json.loads(args.model_calls.read_text(encoding=UTF8))
        result = capture(args.workspace, database=args.database, model_calls=calls)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding=UTF8,
        )
        print(json.dumps({"ok": True, "output": str(args.output)}))
        return 0
    before = json.loads(args.before.read_text(encoding=UTF8))
    after = json.loads(args.after.read_text(encoding=UTF8))
    result = compare(before, after)
    print(json.dumps({"equal": result.equal, "differences": result.differences}))
    return 0 if result.equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
