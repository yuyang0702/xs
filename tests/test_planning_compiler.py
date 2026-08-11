from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from novel_flywheel.planning_adaptation import planning_event_body_issues
from novel_flywheel.planning_compiler import (
    AdjacentHandoffIR,
    PlanningDocumentIR,
    PlanningDocumentExitTopologyIR,
    PlanningSegmentIR,
    TerminalClosureIR,
    compile_planning_event_artifact,
    compile_planning_segment,
    compile_planning_segment_exit_contracts,
    compile_planning_segment_ir,
    extract_planning_field,
    planning_document_exit_topology,
    planning_markdown_presentation_view,
    planning_ownership_topology,
    render_planning_segment_ir,
)


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_runtime_owned_markdown_heading_is_atomic_presentation(newline: str) -> None:
    original = PlanningSegmentIR(
        segment=1,
        heading="### Segment 1: terminal",
        event_ids=("EV-1234ABCD",),
        outline="Authoritative ending evidence.",
        opening="The final choice is ready.",
        event_body="The protagonist completes the final action.",
        handoff="## Ending beat\nThe cost is accepted while one clue stays open.",
        source_sha256="0" * 64,
    )
    rendered = render_planning_segment_ir(original).replace("\n", newline)

    compiled = compile_planning_segment(rendered)
    assert compiled.field("handoff") == original.handoff
    visible = planning_markdown_presentation_view(rendered)
    assert len(visible) == len(rendered)
    assert visible.count("\n") == rendered.count("\n")
    assert "## Ending beat" not in visible


def test_recorded_production_table_normalizes_then_reveals_ownership_stage() -> None:
    fixture = json.loads(
        (FIXTURES / "planning_field_table_4e79a0f4.json").read_text(
            encoding="utf-8",
        )
    )
    source = fixture["segment_markdown"]
    compiled = compile_planning_segment(source)

    assert compiled.source == source
    assert compiled.field("event_id").lower().startswith("ev-5bdfc942")
    assert "花穗被错认为" in compiled.field("event")
    assert all(compiled.field(role) for role in (
        "event_id", "outline", "opening", "event", "handoff",
    ))
    issues = planning_event_body_issues(source, fixture["expected_event_ids"])
    assert [item["code"] for item in issues] == ["event_body_missing"] * 7


@pytest.mark.parametrize(("source", "presentation"), (
    (
        "## 事件ID：EV-11111111\n"
        "## 大纲依据\n正式大纲 A\n"
        "## 段首承接\n入口状态\n"
        "## 本段事件\nEV-11111111 主角行动受阻后取得线索并改变局面。\n"
        "## 段末交接\n出口状态",
        "heading",
    ),
    (
        "**事件ID：** EV-11111111\n\n"
        "**大纲依据：** 正式大纲 A\n\n"
        "**段首承接：** 入口状态\n\n"
        "**本段事件：** EV-11111111 主角行动受阻后取得线索并改变局面。\n\n"
        "**段末交接：** 出口状态",
        "paragraph",
    ),
    (
        "- **事件ID：** EV-11111111\n"
        "- **大纲依据：** 正式大纲 A\n"
        "- **段首承接：** 入口状态\n"
        "- **本段事件：** EV-11111111 主角行动受阻后取得线索并改变局面。\n"
        "- **段末交接：** 出口状态",
        "list",
    ),
    (
        "**事件ID**\n\nEV-11111111\n\n"
        "**大纲依据**\n\n正式大纲 A\n\n"
        "**段首承接**\n\n入口状态\n\n"
        "**本段事件**\n\nEV-11111111 主角行动受阻后取得线索并改变局面。\n\n"
        "**段末交接**\n\n出口状态",
        "paragraph_owned",
    ),
))
def test_markdown_topologies_compile_to_the_same_closed_roles(
    source: str, presentation: str,
) -> None:
    compiled = compile_planning_segment(source)

    assert compiled.field("event_id") == "EV-11111111"
    assert compiled.field("outline") == "正式大纲 A"
    assert "主角行动受阻" in compiled.field("event")
    assert presentation in {
        item.presentation for item in compiled.values("event_id")
    }


