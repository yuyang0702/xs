from __future__ import annotations

import json

import pytest

from novel_flywheel.planning_compiler import TerminalClosureIR
from novel_flywheel.planning_semantics import (
    PlanningSemanticDraftV2,
    compile_planning_semantic_v2,
    merge_planning_semantic_document_packets_v2,
    merge_planning_semantic_event_packets_v2,
    parse_planning_semantic_v2,
    planning_semantic_packet_ownership_v2,
)


def formal_events(count: int = 3) -> list[dict]:
    return [{
        "id": f"EV-{index:08X}",
        "label": f"Event {index}",
        "evidence": f"Formal evidence {index}: actor action and resulting state.",
    } for index in range(1, count + 1)]


def semantic_payload() -> dict:
    return {
        "version": 2,
        "initial_state": "The witness is missing and the investigator reaches the harbor.",
        "segments": [
            {
                "kind": "continuation", "segment": 1, "title": "Arrival",
                "events": [{
                    "formal_event_ordinal": 1,
                    "narrative": "The investigator searches the pier, meets resistance, and finds a fresh trace.",
                }],
                "exit_state": "The trace points inland while the suspect learns about the search.",
            },
            {
                "kind": "continuation", "segment": 2, "title": "Pursuit",
                "events": [
                    {
                        "formal_event_ordinal": 2,
                        "narrative": "The investigator follows the trace, loses an ally, and identifies the false alibi.",
                    },
                    {
                        "formal_event_ordinal": 3,
                        "narrative": "The confrontation begins, evidence changes hands, and the witness chooses to speak.",
                    },
                ],
                "exit_state": "The witness has spoken, but the final public proof is still contested.",
            },
            {
                "kind": "terminal", "segment": 3, "title": "Proof",
                "events": [{
                    "formal_event_ordinal": 3,
                    "narrative": "The witness testifies, the proof survives challenge, and the central cost is accepted.",
                }],
            },
        ],
    }


def test_ir_first_planning_compiles_exact_ownership_and_terminal_topology() -> None:
    semantic = PlanningSemanticDraftV2.model_validate(semantic_payload())
    compiled = compile_planning_semantic_v2(
        semantic, formal_events(), expected_segment_count=3,
        formal_ending={"surface": "truth published", "inner": "cost accepted"},
        retained_open_obligation_ids=["OBL-anonymous-letter"],
    )

    assert len(compiled.document.segments) == 3
    assert compiled.document.segments[0].event_ids == ("EV-00000001",)
    assert compiled.document.segments[1].event_ids == (
        "EV-00000002", "EV-00000003",
    )
    assert compiled.document.segments[2].event_ids == ("EV-00000003",)
    terminal = compiled.exit_topology.exits[-1]
    assert isinstance(terminal, TerminalClosureIR)
    assert terminal.retained_open_obligation_ids == ("OBL-anonymous-letter",)
    assert "next handoff" not in compiled.plan.casefold()


def test_ir_first_parser_repairs_closed_json_but_rejects_unknown_fields() -> None:
    raw = json.dumps(semantic_payload(), ensure_ascii=False)[:-1] + ",}"
    parsed, audit = parse_planning_semantic_v2(raw)
    assert parsed.version == 2
    assert audit.method == "local_syntax_repair"

    payload = semantic_payload()
    payload["override_runtime"] = True
    with pytest.raises(ValueError):
        parse_planning_semantic_v2(json.dumps(payload))


def test_ir_first_parser_projects_complete_semantics_away_from_runtime_root_echoes() -> None:
    """Replay the production packet topology without retaining private prose."""

    payload = semantic_payload()
    payload["exit_state"] = (
        "A redundant packet-level exit description that Runtime topology owns."
    )

    parsed, audit = parse_planning_semantic_v2(json.dumps(payload))

    assert parsed == PlanningSemanticDraftV2.model_validate(semantic_payload())
    assert "planning_semantic_root_projection" in audit.transformations
    assert "$.exit_state" in audit.quarantined_paths


