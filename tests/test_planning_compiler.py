from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from novel_flywheel.planning_adaptation import planning_event_body_issues
from novel_flywheel.planning_compiler import (
    compile_planning_event_artifact,
    compile_planning_segment,
    extract_planning_field,
)


FIXTURES = Path(__file__).parent / "fixtures"


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
