from __future__ import annotations

from dataclasses import replace

import pytest

from novel_flywheel.context_packet import (
    build_stage_context_packet,
    context_packet_sha256,
    render_stage_context_packet,
    validate_rule_coverage,
)


def large_repeated_constraints() -> str:
    return "\n".join([
        "# Current Confirmed Outline",
        "- **视角**：第一人称（女主视角）",
        "- 确认结局：花穗选择留下并守护沈府。",
        "- 必须保持花穗不知道二十两已经提前支取。",
        *["- 普通背景说明，不属于当前正文硬规则。" for _ in range(900)],
        "- 必须保持花穗不知道二十两已经提前支取。",
    ])


def repeated_skill_prompt() -> str:
    return "\n".join([
        "# Chapter Writing",
        "- Never change established plot facts.",
        "- 必须保持第一人称叙述。",
        "## Examples",
        *["示例：这是一段不应发送到当前模型的长示例。" for _ in range(300)],
        "# Novel Writing",
        "- Never change established plot facts.",
        "- 每个角色必须遵守已经确认的认知边界。",
    ])


def build_packet(stage: str = "draft"):
    return build_stage_context_packet(
        stage=stage,
        current_contract={
            "task_id": "segment-01",
            "beat_ids": ["EV-8E4BBA17/01"],
            "entry_state": ["花穗仍在宴厅"],
            "exit_state": ["核实身份的人已经出发"],
            "prohibited_future_beat_ids": ["EV-8E4BBA17/02"],
        },
        constraints=large_repeated_constraints(),
        skill_prompt=repeated_skill_prompt(),
        explicit_invariants={
            "viewpoint": "第一人称（女主视角）",
            "confirmed_ending": "花穗选择留下并守护沈府。",
            "knowledge_boundary": "花穗不知道二十两已经提前支取。",
        },
        relevant_context="原始段落资料：沈老夫人派人去核实花穗身份。",
        global_skeleton="EV-8E4BBA17/01 后接 EV-8E4BBA17/02，结局为花穗留下。",
        advisory="建议级市场资料。" * 2000,
        output_reserve=8192,
        advisory_max_chars=800,
    )


def test_context_packet_keeps_mandatory_rules_once_and_drops_repeated_examples() -> None:
    packet = build_packet()

    rendered = render_stage_context_packet(packet)

    assert validate_rule_coverage(packet) == []
    assert rendered.count("第一人称（女主视角）") == 1
    assert rendered.count("花穗选择留下并守护沈府。") == 1
    assert rendered.count("花穗不知道二十两已经提前支取。") == 1
    assert rendered.count("Never change established plot facts.") == 1
    assert "不应发送到当前模型的长示例" not in rendered
    assert len(packet.advisory) <= 800
    assert packet.metrics["removed_duplicate_rules"] >= 2


@pytest.mark.parametrize(
    "stage", ["draft", "polish", "review", "revision_plan", "final_review"],
)
def test_every_prose_affecting_stage_keeps_story_invariants(stage: str) -> None:
    rendered = render_stage_context_packet(build_packet(stage))

    for required in (
        "第一人称（女主视角）",
        "花穗选择留下并守护沈府。",
        "花穗不知道二十两已经提前支取。",
        "EV-8E4BBA17/01",
        "花穗仍在宴厅",
        "核实身份的人已经出发",
        "EV-8E4BBA17/02",
    ):
        assert required in rendered


def test_missing_mandatory_rule_is_detected_before_provider_use() -> None:
    packet = build_packet()
    broken = replace(packet, mandatory_rules=packet.mandatory_rules[1:])

    issues = validate_rule_coverage(broken)

    assert issues == [{
        "code": "missing_mandatory_rule",
        "rule_id": packet.required_rule_ids[0],
        "message": "模型上下文缺少强制叙事规则",
    }]


def test_advisory_changes_do_not_change_context_authority_hash() -> None:
    packet = build_packet()
    changed = replace(packet, advisory="另一份建议，不属于叙事权威。")

    assert context_packet_sha256(packet) == context_packet_sha256(changed)


def test_context_metrics_report_each_layer_without_guessing_provider_capacity() -> None:
    packet = build_packet()

    assert packet.metrics["output_reserve_tokens"] == 8192
    assert packet.metrics["total_input_tokens"] > 0
    assert set(packet.metrics["layers"]) == {
        "current_contract",
        "mandatory_rules",
        "relevant_context",
        "global_skeleton",
        "advisory",
    }
    assert "context_window" not in packet.metrics
