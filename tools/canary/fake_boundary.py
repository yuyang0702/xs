"""Deterministic C0A replacement for the paid model boundary only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from novel_flywheel.execution_manifest import (
    bind_previous_exit_hashes,
    execution_manifest_sha256,
    parse_execution_manifest,
)
from novel_flywheel.models import ModelResult
from novel_flywheel.planning_adaptation import INVARIANT_FIELDS


REQUIRED_SKILLS = frozenset({
    "story-init", "plot-structure", "character-management", "worldbuilding",
    "chapter-writing", "novel-writing", "dialogue", "revision-continuity",
    "humanizer-zh", "story-maintenance",
})


def write_sanitized_skill_fixtures(root: Path) -> None:
    for name in sorted(REQUIRED_SKILLS):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\n---\n\nDeterministic Canary instruction for {name}.",
            encoding="utf-8",
        )


def _execution_manifest_body(user: str) -> dict:
    if (
        "SHORT_EXECUTION_MANIFEST_FRAGMENT_V3" in user
        or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V4" in user
    ):
        expected = json.loads(
            user.split("EXPECTED EVENT IDS:\n", 1)[1].split("\n\n", 1)[0]
        )
        segment = int(user.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
        contracts = json.loads(
            user.split("CURRENT EVENT CONTRACTS:\n", 1)[1].split(
                "\n\nCURRENT ACCEPTED PLAN SEGMENT:\n", 1,
            )[0]
        )
        contract_by_id = {str(item["id"]).upper(): item for item in contracts}
        previous_exit = json.loads(
            user.split("PREVIOUS ACCEPTED EXIT STATE:\n", 1)[1].split(
                "\n\nVIEWPOINT AND TIMELINE AUTHORITY:\n", 1,
            )[0]
        )
        beats = []
        for index, source in enumerate(expected, 1):
            evidence_ids = [
                str(item.get("evidence_id") or "")
                for item in contract_by_id[source].get("evidence_catalog", [])
                if isinstance(item, dict) and str(item.get("evidence_id") or "")
            ]
            beats.append({
                "beat_id": f"{source}/01", "source_event_id": source,
                "order": index, "presentation_order": index,
                "action": f"Execute approved event {source}",
                "preconditions": ["inherit current entry state"],
                "postconditions": [f"complete {source}"],
                "owner_segment": segment, "source_evidence_ids": evidence_ids,
            })
        entry_state = previous_exit or [{"state": "opening", "inherited_from": "opening"}]
        return {
            "beats": beats,
            "segments": [{
                "segment": segment,
                "beat_ids": [item["beat_id"] for item in beats],
                "entry_state": [{
                    "state": item["state"],
                    "inherited_from": item.get("inherited_from")
                    or f"segment-{segment - 1:02d}",
                } for item in entry_state],
                "exit_state": [{
                    "state": f"complete {expected[-1]}",
                    "produced_by": beats[-1]["beat_id"],
                }],
                "previous_exit_sha256": "",
                "prohibited_future_beat_ids": [],
            }],
        }
    expected = json.loads(user.split("EXPECTED EVENT IDS:\n", 1)[1].split("\n\n", 1)[0])
    count = int(user.split("SEGMENT COUNT: ", 1)[1].splitlines()[0])
    total = max(len(expected), count)
    occurrences: dict[str, int] = {}
    beats = []
    per_segment = {number: [] for number in range(1, count + 1)}
    for index in range(total):
        source_index = min(len(expected) - 1, index * len(expected) // total)
        source = expected[source_index]
        occurrences[source] = occurrences.get(source, 0) + 1
        beat_id = f"{source}/{occurrences[source]:02d}"
        segment = min(count, index * count // total + 1)
        beats.append({
            "beat_id": beat_id, "source_event_id": source, "order": index + 1,
            "action": f"Execute approved event {source}",
            "preconditions": ["inherit previous beat"],
            "postconditions": [source], "owner_segment": segment,
            "source_evidence": source,
        })
        per_segment[segment].append(beat_id)
    segments = []
    previous_state = ""
    all_ids = [item["beat_id"] for item in beats]
    for number in range(1, count + 1):
        owned = per_segment[number]
        exit_state = next(
            item["source_event_id"] for item in reversed(beats)
            if item["beat_id"] in owned
        )
        segments.append({
            "segment": number, "beat_ids": owned,
            "entry_state": [{
                "state": previous_state or "opening",
                "inherited_from": "opening" if number == 1 else f"segment-{number - 1:02d}",
            }],
            "exit_state": [{"state": exit_state, "produced_by": owned[-1]}],
            "previous_exit_sha256": "" if number == 1 else "a" * 64,
            "prohibited_future_beat_ids": [
                beat_id for beat_id in all_ids
                if beats[all_ids.index(beat_id)]["owner_segment"] > number
            ],
        })
        previous_state = exit_state
    return bind_previous_exit_hashes({"beats": beats, "segments": segments})


def _execution_manifest_receipt(user: str) -> str:
    boundary_candidates = json.loads(
        user.split("BOUNDARY EVIDENCE CANDIDATES:\n", 1)[1].split(
            "\n\nEXECUTION MANIFEST:\n", 1,
        )[0]
    )
    raw = user.split("EXECUTION MANIFEST:\n", 1)[1].split(
        "\n\nAUTHORITY TEXT:\n", 1,
    )[0]
    manifest = parse_execution_manifest(json.loads(raw))
    return json.dumps({
        "authority_sha256": manifest.authority_sha256,
        "manifest_sha256": execution_manifest_sha256(manifest),
        "beat_receipts": [{
            "beat_id": beat.beat_id,
            **(
                {"evidence_ids": list(beat.source_evidence_ids)}
                if beat.source_evidence_ids else {"evidence": beat.source_evidence}
            ),
            "actor_action_valid": True,
        } for beat in manifest.beats],
        "segment_receipts": [{
            "segment": segment.segment, "boundary_valid": True,
            "evidence_id": next(reversed(boundary_candidates)),
        } for segment in manifest.segments],
        "formal_plot_unchanged": True,
        "summary": "Execution manifest matches the approved authority.",
    }, ensure_ascii=False)


def _draft_semantic_receipt(contract: dict, prose: str) -> dict:
    evidence = prose[:12]
    order_evidence = prose if len(prose) <= 80 else prose[:80]
    payload = {
        "authority_sha256": contract["authority_sha256"],
        "task_id": contract["task_id"],
        "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
        "entry": {"satisfied": True, "evidence": evidence},
        "exit": {"satisfied": True, "evidence": prose[-12:]},
        "causal_order_valid": True,
        "causal_order_evidence": order_evidence,
        "summary": "Events, state, order, and handoff are verified.",
    }
    if contract.get("beat_ids"):
        payload.update({
            "execution_manifest_sha256": contract["execution_manifest_sha256"],
            "beat_receipts": [{
                "beat_id": beat_id, "evidence": evidence,
                "actor_action_valid": True, "actor_action_evidence": evidence,
                "state_valid": True, "state_evidence": evidence,
                "scene_order_valid": True, "scene_order_evidence": order_evidence,
            } for beat_id in contract["beat_ids"]],
            "outside_beat_ids": [], "future_beat_ids": [],
            "viewpoint_valid": True, "viewpoint_evidence": evidence,
        })
    else:
        payload.update({
            "event_receipts": [{"event_id": item, "evidence": evidence}
                               for item in contract["event_ids"]],
            "outside_event_ids": [],
        })
    return payload


def _planning_segment_receipt(user: str) -> str:
    authority = user.split("EXPECTED AUTHORITY SHA256: ", 1)[1].splitlines()[0]
    planning = user.split("EXPECTED PLANNING SHA256: ", 1)[1].splitlines()[0]
    authority_version = int(
        user.split("EXPECTED AUTHORITY VERSION: ", 1)[1].splitlines()[0]
    )
    segment = int(user.split("CURRENT SEGMENT: ", 1)[1].splitlines()[0])
    expected = json.loads(
        user.split("EXPECTED EVENT IDS:\n", 1)[1].splitlines()[0]
    )
    candidate_source = user.split("PLAN EVIDENCE CANDIDATES:\n", 1)[1]
    candidate_source = candidate_source.split(
        "\n\nRECEIPT PROTOCOL ISSUES:", 1,
    )[0]
    candidates = json.loads(candidate_source)
    evidence_ids = list(candidates) if isinstance(candidates, dict) else [
        str(item.get("evidence_id") or "") for item in candidates
        if isinstance(item, dict) and item.get("evidence_id")
    ]
    return json.dumps({
        "authority_sha256": authority,
        "planning_sha256": planning,
        "authority_version": authority_version,
        "segment": segment,
        "event_reviews": [{
            "event_id": event_id,
            "classification": "equivalent",
            "changed_dimensions": ["scene_realization"],
            "invariants": {field: True for field in INVARIANT_FIELDS},
            "plan_evidence_ids": [
                evidence_ids[min(index, len(evidence_ids) - 1)]
            ],
            "plan_evidence_quote": "",
            "reason": "The accepted plan preserves formal event function and direction.",
        } for index, event_id in enumerate(expected)],
        "segment_order_preserved": True,
        "formal_direction_preserved": True,
        "summary": "The accepted segment preserves formal authority.",
    })


def _planning_whole_receipt(user: str) -> str:
    authority = user.split("EXPECTED AUTHORITY SHA256: ", 1)[1].splitlines()[0]
    planning = user.split("EXPECTED PLANNING SHA256: ", 1)[1].splitlines()[0]
    segments = json.loads(
        user.split("EXPECTED SEGMENTS:\n", 1)[1].splitlines()[0]
    )
    expected = json.loads(
        user.split("EXPECTED EVENT IDS:\n", 1)[1].splitlines()[0]
    )
    return json.dumps({
        "authority_sha256": authority,
        "planning_sha256": planning,
        "segment_numbers": segments,
        "event_ids": expected,
        "causal_order_preserved": True,
        "adjacent_handoffs_preserved": True,
        "knowledge_progression_preserved": True,
        "relationship_progression_preserved": True,
        "viewpoint_timeline_preserved": True,
        "promises_ending_preserved": True,
        "formal_direction_preserved": True,
        "affected_segments": [],
        "affected_event_ids": [],
        "reason": "",
        "summary": "The whole plan preserves order, continuity, promises, and ending.",
    })


def _planning_hierarchy_receipt(user: str) -> str:
    source_match = re.search(r"SOURCE SHA256: ([0-9a-f]{64})", user)
    segments_match = re.search(r"EXPECTED SEGMENTS: (\[[^\n]+\])", user)
    events_match = re.search(r"EXPECTED EVENT IDS: (\[[^\n]+\])", user)
    if source_match is None or segments_match is None or events_match is None:
        raise AssertionError("planning hierarchy authority is incomplete")
    segments = json.loads(segments_match.group(1))
    expected = json.loads(events_match.group(1))
    return json.dumps({
        "source_sha256": source_match.group(1),
        "segment_numbers": segments,
        "event_ids": expected,
        "causal_order_preserved": True,
        "adjacent_handoffs_preserved": True,
        "knowledge_progression_preserved": True,
        "relationship_progression_preserved": True,
        "viewpoint_timeline_preserved": True,
        "promises_ending_preserved": True,
        "formal_direction_preserved": True,
        "affected_segments": [],
        "affected_event_ids": [],
        "entry_state": "The accepted authority supplies the current entry state.",
        "exit_state": "The current range hands off in formal order.",
        "knowledge_state": "Knowledge advances only through owned events.",
        "relationship_state": "Relationship changes remain action-supported.",
        "viewpoint_timeline": "Viewpoint and chronology remain unchanged.",
        "open_promises": ["The approved ending promise remains active."],
        "resolved_promises": [],
        "reason": "",
        "summary": "The hierarchy range preserves the complete authority.",
    })


class DeterministicShortBoundary:
    """Sanitized full-Short responses; no client, credential, or transport."""

    def __init__(self) -> None:
        self.roles: list[str] = []
        self.responses = iter([
            "# Draft\nThe investigator follows the approved evidence and reaches the fixed ending.",
            json.dumps({"score": 86, "hard_fail": False, "issues": ["tighten prose"]}),
            json.dumps({"score": 84, "hard_fail": False, "issues": ["strengthen hook"]}),
            "# Final Story\nThe investigator follows the evidence and completes the approved ending.",
            json.dumps({"score": 92, "hard_fail": False, "issues": []}),
            json.dumps({
                "facts": [
                    "The investigator follows the evidence and completes the approved ending."
                ]
            }),
        ])

    @staticmethod
    def _result(role: str, text: str) -> ModelResult:
        return ModelResult(text, {
            "role": role, "model_name": "c0a-fake-boundary",
            "provider_id": "c0a-fake-provider-v1",
            "model_id": "c0a-fake-model-v1",
            "finish_reason": "stop", "input_tokens": 100,
            "output_tokens": 50,
        })

    async def complete(self, role, system, user, max_output_tokens=None, **kwargs):
        self.roles.append(role)
        if not system.strip():
            raise AssertionError("real stage system assembly was not retained")
        if "IR_FIRST_SHORT_PLANNING_PACKET_V2" in user:
            contract = json.loads(
                user.split("PACKET CONTRACT:\n", 1)[1].split("\n\n", 1)[0]
            )
            count = len(contract["global_event_ordinals"])
            return self._result(role, json.dumps({
                "version": 2,
                "initial_state": "The approved authority defines the opening state.",
                "segments": [{
                    "kind": "terminal", "segment": 1,
                    "title": "Complete this approved authority packet",
                    "events": [{
                        "formal_event_ordinal": ordinal,
                        "narrative": (
                            "The investigator actively checks the exact approved evidence, "
                            "meets a concrete obstacle, makes the authorized decision, "
                            "records the verifiable result, updates only the owned current "
                            "state, and preserves the confirmed causal direction and ending."
                        ),
                    } for ordinal in range(1, count + 1)],
                }],
            }))
        if "IR_FIRST_SHORT_PLANNING_V2" in user:
            catalog = json.loads(user.split("FORMAL EVENT CATALOG:\n", 1)[1])
            segment_count = int(
                user.split("Return exactly ", 1)[1].split(" contiguous segments", 1)[0]
            )
            ownership = {number: [] for number in range(1, segment_count + 1)}
            for ordinal in range(1, len(catalog) + 1):
                owner = min(
                    segment_count,
                    ((ordinal - 1) * segment_count // len(catalog)) + 1,
                )
                ownership[owner].append(ordinal)
            for number in range(1, segment_count + 1):
                if not ownership[number]:
                    ownership[number].append(
                        min(len(catalog), max(1, number * len(catalog) // segment_count))
                    )
            return self._result(role, json.dumps({
                "version": 2,
                "initial_state": "The approved authority defines the opening state.",
                "segments": [{
                    "kind": "terminal" if number == segment_count else "continuation",
                    "segment": number,
                    "title": f"Complete approved segment {number}",
                    "events": [{
                        "formal_event_ordinal": ordinal,
                        "narrative": (
                            "The investigator actively checks the exact approved evidence, "
                            "meets a concrete obstacle, makes the authorized decision, "
                            "records the verifiable result, updates only the owned current "
                            "state, and preserves the confirmed causal direction and ending."
                        ),
                    } for ordinal in ownership[number]],
                    **({"exit_state": "The verified result passes to the next segment."}
                       if number < segment_count else {}),
                } for number in range(1, segment_count + 1)],
            }))
        if "SHORT_PLAN_ADAPTATION_REVIEW_V2" in user:
            return self._result(role, _planning_segment_receipt(user))
        if "SHORT_PLAN_ADAPTATION_WHOLE_STORY_REVIEW_V2" in user:
            return self._result(role, _planning_whole_receipt(user))
        if (
            "SHORT_PLAN_ADAPTATION_REGIONAL_REVIEW_V3" in user
            or "SHORT_PLAN_ADAPTATION_HIERARCHY_REDUCTION_V3" in user
        ):
            return self._result(role, _planning_hierarchy_receipt(user))
        if (
            "SHORT_EXECUTION_MANIFEST_V2" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V3" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_V4" in user
        ):
            return self._result(
                role, json.dumps(_execution_manifest_body(user), ensure_ascii=False),
            )
        if (
            "SHORT_EXECUTION_MANIFEST_SEMANTIC_VALIDATION" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V3" in user
            or "SHORT_EXECUTION_MANIFEST_FRAGMENT_SEMANTIC_VALIDATION_V4" in user
        ):
            return self._result(role, _execution_manifest_receipt(user))
        if "DRAFT_SEMANTIC_VALIDATION" in user:
            match = re.search(r"TASK CONTRACT: (\{[^\n]+\})", user)
            if match is None:
                raise AssertionError("draft task contract missing")
            contract = json.loads(match.group(1))
            prose = user.split("PROSE:\n", 1)[1]
            return self._result(
                role, json.dumps(_draft_semantic_receipt(contract, prose), ensure_ascii=False),
            )
        if "DRAFT_WHOLE_SEMANTIC_VALIDATION" in user:
            authority = re.search(r"AUTHORITY SHA256: ([0-9a-f]{64})", user).group(1)
            draft_sha = re.search(r"DRAFT SHA256: ([0-9a-f]{64})", user).group(1)
            segments = json.loads(re.search(r"SEGMENT SHA256: (\[[^\n]+\])", user).group(1))
            events = json.loads(re.search(r"EXPECTED EVENT IDS: (\[[^\n]+\])", user).group(1))
            opening = user.split("OPENING EXCERPT: ", 1)[1].split("\nENDING EXCERPT:", 1)[0]
            ending = user.split("ENDING EXCERPT: ", 1)[1]
            return self._result(role, json.dumps({
                "authority_sha256": authority, "draft_sha256": draft_sha,
                "segment_sha256": segments, "event_ids": events,
                "missing_event_ids": [], "duplicate_event_ids": [],
                "out_of_order_event_ids": [], "causal_order_valid": True,
                "continuity_valid": True, "ending_valid": True,
                "commitments_valid": True,
                "evidence": [
                    {"kind": "opening", "excerpt": opening[:12]},
                    {"kind": "ending", "excerpt": ending[-12:]},
                ],
                "summary": "Whole draft coverage and ending are verified.",
            }, ensure_ascii=False))
        if "SHORT_CAUSAL_CHAIN_STANDALONE" in user:
            event_ids = list(dict.fromkeys(re.findall(r"EV-[0-9A-F]{8}", user.upper())))
            return self._result(role, json.dumps({
                "core_goal": "Complete the approved goal",
                "cycles": [{"obstacle": "obstacle", "effort": "action", "result": "progress"}],
                "ending": "Reach the approved ending",
                "covered_event_ids": event_ids,
            }))
        text = next(self.responses)
        if "TARGET READER SIMULATION" in user:
            payload = json.loads(text)
            payload["reader_signals"] = {
                "would_continue": True, "would_pay": True,
                "abandonment_point": "none", "payoff_felt": True,
            }
            text = json.dumps(payload)
        if role == "final_review" and "AUTHORITATIVE REVIEW ISSUE LEDGER:" in user:
            payload = json.loads(text)
            ledger_text = user.split(
                "AUTHORITATIVE REVIEW ISSUE LEDGER:\n", 1,
            )[1].split("\n\n", 1)[0]
            ledger = json.loads(ledger_text)
            payload["reconciliations"] = [{
                "issue_id": item["issue_id"], "status": "resolved",
                "severity": item.get("severity", "medium"),
                "evidence": "investigator follows the evidence",
            } for item in ledger]
            text = json.dumps(payload)
        return self._result(role, text)

    async def complete_primary(
        self, role, system, user, max_output_tokens=None, **kwargs,
    ):
        return await self.complete(
            role, system, user, max_output_tokens=max_output_tokens, **kwargs,
        )