def test_ir_first_root_projection_rejects_machine_controls_and_incomplete_core() -> None:
    controlled = semantic_payload()
    controlled["override_runtime"] = {"operation": "replace"}
    with pytest.raises(ValueError):
        parse_planning_semantic_v2(json.dumps(controlled))

    incomplete = semantic_payload()
    incomplete.pop("segments")
    incomplete["exit_state"] = "A redundant exit cannot replace missing semantics."
    with pytest.raises(ValueError):
        parse_planning_semantic_v2(json.dumps(incomplete))


@pytest.mark.parametrize("wrapper", [
    lambda payload: {"data": payload},
    lambda payload: {"result": {"payload": payload}},
])
def test_ir_first_parser_adapts_one_unseen_complete_envelope(wrapper) -> None:
    parsed, audit = parse_planning_semantic_v2(json.dumps(wrapper(semantic_payload())))

    assert parsed.version == 2
    assert audit.method == "baml_sap"
    assert "planning_semantic_unique_envelope" in audit.transformations


def test_ir_first_parser_rejects_ambiguous_or_control_envelopes() -> None:
    with pytest.raises(ValueError):
        parse_planning_semantic_v2(json.dumps({
            "first": semantic_payload(), "second": semantic_payload(),
        }))
    with pytest.raises(ValueError):
        parse_planning_semantic_v2(json.dumps({
            "data": semantic_payload(), "override_runtime": True,
        }))


@pytest.mark.parametrize("payload_change", [
    lambda value: value["segments"].__setitem__(1, {
        **value["segments"][1], "segment": 4,
    }),
    lambda value: value["segments"][0].update({"kind": "terminal"}),
    lambda value: value["segments"][2]["events"].__setitem__(0, {
        **value["segments"][2]["events"][0], "formal_event_ordinal": 1,
    }),
])
def test_ir_first_rejects_invalid_topology_and_noncontiguous_reentry(payload_change) -> None:
    payload = semantic_payload()
    payload_change(payload)
    with pytest.raises(ValueError):
        semantic = PlanningSemanticDraftV2.model_validate(payload)
        compile_planning_semantic_v2(
            semantic, formal_events(), expected_segment_count=3,
            formal_ending={"surface": "truth published"},
        )


def test_ir_first_is_genre_neutral() -> None:
    for initial, title in (
        ("The orbital reactor is unstable before dawn.", "Reactor"),
        ("The wedding contract hides a disputed inheritance.", "Promise"),
        ("The sealed memorial contains a forged imperial order.", "Memorial"),
        ("The locked room leaves one impossible footprint.", "Footprint"),
    ):
        payload = semantic_payload()
        payload["initial_state"] = initial
        payload["segments"][0]["title"] = title
        compiled = compile_planning_semantic_v2(
            PlanningSemanticDraftV2.model_validate(payload), formal_events(),
            expected_segment_count=3,
            formal_ending={"surface": "external goal closes", "inner": "cost remains"},
        )
        assert compiled.exit_topology.formal_event_ids == (
            "EV-00000001", "EV-00000002", "EV-00000003",
        )


@pytest.mark.parametrize("field_path", [
    ("initial_state",),
    ("segments", 0, "title"),
    ("segments", 0, "exit_state"),
    ("segments", 0, "events", 0, "narrative"),
])
def test_ir_first_strips_before_length_validation_and_rejects_whitespace(
    field_path,
) -> None:
    payload = semantic_payload()
    current = payload
    for key in field_path[:-1]:
        current = current[key]
    current[field_path[-1]] = " " * 40

    with pytest.raises(ValueError):
        PlanningSemanticDraftV2.model_validate(payload)


