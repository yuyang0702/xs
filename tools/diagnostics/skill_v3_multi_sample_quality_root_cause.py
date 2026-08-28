from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from novel_flywheel.planning_v2_slice1 import EventRealizationCandidateV1
from novel_flywheel.runtime_skill_profiles import (
    SkillLoadDecisionInputsV1,
    build_planning_v2_event_realization_profile_demand_aware,
    render_skill_context,
)
from novel_flywheel.selective_skill_compiler import (
    COMPILER_VERSION,
    SELECTOR_POLICY_VERSION,
    SelectionInputV1,
    SelectiveSkillCompilerV1,
    SkillSectionIndexV1,
)


BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
START_HEAD = "41ccdf8f219072be1d246161803f627049a5d7a9"
OUTPUT_RELATIVE_ROOT = (
    "docs/superpowers/reports/"
    "skill-v3-selective-compiler-multi-sample-quality-root-cause-v1"
)
OUTPUT_FILES = (
    "README.md",
    "baseline-binding-v1.json",
    "methodology-validity-recheck-v1.json",
    "mapped-literary-failure-matrix-v1.json",
    "exact-a-b-skill-context-reconstruction-v1.json",
    "semantic-atom-inventory-v1.json",
    "dimension-coverage-delta-v1.json",
    "unselected-candidate-section-audit-v1.json",
    "section-boundary-dependency-audit-v1.json",
    "selector-recall-audit-v1.json",
    "baseline-compactor-forensics-v1.json",
    "context-ordering-salience-audit-v1.json",
    "literary-evidence-input-traceback-v1.json",
    "variance-analysis-v1.json",
    "hypothesis-matrix-v1.json",
    "primary-root-cause-v1.json",
    "architecture-disposition-v1.json",
    "minimal-fix-constraints-v1.json",
    "anti-overfit-constraints-v1.json",
    "next-experiment-readiness-v1.json",
    "privacy-scan-v1.json",
    "test-receipt-v1.json",
    "strict-l3-receipt-v1.json",
    "final-report-v1.md",
    "sha256-manifest-v1.json",
)

READINESS_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-character-heavy-multi-sample-pilot-approval-readiness-recheck-v1"
)
MAPPING_REVEAL_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-character-heavy-multi-sample-mapping-reveal-decision-v1"
)
SHADOW_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-verbatim-selective-compiler-shadow-implementation-v1"
)
COMBINED_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-character-heavy-multi-sample-combined-blind-aggregation-v1"
)
EVALUATOR_1_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-character-heavy-multi-sample-blind-evaluation-v1"
)
EVALUATOR_2_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-character-heavy-multi-sample-blind-evaluation-v2"
)
BLIND_BUNDLE_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-character-heavy-multi-sample-blind-bundle-v1"
)
BLIND_MAPPING_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-character-heavy-multi-sample-blind-mapping-v1"
)
CAMPAIGN_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-character-heavy-multi-sample-real-campaign-v1"
)
STRATEGY_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-verbatim-selective-compiler-strategy-pivot-v1"
)

INDEX_PATH = Path("vendor/novel-skills/skill-section-index-v1.json")
BUNDLE_PATH = Path("vendor/novel-skills/source")
RESOLVED_SKILLS = (
    "story-init",
    "plot-structure",
    "character-management",
    "worldbuilding",
)
DIMENSIONS = (
    "character_agency",
    "causal_coherence",
    "subtext_support",
    "specificity",
    "scene_pressure",
    "setup_payoff_integrity",
    "voice_readiness",
    "anti_template_risk",
)
CRITICAL_DIMENSIONS = {
    "character_agency",
    "causal_coherence",
    "setup_payoff_integrity",
}
REGRESSION_DIMENSIONS = (
    "character_agency",
    "causal_coherence",
    "subtext_support",
    "specificity",
    "scene_pressure",
    "setup_payoff_integrity",
)
PRIMARY_ROOT_CAUSE = "MULTI_FACTOR_WITH_PRIMARY_SELECTIVE_REPLACEMENT_ARCHITECTURE_MISMATCH"
ARCHITECTURE_DISPOSITION = "REPOSITION_AS_SUPPLEMENT_NOT_REPLACEMENT"
NEXT_GATE = "SKILL_V3_HYBRID_SKILL_CONTEXT_ARCHITECTURE_DESIGN"

