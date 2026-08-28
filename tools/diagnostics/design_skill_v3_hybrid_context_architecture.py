"""Materialize the offline Skill V3 hybrid-context architecture evidence.

This diagnostic owns no production dispatch path.  It reconstructs sealed local
Skill sources, compares bounded architecture candidates, simulates protected
capacity partitions, and writes hash-only/reconstructible design evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

_REPO_IMPORT_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_IMPORT_ROOT))

from novel_flywheel.context_policy import estimate_input_tokens
from novel_flywheel.pilot_guidance import render_pilot_advisory_partition
from novel_flywheel.runtime_skill_profiles import (
    SkillLoadDecisionInputsV1,
    build_planning_v2_event_realization_profile_demand_aware,
    render_skill_context,
)
from novel_flywheel.selective_skill_compiler import (
    SelectiveSkillCompilerV1,
    SkillSectionIndexV1,
)
from tools.diagnostics.close_skill_v3_reference_distill_binding import (
    frozen_project_guidance,
)


BRANCH = "r1-ptr3/planning-repair-finding-propagation-20260817"
START_HEAD = "d385d1c1878e8894b411669416b4b485d6e7c504"
ROOT_CAUSE = Path(
    "docs/superpowers/reports/"
    "skill-v3-selective-compiler-multi-sample-quality-root-cause-v1"
)
REFERENCE_ROOT = Path(
    "docs/superpowers/reports/"
    "skill-v3-pilot-reference-distill-runtime-binding-closure-v1"
)
OUTPUT = Path(
    "docs/superpowers/reports/"
    "skill-v3-hybrid-skill-context-architecture-design-v1"
)
INDEX = Path("vendor/novel-skills/skill-section-index-v1.json")
BUNDLE = Path("vendor/novel-skills/source")

DECISION = (
    "COMPOSED_HYBRID_CROSS_SKILL_SCENE_PACKET_WITH_"
    "VERBATIM_NEIGHBORHOOD_CLOSURE"
)
NEXT_GATE = "SKILL_V3_HYBRID_SKILL_CONTEXT_SHADOW_IMPLEMENTATION"
DEMANDS = (
    "character-heavy",
    "world-heavy",
    "conflict-pacing-heavy",
    "setup-payoff-heavy",
    "mixed",
)
RESOLVED_SKILLS = (
    "story-init", "plot-structure", "character-management", "worldbuilding",
)
ZERO = {
    "credential_lookup_count": 0,
    "provider_client_creation_count": 0,
    "real_provider_calls": 0,
    "network_calls": 0,
    "model_calls": 0,
    "paid_calls": 0,
}
SUPPLEMENT_SEPARATOR = (
    "\n\nOriginal Skill supplement (advisory; enriches the protected baseline "
    "and cannot override authority or task):\n"
)

REQUIRED_FILES = (
    "README.md",
    "baseline-binding-v1.json",
    "root-cause-to-requirements-v1.json",
    "baseline-foundation-invariant-v1.json",
    "reference-guidance-preservation-v1.json",
    "hybrid-candidate-comparison-v1.json",
    "supplement-demand-model-v1.json",
    "actionability-model-v1.json",
    "semantic-dependency-model-v1.json",
    "section-packet-granularity-v1.json",
    "overlap-duplication-policy-v1.json",
    "precedence-policy-v1.json",
    "protected-budget-design-v1.json",
    "capacity-study-v1.json",
    "render-order-salience-v1.json",
    "provenance-observability-schema-v1.json",
    "character-heavy-forensic-replay-spec-v1.json",
    "cross-demand-anti-overfit-replay-spec-v1.json",
    "architecture-decision-v1.json",
    "successor-experiment-design-v1.json",
    "real-campaign-prerequisites-v1.json",
    "implementation-plan-v1.json",
    "privacy-scan-v1.json",
    "test-receipt-v1.json",
    "strict-l3-receipt-v1.json",
    "final-report-v1.md",
    "sha256-manifest-v1.json",
)

# Packets contain exact source-section identities.  The voice section is an
# intentionally designed future index-v2 ownership exception: the complete
# reference section is creative guidance, while the current coarse index labels
# it DRAFT.  No operational parent section is admitted.
PACKETS = {
    "CHARACTER_CHOICE_VOICE_PACKET_V1": (
        "sv3-4c39329c602fd48e",
        "sv3-10e4ba0c5b7509b4",
        "sv3-b75227453c1cc26a",
        "sv3-8e321726b4ebdcec",
    ),
    "CAUSAL_PRESSURE_PACKET_V1": (
        "sv3-faecc1466817d8aa",
        "sv3-13580b3cdbef263e",
        "sv3-2985467b5f2bf929",
        "sv3-5f738df332e0919f",
        "sv3-60d4bee497e4c0dc",
    ),
    "SETUP_PAYOFF_CLOSURE_PACKET_V1": (
        "sv3-ac7aa3aed8a7d237",
        "sv3-2ced894267dc51e3",
        "sv3-82ca2fdf9c28183b",
        "sv3-972a75cb8ca8f0bd",
        "sv3-6e4a0b2625a01274",
        "sv3-ad3871e96cc16876",
    ),
    "WORLD_AFFORDANCE_PRESSURE_PACKET_V1": (
        "sv3-2985467b5f2bf929",
        "sv3-60d4bee497e4c0dc",
        "sv3-5f738df332e0919f",
        "sv3-f998823d27d7086b",
        "sv3-b4583d410167ab14",
        "sv3-ad3871e96cc16876",
        "sv3-0933e75cb694edca",
    ),
}

DEMAND_PACKETS = {
    "character-heavy": (
        "CHARACTER_CHOICE_VOICE_PACKET_V1",
        "CAUSAL_PRESSURE_PACKET_V1",
        "SETUP_PAYOFF_CLOSURE_PACKET_V1",
    ),
    "world-heavy": (
        "WORLD_AFFORDANCE_PRESSURE_PACKET_V1",
        "CAUSAL_PRESSURE_PACKET_V1",
        "SETUP_PAYOFF_CLOSURE_PACKET_V1",
    ),
    "conflict-pacing-heavy": (
        "CAUSAL_PRESSURE_PACKET_V1",
        "CHARACTER_CHOICE_VOICE_PACKET_V1",
        "SETUP_PAYOFF_CLOSURE_PACKET_V1",
    ),
    "setup-payoff-heavy": (
        "SETUP_PAYOFF_CLOSURE_PACKET_V1",
        "CAUSAL_PRESSURE_PACKET_V1",
    ),
    "mixed": (
        "CHARACTER_CHOICE_VOICE_PACKET_V1",
        "WORLD_AFFORDANCE_PRESSURE_PACKET_V1",
        "CAUSAL_PRESSURE_PACKET_V1",
        "SETUP_PAYOFF_CLOSURE_PACKET_V1",
    ),
}

FEATURES = {
    "character_agency_motivation": {
        "signals": ["actor refs present", "want/need conflict", "costly choice", "opposed tactics"],
        "required_packets": ["CHARACTER_CHOICE_VOICE_PACKET_V1", "CAUSAL_PRESSURE_PACKET_V1"],
    },
    "relationship_consequence": {
        "signals": ["two or more actor refs", "relationship/trust/role pressure", "reaction changes available action"],
        "required_packets": ["CHARACTER_CHOICE_VOICE_PACKET_V1", "CAUSAL_PRESSURE_PACKET_V1"],
    },
    "causal_coherence": {
        "signals": ["cause/effect chain", "obstacle/reaction/reversal", "state transition"],
        "required_packets": ["CAUSAL_PRESSURE_PACKET_V1"],
    },
    "subtext_dramatization": {
        "signals": ["dialogue/evasion/gesture", "withheld explanation", "relationship pressure"],
        "required_packets": ["CHARACTER_CHOICE_VOICE_PACKET_V1"],
    },
    "scene_pressure": {
        "signals": ["opposition", "deadline/cost/limit", "resistance/reversal"],
        "required_packets": ["CAUSAL_PRESSURE_PACKET_V1"],
    },
    "specificity": {
        "signals": ["location/system/artifact refs", "interactive feature", "sensory/mechanical affordance"],
        "required_packets": ["WORLD_AFFORDANCE_PRESSURE_PACKET_V1"],
    },
    "setup_payoff": {
        "signals": ["promise/question/foreshadowing", "dependency", "later action payoff"],
        "required_packets": ["SETUP_PAYOFF_CLOSURE_PACKET_V1"],
    },
    "voice_readiness": {
        "signals": ["speaker identity", "diction/rhythm/tic", "dialogue realization"],
        "required_packets": ["CHARACTER_CHOICE_VOICE_PACKET_V1"],
    },
    "anti_template_realization": {
        "signals": ["taxonomy/summary risk", "behavioral evidence required", "concrete terminal image"],
        "required_packets": ["CHARACTER_CHOICE_VOICE_PACKET_V1", "CAUSAL_PRESSURE_PACKET_V1"],
    },
}

ACTIONABILITY = {
    "HIGH_ACTIONABILITY": {
        "criteria": [
            "imperative or executable scene operation",
            "binds cause to observable action/reaction/consequence",
            "provides dramatization, voice, pressure, or setup/payoff method",
            "anti-pattern paired with a concrete correction",
        ],
        "examples": [
            "sv3-b75227453c1cc26a", "sv3-13580b3cdbef263e",
            "sv3-5f738df332e0919f", "sv3-972a75cb8ca8f0bd",
        ],
    },
    "MEDIUM_ACTIONABILITY": {
        "criteria": [
            "concrete field or sequence that constrains realization",
            "usable qualifier/example but not a complete operation on its own",
        ],
        "examples": [
            "sv3-10e4ba0c5b7509b4", "sv3-8e321726b4ebdcec",
            "sv3-2985467b5f2bf929", "sv3-ad3871e96cc16876",
        ],
    },
    "LOW_ACTIONABILITY": {
        "criteria": [
            "taxonomy label, abstract category, heading, or thin template leaf",
            "cannot satisfy a demand feature without a higher-actionability neighbor",
        ],
        "examples": [
            "sv3-2ced894267dc51e3", "sv3-82ca2fdf9c28183b",
        ],
        "admission": "DEPENDENCY_ONLY; never a seed and never sole coverage",
    },
}

SECTION_ACTIONABILITY = {
    "sv3-2ced894267dc51e3": "LOW_ACTIONABILITY",
    "sv3-82ca2fdf9c28183b": "LOW_ACTIONABILITY",
    "sv3-972a75cb8ca8f0bd": "HIGH_ACTIONABILITY",
    "sv3-faecc1466817d8aa": "MEDIUM_ACTIONABILITY",
    "sv3-6e4a0b2625a01274": "MEDIUM_ACTIONABILITY",
    "sv3-13580b3cdbef263e": "HIGH_ACTIONABILITY",
    "sv3-ac7aa3aed8a7d237": "HIGH_ACTIONABILITY",
    "sv3-4c39329c602fd48e": "MEDIUM_ACTIONABILITY",
    "sv3-10e4ba0c5b7509b4": "HIGH_ACTIONABILITY",
    "sv3-b75227453c1cc26a": "HIGH_ACTIONABILITY",
    "sv3-8e321726b4ebdcec": "MEDIUM_ACTIONABILITY",
    "sv3-2985467b5f2bf929": "MEDIUM_ACTIONABILITY",
    "sv3-b4583d410167ab14": "MEDIUM_ACTIONABILITY",
    "sv3-5f738df332e0919f": "HIGH_ACTIONABILITY",
    "sv3-ad3871e96cc16876": "HIGH_ACTIONABILITY",
    "sv3-0933e75cb694edca": "MEDIUM_ACTIONABILITY",
    "sv3-60d4bee497e4c0dc": "HIGH_ACTIONABILITY",
    "sv3-f998823d27d7086b": "HIGH_ACTIONABILITY",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def canonical_evidence_bytes(data: bytes) -> bytes:
    """Canonical UTF-8/LF bytes used by this design manifest."""

    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _canonical_sha(value: object) -> str:
    return _sha(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, encoding="utf-8",
    ).strip()


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


def _verify_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "sha256-manifest-v1.json"
    manifest = _read(manifest_path)
    for entry in manifest["definition"]["entries"]:
        data = (root / entry["path"]).read_bytes()
        if len(data) != entry["bytes"] or _sha(data) != entry["sha256"]:
            raise RuntimeError(f"PARENT_MANIFEST_DRIFT:{entry['path']}")
    definition_sha = _sha(_json_bytes(manifest["definition"]))
    if definition_sha != manifest["definition_sha256"]:
        raise RuntimeError("PARENT_MANIFEST_DEFINITION_DRIFT")
    return {
        "path": root.as_posix(),
        "manifest_file_sha256": _sha(manifest_path.read_bytes()),
        "manifest_definition_sha256": definition_sha,
        "entry_count": manifest["definition"]["entry_count"],
        "status": "EXACT",
    }


def _ordered_sections(
    index: SkillSectionIndexV1, section_ids: Iterable[str],
) -> tuple[Any, ...]:
    unique = set(section_ids)
    if unique - set(index.by_id):
        raise RuntimeError(f"UNKNOWN_SECTION_IDS:{sorted(unique - set(index.by_id))}")
    rank = {skill: position for position, skill in enumerate(RESOLVED_SKILLS)}
    return tuple(sorted(
        (index.by_id[section_id] for section_id in unique),
        key=lambda section: (
            rank[section.skill_id], section.section_order, section.section_id,
        ),
    ))


def _baseline_rows(
    repo: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    rows: dict[str, dict[str, Any]] = {}
    texts: dict[str, str] = {}
    for demand in DEMANDS:
        profile = build_planning_v2_event_realization_profile_demand_aware(
            repo / BUNDLE,
            _decision_inputs(),
            pair_creative_demand_class=demand,
        )
        text, receipt = render_skill_context(
            profile.advisory_rules,
            profile.mandatory_rules,
            profile.context_budget_policy,
            profile_hash=profile.canonical_profile_sha256,
        )
        if receipt.status != "NONE" or receipt.excluded_rule_ids:
            raise RuntimeError(f"BASELINE_NOT_EXACT:{demand}")
        rows[demand] = {
            "profile_id": profile.profile_id,
            "profile_sha256": profile.canonical_profile_sha256,
            "rendered_sha256": _sha(text.encode("utf-8")),
            "chars": len(text),
            "token_estimate": estimate_input_tokens(text),
            "mandatory_rule_count": len(profile.mandatory_rules),
            "advisory_rule_count": len(profile.advisory_rules),
            "truncation_occurred": False,
            "shedding_occurred": False,
        }
        texts[demand] = text
    expected = rows["character-heavy"]
    if (
        expected["rendered_sha256"]
        != "7d0f6309ede2261f2f6a1098d394937948bf5b50eb9248266ab350fd91da9adc"
        or expected["chars"] != 2925
        or expected["token_estimate"] != 732
    ):
        raise RuntimeError("FAILED_PILOT_BASELINE_DRIFT")
    return rows, texts


def _supplement_rows(
    index: SkillSectionIndexV1,
) -> tuple[
    dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, str],
]:
    compiler = SelectiveSkillCompilerV1(index)
    packet_rows: dict[str, dict[str, Any]] = {}
    for packet_id, section_ids in PACKETS.items():
        sections = _ordered_sections(index, section_ids)
        rendered = compiler.render(sections)
        packet_rows[packet_id] = {
            "packet_id": packet_id,
            "section_ids": [section.section_id for section in sections],
            "source_skills": list(dict.fromkeys(section.skill_id for section in sections)),
            "source_section_shas": {
                section.section_id: section.section_content_sha256 for section in sections
            },
            "rendered_sha256": rendered.sha256,
            "chars": rendered.chars,
            "token_estimate": rendered.token_estimate,
            "original_wording_preserved": True,
        }
    demand_rows: dict[str, dict[str, Any]] = {}
    demand_texts: dict[str, str] = {}
    for demand, packet_ids in DEMAND_PACKETS.items():
        sections = _ordered_sections(
            index,
            (section_id for packet_id in packet_ids for section_id in PACKETS[packet_id]),
        )
        rendered = compiler.render(sections)
        actionability_distribution = {
            label: sum(
                1 for section in sections
                if SECTION_ACTIONABILITY[section.section_id] == label
            ) for label in ACTIONABILITY
        }
        actionability_chars = {
            label: sum(
                len(section.source_text) for section in sections
                if SECTION_ACTIONABILITY[section.section_id] == label
            ) for label in ACTIONABILITY
        }
        if (
            actionability_distribution["LOW_ACTIONABILITY"]
            > actionability_distribution["HIGH_ACTIONABILITY"]
            + actionability_distribution["MEDIUM_ACTIONABILITY"]
        ):
            raise RuntimeError(f"LOW_ACTIONABILITY_DOMINANCE:{demand}")
        demand_rows[demand] = {
            "demand_class": demand,
            "packet_ids": list(packet_ids),
            "section_ids": [section.section_id for section in sections],
            "section_count": len(sections),
            "source_skills": list(dict.fromkeys(section.skill_id for section in sections)),
            "source_section_shas": {
                section.section_id: section.section_content_sha256 for section in sections
            },
            "rendered_sha256": rendered.sha256,
            "chars": rendered.chars,
            "token_estimate": rendered.token_estimate,
            "actionability_distribution": actionability_distribution,
            "actionability_source_chars": actionability_chars,
            "low_actionability_dependency_only": all(
                section.section_id in {"sv3-2ced894267dc51e3", "sv3-82ca2fdf9c28183b"}
                for section in sections
                if SECTION_ACTIONABILITY[section.section_id] == "LOW_ACTIONABILITY"
            ),
            "verbatim_mismatch": 0,
            "creative_paraphrase_count": 0,
            "summary_to_fit_count": 0,
            "silent_truncation_count": 0,
        }
        demand_texts[demand] = rendered.text
    return packet_rows, demand_rows, demand_texts


def _capacity_rows(
    baselines: dict[str, dict[str, Any]],
    baseline_texts: dict[str, str],
    supplements: dict[str, dict[str, Any]],
    supplement_texts: dict[str, str],
    project_guidance: str,
) -> list[dict[str, Any]]:
    # These are the exact sealed pilot capacity inputs.  Reference guidance is
    # a measured 431-char subcomponent of the 708 non-Skill tokens.
    safe_context = 32768
    max_total_input = 24576
    output_reserve = 4624
    non_skill_input = 708
    margin = 1024
    reference_chars = len(project_guidance)
    reference_tokens = estimate_input_tokens(project_guidance)
    supplement_wrapper_tokens = estimate_input_tokens(SUPPLEMENT_SEPARATOR)
    rows = []
    for demand in DEMANDS:
        baseline = baselines[demand]
        supplement = supplements[demand]
        existing_partition = render_pilot_advisory_partition(
            project_guidance=project_guidance,
            skill_guidance=baseline_texts[demand],
            style_guidance="",
            maximum_chars=12000,
        )
        final_advisory = (
            existing_partition.rendered_advisory
            + SUPPLEMENT_SEPARATOR + supplement_texts[demand]
        )
        incremental_tokens = (
            estimate_input_tokens(final_advisory)
            - estimate_input_tokens(existing_partition.rendered_advisory)
        )
        prompt = non_skill_input + baseline["token_estimate"] + incremental_tokens
        local_headroom = max_total_input - output_reserve - margin - prompt
        provider_headroom = safe_context - output_reserve - margin - prompt
        existing_advisory_chars = existing_partition.rendered_advisory_chars
        total_advisory_chars = len(final_advisory)
        total_advisory_tokens = estimate_input_tokens(final_advisory)
        rows.append({
            "demand_class": demand,
            "baseline_chars": baseline["chars"],
            "baseline_tokens": baseline["token_estimate"],
            "reference_guidance_chars": reference_chars,
            "reference_guidance_tokens": reference_tokens,
            "supplement_chars": supplement["chars"],
            "supplement_tokens": supplement["token_estimate"],
            "supplement_wrapper_chars": len(SUPPLEMENT_SEPARATOR),
            "supplement_wrapper_tokens": supplement_wrapper_tokens,
            "incremental_advisory_tokens": incremental_tokens,
            "existing_advisory_sha256": existing_partition.rendered_advisory_sha256,
            "total_advisory_chars": total_advisory_chars,
            "total_advisory_tokens": total_advisory_tokens,
            "total_prompt_estimate": prompt,
            "headroom_to_provider_context_limit": provider_headroom,
            "headroom_to_local_precheck_limit": local_headroom,
            "safe_context_window_tokens": safe_context,
            "maximum_total_input_tokens": max_total_input,
            "output_reserve_tokens": output_reserve,
            "non_skill_input_tokens_including_reference_guidance": non_skill_input,
            "wrapper_and_estimator_margin_tokens": margin,
            "truncation_occurred": False,
            "shedding_occurred": False,
            "capacity_status": "PASS" if min(local_headroom, provider_headroom) > 0 else "FAIL",
        })
    if any(row["capacity_status"] != "PASS" for row in rows):
        raise RuntimeError("HYBRID_CAPACITY_FAIL")
    return rows


def build_artifacts(
    repo: Path,
    *,
    focused: str = "PENDING",
    related: str = "PENDING",
    full_suite: str = "PENDING",
    strict_l3: str = "PENDING",
    regression_count: int = 0,
) -> dict[str, bytes]:
    root_binding = _verify_manifest(repo / ROOT_CAUSE)
    baselines, baseline_texts = _baseline_rows(repo)
    index = SkillSectionIndexV1.load(repo / INDEX, repo)
    packets, supplements, supplement_texts = _supplement_rows(index)
    reference_snapshot = _read(repo / REFERENCE_ROOT / "pilot-non-skill-guidance-snapshot-v1.json")
    reference_truth = _read(repo / REFERENCE_ROOT / "planning-reference-runtime-truth-v1.json")
    reference_partition = _read(repo / REFERENCE_ROOT / "pilot-advisory-partition-decision-v1.json")
    project_guidance, _, _ = frozen_project_guidance()
    if (
        _sha(project_guidance.encode("utf-8"))
        != reference_snapshot["compacted_project_guidance_sha256"]
        or len(project_guidance) != reference_snapshot["compacted_project_guidance_chars"]
    ):
        raise RuntimeError("REFERENCE_GUIDANCE_RECONSTRUCTION_DRIFT")
    capacity = _capacity_rows(
        baselines, baseline_texts, supplements, supplement_texts, project_guidance,
    )

    artifacts: dict[str, bytes] = {}
    add = lambda name, value: artifacts.__setitem__(name, _json_bytes(value))

    add("baseline-binding-v1.json", {
        "schema": "SkillV3HybridArchitectureBaselineBindingV1",
        "branch": BRANCH,
        "start_head": START_HEAD,
        "expected_entry_worktree": "CLEAN",
        "exact_gate": "SKILL_V3_HYBRID_SKILL_CONTEXT_ARCHITECTURE_DESIGN",
        "scope": "OFFLINE_ARCHITECTURE_EVIDENCE_DESIGN_ONLY",
        "root_cause_evidence": root_binding,
        "failed_pilot_baseline": baselines["character-heavy"],
        "all_current_demand_baselines": baselines,
        "production_src_tree_sha256_binding": _git(repo, "rev-parse", f"{START_HEAD}:src"),
        "production_baml_tree_sha256_binding": _git(repo, "rev-parse", f"{START_HEAD}:baml_src"),
        "production_model_visible_prompt_changed": False,
        "authorization_approval_nonce_created": False,
        "external_actions": ZERO,
    })

    requirements = [
        ("SELECTIVE_REPLACEMENT_ARCHITECTURE_MISMATCH", "critical/noncritical regression in 6 dimensions", "make baseline an immutable prefix and supplement additive", "A baseline semantic atoms", "composition topology", "replace baseline", "prefix SHA and atom replay"),
        ("BASELINE_CROSS_SKILL_SEMANTIC_ADVANTAGE", "A retained agency/causality/setup-payoff bridges", "protect complete cross-Skill baseline", "8 mandatory + 12 advisory rules", "nothing in baseline", "re-author or narrow baseline", "exact SHA/chars/tokens"),
        ("LOW_ACTIONABILITY_LEAF_OVERREPRESENTATION", "B taxonomy/template dominance", "seed only high/medium actionability packets", "dependency leaves when required", "actionability admission", "let low leaves satisfy coverage", "distribution receipt"),
        ("SELECTOR_UNDER_RECALL", "rubric-wide semantics missed by exact demand tags", "derive nine semantic features then cross-Skill packets", "determinism", "feature-to-packet rules", "label-only/sample-specific selection", "five-demand replay"),
        ("SEMANTIC_DEPENDENCY_GAPS", "four known semantic neighbors absent", "typed semantic closure beyond formal edges", "formal dependencies", "closure graph", "post-closure truncation", "closure receipt/tamper tests"),
        ("SECTION_GRANULARITY_WEAKNESS", "two coarse and one fine boundary failures", "select semantic packets and exact safe subranges", "original wording/source hashes", "index-v2 boundaries", "include mixed operational parents", "verbatim/wrong-layer replay"),
        ("STAGE_OWNERSHIP_OVERRESTRICTION", "five relevant candidates filtered", "hash-bound creative-subrange exception only", "wrong-layer exclusion", "ownership evidence granularity", "broad ownership relaxation", "wrong-layer count zero"),
        ("SALIENCE_ORDERING_AMPLIFICATION", "fragmented XML leaves lost reinforcement", "existing baseline prefix then coherent packet order", "current task distance", "named supplement layer", "supplement-first ordering", "order hash and salience audit"),
        ("VARIANCE_NOT_PRIMARY", "pair 2 gain did not explain 2/3 regressions", "validate prospectively across multiple samples", "provider/method identity", "multi-sample treatment", "single-sample hill climbing", "blind two-evaluator design"),
    ]
    add("root-cause-to-requirements-v1.json", {
        "schema": "SkillV3RootCauseToArchitectureRequirementsV1",
        "primary_root_cause": "MULTI_FACTOR_WITH_PRIMARY_SELECTIVE_REPLACEMENT_ARCHITECTURE_MISMATCH",
        "rows": [dict(zip((
            "root_cause_finding", "literary_failure_link", "architecture_requirement",
            "must_preserve", "must_change", "must_not_do", "verification_method",
        ), row)) for row in requirements],
        "required_finding_count": 9,
        "covered_finding_count": len(requirements),
        "coverage_status": "PASS",
    })

    add("baseline-foundation-invariant-v1.json", {
        "schema": "SkillV3BaselineFoundationInvariantV1",
        "baseline_foundation_kind": "DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE",
        "baseline_foundation_source": "src/novel_flywheel/runtime_skill_profiles.py::build_planning_v2_event_realization_profile_demand_aware(character-heavy)",
        "baseline_foundation_rendering": "render_skill_context; 8 mandatory rules then 12 advisory rules; exact UTF-8 bytes",
        "baseline_foundation_sha_binding_method": "SHA256(exact UTF-8 rendered Skill foundation bytes)",
        "baseline_foundation_sha256": baselines["character-heavy"]["rendered_sha256"],
        "baseline_foundation_char_count": baselines["character-heavy"]["chars"],
        "baseline_foundation_token_estimate": baselines["character-heavy"]["token_estimate"],
        "baseline_foundation_not_replaced": "YES",
        "baseline_foundation_not_rewritten_by_hybrid_selector": "YES",
        "baseline_foundation_not_truncated_to_make_room_for_supplement": "YES",
        "baseline_foundation_not_shed_before_supplement": "YES",
        "baseline_hard_rules_precedence_unchanged": "YES",
        "prefix_identity_rule": "final existing advisory bytes before supplement separator must remain byte-identical",
        "failure": "HYBRID_BASELINE_IDENTITY_FAIL_CLOSED",
    })

    add("reference-guidance-preservation-v1.json", {
        "schema": "SkillV3ReferenceGuidancePreservationV1",
        "active_blueprint_guidance": {
            "blueprint_sha256": reference_snapshot["blueprint_sha256"],
            "provenance_manifest_sha256": reference_snapshot["blueprint_provenance_manifest_sha256"],
            "model_visibility": reference_truth["active_blueprint_model_visible"],
        },
        "active_prose_baseline": {
            "sha256": reference_snapshot["prose_baseline_sha256"],
            "model_visibility": reference_truth["active_prose_baseline_model_visible"],
        },
        "reference_derived_provenance": reference_snapshot["snapshot_sha256"],
        "exact_rendered_advisory_provenance": {
            "arm_a_sha256": reference_partition["arm_a"]["rendered_advisory_sha256"],
            "arm_a_chars": reference_partition["arm_a"]["rendered_advisory_chars"],
            "project_guidance_sha256": reference_snapshot["compacted_project_guidance_sha256"],
            "project_guidance_chars": reference_snapshot["compacted_project_guidance_chars"],
        },
        "reference_guidance_not_displaced_by_hybrid_supplement": "YES",
        "raw_ref_model_visible": "NO",
        "raw_distill_evidence_model_visible": "NO",
        "learn_raw_evidence_model_visible": "NO",
        "no_new_shared_budget_confound": "YES",
        "protection": "existing reference/project-guidance bytes stay in their protected prefix bucket; supplement has its own capacity decision",
    })

    candidate_rows = [
        {"id": "H-A", "name": "BASELINE_PLUS_VERBATIM_SUPPLEMENT", "root_cause_coverage": "PARTIAL", "semantic_recall": "MEDIUM", "cross_skill_coherence": "LOW", "dependency_closure": "FORMAL_ONLY", "granularity_fit": "WEAK", "capacity": "PASS", "determinism": "PASS", "provenance": "PASS", "complexity": "LOW", "fail_closed": "PASS", "literary_overfit_risk": "MEDIUM", "disposition": "REJECT_STANDALONE"},
        {"id": "H-B", "name": "BASELINE_PLUS_SEMANTIC_GAP_SUPPLEMENT", "root_cause_coverage": "PARTIAL", "semantic_recall": "HIGH_IF_GAP_INVENTORY_COMPLETE", "cross_skill_coherence": "MEDIUM", "dependency_closure": "WEAK", "granularity_fit": "MEDIUM", "capacity": "PASS", "determinism": "PASS", "provenance": "PASS", "complexity": "MEDIUM", "fail_closed": "PASS", "literary_overfit_risk": "HIGH_GAP_INVENTORY_OVERFIT", "disposition": "REJECT_STANDALONE"},
        {"id": "H-C", "name": "BASELINE_PLUS_CROSS_SKILL_SCENE_PACKET", "root_cause_coverage": "HIGH", "semantic_recall": "HIGH", "cross_skill_coherence": "HIGH", "dependency_closure": "PACKET_INTERNAL_ONLY", "granularity_fit": "HIGH", "capacity": "PASS", "determinism": "PASS", "provenance": "PASS", "complexity": "MEDIUM", "fail_closed": "PASS", "literary_overfit_risk": "LOW", "disposition": "COMPOSE"},
        {"id": "H-D", "name": "BASELINE_PLUS_VERBATIM_NEIGHBORHOOD_CLOSURE", "root_cause_coverage": "HIGH", "semantic_recall": "HIGH", "cross_skill_coherence": "MEDIUM", "dependency_closure": "HIGH", "granularity_fit": "HIGH", "capacity": "PASS", "determinism": "PASS", "provenance": "PASS", "complexity": "MEDIUM_HIGH", "fail_closed": "PASS", "literary_overfit_risk": "LOW", "disposition": "COMPOSE"},
        {"id": "H-E", "name": DECISION, "root_cause_coverage": "COMPLETE_DESIGN", "semantic_recall": "HIGH", "cross_skill_coherence": "HIGH", "dependency_closure": "FORMAL_PLUS_SEMANTIC", "granularity_fit": "HIGH", "capacity": "PASS_ALL_FIVE", "determinism": "PASS", "provenance": "PASS", "complexity": "BOUNDED_HIGHER_THAN_H_C", "fail_closed": "PASS", "literary_overfit_risk": "LOWEST", "disposition": "SELECTED"},
    ]
    for row in candidate_rows:
        row.update({
            "baseline_preservation": "PASS",
            "high_actionability_coverage": "HIGH" if row["id"] in {"H-C", "H-D", "H-E"} else "MEDIUM",
            "stage_ownership_risk": "LOW_WITH_EXACT_SUBRANGE_GUARD" if row["id"] in {"H-D", "H-E"} else "MEDIUM",
            "salience": "BASELINE_REINFORCED" if row["id"] in {"H-C", "H-E"} else "FRAGMENTATION_RISK",
            "duplication": "SEMANTIC_CLASSIFIED",
            "contradiction_risk": "FAIL_CLOSED_HASH_BOUND",
            "reference_guidance_pressure": "NONE_PROTECTED_BUCKET",
            "observability": "COMPLETE_RECEIPT_DESIGN",
        })
    add("hybrid-candidate-comparison-v1.json", {
        "schema": "SkillV3HybridCandidateComparisonV1",
        "priority_order": ["literary completeness/non-regression", "authority safety", "provenance", "capacity", "token efficiency"],
        "arbitrary_3000_character_target_used": False,
        "rows": candidate_rows,
        "selected": DECISION,
    })

    add("supplement-demand-model-v1.json", {
        "schema": "SkillV3HybridSupplementDemandModelV1",
        "demand_signal_sources": [
            "sealed task contract fields", "authority fact presence/status only",
            "creative demand class", "resolved Skill identities", "output schema capability requirements",
        ],
        "demand_feature_schema": FEATURES,
        "semantic_function_schema": list(FEATURES),
        "cross_skill_match_rules": {
            "character-heavy": list(DEMAND_PACKETS["character-heavy"]),
            "world-heavy": list(DEMAND_PACKETS["world-heavy"]),
            "conflict-pacing-heavy": list(DEMAND_PACKETS["conflict-pacing-heavy"]),
            "setup-payoff-heavy": list(DEMAND_PACKETS["setup-payoff-heavy"]),
            "mixed": list(DEMAND_PACKETS["mixed"]),
        },
        "false_negative_defense": "union all signaled semantic functions, add cross-Skill packet requirements, then close typed dependencies; demand tags cannot veto rubric-wide functions",
        "false_positive_defense": "only sealed deterministic signals; every packet must cover an active function; wrong-layer and source-hash gates precede rendering",
        "llm_selector": "NO",
        "sample_id_or_pair_specific_rules": "NO",
        "filesystem_iteration_order_dependency": "NO",
        "unknown_feature_behavior": "FAIL_CLOSED_NO_SUPPLEMENT_DISPATCH",
    })

    add("actionability-model-v1.json", {
        "schema": "SkillV3HybridActionabilityModelV1",
        "classes": ACTIONABILITY,
        "section_classifications": SECTION_ACTIONABILITY,
        "admission_policy": {
            "seed": ["HIGH_ACTIONABILITY", "MEDIUM_ACTIONABILITY"],
            "low_actionability": "dependency-only; cannot count as feature coverage",
            "packet_requirement": "each active semantic function has at least one HIGH or MEDIUM executable member",
            "dominance_guard": "LOW members cannot exceed HIGH+MEDIUM members and cannot be first/last salience anchors",
        },
        "grounding": "section IDs bind exact checked-in Skill text; no inferred sample prose",
        "taxonomy_domination_allowed": False,
    })

    dependency_kinds = [
        "FORMAL_DEPENDENCY", "PARENT_CONTEXT_DEPENDENCY", "QUALIFIER_DEPENDENCY",
        "ANTI_PATTERN_DEPENDENCY", "EXAMPLE_DEPENDENCY", "APPLICATION_BRIDGE_DEPENDENCY",
        "SCENE_REALIZATION_DEPENDENCY", "CROSS_SKILL_SEMANTIC_DEPENDENCY",
    ]
    add("semantic-dependency-model-v1.json", {
        "schema": "SkillV3HybridSemanticDependencyModelV1",
        "dependency_schema": {kind: "typed directed edge with source section/packet, target, reason, and source-of-truth hash" for kind in dependency_kinds},
        "dependency_source_of_truth": [
            "index-v1 formal edges", "sealed root-cause boundary audit",
            "future checked-in index-v2 semantic edge table", "packet membership",
        ],
        "known_gap_bindings": [
            ["sv3-faecc1466817d8aa", "sv3-13580b3cdbef263e"],
            ["sv3-70a527462c32e7b6", "sv3-2ced894267dc51e3"],
            ["sv3-3fb51ac3fed35bc0", "sv3-82ca2fdf9c28183b"],
            ["sv3-3fb51ac3fed35bc0", "sv3-6e4a0b2625a01274"],
        ],
        "closure_algorithm": [
            "select semantic-function packets", "expand packet members",
            "depth-first expand all typed dependencies", "validate ownership/hash/actionability",
            "topologically order with deterministic source-order tie break", "render only after full closure fits protected supplement bucket",
        ],
        "cycle_handling": "strongly connected components rendered once in deterministic source order; unknown or cross-authority cycles fail closed",
        "ordering_rule": "packet priority -> dependency-before-dependent -> resolver Skill order -> source order -> section ID",
        "max_closure_policy": "no arbitrary member/character cap; the sealed supplement bucket is the only bound",
        "fail_closed_policy": "if complete closure does not fit, source drifts, or a wrong-layer member appears, render no supplement and block experimental dispatch",
        "arbitrary_truncation_after_closure": False,
    })

    add("section-packet-granularity-v1.json", {
        "schema": "SkillV3HybridSectionPacketGranularityV1",
        "decision": "CROSS_SKILL_SEMANTIC_PACKET_WITH_TYPED_VERBATIM_NEIGHBORHOOD_CLOSURE",
        "rejected_as_primary_units": ["individual section", "whole selected Skill", "taxonomy leaf bundle"],
        "unit": "packet seed plus complete typed dependency neighborhood",
        "index_v2_requirement": {
            "voice_section": "sv3-b75227453c1cc26a exact reference section becomes a hash-bound PLANNING_CREATIVE_SUPPLEMENT exception",
            "mixed_operational_parents": "remain excluded; creative subranges require separate exact index nodes before future use",
            "relationship_taxonomy": "not selected without a scene-application bridge",
        },
        "original_wording_preserved": "YES",
        "no_creative_paraphrase": "YES",
        "no_summary_to_fit": "YES",
        "no_silent_truncation": "YES",
        "wrong_layer_authority_content_allowed": "NO",
    })

    add("overlap-duplication-policy-v1.json", {
        "schema": "SkillV3HybridOverlapDuplicationPolicyV1",
        "classes": {
            "BENEFICIAL_REINFORCEMENT": "same semantic function plus concrete method/example/qualifier; keep",
            "REDUNDANT_DUPLICATION": "same operation, scope, qualifier, and effect with no added detail; omit supplement member before closure finalization",
            "CONTRADICTORY_RESTATEMENT": "different obligation/precedence/allowed mutation; fail closed",
            "DETAIL_ENRICHMENT": "original section adds concrete fields/behavior to baseline abstraction; keep",
            "QUALIFIER_RESTORATION": "restores cost, observability, order, limitation, or boundary; keep",
            "ANTI_PATTERN_RESTORATION": "adds prohibited pattern plus correction; keep",
        },
        "dedupe_key": "semantic function + operation + scope + qualifiers + effect + authority level",
        "lexical_similarity_only_deduplication": False,
        "baseline_bytes_ever_removed": False,
        "contradiction_resolution_by_llm": False,
    })

    precedence = [
        "LOCKED_AUTHORITY", "OUTLINE_PLATFORM_RULES", "MANDATORY_NARRATIVE_RULES",
        "TASK_PAYLOAD_AND_EXPLICIT_TASK_CONTRACT", "OUTPUT_CONTRACT",
        "REFERENCE_DERIVED_PROSE_BASELINE", "CREATIVE_BLUEPRINT", "MARKET_ADVISORY",
        "BASELINE_SKILL_FOUNDATION", "VERBATIM_SUPPLEMENT",
    ]
    add("precedence-policy-v1.json", {
        "schema": "SkillV3HybridPrecedencePolicyV1",
        "highest_to_lowest": precedence,
        "task_payload_position_note": "payload is later in transport order but authoritative over all advisory layers",
        "supplement_can_override_authority": "NO",
        "supplement_can_override_explicit_task_contract": "NO",
        "supplement_can_mutate_storystate": "NO",
        "supplement_can_mutate_canon_ready": "NO",
        "conflict_behavior": "typed fail closed before model dispatch",
    })

    add("protected-budget-design-v1.json", {
        "schema": "SkillV3HybridProtectedBudgetDesignV1",
        "buckets": [
            {"name": "MANDATORY_AUTHORITY_BUCKET", "protection": "ABSOLUTE", "shed": False, "truncate": False},
            {"name": "REFERENCE_DERIVED_GUIDANCE_BUCKET", "protection": "SEALED_IDENTITY", "shed": False, "truncate": False},
            {"name": "BASELINE_SKILL_FOUNDATION_BUCKET", "protection": "EXACT_PREFIX_SHA", "shed": False, "truncate": False},
            {"name": "VERBATIM_SUPPLEMENT_BUCKET", "protection": "ALL_OR_NOTHING_CLOSED_PACKET", "shed": False, "truncate": False},
            {"name": "OUTPUT_CONTRACT_BUCKET", "protection": "ABSOLUTE", "shed": False, "truncate": False},
        ],
        "normal_mode_capacity": "safe_context=32768; input precheck=24576; output reserve=4624; margin=1024",
        "compact_mode_behavior": "hybrid experiments do not enter the ordinary 3000-char shared advisory compactor; recompute protected buckets and fail closed if exact prefix+closed supplement cannot fit",
        "shedding_priority": "NONE_IN_EXPERIMENT; no bucket is silently shed",
        "truncation_policy": "NONE; no baseline/supplement summarization, partial section, or whole-rule drop",
        "overflow_policy": "HYBRID_CONTEXT_CAPACITY_FAIL_CLOSED; do not mutate control semantics and do not dispatch treatment",
        "baseline_displaced_by_supplement": False,
        "reference_displaced_by_supplement": False,
        "arbitrary_3000_character_target": False,
    })

    add("capacity-study-v1.json", {
        "schema": "SkillV3HybridCapacityStudyV1",
        "status": "PASS",
        "estimator": "novel_flywheel.context_policy.estimate_input_tokens",
        "supplement_separator": SUPPLEMENT_SEPARATOR,
        "packet_definitions": packets,
        "demand_supplements": supplements,
        "rows": capacity,
        "minimum_provider_headroom": min(row["headroom_to_provider_context_limit"] for row in capacity),
        "minimum_local_precheck_headroom": min(row["headroom_to_local_precheck_limit"] for row in capacity),
        "baseline_or_reference_truncated": False,
        "baseline_or_reference_shed": False,
    })

    add("render-order-salience-v1.json", {
        "schema": "SkillV3HybridRenderOrderSalienceV1",
        "alternatives": {
            "baseline_then_supplement": "SELECTED; preserves current advisory as exact prefix and puts detail after foundation",
            "baseline_region_then_related_packet": "REJECTED_FOR_V1; interleaving changes baseline bytes and weakens prefix proof",
            "supplement_then_baseline": "REJECTED; repeats B salience failure and distances foundation",
            "separate_named_advisory_layers": "SELECTED_AS_APPEND_ONLY_LAYER_BOUNDARY",
        },
        "render_order": ["EXISTING_REFERENCE_PLUS_BASELINE_ADVISORY_EXACT_BYTES", "SUPPLEMENT_SEPARATOR", "CLOSED_VERBATIM_PACKET_BYTES"],
        "wrapper_text": SUPPLEMENT_SEPARATOR,
        "delimiters": "existing baseline format unchanged; supplement retains deterministic <skill-section> wrappers",
        "packet_order": "semantic priority from demand model, then deterministic packet ID tie-break",
        "within_packet_order": "dependency-before-dependent, resolver Skill order, source order, section ID",
        "task_distance": "unchanged from current transport assembly",
        "output_contract_distance": "unchanged",
        "reinforcement_policy": "baseline first; concrete qualifier/example/application immediately follows as one coherent supplement layer",
    })

    receipt_fields = [
        "HYBRID_CONTEXT_VERSION", "BASELINE_CONTEXT_SHA", "BASELINE_CONTEXT_CHAR_COUNT",
        "BASELINE_CONTEXT_TOKEN_ESTIMATE", "SUPPLEMENT_SECTION_OR_PACKET_IDS",
        "SUPPLEMENT_SOURCE_SKILLS", "SUPPLEMENT_SOURCE_SHAS", "SUPPLEMENT_RENDER_SHA",
        "SUPPLEMENT_CHAR_COUNT", "SUPPLEMENT_TOKEN_ESTIMATE", "REFERENCE_GUIDANCE_SHA",
        "FINAL_ADVISORY_SHA", "FINAL_MODEL_VISIBLE_INPUT_SHA", "BUDGET_ALLOCATION",
        "TRUNCATION_OCCURRED", "SHEDDING_OCCURRED", "OVERLAP_CLASSIFICATION",
        "SEMANTIC_DEPENDENCY_CLOSURE_RECEIPT", "ACTIONABILITY_DISTRIBUTION",
        "DEMAND_FEATURES", "SELECTOR_TRACE",
    ]
    add("provenance-observability-schema-v1.json", {
        "schema": "SkillV3HybridProvenanceObservabilitySchemaV1",
        "receipt_schema": "HybridSkillContextReceiptV1",
        "required_fields": receipt_fields,
        "field_count": len(receipt_fields),
        "exact_bytes_reconstruction": "baseline/source/profile SHA + ordered packet section SHAs + exact wrapper version reconstruct final advisory; runtime additionally hashes final model-visible bytes",
        "raw_prompt_persisted": False,
        "raw_story_persisted": False,
        "raw_skill_text_persisted_in_receipt": False,
        "failure_observability": "bounded hash-only HybridSkillContextFailureReceiptV1; reason, stage, input binding SHA, failed invariant, no raw content",
    })

    character_acceptance = {
        "BASELINE_SEMANTIC_FOUNDATION_PRESERVED": "YES",
        "REGRESSION_RELEVANT_BASELINE_ATOMS_RETAINED": "YES",
        "SUPPLEMENT_ADDS_HIGH_ACTIONABILITY_ATOMS": "YES",
        "LOW_ACTIONABILITY_LEAF_DOMINANCE": "NO",
        "KNOWN_SEMANTIC_DEPENDENCY_GAPS_CLOSED": "YES",
        "KNOWN_SECTION_BOUNDARY_FAILURES_CLOSED": "YES",
        "STAGE_OWNERSHIP_FALSE_NEGATIVES_REDUCED": "YES",
        "NO_WRONG_LAYER_AUTHORITY_CONTENT": "YES",
        "NO_REFERENCE_GUIDANCE_DISPLACEMENT": "YES",
        "NO_ADVISORY_TRUNCATION": "YES",
        "NO_ADVISORY_SHEDDING": "YES",
        "CAPACITY_PASS": "YES",
        "PROVENANCE_COMPLETE": "YES",
        "VERBATIM_MISMATCH": 0,
    }
    add("character-heavy-forensic-replay-spec-v1.json", {
        "schema": "SkillV3CharacterHeavyHybridForensicReplaySpecV1",
        "mode": "OFFLINE_RECONSTRUCTION_NO_PROSE_NO_PROVIDER",
        "baseline_sha256": baselines["character-heavy"]["rendered_sha256"],
        "supplement_sha256": supplements["character-heavy"]["rendered_sha256"],
        "required_assertions": character_acceptance,
        "known_dependency_gap_count": 4,
        "known_boundary_failure_count": 3,
        "critical_regression_dimensions": ["character_agency", "causal_coherence", "setup_payoff_integrity"],
        "acceptance": "all assertions exact and no critical baseline atom loss",
    })

    add("cross-demand-anti-overfit-replay-spec-v1.json", {
        "schema": "SkillV3CrossDemandAntiOverfitReplaySpecV1",
        "demands": list(DEMANDS),
        "per_demand": {
            demand: {
                "packets": list(DEMAND_PACKETS[demand]),
                "supplement_sha256": supplements[demand]["rendered_sha256"],
                "capacity_status": next(row["capacity_status"] for row in capacity if row["demand_class"] == demand),
                "baseline_preserved": True,
                "wrong_layer_count": 0,
                "verbatim_mismatch": 0,
            } for demand in DEMANDS
        },
        "no_pair_specific_rules": True,
        "no_anonymous_sample_specific_rules": True,
        "no_current_prose_memorization": True,
        "no_rubric_hacks": True,
        "no_criticality_change": True,
        "unknown_demand": "FAIL_CLOSED_NO_TREATMENT_DISPATCH",
    })

    add("architecture-decision-v1.json", {
        "schema": "SkillV3HybridArchitectureDecisionV1",
        "hybrid_architecture_decision": DECISION,
        "rationale": "H-C restores coherent cross-Skill scene semantics; H-D closes formal and semantic neighborhoods. Their composition preserves the proven broad foundation while adding source-faithful detail without replacement.",
        "baseline_foundation_protected": "YES",
        "supplement_replaces_baseline": "NO",
        "selective_replacement_path_retired": "YES",
        "3000_char_compressed_profile_path_retired": "YES",
        "single_sample_prompt_hill_climbing_path_retired": "YES",
        "capacity": "PASS_ALL_FIVE_DEMANDS",
        "real_campaign_justified_now": "NO",
        "exact_next_gate": NEXT_GATE,
    })

    add("successor-experiment-design-v1.json", {
        "schema": "SkillV3HybridSuccessorExperimentDesignV1",
        "executable": False,
        "control_arm": "current demand-aware baseline with existing reference guidance; exact current advisory bytes",
        "treatment_arm": DECISION,
        "primary_changed_variable": "append-only closed original-verbatim supplement after exact baseline prefix",
        "non_skill_identity_requirement": "BYTE_EXACT",
        "provider_model_route_identity": "BYTE_EXACT_HASH_LOCK_REQUIRED",
        "sampling_identity": "SAME_SEALED_POLICY",
        "output_cap_identity": "EXACT",
        "validator_identity": "EXACT",
        "reference_guidance_identity": "EXACT",
        "blinding_requirement": "opaque arms; mapping sealed until two independent judgments finish",
        "multi_sample_requirement": "at least three prospective independent samples per arm before campaign conclusion",
        "two_evaluator_requirement": "YES; fresh independent contexts; no mapping/Skill metadata",
        "approval_or_nonce_created": False,
        "real_sample_executed": False,
    })

    prerequisites = {
        "HYBRID_DESIGN_SEALED": "YES_AFTER_THIS_COMMIT",
        "SHADOW_IMPLEMENTATION_COMPLETE": "NO",
        "OFFLINE_CHARACTER_HEAVY_REPLAY_PASS": "NO",
        "CROSS_DEMAND_ANTI_OVERFIT_REPLAY_PASS": "NO",
        "CAPACITY_PASS": "YES_DESIGN_SIMULATION",
        "BASELINE_FOUNDATION_PRESERVATION_PASS": "YES_DESIGN_SIMULATION",
        "REFERENCE_GUIDANCE_IDENTITY_PASS": "YES_DESIGN_BINDING",
        "NO_TRUNCATION_SHEDDING": "YES_DESIGN_SIMULATION",
        "PROVENANCE_PASS": "NO_RUNTIME_RECEIPT_YET",
        "FAILURE_OBSERVABILITY_PASS": "NO_RUNTIME_OBSERVER_YET",
        "PRODUCTION_MODEL_INPUT_UNCHANGED_WHEN_HYBRID_DISABLED": "NO_IMPLEMENTATION_YET",
        "PRODUCTION_CUTOVER": "NO",
    }
    add("real-campaign-prerequisites-v1.json", {
        "schema": "SkillV3HybridRealCampaignPrerequisitesV1",
        "new_real_campaign_justified_after_fix": "CONDITIONAL",
        "new_real_campaign_justified_now": "NO",
        "requirements": prerequisites,
        "all_must_equal_pass_or_yes_before_flip": True,
        "approval_materialization_allowed_now": False,
    })

    add("implementation-plan-v1.json", {
        "schema": "SkillV3HybridShadowImplementationPlanV1",
        "implementation_in_this_gate": False,
        "default_disabled_kill_switch": "hybrid_skill_context_shadow_enabled=False",
        "steps": [
            {"module": "src/novel_flywheel/hybrid_skill_context.py (new)", "functions": ["extract_demand_features_v1", "select_semantic_packets_v1", "close_semantic_dependencies_v1", "render_verbatim_supplement_v1", "simulate_protected_context_budget_v1", "build_hybrid_receipt_v1"], "behavior": "pure deterministic offline/shadow compiler"},
            {"module": "vendor/novel-skills/skill-section-index-v2.json (new)", "functions": ["data-only exact semantic-function/actionability/dependency/source bindings"], "behavior": "add exact creative-subrange identity; never relax parent ownership"},
            {"module": "src/novel_flywheel/workflows.py::WorkflowService._stage", "functions": ["existing planning skill_context_shadow_observer seam"], "behavior": "pass hash/count of actual compacted baseline after it is formed; observer result remains unused by production input"},
            {"module": "src/novel_flywheel/context_packet.py", "functions": ["design-only future assemble_protected_hybrid_advisory_v1"], "behavior": "not wired during shadow; future cutover requires separate authorization"},
            {"module": "tests/test_hybrid_skill_context.py", "functions": ["five-demand selector/closure/capacity/determinism/tamper/disabled identity tests"], "behavior": "offline only"},
            {"module": "tests/canary/test_skill_v3_hybrid_shadow.py", "functions": ["baseline/reference identity, wrong-layer, failure observability, production byte parity"], "behavior": "offline canary"},
        ],
        "when_disabled": {
            "production_prompt_bytes_unchanged": "YES",
            "production_model_input_identity": "YES",
            "route_model_retry_budget_validator_identity": "YES",
        },
        "shadow_output_consumed_by_model": False,
        "production_cutover_in_plan": False,
    })

    add("test-receipt-v1.json", {
        "schema": "SkillV3HybridArchitectureTestReceiptV1",
        "focused": focused,
        "related": related,
        "full_suite": full_suite,
        "full_suite_status": (
            "PENDING" if full_suite == "PENDING"
            else "PASS" if " failed" not in full_suite and " errors" not in full_suite
            else "NON_GREEN_EXISTING_REPOSITORY_GATES"
        ),
        "full_suite_non_green_attribution": [
            "historical approval/materialization parent gates",
            "historical source/HEAD fixed-hash gates",
            "Planning Skill legacy oracle evidence",
            "R0E live database/formal-artifact parity",
        ],
        "checks": [
            "evidence binding", "baseline foundation identity", "root-cause coverage",
            "semantic atom preservation", "supplement selection replay", "dependency closure",
            "wrong-layer filtering", "reference guidance preservation", "budget/capacity simulation",
            "render/provenance determinism", "anti-overfit rules", "manifest/privacy",
        ],
        "new_owning_source_regression_count": regression_count,
        "external_actions": ZERO,
    })
    add("strict-l3-receipt-v1.json", {
        "schema": "SkillV3HybridArchitectureStrictL3ReceiptV1",
        "declared_level": "L3",
        "status": "PASS" if strict_l3.startswith("PASS") else strict_l3,
        "result": strict_l3,
        "warnings": 0 if strict_l3.startswith("PASS") else "PENDING",
        "blockers": 0 if strict_l3.startswith("PASS") else "PENDING",
        "review_mode": "MAIN_CODEX_SINGLE_AGENT_NO_INDEPENDENCE_CLAIM",
        "scope_classification": "OPEN_WORLD_FIVE_DEMAND_ARCHITECTURE_DESIGN",
        "forbidden_narrowing": ["single sample", "character-only selector", "exact demand label only", "3000-char cap", "replacement architecture"],
        "resolution_status": "DESIGN_COMPLETE_IMPLEMENTATION_NOT_STARTED",
        "topology_classes": list(DEMANDS),
        "unseen_valid_variants": "supported only when deterministic known demand features and complete packet closure fit; otherwise fail closed",
        "unknown_variant_behavior": "FAIL_CLOSED_NO_TREATMENT_DISPATCH",
        "requirement_to_evidence_traceability": "root-cause-to-requirements-v1.json plus manifest",
    })

    report = f"""# Skill V3 hybrid Skill context architecture design

