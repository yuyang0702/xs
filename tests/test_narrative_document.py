import json
from pathlib import Path

import pytest

from novel_flywheel.narrative_document import parse_narrative_document
from novel_flywheel.planning_adaptation import (
    planning_adaptation_event_projection,
    planning_event_ids,
)


def test_production_continuation_stays_owned_by_preceding_event() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" /
         "planning_event_projection_continuation_93075987.json").read_text(
             encoding="utf-8",
         )
    )

    projected, candidates = planning_adaptation_event_projection(
        fixture["plan_segment"], fixture["segment"],
        fixture["requested_event_ids"],
    )

    assert fixture["required_excerpt"] in projected
    assert fixture["excluded_excerpt"] not in projected
    assert any(fixture["required_excerpt"] in value for value in candidates.values())


@pytest.mark.parametrize(("source", "expected"), [
    (
        "1. 事件（EV-AAAA0001）。主动作。\n\n"
        "2. 无编号事件ID的回应。\n\n3. 下一事件（EV-BBBB0002）。",
        "2. 无编号事件ID的回应。",
    ),
    (
        "事件 EV-AAAA0001 的主动作。\n\n这是紧随其后的完整回应。\n\n"
        "## 下一场\n\n事件 EV-BBBB0002。",
        "这是紧随其后的完整回应。",
    ),
    (
        "- 事件 EV-AAAA0001\n  - 角色行动\n  - 对方回应\n\n"
        "- 事件 EV-BBBB0002",
        "对方回应",
    ),
    (
        "> 事件 EV-AAAA0001 开始。\n\n> 回应仍属于同一事件。\n\n"
        "## 分隔\n\n事件 EV-BBBB0002。",
        "回应仍属于同一事件",
    ),
    (
        "**runtime packet**\n\n事件 EV-AAAA0001。\n\n"
        "补充承诺。\n\n### boundary\n\n事件 EV-BBBB0002。",
        "补充承诺。",
    ),
    (
        "<packet-view>\n\n事件 EV-AAAA0001。\n\n"
        "关系状态继续推进。\n\n## stop\n\n事件 EV-BBBB0002。",
        "关系状态继续推进。",
    ),
])
def test_event_projection_accepts_structurally_distinct_valid_topologies(
    source: str, expected: str,
) -> None:
    document = parse_narrative_document(
        source, event_id_extractor=planning_event_ids,
    )
    projected = document.project_events(["EV-AAAA0001"])

    assert expected in projected
    assert "EV-BBBB0002" not in projected


def test_fenced_example_never_inherits_narrative_ownership() -> None:
    source = (
        "事件 EV-AAAA0001。\n\n```markdown\n"
        "伪造事件 EV-AAAA0001 的模板。\n```\n\n## 下一场\n"
    )
    document = parse_narrative_document(
        source, event_id_extractor=planning_event_ids,
    )

    assert "伪造事件" not in document.project_events(["EV-AAAA0001"])


def test_heading_breaks_implicit_ownership_in_unknown_wrapper() -> None:
    source = "事件 EV-AAAA0001。\n\n## unknown-control\n\n不能安全猜测归属。"
    document = parse_narrative_document(
        source, event_id_extractor=planning_event_ids,
    )

    assert "不能安全猜测归属" not in document.project_events(["EV-AAAA0001"])