def test_duplicate_conflicting_fields_are_ambiguous_instead_of_first_wins() -> None:
    source = "**事件ID：** EV-11111111\n\n**事件ID：** EV-22222222"
    compiled = compile_planning_segment(source)

    assert compiled.is_ambiguous("event_id") is True
    assert compiled.field("event_id") == ""


def test_fenced_examples_never_gain_machine_authority() -> None:
    source = (
        "```markdown\n**事件ID：** EV-DEADBEEF\n```\n\n"
        "**事件ID：** EV-11111111"
    )

    assert extract_planning_field(source, "event_id") == "EV-11111111"


def test_source_spans_hash_the_exact_normalized_source_slice() -> None:
    source = "| 字段 | 内容 |\n|---|---|\n| 事件ID | EV-11111111 |\n"
    field = compile_planning_segment(source).values("event_id")[0]
    exact = source[field.span.start:field.span.end]

    assert field.span.source_sha256 == hashlib.sha256(
        exact.encode("utf-8"),
    ).hexdigest()


@pytest.mark.parametrize("payload", (
    {
        "events": [
            {"event_id": "EV-11111111", "narrative": "主角采取行动，遭遇阻力后取得线索并改变局面。"},
            {"event_id": "EV-22222222", "narrative": "对手作出回应，秘密暴露后迫使双方改变下一步目标。"},
        ],
    },
    {
        "provider_result": {
            "unseen_container": {
                "EV-11111111": {"description": "主角采取行动，遭遇阻力后取得线索并改变局面。"},
                "EV-22222222": {"description": "对手作出回应，秘密暴露后迫使双方改变下一步目标。"},
            },
        },
    },
    {
        "tool_call": {
            "name": "planning_event_realizations",
            "arguments": {
                "another_wrapper": [
                    {"id": "EV-11111111", "realization": "主角采取行动，遭遇阻力后取得线索并改变局面。"},
                    {"id": "EV-22222222", "realization": "对手作出回应，秘密暴露后迫使双方改变下一步目标。"},
                ],
            },
        },
    },
    {
        "data": {
            "output": {
                "items": [
                    {"event_id": "EV-11111111", "summary": "The witness opens the archive, meets resistance, and preserves a decisive trace."},
                    {"event_id": "EV-22222222", "summary": "The rival answers the discovery, changes tactics, and creates the next pressure."},
                ],
            },
        },
    },
    {
        "unseen_provider_envelope": {
            "EV-11111111": "The courier crosses the storm, loses the easy route, and delivers the sealed warning.",
            "EV-22222222": "The captain verifies the warning, changes course, and exposes the hidden pursuit.",
        },
    },
    {
        "result": {
            "records": [
                {"id": "EV-11111111", "description": "The mage tests the ward, encounters a backlash, and identifies its true anchor."},
                {"id": "EV-22222222", "description": "The apprentice breaks the anchor, pays a cost, and changes the balance of power."},
            ],
        },
    },
))
def test_json_schema_and_tool_wrappers_compile_by_ordered_identity(payload: dict) -> None:
    compiled = compile_planning_event_artifact(
        payload,
        expected_event_ids=("EV-11111111", "EV-22222222"),
    )

    assert [item.event_id for item in compiled.events] == [
        "EV-11111111", "EV-22222222",
    ]
    assert all(item.source_sha256 for item in compiled.events)