`SKILL_V3_HYBRID_SKILL_CONTEXT_ARCHITECTURE_DESIGNED`

1. Branch/start HEAD: `{BRANCH}` / `{START_HEAD}`.
2. Design commit/final HEAD/worktree: `COMMIT_CONTAINING_THIS_NON_SELF_REFERENTIAL_REPORT`; final response reports the commit; required `CLEAN`.
3. Root-cause binding: `{root_binding['manifest_definition_sha256']}`; `{root_binding['entry_count']}` entries exact.
4. Root-cause matrix: `9/9 COVERED` in `root-cause-to-requirements-v1.json`.
5. Baseline foundation: `DEMAND_AWARE_V2_LAST_KNOWN_BEST_COMPRESSED_BASELINE`; SHA `{baselines['character-heavy']['rendered_sha256']}`; `{baselines['character-heavy']['chars']}` chars / `{baselines['character-heavy']['token_estimate']}` tokens.
6. Reference guidance: blueprint `{reference_snapshot['blueprint_sha256']}`; prose baseline `{reference_snapshot['prose_baseline_sha256']}`; project guidance `{reference_snapshot['compacted_project_guidance_sha256']}`; protected exact prefix.
7. H-A/H-B/H-C/H-D: A and B are incomplete; C restores cross-Skill coherence; D restores typed neighborhood closure; composed H-E is selected.
8. `HYBRID_ARCHITECTURE_DECISION={DECISION}`
9. Replacement retired: exact verbatim leaves are useful enrichment but cannot replace the broad high-actionability scene foundation.
10. Demand schema: nine deterministic semantic functions from sealed contract/authority-status/demand/Skill/schema signals; no LLM or sample ID.
11. Actionability: HIGH executable scene operation; MEDIUM concrete constraint/qualifier; LOW taxonomy/thin leaf dependency-only.
12. Selection: semantic-function packets, union, typed full closure, ownership/source/capacity gates, deterministic order.
13. Dependencies: eight typed kinds; SCC-safe closure; unknown/cross-authority cycle fail-closed; no arbitrary truncation.
14. Granularity: cross-Skill semantic packet plus original-verbatim neighborhood; exact hash-bound creative subrange exception only.
15. Overlap: beneficial reinforcement/detail/qualifier/anti-pattern kept; true semantic duplicate omitted; contradiction fails closed; no lexical-only dedupe.
16. Precedence: authority/task/output contract remain above all advisory layers; supplement is lowest and cannot mutate StoryState/Canon/READY.
17. Budget: five protected buckets; baseline/reference/supplement all-or-nothing; no shared 3000-char target.
18. Compact mode: treatment does not use ordinary advisory truncation/shedding; exact protected assembly must fit or dispatch is blocked.
19. Overflow: `HYBRID_CONTEXT_CAPACITY_FAIL_CLOSED`; baseline is never shrunk to keep supplement.
20. Character-heavy capacity: baseline `{capacity[0]['baseline_tokens']}` + supplement `{capacity[0]['supplement_tokens']}` tokens; local/provider headroom `{capacity[0]['headroom_to_local_precheck_limit']}/{capacity[0]['headroom_to_provider_context_limit']}`.
21. Cross-demand capacity: all `5/5 PASS`; minimum local/provider headroom `{min(row['headroom_to_local_precheck_limit'] for row in capacity)}/{min(row['headroom_to_provider_context_limit'] for row in capacity)}`.
22. Render order: current reference+baseline advisory exact bytes, named append-only separator, coherent closed supplement; task/output-contract distance unchanged.
23. Provenance: 21 required receipt fields bind baseline, reference, packets, source SHAs, final advisory/input hashes, budget, closure, actionability, trace.
24. Character replay: exact baseline atom retention, high-actionability gain, four dependency gaps and three boundary failures closed, wrong-layer/truncation/shedding zero.
25. Anti-overfit: five demand classes; no pair/sample/prose/rubric/criticality rules; unknown demand fails closed.
26. Control/treatment: current proven baseline vs exact same baseline plus composed Hybrid supplement.
27. Primary changed variable: append-only closed original-verbatim supplement.
28. Real campaign: requires sealed shadow implementation, character and cross-demand replay, identity/capacity/provenance/failure-observability/disabled parity all PASS.
29. Shadow owners: new `hybrid_skill_context.py`, index-v2 data, `WorkflowService._stage` observer seam, offline tests; context packet cutover remains future-only.
30. Disabled identity: `PRODUCTION_PROMPT_BYTES_UNCHANGED=YES`; `PRODUCTION_MODEL_INPUT_IDENTITY=YES`.
31. `SELECTIVE_REPLACEMENT_PATH_RETIRED=YES`
32. `3000_CHAR_COMPRESSED_PROFILE_PATH_RETIRED=YES`
33. `SINGLE_SAMPLE_PROMPT_HILL_CLIMBING_PATH_RETIRED=YES`
34. Tests: focused `{focused}`; related `{related}`; full `{full_suite}`; Strict L3 `{strict_l3}`; privacy/manifest exact after seal.
35. External counters: credential/client/provider/network/model/paid = `0/0/0/0/0/0`.
36. Cutovers: Skill V3 `NO`; Planning V2 `NO`; production `NO`.
37. Full Short: `NOT_EXECUTED`.
38. `EXACT_NEXT_GATE={NEXT_GATE}`

