from __future__ import annotations

from pathlib import Path

import pytest

from novel_flywheel.runtime_skill_profiles import (
    CHARACTER_HEAVY_CREATIVE_CORE_V2_RULE_TEXT,
    CHARACTER_HEAVY_CREATIVE_CORE_V3_RULE_TEXT,
    SkillLoadDecisionInputsV1,
    build_planning_v2_event_realization_profile_demand_aware,
    build_planning_v2_event_realization_profile_residual_v3,
    profile_contains_runtime_owned_responsibility,
    render_skill_context,
)


REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "vendor/novel-skills/source"
AUTHORITY_HASH = "a" * 64
AUTHORIZED_REWRITES = ("DRAFT_SCENE", "ANTI_TAXONOMY")
UNCHANGED_DEMANDS = (
    "world-heavy",
    "conflict-pacing-heavy",
    "setup-payoff-heavy",
    "mixed",
)


def _inputs() -> SkillLoadDecisionInputsV1:
    return SkillLoadDecisionInputsV1.model_validate({
        "authority_revision": 1,
        "authority_hash": AUTHORITY_HASH,
        "actor_refs_status": "present",
        "world_refs_status": "present",
        "actor_ref_count": 1,
        "world_ref_count": 1,
        "actor_refs": ("actor-fixture",),
        "location_refs": ("location-fixture",),
    })


def _rules(profile):
    return {rule.rule_id: rule for rule in (*profile.mandatory_rules, *profile.advisory_rules)}


def _render(profile):
    return render_skill_context(
        profile.advisory_rules,
        profile.mandatory_rules,
        profile.context_budget_policy,
    )


def test_v3_rewrites_exactly_the_two_sealed_sections_in_place():
    v2 = build_planning_v2_event_realization_profile_demand_aware(
        BUNDLE, _inputs(), pair_creative_demand_class="character-heavy",
    )
    v3 = build_planning_v2_event_realization_profile_residual_v3(
        BUNDLE, _inputs(), pair_creative_demand_class="character-heavy",
    )
    v2_rules = _rules(v2)
    v3_rules = _rules(v3)

    assert v2.profile_id == "RESTORED_SKILL_V2_CHARACTER_CORE_V2"
    assert v3.profile_id == "RESTORED_SKILL_V2_CHARACTER_CORE_V3"
    assert v2.included_rule_ids == v3.included_rule_ids
    assert tuple(
        rule_id for rule_id in v3.included_rule_ids
        if v2_rules[rule_id] != v3_rules[rule_id]
    ) == AUTHORIZED_REWRITES
    for rule_id in AUTHORIZED_REWRITES:
        old_payload = v2_rules[rule_id].model_dump(mode="json")
        new_payload = v3_rules[rule_id].model_dump(mode="json")
        assert {key: value for key, value in old_payload.items() if key != "text"} == {
            key: value for key, value in new_payload.items() if key != "text"
        }
        assert old_payload["text"] == CHARACTER_HEAVY_CREATIVE_CORE_V2_RULE_TEXT[rule_id]
        assert new_payload["text"] == CHARACTER_HEAVY_CREATIVE_CORE_V3_RULE_TEXT[rule_id]
    for rule_id in set(v2_rules) - set(AUTHORIZED_REWRITES):
        assert v2_rules[rule_id] == v3_rules[rule_id]


def test_v3_uses_the_exact_sealed_replacement_text():
    assert CHARACTER_HEAVY_CREATIVE_CORE_V3_RULE_TEXT["DRAFT_SCENE"] == (
        "Make a specific setting affordance drive a Draft-usable chain of opposed action, "
        "reaction, reversal, cost, and terminal image; carry hidden motive and relational "
        "pressure through choice, omission, and consequence rather than explanation."
    )
    assert CHARACTER_HEAVY_CREATIVE_CORE_V3_RULE_TEXT["ANTI_TAXONOMY"] == (
        "Keep labels in reasoning; avoid stock emotion, generic gestures, and checklist "
        "rhythm; choose character-specific dialogue, evasion, sensory contrast, or "
        "consequence that does double duty."
    )


