import copy
import hashlib

import pytest

from novel_flywheel.prose_policy import ProseValidationPolicy
from novel_flywheel.revision import (
    assess_polish_candidate,
    align_revision_plan_targets,
    check_revision_constraints,
    check_source_local_constraints,
    compact_polish_findings,
    compact_review,
    filter_polish_findings_for_segment,
    apply_patch_group,
    normalize_revision_plan,
    normalize_chinese_prose,
    normalize_repair_contract,
    repair_mechanical_text,
    remove_consecutive_duplicate_blocks,
    segment_map,
)


def test_mechanical_repairs_leave_ambiguous_quotes_and_report_them() -> None:
    result = repair_mechanical_text('他说："门开了。\n她没有回答。')
    assert result["text"] == '他说："门开了。\n她没有回答。'
    assert result["applied"] == []
    assert result["blocked"][0]["code"] == "unpaired_quote"


def test_mechanical_repairs_apply_only_the_explicit_whitelist() -> None:
    result = repair_mechanical_text(
        '他说："门开了。"\n她 点头！！！\x00\n\n甲。\n\n乙。\n\n甲。\n\n乙。'
    )

    assert result["text"] == '他说：“门开了。”\n她点头！\n\n甲。\n\n乙。'
    assert [item["code"] for item in result["applied"]] == [
        "ascii_dialogue_quotes",
        "cjk_spacing",
        "duplicate_punctuation",
        "c0_control",
        "consecutive_duplicate_blocks",
    ]
    assert all(item["label"] for item in result["applied"])


def test_mechanical_repairs_report_truncated_sentences_without_rewriting() -> None:
    result = repair_mechanical_text("他推开门")

    assert result["text"] == "他推开门"
    assert result["applied"] == []
    assert result["blocked"] == [{"code": "truncated_sentence", "label": "疑似句子截断"}]


def test_patch_group_rolls_back_when_second_anchor_is_not_unique() -> None:
    source = "银锁第一次出现。\n\n证人看见银锁。\n\n证人看见银锁。"
    group = {
        "group_id": "issue-lock",
        "issue_ids": ["issue-lock"],
        "patches": [
            {"operation": "replace", "old_text": "银锁第一次出现。", "new_text": "父亲交出银锁。"},
            {"operation": "replace", "old_text": "证人看见银锁。", "new_text": "民警登记了银锁。"},
        ],
    }
    result = apply_patch_group(source, group, hashlib.sha256(source.encode()).hexdigest())
    assert result["accepted"] is False
    assert result["text"] == source
    assert result["failures"] == [{"patch": 2, "code": "anchor_not_unique"}]


def test_normalize_repair_contract_validates_and_preserves_review_fields() -> None:
    manuscript = "父亲交出银锁。"
    value = {
        "manuscript_hash": hashlib.sha256(manuscript.encode()).hexdigest(),
        "required_text": ["银锁"],
        "forbidden_text": ["铜锁"],
        "related_entities": ["entity-father"],
        "related_events": ["event-handover"],
        "related_relations": ["relation-owns"],
        "target_word_delta": 12,
        "requires_full_review": True,
        "groups": [{
            "group_id": "issue-lock",
            "issue_ids": ["issue-lock"],
            "kind": "semantic",
            "requires_user_confirmation": True,
            "patches": [{
                "operation": "replace",
                "old_text": "父亲交出银锁。",
                "new_text": "父亲当面交出银锁。",
            }],
        }],
    }

    normalized = normalize_repair_contract(value, manuscript, {"issue-lock"})

    for key in (
        "required_text", "forbidden_text", "related_entities", "related_events",
        "related_relations", "target_word_delta", "requires_full_review",
    ):
        assert normalized[key] == value[key]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"manuscript_hash": "stale"}, "manuscript_hash"),
        ({"groups": []}, "group"),
        ({"groups.0.patches": []}, "patch"),
        ({"groups.0.patches.0.operation": "delete"}, "operation"),
        ({"groups.0.patches.0.old_text": "不存在"}, "old_text"),
        ({"groups.0.issue_ids": ["issue-unknown"]}, "issue"),
        ({"groups.0.issue_ids": ["issue-lock", "issue-other"]}, "unrelated"),
        ({"groups.0.requires_user_confirmation": False}, "confirmation"),
    ],
)
def test_normalize_repair_contract_rejects_unsafe_contracts(
    mutation: dict[str, object], message: str,
) -> None:
    manuscript = "父亲交出银锁。"
    value = {
        "manuscript_hash": hashlib.sha256(manuscript.encode()).hexdigest(),
        "groups": [{
            "group_id": "issue-lock",
            "issue_ids": ["issue-lock"],
            "kind": "semantic",
            "requires_user_confirmation": True,
            "patches": [{
                "operation": "replace",
                "old_text": manuscript,
                "new_text": "父亲当面交出银锁。",
            }],
        }],
    }
    for path, replacement in mutation.items():
        target = value
        parts = path.split(".")
        for part in parts[:-1]:
            target = target[int(part)] if part.isdigit() else target[part]
        target[parts[-1]] = replacement

    with pytest.raises(ValueError, match=message):
        normalize_repair_contract(value, manuscript, {"issue-lock", "issue-other"})


