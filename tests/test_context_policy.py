import pytest

from novel_flywheel import context_policy
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


def authority_api():
    required = (
        "PolishAuthorityPacket", "authority_packet_sha256",
        "build_polish_authority_packet", "classify_input_pressure",
        "render_polish_authority_packet",
    )
    missing = [name for name in required if not hasattr(context_policy, name)]
    assert not missing, f"missing authority API: {missing}"
    return context_policy


def build_authority_fixture():
    module = authority_api()
    return module.build_polish_authority_packet(
        source="当前完整源段。",
        event_ids=["EV-00000001"],
        causal_goal="查明钥匙来源",
        previous_exit="她已经知道账本存在。",
        next_entry="下一段才能打开密室。",
        character_state={"花穗": {"knowledge": "不知道密室位置"}},
        locked_facts=["钥匙不能丢失", "确认结局：花穗独自离开"],
        ending_constraints=["确认结局"],
        promises=["伏笔必须兑现"],
        narrative_state={"location": "沈府后院"},
        style_rules=["信息揭示时允许短句"],
        protected_passages=[{"id": "lock-1", "text": "不能改写的原句"}],
        allowed_scope={"segment": 2, "minimum_characters": 300, "maximum_characters": 700},
    )


def test_authority_render_keeps_every_required_field_without_slicing() -> None:
    module = authority_api()
    packet = build_authority_fixture()

    rendered = module.render_polish_authority_packet(packet)

    for expected in (
        "当前完整源段。", "EV-00000001", "查明钥匙来源",
        "她已经知道账本存在。", "下一段才能打开密室。",
        "不知道密室位置", "钥匙不能丢失", "确认结局",
        "伏笔必须兑现", "沈府后院", "信息揭示时允许短句", "不能改写的原句",
    ):
        assert expected in rendered
    assert rendered.rstrip().endswith("当前完整源段。")


def test_authority_hash_changes_with_story_truth_but_not_advisory_findings() -> None:
    module = authority_api()
    packet = build_authority_fixture()
    changed = module.build_polish_authority_packet(
        **{**packet.to_dict(), "previous_exit": "她还不知道账本存在。"},
    )

    assert module.authority_packet_sha256(packet) != module.authority_packet_sha256(changed)
    assert module.authority_packet_sha256(packet) == module.authority_packet_sha256(packet)
    assert "可删除的普通建议" in module.render_polish_authority_packet(
        packet, advisory={"notes": ["可删除的普通建议"]},
    )


@pytest.mark.parametrize(("window", "full", "authority", "reserve", "expected"), [
    (None, 50_000, 30_000, 8_000, "full"),
    (20_000, 13_000, 9_000, 3_000, "compact"),
    (12_000, 9_000, 8_500, 3_000, "split"),
    (20_000, 8_000, 7_000, 3_000, "full"),
])
def test_input_pressure_never_guesses_an_unknown_window(
    window, full, authority, reserve, expected,
) -> None:
    module = authority_api()

    assert module.classify_input_pressure(
        full_input_tokens=full,
        authority_input_tokens=authority,
        output_reserve=reserve,
        context_window=window,
    ) == expected


@pytest.mark.parametrize(("failure", "expected"), [
    (RuntimeError("maximum context length exceeded"), "input_context_overflow"),
    (RuntimeError("HTTP 413 request too large"), "input_context_overflow"),
    ({"finish_reason": "max_tokens"}, "output_limit"),
    (RuntimeError("polish output incomplete (finish_reason=max_tokens)"), "output_limit"),
    (RuntimeError("ConnectError: connection reset"), "transport_interrupted"),
    (RuntimeError("polish output exceeds allowed maximum"), "normal_invalid_output"),
    (RuntimeError("missing_api_key: provider"), "provider_rejection"),
])
def test_model_failure_classification_is_conservative(failure, expected) -> None:
    assert context_policy.classify_model_failure(failure) == expected


def test_nested_route_failure_does_not_turn_transport_into_output_limit() -> None:
    class RoutesFailed(RuntimeError):
        def __init__(self):
            super().__init__("primary and fallback failed")
            self.primary_error = RuntimeError("ConnectError")
            self.fallback_error = RuntimeError("504 Gateway Timeout")

    assert context_policy.classify_model_failure(RoutesFailed()) == "transport_interrupted"


def test_nested_fatal_route_failure_wins_over_transient_route() -> None:
    class RoutesFailed(RuntimeError):
        def __init__(self):
            super().__init__("primary and fallback failed")
            self.primary_error = RuntimeError("provider_not_found: primary")
            self.fallback_error = RuntimeError("504 Gateway Timeout")

    assert context_policy.classify_model_failure(RoutesFailed()) == "provider_rejection"


def test_explicitly_suppressed_exception_context_does_not_poison_classification() -> None:
    try:
        raise RuntimeError("maximum context length exceeded")
    except RuntimeError:
        try:
            raise ValueError("invariant_shape") from None
        except ValueError as failure:
            assert failure.__suppress_context__ is True
            assert context_policy.classify_model_failure(
                failure,
            ) == "normal_invalid_output"


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
