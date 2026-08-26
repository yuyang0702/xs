from __future__ import annotations

from pathlib import Path

import pytest

from novel_flywheel.runtime_skill_profiles import (
    CHARACTER_HEAVY_CREATIVE_CORE_V2_RULE_TEXT,
    SkillLoadDecisionInputsV1,
    build_planning_v2_event_realization_profile_demand_aware,
    build_planning_v2_event_realization_profile_restored,
    profile_contains_runtime_owned_responsibility,
    render_skill_context,
    resolve_demand_aware_creative_profile,
)


REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "vendor/novel-skills/source"
AUTHORITY_HASH = "a" * 64
TARGET_RULE_IDS = ("MOTIVE_ACTION", "VOICE_RELATION", "DRAFT_SCENE", "ANTI_TAXONOMY")
KNOWN_UNCHANGED_DEMANDS = (
    "world-heavy",
    "conflict-pacing-heavy",
    "setup-payoff-heavy",
    "mixed",
)


def _decision_inputs() -> SkillLoadDecisionInputsV1:
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


def _rule_map(profile):
    return {rule.rule_id: rule for rule in (*profile.mandatory_rules, *profile.advisory_rules)}


def _render(profile):
    return render_skill_context(
        profile.advisory_rules,
        profile.mandatory_rules,
        profile.context_budget_policy,
    )


def test_character_heavy_resolver_is_exact_local_and_unknown_fails_closed():
    character = resolve_demand_aware_creative_profile("character-heavy")
    assert character.profile_strategy == "RESTORED_SKILL_V2_CHARACTER_CORE_V2"
    assert character.substitution_allowed is True
    assert character.changed_rule_ids == TARGET_RULE_IDS

    for demand_class in KNOWN_UNCHANGED_DEMANDS:
        resolution = resolve_demand_aware_creative_profile(demand_class)
        assert resolution.profile_strategy.startswith("UNCHANGED_PENDING_PAIR")
        assert resolution.substitution_allowed is False
        assert resolution.changed_rule_ids == ()

    unknown = resolve_demand_aware_creative_profile("unknown-future-class")
    assert unknown.profile_strategy == "FAIL_CLOSED_NO_PROFILE_SUBSTITUTION"
    assert unknown.substitution_allowed is False
    assert unknown.changed_rule_ids == ()


def test_character_heavy_deepens_exactly_four_existing_rules_in_place():
    old = build_planning_v2_event_realization_profile_restored(BUNDLE, _decision_inputs())
    new = build_planning_v2_event_realization_profile_demand_aware(
        BUNDLE, _decision_inputs(), pair_creative_demand_class="character-heavy",
    )
    old_rules = _rule_map(old)
    new_rules = _rule_map(new)

    assert new.profile_id == "RESTORED_SKILL_V2_CHARACTER_CORE_V2"
    assert old.included_rule_ids == new.included_rule_ids
    assert set(old_rules) == set(new_rules)
    assert tuple(rule_id for rule_id in new.included_rule_ids if old_rules[rule_id] != new_rules[rule_id]) == TARGET_RULE_IDS
    for rule_id in TARGET_RULE_IDS:
        old_payload = old_rules[rule_id].model_dump(mode="json")
        new_payload = new_rules[rule_id].model_dump(mode="json")
        assert {key: value for key, value in old_payload.items() if key != "text"} == {
            key: value for key, value in new_payload.items() if key != "text"
        }
        assert new_payload["text"] == CHARACTER_HEAVY_CREATIVE_CORE_V2_RULE_TEXT[rule_id]
    for rule_id in set(old_rules) - set(TARGET_RULE_IDS):
        assert old_rules[rule_id] == new_rules[rule_id]