def test_normalize_repair_contract_rejects_unconfirmed_mechanical_disguise() -> None:
    manuscript = "父亲交出银锁。"
    value = {
        "manuscript_hash": hashlib.sha256(manuscript.encode()).hexdigest(),
        "groups": [{
            "group_id": "issue-lock",
            "issue_ids": ["issue-lock"],
            "kind": "mechanical",
            "requires_user_confirmation": False,
            "patches": [{
                "operation": "replace",
                "old_text": manuscript,
                "new_text": "父亲从未交出银锁。",
            }],
        }],
    }

    with pytest.raises(ValueError, match="confirmation"):
        normalize_repair_contract(value, manuscript, {"issue-lock"})


def test_normalize_repair_contract_rejects_unknown_group_kind() -> None:
    manuscript = "父亲交出银锁。"
    value = {
        "manuscript_hash": hashlib.sha256(manuscript.encode()).hexdigest(),
        "groups": [{
            "group_id": "issue-lock",
            "issue_ids": ["issue-lock"],
            "kind": "automatic",
            "requires_user_confirmation": True,
            "patches": [{
                "operation": "replace",
                "old_text": manuscript,
                "new_text": "父亲当面交出银锁。",
            }],
        }],
    }

    with pytest.raises(ValueError, match="kind"):
        normalize_repair_contract(value, manuscript, {"issue-lock"})


def test_compact_review_keeps_every_issue_without_arbitrary_truncation() -> None:
    review = {
        "dimensions": {"commercial": 60, "story": 50, "prose": 70},
        "score": 58,
        "hard_fail": True,
        "decision": "rewrite",
        "issues": [
            {"category": f"issue-{index}", "severity": "high",
             "evidence": f"evidence-{index}", "action": f"action-{index}"}
            for index in range(20)
        ],
    }

    brief = compact_review(review)

    assert len(brief["issues"]) == 20
    assert brief["issues"][-1]["action"] == "action-19"


def test_segment_map_includes_both_ends_of_every_segment() -> None:
    mapped = segment_map(["A" * 100 + "middle" + "B" * 100, "second"], width=20)

    assert mapped[0] == {"segment": 1, "scene_id": "scene-01", "characters": 206,
                         "opening": "A" * 20, "ending": "B" * 20}
    assert mapped[1]["scene_id"] == "scene-02"
    assert mapped[1]["opening"] == "second"
    assert mapped[1]["ending"] == "second"


def test_segment_map_carries_event_ids_and_handoff_when_available() -> None:
    mapped = segment_map(
        ["正文"], event_assignments=[{
            "segment": 1, "event_ids": ["EV-12345678"], "handoff": "主角已经知道真相。",
        }],
    )

    assert mapped[0]["event_ids"] == ["EV-12345678"]
    assert mapped[0]["handoff"] == "主角已经知道真相。"


def test_normalize_revision_plan_rejects_unknown_segments_and_keeps_valid_tasks() -> None:
    plan = normalize_revision_plan({
        "global_facts": ["The ceremony is a wedding."],
        "checks": [
            {"kind": "forbidden_text", "value": "engagement banquet"},
            {"kind": "required_text", "value": "wedding"},
        ],
        "tasks": [
            {"segments": [1, 3, 99], "instruction": "Unify the ceremony."},
            {"segments": [], "instruction": "Ignore this."},
        ],
    }, segment_count=3)

    assert plan["tasks"] == [{"segments": [1, 3], "instruction": "Unify the ceremony."}]
    assert plan["target_segments"] == [1, 3]


