from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_flywheel.storage import atomic_write


PLANNING_RECOVERY_VERSION = 1
PLANNING_RECOVERY_ENVELOPE_VERSION = 1


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
    previous_issues: list[dict], candidate_issues: list[dict], *,
    changed_segments: set[int] | list[int] | tuple[int, ...] | None = None,
    segment_event_ids: dict[int, list[str]] | None = None,
) -> dict[str, Any]:
    """Accept only a strict semantic improvement with no attributable regression.

    The historical two-argument form compares the complete hard-issue set.  A
    repair workflow may additionally provide the segments whose bytes actually
    changed.  In that mode, a finding wholly owned by an unchanged segment is
    retained as a latent baseline issue instead of being blamed on the current
    candidate.  Unscoped and cross-boundary findings remain attributable to the
    candidate so whole-plan safety is never weakened.
    """
    previous = planning_issue_keys(previous_issues)
    candidate = planning_issue_keys(candidate_issues)
    changed = {
        number for number in (
            _integer(value) for value in (changed_segments or [])
        ) if number
    }
    if changed_segments is None:
        previous_attributable = previous
        candidate_attributable = candidate
        previous_latent: set[str] = set()
        candidate_latent: set[str] = set()
    else:
        if segment_event_ids is None:
            raise ValueError(
                "segment_event_ids is required for attribution-aware comparison"
            )
        previous_attributable, previous_latent = _partition_planning_issue_keys(
            previous_issues,
            changed_segments=changed,
            segment_event_ids=segment_event_ids,
        )
        candidate_attributable, candidate_latent = _partition_planning_issue_keys(
            candidate_issues,
            changed_segments=changed,
            segment_event_ids=segment_event_ids,
        )
    introduced = sorted(candidate_attributable - previous_attributable)
    resolved = sorted(previous_attributable - candidate_attributable)
    retained = sorted(previous & candidate)
    improved = bool(resolved) and not introduced
    return {
        "improved": improved,
        "previous_issue_keys": sorted(previous),
        "candidate_issue_keys": sorted(candidate),
        "changed_segments": sorted(changed),
        "previous_attributable_issue_keys": sorted(previous_attributable),
        "candidate_attributable_issue_keys": sorted(candidate_attributable),
        "attributable_issue_keys": sorted(candidate_attributable),
        "previous_latent_issue_keys": sorted(previous_latent),
        "latent_baseline_issue_keys": sorted(candidate_latent),
        "newly_discovered_latent_issue_keys": sorted(candidate_latent - previous),
        "observed_new_issue_keys": sorted(candidate - previous),
        "introduced_issue_keys": introduced,
        "resolved_issue_keys": resolved,
        "retained_issue_keys": retained,
        "reason": (
            "strict_improvement" if improved
            else "introduced_hard_issue" if introduced
            else "no_semantic_progress"
        ),
    }


def merge_planning_issue_ledgers(
    previous_issues: list[dict], candidate_issues: list[dict], *,
    changed_segments: set[int] | list[int] | tuple[int, ...],
    segment_event_ids: dict[int, list[str]],
) -> list[dict]:
    """Merge a candidate review without erasing known issues on unchanged text.

    The candidate review is authoritative for changed segments, their adjacent
    boundary findings, and whole-plan findings.  For byte-identical segments,
    newly observed candidate findings are kept and previously known findings
    omitted by a later nondeterministic review are also retained.  This makes
    the best-plan issue ledger monotonic without treating diagnostics as canon.
    """
    changed = {
        number for number in (
            _integer(value) for value in changed_segments
        ) if number
    }
    result = json.loads(json.dumps(candidate_issues, ensure_ascii=False))
    known_keys = planning_issue_keys(result)
    for issue in previous_issues:
        if not isinstance(issue, dict):
            continue
        owned = planning_issue_segments([issue], segment_event_ids)
        if not owned or owned.intersection(changed):
            continue
        missing = planning_issue_keys([issue]) - known_keys
        for retained in _planning_issue_records_for_keys(issue, missing):
            result.append(retained)
            known_keys.update(planning_issue_keys([retained]))
    return result


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
        "candidate_generation_attempts": 0,
        "no_progress_rounds": 0,
        "candidates": [],
        "execution_failures": [],
    }


