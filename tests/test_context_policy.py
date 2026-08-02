import pytest

from novel_flywheel.context_policy import (
    adaptive_output_budget,
    estimate_input_tokens,
    expanded_output_budget,
    invalid_terminal_output,
    next_retry_action,
    patch_output_budget,
    polish_context,
    revision_patch_context,
    schema_repair_prompt,
    stage_output_budget,
)


def test_input_token_estimator_is_conservative_for_chinese_and_ascii() -> None:
    estimated = estimate_input_tokens("中" * 100 + "a" * 400)

    assert 190 <= estimated <= 220


def test_polish_context_contains_global_position_without_repeating_manuscript() -> None:
    state = {
        "locked_facts": [{"key": "ending", "value": "She leaves alone."}],
        "confirmed_facts": [{"key": "injury", "value": "Her left hand is injured."}],
        "character_states": {"Lin": {"knowledge": "suspects fraud"}},
        "world_rules": ["No supernatural events"],
    }
    segment = "She hides the insurance document."

    prompt = polish_context(
        state=state,
        story_map=[{"segment": 1, "opening": "Arrival", "ending": "She waits"}],
        segment_index=1,
        segment_count=3,
        segment=segment,
        previous_tail="Previous boundary",
        next_head="Next boundary",
        findings='{"issues": []}',
        edit_rule="Preserve events.",
    )

    assert "AUTHORITATIVE STORY CONTEXT" in prompt
    assert "She leaves alone." in prompt
    assert "COMPACT FULL STORY MAP" in prompt
    assert "Previous boundary" in prompt
    assert "Next boundary" in prompt
    assert prompt.count(segment) == 1


def test_polish_context_caps_boundaries_and_state_size() -> None:
    prompt = polish_context(
        state={"locked_facts": ["x" * 5000]},
        story_map=[], segment_index=1, segment_count=1, segment="body",
        previous_tail="p" * 3000, next_head="n" * 3000,
        findings="f" * 8000, edit_rule="Preserve events.",
    )

    assert len(prompt) < 9000
    assert "p" * 800 in prompt
    assert "p" * 801 not in prompt
    assert "n" * 800 in prompt
    assert "n" * 801 not in prompt


def test_polish_output_budget_scales_with_segment_and_stays_bounded() -> None:
    assert stage_output_budget("polish", 500) == 2048
    assert 2048 < stage_output_budget("polish", 3000) < 8192
    assert stage_output_budget("polish", 20000) == 8192
    assert stage_output_budget("review", 100000) == 4096


def test_adaptive_budget_adds_quality_headroom_and_respects_physical_context() -> None:
    assert adaptive_output_budget(
        "draft", expected_output_characters=12000,
    ) > stage_output_budget("draft")
    assert adaptive_output_budget(
        "draft", expected_output_characters=12000,
        input_tokens=6000, context_window=14000,
    ) == 5952
    assert expanded_output_budget(
        4096, input_tokens=6000, context_window=14000,
    ) == 5952
    assert invalid_terminal_output({"finish_reason": "content_filter"}) is True
    assert invalid_terminal_output({"finish_reason": "max_tokens"}) is False


@pytest.mark.parametrize(
    ("failure_kind", "attempt", "current", "ceiling", "action", "next_limit"),
    [
        ("invalid_json", 1, 4096, 8192, "schema_repair", 4096),
        ("output_limit", 1, 4096, 8192, "retry_larger", 8192),
        ("output_limit", 1, 8192, 8192, "split", 8192),
        ("execution", 1, 4096, 8192, "fallback", 4096),
        ("execution", 2, 4096, 8192, "stop", 4096),
    ],
)
def test_retry_decision_matrix_never_repeats_an_unchanged_larger_limit(
    failure_kind, attempt, current, ceiling, action, next_limit,
) -> None:
    assert next_retry_action(
        failure_kind=failure_kind, attempt=attempt,
        current_limit=current, provider_limit=ceiling,
    ) == {"action": action, "next_limit": next_limit}


def test_patch_output_budget_is_bounded_by_allowed_size_and_provider_ceiling() -> None:
    assert patch_output_budget(400, 8192) < patch_output_budget(3000, 8192)
    assert patch_output_budget(20000, 4096) == 4096
    assert patch_output_budget(20000, 8192) == 8192


def test_revision_patch_context_contains_only_the_local_authorized_material() -> None:
    context = revision_patch_context(
        issue={"issue_id": "i1", "action": "补足交接"},
        target_paragraph="目标段", previous_paragraph="上一段", next_paragraph="下一段",
        evidence_summaries=["证据摘要"], seven_step_position="承：承诺升级",
        authoritative_facts=["银锁属于父亲"], protected_passages=["结尾不得改"],
        allowed_range={"start": 10, "end": 20}, word_target=300,
    )

    for expected in ("目标段", "上一段", "下一段", "证据摘要", "承：承诺升级", "银锁属于父亲", "结尾不得改", "300"):
        assert expected in context
    assert "UNRELATED FULL MANUSCRIPT" not in context
    assert "COMPACT FULL STORY MAP" not in context
    assert context.count("目标段") == 1


def test_invalid_json_retry_prompt_contains_only_malformed_output_and_schema() -> None:
    prompt = schema_repair_prompt('{"patches": [', "repair_patch_v1")

    assert '{"patches": [' in prompt
    assert "repair_patch_v1" in prompt
    assert "MANUSCRIPT SEGMENT" not in prompt
