from __future__ import annotations

import hashlib
import re
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
    mode: str = "short",
) -> dict:
    if mode not in {"short", "long"}:
        raise ValueError("diff mode must be 'short' or 'long'")
    if mode == "long":
        ranges, structural = _long_diff_ranges(
            before, after, before_analysis, after_analysis,
        )
    else:
        ranges = _exact_diff_ranges(before, after)
        structural = {}
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
        **structural,
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
    impact_relations = current_analysis.get("impact_index", {}).get("relations", {})
    for relation_id in changed_relations:
        for location in impact_relations.get(relation_id, []):
            position = location.get("start")
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
    scope: dict, changes: dict, current_analysis: dict, patch_groups=(),
) -> tuple[bool, list[str]]:
    reasons = []
    if changes.get("changed_ratio", 0) > 0.20:
        reasons.append("changed_ratio")
    if scope.get("selected_ratio", 0) > 0.40:
        reasons.append("selected_ratio")
    for key in (
        "scene_inserted", "scene_deleted", "scene_moved", "scene_merged",
        "event_order_changed", "scene_order_changed", "principal_character_changed",
        "key_event_changed", "opening_promise_changed", "climax_changed",
        "ending_changed", "timeline_changed", "causal_relations_changed",
        "seven_step_structure_changed", "principal_goal_changed",
        "key_choice_changed", "life_death_changed", "identity_changed",
        "relationship_changed", "knowledge_state_changed", "key_evidence_changed",
        "setup_changed", "promise_changed", "question_changed", "payoff_changed",
        "locked_fact_changed", "world_rule_changed", "protected_passage_changed",
        "reviewer_requested_full", "partially_applied_groups",
    ):
        if changes.get(key):
            reasons.append(key)
    if (
        "partially_applied_groups" not in reasons
        and any(
            isinstance(group, dict) and group.get("partially_applied") is True
            for group in patch_groups
        )
    ):
        reasons.append("partially_applied_groups")
    only_mechanical = bool(patch_groups) and all(
        isinstance(group, dict)
        and (group.get("mechanical") is True or group.get("kind") == "mechanical")
        for group in patch_groups
    )
    if not current_analysis.get("nlp", {}).get("available") and not only_mechanical:
        reasons.append("ltp_unavailable")
    if scope.get("ambiguous"):
        reasons.append("ambiguous_mapping")
    prose = current_analysis.get("prose", {})
    if prose.get("blocking_count"):
        reasons.append("new_blocking_issue")
    return bool(reasons), reasons


def apply_incremental_gate(
    review: dict, baseline: dict, scope: dict, current_analysis: dict,
    current_manuscript: str | list[dict] | None = None,
    reconciliations: list[dict] | None = None,
) -> tuple[dict, list[str]]:
    if isinstance(current_manuscript, list) and reconciliations is None:
        reconciliations = current_manuscript
        current_manuscript = None
    reconciliations = reconciliations or []
    reasons = []
    digest = current_analysis.get("text_hash", "")
    if current_manuscript is not None:
        expected_hash = _hash(current_manuscript)
        if digest != expected_hash:
            reasons.append("current_analysis_hash_mismatch")
    elif len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        reasons.append("stale_analysis")
    selected = set(scope.get("selected_windows", []))
    changes_present = bool(selected)
    if current_manuscript is not None and baseline.get("manuscript_hash"):
        changes_present = changes_present or baseline["manuscript_hash"] != _hash(
            current_manuscript
        )
    if changes_present and not selected:
        reasons.append("empty_incremental_scope")
    explained = set()
    for key in scope.get("reasons", {}):
        try:
            explained.add(int(key))
        except (TypeError, ValueError):
            continue
    if selected - explained:
        reasons.append("unexplained_review_window")
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


def _exact_diff_ranges(
    before: str, after: str, old_offset: int = 0, new_offset: int = 0,
) -> list[dict]:
    return [
        {
            "kind": tag,
            "old_start": old_offset + old_start,
            "old_end": old_offset + old_end,
            "new_start": new_offset + new_start,
            "new_end": new_offset + new_end,
        }
        for tag, old_start, old_end, new_start, new_end in SequenceMatcher(
            None, before, after, autojunk=False,
        ).get_opcodes()
        if tag != "equal"
    ]


_CHAPTER_MARKER = re.compile(
    r"(?m)^(?:#{1,6}[ \t]+\S.*|第[^\n]{1,20}[章节卷回部篇](?:[ \t]|$).*)$"
)


def _chapter_spans(text: str) -> list[dict]:
    markers = list(_CHAPTER_MARKER.finditer(text))
    if not markers:
        return [{"key": "__document__", "start": 0, "end": len(text)}]
    chapters = []
    if markers[0].start() > 0:
        chapters.append({"key": "__preamble__", "start": 0,
                         "end": markers[0].start()})
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        chapters.append({
            "key": marker.group().strip(), "start": marker.start(), "end": end,
        })
    return chapters


