import json

from novel_flywheel.execution_authority import (
    compile_execution_fragment_authority,
    planning_evidence_reference,
    project_execution_fragment_authority,
)


def test_planning_evidence_reference_is_bounded_and_content_addressed() -> None:
    short = planning_evidence_reference(
        segment=1, event_id="EV-00000001", event_body="a" * 100,
    )
    long = planning_evidence_reference(
        segment=1, event_id="EV-00000001", event_body="a" * 10_000,
    )

    assert len(short) == len(long)
    assert short != long
    assert "a" * 20 not in long


def test_fragment_authority_withholds_unscoped_global_arrays() -> None:
    authority_ir = compile_execution_fragment_authority(
        causal_chain={
            "core_goal": "survive",
            "question_chain": ["global question", {
                "event_ids": ["EV-00000002"], "question": "local question",
            }],
            "relationship_arc": ["global relationship"],
        },
        timeline_events=["global time", {
            "event_id": "EV-00000002", "time": "night",
        }],
        presentation_order=["EV-00000001", "EV-00000002"],
        viewpoint_rule="third limited",
    )
    projection = project_execution_fragment_authority(
        authority_ir=authority_ir,
        owned_event_ids=["EV-00000002"], segment=2, segment_count=2,
    )

    assert projection["question_chain"]["local_entries"] == [{
        "event_ids": ["EV-00000002"], "question": "local question",
    }]
    assert projection["relationship_arc"]["local_entries"] == []
    assert projection["timeline_events"]["local_entries"] == [{
        "event_id": "EV-00000002", "time": "night",
    }]
    assert "global relationship" not in json.dumps(projection)


def test_fragment_authority_total_size_scales_linearly_by_segment() -> None:
    totals = []
    for count in (8, 16, 32):
        event_ids = [f"EV-{index:08X}" for index in range(1, count + 1)]
        causal = {
            "core_goal": "goal",
            "question_chain": [f"question {index}" for index in range(count)],
            "relationship_arc": [f"relationship {index}" for index in range(count)],
        }
        timeline = [f"timeline {index}" for index in range(count)]
        authority_ir = compile_execution_fragment_authority(
            causal_chain=causal, timeline_events=timeline,
            presentation_order=event_ids, viewpoint_rule="third limited",
        )
        total = sum(len(json.dumps(project_execution_fragment_authority(
            authority_ir=authority_ir, owned_event_ids=[event_id],
            segment=index, segment_count=count,
        ), ensure_ascii=False)) for index, event_id in enumerate(event_ids, 1))
        totals.append(total)

    assert totals[1] < totals[0] * 2.3
    assert totals[2] < totals[1] * 2.3


def test_fragment_authority_localizes_multi_owner_entries_once_per_segment() -> None:
    totals = []
    for count in (8, 16, 32):
        event_ids = [f"EV-{index:08X}" for index in range(1, count + 1)]
        shared_question = {
            "event_ids": event_ids,
            "question": "One unresolved promise spans the complete story.",
        }
        shared_relationship = {
            "event_ids": event_ids,
            "change": "Trust changes gradually across the complete story.",
        }
        shared_timeline = {
            "event_ids": event_ids,
            "time": "One bounded shared chronology.",
        }
        authority_ir = compile_execution_fragment_authority(
            causal_chain={
                "core_goal": "Resolve the shared promise.",
                "question_chain": [shared_question],
                "relationship_arc": [shared_relationship],
            },
            timeline_events=[shared_timeline],
            presentation_order=event_ids,
            viewpoint_rule="third limited",
        )
        projections = [
            project_execution_fragment_authority(
                authority_ir=authority_ir,
                owned_event_ids=[event_id], segment=index,
                segment_count=count,
            )
            for index, event_id in enumerate(event_ids, 1)
        ]
        totals.append(sum(len(json.dumps(item, ensure_ascii=False)) for item in projections))
        shared_scope = projections[0]["question_chain"]["local_entries"][0]
        assert shared_scope["entry"]["question"] == shared_question["question"]
        assert shared_scope["shared_scope"]["event_count"] == count
        assert shared_scope["shared_scope"]["owned_event_ids"] == [event_ids[0]]
        assert "event_ids" not in shared_scope["entry"]

    assert totals[1] < totals[0] * 2.3
    assert totals[2] < totals[1] * 2.3