def test_v3_subtext_dramatization_and_specificity_semantics_are_present():
    profile = build_planning_v2_event_realization_profile_residual_v3(
        BUNDLE, _inputs(), pair_creative_demand_class="character-heavy",
    )
    rules = _rules(profile)
    draft = rules["DRAFT_SCENE"].text.casefold()
    anti = rules["ANTI_TAXONOMY"].text.casefold()

    assert all(unit in draft for unit in (
        "specific setting affordance", "draft-usable chain", "opposed action",
        "reaction", "reversal", "cost", "terminal image", "hidden motive",
        "relational pressure", "choice", "omission", "consequence",
        "rather than explanation",
    ))
    assert all(unit in anti for unit in (
        "labels in reasoning", "stock emotion", "generic gestures", "checklist rhythm",
        "character-specific dialogue", "evasion", "sensory contrast", "consequence",
        "double duty",
    ))


def test_v3_preserves_causality_voice_relationship_and_setup_payoff_gains():
    v2 = build_planning_v2_event_realization_profile_demand_aware(
        BUNDLE, _inputs(), pair_creative_demand_class="character-heavy",
    )
    v3 = build_planning_v2_event_realization_profile_residual_v3(
        BUNDLE, _inputs(), pair_creative_demand_class="character-heavy",
    )
    v2_rules = _rules(v2)
    v3_rules = _rules(v3)

    for rule_id in (
        "MOTIVE_ACTION", "VOICE_RELATION", "CAUSAL_AFFORDANCE", "PRESSURE_BEATS",
        "SETUP_PAYOFF", "PLOT_CAUSAL_ESCALATION", "PLOT_SETUP_PAYOFF_INTENT",
        "CHARACTER_VOICE", "CHARACTER_RELATIONSHIP_NUANCE",
    ):
        assert v3_rules[rule_id] == v2_rules[rule_id]
    assert "opposed action" in v3_rules["DRAFT_SCENE"].text.casefold()
    assert "consequence" in v3_rules["DRAFT_SCENE"].text.casefold()


@pytest.mark.parametrize("demand_class", UNCHANGED_DEMANDS)
def test_v3_keeps_non_character_demands_byte_identical(demand_class: str):
    v2 = build_planning_v2_event_realization_profile_demand_aware(
        BUNDLE, _inputs(), pair_creative_demand_class=demand_class,
    )
    v3 = build_planning_v2_event_realization_profile_residual_v3(
        BUNDLE, _inputs(), pair_creative_demand_class=demand_class,
    )
    assert v3 == v2


def test_v3_unknown_demand_fails_closed():
    with pytest.raises(ValueError, match="FAIL_CLOSED_NO_PROFILE_SUBSTITUTION"):
        build_planning_v2_event_realization_profile_residual_v3(
            BUNDLE, _inputs(), pair_creative_demand_class="unknown-future-class",
        )


def test_v3_context_is_complete_deterministic_and_within_the_unchanged_cap():
    first = build_planning_v2_event_realization_profile_residual_v3(
        BUNDLE, _inputs(), pair_creative_demand_class="character-heavy",
    )
    second = build_planning_v2_event_realization_profile_residual_v3(
        BUNDLE, _inputs(), pair_creative_demand_class="character-heavy",
    )
    first_context, first_receipt = _render(first)
    second_context, second_receipt = _render(second)

    assert first == second
    assert first_context == second_context
    assert first_receipt == second_receipt
    assert first_receipt.total_characters == 2998
    assert first_receipt.total_characters <= 3000
    assert first_receipt.status == "NONE"
    assert first_receipt.excluded_rule_ids == ()


def test_v3_remains_shadow_only_and_does_not_add_rigid_runtime_instructions():
    profile = build_planning_v2_event_realization_profile_residual_v3(
        BUNDLE, _inputs(), pair_creative_demand_class="character-heavy",
    )
    rendered, _ = _render(profile)
    lowered = rendered.casefold()

    assert profile.shadow_only is True
    assert profile.production_reachable is False
    assert profile_contains_runtime_owned_responsibility(profile) is False
    assert not any(term in lowered for term in (
        "provider", "http", "retry", "fallback", "persist", "story_state",
        "must emit exactly", "sensory quota", "beat quota", "fixed scene template",
        "step 1:",
    ))