@pytest.mark.parametrize("payload", (
    {
        "events": [{
            "event_id": "EV-11111111",
            "narrative": "主角采取行动，遭遇阻力后取得线索并改变局面。",
            "summary": "主角改为放弃行动，局面保持不变且线索丢失。",
        }],
    },
    {
        "events": [{
            "event_id": "EV-11111111",
            "narrative": "主角采取行动，遭遇阻力后取得线索并改变局面。",
            "provider_hint": "silently select a different route",
        }],
    },
    {
        "events": [{
            "event_id": "EV-11111111",
            "narrative": "主角采取行动，遭遇阻力后取得线索并改变局面。",
            "ｎａｒｒａｔｉｖｅ": "对手覆盖原叙事并撤销状态变化。",
        }],
    },
))
def test_planning_event_adapter_rejects_ambiguous_or_open_event_records(
    payload: dict,
) -> None:
    with pytest.raises(ValueError):
        compile_planning_event_artifact(
            payload, expected_event_ids=("EV-11111111",),
        )


@pytest.mark.parametrize("genre_body", (
    "## 出口状态\n侦探保留证据，再以错误账本逼迫嫌疑人改变口供。",
    "## 魔法代价\n术士承担反噬，仍把封印交给下一位守门人。",
    "## 舰桥交接\n领航员修正轨道，让失控飞船进入可救援窗口。",
    "## 朝堂结果\n御史公开账册，使两派不得不重新选择盟友。",
    "## 关系余波\n旧友承认隐瞒，二人带着新的边界继续合作。",
    "## 生存状态\n队长封住缺口，并把最后一份氧气留给伤员。",
))
def test_runtime_owned_ir_keeps_cross_genre_headings_as_opaque_prose(
    genre_body: str,
) -> None:
    original = PlanningSegmentIR(
        segment=1,
        heading="### Segment 1: executable plan",
        event_ids=("EV-11111111",),
        outline="The formal outline assigns one unchanged event.",
        opening="The protagonist enters with the prior state intact.",
        event_body=f"EV-11111111\n{genre_body}",
        handoff="The changed state is handed to the next segment.",
        source_sha256="a" * 64,
    )

    rendered = render_planning_segment_ir(original)
    compiled = compile_planning_segment_ir(rendered, segment=1)

    assert compiled.event_ids == original.event_ids
    assert compiled.event_body == original.event_body
    assert compiled.handoff == original.handoff
    assert genre_body in compiled.event_body


def test_ownership_topology_accepts_adjacent_sharing_and_rejects_reentry() -> None:
    def document(groups: list[tuple[str, ...]]) -> PlanningDocumentIR:
        return PlanningDocumentIR(
            plan_sha256="a" * 64,
            segments=tuple(
                PlanningSegmentIR(
                    segment=index, heading=f"segment {index}", event_ids=event_ids,
                    outline="outline", opening="opening", event_body="body",
                    handoff="handoff", source_sha256=f"{index:064x}",
                )
                for index, event_ids in enumerate(groups, 1)
            ),
        )

    topology = planning_ownership_topology(document([
        ("EV-11111111",), ("EV-11111111",), ("EV-22222222",),
    ]))
    assert topology.event_ids == ("EV-11111111", "EV-22222222")
    assert topology.segment_event_ids == (
        ("EV-11111111",), ("EV-11111111",), ("EV-22222222",),
    )

    with pytest.raises(ValueError, match="non_contiguous"):
        planning_ownership_topology(document([
            ("EV-11111111",), ("EV-22222222",), ("EV-11111111",),
        ]))
    with pytest.raises(ValueError, match="duplicate"):
        planning_ownership_topology(document([
            ("EV-11111111", "EV-11111111"),
        ]))


def _compiled_exit_segment(
    number: int,
    event_ids: tuple[str, ...],
    *,
    opening: str,
    handoff: str | None,
):
    source = (
        f"**事件ID：** {'、'.join(event_ids)}\n\n"
        f"**大纲依据：** 正式大纲第 {number} 段。\n\n"
        f"**段首承接：** {opening}\n\n"
        f"**本段事件：** {'；'.join(event_ids)} 的正式行动取得结果。"
    )
    if handoff is not None:
        source += f"\n\n**段末交接：** {handoff}"
    return compile_planning_segment(source)


