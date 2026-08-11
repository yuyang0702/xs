from __future__ import annotations

import json

import pytest

from novel_flywheel.planning_compiler import TerminalClosureIR
from novel_flywheel.planning_semantics import (
    PlanningSemanticDraftV2,
    compile_planning_semantic_v2,
    parse_planning_semantic_v2,
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
