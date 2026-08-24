from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from novel_flywheel.runtime_skill_profiles import (
    EXPECTED_BUNDLE_MANIFEST_SHA256,
    RESTORED_CREATIVE_RULE_IDS,
    ProfileRuleV1,
    RuntimeSkillProfileV1,
    SkillContextBudgetPolicyV1,
    SkillLoadDecisionInputsV1,
    audit_creative_capability_presence,
    build_planning_v1_compat_profile,
    build_planning_v2_event_realization_profile,
    build_planning_v2_event_realization_profile_restored,
    classify_current_mandatory_rules,
    context_budget_policy_v1,
    creative_coverage,
    model_schema,
    profile_contains_runtime_owned_responsibility,
    render_skill_context,
    resolve_conditional_load,
    resolve_precedence,
    verify_source_bundle,
)


REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "vendor/novel-skills/source"
FIXTURES = REPO / "tests/fixtures/skills/planning-profile-v1"
AUTHORITY_HASH = "a" * 64


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _decision_inputs(**overrides) -> SkillLoadDecisionInputsV1:
    values = {
        "authority_revision": 1,
        "authority_hash": AUTHORITY_HASH,
        "actor_refs_status": "present",
        "world_refs_status": "present",
        "actor_ref_count": 1,
        "world_ref_count": 1,
        "actor_refs": ("actor-fixture",),
        "location_refs": ("location-fixture",),
    }
    values.update(overrides)
    return SkillLoadDecisionInputsV1.model_validate(values)


def test_source_bundle_is_exact_and_read_only():
    result = verify_source_bundle(BUNDLE)
    assert result == {
        "manifest_sha256": EXPECTED_BUNDLE_MANIFEST_SHA256,
        "skill_hashes": result["skill_hashes"],
        "skill_count": 11,
        "file_count": 83,
        "total_bytes": 314197,
        "status": "exact",
    }
    assert set(result["skill_hashes"]) == {
        "story-init", "plot-structure", "character-management", "worldbuilding",
    }


def test_profile_schema_is_typed_and_hash_bound():
    profile = build_planning_v1_compat_profile(BUNDLE, _json("authority-present.json"))
    payload = profile.model_dump(mode="json", by_alias=True)
    assert RuntimeSkillProfileV1.model_validate_json(json.dumps(payload)) == profile
    assert payload["schema"] == "RuntimeSkillProfileV1"
    assert payload["shadow_only"] is True
    assert payload["production_reachable"] is False
    assert len(profile.definition_sha256) == 64
    assert len(profile.canonical_profile_sha256) == 64
    assert len(profile.prompt_binding_sha256) == 64
    assert model_schema()["title"] == "RuntimeSkillProfileV1"


def test_profile_compilation_is_deterministic_and_path_portable():
    first = build_planning_v1_compat_profile(BUNDLE, _json("authority-present.json"))
    second = build_planning_v1_compat_profile(BUNDLE, _json("authority-present.json"))
    assert first == second
    encoded = json.dumps(first.model_dump(mode="json", by_alias=True), ensure_ascii=False)
    assert str(REPO) not in encoded
    assert "\\" not in encoded
    assert all(item.line_end >= item.line_start for item in first.included_sections)
    assert all(item.rule_ids for item in first.included_sections)


def test_source_mutation_fails_closed(tmp_path: Path):
    copied = tmp_path / "repo/vendor/novel-skills/source"
    copied.parent.mkdir(parents=True)
    for skill_id in ("story-init", "plot-structure", "character-management", "worldbuilding"):
        shutil.copytree(BUNDLE / skill_id, copied / skill_id)
    evidence = tmp_path / "repo/docs/superpowers/reports/project-skill-portable-bundle"
    evidence.mkdir(parents=True)
    shutil.copy2(
        REPO / "docs/superpowers/reports/project-skill-portable-bundle/project-skill-final-sha256-manifest-v1.json",
        evidence,
    )
    (copied / "plot-structure/SKILL.md").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="source bundle changed"):
        verify_source_bundle(copied)