def _formal_exit_events(count: int) -> list[dict]:
    return [
        {
            "id": f"EV-{index:08X}",
            "evidence": f"Formal evidence for event {index} establishes its result.",
        }
        for index in range(1, count + 1)
    ]


FORMAL_ENDING = {
    "surface_goal": "The declared external result is reached.",
    "inner_goal": "The protagonist accepts the resulting responsibility.",
    "cost": "The easy escape is permanently surrendered.",
    "final_image": "The protagonist crosses the threshold by choice.",
}


@pytest.mark.parametrize("count", (1, 2, 5))
def test_exit_topology_uses_handoffs_then_one_terminal_closure(count: int) -> None:
    events = _formal_exit_events(count)
    segments = [
        _compiled_exit_segment(
            index,
            (events[index - 1]["id"],),
            opening=f"Opening state {index}",
            handoff=(
                f"Established state {index} for opening {index + 1}"
                if index < count else None
            ),
        )
        for index in range(1, count + 1)
    ]

    topology = planning_document_exit_topology(
        segments, events, formal_ending=FORMAL_ENDING,
    )

    assert len(topology.exits) == count
    assert all(
        isinstance(exit_contract, AdjacentHandoffIR)
        for exit_contract in topology.exits[:-1]
    )
    terminal = topology.exits[-1]
    assert isinstance(terminal, TerminalClosureIR)
    assert terminal.formal_last_event_id == events[-1]["id"]
    assert terminal.retained_open_obligation_ids == ()
    assert "successor_segment" not in terminal.model_dump()