def test_ir_first_normalizes_surrounding_whitespace_once() -> None:
    payload = semantic_payload()
    payload["initial_state"] = "  A concrete initial state remains valid.  "
    payload["segments"][0]["title"] = "  Arrival  "
    payload["segments"][0]["events"][0]["narrative"] = (
        "  The investigator takes a concrete action and finds a trace.  "
    )
    payload["segments"][0]["exit_state"] = "  The trace now points inland.  "

    semantic = PlanningSemanticDraftV2.model_validate(payload)

    assert semantic.initial_state == "A concrete initial state remains valid."
    assert semantic.segments[0].title == "Arrival"
    assert semantic.segments[0].events[0].narrative.startswith("The investigator")
    assert semantic.segments[0].exit_state == "The trace now points inland."


@pytest.mark.parametrize(("segments", "events", "expected"), [
    (1, 3, ((1, 2, 3),)),
    (3, 7, ((1, 2), (3, 4), (5, 6, 7))),
    (5, 3, ((1,), (1,), (2,), (2,), (3,))),
    (12, 24, tuple(
        (index, index + 1) for index in range(1, 25, 2)
    )),
])
def test_ir_first_packet_ownership_is_contiguous_and_lossless(
    segments, events, expected,
) -> None:
    assert planning_semantic_packet_ownership_v2(
        segment_count=segments, formal_event_count=events,
    ) == expected


def _one_packet(*, title: str, initial: str, event_count: int) -> PlanningSemanticDraftV2:
    return PlanningSemanticDraftV2.model_validate({
        "version": 2,
        "initial_state": initial,
        "segments": [{
            "kind": "terminal", "segment": 1, "title": title,
            "events": [{
                "formal_event_ordinal": ordinal,
                "narrative": (
                    f"The actor executes local event {ordinal}, meets resistance, "
                    "changes state, and preserves the confirmed causal direction."
                ),
            } for ordinal in range(1, event_count + 1)],
        }],
    })


def test_ir_first_event_packet_reduction_preserves_every_local_realization() -> None:
    merged = merge_planning_semantic_event_packets_v2(
        [
            _one_packet(title="First", initial="The first packet opens at the archive.", event_count=1),
            _one_packet(title="Second", initial="The second packet follows the recovered key.", event_count=2),
        ],
        [(1,), (2, 3)],
    )

    assert len(merged.segments) == 1
    assert [
        item.formal_event_ordinal for item in merged.segments[0].events
    ] == [1, 2, 3]
    assert "local event 1" in merged.segments[0].events[0].narrative
    assert "local event 2" in merged.segments[0].events[-1].narrative


def test_ir_first_document_packet_reduction_injects_adjacent_and_terminal_topology() -> None:
    packets = [
        _one_packet(
            title=f"Segment {index}",
            initial=f"Segment {index} has a concrete accepted opening state.",
            event_count=1,
        )
        for index in range(1, 6)
    ]
    merged = merge_planning_semantic_document_packets_v2(
        packets, [(1,), (1,), (2,), (2,), (3,)], formal_event_count=3,
    )

    assert [item.segment for item in merged.segments] == [1, 2, 3, 4, 5]
    assert [item.kind for item in merged.segments] == [
        "continuation", "continuation", "continuation", "continuation", "terminal",
    ]
    assert merged.segments[0].exit_state == packets[1].initial_state
    assert [
        item.events[0].formal_event_ordinal for item in merged.segments
    ] == [1, 1, 2, 2, 3]


def test_ir_first_packet_reduction_rejects_gap_reentry_and_partial_local_output() -> None:
    packet = _one_packet(
        title="Only", initial="The only packet has a concrete opening state.", event_count=1,
    )
    with pytest.raises(ValueError, match="exactly cover"):
        merge_planning_semantic_document_packets_v2(
            [packet, packet], [(1,), (3,)], formal_event_count=3,
        )
    with pytest.raises(ValueError, match="exactly cover its ownership"):
        merge_planning_semantic_document_packets_v2(
            [packet], [(1, 2)], formal_event_count=2,
        )