def test_current_mandatory_rule_classification_is_closed_world_and_exact():
    rows = classify_current_mandatory_rules(BUNDLE)
    assert len(rows) == 7
    assert sum(item.occurrence_count for item in rows) == 9
    assert sum(item.classification == "TEMPLATE_FALSE_POSITIVE" for item in rows) == 3
    assert sum(item.classification == "OPERATIONAL_INSTRUCTION" for item in rows) == 4
    assert sum(item.true_narrative_invariant for item in rows) == 0
    profile = build_planning_v1_compat_profile(BUNDLE, _json("authority-present.json"))
    assert profile.mandatory_rules == ()
    assert not any(item.rule_id in profile.included_rule_ids for item in rows)


def test_v1_compat_excludes_story_init_sections_and_uses_bridge():
    profile = build_planning_v1_compat_profile(BUNDLE, _json("authority-unspecified.json"))
    assert "story-init" in profile.source_skill_ids
    assert not any(item.skill_id == "story-init" for item in profile.included_sections)
    assert profile.narrative_bridge is not None
    assert profile.narrative_bridge.story_init_loaded is False
    statuses = {item.field_name: item.status for item in profile.narrative_bridge.fields}
    assert statuses == {
        "genre": "present", "premise": "present", "pov": "present", "tone": "present",
        "theme": "unspecified", "tense": "unspecified",
    }


@pytest.mark.parametrize("case", _json("conditional-load-cases.json")["cases"])
def test_conditional_load_matrix_is_deterministic_and_fail_safe(case):
    decision = resolve_conditional_load(_decision_inputs(
        actor_refs_status=case["actor_refs_status"],
        world_refs_status=case["world_refs_status"],
        actor_ref_count=None, world_ref_count=None,
        actor_refs=(), location_refs=(),
    ))
    outcomes = {item.component_id: item.outcome for item in decision.components}
    assert outcomes["character-creative"] == case["character"]
    assert outcomes["world-creative"] == case["world"]
    assert decision.fail_safe_used is case["fail_safe"]


def test_decision_input_change_changes_decision_and_profile_identity():
    present = _decision_inputs()
    absent = _decision_inputs(actor_refs_status="absent", actor_ref_count=0, actor_refs=())
    first = build_planning_v2_event_realization_profile(BUNDLE, present)
    second = build_planning_v2_event_realization_profile(BUNDLE, absent)
    assert first.load_decision.decision_id != second.load_decision.decision_id  # type: ignore[union-attr]
    assert first.canonical_profile_sha256 != second.canonical_profile_sha256
    assert "story-init" not in first.source_skill_ids
    assert "character-management" not in second.source_skill_ids


@pytest.mark.parametrize(
    ("overrides", "component"),
    [
        ({"actor_refs_status": "absent", "actor_refs": (), "relationship_dependency_refs": ("rel",)}, "character-creative"),
        ({"actor_refs_status": "absent", "actor_refs": (), "knowledge_state_refs": ("knowledge",)}, "character-creative"),
        ({"actor_refs_status": "absent", "actor_refs": (), "dialogue_required": True}, "character-creative"),
        ({"world_refs_status": "absent", "location_refs": ("location",)}, "world-creative"),
        ({"world_refs_status": "absent", "location_refs": (), "system_refs": ("system",)}, "world-creative"),
        ({"world_refs_status": "absent", "location_refs": (), "faction_refs": ("faction",)}, "world-creative"),
        ({"world_refs_status": "absent", "location_refs": (), "object_refs": ("object",)}, "world-creative"),
    ],
)
def test_typed_dependency_refs_enable_the_corresponding_component(overrides, component):
    decision = resolve_conditional_load(_decision_inputs(**overrides))
    outcomes = {item.component_id: item.outcome for item in decision.components}
    assert outcomes[component] == "include"


