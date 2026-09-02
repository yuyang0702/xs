from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from novel_flywheel.context_packet import (
    advisory_provenance,
    build_stage_context_packet,
    context_packet_sha256,
    extract_mandatory_rules,
    render_stage_context_packet,
    render_stage_system_context,
    validate_rule_coverage,
)


def test_temporal_before_after_rules_are_not_mistaken_for_examples() -> None:
    rules, _duplicates = extract_mandatory_rules(
        "Never reveal her identity before the climax.\n"
        "After the bell, the hero must leave the hall.",
        "",
        stage="draft",
    )

    assert [rule.text for rule in rules] == [
        "Never reveal her identity before the climax.",
        "After the bell, the hero must leave the hall.",
    ]


def test_explicit_invariant_deduplication_keeps_companion_rule_on_same_line() -> None:
    rules, _duplicates = extract_mandatory_rules(
        "Viewpoint: first person; Never reveal the witness before the ending.",
        "",
        stage="draft",
        explicit_invariants={"viewpoint": "first person"},
    )

    assert [rule.text for rule in rules] == [
        "viewpoint: first person",
        "Never reveal the witness before the ending.",
    ]


def test_unmarked_rules_inside_hard_rule_section_remain_mandatory() -> None:
    rules, _duplicates = extract_mandatory_rules(
        "# HARD RULES\nNarrate in first person.\nAlice is Bob's mother.\n"
        "# Optional Notes\nTry a brisk opening.",
        "",
        stage="draft",
    )

    assert [rule.text for rule in rules] == [
        "Narrate in first person.",
        "Alice is Bob's mother.",
    ]


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


def test_rendered_advisory_provenance_is_hash_only_and_exact() -> None:
    packet = build_packet()

    receipt = advisory_provenance(packet)

    assert receipt["schema"] == "RenderedAdvisoryProvenanceV1"
    assert receipt["final_rendered_advisory_chars"] == len(packet.advisory)
    assert receipt["final_rendered_advisory_sha256"] == hashlib.sha256(
        packet.advisory.encode("utf-8")
    ).hexdigest()
    assert receipt["advisory_truncation_occurred"] is True
    assert receipt["advisory_shedding_occurred"] is True
    assert receipt["advisory_omission_reasons"] == [
        "ADVISORY_MAX_CHARS", "PARAGRAPH_BOUNDARY_BUDGET",
    ]
    assert "rendered_text" not in receipt


@pytest.mark.parametrize(
    ("marker", "rule"),
    [
        ("保持", "应保持已经确认的时间线。"),
        ("应当", "角色应当遵守已确认的知识边界。"),
        ("preserve", "Preserve every confirmed causal dependency."),
    ],
)
def test_preservation_language_is_bound_as_mandatory(marker: str, rule: str) -> None:
    rules, _duplicates = extract_mandatory_rules(
        f"普通建议。\n{rule}",
        "",
        stage="review",
    )

    assert marker.casefold() in rules[0].text.casefold()
    assert [item.text for item in rules] == [rule]


def test_advisory_compaction_never_emits_a_partial_paragraph() -> None:
    first = "第一段完整建议。"
    second = "第二段也必须保持完整，不能从中间切断。"
    packet = build_stage_context_packet(
        stage="review",
        current_contract={"task_id": "review-01"},
        constraints="必须保持确认结局。",
        skill_prompt="",
        explicit_invariants=None,
        relevant_context="受保护的当前故事正文。",
        global_skeleton="受保护的全局故事骨架。",
        advisory=f"{first}\n\n{second}",
        advisory_max_chars=len(first) + 2 + len(second) - 1,
    )

    assert packet.advisory == first
    assert second not in packet.advisory
    assert packet.metrics["advisory_compaction"]["partial_paragraph_count"] == 0