def test_normalize_revision_plan_accepts_common_segment_labels_and_rejects_booleans() -> None:
    plan = normalize_revision_plan({
        "tasks": [{
            "segments": [
                "1", "第2段", "第三段", "段 4", "Segment 5", "scene-06", "场景7",
                True, "第99段",
            ],
            "instruction": "修正这些分段。",
        }],
    }, segment_count=7)

    assert plan["tasks"] == [{
        "segments": [1, 2, 3, 4, 5, 6, 7], "instruction": "修正这些分段。",
    }]
    assert plan["target_segments"] == [1, 2, 3, 4, 5, 6, 7]


def test_normalize_revision_plan_keeps_issue_links_on_tasks() -> None:
    plan = normalize_revision_plan({
        "tasks": [{
            "segments": [2], "instruction": "回应开篇承诺。",
            "issue_ids": ["issue-ab12", "", 3, "issue-ab12"],
        }],
    }, segment_count=3)

    assert plan["tasks"][0]["issue_ids"] == ["issue-ab12"]


def test_normalize_revision_plan_drops_mechanical_quote_checks() -> None:
    plan = normalize_revision_plan({
        "checks": [
            {"kind": "forbidden_text", "value": '"'},
            {"kind": "forbidden_text", "value": "forbidden event"},
        ],
        "tasks": [{"segments": [1], "instruction": "Repair the scene."}],
    }, segment_count=1)

    assert plan["checks"] == [{"kind": "forbidden_text", "value": "forbidden event"}]


def test_normalize_chinese_prose_repairs_safe_typography_only() -> None:
    text = (
        '他说："门我来修。"\n'
        "她 慢慢 点头！！！\n"
        "https://example.com/a  b\n"
        "<!-- NOVEL_FLYWHEEL_SEGMENT -->"
    )

    normalized, repairs = normalize_chinese_prose(text)

    assert normalized == (
        "他说：“门我来修。”\n"
        "她慢慢点头！\n"
        "https://example.com/a  b\n"
        "<!-- NOVEL_FLYWHEEL_SEGMENT -->"
    )
    assert repairs == ["ascii_dialogue_quotes", "cjk_spacing", "duplicate_punctuation"]


def test_normalize_chinese_prose_keeps_legacy_scope() -> None:
    text = "甲。\x00\n\n乙。\n\n甲。\n\n乙。"

    normalized, repairs = normalize_chinese_prose(text)

    assert normalized == text
    assert repairs == []


def test_polish_candidate_rejects_process_text_and_missing_locked_literal() -> None:
    rejected = assess_polish_candidate(
        "陈东推开门，叫了一声小雨。", "以下是润色版本：他推开门。",
        required_literals=["陈东", "小雨"],
    )

    assert rejected["accepted"] is False
    assert "production_text" in rejected["reasons"]
    assert "missing_literal:陈东" in rejected["reasons"]


def test_polish_candidate_accepts_local_improvement() -> None:
    accepted = assess_polish_candidate(
        "陈东轻轻地推开门。", "陈东推开门，门轴蹭过地面。",
        required_literals=["陈东"],
    )

    assert accepted["accepted"] is True
    assert accepted["reasons"] == []


def test_polish_candidate_rejects_short_sentence_rhythm_regression() -> None:
    source = "A measured sentence carries the action forward with enough context. " * 8
    candidate = (
        "Door opened. He entered. Light moved. Rain fell. She stopped. "
        "A measured sentence carries the action forward with enough context. " * 6
    )

    rejected = assess_polish_candidate(source, candidate)

    assert rejected["accepted"] is False
    assert "sentence_rhythm_regression" in rejected["reasons"]


def test_polish_candidate_collapses_related_rhythm_evidence_into_one_family() -> None:
    source = "A measured sentence carries the action forward with enough context. " * 8
    candidate = (
        "Door opened. He entered. Light moved. Rain fell. She stopped. "
        "A measured sentence carries the action forward with enough context. " * 6
    )

    result = assess_polish_candidate(source, candidate)

    assert result["disposition"] == "targeted_repair"
    assert result["signal_families"] == ["rhythm"]
    assert [item["family"] for item in result["soft_signals"]] == ["rhythm"]
    assert not ({"style_regression", "sentence_rhythm_regression"} <= set(result["reasons"]))


