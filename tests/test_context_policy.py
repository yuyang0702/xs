from novel_flywheel.context_policy import polish_context, stage_output_budget


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