def test_character_heavy_context_covers_sealed_microchain_and_draft_handoff():
    profile = build_planning_v2_event_realization_profile_demand_aware(
        BUNDLE, _decision_inputs(), pair_creative_demand_class="character-heavy",
    )
    rules = _rule_map(profile)
    motive = rules["MOTIVE_ACTION"].text.casefold()
    voice = rules["VOICE_RELATION"].text.casefold()
    draft = rules["DRAFT_SCENE"].text.casefold()
    anti = rules["ANTI_TAXONOMY"].text.casefold()

    assert all(unit in motive for unit in (
        "formative pressure", "present want", "concealed need", "opposed tactics",
        "costly choice", "observable reaction", "next-beat consequence",
    ))
    assert all(unit in voice for unit in (
        "distinct voice", "diction", "rhythm", "evasion", "gesture",
        "withheld explanation", "relationship pressure", "tactics", "costs",
        "trust", "available action",
    ))
    assert all(unit in draft for unit in (
        "draft-usable microchain", "spatial stimulus", "opposed action", "reaction",
        "resistance", "reversal", "costly choice", "terminal image", "behavior",
    ))
    assert all(unit in anti for unit in (
        "labels in reasoning only", "choice", "dialogue", "evasion", "gesture",
        "consequence",
    ))


def test_relationship_and_setup_payoff_gains_are_preserved_exactly():
    old = build_planning_v2_event_realization_profile_restored(BUNDLE, _decision_inputs())
    new = build_planning_v2_event_realization_profile_demand_aware(
        BUNDLE, _decision_inputs(), pair_creative_demand_class="character-heavy",
    )
    old_rules = _rule_map(old)
    new_rules = _rule_map(new)

    assert "relationship pressure" in new_rules["VOICE_RELATION"].text.casefold()
    assert "available action" in new_rules["VOICE_RELATION"].text.casefold()
    assert new_rules["SETUP_PAYOFF"] == old_rules["SETUP_PAYOFF"]
    assert new_rules["PLOT_SETUP_PAYOFF_INTENT"] == old_rules["PLOT_SETUP_PAYOFF_INTENT"]


@pytest.mark.parametrize("demand_class", KNOWN_UNCHANGED_DEMANDS)
def test_non_character_demands_preserve_previous_effective_profile(demand_class: str):
    old = build_planning_v2_event_realization_profile_restored(BUNDLE, _decision_inputs())
    selected = build_planning_v2_event_realization_profile_demand_aware(
        BUNDLE, _decision_inputs(), pair_creative_demand_class=demand_class,
    )
    assert selected == old


def test_unknown_demand_cannot_substitute_a_profile():
    with pytest.raises(ValueError, match="FAIL_CLOSED_NO_PROFILE_SUBSTITUTION"):
        build_planning_v2_event_realization_profile_demand_aware(
            BUNDLE, _decision_inputs(), pair_creative_demand_class="unknown-future-class",
        )


def test_character_heavy_context_is_deterministic_complete_and_within_frozen_cap():
    first = build_planning_v2_event_realization_profile_demand_aware(
        BUNDLE, _decision_inputs(), pair_creative_demand_class="character-heavy",
    )
    second = build_planning_v2_event_realization_profile_demand_aware(
        BUNDLE, _decision_inputs(), pair_creative_demand_class="character-heavy",
    )
    first_context, first_receipt = _render(first)
    second_context, second_receipt = _render(second)

    assert first == second
    assert first_context == second_context
    assert first_receipt == second_receipt
    assert first_receipt.total_characters == 2925
    assert first_receipt.total_characters <= 3000
    assert first_receipt.status == "NONE"
    assert first_receipt.excluded_rule_ids == ()


def test_character_heavy_profile_has_no_operational_or_rigid_template_leakage():
    profile = build_planning_v2_event_realization_profile_demand_aware(
        BUNDLE, _decision_inputs(), pair_creative_demand_class="character-heavy",
    )
    rendered, _ = _render(profile)
    lowered = rendered.casefold()

    assert profile.shadow_only is True
    assert profile.production_reachable is False
    assert profile_contains_runtime_owned_responsibility(profile) is False
    assert len(profile.included_rule_ids) == len(set(profile.included_rule_ids))
    assert not any(term in lowered for term in (
        "provider", "http", "retry", "fallback", "persist", "story_state",
        "must emit exactly", "six-step template", "step 1:", "checklist",
    ))