def test_project_style_can_authorize_local_short_rhythm_but_not_hard_loss() -> None:
    source = "A measured sentence carries the action forward with enough context. " * 8
    candidate = (
        "Door opened. He entered. Light moved. Rain fell. She stopped. "
        "A measured sentence carries the action forward with enough context. " * 6
    )
    policy = ProseValidationPolicy(
        source_ids=("prose_baseline:2",),
        authorized_short_beats=frozenset({"information_reveal"}),
    )

    allowed = assess_polish_candidate(
        source, candidate, policy=policy,
        narrative_context={"reveals": ["the hidden identity is exposed"]},
    )
    rejected = assess_polish_candidate(
        "She leaves with the brass key.", "She leaves.",
        required_literals=["brass key"], policy=policy,
        narrative_context={"reveals": ["the hidden identity is exposed"]},
    )

    assert allowed["accepted"] is True
    assert allowed["disposition"] == "pass_with_style_allowance"
    assert allowed["reasons"] == []
    assert allowed["style_allowances"][0]["policy_sources"] == ["prose_baseline:2"]
    assert rejected["accepted"] is False
    assert rejected["disposition"] == "reject"
    assert "missing_literal:brass key" in rejected["hard_reasons"]


@pytest.mark.parametrize(("genre", "prose_kind"), [
    ("古言宅斗", "authorized_short_reveal"),
    ("现代情感", "dialogue_dense"),
    ("悬疑", "authorized_suspense_turn"),
    ("科幻", "long_exposition"),
    ("玄幻", "scene_transition"),
    ("梦境", "ambiguous_location"),
    ("虚拟世界", "knowledge_change"),
])
def test_genre_name_does_not_change_structural_style_decision(
    genre: str, prose_kind: str,
) -> None:
    measured = "A measured sentence carries the action forward with enough context. " * 8
    fixtures = {
        "authorized_short_reveal": (
            measured,
            "Door opened. Name matched. Debt was real. She understood. " + measured * 6,
            ProseValidationPolicy(
                source_ids=("style-profile",),
                authorized_short_beats=frozenset({"information_reveal"}),
            ),
            {"reveals": ["identity"]},
        ),
        "dialogue_dense": (
            "\n\n".join(f'“Turn {index} carries distinct subtext.”' for index in range(5)),
            "\n\n".join(f'“Turn {index} carries distinct subtext.”' for index in range(5)),
            ProseValidationPolicy(),
            {},
        ),
        "authorized_suspense_turn": (
            measured,
            "Lock moved. Footsteps stopped. Light vanished. The promise returned. "
            + measured * 6,
            ProseValidationPolicy(
                source_ids=("prose_baseline:1",),
                authorized_short_beats=frozenset({"suspense_turn"}),
            ),
            {"payoffs": [{"id": "promise-1"}]},
        ),
        "long_exposition": (measured, measured, ProseValidationPolicy(), {}),
        "scene_transition": (
            "Three days later, she crossed the courtyard and entered the archive. " * 5,
            "Three days later, she crossed the courtyard and entered the archive. " * 5,
            ProseValidationPolicy(),
            {"scenes": [{"location": "archive"}]},
        ),
        "ambiguous_location": (
            "She could not tell whether the corridor belonged to memory or sleep. " * 5,
            "She could not tell whether the corridor belonged to memory or sleep. " * 5,
            ProseValidationPolicy(),
            {"location": "unresolved"},
        ),
        "knowledge_change": (
            measured, measured, ProseValidationPolicy(),
            {"knowledge_changed": True},
        ),
    }
    source, candidate, policy, narrative = fixtures[prose_kind]

    themed = assess_polish_candidate(
        source, candidate, policy=policy,
        narrative_context={**narrative, "genre": genre},
    )
    control = assess_polish_candidate(
        source, candidate, policy=policy,
        narrative_context={**narrative, "genre": "未指定"},
    )

    assert themed["disposition"] == control["disposition"]
    assert themed["signal_families"] == control["signal_families"]
    assert themed["style_allowances"] == control["style_allowances"]


def test_small_single_metric_shift_is_advisory_not_a_repair_target() -> None:
    source = "A measured sentence carries enough context. " * 8
    candidate = "Stop. Wait. " + source

    result = assess_polish_candidate(source, candidate)

    assert result["accepted"] is True
    assert result["disposition"] == "pass"
    assert result["signal_families"] == []


