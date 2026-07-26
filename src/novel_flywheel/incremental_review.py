from __future__ import annotations

import hashlib
from difflib import SequenceMatcher

from novel_flywheel.quality import issue_ledger


def build_review_baseline(
    manuscript: str, analysis: dict, evidence: list[dict], review: dict,
) -> dict:
    issues = issue_ledger(review.get("issues", []))
    return {
        "manuscript": manuscript,
        "manuscript_hash": _hash(manuscript),
        "analysis": analysis,
        "windows": analysis.get("windows", []),
        "evidence": evidence,
        "issue_ledger": issues,
        "review": review,
        "coverage": analysis.get("coverage", 0.0),
    }


def diff_manuscripts(
    before: str, after: str, before_analysis: dict, after_analysis: dict,
) -> dict:
    ranges = []
    for tag, old_start, old_end, new_start, new_end in SequenceMatcher(
        None, before, after, autojunk=False,
    ).get_opcodes():
        if tag != "equal":
            ranges.append({
                "kind": tag, "old_start": old_start, "old_end": old_end,
                "new_start": new_start, "new_end": new_end,
            })
    changed = sum(max(item["old_end"] - item["old_start"],
                      item["new_end"] - item["new_start"]) for item in ranges)
    before_events = [item.get("signature", item.get("predicate")) for item in before_analysis.get("events", [])]
    after_events = [item.get("signature", item.get("predicate")) for item in after_analysis.get("events", [])]
    before_relations = {item.get("id") for item in before_analysis.get("narrative_ledger", {}).get("relations", []) if item.get("id")}
    after_relations = {item.get("id") for item in after_analysis.get("narrative_ledger", {}).get("relations", []) if item.get("id")}
    return {
        "ranges": ranges,
        "changed_ratio": changed / max(1, len(before)),
        "changed_windows": sorted({
            window["index"]
            for item in ranges for window in after_analysis.get("windows", [])
            if _overlaps(item["new_start"], item["new_end"], window["start"], window["end"])
        }),
        "changed_entities": sorted(
            {item.get("text") for item in before_analysis.get("entities", [])}
            ^ {item.get("text") for item in after_analysis.get("entities", [])}
        ),
        "changed_events": sorted(set(before_events) ^ set(after_events)),
        "changed_narrative_relations": sorted(before_relations ^ after_relations),
        "event_order_changed": (
            set(before_events) == set(after_events) and before_events != after_events
        ),
        "opening_promise_changed": before[:500] != after[:500],
        "ending_changed": before[-500:] != after[-500:],
    }


def select_review_scope(baseline: dict, current_analysis: dict, changes: dict) -> dict:
    windows = current_analysis.get("windows", [])
    total = len(windows)
    selected: set[int] = set()
    reasons: dict[str, list[str]] = {}

    def add(index: int, reason: str) -> None:
        if 1 <= index <= total:
            selected.add(index)
            reasons.setdefault(str(index), [])
            if reason not in reasons[str(index)]:
                reasons[str(index)].append(reason)

    changed_windows = changes.get("changed_windows", [])
    for index in changed_windows:
        add(index, "changed")
        add(index - 1, f"adjacent_to:{index}")
        add(index + 1, f"adjacent_to:{index}")

    changed_names = set(changes.get("changed_entities", []))
    for index in changed_windows:
        changed_names.update(
            item.get("text") for item in current_analysis.get("entities", [])
            if item.get("window") == index
        )
    for entity in current_analysis.get("entities", []):
        name, index = entity.get("text"), entity.get("window")
        if name and name in changed_names and index:
            add(index, f"shared_entity:{name}")

    event_signatures = set(changes.get("changed_events", []))
    for event in current_analysis.get("events", []):
        signature = event.get("signature", event.get("predicate"))
        if signature in event_signatures and event.get("window"):
            add(event["window"], f"related_event:{signature}")

    changed_relations = set(changes.get("changed_narrative_relations", []))
    for relation in current_analysis.get("narrative_ledger", {}).get("relations", []):
        relation_id = relation.get("id")
        if relation_id not in changed_relations:
            continue
        for position in (relation.get("from_start"), relation.get("to_start")):
            for window in windows:
                if isinstance(position, int) and window["start"] <= position < window["end"]:
                    add(window["index"], f"narrative_relation:{relation_id}")

    ambiguous = _mapping_ambiguity(baseline.get("windows", []), windows)
    return {
        "selected_windows": sorted(selected),
        "reasons": reasons,
        "selected_ratio": len(selected) / max(1, total),
        "total_windows": total,
        "coverage": 1.0 if selected and all(str(item) in reasons for item in selected) else 0.0,
        "ambiguous": ambiguous,
    }


def requires_full_review(
    scope: dict, changes: dict, current_analysis: dict,
) -> tuple[bool, list[str]]:
    reasons = []
    if changes.get("changed_ratio", 0) > 0.20:
        reasons.append("changed_ratio")
    if scope.get("selected_ratio", 0) > 0.40:
        reasons.append("selected_ratio")
    for key in (
        "event_order_changed", "scene_order_changed", "principal_character_changed",
        "key_event_changed", "opening_promise_changed", "climax_changed",
        "ending_changed", "timeline_changed", "causal_relations_changed",
        "reviewer_requested_full",
    ):
        if changes.get(key):
            reasons.append(key)
    if not current_analysis.get("nlp", {}).get("available"):
        reasons.append("ltp_unavailable")
    if scope.get("ambiguous"):
        reasons.append("ambiguous_mapping")
    prose = current_analysis.get("prose", {})
    if prose.get("blocking_count"):
        reasons.append("new_blocking_issue")
    return bool(reasons), reasons


def apply_incremental_gate(
    review: dict, baseline: dict, scope: dict, current_analysis: dict,
    reconciliations: list[dict],
) -> tuple[dict, list[str]]:
    reasons = []
    digest = current_analysis.get("text_hash", "")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        reasons.append("stale_analysis")
    if baseline.get("coverage") != 1.0 or scope.get("coverage") != 1.0:
        reasons.append("incomplete_review_coverage")
    expected = {item.get("issue_id") for item in baseline.get("issue_ledger", [])}
    actual = {item.get("issue_id") for item in reconciliations}
    if expected - actual:
        reasons.append("missing_issue_reconciliation")
    allowed_states = {"resolved", "unresolved", "uncertain"}
    if any(item.get("status") not in allowed_states for item in reconciliations):
        reasons.append("invalid_issue_reconciliation")
    severity_by_id = {
        item.get("issue_id"): str(item.get("severity", "")).lower()
        for item in baseline.get("issue_ledger", [])
    }
    if any(
        item.get("status") in {"unresolved", "uncertain"}
        and severity_by_id.get(item.get("issue_id")) in {"major", "critical", "blocking", "high"}
        for item in reconciliations
    ):
        reasons.append("unresolved_major_issue")
    if current_analysis.get("prose", {}).get("blocking_count"):
        reasons.append("new_blocking_issue")
    result = dict(review)
    if reasons:
        result["hard_fail"] = True
        result["decision"] = "rewrite"
    return result, reasons


def _mapping_ambiguity(old_windows: list[dict], new_windows: list[dict]) -> list[int]:
    old_hashes = {item.get("hash") for item in old_windows}
    return [
        item["index"] for item in new_windows
        if item.get("hash") not in old_hashes and not item.get("text")
    ]


def _overlaps(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    if left_start == left_end:
        return right_start <= left_start <= right_end
    return left_start < right_end and right_start < left_end


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