def record_planning_candidate(
    state: dict[str, Any], *, plan: str, issues: list[dict],
    comparison: dict[str, Any], source: str, accepted: bool,
    counts_as_semantic: bool = True,
) -> dict[str, Any]:
    result = json.loads(json.dumps(state, ensure_ascii=False))
    previous = planning_issue_keys(list(state.get("best_issues") or []))
    candidate_keys = planning_issue_keys(issues)
    comparison_introduced = comparison.get("introduced_issue_keys")
    introduced_keys = (
        sorted({str(value) for value in comparison_introduced})
        if isinstance(comparison_introduced, list)
        else sorted(candidate_keys - previous)
    )
    issue_records = json.loads(json.dumps(issues, ensure_ascii=False))
    result.setdefault("candidates", []).append({
        "source": source,
        "planning_sha256": _hash(plan),
        "issue_keys": sorted(candidate_keys),
        # Keep the lossless diagnostic receipt available to the next repair
        # attempt. Keys remain the acceptance authority; these records are
        # no-regression guidance and must never become canon by themselves.
        "issues": issue_records,
        "introduced_issues": [
            item for item in issue_records
            if planning_issue_keys([item]) & set(introduced_keys)
        ],
        "introduced_issue_keys": introduced_keys,
        "accepted": bool(accepted),
        "comparison": comparison,
    })
    counter = (
        "semantic_attempts" if counts_as_semantic
        else "candidate_generation_attempts"
    )
    result[counter] = int(result.get(counter) or 0) + 1
    if accepted:
        result["best_plan_sha256"] = _hash(plan)
        result["best_issue_keys"] = sorted(planning_issue_keys(issues))
        result["best_issues"] = issues
        result["no_progress_rounds"] = 0
    elif counts_as_semantic:
        result["no_progress_rounds"] = int(result.get("no_progress_rounds") or 0) + 1
    return result


def write_planning_recovery(
    outputs: Path, state: dict[str, Any], best_plan: str,
) -> None:
    """Persist the recoverable candidate and ledger as one atomic envelope.

    The historical projection files remain for audit and compatibility, but
    recovery reads the single envelope first.  A process exit between legacy
    projection writes therefore cannot destroy the newest valid checkpoint.
    """
    if state.get("best_plan_sha256") != _hash(best_plan):
        raise ValueError("Planning recovery state does not bind the best plan")
    state_json = json.dumps(
        state, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    pair_sha256 = hashlib.sha256(
        (state_json + "\n" + best_plan).encode("utf-8"),
    ).hexdigest()
    atomic_write(
        outputs / "planning-recovery.json",
        json.dumps({
            "envelope_version": PLANNING_RECOVERY_ENVELOPE_VERSION,
            "pair_sha256": pair_sha256,
            "state": state,
            "best_plan": best_plan,
        }, ensure_ascii=False, indent=2, sort_keys=True),
    )
    atomic_write(outputs / "planning-best.md", best_plan)
    atomic_write(
        outputs / "planning-recovery-state.json",
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
    )


def read_planning_recovery(outputs: Path) -> tuple[dict, str] | None:
    try:
        envelope = json.loads(
            (outputs / "planning-recovery.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        envelope = None
    if isinstance(envelope, dict) and envelope.get(
        "envelope_version"
    ) == PLANNING_RECOVERY_ENVELOPE_VERSION:
        state = envelope.get("state")
        plan = envelope.get("best_plan")
        if isinstance(state, dict) and isinstance(plan, str):
            state_json = json.dumps(
                state, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            )
            pair_sha256 = hashlib.sha256(
                (state_json + "\n" + plan).encode("utf-8"),
            ).hexdigest()
            if (
                envelope.get("pair_sha256") == pair_sha256
                and state.get("best_plan_sha256") == _hash(plan)
            ):
                return state, plan

    # Backward-compatible V1 pair for runs created before the envelope existed.
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


def _partition_planning_issue_keys(
    issues: list[dict], *, changed_segments: set[int],
    segment_event_ids: dict[int, list[str]],
) -> tuple[set[str], set[str]]:
    attributable: set[str] = set()
    latent: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        keys = planning_issue_keys([issue])
        owned = planning_issue_segments([issue], segment_event_ids)
        if not owned or owned.intersection(changed_segments):
            attributable.update(keys)
        else:
            latent.update(keys)
    return attributable, latent


def _planning_issue_records_for_keys(
    issue: dict, wanted_keys: set[str],
) -> list[dict]:
    if not wanted_keys:
        return []
    for field in ("invalid_invariants", "invalid_dimensions"):
        values = issue.get(field)
        if not isinstance(values, list) or not values:
            continue
        result: list[dict] = []
        for value in values:
            clone = json.loads(json.dumps(issue, ensure_ascii=False))
            clone[field] = [value]
            if planning_issue_keys([clone]).intersection(wanted_keys):
                result.append(clone)
        return result
    clone = json.loads(json.dumps(issue, ensure_ascii=False))
    return [clone] if planning_issue_keys([clone]).intersection(wanted_keys) else []


def _string_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({
        str(item or "").strip().lower()
        for item in value if str(item or "").strip()
    })


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
