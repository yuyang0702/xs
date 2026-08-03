from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_flywheel.storage import atomic_write


PLANNING_RECOVERY_VERSION = 1


def planning_issue_keys(issues: list[dict]) -> set[str]:
    """Return stable semantic identities independent of reviewer wording."""
    keys: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        code = str(issue.get("code") or "unknown").strip().lower()
        segment = _integer(issue.get("segment"))
        event_id = str(issue.get("event_id") or "").strip().upper()
        prefix = f"planning:segment-{segment:02d}" if segment else "planning:whole"
        if event_id:
            prefix += f":{event_id}"
        invalid_invariants = _string_values(issue.get("invalid_invariants"))
        invalid_dimensions = _string_values(issue.get("invalid_dimensions"))
        if invalid_invariants:
            keys.update(
                f"{prefix}:invariant:{value}" for value in invalid_invariants
            )
            continue
        if invalid_dimensions:
            keys.update(
                f"{prefix}:whole-invariant:{value}" for value in invalid_dimensions
            )
            continue
        if code == "planning_whole_story_drift":
            affected_segments = sorted({
                number for number in (
                    _integer(value) for value in issue.get("affected_segments", [])
                ) if number
            })
            affected_events = sorted({
                str(value or "").strip().upper()
                for value in issue.get("affected_event_ids", [])
                if str(value or "").strip()
            })
            scope = ",".join(map(str, affected_segments)) or "whole"
            events = ",".join(affected_events) or "all"
            keys.add(f"planning:whole:{code}:segments-{scope}:events-{events}")
            continue
        keys.add(f"{prefix}:{code}")
    return keys


def planning_issue_segments(
    issues: list[dict], segment_event_ids: dict[int, list[str]],
) -> set[int]:
    """Resolve the smallest executable segment closure described by issues."""
    affected: set[int] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        direct = _integer(issue.get("segment"))
        if direct:
            affected.add(direct)
        raw_segments = issue.get("affected_segments")
        if isinstance(raw_segments, list):
            affected.update(
                number for number in (_integer(value) for value in raw_segments)
                if number
            )
        event_ids = {
            str(value or "").strip().upper()
            for value in issue.get("affected_event_ids", [])
            if str(value or "").strip()
        }
        event_id = str(issue.get("event_id") or "").strip().upper()
        if event_id:
            event_ids.add(event_id)
        if event_ids:
            for segment, owned in segment_event_ids.items():
                if event_ids.intersection(str(value).upper() for value in owned):
                    affected.add(segment)
    return {value for value in affected if value in segment_event_ids}


def planning_candidate_comparison(
    previous_issues: list[dict], candidate_issues: list[dict],
) -> dict[str, Any]:
    """Accept only a strict semantic improvement with no new hard failure."""
    previous = planning_issue_keys(previous_issues)
    candidate = planning_issue_keys(candidate_issues)
    introduced = sorted(candidate - previous)
    resolved = sorted(previous - candidate)
    retained = sorted(previous & candidate)
    improved = bool(resolved) and not introduced
    return {
        "improved": improved,
        "previous_issue_keys": sorted(previous),
        "candidate_issue_keys": sorted(candidate),
        "introduced_issue_keys": introduced,
        "resolved_issue_keys": resolved,
        "retained_issue_keys": retained,
        "reason": (
            "strict_improvement" if improved
            else "introduced_hard_issue" if introduced
            else "no_semantic_progress"
        ),
    }


def planning_recovery_state_matches(
    value: object, *, outline_sha256: str, generation_context_sha256: str,
    segment_count: int,
) -> bool:
    return bool(
        isinstance(value, dict)
        and value.get("version") == PLANNING_RECOVERY_VERSION
        and value.get("outline_sha256") == outline_sha256
        and value.get("generation_context_sha256") == generation_context_sha256
        and value.get("segment_count") == segment_count
        and isinstance(value.get("best_plan_sha256"), str)
        and isinstance(value.get("best_issues"), list)
    )


def new_planning_recovery_state(
    *, outline_sha256: str, generation_context_sha256: str | None,
    segment_count: int, plan: str, issues: list[dict],
) -> dict[str, Any]:
    return {
        "version": PLANNING_RECOVERY_VERSION,
        "status": "running",
        "outline_sha256": outline_sha256,
        "generation_context_sha256": generation_context_sha256 or "",
        "segment_count": segment_count,
        "best_plan_sha256": _hash(plan),
        "best_issue_keys": sorted(planning_issue_keys(issues)),
        "best_issues": issues,
        "semantic_attempts": 0,
        "no_progress_rounds": 0,
        "candidates": [],
    }


def record_planning_candidate(
    state: dict[str, Any], *, plan: str, issues: list[dict],
    comparison: dict[str, Any], source: str, accepted: bool,
) -> dict[str, Any]:
    result = json.loads(json.dumps(state, ensure_ascii=False))
    result.setdefault("candidates", []).append({
        "source": source,
        "planning_sha256": _hash(plan),
        "issue_keys": sorted(planning_issue_keys(issues)),
        "accepted": bool(accepted),
        "comparison": comparison,
    })
    result["semantic_attempts"] = int(result.get("semantic_attempts") or 0) + 1
    if accepted:
        result["best_plan_sha256"] = _hash(plan)
        result["best_issue_keys"] = sorted(planning_issue_keys(issues))
        result["best_issues"] = issues
        result["no_progress_rounds"] = 0
    else:
        result["no_progress_rounds"] = int(result.get("no_progress_rounds") or 0) + 1
    return result


def write_planning_recovery(
    outputs: Path, state: dict[str, Any], best_plan: str,
) -> None:
    """Persist the recoverable candidate and its ledger as one hash-bound pair."""
    if state.get("best_plan_sha256") != _hash(best_plan):
        raise ValueError("Planning recovery state does not bind the best plan")
    atomic_write(outputs / "planning-best.md", best_plan)
    atomic_write(
        outputs / "planning-recovery-state.json",
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
    )


def read_planning_recovery(outputs: Path) -> tuple[dict, str] | None:
    try:
        state = json.loads(
            (outputs / "planning-recovery-state.json").read_text(encoding="utf-8")
        )
        plan = (outputs / "planning-best.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict) or state.get("best_plan_sha256") != _hash(plan):
        return None
    return state, plan


def _integer(value: object) -> int:
    try:
        result = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return result if result > 0 else 0


def _string_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({
        str(item or "").strip().lower()
        for item in value if str(item or "").strip()
    })


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
