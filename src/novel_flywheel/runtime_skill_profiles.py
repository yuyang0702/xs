"""Deterministic Planning Skill profiles for offline shadow evaluation only.

The contracts in this module compile selected creative guidance from the sealed
repo-owned Skill source bundle.  They are intentionally unreachable from the
production Skill scanner, prompt assembly, routing, and workflow owners.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_flywheel.canonical_shadow import canonical_sha256, stable_id
from novel_flywheel.context_policy import estimate_input_tokens


UTF8 = "utf-8"
EXPECTED_BUNDLE_MANIFEST_SHA256 = (
    "451a30d3815e1c6e4bdb3e1a1bc1dbec4e4a84061e873f8acca3aee2e2925a3a"
)
PLANNING_SKILL_IDS = (
    "story-init", "plot-structure", "character-management", "worldbuilding",
)
EXPECTED_SKILL_HASHES = {
    "story-init": "77d0a75c0ccdd959218a75f02852cb6654aebf0e645e427dd8ef86514ffbd6a9",
    "plot-structure": "97bd7c6985867076a1b53b461db4549fefff4d1e3c2afad17de2b0a67a1cb9b9",
    "character-management": "3debd36a3da4a430f4f71292280d4824bfab0436234a2ace68be939773062be5",
    "worldbuilding": "434e8f9f37a54b4f15e4f1b6978862eaa40eb1ec37d02e778336bda485950678",
}
_SHA256 = r"^[0-9a-f]{64}$"


class _ProfileModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, str_strip_whitespace=True,
    )


class SourceSectionBindingV1(_ProfileModel):
    schema_name: Literal["SourceSectionBindingV1"] = Field(
        default="SourceSectionBindingV1", alias="schema", serialization_alias="schema",
    )
    section_id: str
    skill_id: str
    relative_source_path: str
    heading: str
    heading_level: int = Field(ge=1, le=6)
    heading_ordinal: int = Field(ge=1)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    section_sha256: str = Field(pattern=_SHA256)
    rule_ids: tuple[str, ...]
    classification: Literal["creative_guidance", "template_content"]
    applicability: Literal["always", "conditional"]


class ProfileRuleV1(_ProfileModel):
    schema_name: Literal["ProfileRuleV1"] = Field(
        default="ProfileRuleV1", alias="schema", serialization_alias="schema",
    )
    rule_id: str
    skill_id: str
    text: str
    source_section_ids: tuple[str, ...]
    classification: Literal["advisory_creative", "true_narrative_invariant"]
    authority_level: Literal[6, 7] = 7
    owner: Literal["model_creative"] = "model_creative"
    coverage_categories: tuple[str, ...]


class ConditionalComponentV1(_ProfileModel):
    schema_name: Literal["ConditionalComponentV1"] = Field(
        default="ConditionalComponentV1", alias="schema", serialization_alias="schema",
    )
    component_id: str
    skill_id: Literal["character-management", "worldbuilding"]
    trigger_field: Literal["actor_refs_status", "world_refs_status"]
    true_states: tuple[Literal["present"], ...] = ("present",)
    false_states: tuple[Literal["absent"], ...] = ("absent",)
    fail_safe_include_states: tuple[
        Literal["unknown", "missing", "stale", "mixed"], ...
    ] = ("unknown", "missing", "stale", "mixed")
    rule_ids: tuple[str, ...]
    section_ids: tuple[str, ...]


class SkillLoadDecisionInputsV1(_ProfileModel):
    schema_name: Literal["SkillLoadDecisionInputsV1"] = Field(
        default="SkillLoadDecisionInputsV1", alias="schema", serialization_alias="schema",
    )
    authority_revision: int = Field(ge=1)
    authority_hash: str = Field(pattern=_SHA256)
    actor_refs_status: Literal["present", "absent", "unknown", "missing", "stale", "mixed"]
    world_refs_status: Literal["present", "absent", "unknown", "missing", "stale", "mixed"]
    actor_ref_count: int | None = Field(default=None, ge=0)
    world_ref_count: int | None = Field(default=None, ge=0)
    actor_refs: tuple[str, ...] = ()
    character_refs: tuple[str, ...] = ()
    relationship_dependency_refs: tuple[str, ...] = ()
    knowledge_state_refs: tuple[str, ...] = ()
    location_refs: tuple[str, ...] = ()
    world_rule_refs: tuple[str, ...] = ()
    system_refs: tuple[str, ...] = ()
    faction_refs: tuple[str, ...] = ()
    object_refs: tuple[str, ...] = ()
    dialogue_required: bool | None = None
    formal_event_dependency_refs: tuple[str, ...] = ()
    slice_dependency_refs: tuple[str, ...] = ()


class ComponentLoadDecisionV1(_ProfileModel):
    component_id: str
    outcome: Literal["include", "exclude", "fail_safe_include"]
    reason_code: str


class SkillLoadDecisionV1(_ProfileModel):
    schema_name: Literal["SkillLoadDecisionV1"] = Field(
        default="SkillLoadDecisionV1", alias="schema", serialization_alias="schema",
    )
    version: Literal[1] = 1
    decision_id: str
    inputs: SkillLoadDecisionInputsV1
    components: tuple[ComponentLoadDecisionV1, ...]
    included_skill_ids: tuple[str, ...]
    fail_safe_used: bool

    @model_validator(mode="after")
    def decision_id_is_current(self) -> "SkillLoadDecisionV1":
        unsigned = self.model_dump(mode="json", by_alias=True, exclude={"decision_id"})
        if self.decision_id != stable_id("skill-load", "SkillLoadDecisionV1", unsigned):
            raise ValueError("decision_id is not bound to decision inputs")
        return self


class NarrativeBridgeFieldV1(_ProfileModel):
    field_name: Literal["genre", "premise", "pov", "tone", "theme", "tense"]
    status: Literal["present", "unspecified"]
    value_hash: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def hash_matches_status(self) -> "NarrativeBridgeFieldV1":
        if (self.status == "present") != (self.value_hash is not None):
            raise ValueError("present bridge fields require a hash; unspecified fields forbid one")
        return self


class ExistingProjectNarrativeBridgeV1(_ProfileModel):
    schema_name: Literal["ExistingProjectNarrativeBridgeV1"] = Field(
        default="ExistingProjectNarrativeBridgeV1", alias="schema", serialization_alias="schema",
    )
    bridge_id: str
    policy_id: Literal["EXISTING_PROJECT_NARRATIVE_BRIDGE_V1"] = (
        "EXISTING_PROJECT_NARRATIVE_BRIDGE_V1"
    )
    fields: tuple[NarrativeBridgeFieldV1, ...]
    story_init_loaded: Literal[False] = False

    @model_validator(mode="after")
    def bridge_id_is_current(self) -> "ExistingProjectNarrativeBridgeV1":
        if tuple(item.field_name for item in self.fields) != (
            "genre", "premise", "pov", "tone", "theme", "tense",
        ):
            raise ValueError("bridge fields must use canonical order")
        unsigned = self.model_dump(mode="json", by_alias=True, exclude={"bridge_id"})
        if self.bridge_id != stable_id("narrative-bridge", self.policy_id, unsigned):
            raise ValueError("bridge_id is stale")
        return self


class WorldCreativeProposalLaneV1(_ProfileModel):
    lane_id: str
    classification: Literal[
        "SENSORY_REALIZATION", "DRAMATIZATION", "NON_CANONICAL_DETAIL",
        "CANONICAL_FACT_PROPOSAL", "FORBIDDEN_AUTHORITY_OVERRIDE",
    ]
    disposition: Literal["allowed", "proposal_only", "reject"]
    canon_authority: Literal[False] = False
    constraints: tuple[str, ...]
    lane_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def lane_identity_is_current(self) -> "WorldCreativeProposalLaneV1":
        unsigned = self.model_dump(mode="json", exclude={"lane_id", "lane_sha256"})
        if self.lane_id != stable_id("world-lane", "WorldCreativeProposalLaneV1", unsigned):
            raise ValueError("world creative lane id is stale")
        if self.lane_sha256 != canonical_sha256("WorldCreativeProposalLaneV1", unsigned):
            raise ValueError("world creative lane hash is stale")
        return self


class WorldCreativeProposalPolicyV1(_ProfileModel):
    schema_name: Literal["WorldCreativeProposalPolicyV1"] = Field(
        default="WorldCreativeProposalPolicyV1", alias="schema", serialization_alias="schema",
    )
    policy_id: Literal["WORLD_CREATIVE_PROPOSAL_POLICY_V1"] = "WORLD_CREATIVE_PROPOSAL_POLICY_V1"
    allowed: tuple[str, ...] = (
        "propose_local_location_detail",
        "propose_sensory_specificity",
        "propose_world_cost_or_limit",
        "propose_faction_pressure",
        "propose_artifact_detail",
    )
    forbidden: tuple[str, ...] = (
        "write_story_state", "write_canon", "change_ready_authority",
        "invent_locked_fact", "override_formal_event",
    )
    lanes: tuple[WorldCreativeProposalLaneV1, ...]
    covered_subjects: tuple[str, ...] = (
        "world_rule_cost", "owner", "location", "power", "historical_state",
    )
    proposal_only: Literal[True] = True
    formal_write_authority: Literal[False] = False
    policy_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def policy_hash_is_current(self) -> "WorldCreativeProposalPolicyV1":
        unsigned = self.model_dump(mode="json", by_alias=True, exclude={"policy_sha256"})
        if self.policy_sha256 != canonical_sha256(self.policy_id, unsigned):
            raise ValueError("world creative policy hash is stale")
        return self


class PrecedenceLevelV1(_ProfileModel):
    level: int = Field(ge=1, le=8)
    authority: str
    may_be_overridden_by_skill: Literal[False] = False


class SkillPrecedencePolicyV1(_ProfileModel):
    schema_name: Literal["SkillPrecedencePolicyV1"] = Field(
        default="SkillPrecedencePolicyV1", alias="schema", serialization_alias="schema",
    )
    policy_id: Literal["SKILL_PRECEDENCE_POLICY_V1"] = "SKILL_PRECEDENCE_POLICY_V1"
    levels: tuple[PrecedenceLevelV1, ...]
    lower_number_wins: Literal[True] = True
    skill_mandatory_authority_level: Literal[6] = 6
    skill_advisory_authority_level: Literal[7] = 7
    unknown_conflict_behavior: Literal["block"] = "block"
    policy_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def validate_policy(self) -> "SkillPrecedencePolicyV1":
        if tuple(item.level for item in self.levels) != tuple(range(1, 9)):
            raise ValueError("precedence levels must be complete and ordered")
        unsigned = self.model_dump(mode="json", by_alias=True, exclude={"policy_sha256"})
        if self.policy_sha256 != canonical_sha256(self.policy_id, unsigned):
            raise ValueError("precedence policy hash is stale")
        return self


class SkillContextBudgetPolicyV1(_ProfileModel):
    schema_name: Literal["SkillContextBudgetPolicyV1"] = Field(
        default="SkillContextBudgetPolicyV1", alias="schema", serialization_alias="schema",
    )
    policy_id: Literal["SKILL_CONTEXT_BUDGET_POLICY_V1"] = "SKILL_CONTEXT_BUDGET_POLICY_V1"
    maximum_characters: int = Field(default=3000, ge=1, le=3000)
    mandatory_character_budget: int = Field(default=1200, ge=1)
    advisory_character_budget: int = Field(default=1800, ge=0)
    whole_rule_only: Literal[True] = True
    mandatory_overflow_behavior: Literal["block"] = "block"
    advisory_overflow_behavior: Literal["truncate_by_whole_rule"] = "truncate_by_whole_rule"
    policy_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def validate_policy(self) -> "SkillContextBudgetPolicyV1":
        if self.mandatory_character_budget + self.advisory_character_budget != self.maximum_characters:
            raise ValueError("budget partitions must equal the total")
        unsigned = self.model_dump(mode="json", by_alias=True, exclude={"policy_sha256"})
        if self.policy_sha256 != canonical_sha256(self.policy_id, unsigned):
            raise ValueError("context budget policy hash is stale")
        return self


class SkillContextTruncationReceiptV1(_ProfileModel):
    schema_name: Literal["SkillContextTruncationReceiptV1"] = Field(
        default="SkillContextTruncationReceiptV1", alias="schema", serialization_alias="schema",
    )
    status: Literal["NONE", "ADVISORY_TRUNCATED", "ADVISORY_SHED", "BLOCKED_MANDATORY_OVERFLOW"]
    profile_hash: str
    input_hash: str = Field(pattern=_SHA256)
    source_rule_ids: tuple[str, ...]
    included_rule_ids: tuple[str, ...]
    excluded_rule_ids: tuple[str, ...]
    original_characters: int = Field(ge=0)
    mandatory_characters: int = Field(ge=0)
    advisory_characters: int = Field(ge=0)
    total_characters: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    rendered_context_sha256: str | None = Field(default=None, pattern=_SHA256)
    mandatory_overflow: bool
    truncation_reason: str
    ordering_policy: Literal["priority_then_source_skill_then_section_then_rule_id"] = (
        "priority_then_source_skill_then_section_then_rule_id"
    )
    dispatch_allowed: bool
    whole_rule_only: Literal[True] = True
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_hash_is_current(self) -> "SkillContextTruncationReceiptV1":
        unsigned = self.model_dump(mode="json", by_alias=True, exclude={"receipt_sha256"})
        if self.receipt_sha256 != canonical_sha256("SkillContextTruncationReceiptV1", unsigned):
            raise ValueError("truncation receipt hash is stale")
        return self


class RuntimeSkillProfileV1(_ProfileModel):
    schema_name: Literal["RuntimeSkillProfileV1"] = Field(
        default="RuntimeSkillProfileV1", alias="schema", serialization_alias="schema",
    )
    version: Literal[1] = 1
    profile_id: Literal[
        "CURRENT_PLANNING_V1_COMPAT_PROFILE_V1",
        "PLANNING_V2_EVENT_REALIZATION_PROFILE_V1",
        "RESTORED_SKILL_V2_CHARACTER_CORE_V2",
    ]
    stage: Literal["planning"] = "planning"
    substage: Literal["planning_v1_compat", "planning_v2_event_realization"]
    slice_id: Literal["not_applicable", "EVENT_REALIZATION_UNIT_SHADOW_V1"]
    source_bundle_manifest_sha256: str = Field(pattern=_SHA256)
    source_skill_ids: tuple[str, ...]
    source_skill_sha256: dict[str, str]
    included_sections: tuple[SourceSectionBindingV1, ...]
    included_rule_ids: tuple[str, ...]
    mandatory_rules: tuple[ProfileRuleV1, ...]
    advisory_rules: tuple[ProfileRuleV1, ...]
    excluded_section_categories: tuple[str, ...]
    conditional_components: tuple[ConditionalComponentV1, ...]
    decision_inputs: tuple[SkillLoadDecisionInputsV1, ...]
    decision_result: SkillLoadDecisionV1 | None
    authority_revision: int | Literal["unknown"]
    authority_hash: str
    precedence_policy: SkillPrecedencePolicyV1
    context_budget_policy: SkillContextBudgetPolicyV1
    world_creative_policy: WorldCreativeProposalPolicyV1
    narrative_bridge: ExistingProjectNarrativeBridgeV1 | None
    context_budget: int = Field(ge=1, le=3000)
    mandatory_budget: int = Field(ge=1)
    advisory_budget: int = Field(ge=0)
    truncation_status: Literal["NONE", "ADVISORY_TRUNCATED", "ADVISORY_SHED"]
    prompt_binding_sha256: str = Field(pattern=_SHA256)
    definition_sha256: str = Field(pattern=_SHA256)
    canonical_profile_sha256: str = Field(pattern=_SHA256)
    shadow_only: Literal[True] = True
    production_reachable: Literal[False] = False

    @model_validator(mode="after")
    def validate_profile(self) -> "RuntimeSkillProfileV1":
        rules = (*self.mandatory_rules, *self.advisory_rules)
        if self.included_rule_ids != tuple(item.rule_id for item in rules):
            raise ValueError("included_rule_ids must match canonical rule order")
        available_sections = {item.section_id for item in self.included_sections}
        if any(not set(rule.source_section_ids) <= available_sections for rule in rules):
            raise ValueError("profile rule references a missing section")
        unsigned = self.model_dump(
            mode="json", by_alias=True, exclude={"canonical_profile_sha256"},
        )
        if self.canonical_profile_sha256 != canonical_sha256("RuntimeSkillProfileV1", unsigned):
            raise ValueError("canonical profile hash is stale")
        return self

    @property
    def load_decision(self) -> SkillLoadDecisionV1 | None:
        return self.decision_result


class MandatoryRuleClassificationV2(_ProfileModel):
    rule_id: str
    text_sha256: str = Field(pattern=_SHA256)
    occurrence_count: int = Field(ge=1)
    classification: Literal[
        "TRUE_NARRATIVE_INVARIANT", "PROJECT_AUTHORITY_DUPLICATE",
        "OPERATIONAL_INSTRUCTION", "TEMPLATE_FALSE_POSITIVE",
        "GENERIC_WRITING_PREFERENCE", "UNKNOWN",
    ]
    true_narrative_invariant: Literal[False] = False


@dataclass(frozen=True)
class _SectionSpec:
    skill_id: str
    relative_path: str
    heading: str
    classification: Literal["creative_guidance", "template_content"] = "creative_guidance"
    applicability: Literal["always", "conditional"] = "always"
    ordinal: int = 1


@dataclass(frozen=True)
class _RuleSpec:
    rule_id: str
    skill_id: str
    text: str
    section_keys: tuple[str, ...]
    categories: tuple[str, ...]
    classification: Literal["advisory_creative", "true_narrative_invariant"] = (
        "advisory_creative"
    )
    authority_level: Literal[6, 7] = 7


DemandAwareProfileStrategy = Literal[
    "RESTORED_SKILL_V2_CHARACTER_CORE_V2",
    "UNCHANGED_PENDING_PAIR2",
    "UNCHANGED_PENDING_PAIR3",
    "UNCHANGED_PENDING_PAIR4",
    "UNCHANGED_PENDING_PAIR5",
    "FAIL_CLOSED_NO_PROFILE_SUBSTITUTION",
]


@dataclass(frozen=True)
class DemandAwareCreativeProfileResolutionV1:
    """Closed-world local decision for the shadow-only creative profile."""

    pair_creative_demand_class: str
    profile_strategy: DemandAwareProfileStrategy
    substitution_allowed: bool
    changed_rule_ids: tuple[str, ...]


def _json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode(UTF8)).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _skill_tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(entry for entry in path.rglob("*") if entry.is_file()):
        digest.update(item.relative_to(path).as_posix().encode(UTF8))
        digest.update(item.read_bytes())
    return digest.hexdigest()


def verify_source_bundle(bundle_root: Path) -> dict[str, Any]:
    bundle_root = bundle_root.resolve()
    repo_root = bundle_root.parents[2]
    manifest_path = repo_root / "docs/superpowers/reports/project-skill-portable-bundle/project-skill-final-sha256-manifest-v1.json"
    if _file_sha256(manifest_path) != EXPECTED_BUNDLE_MANIFEST_SHA256:
        raise ValueError("sealed source bundle manifest changed")
    actual = {skill_id: _skill_tree_sha256(bundle_root / skill_id) for skill_id in PLANNING_SKILL_IDS}
    if actual != EXPECTED_SKILL_HASHES:
        raise ValueError("Planning Skill source bundle changed")
    return {
        "manifest_sha256": EXPECTED_BUNDLE_MANIFEST_SHA256,
        "skill_hashes": actual,
        "skill_count": 11,
        "file_count": 83,
        "total_bytes": 314197,
        "status": "exact",
    }


def _extract_section(bundle_root: Path, spec: _SectionSpec, rule_ids: tuple[str, ...]) -> SourceSectionBindingV1:
    relative = f"{spec.skill_id}/{spec.relative_path}"
    path = bundle_root / relative
    lines = path.read_text(encoding=UTF8).splitlines(keepends=True)
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line.rstrip("\r\n"))
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))
    matches = [item for item in headings if item[2] == spec.heading]
    if len(matches) < spec.ordinal:
        raise ValueError(f"exact section not found: {relative}#{spec.heading}[{spec.ordinal}]")
    start, level, heading = matches[spec.ordinal - 1]
    end = len(lines)
    for candidate, candidate_level, _candidate_heading in headings:
        if candidate > start and candidate_level <= level:
            end = candidate
            break
    section_bytes = "".join(lines[start:end]).encode(UTF8)
    identity = {
        "skill_id": spec.skill_id, "relative_source_path": relative,
        "heading": heading, "heading_level": level, "heading_ordinal": spec.ordinal,
        "line_start": start + 1, "line_end": end,
        "section_sha256": hashlib.sha256(section_bytes).hexdigest(),
    }
    return SourceSectionBindingV1(
        **identity,
        section_id=stable_id("skill-section", "SourceSectionBindingV1", identity),
        rule_ids=rule_ids, classification=spec.classification,
        applicability=spec.applicability,
    )


def _make_policy(model: type[_ProfileModel], policy_id: str, payload: dict[str, Any]) -> _ProfileModel:
    return model.model_validate({
        **payload, "policy_sha256": canonical_sha256(policy_id, _json_value(payload)),
    })


def precedence_policy_v1() -> SkillPrecedencePolicyV1:
    payload = {
        "schema": "SkillPrecedencePolicyV1", "policy_id": "SKILL_PRECEDENCE_POLICY_V1",
        "levels": tuple(
            {"level": level, "authority": authority, "may_be_overridden_by_skill": False}
            for level, authority in enumerate((
                "ready_and_story_state_canonical_authority",
                "confirmed_project_and_narrative_constraints",
                "formal_events_and_execution_manifest",
                "stage_contract_and_schema_ownership",
                "deterministic_runtime_rules", "skill_mandatory_creative_constraint",
                "skill_advisory", "generic_writing_preferences",
            ), start=1)
        ),
        "lower_number_wins": True, "skill_mandatory_authority_level": 6,
        "skill_advisory_authority_level": 7,
        "unknown_conflict_behavior": "block",
    }
    return _make_policy(SkillPrecedencePolicyV1, "SKILL_PRECEDENCE_POLICY_V1", payload)  # type: ignore[return-value]


def context_budget_policy_v1() -> SkillContextBudgetPolicyV1:
    payload = {
        "schema": "SkillContextBudgetPolicyV1", "policy_id": "SKILL_CONTEXT_BUDGET_POLICY_V1",
        "maximum_characters": 3000, "mandatory_character_budget": 1200,
        "advisory_character_budget": 1800, "whole_rule_only": True,
        "mandatory_overflow_behavior": "block",
        "advisory_overflow_behavior": "truncate_by_whole_rule",
    }
    return _make_policy(SkillContextBudgetPolicyV1, "SKILL_CONTEXT_BUDGET_POLICY_V1", payload)  # type: ignore[return-value]


def character_heavy_context_budget_policy_v2() -> SkillContextBudgetPolicyV1:
    """Keep the 3000-char ceiling while fitting the sealed mandatory V2 rewrite."""

    payload = {
        "schema": "SkillContextBudgetPolicyV1", "policy_id": "SKILL_CONTEXT_BUDGET_POLICY_V1",
        "maximum_characters": 3000, "mandatory_character_budget": 1338,
        "advisory_character_budget": 1662, "whole_rule_only": True,
        "mandatory_overflow_behavior": "block",
        "advisory_overflow_behavior": "truncate_by_whole_rule",
    }
    return _make_policy(SkillContextBudgetPolicyV1, "SKILL_CONTEXT_BUDGET_POLICY_V1", payload)  # type: ignore[return-value]


def world_creative_policy_v1() -> WorldCreativeProposalPolicyV1:
    lane_specs = (
        ("SENSORY_REALIZATION", "allowed", ("does_not_become_canon",)),
        ("DRAMATIZATION", "allowed", ("derive_from_existing_facts",)),
        ("NON_CANONICAL_DETAIL", "allowed", ("local_and_reversible", "not_a_downstream_causal_prerequisite")),
        ("CANONICAL_FACT_PROPOSAL", "proposal_only", ("never_authority", "requires_separate_confirmation")),
        ("FORBIDDEN_AUTHORITY_OVERRIDE", "reject", ("preserve_story_state_canon_ready",)),
    )
    lanes = []
    for classification, disposition, constraints in lane_specs:
        unsigned = {
            "classification": classification, "disposition": disposition,
            "canon_authority": False, "constraints": constraints,
        }
        lanes.append(WorldCreativeProposalLaneV1.model_validate({
            **unsigned,
            "lane_id": stable_id("world-lane", "WorldCreativeProposalLaneV1", unsigned),
            "lane_sha256": canonical_sha256("WorldCreativeProposalLaneV1", unsigned),
        }))
    payload = {
        "schema": "WorldCreativeProposalPolicyV1", "policy_id": "WORLD_CREATIVE_PROPOSAL_POLICY_V1",
        "allowed": (
            "propose_local_location_detail", "propose_sensory_specificity",
            "propose_world_cost_or_limit", "propose_faction_pressure",
            "propose_artifact_detail",
        ),
        "forbidden": (
            "write_story_state", "write_canon", "change_ready_authority",
            "invent_locked_fact", "override_formal_event",
        ),
        "lanes": tuple(lanes),
        "covered_subjects": (
            "world_rule_cost", "owner", "location", "power", "historical_state",
        ),
        "proposal_only": True, "formal_write_authority": False,
    }
    return _make_policy(WorldCreativeProposalPolicyV1, "WORLD_CREATIVE_PROPOSAL_POLICY_V1", payload)  # type: ignore[return-value]


def resolve_precedence(left_level: int | None, right_level: int | None) -> Literal["left", "right", "equal", "block"]:
    if left_level not in range(1, 9) or right_level not in range(1, 9):
        return "block"
    if left_level == right_level:
        return "equal"
    return "left" if left_level < right_level else "right"


def make_narrative_bridge(values: dict[str, str | None]) -> ExistingProjectNarrativeBridgeV1:
    fields = tuple(
        NarrativeBridgeFieldV1(
            field_name=name,
            status="present" if values.get(name) not in (None, "") else "unspecified",
            value_hash=(
                canonical_sha256("NarrativeBridgeFieldValueV1", values[name])
                if values.get(name) not in (None, "") else None
            ),
        )
        for name in ("genre", "premise", "pov", "tone", "theme", "tense")
    )
    payload = {
        "schema": "ExistingProjectNarrativeBridgeV1",
        "policy_id": "EXISTING_PROJECT_NARRATIVE_BRIDGE_V1",
        "fields": tuple(item.model_dump(mode="json", by_alias=True) for item in fields),
        "story_init_loaded": False,
    }
    return ExistingProjectNarrativeBridgeV1.model_validate({
        **payload,
        "bridge_id": stable_id("narrative-bridge", "EXISTING_PROJECT_NARRATIVE_BRIDGE_V1", payload),
    })


def resolve_conditional_load(inputs: SkillLoadDecisionInputsV1) -> SkillLoadDecisionV1:
    rows: list[ComponentLoadDecisionV1] = []
    included = ["plot-structure"]
    fail_safe = False
    for component, skill_id, field, dependency_fields in (
        (
            "character-creative", "character-management", "actor_refs_status",
            ("actor_refs", "character_refs", "relationship_dependency_refs", "knowledge_state_refs"),
        ),
        (
            "world-creative", "worldbuilding", "world_refs_status",
            ("location_refs", "world_rule_refs", "system_refs", "faction_refs", "object_refs"),
        ),
    ):
        status = getattr(inputs, field)
        has_dependency = any(getattr(inputs, name) for name in dependency_fields)
        if component == "character-creative" and inputs.dialogue_required is True:
            has_dependency = True
        if status == "present" or has_dependency:
            outcome, reason = "include", f"{field}_or_typed_dependency_present"
            included.append(skill_id)
        elif status == "absent":
            outcome, reason = "exclude", f"{field}_absent"
        else:
            outcome, reason = "fail_safe_include", f"{field}_{status}_fail_safe"
            included.append(skill_id)
            fail_safe = True
        rows.append(ComponentLoadDecisionV1(
            component_id=component, outcome=outcome, reason_code=reason,
        ))
    payload = {
        "schema": "SkillLoadDecisionV1", "version": 1,
        "inputs": inputs,
        "components": tuple(rows),
        "included_skill_ids": tuple(included), "fail_safe_used": fail_safe,
    }
    return SkillLoadDecisionV1.model_validate({
        **payload, "decision_id": stable_id("skill-load", "SkillLoadDecisionV1", _json_value(payload)),
    })


_STORY_SECTION_SPECS = {
    "story-workflow": _SectionSpec("story-init", "SKILL.md", "Workflow"),
}
_PLOT_SECTION_SPECS = {
    "plot-choose": _SectionSpec("plot-structure", "SKILL.md", "Choosing a Story Structure"),
    "plot-timeline": _SectionSpec("plot-structure", "SKILL.md", "Timeline Management"),
    "plot-foreshadow": _SectionSpec("plot-structure", "SKILL.md", "Foreshadowing Tracking"),
    "plot-arc-setup": _SectionSpec("plot-structure", "references/arc-template.md", "Setup"),
    "plot-arc-rise": _SectionSpec("plot-structure", "references/arc-template.md", "Rising Action"),
    "plot-arc-climax": _SectionSpec("plot-structure", "references/arc-template.md", "Climax"),
    "plot-arc-resolution": _SectionSpec("plot-structure", "references/arc-template.md", "Resolution"),
    "plot-arc-foreshadow": _SectionSpec("plot-structure", "references/arc-template.md", "Foreshadowing"),
    "plot-promise-setup": _SectionSpec("plot-structure", "references/promise-template.md", "Setup"),
    "plot-promise-payoff": _SectionSpec("plot-structure", "references/promise-template.md", "Payoff"),
    "plot-question": _SectionSpec("plot-structure", "references/question-template.md", "Question"),
    "plot-question-resolution": _SectionSpec("plot-structure", "references/question-template.md", "Resolution Plan"),
    **{
        f"plot-model-{index}": _SectionSpec("plot-structure", "references/structure-models.md", heading)
        for index, heading in enumerate((
            "Three-Act Structure", "Hero's Journey (Campbell/Vogler)", "Save the Cat (Snyder)",
            "Kishotenketsu", "Five-Act Structure (Shakespeare)", "Choosing a Structure",
        ), start=1)
    },
}
_CHAR_SECTION_SPECS = {
    "char-create": _SectionSpec("character-management", "SKILL.md", "Creating a Character", applicability="conditional"),
    **{
        f"char-{index}": _SectionSpec("character-management", "references/character-template.md", heading, applicability="conditional")
        for index, heading in enumerate((
            "Appearance", "Personality & Traits", "Backstory", "Motivations & Goals",
            "Voice & Speech Patterns", "Character Arc",
        ), start=1)
    },
    **{
        f"char-rel-{index}": _SectionSpec("character-management", "references/relationship-types.md", heading, applicability="conditional")
        for index, heading in enumerate(("Family", "Social", "Story Role"), start=1)
    },
}
_WORLD_SECTION_SPECS = {
    **{
        f"world-create-{index}": _SectionSpec("worldbuilding", "SKILL.md", heading, applicability="conditional")
        for index, heading in enumerate((
            "Creating a Location", "Creating a System", "Creating A Faction", "Creating An Artifact",
        ), start=1)
    },
    **{
        f"world-location-{index}": _SectionSpec("worldbuilding", "references/location-template.md", heading, applicability="conditional")
        for index, heading in enumerate(("Description", "History", "Culture & Customs", "Notable Features", "Current State"), start=1)
    },
    **{
        f"world-system-{index}": _SectionSpec("worldbuilding", "references/system-template.md", heading, applicability="conditional")
        for index, heading in enumerate(("Overview", "Rules & Limitations", "History", "Practitioners", "Impact on Society"), start=1)
    },
    **{
        f"world-faction-{index}": _SectionSpec("worldbuilding", "references/faction-template.md", heading, applicability="conditional")
        for index, heading in enumerate(("Purpose", "Power Base", "Members", "Conflicts"), start=1)
    },
    **{
        f"world-artifact-{index}": _SectionSpec("worldbuilding", "references/artifact-template.md", heading, applicability="conditional")
        for index, heading in enumerate(("Description", "Function", "History", "Current State"), start=1)
    },
    **{
        f"world-type-{index}": _SectionSpec("worldbuilding", "references/world-element-types.md", heading, applicability="conditional")
        for index, heading in enumerate((
            "Magic System", "Political System", "Technology System", "Religion System",
            "Economic System", "Military System", "Social System", "Education System",
        ), start=1)
    },
}

_RULE_SPECS = (
    _RuleSpec("PLOT_STRUCTURE_ADAPTATION", "plot-structure", "Choose and adapt a structure to the story; structure models are guides rather than immutable formulas.", tuple(key for key in _PLOT_SECTION_SPECS if key.startswith("plot-model-")) + ("plot-choose",), ("structure_adaptation",)),
    _RuleSpec("PLOT_CAUSAL_ESCALATION", "plot-structure", "Within the frozen event role, realize actor choice and action, causal escalation, and the resulting local state change toward resolution.", ("plot-arc-setup", "plot-arc-rise", "plot-arc-climax", "plot-arc-resolution"), ("causal_intent", "escalation")),
    _RuleSpec("PLOT_SETUP_PAYOFF_INTENT", "plot-structure", "Preserve deliberate setup, question, foreshadowing, and payoff intent across the plan.", ("plot-foreshadow", "plot-arc-foreshadow", "plot-promise-setup", "plot-promise-payoff", "plot-question", "plot-question-resolution"), ("setup_payoff",)),
    _RuleSpec("PLOT_PACING_INTENT", "plot-structure", "Pace action and progression under the frozen formal event role without changing formal chronology or ownership.", ("plot-timeline",), ("pacing_intent",)),
    _RuleSpec("CHARACTER_MOTIVATION", "character-management", "Realize external wants, internal needs, relevant biography, formative pressures, and their conflict in character action.", ("char-create", "char-3", "char-4"), ("motivation", "relevant_biography")),
    _RuleSpec("CHARACTER_VOICE", "character-management", "Keep vocabulary, sentence shape, verbal habits, and tone distinct for referenced actors.", ("char-create", "char-5"), ("voice",)),
    _RuleSpec("CHARACTER_ARC", "character-management", "Connect starting state, turning points, and ending state without overriding frozen event outcomes.", ("char-create", "char-6"), ("character_arc",)),
    _RuleSpec("CHARACTER_RELATIONSHIP_NUANCE", "character-management", "Use the referenced relationship role to shape pressure, contrast, trust, and subtext without inventing authority.", ("char-rel-1", "char-rel-2", "char-rel-3"), ("relationship_nuance",)),
    _RuleSpec("WORLD_SENSORY_SPECIFICITY", "worldbuilding", "Propose concrete sensory and interactive location details that remain local to event realization.", ("world-create-1", "world-location-1", "world-location-4"), ("sensory_specificity", "location_realization")),
    _RuleSpec("WORLD_COST_AND_LIMIT", "worldbuilding", "When a system matters, propose specific costs, limits, consequences, and social impact without creating Canon.", ("world-create-2", "world-system-2", "world-system-5", "world-type-1", "world-type-3"), ("world_cost_limit",)),
    _RuleSpec("WORLD_FACTION_PRESSURE", "worldbuilding", "Use faction purpose, power base, membership, and conflicts as proposal-only local pressure.", ("world-create-3", "world-faction-1", "world-faction-2", "world-faction-3", "world-faction-4"), ("faction_pressure",)),
    _RuleSpec("WORLD_CURRENT_STATE", "worldbuilding", "Ground realization in story-relevant history, culture, and current tensions while preserving existing authority.", ("world-location-2", "world-location-3", "world-location-5", "world-artifact-2", "world-artifact-4"), ("world_current_state",)),
    _RuleSpec("WORLD_ARTIFACT_DETAIL", "worldbuilding", "Treat an artifact as a proposal-only story element with recognizable form, bounded function, relevant history, and current risk.", ("world-create-4", "world-artifact-1", "world-artifact-2", "world-artifact-3", "world-artifact-4"), ("artifact_realization",)),
)

RESTORED_CREATIVE_RULE_IDS = (
    "MOTIVE_ACTION",
    "VOICE_RELATION",
    "CAUSAL_AFFORDANCE",
    "PRESSURE_BEATS",
    "SETUP_PAYOFF",
    "FRAME_BRIDGE",
    "DRAFT_SCENE",
    "ANTI_TAXONOMY",
)

_RESTORED_CREATIVE_RULE_SPECS = (
    _RuleSpec(
        "MOTIVE_ACTION",
        "character-management",
        "Render competing wants and needs through choices, tactics, concessions, and costs; do not name the taxonomy in the artifact.",
        ("char-create", "char-3", "char-4"),
        ("motivation", "subtext_dramatization", "anti_template"),
        "true_narrative_invariant",
        6,
    ),
    _RuleSpec(
        "VOICE_RELATION",
        "character-management",
        "Differentiate actors through word choice, rhythm, evasions, behavior, and relationship pressure that changes available actions.",
        ("char-create", "char-5", "char-rel-3"),
        ("voice", "relationship_consequence", "subtext_dramatization"),
        "true_narrative_invariant",
        6,
    ),
    _RuleSpec(
        "CAUSAL_AFFORDANCE",
        "worldbuilding",
        "Select a small number of concrete sensory or mechanical affordances that constrain action, can be interacted with, and can carry a later payoff.",
        ("world-create-1", "world-location-1", "world-location-4"),
        ("world_specificity", "sensory_realization", "setup_payoff"),
        "true_narrative_invariant",
        6,
    ),
    _RuleSpec(
        "PRESSURE_BEATS",
        "plot-structure",
        "Realize escalation as opposed tactics, obstacle, reaction, and reversal rather than explanatory summary.",
        ("plot-arc-rise", "plot-arc-climax"),
        ("conflict_pacing", "draft_handoff", "subtext_dramatization"),
        "true_narrative_invariant",
        6,
    ),
    _RuleSpec(
        "SETUP_PAYOFF",
        "plot-structure",
        "Plant a concrete question or affordance, preserve its dependency, and pay it off through later action inside the bounded event.",
        ("plot-promise-setup", "plot-promise-payoff", "plot-question", "plot-question-resolution"),
        ("setup_payoff", "draft_handoff"),
        "true_narrative_invariant",
        6,
    ),
    _RuleSpec(
        "FRAME_BRIDGE",
        "story-init",
        "When confirmed values exist, bridge premise, theme, tone, genre, POV, and tense without guessing or asking questions.",
        ("story-workflow",),
        ("tone_genre_fidelity", "pov_consistency", "tense_consistency", "draft_handoff"),
        "true_narrative_invariant",
        6,
    ),
    _RuleSpec(
        "DRAFT_SCENE",
        "cross-skill",
        "Produce Draft-usable spatial beats with action/reaction, resistance, reversal, and a terminal image; avoid synopsis-only realization.",
        ("plot-arc-setup", "plot-arc-rise", "plot-arc-climax", "plot-arc-resolution"),
        ("draft_handoff", "conflict_pacing", "sensory_realization"),
        "true_narrative_invariant",
        6,
    ),
    _RuleSpec(
        "ANTI_TAXONOMY",
        "cross-skill",
        "Use capability labels only for reasoning; never emit labels such as external want, internal need, or local state change as explanatory prose.",
        ("char-create", "plot-arc-resolution"),
        ("anti_template", "subtext_dramatization"),
        "true_narrative_invariant",
        6,
    ),
)


CHARACTER_HEAVY_CREATIVE_CORE_V2_RULE_TEXT = {
    "MOTIVE_ACTION": (
        "Link formative pressure to present want and concealed need; externalize conflict "
        "through opposed tactics, costly choice, observable reaction, and next-beat "
        "consequence; never name labels."
    ),
    "VOICE_RELATION": (
        "Sustain distinct voice through diction, rhythm, evasion, gesture, and withheld "
        "explanation; make relationship pressure change tactics, costs, trust, and available "
        "action."
    ),
    "DRAFT_SCENE": (
        "Build a continuous Draft-usable microchain: spatial stimulus, opposed action, "
        "reaction, resistance, reversal, costly choice, and terminal image; replace "
        "interpretive summary with behavior."
    ),
    "ANTI_TAXONOMY": (
        "Keep labels in reasoning only; replace abstractions about wants, needs, instincts, "
        "strain, or local change with choice, dialogue, evasion, gesture, or consequence."
    ),
}

_DEMAND_AWARE_PROFILE_STRATEGY: dict[str, DemandAwareProfileStrategy] = {
    "character-heavy": "RESTORED_SKILL_V2_CHARACTER_CORE_V2",
    "world-heavy": "UNCHANGED_PENDING_PAIR2",
    "conflict-pacing-heavy": "UNCHANGED_PENDING_PAIR3",
    "setup-payoff-heavy": "UNCHANGED_PENDING_PAIR4",
    "mixed": "UNCHANGED_PENDING_PAIR5",
}


def resolve_demand_aware_creative_profile(
    pair_creative_demand_class: str,
) -> DemandAwareCreativeProfileResolutionV1:
    """Resolve only sealed demand-class facts; unknown values cannot select a profile."""

    strategy: DemandAwareProfileStrategy = _DEMAND_AWARE_PROFILE_STRATEGY.get(
        pair_creative_demand_class, "FAIL_CLOSED_NO_PROFILE_SUBSTITUTION",
    )
    return DemandAwareCreativeProfileResolutionV1(
        pair_creative_demand_class=pair_creative_demand_class,
        profile_strategy=strategy,
        substitution_allowed=strategy == "RESTORED_SKILL_V2_CHARACTER_CORE_V2",
        changed_rule_ids=(
            tuple(CHARACTER_HEAVY_CREATIVE_CORE_V2_RULE_TEXT)
            if strategy == "RESTORED_SKILL_V2_CHARACTER_CORE_V2" else ()
        ),
    )


def _character_heavy_creative_core_v2_rule_specs() -> tuple[_RuleSpec, ...]:
    return tuple(
        replace(spec, text=CHARACTER_HEAVY_CREATIVE_CORE_V2_RULE_TEXT[spec.rule_id])
        if spec.rule_id in CHARACTER_HEAVY_CREATIVE_CORE_V2_RULE_TEXT else spec
        for spec in _RESTORED_CREATIVE_RULE_SPECS
    )


def _all_section_specs() -> dict[str, _SectionSpec]:
    return {
        **_STORY_SECTION_SPECS,
        **_PLOT_SECTION_SPECS,
        **_CHAR_SECTION_SPECS,
        **_WORLD_SECTION_SPECS,
    }


def _compile_sections(
    bundle_root: Path,
    selected_keys: tuple[str, ...],
    rule_specs: tuple[_RuleSpec, ...],
) -> tuple[SourceSectionBindingV1, ...]:
    all_specs = _all_section_specs()
    rule_map = {
        key: tuple(rule.rule_id for rule in rule_specs if key in rule.section_keys)
        for key in selected_keys
    }
    sections = []
    for key in selected_keys:
        spec = all_specs[key]
        if any(
            rule.classification == "true_narrative_invariant" and key in rule.section_keys
            for rule in rule_specs
        ):
            spec = _SectionSpec(
                skill_id=spec.skill_id,
                relative_path=spec.relative_path,
                heading=spec.heading,
                classification=spec.classification,
                applicability="always",
                ordinal=spec.ordinal,
            )
        sections.append(_extract_section(bundle_root, spec, rule_map[key]))
    return tuple(sections)


def _compile_rules(
    sections: tuple[SourceSectionBindingV1, ...],
    rule_specs: tuple[_RuleSpec, ...],
) -> tuple[ProfileRuleV1, ...]:
    by_key: dict[str, str] = {}
    all_specs = _all_section_specs()
    identity_to_id = {
        (item.skill_id, item.relative_source_path, item.heading, item.heading_ordinal): item.section_id
        for item in sections
    }
    for key, spec in all_specs.items():
        identity = (spec.skill_id, f"{spec.skill_id}/{spec.relative_path}", spec.heading, spec.ordinal)
        if identity in identity_to_id:
            by_key[key] = identity_to_id[identity]
    return tuple(
        ProfileRuleV1(
            rule_id=spec.rule_id, skill_id=spec.skill_id, text=spec.text,
            source_section_ids=tuple(by_key[key] for key in spec.section_keys if key in by_key),
            classification=spec.classification,
            authority_level=spec.authority_level,
            coverage_categories=spec.categories,
        )
        for spec in rule_specs
        if all(key in by_key for key in spec.section_keys)
    )


def _definition_payload(
    *, profile_id: str, phase: str, source_skill_ids: tuple[str, ...],
    source_hashes: dict[str, str], sections: tuple[SourceSectionBindingV1, ...],
    rules: tuple[ProfileRuleV1, ...], conditional: tuple[ConditionalComponentV1, ...],
    bridge: ExistingProjectNarrativeBridgeV1 | None, decision: SkillLoadDecisionV1 | None,
    precedence: SkillPrecedencePolicyV1, budget: SkillContextBudgetPolicyV1,
    world_policy: WorldCreativeProposalPolicyV1,
) -> dict[str, Any]:
    return {
        "profile_id": profile_id, "phase": phase,
        "source_bundle_manifest_sha256": EXPECTED_BUNDLE_MANIFEST_SHA256,
        "source_skill_ids": source_skill_ids,
        "source_skill_sha256": source_hashes,
        "included_sections": sections,
        "rules": tuple(item.model_dump(mode="json", by_alias=True) for item in rules),
        "excluded_section_categories": (
            "initialization_scaffolding", "filesystem_mutation", "registry_maintenance",
            "cli_execution", "cross_link_writes", "template_frontmatter",
        ),
        "conditional_components": tuple(item.model_dump(mode="json", by_alias=True) for item in conditional),
        "narrative_bridge": bridge.model_dump(mode="json", by_alias=True) if bridge else None,
        "decision_inputs": (
            (decision.inputs.model_dump(mode="json", by_alias=True),) if decision else ()
        ),
        "decision_result": decision.model_dump(mode="json", by_alias=True) if decision else None,
        "precedence_policy_sha256": precedence.policy_sha256,
        "context_budget_policy_sha256": budget.policy_sha256,
        "world_creative_policy_sha256": world_policy.policy_sha256,
    }


def _build_profile(
    *, bundle_root: Path, profile_id: Literal[
        "CURRENT_PLANNING_V1_COMPAT_PROFILE_V1",
        "PLANNING_V2_EVENT_REALIZATION_PROFILE_V1",
        "RESTORED_SKILL_V2_CHARACTER_CORE_V2",
    ],
    phase: Literal["planning_v1", "planning_v2_event_realization"], selected_keys: tuple[str, ...],
    source_skill_ids: tuple[str, ...], conditional: tuple[ConditionalComponentV1, ...],
    bridge: ExistingProjectNarrativeBridgeV1 | None, decision: SkillLoadDecisionV1 | None,
    rule_specs: tuple[_RuleSpec, ...] = _RULE_SPECS,
    context_budget_policy: SkillContextBudgetPolicyV1 | None = None,
) -> RuntimeSkillProfileV1:
    verification = verify_source_bundle(bundle_root)
    sections = _compile_sections(bundle_root, selected_keys, rule_specs)
    rules = _compile_rules(sections, rule_specs)
    mandatory_rules = tuple(
        rule for rule in rules if rule.classification == "true_narrative_invariant"
    )
    advisory_rules = tuple(rule for rule in rules if rule.classification == "advisory_creative")
    canonical_rules = (*mandatory_rules, *advisory_rules)
    precedence = precedence_policy_v1()
    budget = context_budget_policy or context_budget_policy_v1()
    world_policy = world_creative_policy_v1()
    definition_payload = _definition_payload(
        profile_id=profile_id, phase=phase, source_skill_ids=source_skill_ids,
        source_hashes={key: verification["skill_hashes"][key] for key in source_skill_ids},
        sections=sections, rules=canonical_rules, conditional=conditional, bridge=bridge,
        decision=decision, precedence=precedence, budget=budget, world_policy=world_policy,
    )
    definition_sha = canonical_sha256("RuntimeSkillProfileDefinitionV1", definition_payload)
    rendered, receipt = render_skill_context(
        advisory_rules, mandatory_rules, budget, profile_hash=definition_sha,
    )
    if not receipt.dispatch_allowed or receipt.status != "NONE" or receipt.excluded_rule_ids:
        raise ValueError("default profile exceeds context budget without complete creative coverage")
    prompt_binding = canonical_sha256("RuntimeSkillPromptBindingV1", {
        "definition_sha256": definition_sha,
        "rendered_context_sha256": receipt.rendered_context_sha256,
        "bridge_id": bridge.bridge_id if bridge else None,
        "load_decision_id": decision.decision_id if decision else None,
    })
    payload = {
        "schema": "RuntimeSkillProfileV1", "version": 1,
        "profile_id": profile_id, "stage": "planning",
        "substage": "planning_v1_compat" if phase == "planning_v1" else "planning_v2_event_realization",
        "slice_id": "not_applicable" if phase == "planning_v1" else "EVENT_REALIZATION_UNIT_SHADOW_V1",
        "source_bundle_manifest_sha256": EXPECTED_BUNDLE_MANIFEST_SHA256,
        "source_skill_ids": source_skill_ids,
        "source_skill_sha256": {key: verification["skill_hashes"][key] for key in source_skill_ids},
        "included_sections": sections,
        "included_rule_ids": tuple(item.rule_id for item in canonical_rules),
        "mandatory_rules": mandatory_rules,
        "advisory_rules": advisory_rules,
        "excluded_section_categories": definition_payload["excluded_section_categories"],
        "conditional_components": conditional,
        "decision_inputs": ((decision.inputs,) if decision else ()),
        "decision_result": decision,
        "authority_revision": decision.inputs.authority_revision if decision else "unknown",
        "authority_hash": decision.inputs.authority_hash if decision else "not_bound_in_offline_fixture",
        "precedence_policy": precedence,
        "context_budget_policy": budget,
        "world_creative_policy": world_policy,
        "narrative_bridge": bridge,
        "context_budget": budget.maximum_characters,
        "mandatory_budget": budget.mandatory_character_budget,
        "advisory_budget": budget.advisory_character_budget,
        "truncation_status": receipt.status,
        "prompt_binding_sha256": prompt_binding, "definition_sha256": definition_sha,
        "shadow_only": True, "production_reachable": False,
    }
    return RuntimeSkillProfileV1.model_validate({
        **payload,
        "canonical_profile_sha256": canonical_sha256("RuntimeSkillProfileV1", _json_value(payload)),
    })


def build_planning_v1_compat_profile(bundle_root: Path, bridge_values: dict[str, str | None]) -> RuntimeSkillProfileV1:
    used = {key for rule in _RULE_SPECS for key in rule.section_keys}
    keys = tuple(key for key in (*_PLOT_SECTION_SPECS, *_CHAR_SECTION_SPECS, *_WORLD_SECTION_SPECS) if key in used)
    return _build_profile(
        bundle_root=bundle_root, profile_id="CURRENT_PLANNING_V1_COMPAT_PROFILE_V1",
        phase="planning_v1", selected_keys=keys, source_skill_ids=PLANNING_SKILL_IDS,
        conditional=(), bridge=make_narrative_bridge(bridge_values), decision=None,
        rule_specs=_RULE_SPECS,
    )


def build_planning_v2_event_realization_profile(
    bundle_root: Path, inputs: SkillLoadDecisionInputsV1,
) -> RuntimeSkillProfileV1:
    decision = resolve_conditional_load(inputs)
    v2_rules = tuple(
        rule for rule in _RULE_SPECS
        if rule.rule_id != "PLOT_STRUCTURE_ADAPTATION"
        and rule.skill_id in decision.included_skill_ids
    )
    used = {key for rule in v2_rules for key in rule.section_keys}
    selected = tuple(key for key in _all_section_specs() if key in used)
    sections = _compile_sections(bundle_root, selected, v2_rules)
    rules = _compile_rules(sections, v2_rules)
    section_ids = {
        skill_id: tuple(item.section_id for item in sections if item.skill_id == skill_id)
        for skill_id in ("character-management", "worldbuilding")
    }
    rule_ids = {
        skill_id: tuple(item.rule_id for item in rules if item.skill_id == skill_id)
        for skill_id in ("character-management", "worldbuilding")
    }
    conditional = tuple(
        ConditionalComponentV1(
            component_id=component_id, skill_id=skill_id, trigger_field=trigger,
            rule_ids=rule_ids[skill_id], section_ids=section_ids[skill_id],
        )
        for component_id, skill_id, trigger in (
            ("character-creative", "character-management", "actor_refs_status"),
            ("world-creative", "worldbuilding", "world_refs_status"),
        )
    )
    return _build_profile(
        bundle_root=bundle_root, profile_id="PLANNING_V2_EVENT_REALIZATION_PROFILE_V1",
        phase="planning_v2_event_realization", selected_keys=selected,
        source_skill_ids=tuple(decision.included_skill_ids), conditional=conditional,
        bridge=None, decision=decision, rule_specs=v2_rules,
    )


def _build_planning_v2_event_realization_profile_restored(
    bundle_root: Path,
    inputs: SkillLoadDecisionInputsV1,
    *,
    restored_rule_specs: tuple[_RuleSpec, ...],
    profile_id: Literal[
        "PLANNING_V2_EVENT_REALIZATION_PROFILE_V1",
        "RESTORED_SKILL_V2_CHARACTER_CORE_V2",
    ],
    context_budget_policy: SkillContextBudgetPolicyV1 | None = None,
) -> RuntimeSkillProfileV1:
    decision = resolve_conditional_load(inputs)
    included = set(decision.included_skill_ids)
    conditional_rules = tuple(
        rule for rule in _RULE_SPECS
        if rule.rule_id != "PLOT_STRUCTURE_ADAPTATION" and rule.skill_id in included
    )
    active_rules = (*restored_rule_specs, *conditional_rules)
    used = {key for rule in active_rules for key in rule.section_keys}
    selected = tuple(key for key in _all_section_specs() if key in used)
    sections = _compile_sections(bundle_root, selected, active_rules)
    compiled_conditional_rules = _compile_rules(sections, conditional_rules)
    rule_ids = {
        skill_id: tuple(item.rule_id for item in compiled_conditional_rules if item.skill_id == skill_id)
        for skill_id in ("character-management", "worldbuilding")
    }
    section_ids = {
        skill_id: tuple(dict.fromkeys(
            section_id
            for rule in compiled_conditional_rules if rule.skill_id == skill_id
            for section_id in rule.source_section_ids
        ))
        for skill_id in ("character-management", "worldbuilding")
    }
    conditional = tuple(
        ConditionalComponentV1(
            component_id=component_id, skill_id=skill_id, trigger_field=trigger,
            rule_ids=rule_ids[skill_id], section_ids=section_ids[skill_id],
        )
        for component_id, skill_id, trigger in (
            ("character-creative", "character-management", "actor_refs_status"),
            ("world-creative", "worldbuilding", "world_refs_status"),
        )
    )
    return _build_profile(
        bundle_root=bundle_root, profile_id=profile_id,
        phase="planning_v2_event_realization", selected_keys=selected,
        source_skill_ids=PLANNING_SKILL_IDS, conditional=conditional,
        bridge=make_narrative_bridge({}), decision=decision,
        rule_specs=active_rules, context_budget_policy=context_budget_policy,
    )


def build_planning_v2_event_realization_profile_restored(
    bundle_root: Path, inputs: SkillLoadDecisionInputsV1,
) -> RuntimeSkillProfileV1:
    return _build_planning_v2_event_realization_profile_restored(
        bundle_root,
        inputs,
        restored_rule_specs=_RESTORED_CREATIVE_RULE_SPECS,
        profile_id="PLANNING_V2_EVENT_REALIZATION_PROFILE_V1",
    )


def build_planning_v2_event_realization_profile_demand_aware(
    bundle_root: Path,
    inputs: SkillLoadDecisionInputsV1,
    *,
    pair_creative_demand_class: str,
) -> RuntimeSkillProfileV1:
    resolution = resolve_demand_aware_creative_profile(pair_creative_demand_class)
    if resolution.profile_strategy == "FAIL_CLOSED_NO_PROFILE_SUBSTITUTION":
        raise ValueError("FAIL_CLOSED_NO_PROFILE_SUBSTITUTION")
    if resolution.profile_strategy != "RESTORED_SKILL_V2_CHARACTER_CORE_V2":
        return build_planning_v2_event_realization_profile_restored(bundle_root, inputs)
    return _build_planning_v2_event_realization_profile_restored(
        bundle_root,
        inputs,
        restored_rule_specs=_character_heavy_creative_core_v2_rule_specs(),
        profile_id="RESTORED_SKILL_V2_CHARACTER_CORE_V2",
        context_budget_policy=character_heavy_context_budget_policy_v2(),
    )


def render_skill_context(
    advisory_rules: tuple[ProfileRuleV1, ...] | list[ProfileRuleV1],
    mandatory_rules: tuple[ProfileRuleV1, ...] | list[ProfileRuleV1],
    policy: SkillContextBudgetPolicyV1,
    *, profile_hash: str = "not_bound_in_offline_fixture",
) -> tuple[str, SkillContextTruncationReceiptV1]:
    def render(rule: ProfileRuleV1) -> str:
        return f"[{rule.rule_id}] {rule.text}\n"

    mandatory_chunks = [render(rule) for rule in mandatory_rules]
    mandatory_chars = sum(map(len, mandatory_chunks))
    if mandatory_chars > policy.mandatory_character_budget or mandatory_chars > policy.maximum_characters:
        source_ids = tuple(rule.rule_id for rule in (*mandatory_rules, *advisory_rules))
        original = sum(len(render(rule)) for rule in (*mandatory_rules, *advisory_rules))
        payload = {
            "schema": "SkillContextTruncationReceiptV1",
            "status": "BLOCKED_MANDATORY_OVERFLOW", "profile_hash": profile_hash,
            "input_hash": canonical_sha256("SkillContextBudgetInputV1", source_ids),
            "source_rule_ids": source_ids, "included_rule_ids": (),
            "excluded_rule_ids": tuple(rule.rule_id for rule in advisory_rules),
            "original_characters": original,
            "mandatory_characters": mandatory_chars, "advisory_characters": 0,
            "total_characters": 0, "estimated_tokens": 0,
            "rendered_context_sha256": None, "mandatory_overflow": True,
            "truncation_reason": "mandatory_budget_exceeded", "dispatch_allowed": False,
            "ordering_policy": "priority_then_source_skill_then_section_then_rule_id",
            "whole_rule_only": True,
        }
        return "", SkillContextTruncationReceiptV1.model_validate({
            **payload, "receipt_sha256": canonical_sha256("SkillContextTruncationReceiptV1", payload),
        })
    selected = list(mandatory_chunks)
    included = [rule.rule_id for rule in mandatory_rules]
    omitted: list[str] = []
    advisory_chars = 0
    for rule in advisory_rules:
        chunk = render(rule)
        if (
            advisory_chars + len(chunk) <= policy.advisory_character_budget
            and mandatory_chars + advisory_chars + len(chunk) <= policy.maximum_characters
        ):
            selected.append(chunk)
            included.append(rule.rule_id)
            advisory_chars += len(chunk)
        else:
            omitted.append(rule.rule_id)
    rendered = "".join(selected)
    source_ids = tuple(rule.rule_id for rule in (*mandatory_rules, *advisory_rules))
    original = sum(len(render(rule)) for rule in (*mandatory_rules, *advisory_rules))
    payload = {
        "schema": "SkillContextTruncationReceiptV1",
        "status": ("ADVISORY_SHED" if omitted and advisory_chars == 0 else "ADVISORY_TRUNCATED") if omitted else "NONE",
        "profile_hash": profile_hash,
        "input_hash": canonical_sha256("SkillContextBudgetInputV1", source_ids),
        "source_rule_ids": source_ids,
        "included_rule_ids": tuple(included), "excluded_rule_ids": tuple(omitted),
        "original_characters": original,
        "mandatory_characters": mandatory_chars, "advisory_characters": advisory_chars,
        "total_characters": len(rendered), "estimated_tokens": estimate_input_tokens(rendered),
        "rendered_context_sha256": hashlib.sha256(rendered.encode(UTF8)).hexdigest(),
        "mandatory_overflow": False,
        "truncation_reason": "advisory_budget_exceeded" if omitted else "none",
        "ordering_policy": "priority_then_source_skill_then_section_then_rule_id",
        "dispatch_allowed": True, "whole_rule_only": True,
    }
    return rendered, SkillContextTruncationReceiptV1.model_validate({
        **payload, "receipt_sha256": canonical_sha256("SkillContextTruncationReceiptV1", payload),
    })


_KNOWN_MANDATORY_CLASSIFICATIONS = {
    "RULE-3FCD9AEB9A30F19A": "TEMPLATE_FALSE_POSITIVE",
    "RULE-72668C0A0945572B": "OPERATIONAL_INSTRUCTION",
    "RULE-E39AA5723E9297B8": "TEMPLATE_FALSE_POSITIVE",
    "RULE-4B1E7AC4A6C3302A": "TEMPLATE_FALSE_POSITIVE",
    "RULE-80208D851D469857": "OPERATIONAL_INSTRUCTION",
    "RULE-CCA1F7BA473A44E0": "OPERATIONAL_INSTRUCTION",
    "RULE-D337C6BC2BBD6EAE": "OPERATIONAL_INSTRUCTION",
}


def classify_current_mandatory_rules(bundle_root: Path) -> tuple[MandatoryRuleClassificationV2, ...]:
    from novel_flywheel.context_packet import extract_mandatory_rules

    prompt = "\n\n".join(
        (bundle_root / skill_id / "SKILL.md").read_text(encoding=UTF8)
        for skill_id in PLANNING_SKILL_IDS
    )
    rules, duplicate_count = extract_mandatory_rules("", prompt, stage="planning")
    if duplicate_count != 2 or {item.rule_id for item in rules} != set(_KNOWN_MANDATORY_CLASSIFICATIONS):
        raise ValueError("unknown mandatory-rule materialization; fail closed")
    counts: dict[str, int] = {}
    for skill_id in PLANNING_SKILL_IDS:
        skill_rules, _ = extract_mandatory_rules(
            "", (bundle_root / skill_id / "SKILL.md").read_text(encoding=UTF8), stage="planning",
        )
        for item in skill_rules:
            counts[item.rule_id] = counts.get(item.rule_id, 0) + 1
    return tuple(
        MandatoryRuleClassificationV2(
            rule_id=item.rule_id, text_sha256=hashlib.sha256(item.text.encode(UTF8)).hexdigest(),
            occurrence_count=counts[item.rule_id],
            classification=_KNOWN_MANDATORY_CLASSIFICATIONS[item.rule_id],  # type: ignore[arg-type]
        )
        for item in rules
    )


def creative_coverage(profile: RuntimeSkillProfileV1) -> tuple[str, ...]:
    return tuple(sorted({category for rule in profile.advisory_rules for category in rule.coverage_categories}))


_CREATIVE_CAPABILITY_CHECKS = (
    ("motivation_action", "MOTIVE_ACTION", ("competing wants and needs", "choices", "tactics", "concessions", "costs")),
    ("voice_distinctiveness", "VOICE_RELATION", ("word choice", "rhythm", "evasions", "behavior")),
    ("relationship_consequence", "VOICE_RELATION", ("relationship pressure", "changes available actions")),
    ("world_specificity", "CAUSAL_AFFORDANCE", ("concrete sensory or mechanical affordances", "constrain action")),
    ("sensory_affordance", "CAUSAL_AFFORDANCE", ("interacted with", "later payoff")),
    ("conflict_pacing", "PRESSURE_BEATS", ("opposed tactics", "obstacle", "reaction", "reversal")),
    ("setup_payoff_dependency", "SETUP_PAYOFF", ("plant a concrete question or affordance", "preserve its dependency", "pay it off through later action")),
    ("subtext_dramatization", "PRESSURE_BEATS", ("rather than explanatory summary",)),
    ("draft_handoff", "DRAFT_SCENE", ("spatial beats", "action/reaction", "resistance", "terminal image", "avoid synopsis-only")),
    ("anti_template", "ANTI_TAXONOMY", ("capability labels only for reasoning", "never emit labels", "explanatory prose")),
    ("narrative_frame", "FRAME_BRIDGE", ("confirmed values", "premise", "theme", "tone", "genre", "pov", "tense", "without guessing")),
)


def audit_creative_capability_presence(rendered_context: str) -> dict[str, Any]:
    """Check actionable restored semantics; capability names alone never pass."""

    normalized = " ".join(rendered_context.casefold().split())
    checks = []
    for check_id, rule_id, required_phrases in _CREATIVE_CAPABILITY_CHECKS:
        rule_present = f"[{rule_id.casefold()}]" in normalized
        missing = tuple(
            phrase for phrase in required_phrases if phrase.casefold() not in normalized
        )
        checks.append({
            "check_id": check_id,
            "rule_id": rule_id,
            "rule_present": rule_present,
            "missing_semantic_phrases": missing,
            "status": "pass" if rule_present and not missing else "fail",
        })
    passed = sum(item["status"] == "pass" for item in checks)
    return {
        "schema": "SkillV2CreativeCapabilityPresenceAuditV1",
        "gate_type": "actionable_creative_decomposition_presence",
        "generated_prose_quality_claimed": False,
        "check_count": len(checks),
        "passed_check_count": passed,
        "checks": checks,
        "overall_status": "pass" if passed == len(checks) else "fail",
    }


def profile_contains_runtime_owned_responsibility(profile: RuntimeSkillProfileV1) -> bool:
    return any(
        rule.owner != "model_creative"
        or rule.authority_level != (6 if rule.classification == "true_narrative_invariant" else 7)
        for rule in (*profile.mandatory_rules, *profile.advisory_rules)
    )


def model_schema() -> dict[str, Any]:
    return RuntimeSkillProfileV1.model_json_schema(by_alias=True)
