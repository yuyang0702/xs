"""Build the checked-in data-only Hybrid Skill section index V2."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from novel_flywheel.hybrid_skill_context import (
    HYBRID_ARCHITECTURE_DECISION,
    HYBRID_INDEX_SCHEMA,
    HYBRID_INDEX_VERSION,
)


INDEX_V1 = Path("vendor/novel-skills/skill-section-index-v1.json")
INDEX_V2 = Path("vendor/novel-skills/skill-section-index-v2.json")
DESIGN_MANIFEST = Path(
    "docs/superpowers/reports/"
    "skill-v3-hybrid-skill-context-architecture-design-v1/"
    "sha256-manifest-v1.json"
)
ROOT_CAUSE_MANIFEST = Path(
    "docs/superpowers/reports/"
    "skill-v3-selective-compiler-multi-sample-quality-root-cause-v1/"
    "sha256-manifest-v1.json"
)


PACKETS = {
    "CHARACTER_CHOICE_VOICE_PACKET_V1": {
        "root_section_ids": [
            "sv3-10e4ba0c5b7509b4",
            "sv3-b75227453c1cc26a",
            "sv3-8e321726b4ebdcec",
        ],
        "semantic_functions": [
            "character_agency_motivation",
            "relationship_consequence",
            "subtext_dramatization",
            "voice_readiness",
            "anti_template_realization",
        ],
        "priority": 10,
    },
    "CAUSAL_PRESSURE_PACKET_V1": {
        "root_section_ids": [
            "sv3-13580b3cdbef263e",
            "sv3-5f738df332e0919f",
            "sv3-60d4bee497e4c0dc",
        ],
        "semantic_functions": ["causal_coherence", "scene_pressure"],
        "priority": 20,
    },
    "SETUP_PAYOFF_CLOSURE_PACKET_V1": {
        "root_section_ids": [
            "sv3-ac7aa3aed8a7d237",
            "sv3-972a75cb8ca8f0bd",
            "sv3-6e4a0b2625a01274",
            "sv3-ad3871e96cc16876",
        ],
        "semantic_functions": ["setup_payoff"],
        "priority": 30,
    },
    "WORLD_AFFORDANCE_PRESSURE_PACKET_V1": {
        "root_section_ids": [
            "sv3-2985467b5f2bf929",
            "sv3-60d4bee497e4c0dc",
            "sv3-5f738df332e0919f",
            "sv3-f998823d27d7086b",
            "sv3-b4583d410167ab14",
            "sv3-ad3871e96cc16876",
            "sv3-0933e75cb694edca",
        ],
        "semantic_functions": ["specificity"],
        "priority": 15,
    },
}

DEMAND_CLASS_FEATURES = {
    "character-heavy": [
        "character_agency_motivation", "relationship_consequence",
        "causal_coherence", "subtext_dramatization", "scene_pressure",
        "setup_payoff", "voice_readiness", "anti_template_realization",
    ],
    "world-heavy": ["specificity", "causal_coherence", "setup_payoff"],
    "conflict-pacing-heavy": [
        "causal_coherence", "scene_pressure", "character_agency_motivation",
        "setup_payoff",
    ],
    "setup-payoff-heavy": ["setup_payoff", "causal_coherence"],
    "mixed": [
        "character_agency_motivation", "relationship_consequence",
        "causal_coherence", "subtext_dramatization", "scene_pressure",
        "specificity", "setup_payoff", "voice_readiness",
        "anti_template_realization",
    ],
}

DEMAND_PACKET_ORDER = {
    "character-heavy": [
        "CHARACTER_CHOICE_VOICE_PACKET_V1", "CAUSAL_PRESSURE_PACKET_V1",
        "SETUP_PAYOFF_CLOSURE_PACKET_V1",
    ],
    "world-heavy": [
        "WORLD_AFFORDANCE_PRESSURE_PACKET_V1", "CAUSAL_PRESSURE_PACKET_V1",
        "SETUP_PAYOFF_CLOSURE_PACKET_V1",
    ],
    "conflict-pacing-heavy": [
        "CAUSAL_PRESSURE_PACKET_V1", "CHARACTER_CHOICE_VOICE_PACKET_V1",
        "SETUP_PAYOFF_CLOSURE_PACKET_V1",
    ],
    "setup-payoff-heavy": [
        "SETUP_PAYOFF_CLOSURE_PACKET_V1", "CAUSAL_PRESSURE_PACKET_V1",
    ],
    "mixed": [
        "CHARACTER_CHOICE_VOICE_PACKET_V1",
        "WORLD_AFFORDANCE_PRESSURE_PACKET_V1",
        "CAUSAL_PRESSURE_PACKET_V1",
        "SETUP_PAYOFF_CLOSURE_PACKET_V1",
    ],
}

ACTIONABILITY = {
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

SECTION_FUNCTIONS = {
    "sv3-4c39329c602fd48e": ["character_agency_motivation"],
    "sv3-10e4ba0c5b7509b4": ["character_agency_motivation"],
    "sv3-b75227453c1cc26a": ["voice_readiness", "subtext_dramatization"],
    "sv3-8e321726b4ebdcec": ["character_agency_motivation", "relationship_consequence"],
    "sv3-faecc1466817d8aa": ["causal_coherence", "scene_pressure"],
    "sv3-13580b3cdbef263e": ["causal_coherence", "scene_pressure"],
    "sv3-2985467b5f2bf929": ["specificity", "scene_pressure"],
    "sv3-5f738df332e0919f": ["causal_coherence", "scene_pressure", "specificity"],
    "sv3-60d4bee497e4c0dc": ["scene_pressure", "specificity"],
    "sv3-ac7aa3aed8a7d237": ["setup_payoff"],
    "sv3-2ced894267dc51e3": ["setup_payoff"],
    "sv3-972a75cb8ca8f0bd": ["setup_payoff", "causal_coherence"],
    "sv3-82ca2fdf9c28183b": ["setup_payoff"],
    "sv3-6e4a0b2625a01274": ["setup_payoff", "causal_coherence"],
    "sv3-ad3871e96cc16876": ["setup_payoff", "specificity"],
    "sv3-f998823d27d7086b": ["scene_pressure"],
    "sv3-b4583d410167ab14": ["specificity"],
    "sv3-0933e75cb694edca": ["specificity", "causal_coherence"],
}

OVERLAP = {
    "sv3-2ced894267dc51e3": "QUALIFIER_RESTORATION",
    "sv3-82ca2fdf9c28183b": "QUALIFIER_RESTORATION",
    "sv3-972a75cb8ca8f0bd": "DETAIL_ENRICHMENT",
    "sv3-faecc1466817d8aa": "BENEFICIAL_REINFORCEMENT",
    "sv3-6e4a0b2625a01274": "APPLICATION_BRIDGE_RESTORATION",
}

EDGES = [
    ("sv3-10e4ba0c5b7509b4", "sv3-4c39329c602fd48e", "PARENT_CONTEXT_DEPENDENCY", "Motivation requires the bound character traits context."),
    ("sv3-10e4ba0c5b7509b4", "sv3-b75227453c1cc26a", "APPLICATION_BRIDGE_DEPENDENCY", "Motivation becomes scene-usable through exact voice behavior."),
    ("sv3-b75227453c1cc26a", "sv3-8e321726b4ebdcec", "QUALIFIER_DEPENDENCY", "Voice choices must remain aligned with the character arc."),
    ("sv3-b75227453c1cc26a", "sv3-4c39329c602fd48e", "ANTI_PATTERN_DEPENDENCY", "Trait context prevents generic voice templating."),
    ("sv3-13580b3cdbef263e", "sv3-faecc1466817d8aa", "FORMAL_DEPENDENCY", "Plot points realize the rising-action progression."),
    ("sv3-13580b3cdbef263e", "sv3-2985467b5f2bf929", "SCENE_REALIZATION_DEPENDENCY", "Causal plot pressure needs a concrete location affordance."),
    ("sv3-13580b3cdbef263e", "sv3-5f738df332e0919f", "CROSS_SKILL_SEMANTIC_DEPENDENCY", "Causal escalation needs explicit world-system costs and limits."),
    ("sv3-5f738df332e0919f", "sv3-60d4bee497e4c0dc", "EXAMPLE_DEPENDENCY", "Rules become actionable through concrete notable features."),
    ("sv3-ac7aa3aed8a7d237", "sv3-2ced894267dc51e3", "PARENT_CONTEXT_DEPENDENCY", "Foreshadowing retains its setup identity."),
    ("sv3-ac7aa3aed8a7d237", "sv3-972a75cb8ca8f0bd", "APPLICATION_BRIDGE_DEPENDENCY", "Foreshadowing must yield observable evidence."),
    ("sv3-972a75cb8ca8f0bd", "sv3-82ca2fdf9c28183b", "EXAMPLE_DEPENDENCY", "Evidence is retained through its payoff target."),
    ("sv3-972a75cb8ca8f0bd", "sv3-6e4a0b2625a01274", "QUALIFIER_DEPENDENCY", "Evidence requires a bounded resolution plan."),
]


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_hash(value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_payload(repo: Path) -> dict[str, Any]:
    source = _read(repo / INDEX_V1)
    design = _read(repo / DESIGN_MANIFEST)
    root_cause = _read(repo / ROOT_CAUSE_MANIFEST)
    sections = {row["section_id"]: row for row in source["sections"]}
    if set(ACTIONABILITY) != set(SECTION_FUNCTIONS):
        raise RuntimeError("hybrid section policy coverage mismatch")
    missing = set(ACTIONABILITY) - set(sections)
    if missing:
        raise RuntimeError(f"unknown source section IDs: {sorted(missing)}")
    policies: dict[str, Any] = {}
    for section_id in sorted(ACTIONABILITY):
        actionability = ACTIONABILITY[section_id]
        policies[section_id] = {
            "actionability_class": actionability,
            "actionability_reason": {
                "HIGH_ACTIONABILITY": "exact section provides an executable scene, causal, reaction, voice, pressure, or setup/payoff operation",
                "MEDIUM_ACTIONABILITY": "exact section supplies a concrete field, qualifier, or sequence used by an executable neighbor",
                "LOW_ACTIONABILITY": "thin taxonomy/template leaf retained only as a required typed dependency",
            }[actionability],
            "target_semantic_functions": SECTION_FUNCTIONS[section_id],
            "overlap_classification": OVERLAP.get(
                section_id,
                "ANTI_PATTERN_RESTORATION"
                if section_id == "sv3-b75227453c1cc26a"
                else "DETAIL_ENRICHMENT",
            ),
            "stage_ownership_exception": (
                "PLANNING_CREATIVE_SUPPLEMENT_EXACT_SUBRANGE_V1"
                if section_id == "sv3-b75227453c1cc26a" else None
            ),
            "cycle_group_id": None,
        }
    # The sealed class is QUALIFIER_RESTORATION; keep the label within the
    # architecture's exact overlap vocabulary.
    policies["sv3-6e4a0b2625a01274"]["overlap_classification"] = (
        "QUALIFIER_RESTORATION"
    )
    edge_rows = [
        {
            "from_section_id": left,
            "to_section_id": right,
            "dependency_type": kind,
            "source_of_truth": (
                "skill-v3-hybrid-skill-context-architecture-design-v1/"
                "semantic-dependency-model-v1"
            ),
            "reason": reason,
            "cycle_allowed": False,
        }
        for left, right, kind, reason in EDGES
    ]
    payload: dict[str, Any] = {
        "schema": HYBRID_INDEX_SCHEMA,
        "version": HYBRID_INDEX_VERSION,
        "architecture_binding": {
            "decision": HYBRID_ARCHITECTURE_DECISION,
            "baseline_foundation_protected": "YES",
            "supplement_replaces_baseline": "NO",
            "selective_replacement_path_retired": "YES",
            "new_real_campaign_justified_now": "NO",
        },
        "source_index_v1_binding": {
            "path": INDEX_V1.as_posix(),
            "index_definition_sha256": source["index_definition_sha256"],
        },
        "evidence_binding": {
            "design_manifest_definition_sha256": design["definition_sha256"],
            "root_cause_manifest_definition_sha256": root_cause[
                "definition_sha256"
            ],
        },
        "signal_feature_map": {
            "actor_refs_present": ["character_agency_motivation"],
            "relationship_pressure_present": ["relationship_consequence", "subtext_dramatization"],
            "causal_chain_present": ["causal_coherence"],
            "dialogue_required": ["subtext_dramatization", "voice_readiness"],
            "opposition_present": ["scene_pressure"],
            "world_refs_present": ["specificity"],
            "setup_payoff_present": ["setup_payoff"],
            "anti_template_required": ["anti_template_realization"],
        },
        "demand_class_features": DEMAND_CLASS_FEATURES,
        "demand_packet_order": DEMAND_PACKET_ORDER,
        "actionability_classes": {
            "HIGH_ACTIONABILITY": "executable scene/causal/reaction/subtext/application guidance",
            "MEDIUM_ACTIONABILITY": "concrete qualifier or sequence supporting an executable root",
            "LOW_ACTIONABILITY": "dependency-only taxonomy/template context",
        },
        "section_policies": policies,
        "packet_definitions": PACKETS,
        "dependency_edges": edge_rows,
        "cycle_policy": (
            "only exact same-owner cycle_group_id SCCs with cycle_allowed edges; "
            "all other cycles fail closed"
        ),
        "ordering_policy": (
            "packet priority then dependency-before-dependent then resolver Skill "
            "order then source order then section ID"
        ),
        "unknown_feature_behavior": "FAIL_CLOSED_NO_SUPPLEMENT_DISPATCH",
        "wrong_layer_behavior": "FAIL_CLOSED_NO_SUPPLEMENT_DISPATCH",
        "raw_prompt_or_story_dependency": False,
        "sample_pair_or_evaluator_rule_count": 0,
    }
    payload["index_definition_sha256"] = _canonical_hash(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    payload = build_payload(repo)
    target = repo / INDEX_V2
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
            raise SystemExit("HYBRID_INDEX_V2_NOT_EXACT")
        print(json.dumps({"status": "EXACT", "sha256": payload["index_definition_sha256"]}))
        return
    target.write_text(rendered, encoding="utf-8", newline="\n")
    print(json.dumps({"status": "WRITTEN", "path": str(target), "sha256": payload["index_definition_sha256"]}))


if __name__ == "__main__":
    main()