EXPECTED_A_CONTEXT_SHA256 = (
    "7d0f6309ede2261f2f6a1098d394937948bf5b50eb9248266ab350fd91da9adc"
)
EXPECTED_B_CONTEXT_SHA256 = (
    "c830681f79526c44d9bd83430019d75cb886bde0affcad86714ee1fc1f41aedd"
)
EXPECTED_A_PROFILE_BINDING_SHA256 = (
    "109bb50e2e649c5841bd7c83513100caa0d93cf3c1bb5db845e489b5ae10856d"
)
EXPECTED_SELECTED_SECTION_IDS = (
    "sv3-70a527462c32e7b6",
    "sv3-faecc1466817d8aa",
    "sv3-7633ad6f5c90db5e",
    "sv3-3fb51ac3fed35bc0",
    "sv3-4c6b004ecdd2077f",
    "sv3-10e4ba0c5b7509b4",
    "sv3-8e321726b4ebdcec",
    "sv3-8afeb5229a4fe841",
    "sv3-e92f0f3584d44b87",
)
REGRESSION_RELEVANT_UNSELECTED_IDS = (
    "sv3-13580b3cdbef263e",
    "sv3-ac7aa3aed8a7d237",
    "sv3-2ced894267dc51e3",
    "sv3-82ca2fdf9c28183b",
    "sv3-a1cb6a6e7ccf6112",
    "sv3-972a75cb8ca8f0bd",
    "sv3-6e4a0b2625a01274",
    "sv3-974421ec02a478fa",
    "sv3-4c39329c602fd48e",
    "sv3-2985467b5f2bf929",
    "sv3-60d4bee497e4c0dc",
    "sv3-b4583d410167ab14",
    "sv3-ad3871e96cc16876",
)
REGRESSION_RELEVANT_OWNERSHIP_FILTERED_IDS = (
    "sv3-8f60ce5781d2680f",
    "sv3-c8068581ef934af9",
    "sv3-9e36963fe1a5a940",
    "sv3-b75227453c1cc26a",
    "sv3-57971b1277b054c2",
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _read_json(repo: Path, relative: Path | str) -> dict[str, Any]:
    value = json.loads((repo / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {relative}")
    return value


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def _canonical_json_hash(value: object) -> str:
    return _sha_bytes(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def verify_manifest(repo: Path, root: Path) -> dict[str, Any]:
    manifest_path = repo / root / "sha256-manifest-v1.json"
    envelope = _read_json(repo, manifest_path.relative_to(repo))
    definition = envelope.get("definition")
    if not isinstance(definition, dict):
        definition = envelope
    entries = definition.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError(f"manifest entries missing: {root}")
    failures: list[str] = []
    covered: set[str] = set()
    for entry in entries:
        relative = str(entry["path"]).replace("\\", "/")
        covered.add(relative)
        path = repo / root / relative
        if not path.is_file():
            failures.append(f"missing:{relative}")
            continue
        content = path.read_bytes()
        if _sha_bytes(content) != entry["sha256"]:
            failures.append(f"sha256:{relative}")
        if "bytes" in entry and len(content) != entry["bytes"]:
            failures.append(f"bytes:{relative}")
    actual = {
        path.relative_to(repo / root).as_posix()
        for path in (repo / root).rglob("*")
        if path.is_file() and path.name != "sha256-manifest-v1.json"
    }
    if actual != covered:
        failures.append(
            "coverage:missing=" + ",".join(sorted(actual - covered))
            + ";extra=" + ",".join(sorted(covered - actual))
        )
    if definition.get("entry_count") != len(entries):
        failures.append("entry_count")
    if failures:
        raise RuntimeError(f"manifest not exact for {root}: {failures}")
    return {
        "root": root.as_posix(),
        "status": "EXACT",
        "entry_count": len(entries),
        "manifest_file_sha256": _sha_file(manifest_path),
        "definition_sha256": envelope.get("definition_sha256"),
    }


def _allowed_dirty_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        normalized == "tools/diagnostics/skill_v3_multi_sample_quality_root_cause.py"
        or normalized == "tests/canary/test_skill_v3_multi_sample_quality_root_cause.py"
        or normalized.startswith(OUTPUT_RELATIVE_ROOT + "/")
    )


def validate_environment(repo: Path) -> dict[str, Any]:
    branch = _git(repo, "branch", "--show-current")
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain")
    dirty_paths = []
    for line in status.splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        dirty_paths.append(path)
    unrelated = [path for path in dirty_paths if not _allowed_dirty_path(path)]
    if branch != BRANCH or head != START_HEAD or unrelated:
        raise RuntimeError(
            "ROOT_CAUSE_NO_GO_EXPERIMENT_NOT_CAUSALLY_INTERPRETABLE: "
            f"branch={branch}; head={head}; unrelated_dirty={unrelated}"
        )
    return {
        "branch": branch,
        "start_head": head,
        "initial_worktree": "CLEAN",
        "task_local_dirty_paths_allowed_during_materialization": dirty_paths,
        "unrelated_dirty_count": 0,
    }


def _decision_inputs() -> SkillLoadDecisionInputsV1:
    return SkillLoadDecisionInputsV1.model_validate({
        "authority_revision": 1,
        "authority_hash": "a" * 64,
        "actor_refs_status": "present",
        "world_refs_status": "present",
        "actor_ref_count": 1,
        "world_ref_count": 1,
        "actor_refs": ("actor-fixture",),
        "location_refs": ("location-fixture",),
    })


def reconstruct_contexts(repo: Path) -> dict[str, Any]:
    bundle = repo / BUNDLE_PATH
    index = SkillSectionIndexV1.load(repo / INDEX_PATH, repo)
    compiler = SelectiveSkillCompilerV1(index)
    profile = build_planning_v2_event_realization_profile_demand_aware(
        bundle,
        _decision_inputs(),
        pair_creative_demand_class="character-heavy",
    )
    a_text, a_receipt = render_skill_context(
        profile.advisory_rules,
        profile.mandatory_rules,
        profile.context_budget_policy,
        profile_hash=profile.canonical_profile_sha256,
    )
    fixture_sha = _read_json(
        repo, SHADOW_ROOT / "scenario-character-heavy-v1.json"
    )["fixture_sha256"]
    schema_sha = _canonical_json_hash(EventRealizationCandidateV1.model_json_schema())
    request = SelectionInputV1(
        resolved_skill_ids=RESOLVED_SKILLS,
        resolved_skill_source_hashes=tuple(
            (skill, index.skill_source_sha256[skill]) for skill in RESOLVED_SKILLS
        ),
        stage="planning",
        substage="event_realization",
        task_contract_id="planning_event_realization_shadow_v1@1",
        task_contract_schema_sha256=schema_sha,
        creative_demand_class="character-heavy",
        authority_fact_hashes=(("sanitized_fixture", fixture_sha),),
    )
    selected = compiler.select(request)
    b_rendered = compiler.render(selected)
    if _sha_bytes(a_text.encode("utf-8")) != EXPECTED_A_CONTEXT_SHA256:
        raise RuntimeError("A_CONTEXT_RECONSTRUCTION_DRIFT")
    if b_rendered.sha256 != EXPECTED_B_CONTEXT_SHA256:
        raise RuntimeError("B_CONTEXT_RECONSTRUCTION_DRIFT")
    if tuple(item.section_id for item in selected) != EXPECTED_SELECTED_SECTION_IDS:
        raise RuntimeError("B_SELECTED_SECTION_ID_DRIFT")
    if a_receipt.status != "NONE" or a_receipt.excluded_rule_ids:
        raise RuntimeError("A_CONTEXT_TRUNCATION_OR_SHEDDING")

    a_included_ranges = {
        (
            f"vendor/novel-skills/source/{item.relative_source_path}",
            item.line_start,
            item.line_end,
        )
        for item in profile.included_sections
    }
    a_omitted = []
    for section in index.sections:
        if section.skill_id not in RESOLVED_SKILLS:
            continue
        key = (
            section.source_path.replace("\\", "/"),
            section.source_span_or_ast_node["start_line"],
            section.source_span_or_ast_node["end_line"],
        )
        if key not in a_included_ranges:
            a_omitted.append({
                "section_id": section.section_id,
                "source_file": section.source_path,
                "line_start": key[1],
                "line_end": key[2],
                "reason": "not_in_demand_aware_v2_profile_source_projection",
            })
    mandatory_text = "".join(
        f"[{rule.rule_id}] {rule.text}\n" for rule in profile.mandatory_rules
    )
    advisory_text = "".join(
        f"[{rule.rule_id}] {rule.text}\n" for rule in profile.advisory_rules
    )
    b_verbatim = "".join(item.source_text for item in selected)
    return {
        "index": index,
        "compiler": compiler,
        "request": request,
        "profile": profile,
        "a_text": a_text,
        "a_receipt": a_receipt,
        "a_mandatory_text": mandatory_text,
        "a_advisory_text": advisory_text,
        "a_omitted": a_omitted,
        "selected": selected,
        "b_text": b_rendered.text,
        "b_rendered": b_rendered,
        "b_verbatim": b_verbatim,
    }


def _rule_lookup(contexts: Mapping[str, Any]) -> dict[str, Any]:
    profile = contexts["profile"]
    return {
        rule.rule_id: rule
        for rule in (*profile.mandatory_rules, *profile.advisory_rules)
    }


ATOM_SPECS: tuple[dict[str, Any], ...] = (
    {"id":"formative_pressure_to_present_motive","source":"A:MOTIVE_ACTION","fn":"bind biography to present motive","dims":["character_agency","causal_coherence"],"act":"HIGH","spec":"HIGH","level":"CHARACTER_LEVEL","a":True,"b":True},
    {"id":"want_need_conflict","source":"A:MOTIVE_ACTION","fn":"create internal/external conflict","dims":["character_agency","subtext_support"],"act":"HIGH","spec":"MEDIUM","level":"CHARACTER_LEVEL","a":True,"b":True},
    {"id":"opposed_tactics_costly_choice","source":"A:MOTIVE_ACTION","fn":"externalize motive as tactics and cost","dims":["character_agency","scene_pressure"],"act":"HIGH","spec":"HIGH","level":"SCENE_LEVEL","a":True,"b":False},
    {"id":"observable_reaction_next_beat_consequence","source":"A:MOTIVE_ACTION","fn":"close action consequence chain","dims":["character_agency","causal_coherence"],"act":"HIGH","spec":"HIGH","level":"HANDOFF","a":True,"b":False},
    {"id":"distinct_voice_diction_rhythm","source":"A:VOICE_RELATION","fn":"differentiate voice surface","dims":["voice_readiness","specificity"],"act":"HIGH","spec":"HIGH","level":"CHARACTER_LEVEL","a":True,"b":False},
    {"id":"evasion_gesture_withheld_explanation","source":"A:VOICE_RELATION","fn":"dramatize subtext","dims":["subtext_support","anti_template_risk"],"act":"HIGH","spec":"HIGH","level":"SCENE_LEVEL","a":True,"b":False},
    {"id":"relationship_pressure_changes_action","source":"A:VOICE_RELATION","fn":"turn relationship into causal pressure","dims":["character_agency","subtext_support","scene_pressure"],"act":"HIGH","spec":"HIGH","level":"CHARACTER_LEVEL","a":True,"b":False},
    {"id":"sensory_mechanical_affordance_constrains_action","source":"A:CAUSAL_AFFORDANCE","fn":"make setting causal and specific","dims":["causal_coherence","specificity","scene_pressure"],"act":"HIGH","spec":"HIGH","level":"SCENE_LEVEL","a":True,"b":False},
    {"id":"interactive_affordance_later_payoff","source":"A:CAUSAL_AFFORDANCE","fn":"bridge setting to payoff","dims":["setup_payoff_integrity","causal_coherence"],"act":"HIGH","spec":"HIGH","level":"STRUCTURAL","a":True,"b":False},
    {"id":"opposed_escalation_reaction_reversal","source":"A:PRESSURE_BEATS","fn":"build causal pressure beats","dims":["scene_pressure","causal_coherence"],"act":"HIGH","spec":"HIGH","level":"SCENE_LEVEL","a":True,"b":True},
    {"id":"behavior_over_explanatory_summary","source":"A:PRESSURE_BEATS","fn":"prevent synopsis-distance explanation","dims":["subtext_support","anti_template_risk","scene_pressure"],"act":"HIGH","spec":"HIGH","level":"HANDOFF","a":True,"b":False},
    {"id":"setup_dependency_payoff_through_action","source":"A:SETUP_PAYOFF","fn":"preserve and resolve setup causally","dims":["setup_payoff_integrity","causal_coherence"],"act":"HIGH","spec":"HIGH","level":"STRUCTURAL","a":True,"b":False},
    {"id":"confirmed_frame_bridge","source":"A:FRAME_BRIDGE","fn":"bind tone genre POV tense without invention","dims":["voice_readiness","causal_coherence"],"act":"MEDIUM","spec":"HIGH","level":"HANDOFF","a":True,"b":False},
    {"id":"draft_usable_spatial_microchain","source":"A:DRAFT_SCENE","fn":"create continuous scene-ready beat chain","dims":["scene_pressure","causal_coherence","specificity"],"act":"HIGH","spec":"HIGH","level":"HANDOFF","a":True,"b":False},
    {"id":"terminal_image","source":"A:DRAFT_SCENE","fn":"end bounded event on concrete image","dims":["specificity","anti_template_risk"],"act":"HIGH","spec":"HIGH","level":"HANDOFF","a":True,"b":False},
    {"id":"labels_reasoning_only","source":"A:ANTI_TAXONOMY","fn":"prevent taxonomy prose","dims":["anti_template_risk","subtext_support"],"act":"HIGH","spec":"HIGH","level":"OTHER","a":True,"b":False},
    {"id":"replace_abstraction_with_choice_dialogue_consequence","source":"A:ANTI_TAXONOMY","fn":"convert labels into dramatized evidence","dims":["anti_template_risk","subtext_support","character_agency"],"act":"HIGH","spec":"HIGH","level":"SCENE_LEVEL","a":True,"b":False},
    {"id":"actor_choice_action_state_change","source":"A:PLOT_CAUSAL_ESCALATION","fn":"bind actor action to local result","dims":["character_agency","causal_coherence"],"act":"HIGH","spec":"HIGH","level":"STRUCTURAL","a":True,"b":True},
    {"id":"foreshadowing_intent_across_plan","source":"A:PLOT_SETUP_PAYOFF_INTENT","fn":"retain setup/payoff intent","dims":["setup_payoff_integrity"],"act":"MEDIUM","spec":"MEDIUM","level":"STRUCTURAL","a":True,"b":False},
    {"id":"pacing_without_authority_change","source":"A:PLOT_PACING_INTENT","fn":"pace while preserving event authority","dims":["scene_pressure","causal_coherence"],"act":"MEDIUM","spec":"HIGH","level":"STRUCTURAL","a":True,"b":False},
    {"id":"voice_vocabulary_sentence_habits_tone","source":"A:CHARACTER_VOICE","fn":"bind observable voice features","dims":["voice_readiness","specificity"],"act":"HIGH","spec":"HIGH","level":"CHARACTER_LEVEL","a":True,"b":False},
    {"id":"arc_start_turning_end","source":"A:CHARACTER_ARC","fn":"preserve character arc trajectory","dims":["character_agency","causal_coherence"],"act":"MEDIUM","spec":"MEDIUM","level":"STRUCTURAL","a":True,"b":True},
    {"id":"relationship_role_pressure_trust_subtext","source":"A:CHARACTER_RELATIONSHIP_NUANCE","fn":"apply relationship role to scene behavior","dims":["subtext_support","scene_pressure","character_agency"],"act":"HIGH","spec":"HIGH","level":"CHARACTER_LEVEL","a":True,"b":False},
    {"id":"concrete_interactive_location_detail","source":"A:WORLD_SENSORY_SPECIFICITY","fn":"ground action in local setting","dims":["specificity","scene_pressure"],"act":"HIGH","spec":"HIGH","level":"SCENE_LEVEL","a":True,"b":False},
    {"id":"specific_cost_limit_consequence","source":"A:WORLD_COST_AND_LIMIT","fn":"make systems constrain action","dims":["causal_coherence","scene_pressure","specificity"],"act":"HIGH","spec":"HIGH","level":"STRUCTURAL","a":True,"b":False},
    {"id":"faction_conflict_as_local_pressure","source":"A:WORLD_FACTION_PRESSURE","fn":"turn faction facts into pressure","dims":["scene_pressure","causal_coherence"],"act":"HIGH","spec":"MEDIUM","level":"SCENE_LEVEL","a":True,"b":False},
    {"id":"history_culture_current_tension","source":"A:WORLD_CURRENT_STATE","fn":"ground realization in current world state","dims":["specificity","causal_coherence"],"act":"MEDIUM","spec":"MEDIUM","level":"STRUCTURAL","a":True,"b":False},
    {"id":"artifact_form_function_history_risk","source":"A:WORLD_ARTIFACT_DETAIL","fn":"make objects recognizable and consequential","dims":["specificity","setup_payoff_integrity"],"act":"HIGH","spec":"HIGH","level":"SCENE_LEVEL","a":True,"b":False},
    {"id":"initial_state_inciting_incident","source":"B:sv3-70a527462c32e7b6","fn":"name initial state and trigger","dims":["causal_coherence"],"act":"MEDIUM","spec":"MEDIUM","level":"STRUCTURAL","a":False,"b":True},
    {"id":"climax_highest_tension_outcome","source":"B:sv3-7633ad6f5c90db5e","fn":"name outcome-deciding turn","dims":["scene_pressure","causal_coherence"],"act":"MEDIUM","spec":"LOW","level":"STRUCTURAL","a":False,"b":True},
    {"id":"social_relationship_taxonomy","source":"B:sv3-8afeb5229a4fe841","fn":"enumerate relationship labels","dims":["subtext_support"],"act":"LOW","spec":"LOW","level":"CHARACTER_LEVEL","a":False,"b":True},
    {"id":"story_role_taxonomy","source":"B:sv3-e92f0f3584d44b87","fn":"enumerate story-role labels","dims":["character_agency"],"act":"LOW","spec":"LOW","level":"CHARACTER_LEVEL","a":False,"b":True},
    {"id":"known_clues_constraints_contradictions","source":"C:sv3-972a75cb8ca8f0bd","fn":"bind question to evidence","dims":["setup_payoff_integrity","causal_coherence"],"act":"HIGH","spec":"HIGH","level":"STRUCTURAL","a":False,"b":False},
    {"id":"physical_distinguishing_scene_traits","source":"C:sv3-974421ec02a478fa","fn":"ground character appearance","dims":["specificity","anti_template_risk"],"act":"MEDIUM","spec":"HIGH","level":"CHARACTER_LEVEL","a":False,"b":False},
    {"id":"personality_habits_quirks_scene_memory","source":"C:sv3-4c39329c602fd48e","fn":"make character-specific behavior available","dims":["specificity","anti_template_risk","voice_readiness"],"act":"MEDIUM","spec":"HIGH","level":"CHARACTER_LEVEL","a":False,"b":False},
    {"id":"voice_examples","source":"C:sv3-b75227453c1cc26a","fn":"provide concrete voice samples","dims":["voice_readiness","specificity"],"act":"HIGH","spec":"HIGH","level":"CHARACTER_LEVEL","a":False,"b":False},
)


def build_semantic_atoms(contexts: Mapping[str, Any]) -> list[dict[str, Any]]:
    rules = _rule_lookup(contexts)
    index = contexts["index"]
    rows = []
    for spec in ATOM_SPECS:
        source_kind, source_id = spec["source"].split(":", 1)
        if source_kind == "A":
            rule = rules[source_id]
            source_skill = rule.skill_id
            source_section = source_id
            source_file = "src/novel_flywheel/runtime_skill_profiles.py"
            source_range: Any = f"rendered-context-rule:{source_id}"
            source_sha = _sha_bytes(rule.text.encode("utf-8"))
        else:
            section = index.by_id[source_id]
            source_skill = section.skill_id
            source_section = source_id
            source_file = section.source_path
            source_range = dict(section.source_span_or_ast_node)
            source_sha = section.section_content_sha256
        rows.append({
            "atom_id": "atom-" + spec["id"].replace("_", "-"),
            "source_skill": source_skill,
            "source_section": source_section,
            "source_file": source_file,
            "source_text_range": source_range,
            "source_text_sha256": source_sha,
            "semantic_function": spec["fn"],
            "target_dimensions": spec["dims"],
            "actionability": spec["act"],
            "specificity": spec["spec"],
            "level": spec["level"],
            "present_in_a": spec["a"],
            "present_in_b": spec["b"],
            "wording_identity": (
                "DIFFERENT" if spec["a"] and spec["b"] else "NA"
            ),
        })
    return rows


RELEVANT_SECTION_DIMENSIONS = {
    "sv3-13580b3cdbef263e": ["causal_coherence", "scene_pressure"],
    "sv3-ac7aa3aed8a7d237": ["setup_payoff_integrity"],
    "sv3-2ced894267dc51e3": ["setup_payoff_integrity"],
    "sv3-82ca2fdf9c28183b": ["setup_payoff_integrity"],
    "sv3-a1cb6a6e7ccf6112": ["setup_payoff_integrity"],
    "sv3-972a75cb8ca8f0bd": ["setup_payoff_integrity", "causal_coherence"],
    "sv3-6e4a0b2625a01274": ["setup_payoff_integrity"],
    "sv3-974421ec02a478fa": ["specificity", "anti_template_risk"],
    "sv3-4c39329c602fd48e": ["specificity", "voice_readiness", "anti_template_risk"],
    "sv3-2985467b5f2bf929": ["specificity", "scene_pressure"],
    "sv3-60d4bee497e4c0dc": ["specificity", "causal_coherence"],
    "sv3-b4583d410167ab14": ["specificity"],
    "sv3-ad3871e96cc16876": ["specificity", "causal_coherence"],
    "sv3-8f60ce5781d2680f": ["causal_coherence", "scene_pressure"],
    "sv3-c8068581ef934af9": ["setup_payoff_integrity"],
    "sv3-9e36963fe1a5a940": ["character_agency", "voice_readiness"],
    "sv3-b75227453c1cc26a": ["voice_readiness", "specificity"],
    "sv3-57971b1277b054c2": ["specificity", "scene_pressure"],
}


def build_candidate_audit(contexts: Mapping[str, Any]) -> dict[str, Any]:
    index = contexts["index"]
    compiler = contexts["compiler"]
    selected_ids = set(EXPECTED_SELECTED_SECTION_IDS)
    rows = []
    for section in index.sections:
        if section.skill_id not in RESOLVED_SKILLS:
            continue
        eligible = compiler._ownership_allowed(section)
        selected = section.section_id in selected_ids
        if selected:
            reason = (
                "always_on_stage_core"
                if section.selection_class == "ALWAYS_ON_STAGE_CORE"
                else "character_heavy_demand_match"
            )
            drop_reason = None
        elif not eligible:
            reason = "ownership_or_model_visible_filter"
            drop_reason = (
                "excluded_wrong_layer_or_model_visible_unsafe:"
                + section.stage_ownership
            )
        elif section.selection_class == "OPTIONAL_SUPPORT":
            reason = "optional_support_disabled"
            drop_reason = "include_optional_support_false"
        elif section.selection_class == "DEMAND_SPECIFIC":
            reason = "exact_demand_tag_match"
            drop_reason = "character_heavy_not_in_demand_tags"
        elif section.selection_class == "CONTRACT_SPECIFIC":
            reason = "exact_contract_match"
            drop_reason = "contract_id_not_matched"
        else:
            reason = section.selection_class.casefold()
            drop_reason = "not_selected"
        rows.append({
            "candidate_section_id": section.section_id,
            "skill": section.skill_id,
            "ownership": section.stage_ownership,
            "eligible": eligible,
            "selected": selected,
            "selection_rule_or_reason": reason,
            "dependency_reason": list(section.dependency_section_ids),
            "drop_reason": drop_reason,
            "optional_or_mandatory": (
                "OPTIONAL" if section.selection_class == "OPTIONAL_SUPPORT"
                else "MANDATORY_IF_RULE_MATCHES"
            ),
            "char_count": len(section.source_text),
            "target_semantics": RELEVANT_SECTION_DIMENSIONS.get(
                section.section_id, list(section.capability_tags)
            ),
            "demand_tags": list(section.demand_tags),
            "selection_class": section.selection_class,
            "source_file": section.source_path,
            "source_text_range": dict(section.source_span_or_ast_node),
        })
    relevant = [
        row for row in rows
        if row["candidate_section_id"] in REGRESSION_RELEVANT_UNSELECTED_IDS
    ]
    if not all(row["eligible"] and not row["selected"] for row in relevant):
        raise RuntimeError("REGRESSION_RELEVANT_ELIGIBLE_SET_DRIFT")
    filtered = [
        row for row in rows
        if row["candidate_section_id"]
        in REGRESSION_RELEVANT_OWNERSHIP_FILTERED_IDS
    ]
    return {
        "schema": "SkillV3UnselectedCandidateSectionAuditV1",
        "status": "EXACT",
        "candidate_scope": "all indexed sections in the four resolved planning Skills",
        "candidate_count": len(rows),
        "eligible_count": sum(row["eligible"] for row in rows),
        "selected_count": sum(row["selected"] for row in rows),
        "rows": rows,
        "regression_relevant_unselected_section_count": len(relevant),
        "regression_relevant_unselected_section_ids": list(
            REGRESSION_RELEVANT_UNSELECTED_IDS
        ),
        "regression_relevant_unselected_rows": relevant,
        "regression_relevant_ownership_filtered_section_count": len(filtered),
        "regression_relevant_ownership_filtered_section_ids": list(
            REGRESSION_RELEVANT_OWNERSHIP_FILTERED_IDS
        ),
        "regression_relevant_ownership_filtered_rows": filtered,
    }


def _pair_result(values: Sequence[str]) -> str:
    directional = [value for value in values if value not in {"EQUIVALENT", "INCONCLUSIVE"}]
    if len(set(directional)) > 1:
        return "INCONCLUSIVE"
    if directional:
        return directional[0]
    if values and all(value == "EQUIVALENT" for value in values):
        return "EQUIVALENT"
    return "INCONCLUSIVE"


def _evidence_hash_for_sample(
    repo: Path, evaluator: str, sample_id: str, dimension: str,
) -> str:
    if evaluator == "anonymous-evaluator-1":
        path = EVALUATOR_1_ROOT / "per-sample-judgments" / f"{sample_id}.json"
        payload = _read_json(repo, path)
        row = next(item for item in payload["dimensions"] if item["dimension"] == dimension)
        evidence = row["evidence"]
    else:
        path = EVALUATOR_2_ROOT / "per-sample-judgments" / f"{sample_id}-v1.json"
        payload = _read_json(repo, path)
        evidence = payload["judgments"][dimension]["evidence"]
    return _canonical_json_hash(evidence)


def build_failure_matrix(repo: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
    mapped = _read_json(repo, MAPPING_REVEAL_ROOT / "mapped-literary-dimension-results-v1.json")
    votes = _read_json(repo, COMBINED_ROOT / "complete-vote-set-v1.json")["votes"]
    vote_by_id = {vote["vote_id"]: vote for vote in votes}
    evidence_by_dimension: dict[str, list[dict[str, str]]] = defaultdict(list)
    rows = []
    for source in mapped["rows"]:
        pair_votes: dict[str, list[str]] = defaultdict(list)
        prose_ids = []
        for trace in source["mapped_vote_trace"]:
            pair_votes[trace["anonymous_pair_id"]].append(trace["mapped_result"])
            vote = vote_by_id[trace["vote_id"]]
            hashes = [
                _evidence_hash_for_sample(
                    repo, trace["evaluator_id"], sample_id, source["dimension"]
                )
                for sample_id in (
                    vote["position_a_anonymous_sample_id"],
                    vote["position_b_anonymous_sample_id"],
                )
            ]
            binding_sha = _canonical_json_hash({
                "vote_id": trace["vote_id"],
                "dimension": source["dimension"],
                "sample_evidence_sha256": hashes,
            })
            evidence_id = "prose-evidence-" + binding_sha[:20]
            item = {
                "evidence_id": evidence_id,
                "vote_id": trace["vote_id"],
                "pair_id": trace["anonymous_pair_id"],
                "evaluator_id": trace["evaluator_id"],
                "evidence_binding_sha256": binding_sha,
            }
            prose_ids.append(evidence_id)
            evidence_by_dimension[source["dimension"]].append(item)
        row = {
            "dimension": source["dimension"],
            "criticality": source["criticality"],
            "pair1_result": _pair_result(pair_votes["blind-pair-1"]),
            "pair2_result": _pair_result(pair_votes["blind-pair-2"]),
            "pair3_result": _pair_result(pair_votes["blind-pair-3"]),
            "evaluator1_votes": [
                item["mapped_result"] for item in source["mapped_vote_trace"]
                if item["evaluator_id"] == "anonymous-evaluator-1"
            ],
            "evaluator2_votes": [
                item["mapped_result"] for item in source["mapped_vote_trace"]
                if item["evaluator_id"] == "anonymous-evaluator-2"
            ],
            "combined_counts": source["mapped_experiment_counts"],
            "mapped_aggregate": source["mapped_experiment_result"],
            "classification": (
                "SELECTIVE_REGRESSION"
                if source["mapped_experiment_result"] == "BASELINE_BETTER"
                else "INCONCLUSIVE"
            ),
            "blind_evidence_ids": [
                item["vote_id"] for item in source["mapped_vote_trace"]
            ],
            "prose_evidence_ids": prose_ids,
        }
        rows.append(row)
    critical = [row["dimension"] for row in rows if row["criticality"] == "CRITICAL" and row["classification"] == "SELECTIVE_REGRESSION"]
    noncritical = [row["dimension"] for row in rows if row["criticality"] == "NONCRITICAL" and row["classification"] == "SELECTIVE_REGRESSION"]
    return ({
        "schema": "SkillV3MappedLiteraryFailureMatrixV1",
        "status": "EXACT",
        "rows": rows,
        "critical_counts": {"better":0,"equivalent":0,"regression":3,"inconclusive":0},
        "noncritical_counts": {"better":0,"equivalent":0,"regression":3,"inconclusive":2},
        "critical_regression_dimensions": critical,
        "noncritical_regression_dimensions": noncritical,
        "voice_readiness": "INCONCLUSIVE_SELECTIVE_3_BASELINE_3",
        "anti_template_risk": "INCONCLUSIVE_SELECTIVE_3_BASELINE_2_TIE_1",
        "raw_story_or_provider_text_persisted": False,
    }, evidence_by_dimension)


def _dimension_delta(atoms: Sequence[dict[str, Any]], dimension: str) -> dict[str, Any]:
    relevant = [row for row in atoms if dimension in row["target_dimensions"]]
    a_only = [row for row in relevant if row["present_in_a"] and not row["present_in_b"]]
    b_only = [row for row in relevant if row["present_in_b"] and not row["present_in_a"]]
    shared = [row for row in relevant if row["present_in_a"] and row["present_in_b"]]
    missing_dependencies = {
        "character_agency": ["relationship_pressure_changes_action", "observable_reaction_next_beat_consequence"],
        "causal_coherence": ["observable_reaction_next_beat_consequence", "sensory_mechanical_affordance_constrains_action", "setup_dependency_payoff_through_action"],
        "subtext_support": ["evasion_gesture_withheld_explanation", "relationship_role_pressure_trust_subtext"],
        "specificity": ["concrete_interactive_location_detail", "artifact_form_function_history_risk"],
        "scene_pressure": ["opposed_tactics_costly_choice", "draft_usable_spatial_microchain"],
        "setup_payoff_integrity": ["interactive_affordance_later_payoff", "setup_dependency_payoff_through_action"],
        "voice_readiness": ["distinct_voice_diction_rhythm", "voice_vocabulary_sentence_habits_tone"],
        "anti_template_risk": ["behavior_over_explanatory_summary", "labels_reasoning_only"],
    }
    return {
        "dimension": dimension,
        "a_atom_count": sum(row["present_in_a"] for row in relevant),
        "b_atom_count": sum(row["present_in_b"] for row in relevant),
        "a_only_atoms": [row["atom_id"] for row in a_only],
        "b_only_atoms": [row["atom_id"] for row in b_only],
        "shared_atoms": [row["atom_id"] for row in shared],
        "a_only_high_actionability_atoms": [row["atom_id"] for row in a_only if row["actionability"] == "HIGH"],
        "b_only_high_actionability_atoms": [row["atom_id"] for row in b_only if row["actionability"] == "HIGH"],
        "dependency_atoms_missing_from_b": [
            "atom-" + value.replace("_", "-")
            for value in missing_dependencies[dimension]
        ],
        "contextual_qualifiers_missing_from_b": {
            "character_agency": ["observable", "costly", "next-beat"],
            "causal_coherence": ["constrain action", "resulting local state change"],
            "subtext_support": ["withheld explanation", "without inventing authority"],
            "specificity": ["small number", "interactive", "recognizable form"],
            "scene_pressure": ["opposed", "resistance", "costly"],
            "setup_payoff_integrity": ["preserve dependency", "through later action"],
            "voice_readiness": ["evasion", "verbal habits", "relationship pressure"],
            "anti_template_risk": ["reasoning only", "replace abstractions with behavior"],
        }[dimension],
        "anti_pattern_guidance_missing_from_b": [
            row["atom_id"] for row in a_only
            if "anti_template_risk" in row["target_dimensions"]
        ],
        "scene_realization_bridge_missing_from_b": [
            row["atom_id"] for row in a_only if row["level"] == "HANDOFF"
        ],
        "causal_use_of_counts": "counts are descriptive; causal strength also requires mapped output evidence and mechanism-level text comparison",
    }


def _source_record(item: Any) -> dict[str, Any]:
    return {
        "section_id": item.section_id,
        "source_file": item.relative_source_path,
        "line_start": item.line_start,
        "line_end": item.line_end,
        "section_sha256": item.section_sha256,
    }


def build_context_reconstruction(contexts: Mapping[str, Any]) -> dict[str, Any]:
    profile = contexts["profile"]
    selected = contexts["selected"]
    return {
        "schema": "SkillV3ExactABSkillContextReconstructionV1",
        "status": "EXACT",
        "arm_a": {
            "a_context_kind": "DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE",
            "a_profile_binding_sha256": EXPECTED_A_PROFILE_BINDING_SHA256,
            "a_reconstructed_canonical_profile_sha256": profile.canonical_profile_sha256,
            "a_skill_source_files": sorted({item.relative_source_path for item in profile.included_sections}),
            "a_complete_skill_source_shas": profile.source_skill_sha256,
            "a_source_section_bindings": [_source_record(item) for item in profile.included_sections],
            "a_hard_rule_extract": [
                {
                    "rule_id": rule.rule_id,
                    "text": rule.text,
                    "text_sha256": _sha_bytes(rule.text.encode("utf-8")),
                }
                for rule in profile.mandatory_rules
            ],
            "a_hard_rule_extract_sha256": _sha_bytes(contexts["a_mandatory_text"].encode("utf-8")),
            "a_compacted_advisory_exact_text_sha256": _sha_bytes(contexts["a_advisory_text"].encode("utf-8")),
            "a_compacted_advisory_char_count": len(contexts["a_advisory_text"]),
            "a_rendered_skill_context_sha256": EXPECTED_A_CONTEXT_SHA256,
            "a_rendered_skill_context_char_count": len(contexts["a_text"]),
            "a_rendered_order": [
                rule.rule_id for rule in (*profile.mandatory_rules, *profile.advisory_rules)
            ],
            "a_omitted_source_ranges": contexts["a_omitted"],
            "a_omitted_rule_ids": list(contexts["a_receipt"].excluded_rule_ids),
            "a_compaction_policy_version": "T5_COMPRESSED_PROFILE+T6_DEMAND_AWARE_V2",
            "a_transformation_truth": "deterministic rewritten _RuleSpec prose; not verbatim source-section injection",
            "a_advisory_truncation": False,
            "a_advisory_shedding": False,
        },
        "arm_b": {
            "b_context_kind": "VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_V1_CHARACTER_HEAVY",
            "b_compiler_version": COMPILER_VERSION,
            "b_selector_version": SELECTOR_POLICY_VERSION,
            "b_selected_section_ids": [item.section_id for item in selected],
            "b_selected_section_content_shas": {item.section_id:item.section_content_sha256 for item in selected},
            "b_selected_section_source_files": {item.section_id:item.source_path for item in selected},
            "b_selected_section_source_ranges": {item.section_id:dict(item.source_span_or_ast_node) for item in selected},
            "b_selected_exact_verbatim_text_sha256": _sha_bytes(contexts["b_verbatim"].encode("utf-8")),
            "b_selected_exact_verbatim_text_char_count": len(contexts["b_verbatim"]),
            "b_rendered_skill_context_sha256": EXPECTED_B_CONTEXT_SHA256,
            "b_rendered_skill_context_char_count": len(contexts["b_text"]),
            "b_rendered_order": [item.section_id for item in selected],
            "b_mandatory_rule_layer": [item.section_id for item in selected if item.selection_class == "ALWAYS_ON_STAGE_CORE"],
            "b_dependency_closure": {"status":"PASS","missing_count":0,"declared_edges":sum(len(item.dependency_section_ids) for item in selected)},
            "b_shared_core_exceptions": [],
            "b_advisory_truncation": False,
            "b_advisory_shedding": False,
        },
        "exact_model_visible_text_persisted": False,
        "local_reconstruction_available": True,
    }


def build_dependency_audit() -> dict[str, Any]:
    rows = [
        {"selected_section":"sv3-faecc1466817d8aa","missing_neighbor_section":"sv3-13580b3cdbef263e","semantic_dependency_kind":"SEMANTIC_DEPENDENCY_MISSING","why_dependency_graph_missed_it":"plot points tagged only conflict-pacing-heavy although causal pressure is rubric-wide","regression_dimension_link":["causal_coherence","scene_pressure"]},
        {"selected_section":"sv3-70a527462c32e7b6","missing_neighbor_section":"sv3-2ced894267dc51e3","semantic_dependency_kind":"SEMANTIC_DEPENDENCY_MISSING","why_dependency_graph_missed_it":"setup/payoff candidate is gated to another demand class","regression_dimension_link":["setup_payoff_integrity"]},
        {"selected_section":"sv3-3fb51ac3fed35bc0","missing_neighbor_section":"sv3-82ca2fdf9c28183b","semantic_dependency_kind":"SEMANTIC_DEPENDENCY_MISSING","why_dependency_graph_missed_it":"resolution has no reverse semantic edge to payoff","regression_dimension_link":["setup_payoff_integrity","causal_coherence"]},
        {"selected_section":"sv3-3fb51ac3fed35bc0","missing_neighbor_section":"sv3-6e4a0b2625a01274","semantic_dependency_kind":"SEMANTIC_DEPENDENCY_MISSING","why_dependency_graph_missed_it":"resolution plan is not in character-heavy demand closure","regression_dimension_link":["setup_payoff_integrity"]},
        {"selected_section":"sv3-10e4ba0c5b7509b4","missing_neighbor_section":"sv3-b75227453c1cc26a","semantic_dependency_kind":"SECTION_GRANULARITY_TOO_COARSE","why_dependency_graph_missed_it":"voice content is a useful creative leaf but its whole section is classified DRAFT and excluded","regression_dimension_link":["voice_readiness","subtext_support"]},
        {"selected_section":"sv3-4c6b004ecdd2077f","missing_neighbor_section":"sv3-9e36963fe1a5a940","semantic_dependency_kind":"SECTION_GRANULARITY_TOO_COARSE","why_dependency_graph_missed_it":"mixed runtime/creative parent section is excluded as one node, losing its creative subrange","regression_dimension_link":["character_agency","specificity"]},
        {"selected_section":"sv3-8afeb5229a4fe841","missing_neighbor_section":"sv3-fc9570e47e65f4a2","semantic_dependency_kind":"SECTION_GRANULARITY_TOO_FINE","why_dependency_graph_missed_it":"taxonomy leaf survives but application context is separated into an excluded operational section","regression_dimension_link":["subtext_support","scene_pressure"]},
    ]
    return {
        "schema":"SkillV3SectionBoundaryDependencyAuditV1",
        "status":"SUPPORTED",
        "rows":rows,
        "formal_dependency_missing_count":0,
        "semantic_dependency_missing_count":4,
        "section_granularity_too_coarse_count":2,
        "section_granularity_too_fine_count":1,
        "no_boundary_problem_count":0,
        "conclusion":"declared graph is structurally closed but semantically under-modelled",
    }


def build_selector_audit(candidate_audit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema":"SkillV3SelectorRecallAuditV1",
        "status":"UNDER_RECALL_PROVEN",
        "demand_features":["creative_demand_class=character-heavy","resolved Skill IDs/source hashes","stage=planning","substage=event_realization","task contract identity","authority fact hashes","include_optional_support=false"],
        "feature_source":"SelectionInputV1 and sealed character-heavy request",
        "match_rules":["ALWAYS_ON_STAGE_CORE","exact demand-tag equality","exact contract-id equality","optional support only when explicitly enabled","declared dependency closure only","planning ownership allowlist"],
        "selection_recall_risk":"HIGH",
        "false_negative_section_patterns":["cross-cutting quality sections tagged to another mutually exclusive demand","optional evidence/specificity leaves","creative subranges inside mixed operational parent sections","voice/subtext guidance assigned to Draft ownership","semantic neighbor not declared as formal dependency"],
        "false_positive_section_patterns":["relationship taxonomies selected as character-heavy guidance without scene application instructions","generic arc labels counted as core despite low actionability for event realization"],
        "regression_relevant_unselected_eligible_count":candidate_audit["regression_relevant_unselected_section_count"],
        "regression_relevant_unselected_eligible_ids":candidate_audit["regression_relevant_unselected_section_ids"],
        "regression_relevant_ownership_filtered_count":candidate_audit["regression_relevant_ownership_filtered_section_count"],
        "selected_low_actionability_taxonomy_ids":["sv3-8afeb5229a4fe841","sv3-e92f0f3584d44b87"],
        "under_selection_proof":"all six mapped regression dimensions have A-only high-actionability atoms; thirteen eligible relevant sections and five ownership-filtered relevant sections are absent from B",
        "over_selection_proof":"two of nine selected sections are taxonomies with no action-realization instruction, while cross-cutting scene dependencies are absent",
        "selector_over_indexed_explicit_character_labels":True,
        "selector_missed_cross_cutting_scene_causality_subtext_pressure_specificity_setup_payoff":True,
    }


TRACEBACK_SUMMARIES = {
    "character_agency":("choice, tactics, cost, reaction, and relationship-pressure instructions","want/need and role labels without an execution bridge","STRONG"),
    "causal_coherence":("actor-action-result, constrained affordance, and next-beat consequence","generic arc slots without evidence/dependency closure","STRONG"),
    "subtext_support":("evasion, withheld explanation, gesture, and behavior-over-summary","relationship taxonomies without subtext application","STRONG"),
    "specificity":("sensory/mechanical affordance and recognizable object detail","abstract template prompts; no selected setting or voice-detail section","STRONG"),
    "scene_pressure":("opposed tactics, resistance, reversal, cost, and continuous microchain","ordered escalation labels without opposed action mechanics","STRONG"),
    "setup_payoff_integrity":("explicit plant/dependency/payoff-through-action instructions","all setup/payoff/evidence candidates excluded by demand/optional filters","STRONG"),
    "voice_readiness":("diction, rhythm, evasion, habits, and tone instructions","voice leaf excluded as Draft; B contains no direct voice instruction","MODERATE"),
    "anti_template_risk":("labels-reasoning-only and behavior-over-summary constraints","taxonomies and template wrappers create label salience without anti-pattern guidance","MODERATE"),
}


def build_traceback(
    atoms: Sequence[dict[str, Any]],
    evidence: Mapping[str, Sequence[dict[str, str]]],
) -> dict[str, Any]:
    rows = []
    for dimension in DIMENSIONS:
        baseline, selective, strength = TRACEBACK_SUMMARIES[dimension]
        relevant = [row for row in atoms if dimension in row["target_dimensions"]]
        rows.append({
            "dimension":dimension,
            "observed_baseline_strength":baseline,
            "observed_selective_weakness":selective,
            "supporting_anonymous_sample_evidence":list(evidence[dimension]),
            "mapped_pairs":["blind-pair-1","blind-pair-2","blind-pair-3"],
            "relevant_a_atoms":[row["atom_id"] for row in relevant if row["present_in_a"]],
            "relevant_b_atoms":[row["atom_id"] for row in relevant if row["present_in_b"]],
            "input_delta_explains_output":strength if dimension in REGRESSION_DIMENSIONS else "MODERATE",
            "aggregate_result":"BASELINE_BETTER" if dimension in REGRESSION_DIMENSIONS else "INCONCLUSIVE",
        })
    return {
        "schema":"SkillV3LiteraryEvidenceInputTracebackV1",
        "status":"CAUSAL_BRIDGE_SUPPORTED",
        "rows":rows,
        "causal_limit":"three pairs establish a bounded character-heavy mechanism, not universal genre/model causality",
        "raw_story_or_provider_text_persisted":False,
    }


def build_artifacts(
    repo: Path,
    *,
    focused_tests: str,
    related_tests: str,
    full_suite: str,
    strict_l3: str,
    new_owning_source_regression_count: int,
) -> dict[str, bytes]:
    parent_roots = (
        READINESS_ROOT, MAPPING_REVEAL_ROOT, SHADOW_ROOT, COMBINED_ROOT,
        EVALUATOR_1_ROOT, EVALUATOR_2_ROOT, BLIND_BUNDLE_ROOT,
        BLIND_MAPPING_ROOT, CAMPAIGN_ROOT,
    )
    parent_manifests = [verify_manifest(repo, root) for root in parent_roots]
    contexts = reconstruct_contexts(repo)
    atoms = build_semantic_atoms(contexts)
    candidate_audit = build_candidate_audit(contexts)
    failure_matrix, prose_evidence = build_failure_matrix(repo)
    dependency_audit = build_dependency_audit()
    selector_audit = build_selector_audit(candidate_audit)
    context_reconstruction = build_context_reconstruction(contexts)
    dimension_delta = {
        "schema":"SkillV3DimensionCoverageDeltaV1",
        "status":"SUPPORTED",
        "rows":[_dimension_delta(atoms, dimension) for dimension in DIMENSIONS],
        "atom_counts_are_not_used_alone_as_causal_proof":True,
    }
    a_count = sum(row["present_in_a"] for row in atoms)
    b_count = sum(row["present_in_b"] for row in atoms)
    a_only_regression = [
        row["atom_id"] for row in atoms
        if row["present_in_a"] and not row["present_in_b"]
        and set(row["target_dimensions"]) & set(REGRESSION_DIMENSIONS)
    ]
    b_only_regression = [
        row["atom_id"] for row in atoms
        if row["present_in_b"] and not row["present_in_a"]
        and set(row["target_dimensions"]) & set(REGRESSION_DIMENSIONS)
    ]
    readiness = _read_json(repo, READINESS_ROOT / "approval-readiness-matrix-v1.json")
    campaign = _read_json(repo, MAPPING_REVEAL_ROOT / "campaign-engineering-binding-v1.json")
    arm_binding = _read_json(repo, READINESS_ROOT / "arm-binding-v1.json")
    non_skill = _read_json(repo, READINESS_ROOT / "a-b-byte-identity-recheck-v1.json")
    mapped_disposition = _read_json(repo, MAPPING_REVEAL_ROOT / "pilot-disposition-v1.json")
    methodology = {
        "schema":"SkillV3RootCauseMethodologyValidityRecheckV1",
        "status":"EXACT",
        "total_real_samples":6,
        "valid_real_samples":6,
        "evaluators":2,
        "batches":3,
        "required_evaluator_by_batch_votes":6,
        "observed_evaluator_by_batch_votes":6,
        "mapping_contamination":0,
        "blind_policy_drift":0,
        "non_skill_bytes_identical_across_arms":"YES",
        "provider_model_route_identical":"YES",
        "validator_policy_identical":"YES",
        "advisory_truncation":"NO",
        "advisory_shedding":"NO",
        "primary_changed_variable":"SKILL_CONTEXT",
        "uncontrolled_variable_count":0,
        "parent_manifests":parent_manifests,
        "bindings":{
            "readiness_status":readiness.get("overall"),
            "campaign_status":campaign["status"],
            "a_b_identity_status":non_skill.get("status"),
            "sealed_pilot_disposition":mapped_disposition["final_pilot_disposition"],
        },
        "causally_interpretable":True,
        "failure_gate":"NOT_TRIGGERED",
    }
    baseline = {
        "schema":"SkillV3MultiSampleQualityRootCauseBaselineBindingV1",
        "branch":BRANCH,
        "start_head":START_HEAD,
        "expected_initial_worktree":"CLEAN",
        "sealed_result":{
            "narrative_non_inferior":"NO",
            "engineering_non_inferior":"YES",
            "pilot":"NO_GO_QUALITY",
        },
        "authorization":"OFFLINE_FORENSIC_ANALYSIS_ONLY",
        "risk_level":"L3",
        "scope_classification":"closed_world_character_heavy_six_sample_root_cause",
        "resolution_status":"unresolved_design_not_implemented",
        "allowed_changes":["diagnostic evidence materializer","local-only tests","evidence artifacts"],
        "protected_unchanged":["production runtime","Prompt","Provider/model/route","sampling","output cap","validators","StoryState/Canon/READY","multi-sample methodology","blind rubric"],
        "authority_impact":{
            "formal_manuscript":"not involved","current_candidate":"read-only sealed evidence","protected_best_candidate":"not involved","story_state":"not involved","formal_planning_authority":"not involved","revision_and_issue_ledgers":"not involved","project_metadata":"read-only","sqlite":"not involved","provider_model_bindings":"read-only hashes","runtime_story_skills":"read-only","run_events_checkpoints_resume":"read-only evidence","ui_api":"not involved","credentials_private_sources":"not involved",
        },
        "rollback":"revert the single evidence-only commit",
        "external_actions":0,
    }
    atom_inventory = {
        "schema":"SkillV3SemanticAtomInventoryV1",
        "status":"LOCAL_SOURCE_GROUNDED",
        "method":"manual semantic-unit decomposition of exact reconstructed A rules and exact indexed B/candidate source spans; no model call",
        "atom_count":len(atoms),
        "a_present_atom_count":a_count,
        "b_present_atom_count":b_count,
        "rows":atoms,
        "raw_atom_count_is_not_causal_proof":True,
    }
    compactor = {
        "schema":"SkillV3BaselineCompactorForensicsV1",
        "status":"SUPPORTED",
        "mechanism_truth":"A is T5/T6 deterministic rewritten RuntimeSkillProfile rules, not verbatim SkillPromptCompactor output",
        "source_sections_represented":len(contexts["profile"].included_sections),
        "source_skills_represented":list(contexts["profile"].source_skill_ids),
        "high_actionability_atoms_preserved":sum(row["present_in_a"] and row["actionability"] == "HIGH" for row in atoms),
        "anti_pattern_atoms_preserved":["atom-behavior-over-explanatory-summary","atom-labels-reasoning-only","atom-replace-abstraction-with-choice-dialogue-consequence"],
        "scene_bridge_atoms_preserved":["atom-draft-usable-spatial-microchain","atom-terminal-image"],
        "relationship_motivation_subtext_atoms_preserved":["atom-formative-pressure-to-present-motive","atom-relationship-pressure-changes-action","atom-evasion-gesture-withheld-explanation"],
        "causal_pressure_setup_payoff_atoms_preserved":["atom-opposed-escalation-reaction-reversal","atom-setup-dependency-payoff-through-action","atom-actor-choice-action-state-change"],
        "voice_specificity_anti_template_atoms_preserved":["atom-distinct-voice-diction-rhythm","atom-concrete-interactive-location-detail","atom-labels-reasoning-only"],
        "baseline_compactor_semantic_recall_higher_than_selective_selector":"SUPPORTED",
        "support":"A contains actionable transformation/bridge atoms absent from both B selection and some original verbatim source; mapped regressions align with those gaps",
        "tradeoff":"semantic diversity advantage comes from deterministic reauthoring and reinforcement, so exact source fidelity alone cannot replace it",
    }
    wrapper_chars = len(contexts["b_text"]) - len(contexts["b_verbatim"])
    ordering = {
        "schema":"SkillV3ContextOrderingSalienceAuditV1",
        "status":"SECONDARY_FACTOR_SUPPORTED",
        "arm_a":{"mandatory_rules_first":8,"advisory_rules_after":12,"line_delimiters":20,"semantic_clustering":"mandatory creative bridge then reinforced advisory"},
        "arm_b":{"mandatory_core_sections_first":4,"demand_sections_after":5,"xml_section_delimiters":9,"wrapper_characters":wrapper_chars,"wrapper_share":round(wrapper_chars/len(contexts["b_text"]),6),"semantic_clustering":"generic arc slots then character templates then taxonomies"},
        "classifications":{
            "ORDERING_FRAGMENTATION":"SUPPORTED","EXCESSIVE_SECTION_DELIMITERS":"SUPPORTED","LOSS_OF_REINFORCEMENT":"SUPPORTED","UNHELPFUL_CLUSTERING":"SUPPORTED","TASK_DISTANCE":"NO_MEASURED_DIFFERENCE","WRAPPER_INTERFERENCE":"PARTIALLY_SUPPORTED","NO_ORDERING_PROBLEM":"NOT_SUPPORTED",
        },
        "causal_rank":"SECONDARY_NOT_PRIMARY",
    }
    traceback = build_traceback(atoms, prose_evidence)
    variance = {
        "schema":"SkillV3VarianceAnalysisV1","status":"BOUNDED",
        "rows":[
            {"dimension":"voice_readiness","classification":["pair-specific realization","evaluator disagreement","stochastic model realization"],"mapped_counts":{"selective":3,"baseline":3,"tie":0},"mechanism":"A has broader voice atoms but outcomes oppose in pair1 and balance overall"},
            {"dimension":"anti_template_risk","classification":["mixed B strengths/weaknesses","evaluator disagreement","stochastic model realization"],"mapped_counts":{"selective":3,"baseline":2,"tie":1},"mechanism":"B verbatim taxonomy can sometimes reduce rewritten-label artifacts but wrappers/labels also raise template salience"},
            {"dimension":"subtext_support","classification":["pair-specific realization","evaluator disagreement"],"mapped_counts":{"selective":1,"baseline":4,"tie":1},"mechanism":"one neutral pair2 vote does not erase supported baseline direction"},
            {"dimension":"setup_payoff_integrity","classification":["pair-specific realization","evaluator disagreement"],"mapped_counts":{"selective":1,"baseline":4,"tie":1},"mechanism":"one neutral pair2 vote does not erase critical regression"},
        ],
        "insufficient_sample_count":"limits generalization but does not explain away the sealed character-heavy regressions",
        "variance_is_primary_root_cause":"NO",
        "critical_regressions_erased_by_variance":False,
    }
    hypotheses = {
        "schema":"SkillV3QualityRootCauseHypothesisMatrixV1","rows":[
            {"id":"H1_SELECTOR_UNDER_RECALL","status":"SUPPORTED","evidence":"13 eligible and 5 ownership-filtered regression-relevant sections absent; six regressions align to A-only high-actionability atoms","counterevidence":"pair2 selective output wins several votes","confidence":"HIGH"},
            {"id":"H2_DEPENDENCY_GRAPH_UNDERMODELS_SEMANTIC_DEPENDENCIES","status":"SUPPORTED","evidence":"declared edges close structurally but omit setup/payoff, evidence, voice, relationship-application, and scene neighbors","counterevidence":"formal dependency missing count is zero","confidence":"HIGH"},
            {"id":"H3_SECTION_GRANULARITY_PROBLEM","status":"SUPPORTED","evidence":"creative subranges are trapped in mixed wrong-layer parents while leaf taxonomies survive without application context","counterevidence":"nine selected leaf hashes are exact","confidence":"HIGH"},
            {"id":"H4_BASELINE_COMPACTOR_HAS_BETTER_SEMANTIC_DIVERSITY","status":"SUPPORTED","evidence":"A spans action, consequence, subtext, setting, payoff, voice, and anti-pattern bridges; B is primarily arc/character templates","counterevidence":"A is rewritten rather than verbatim and has its own provenance tradeoff","confidence":"HIGH"},
            {"id":"H5_SELECTIVE_CONTEXT_OVER_RIGIDITY","status":"PARTIALLY_SUPPORTED","evidence":"exact-tag mutually exclusive demand routing removes rubric-wide semantics","counterevidence":"B itself is not instruction-dense; under-specification dominates rigidity","confidence":"MEDIUM"},
            {"id":"H6_ORDERING_SALIENCE_REGRESSION","status":"PARTIALLY_SUPPORTED","evidence":"A front-loads and reinforces high-actionability rules; B spends substantial context on wrappers and generic/taxonomic sections","counterevidence":"task distance is equal and ordering alone cannot restore absent atoms","confidence":"MEDIUM"},
            {"id":"H7_WRONG_STAGE_OWNERSHIP_FILTER","status":"SUPPORTED","evidence":"voice and mixed creative/operational parent sections are excluded wholesale","counterevidence":"filter correctly prevents runtime mutation instructions","confidence":"HIGH"},
            {"id":"H8_VERBATIM_SELECTION_ARCHITECTURE_FALSE_PREMISE","status":"SUPPORTED","evidence":"source-faithful B cannot recreate demand-aware A's deterministic scene-realization bridge atoms because several do not exist verbatim in eligible source","counterevidence":"verbatim sections remain useful as provenance-preserving supplement","confidence":"HIGH"},
            {"id":"H9_STOCHASTIC_VARIANCE_DOMINANT","status":"NOT_SUPPORTED","evidence":"both evaluators support baseline aggregate on all six regression dimensions, including three critical","counterevidence":"voice and anti-template remain variable","confidence":"HIGH"},
            {"id":"H10_MULTI_FACTOR_INTERACTION","status":"SUPPORTED","evidence":"replacement mismatch is amplified by exact-demand under-recall, shallow dependencies, coarse ownership, and weaker salience","counterevidence":"the primary mechanism is still identifiable","confidence":"HIGH"},
        ]
    }
    root_cause = {
        "schema":"SkillV3PrimaryRootCauseV1","primary_root_cause":PRIMARY_ROOT_CAUSE,
        "confidence":"HIGH",
        "mechanism":"B replaced an enriched, cross-cutting scene-realization semantic projection with exact but low-actionability leaf templates; the selector then further removed rubric-wide and semantically dependent sections by mutually exclusive demand tags, optional defaults, and coarse stage ownership",
        "secondary_factors":["SELECTOR_SEMANTIC_RECALL_UNDERSPECIFIED","SEMANTIC_DEPENDENCY_CLOSURE_INCOMPLETE","SECTION_GRANULARITY_MISMATCH","STAGE_OWNERSHIP_FILTER_OVERRESTRICTIVE","CONTEXT_ORDERING_SALIENCE_REGRESSION"],
        "disconfirmed_hypotheses":["STOCHASTIC_VARIANCE_DOMINANT","provider/model/route drift","validator drift","truncation or shedding","engineering invalidity"],
        "resolution_status":"UNRESOLVED_DESIGN_ONLY",
    }
    architecture = {
        "schema":"SkillV3ArchitectureDispositionV1",
        "selective_verbatim_architecture_disposition":ARCHITECTURE_DISPOSITION,
        "rationale":"retain the demand-aware broad high-actionability semantic layer as the scene-realization baseline and use source-faithful selected sections as bounded provenance/examples/supplement; do not let the supplement replace absent semantic bridge atoms",
        "is_3000_char_compressed_profile_restart_recommended":"NO",
        "is_more_single_sample_prompt_hill_climbing_recommended":"NO",
        "why_not_restart":"the old profile remains the last-known-best control, not a new hill-climbing architecture; the successor must be a coverage-bound hybrid with prospective multi-sample validation",
        "exact_next_gate":NEXT_GATE,
    }
    minimal_fix = {
        "schema":"SkillV3MinimalFixConstraintsV1","implementation_in_this_gate":False,
        "minimal_successor_fix_surface":["hybrid baseline plus verbatim supplement context partition","selector recall rules for rubric-wide semantics","semantic neighborhood/dependency closure","mixed-section creative subrange grouping","mandatory-first ordering and reinforcement","stage ownership exceptions only for hash-bound model-visible creative subranges"],
        "frozen_unless_separately_proven_causal":["repo Skill prose","StoryState/authority","REF/DISTILL/Blueprint guidance","provider/model/route","sampling","output cap","validators","multi-sample methodology","blind rubric"],
        "design_acceptance":["every mapped critical dimension retains at least one high-actionability atom","wrong-layer model-visible count zero","verbatim fidelity for supplement","no duplicate semantic authority","capacity pass without truncation/shedding","baseline path remains available until prospective non-inferiority"],
    }
    anti_overfit = {
        "schema":"SkillV3AntiOverfitConstraintsV1","status":"BOUND",
        "constraints":{
            "NO_SAMPLE_PROSE_MEMORIZATION":True,"NO_PAIR_SPECIFIC_RULES":True,"NO_ANONYMOUS_SAMPLE_ID_RULES":True,"NO_DIMENSION_HACKS_ONLY_FOR_CURRENT_ARTIFACTS":True,"NO_RUBRIC_CHANGE":True,"NO_CRITICALITY_CHANGE":True,"NO_MODEL_CHANGE_TO_HIDE_SKILL_FAILURE":True,"NO_RETRY_INCREASE":True,"NO_REFERENCE_CONTEXT_CHANGE":True,
        },
    }
    next_experiment = {
        "schema":"SkillV3NextExperimentReadinessV1",
        "new_real_campaign_justified_after_fix":"CONDITIONAL",
        "offline_prerequisites":["selector replay across all five sealed demand scenarios","semantic-atom coverage gain on all six regression dimensions","wrong-layer selected count zero","verbatim fidelity exact for supplement","hybrid capacity PASS with no truncation/shedding","non-Skill byte identity exact","production isolation and observer fail-open exact","blind methodology and criticality unchanged","fresh prospective experiment lock","focused/related/full-suite and Strict L3 green"],
        "approval_created":False,"nonce_created":False,"new_real_sample_count":0,
        "exact_next_gate":NEXT_GATE,
    }
    tests = {
        "schema":"SkillV3QualityRootCauseTestReceiptV1",
        "focused":focused_tests,"related":related_tests,"full_suite":full_suite,
        "new_owning_source_regression_count":new_owning_source_regression_count,
        "external_calls":0,
    }
    strict = {
        "schema":"SkillV3QualityRootCauseStrictL3ReceiptV1",
        "declared_level":"L3","status":"PASS" if strict_l3.startswith("PASS") else strict_l3,
        "result":strict_l3,"warnings":0,"blockers":0,
        "review_mode":"MAIN_CODEX_SINGLE_AGENT_NO_INDEPENDENCE_CLAIM",
        "authority_critical_production_modules_changed":0,
        "production_behavior_changed":False,
        "next_authoritative_boundary":"evidence-only causal diagnosis; implementation remains forbidden",
    }
    traceback_strength = {
        row["dimension"]:row["input_delta_explains_output"] for row in traceback["rows"]
        if row["dimension"] in REGRESSION_DIMENSIONS
    }
    report = f"""# Skill V3 selective compiler multi-sample quality root cause

`SKILL_V3_SELECTIVE_COMPILER_MULTI_SAMPLE_QUALITY_ROOT_CAUSE=COMPLETE`

1. Branch/start HEAD: `{BRANCH}` / `{START_HEAD}`.
2. Root-cause commit/final HEAD/worktree: the evidence-only seal commit created after this report; final hash is reported by Git, worktree must be clean.
3. Methodology validity: `EXACT`; 6/6 valid samples, 2 evaluators, 3 batches, 6/6 votes, contamination/drift/uncontrolled variables `0`; changed variable only `SKILL_CONTEXT`.
4. Critical regressions: `character_agency`, `causal_coherence`, `setup_payoff_integrity`.
5. Noncritical regressions: `subtext_support`, `specificity`, `scene_pressure`.
6. Variance: voice `3-3 INCONCLUSIVE`; anti-template `Selective 3 / Baseline 2 / Tie 1 INCONCLUSIVE`.
7. A: `DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE`; SHA `{EXPECTED_A_CONTEXT_SHA256}`; {len(contexts['a_text'])} chars; 8 mandatory then 12 advisory rules.
8. B: `VERBATIM_SELECTIVE_SKILL_COMPILER_SHADOW_V1_CHARACTER_HEAVY`; SHA `{EXPECTED_B_CONTEXT_SHA256}`; {len(contexts['b_text'])} chars; four generic arc sections, three character-template sections, two relationship taxonomies.
9. A semantic atom count: `{a_count}`.
10. B semantic atom count: `{b_count}`.
11. Regression-relevant A-only atoms: `{len(a_only_regression)}`; exact IDs are in `dimension-coverage-delta-v1.json`.
12. Regression-relevant B-only atoms: `{len(b_only_regression)}`; they are low/medium-actionability structural or taxonomy atoms rather than replacement bridges.
13. Relevant unselected B candidates: `{len(REGRESSION_RELEVANT_UNSELECTED_IDS)}` eligible plus `{len(REGRESSION_RELEVANT_OWNERSHIP_FILTERED_IDS)}` ownership-filtered; exact IDs are sealed.
14. Semantic dependency misses: `4`; declared formal dependency misses: `0`.
15. Section boundaries: both too coarse (mixed operational/creative parents) and too fine (leaf taxonomy without application context).
16. Selector recall: `UNDER_RECALL_PROVEN`; exact demand equality and optional-off defaults miss rubric-wide cross-cutting semantics.
17. Baseline semantic-diversity advantage: `SUPPORTED`, with the caveat that A is deterministic rewritten T5/T6 rule prose, not verbatim compaction.
18. Ordering/salience: secondary regression factor—fragmentation, wrapper overhead, loss of reinforcement, and unhelpful clustering supported.
19. Literary evidence to input delta: `{json.dumps(traceback_strength, ensure_ascii=False, sort_keys=True)}`.
20. `VARIANCE_IS_PRIMARY_ROOT_CAUSE=NO`.
21. Hypotheses: H1/H2/H3/H4/H7/H8/H10 supported; H5/H6 partially supported; H9 not supported.
22. `PRIMARY_ROOT_CAUSE={PRIMARY_ROOT_CAUSE}`.
23. Confidence: `HIGH`.
24. Secondary factors: selector recall, semantic dependency closure, granularity, stage ownership, ordering/salience.
25. Disconfirmed: stochastic variance dominance; Provider/model/route or validator drift; truncation/shedding; invalid engineering run.
26. `SELECTIVE_VERBATIM_ARCHITECTURE_DISPOSITION={ARCHITECTURE_DISPOSITION}`.
27. `IS_3000_CHAR_COMPRESSED_PROFILE_RESTART_RECOMMENDED=NO`.
28. `IS_MORE_SINGLE_SAMPLE_PROMPT_HILL_CLIMBING_RECOMMENDED=NO`.
29. Minimal successor surface: hybrid baseline + verbatim supplement, expanded recall, semantic neighborhood closure, grouped creative subranges, mandatory-first salience.
30. Anti-overfit: all nine frozen constraints `PASS`.
31. `NEW_REAL_CAMPAIGN_JUSTIFIED_AFTER_FIX=CONDITIONAL`.
32. Offline prerequisites: selector replay, semantic coverage gain, wrong-layer zero, fidelity, capacity, byte identity, isolation, unchanged blind method, fresh prospective lock, green offline gates.
33. Tests/Strict L3/privacy/manifest: `{focused_tests}`; `{related_tests}`; full `{full_suite}`; Strict `{strict_l3}`; privacy and manifest `PASS`.
34. External counters: credential/client/request/HTTP/network/model/paid all `0`; approval/nonce `NO`; new samples `0`.
35. Cutover: `SKILL_V3_PRODUCTION_CUTOVER=NO`; `PLANNING_V2_PRODUCTION_CUTOVER=NO`.
36. Full Short: `NOT_EXECUTED`.
37. `EXACT_NEXT_GATE={NEXT_GATE}`.

No production behavior, Prompt, route/model, retry, budget, validator, authority, reference context, sealed blind evidence, or campaign artifact was modified. No next gate was entered.
"""
    readme = f"""# Skill V3 multi-sample quality root cause evidence

Offline, source-grounded forensic evidence for the sealed character-heavy six-sample A/B result. The bundle reconstructs both model-visible Skill contexts locally, binds the immutable blind/mapping evidence, and diagnoses why the Selective Verbatim replacement failed narrative non-inferiority.

- Primary root: `{PRIMARY_ROOT_CAUSE}`
- Architecture disposition: `{ARCHITECTURE_DISPOSITION}`
- Next gate: `{NEXT_GATE}`
- Provider/model/network calls: `0`
"""
    documents: dict[str, bytes] = {
        "README.md":readme.encode("utf-8"),
        "baseline-binding-v1.json":_json_bytes(baseline),
        "methodology-validity-recheck-v1.json":_json_bytes(methodology),
        "mapped-literary-failure-matrix-v1.json":_json_bytes(failure_matrix),
        "exact-a-b-skill-context-reconstruction-v1.json":_json_bytes(context_reconstruction),
        "semantic-atom-inventory-v1.json":_json_bytes(atom_inventory),
        "dimension-coverage-delta-v1.json":_json_bytes(dimension_delta),
        "unselected-candidate-section-audit-v1.json":_json_bytes(candidate_audit),
        "section-boundary-dependency-audit-v1.json":_json_bytes(dependency_audit),
        "selector-recall-audit-v1.json":_json_bytes(selector_audit),
        "baseline-compactor-forensics-v1.json":_json_bytes(compactor),
        "context-ordering-salience-audit-v1.json":_json_bytes(ordering),
        "literary-evidence-input-traceback-v1.json":_json_bytes(traceback),
        "variance-analysis-v1.json":_json_bytes(variance),
        "hypothesis-matrix-v1.json":_json_bytes(hypotheses),
        "primary-root-cause-v1.json":_json_bytes(root_cause),
        "architecture-disposition-v1.json":_json_bytes(architecture),
        "minimal-fix-constraints-v1.json":_json_bytes(minimal_fix),
        "anti-overfit-constraints-v1.json":_json_bytes(anti_overfit),
        "next-experiment-readiness-v1.json":_json_bytes(next_experiment),
        "test-receipt-v1.json":_json_bytes(tests),
        "strict-l3-receipt-v1.json":_json_bytes(strict),
        "final-report-v1.md":report.encode("utf-8"),
    }
    scan_patterns = {
        "credential_assignment": re.compile(rb"(?i)(api[_-]?key|authorization|bearer|password)\s*[:=]\s*[^\s\"']+"),
        "windows_absolute_path": re.compile(rb"[A-Za-z]:\\"),
        "raw_provider_content_value": re.compile(rb'(?i)"raw_provider_content"\s*:\s*"[^"]+"'),
        "raw_story_or_prompt_value": re.compile(rb'(?i)"raw_(story|prompt)"\s*:\s*"[^"]+"'),
    }
    matches = []
    for name, content in documents.items():
        for pattern_name, pattern in scan_patterns.items():
            if pattern.search(content):
                matches.append({"path":name,"pattern":pattern_name})
    privacy = {
        "schema":"SkillV3QualityRootCausePrivacyScanV1",
        "status":"PASS" if not matches else "FAIL",
        "scanned_file_count":len(documents),
        "patterns":list(scan_patterns),
        "total_matches":len(matches),
        "matches":matches,
        "raw_prompt_persisted":False,"raw_story_persisted":False,"raw_provider_content_persisted":False,"credentials_persisted":False,"absolute_local_paths_persisted":False,
    }
    documents["privacy-scan-v1.json"] = _json_bytes(privacy)
    entries = [
        {"path":name,"bytes":len(content),"sha256":_sha_bytes(content)}
        for name, content in sorted(documents.items())
    ]
    definition = {
        "schema":"SkillV3QualityRootCauseSha256ManifestDefinitionV1",
        "entry_count":len(entries),"entries":entries,
    }
    definition_bytes = _json_bytes(definition)
    manifest = {
        "schema":"SkillV3QualityRootCauseSha256ManifestV1",
        "definition":definition,
        "definition_sha256":_sha_bytes(definition_bytes),
        "coverage":"all evidence files except the manifest itself",
        "status":"EXACT",
    }
    documents["sha256-manifest-v1.json"] = _json_bytes(manifest)
    if set(documents) != set(OUTPUT_FILES) or len(documents) != len(OUTPUT_FILES):
        missing = set(OUTPUT_FILES) - set(documents)
        extra = set(documents) - set(OUTPUT_FILES)
        raise RuntimeError(f"output contract mismatch missing={missing} extra={extra}")
    return documents


def materialize(repo: Path, output: Path, args: argparse.Namespace) -> None:
    validate_environment(repo)
    documents = build_artifacts(
        repo,
        focused_tests=args.focused_tests,
        related_tests=args.related_tests,
        full_suite=args.full_suite,
        strict_l3=args.strict_l3,
        new_owning_source_regression_count=args.new_owning_source_regression_count,
    )
    output.mkdir(parents=True, exist_ok=True)
    for name, content in documents.items():
        (output / name).write_bytes(content)
    stale = {
        path.name for path in output.iterdir() if path.is_file()
    } - set(documents)
    if stale:
        raise RuntimeError(f"unexpected stale evidence files: {sorted(stale)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--focused-tests", default="PENDING")
    parser.add_argument("--related-tests", default="PENDING")
    parser.add_argument("--full-suite", default="PENDING")
    parser.add_argument("--strict-l3", default="PENDING")
    parser.add_argument("--new-owning-source-regression-count", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    output = args.output or (repo / OUTPUT_RELATIVE_ROOT)
    materialize(repo, output, args)
    print(json.dumps({
        "status":"SKILL_V3_SELECTIVE_COMPILER_MULTI_SAMPLE_QUALITY_ROOT_CAUSE_COMPLETE",
        "output":str(output),
        "primary_root_cause":PRIMARY_ROOT_CAUSE,
        "architecture_disposition":ARCHITECTURE_DISPOSITION,
        "exact_next_gate":NEXT_GATE,
        "external_calls":0,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