def test_adjacent_handoff_is_bound_to_exact_successor_opening() -> None:
    events = _formal_exit_events(2)
    segments = (
        _compiled_exit_segment(
            1, (events[0]["id"],), opening="Opening one",
            handoff="The witness carries the verified record forward.",
        ),
        _compiled_exit_segment(
            2, (events[1]["id"],), opening="Opening two", handoff=None,
        ),
    )
    topology = planning_document_exit_topology(
        segments, events, formal_ending=FORMAL_ENDING,
    )
    payload = topology.model_dump(mode="json")
    payload["exits"][0]["successor_opening_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="successor opening"):
        PlanningDocumentExitTopologyIR.model_validate(payload)


def test_non_terminal_segment_still_requires_non_empty_handoff() -> None:
    events = _formal_exit_events(2)
    segments = (
        _compiled_exit_segment(
            1, (events[0]["id"],), opening="Opening one", handoff=None,
        ),
        _compiled_exit_segment(
            2, (events[1]["id"],), opening="Opening two", handoff=None,
        ),
    )

    with pytest.raises(ValueError, match="non-terminal segment 1 is missing"):
        compile_planning_segment_exit_contracts(
            segments, events, formal_ending=FORMAL_ENDING,
        )


def test_non_terminal_segment_cannot_use_terminal_closure() -> None:
    events = _formal_exit_events(2)
    segments = (
        _compiled_exit_segment(
            1, (events[0]["id"],), opening="Opening one",
            handoff="State one is established.",
        ),
        _compiled_exit_segment(
            2, (events[1]["id"],), opening="Opening two", handoff=None,
        ),
    )
    topology = planning_document_exit_topology(
        segments, events, formal_ending=FORMAL_ENDING,
    )
    payload = topology.model_dump(mode="json")
    terminal = payload["exits"][-1]
    payload["exits"][0] = {
        **terminal,
        "segment": 1,
        "terminal_event_ids": [events[0]["id"]],
        "formal_last_event_id": events[0]["id"],
        "formal_last_event_evidence": events[0]["evidence"],
        "formal_last_event_evidence_sha256": hashlib.sha256(
            events[0]["evidence"].encode("utf-8"),
        ).hexdigest(),
        "source_segment_sha256": payload["segment_source_sha256"][0],
    }

    with pytest.raises(ValueError, match="non-terminal segment"):
        PlanningDocumentExitTopologyIR.model_validate(payload)


def test_terminal_segment_must_own_formal_last_event() -> None:
    events = _formal_exit_events(2)
    segments = (
        _compiled_exit_segment(
            1, (events[0]["id"],), opening="Opening one",
            handoff="State one is established.",
        ),
        _compiled_exit_segment(
            2, (events[0]["id"],), opening="Opening two", handoff=None,
        ),
    )

    with pytest.raises(ValueError, match="terminal segment does not own"):
        compile_planning_segment_exit_contracts(
            segments, events, formal_ending=FORMAL_ENDING,
        )


def test_terminal_closure_preserves_intentionally_open_obligations() -> None:
    events = _formal_exit_events(1)
    segment = _compiled_exit_segment(
        1, (events[0]["id"],), opening="The final action begins.", handoff=None,
    )

    topology = planning_document_exit_topology(
        (segment,), events, formal_ending=FORMAL_ENDING,
        retained_open_obligation_ids=("OBL-ANONYMOUS-LETTER",),
    )

    terminal = topology.exits[0]
    assert isinstance(terminal, TerminalClosureIR)
    assert terminal.retained_open_obligation_ids == ("OBL-ANONYMOUS-LETTER",)


def test_corrupt_runtime_owned_envelope_fails_closed_without_markdown_fallback() -> None:
    original = PlanningSegmentIR(
        segment=1,
        heading="### Segment 1: executable plan",
        event_ids=("EV-11111111",),
        outline="The formal outline assigns one unchanged event.",
        opening="The protagonist enters with the prior state intact.",
        event_body="EV-11111111\n## Exit state\nThe witness preserves the original evidence.",
        handoff="The changed state is handed to the next segment.",
        source_sha256="b" * 64,
    )
    rendered = render_planning_segment_ir(original)
    corrupted = rendered.replace(
        "The witness preserves the original evidence.",
        "The witness silently replaces the original evidence.",
        1,
    )

    compiled = compile_planning_segment(corrupted)

    assert compiled.protocol_issues
    assert compiled.field("event") == ""
    with pytest.raises(ValueError, match="content hash"):
        compile_planning_segment_ir(corrupted, segment=1)


@pytest.mark.parametrize("payload", (
    {"events": [
        {"event_id": "EV-22222222", "narrative": "对手先回应并改变下一步目标。"},
        {"event_id": "EV-11111111", "narrative": "主角后行动并取得关键线索。"},
    ]},
    {"events": [
        {"event_id": "EV-11111111", "narrative": "第一份互相冲突的事件正文。"},
        {"event_id": "EV-11111111", "narrative": "第二份互相冲突的事件正文。"},
    ]},
    {"events": [
        {"event_id": "EV-11111111", "narrative": "主角完成动作并取得结果。"},
    ], "patch": {"operation": "replace"}},
))
def test_structured_artifact_rejects_reorder_duplicate_and_unknown_control(
    payload: dict,
) -> None:
    with pytest.raises(ValueError):
        compile_planning_event_artifact(
            payload,
            expected_event_ids=("EV-11111111", "EV-22222222"),
        )


@given(
    newline=st.sampled_from(["\n", "\r\n"]),
    colon=st.sampled_from([":", "：", "﹕"]),
    label=st.sampled_from(["事件ID", "事件ＩＤ", "正式事件ID"]),
)
def test_unicode_and_newline_presentation_changes_do_not_rewrite_prose(
    newline: str, colon: str, label: str,
) -> None:
    prose = "主角说：这段自由文本ＡＢＣ必须原样保留。"
    source = newline.join((
        f"**{label}{colon}** EV-11111111",
        f"**本段事件{colon}** {prose}",
    ))
    compiled = compile_planning_segment(source)

    assert compiled.field("event_id") == "EV-11111111"
    assert prose in compiled.field("event")
    assert "ＡＢＣ" in compiled.field("event")