def _units_for_chapter(analysis: dict, chapter: dict) -> list[dict]:
    units = analysis.get("units", {}).get("scenes", [])
    return [
        unit for unit in units
        if unit.get("start", 0) < chapter["end"]
        and chapter["start"] < unit.get("end", 0)
    ]


def _long_diff_ranges(
    before: str, after: str, before_analysis: dict, after_analysis: dict,
) -> tuple[list[dict], dict]:
    old_chapters = _chapter_spans(before)
    new_chapters = _chapter_spans(after)
    ranges = []
    structural = {
        "scene_inserted": False,
        "scene_deleted": False,
        "scene_moved": False,
        "scene_merged": False,
    }
    old_scene_ids = [
        item.get("stable_id")
        for item in before_analysis.get("units", {}).get("scenes", [])
    ]
    new_scene_ids = [
        item.get("stable_id")
        for item in after_analysis.get("units", {}).get("scenes", [])
    ]
    structural["scene_moved"] = (
        len(old_scene_ids) == len(new_scene_ids)
        and sorted(old_scene_ids) == sorted(new_scene_ids)
        and old_scene_ids != new_scene_ids
    )

    chapter_matcher = SequenceMatcher(
        None,
        [item["key"] for item in old_chapters],
        [item["key"] for item in new_chapters],
        autojunk=False,
    )
    for tag, old_start, old_end, new_start, new_end in chapter_matcher.get_opcodes():
        if tag == "equal":
            for old_chapter, new_chapter in zip(
                old_chapters[old_start:old_end], new_chapters[new_start:new_end],
            ):
                chapter_ranges, flags = _diff_changed_scenes(
                    before, after,
                    _units_for_chapter(before_analysis, old_chapter),
                    _units_for_chapter(after_analysis, new_chapter),
                )
                ranges.extend(chapter_ranges)
                for key, value in flags.items():
                    structural[key] = structural[key] or value
            continue
        old_span = old_chapters[old_start:old_end]
        new_span = new_chapters[new_start:new_end]
        ranges.append({
            "kind": tag,
            "old_start": old_span[0]["start"] if old_span else (
                old_chapters[old_start - 1]["end"] if old_start else 0
            ),
            "old_end": old_span[-1]["end"] if old_span else (
                old_chapters[old_start - 1]["end"] if old_start else 0
            ),
            "new_start": new_span[0]["start"] if new_span else (
                new_chapters[new_start - 1]["end"] if new_start else 0
            ),
            "new_end": new_span[-1]["end"] if new_span else (
                new_chapters[new_start - 1]["end"] if new_start else 0
            ),
        })
        structural["scene_inserted"] = structural["scene_inserted"] or bool(new_span)
        structural["scene_deleted"] = structural["scene_deleted"] or bool(old_span)
    return ranges, {key: value for key, value in structural.items() if value}


def _diff_changed_scenes(
    before: str, after: str, old_units: list[dict], new_units: list[dict],
) -> tuple[list[dict], dict]:
    ranges = []
    flags = {"scene_inserted": False, "scene_deleted": False,
             "scene_merged": False}
    matcher = SequenceMatcher(
        None,
        [item.get("stable_id") for item in old_units],
        [item.get("stable_id") for item in new_units],
        autojunk=False,
    )
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_changed = old_units[old_start:old_end]
        new_changed = new_units[new_start:new_end]
        paired = min(len(old_changed), len(new_changed))
        for index in range(paired):
            old_unit, new_unit = old_changed[index], new_changed[index]
            ranges.extend(_exact_diff_ranges(
                before[old_unit["start"]:old_unit["end"]],
                after[new_unit["start"]:new_unit["end"]],
                old_unit["start"], new_unit["start"],
            ))
        if len(old_changed) > paired:
            first, last = old_changed[paired], old_changed[-1]
            anchor = new_changed[-1]["end"] if new_changed else (
                new_units[new_start - 1]["end"] if new_start else 0
            )
            ranges.append({"kind": "delete", "old_start": first["start"],
                           "old_end": last["end"], "new_start": anchor,
                           "new_end": anchor})
            flags["scene_deleted"] = True
            flags["scene_merged"] = bool(new_changed)
        if len(new_changed) > paired:
            first, last = new_changed[paired], new_changed[-1]
            anchor = old_changed[-1]["end"] if old_changed else (
                old_units[old_start - 1]["end"] if old_start else 0
            )
            ranges.append({"kind": "insert", "old_start": anchor,
                           "old_end": anchor, "new_start": first["start"],
                           "new_end": last["end"]})
            flags["scene_inserted"] = True
    return ranges, flags