@pytest.mark.parametrize("case", _json("precedence-cases.json")["cases"])
def test_typed_precedence_conflicts(case):
    assert resolve_precedence(case["left"], case["right"]) == case["winner"]


def _synthetic_rule(rule_id: str, length: int, *, mandatory: bool = False) -> ProfileRuleV1:
    return ProfileRuleV1(
        rule_id=rule_id, skill_id="fixture", text="x" * length,
        source_section_ids=("fixture-section",),
        classification="true_narrative_invariant" if mandatory else "advisory_creative",
        coverage_categories=("fixture",),
    )


def test_context_budget_never_slices_rules_and_truncates_advisory():
    policy = context_budget_policy_v1()
    rules = tuple(_synthetic_rule(f"R{index}", 800) for index in range(3))
    rendered, receipt = render_skill_context(rules, (), policy)
    assert receipt.status == "ADVISORY_TRUNCATED"
    assert receipt.dispatch_allowed is True
    assert receipt.total_characters <= 3000
    assert "[R0]" in rendered and "[R1]" in rendered and "[R2]" not in rendered
    assert "x" * 800 in rendered


def test_mandatory_budget_overflow_blocks_dispatch():
    policy = context_budget_policy_v1()
    rendered, receipt = render_skill_context((), (_synthetic_rule("M1", 1300, mandatory=True),), policy)
    assert rendered == ""
    assert receipt.status == "BLOCKED_MANDATORY_OVERFLOW"
    assert receipt.dispatch_allowed is False
    assert receipt.rendered_context_sha256 is None


def test_policy_rejects_budget_above_authorized_maximum():
    with pytest.raises(Exception):
        SkillContextBudgetPolicyV1.model_validate({
            "schema": "SkillContextBudgetPolicyV1",
            "maximum_characters": 3001,
            "mandatory_character_budget": 1200,
            "advisory_character_budget": 1801,
            "whole_rule_only": True,
            "mandatory_overflow_behavior": "block",
            "advisory_overflow_behavior": "truncate_by_whole_rule",
            "policy_sha256": "0" * 64,
        })


def test_creative_quality_coverage_and_runtime_ownership_are_preserved():
    expected = set(_json("creative-coverage-expectations.json")["required"])
    profile = build_planning_v1_compat_profile(BUNDLE, _json("authority-present.json"))
    assert expected <= set(creative_coverage(profile))
    assert profile_contains_runtime_owned_responsibility(profile) is False
    assert all(rule.authority_level == 7 for rule in profile.advisory_rules)
    assert profile.world_creative_policy.proposal_only is True
    assert profile.world_creative_policy.formal_write_authority is False
    assert {lane.classification for lane in profile.world_creative_policy.lanes} == {
        "SENSORY_REALIZATION", "DRAMATIZATION", "NON_CANONICAL_DETAIL",
        "CANONICAL_FACT_PROPOSAL", "FORBIDDEN_AUTHORITY_OVERRIDE",
    }


def test_v2_profile_uses_minimal_plot_and_conditional_creative_subsets():
    only_plot = build_planning_v2_event_realization_profile(
        BUNDLE, _decision_inputs(
            actor_refs_status="absent", world_refs_status="absent",
            actor_ref_count=0, world_ref_count=0,
            actor_refs=(), location_refs=(),
        ),
    )
    assert only_plot.source_skill_ids == ("plot-structure",)
    assert {item.skill_id for item in only_plot.included_sections} == {"plot-structure"}
    full = build_planning_v2_event_realization_profile(BUNDLE, _decision_inputs())
    assert set(full.source_skill_ids) == {
        "plot-structure", "character-management", "worldbuilding",
    }
    assert all(item.skill_id != "story-init" for item in full.included_sections)
    assert "PLOT_STRUCTURE_ADAPTATION" not in full.included_rule_ids