def test_oversized_single_advisory_paragraph_is_omitted_not_sliced() -> None:
    advisory = "不可被切成半段的建议内容。" * 30
    packet = build_stage_context_packet(
        stage="review",
        current_contract={"task_id": "review-02"},
        constraints="必须保持确认结局。",
        skill_prompt="",
        explicit_invariants=None,
        relevant_context="受保护的当前故事正文。",
        global_skeleton="受保护的全局故事骨架。",
        advisory=advisory,
        advisory_max_chars=17,
    )

    assert packet.advisory == ""
    assert packet.metrics["advisory_truncation_occurred"] is True
    assert packet.metrics["advisory_compaction"]["omitted_paragraph_count"] == 1
    assert packet.metrics["advisory_compaction"]["partial_paragraph_count"] == 0


def test_explicit_advisory_shedding_preserves_source_identity_and_sizes() -> None:
    advisory = "第一段建议。\n\n第二段建议。"
    packet = build_stage_context_packet(
        stage="review",
        current_contract={"task_id": "review-shed-01"},
        constraints="必须保持确认结局。",
        skill_prompt="",
        explicit_invariants=None,
        relevant_context="受保护的当前故事正文。",
        global_skeleton="受保护的全局故事骨架。",
        advisory="",
        advisory_source=advisory,
        advisory_max_chars=0,
        advisory_shedding_occurred=True,
    )

    receipt = advisory_provenance(packet)
    assert packet.advisory == ""
    assert receipt["source_advisory_sha256"] == hashlib.sha256(
        advisory.encode("utf-8")
    ).hexdigest()
    assert receipt["source_advisory_chars"] == len(advisory)
    assert receipt["source_advisory_tokens"] > 0
    assert receipt["final_rendered_advisory_chars"] == 0
    assert receipt["final_rendered_advisory_tokens"] == 0
    assert receipt["advisory_shedding_occurred"] is True


def test_only_advisory_is_compacted_and_receipt_is_hash_only_verifiable() -> None:
    relevant_context = "受保护正文" * 200
    global_skeleton = "受保护骨架" * 200
    advisory = "私密建议甲。\n\n私密建议乙。"
    kwargs = dict(
        stage="final_review",
        current_contract={"task_id": "final-review-01", "required": ["A", "B"]},
        constraints="必须保持确认结局。",
        skill_prompt="Preserve all locked facts.",
        explicit_invariants=None,
        relevant_context=relevant_context,
        global_skeleton=global_skeleton,
        advisory=advisory,
        advisory_max_chars=1,
    )

    first = build_stage_context_packet(**kwargs)
    second = build_stage_context_packet(**kwargs)
    receipt = advisory_provenance(first)

    assert first.relevant_context == relevant_context
    assert first.global_skeleton == global_skeleton
    assert first.current_contract == kwargs["current_contract"]
    assert first.metrics["protected_layer_silent_truncation_count"] == 0
    assert first.metrics["layer_compaction_policy"] == {
        "current_contract": "PROTECTED_NO_COMPACTION",
        "mandatory_rules": "PROTECTED_NO_COMPACTION",
        "relevant_context": "PROTECTED_NO_COMPACTION",
        "global_skeleton": "PROTECTED_NO_COMPACTION",
        "advisory": "ADVISORY_COMPLETE_PARAGRAPH_PREFIX_V1",
    }
    assert receipt == advisory_provenance(second)
    assert advisory not in json.dumps(receipt, ensure_ascii=False)
    receipt_payload = {
        key: value for key, value in receipt.items()
        if key != "receipt_sha256"
    }
    assert receipt["receipt_sha256"] == hashlib.sha256(json.dumps(
        receipt_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def test_system_layer_keeps_authority_without_duplicating_current_user_payload() -> None:
    packet = build_packet()

    rendered = render_stage_system_context(packet)

    assert "MANDATORY_NARRATIVE_RULES" in rendered
    assert "GLOBAL_STORY_SKELETON" in rendered
    assert "CURRENT_USER_PAYLOAD_SHA256" in rendered
    assert packet.relevant_context not in rendered
