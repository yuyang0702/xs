from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from novel_flywheel.storage import atomic_write


CHECKPOINT_VERSION = 1
HISTORICAL_BEST = re.compile(r"^historical-best-(\d+(?:\.\d+)?)\.md$")


def load_quality_checkpoint(run_path: Path) -> dict | None:
    checkpoint_path = run_path / "outputs" / "quality-checkpoint.json"
    try:
        value = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("version") != CHECKPOINT_VERSION:
        return None
    manuscript = _manuscript_path(run_path, value.get("manuscript_path"))
    if manuscript is None:
        return None
    try:
        digest = _hash(manuscript.read_text(encoding="utf-8"))
    except OSError:
        return None
    if digest != value.get("manuscript_hash"):
        return None
    score = value.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return value


def write_quality_checkpoint(run_path: Path, checkpoint: dict) -> None:
    value = dict(checkpoint)
    value["version"] = CHECKPOINT_VERSION
    manuscript = _manuscript_path(run_path, value.get("manuscript_path"))
    if manuscript is None:
        raise ValueError("Quality checkpoint manuscript is outside the run directory")
    try:
        digest = _hash(manuscript.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError("Quality checkpoint manuscript does not exist") from exc
    if digest != value.get("manuscript_hash"):
        raise ValueError("Quality checkpoint manuscript hash is stale")
    atomic_write(
        run_path / "outputs" / "quality-checkpoint.json",
        json.dumps(value, ensure_ascii=False, indent=2),
    )


def reconcile_legacy_checkpoint(run_path: Path) -> dict | None:
    outputs = run_path / "outputs"
    candidates: list[tuple[float, int, dict]] = []
    existing = load_quality_checkpoint(run_path)
    if existing:
        return existing

    report = _read_json(outputs / "quality-report.json")
    best_path = outputs / "best-candidate.md"
    score = report.get("best_score") if isinstance(report, dict) else None
    if (_valid_score(score) and best_path.is_file()
            and (text := best_path.read_text(encoding="utf-8")).strip()):
        attempt = report.get("best_attempt")
        review = _matching_review(report, attempt, float(score))
        candidates.append((float(score), 2, {
            "version": CHECKPOINT_VERSION,
            "manuscript_path": "outputs/best-candidate.md",
            "manuscript_hash": _hash(text),
            "score": float(score),
            "scoring_profile_id": str(
                (review or {}).get("scoring_profile_id")
                or report.get("scoring_profile_id")
                or "legacy-v1"
            ),
            "judge_signature": _judge_signature(review, report),
            "best_attempt": attempt if isinstance(attempt, int) else None,
            "review": review,
            "outcome": report.get("status"),
            "terminal_reviewed_hash": report.get("terminal_reviewed_hash"),
        }))

    if outputs.is_dir():
        for path in outputs.iterdir():
            match = HISTORICAL_BEST.fullmatch(path.name)
            if not match or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                continue
            historical_score = float(match.group(1))
            candidates.append((historical_score, 1, {
                "version": CHECKPOINT_VERSION,
                "manuscript_path": f"outputs/{path.name}",
                "manuscript_hash": _hash(text),
                "score": historical_score,
                "scoring_profile_id": "legacy-v1",
                "judge_signature": "legacy-unknown",
                "best_attempt": None,
                "review": None,
                "outcome": "legacy_protected",
                "terminal_reviewed_hash": None,
            }))

    if not candidates:
        return None
    selected = max(candidates, key=lambda item: (item[0], item[1]))[2]
    if selected != existing:
        write_quality_checkpoint(run_path, selected)
    return selected


def checkpoint_manuscript(run_path: Path, checkpoint: dict) -> str:
    path = _manuscript_path(run_path, checkpoint.get("manuscript_path"))
    if path is None:
        raise ValueError("Quality checkpoint manuscript is invalid")
    return path.read_text(encoding="utf-8")


def _matching_review(report: dict, attempt: Any, score: float) -> dict | None:
    attempts = report.get("final_attempts", [])
    if not isinstance(attempts, list):
        return None
    for item in attempts:
        if not isinstance(item, dict) or not isinstance(item.get("review"), dict):
            continue
        review = item["review"]
        if ((isinstance(attempt, int) and item.get("attempt") == attempt)
                or review.get("score") == score):
            return review
    return None


def _judge_signature(review: dict | None, report: dict) -> str:
    if review and review.get("judge_signature"):
        return str(review["judge_signature"])
    receipt = None
    if review and isinstance(review.get("receipt"), dict):
        receipt = review["receipt"]
    evidence = report.get("final_review_evidence")
    if receipt is None and isinstance(evidence, dict):
        receipt = evidence.get("adjudication_receipt")
    if isinstance(receipt, dict):
        provider = receipt.get("provider_id") or "unknown-provider"
        model = receipt.get("model_id") or receipt.get("model_name") or "unknown-model"
        return f"{provider}/{model}"
    return "legacy-unknown"


def _manuscript_path(run_path: Path, relative: Any) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    root = run_path.resolve()
    path = (run_path / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


def _valid_score(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