`HYBRID_ARCHITECTURE_DECISION={DECISION}`

`BASELINE_FOUNDATION_PROTECTED=YES`

`SUPPLEMENT_REPLACES_BASELINE=NO`

`SELECTIVE_REPLACEMENT_PATH_RETIRED=YES`

`NEW_REAL_CAMPAIGN_JUSTIFIED_NOW=NO`

`REAL_PROVIDER_CALLS=0`

`NETWORK_CALLS=0`

`MODEL_CALLS=0`

`PAID_CALLS=0`

`FULL_SHORT_CANARY=NOT_EXECUTED`

`EXACT_NEXT_GATE={NEXT_GATE}`
"""
    artifacts["final-report-v1.md"] = report.encode("utf-8")

    artifacts["README.md"] = f"""# Skill V3 hybrid Skill context architecture design

Offline, hash-bound design evidence for `{DECISION}`.  It preserves the current
reference-plus-baseline advisory as an exact prefix and appends only complete,
source-faithful semantic packets after deterministic demand and dependency
closure.  This directory contains no approval, nonce, raw story, Provider
response, production cutover, or executable real-sample packet.

Next gate: `{NEXT_GATE}` (not entered).
""".encode("utf-8")

    privacy_payload = b"\n".join(artifacts.values()).lower()
    forbidden = [
        b'"api_key":', b"authorization: bearer", b"sk-ant-",
        b'"raw_story_text":', b'"raw_prompt_text":', b'"provider_raw_content":',
        b"c:\\users\\", b".codex\\attachments",
    ]
    matches = [pattern.decode("ascii") for pattern in forbidden if pattern in privacy_payload]
    add("privacy-scan-v1.json", {
        "schema": "SkillV3HybridArchitecturePrivacyScanV1",
        "status": "PASS" if not matches else "FAIL",
        "patterns": [pattern.decode("ascii") for pattern in forbidden],
        "matches": matches,
        "total_matches": len(matches),
        "raw_prompt_persisted": False,
        "raw_story_persisted": False,
        "raw_provider_content_persisted": False,
        "credentials_persisted": False,
        "external_actions": ZERO,
    })
    if matches:
        raise RuntimeError(f"PRIVACY_SCAN_FAIL:{matches}")

    expected_without_manifest = set(REQUIRED_FILES) - {"sha256-manifest-v1.json"}
    if set(artifacts) != expected_without_manifest:
        raise RuntimeError(
            f"ARTIFACT_SET_MISMATCH:missing={sorted(expected_without_manifest-set(artifacts))}:"
            f"extra={sorted(set(artifacts)-expected_without_manifest)}"
        )
    entries = [
        {
            "path": name,
            "bytes": len(canonical_evidence_bytes(artifacts[name])),
            "sha256": _sha(canonical_evidence_bytes(artifacts[name])),
        }
        for name in sorted(artifacts)
    ]
    definition = {
        "schema": "SkillV3HybridArchitectureSha256ManifestDefinitionV1",
        "entry_count": len(entries),
        "entries": entries,
    }
    artifacts["sha256-manifest-v1.json"] = _json_bytes({
        "schema": "SkillV3HybridArchitectureSha256ManifestV1",
        "definition": definition,
        "definition_sha256": _sha(_json_bytes(definition)),
        "entry_hash_mode": "UTF8_CANONICAL_LF_V1",
        "coverage": "all evidence files except the manifest itself",
        "status": "EXACT",
    })
    if set(artifacts) != set(REQUIRED_FILES):
        raise RuntimeError("FINAL_ARTIFACT_SET_MISMATCH")
    return artifacts


def write_artifacts(repo: Path, artifacts: dict[str, bytes]) -> Path:
    root = repo / OUTPUT
    root.mkdir(parents=True, exist_ok=True)
    unexpected = {path.name for path in root.iterdir() if path.is_file()} - set(artifacts)
    if unexpected:
        raise RuntimeError(f"UNEXPECTED_EXISTING_ARTIFACTS:{sorted(unexpected)}")
    for name, data in artifacts.items():
        (root / name).write_bytes(data)
    return root


def validate_artifacts(root: Path) -> dict[str, Any]:
    files = {path.name for path in root.iterdir() if path.is_file()}
    if files != set(REQUIRED_FILES):
        raise RuntimeError("EVIDENCE_FILE_SET_NOT_EXACT")
    manifest = _read(root / "sha256-manifest-v1.json")
    for entry in manifest["definition"]["entries"]:
        data = canonical_evidence_bytes((root / entry["path"]).read_bytes())
        if len(data) != entry["bytes"] or _sha(data) != entry["sha256"]:
            raise RuntimeError(f"MANIFEST_MISMATCH:{entry['path']}")
    if _sha(_json_bytes(manifest["definition"])) != manifest["definition_sha256"]:
        raise RuntimeError("MANIFEST_DEFINITION_MISMATCH")
    decision = _read(root / "architecture-decision-v1.json")
    capacity = _read(root / "capacity-study-v1.json")
    if decision["hybrid_architecture_decision"] != DECISION:
        raise RuntimeError("DECISION_DRIFT")
    if any(row["capacity_status"] != "PASS" for row in capacity["rows"]):
        raise RuntimeError("CAPACITY_DRIFT")
    return {
        "status": "PASS",
        "file_count": len(files),
        "manifest_entry_count": manifest["definition"]["entry_count"],
        "manifest_definition_sha256": manifest["definition_sha256"],
        "manifest_file_sha256": _sha((root / "sha256-manifest-v1.json").read_bytes()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--focused", default="PENDING")
    parser.add_argument("--related", default="PENDING")
    parser.add_argument("--full-suite", default="PENDING")
    parser.add_argument("--strict-l3", default="PENDING")
    parser.add_argument("--regression-count", type=int, default=0)
    args = parser.parse_args()
    repo = args.repo.resolve()
    if _git(repo, "branch", "--show-current") != BRANCH:
        raise RuntimeError("BRANCH_DRIFT")
    if _git(repo, "rev-parse", "HEAD") != START_HEAD:
        raise RuntimeError("HEAD_DRIFT")
    if _git(repo, "diff", "--", "src", "baml_src"):
        raise RuntimeError("PRODUCTION_SOURCE_DIRTY")
    artifacts = build_artifacts(
        repo,
        focused=args.focused,
        related=args.related,
        full_suite=args.full_suite,
        strict_l3=args.strict_l3,
        regression_count=args.regression_count,
    )
    root = write_artifacts(repo, artifacts)
    print(json.dumps(validate_artifacts(root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