def test_history_metrics_raise_boundary_without_weakening_source_integrity() -> None:
    source = "A measured sentence carries enough context. " * 8
    candidate = "Stop. Wait. Listen. " + source
    history = [{"short_sentence_ratio": 0.30} for _ in range(5)]

    result = assess_polish_candidate(
        source, candidate, history_metrics=history,
    )

    assert result["accepted"] is True
    assert result["baseline"]["history_count"] == 5
    assert result["baseline"]["short_sentence_ratio_boundary"] == 0.4


def test_polish_candidate_must_improve_existing_short_sentence_run() -> None:
    source = (
        "她听清了对方的话。靖安侯府。三小姐。林知晚。病了很久。"
        "这些词她都听得懂，组合起来却像另一个世界的语言。"
    )

    rejected = assess_polish_candidate(source, source)

    assert rejected["accepted"] is False
    assert "sentence_rhythm_not_improved" in rejected["reasons"]


def test_polish_candidate_accepts_meaningful_relative_rhythm_improvement() -> None:
    source = "门开了。他进来。灯亮了。雨停了。风起了。她回头。长廊尽头传来脚步声。"
    candidate = "门开后，他迎着亮起的灯光走进来。雨停风起时，她听见长廊尽头传来脚步声。"

    result = assess_polish_candidate(source, candidate)

    assert "sentence_rhythm_not_improved" not in result["reasons"]


def test_polish_candidate_must_improve_timestamp_scene_fragment() -> None:
    source = (
        "林知晚发出文档，看了眼时间——二十三点四十七分。"
        "会议室白板上还留着下午画的流程图。"
    )

    rejected = assess_polish_candidate(source, source)

    assert rejected["accepted"] is False
    assert "timestamp_scene_fragment_not_improved" in rejected["reasons"]


def test_polish_candidate_must_break_up_existing_dialogue_ping_pong() -> None:
    source = (
        "“你没走。”他说。\n\n“我走了你就死了。”\n\n"
        "“你也可能死。”\n\n“知道了也不行。”她说。"
    )

    rejected = assess_polish_candidate(source, source)

    assert rejected["accepted"] is False
    assert "dialogue_ping_pong_not_improved" in rejected["reasons"]


def test_normalize_revision_plan_requires_at_least_one_actionable_task() -> None:
    with pytest.raises(ValueError, match="actionable task"):
        normalize_revision_plan({"tasks": []}, segment_count=3)


def test_structural_polish_can_expand_within_explicit_bounds() -> None:
    source = "A" * 1000
    candidate = "B" * 1700

    assert assess_polish_candidate(source, candidate)["accepted"] is False
    structural = assess_polish_candidate(
        source, candidate, minimum_ratio=0.6, maximum_ratio=1.8,
    )

    assert structural["accepted"] is True
    assert structural["length_bounds"] == {"minimum_ratio": 0.6, "maximum_ratio": 1.8}


def test_revision_targets_follow_actual_forbidden_text_location() -> None:
    plan = {
        "global_facts": [],
        "checks": [{"kind": "forbidden_text", "value": "Lin crouched"}],
        "tasks": [
            {"segments": [8], "instruction": "Replace 'Lin crouched' with the full name."},
            {"segments": [5], "instruction": "Repair the retired employee reference."},
        ],
        "target_segments": [5, 8],
    }

    aligned, corrections = align_revision_plan_targets(
        plan, ["scene one", "Lin crouched in darkness", "scene three"] + ["other"] * 5,
    )

    assert aligned["tasks"][0]["segments"] == [2]
    assert aligned["target_segments"] == [2, 5]
    assert corrections == [{
        "value": "Lin crouched", "planned_segments": [8], "actual_segments": [2],
    }]


def test_structural_revision_plan_limits_targets_to_forty_percent() -> None:
    with pytest.raises(ValueError, match="40%"):
        normalize_revision_plan({
            "checks": [{"kind": "forbidden_text", "value": "wrong fact"}],
            "tasks": [{"segments": [1, 2, 3], "instruction": "Rewrite everything."}],
        }, segment_count=5, max_target_ratio=0.4, require_checks=True)