def test_fragment_authority_localizes_unknown_nested_event_owned_structures() -> None:
    totals = []
    for count in (8, 16, 32):
        event_ids = [f"EV-{index:08X}" for index in range(1, count + 1)]
        shared_question = {
            "event_ids": event_ids,
            "question": "One promise changes state across the complete story.",
            "milestones": [
                {
                    "event_id": event_id,
                    "state": f"state-{index}",
                    "required_actions": [
                        f"preserve-clue-{index}", f"delay-reveal-{index}",
                    ],
                    "knowledge_delta": {
                        "hero": [f"knows-clue-{index}", f"suspects-ally-{index}"],
                    },
                }
                for index, event_id in enumerate(event_ids, 1)
            ],
            "unknown_global_matrix": [
                {"label": f"global-{index}", "weight": index}
                for index in range(1, count + 1)
            ],
        }
        authority_ir = compile_execution_fragment_authority(
            causal_chain={
                "core_goal": "Resolve the shared promise.",
                "question_chain": [shared_question],
                "relationship_arc": [],
            },
            timeline_events=[], presentation_order=event_ids,
            viewpoint_rule="third limited",
        )
        projections = [
            project_execution_fragment_authority(
                authority_ir=authority_ir, owned_event_ids=[event_id],
                segment=index, segment_count=count,
            )
            for index, event_id in enumerate(event_ids, 1)
        ]
        totals.append(sum(
            len(json.dumps(item, ensure_ascii=False)) for item in projections
        ))
        local = projections[0]["question_chain"]["local_entries"][0]
        assert local["entry"]["milestones"]["content_addressed"] is True
        assert local["entry"]["unknown_global_matrix"]["content_addressed"] is True
        assert len(local["nested_local_entries"]) == 1
        assert local["nested_local_entries"][0]["entry"] == {
            "state": "state-1",
            "required_actions": ["preserve-clue-1", "delay-reveal-1"],
            "knowledge_delta": {
                "hero": ["knows-clue-1", "suspects-ally-1"],
            },
        }
        assert local["nested_local_entries"][0]["field_path"] == ["milestones"]

    assert totals[1] < totals[0] * 2.3
    assert totals[2] < totals[1] * 2.3


def test_fragment_authority_withholds_foreign_descendant_from_parent_owner() -> None:
    event_ids = ["EV-00000001", "EV-00000002"]
    authority_ir = compile_execution_fragment_authority(
        causal_chain={
            "core_goal": "Preserve event ownership.",
            "question_chain": [{
                "event_ids": event_ids,
                "phases": [{
                    "event_id": event_ids[0],
                    "state": "first-only",
                    "future_consequence": {
                        "event_id": event_ids[1],
                        "state": "second-only",
                        "required_actions": ["reveal only in segment two"],
                    },
                }],
            }],
            "relationship_arc": [],
        },
        timeline_events=[], presentation_order=event_ids,
        viewpoint_rule="third limited",
    )
    first = json.dumps(project_execution_fragment_authority(
        authority_ir=authority_ir, owned_event_ids=[event_ids[0]],
        segment=1, segment_count=2,
    ), ensure_ascii=False)
    second = json.dumps(project_execution_fragment_authority(
        authority_ir=authority_ir, owned_event_ids=[event_ids[1]],
        segment=2, segment_count=2,
    ), ensure_ascii=False)

    assert "first-only" in first
    assert "second-only" not in first
    assert event_ids[1] not in first
    assert "second-only" in second
    assert "reveal only in segment two" in second