def test_restored_v2_context_is_complete_deterministic_and_within_existing_budget():
    profile = build_planning_v2_event_realization_profile_restored(BUNDLE, _decision_inputs())
    assert profile.load_decision.included_skill_ids == (  # type: ignore[union-attr]
        "plot-structure", "character-management", "worldbuilding",
    )
    assert profile.source_skill_ids == (
        "story-init", "plot-structure", "character-management", "worldbuilding",
    )
    assert tuple(item.rule_id for item in profile.mandatory_rules) == RESTORED_CREATIVE_RULE_IDS
    assert len(profile.advisory_rules) == 12
    first, first_receipt = render_skill_context(
        profile.advisory_rules, profile.mandatory_rules, profile.context_budget_policy,
    )
    second, second_receipt = render_skill_context(
        profile.advisory_rules, profile.mandatory_rules, profile.context_budget_policy,
    )
    old, old_receipt = render_skill_context(
        profile.advisory_rules, (), profile.context_budget_policy,
    )

    assert first == second
    assert first_receipt == second_receipt
    assert first_receipt.status == "NONE"
    assert first_receipt.excluded_rule_ids == ()
    assert first_receipt.total_characters <= 3000
    assert first_receipt.mandatory_characters <= 1200
    assert first_receipt.advisory_characters <= 1800
    assert old_receipt.status == "NONE"
    assert len(old) == 1587
    assert old_receipt.rendered_context_sha256 == (
        "a77ca32533e7e480ab3b0ff53d55dde5bed4ff837b8b68f53b7aba59a8d6fd15"
    )


def test_restored_v2_actionable_creative_capability_gate_rejects_old_profile():
    profile = build_planning_v2_event_realization_profile_restored(BUNDLE, _decision_inputs())
    restored, _ = render_skill_context(
        profile.advisory_rules, profile.mandatory_rules, profile.context_budget_policy,
    )
    old, _ = render_skill_context(profile.advisory_rules, (), profile.context_budget_policy)

    restored_audit = audit_creative_capability_presence(restored)
    old_audit = audit_creative_capability_presence(old)
    assert restored_audit["overall_status"] == "pass"
    assert restored_audit["passed_check_count"] == restored_audit["check_count"]
    assert old_audit["overall_status"] == "fail"
    assert old_audit["passed_check_count"] < old_audit["check_count"]


@pytest.mark.parametrize(
    ("rule_id", "replacement"),
    [
        ("PRESSURE_BEATS", None),
        ("DRAFT_SCENE", None),
        ("ANTI_TAXONOMY", None),
        ("MOTIVE_ACTION", "motivation"),
        ("CAUSAL_AFFORDANCE", "world specificity"),
        ("PRESSURE_BEATS", "pacing"),
    ],
)
def test_restored_v2_rejects_deleted_or_label_only_creative_decomposition(
    rule_id: str, replacement: str | None,
):
    profile = build_planning_v2_event_realization_profile_restored(BUNDLE, _decision_inputs())
    restored, _ = render_skill_context(
        profile.advisory_rules, profile.mandatory_rules, profile.context_budget_policy,
    )
    rule = next(item for item in profile.mandatory_rules if item.rule_id == rule_id)
    exact = f"[{rule.rule_id}] {rule.text}\n"
    mutated = restored.replace(
        exact,
        "" if replacement is None else f"[{rule.rule_id}] {replacement}\n",
    )
    assert mutated != restored
    assert audit_creative_capability_presence(mutated)["overall_status"] == "fail"


def test_restored_v2_narrative_bridge_is_bounded_and_unspecified_safe():
    profile = build_planning_v2_event_realization_profile_restored(BUNDLE, _decision_inputs())
    assert profile.narrative_bridge is not None
    assert profile.narrative_bridge.story_init_loaded is False
    assert {item.status for item in profile.narrative_bridge.fields} == {"unspecified"}