def test_structural_revision_plan_defers_targets_beyond_current_batch() -> None:
    plan = normalize_revision_plan({
        "checks": [{"kind": "forbidden_text", "value": "wrong fact"}],
        "tasks": [
            {"segments": [1], "instruction": "Repair the opening."},
            {"segments": [4], "instruction": "Repair the ending."},
            {"segments": [2], "instruction": "Repair the investigation."},
        ],
    }, segment_count=4, max_target_ratio=0.4, require_checks=True,
       defer_excess_targets=True)

    assert plan["target_segments"] == [1, 4]
    assert plan["deferred_segments"] == [2]
    assert [task["segments"] for task in plan["tasks"]] == [[1], [4]]
    assert [task["segments"] for task in plan["deferred_tasks"]] == [[2]]


def test_structural_revision_plan_requires_deterministic_checks() -> None:
    with pytest.raises(ValueError, match="deterministic check"):
        normalize_revision_plan({
            "checks": [],
            "tasks": [{"segments": [2], "instruction": "Repair the contradiction."}],
        }, segment_count=5, max_target_ratio=0.4, require_checks=True)


def test_remove_consecutive_duplicate_blocks_keeps_single_copy() -> None:
    text = "Opening.\n\nClimax A.\n\nClimax B.\n\nClimax A.\n\nClimax B.\n\nEnding."

    cleaned, removals = remove_consecutive_duplicate_blocks(text)

    assert cleaned == "Opening.\n\nClimax A.\n\nClimax B.\n\nEnding."
    assert removals == 1


def test_revision_checks_report_required_and_forbidden_text() -> None:
    failures = check_revision_constraints("This is the wedding.", {
        "checks": [
            {"kind": "required_text", "value": "lawyer escrow"},
            {"kind": "forbidden_text", "value": "engagement banquet"},
            {"kind": "forbidden_text", "value": "wedding"},
        ],
    })

    assert failures == [
        "required text missing: lawyer escrow",
        "forbidden text remains: wedding",
    ]


def test_source_local_constraints_only_require_relevant_forbidden_text_removal() -> None:
    plan = {"checks": [
        {"kind": "forbidden_text", "value": "remove here"},
        {"kind": "forbidden_text", "value": "belongs elsewhere"},
    ]}

    assert check_source_local_constraints(
        "keep remove here", "keep remove here", plan,
    ) == ["forbidden text remains: remove here"]
    assert check_source_local_constraints(
        "keep remove here", "keep", plan,
    ) == []


def test_polish_findings_prioritize_critical_issues_and_bound_evidence() -> None:
    findings = {
        "editorial": {
            "issues": [
                {"category": f"low-{index}", "severity": "low",
                 "evidence": "minor", "action": "Minor polish."}
                for index in range(12)
            ] + [{
                "category": "continuity", "severity": "critical",
                "evidence": "x" * 1000, "action": "Unify wedding timeline.",
            }],
        },
        "target_reader": {"reader_signals": {"would_pay": False}, "issues": []},
    }

    compacted = compact_polish_findings(findings, max_issues=8)

    assert compacted["issues"][0]["category"] == "continuity"
    assert len(compacted["issues"]) == 8
    assert len(compacted["issues"][0]["evidence"]) == 280
    assert compacted["reader_signals"] == {"would_pay": False}


def test_polish_findings_are_limited_to_the_current_segment_and_one_global_issue() -> None:
    compacted = {
        "issues": [
            {"category": "continuity", "severity": "high", "evidence": "她把铜钥匙藏进袖口。",
             "action": "交代铜钥匙后来去了哪里。"},
            {"category": "continuity", "severity": "low", "evidence": "码头的船已经离岸。",
             "action": "修正码头的时间。"},
            {"category": "story_structure", "severity": "critical", "evidence": "",
             "action": "整体因果链需要清楚。"},
            {"category": "overall", "severity": "high", "evidence": "",
             "action": "全文节奏需要调整。"},
        ],
        "reader_signals": {"would_pay": True},
    }
    original = copy.deepcopy(compacted)

    result = filter_polish_findings_for_segment(
        compacted, "她把铜钥匙藏进袖口，然后推门离开。", max_issues=4, max_global=1,
    )

    assert [item["action"] for item in result["issues"]] == [
        "交代铜钥匙后来去了哪里。", "整体因果链需要清楚。",
    ]
    assert result["reader_signals"] == {"would_pay": True}
    assert compacted == original
