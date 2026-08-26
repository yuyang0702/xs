"""Build the explicit Skill V3 section index from sealed design evidence.

This is an offline maintainer tool.  It reads only checked-in repo Skills and
sealed design artifacts; it has no Runtime, Provider, network, or model path.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs/superpowers/reports/skill-v3-verbatim-selective-compiler-strategy-pivot-v1"
OUTPUT = ROOT / "vendor/novel-skills/skill-section-index-v1.json"
PLANNING_SKILLS = {
    "story-init", "plot-structure", "character-management", "worldbuilding",
}
PLANNING_ALLOWED = {
    "PLANNING_EVENT_REALIZATION", "SHARED_CREATIVE_CORE", "AUTHORITY_ONLY",
}


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "section"


def main() -> None:
    ownership = read_json(DESIGN / "skill-semantic-stage-ownership-matrix-v1.json")
    scenarios = read_json(DESIGN / "selective-compiler-context-size-scenario-matrix-v1.json")
    catalog = read_json(DESIGN / "repo-skill-section-catalog-v1.json")
    full = read_json(DESIGN / "full-verbatim-selected-skills-baseline-assessment-v1.json")

    scenario_ids = {
        item["demand_class"]: set(item["selected_section_ids"])
        for item in scenarios["scenarios"]
    }
    estimated_core_ids = set.intersection(*scenario_ids.values())
    rows = ownership["rows"]
    row_by_id = {row["section_id"]: row for row in rows}
    # The sealed size matrix was an estimate, not an authorization to expose a
    # mixed creative/operational block.  Only reference sections are clean
    # model-visible units.  `Creating an Arc` also contains file/registry/CLI
    # instructions, so the four original arc reference sections are the core.
    core_ids = {
        section_id for section_id in estimated_core_ids
        if "/references/" in row_by_id[section_id]["source_path"]
    }
    demand_by_id: dict[str, set[str]] = {}
    for demand, ids in scenario_ids.items():
        for section_id in ids:
            if section_id not in core_ids:
                demand_by_id.setdefault(section_id, set()).add(demand)

    climax_exception_id = next(
        section_id for section_id in core_ids
        if row_by_id[section_id]["heading_path"][-1] == "Climax"
    )

    sections = []
    for row in rows:
        section_id = row["section_id"]
        owner = row["stage_ownership"]
        reference_safe = "/references/" in row["source_path"]
        ownership_exception = (
            "PLOT_ARC_CLIMAX_REFERENCE_FALSE_POSITIVE_V1"
            if section_id == climax_exception_id else None
        )
        owner_allowed = owner in PLANNING_ALLOWED or ownership_exception is not None
        if section_id in core_ids:
            selection_class = "ALWAYS_ON_STAGE_CORE"
        elif section_id in demand_by_id and reference_safe and owner_allowed:
            selection_class = "DEMAND_SPECIFIC"
        elif (
            row["skill_id"] in PLANNING_SKILLS
            and reference_safe and owner_allowed
        ):
            selection_class = "OPTIONAL_SUPPORT"
        else:
            selection_class = "EXCLUDED_WRONG_LAYER"
        dependencies: list[str] = []
        if selection_class == "DEMAND_SPECIFIC":
            dependencies = sorted(core_ids)
        heading_text = " / ".join(row["heading_path"])
        sections.append({
            "skill_id": row["skill_id"],
            "section_id": section_id,
            "source_path": row["source_path"],
            "source_file_sha256": row["source_file_sha256"],
            "section_content_sha256": row["section_content_sha256"],
            "heading_path": row["heading_path"],
            "source_span_or_ast_node": row["source_span"],
            "section_order": row["section_order"],
            "stage_ownership": owner,
            "stage_ownership_exception": ownership_exception,
            "model_visible_safe": reference_safe,
            "demand_tags": sorted(demand_by_id.get(section_id, set())),
            "capability_tags": [slug(heading_text)],
            "dependency_section_ids": dependencies,
            "selection_class": selection_class,
            "contract_ids": [],
        })

    short_ids = catalog["short_used_skill_ids"]
    skill_source_sha256 = {}
    for skill_id in short_ids:
        source = ROOT / "vendor/novel-skills/source" / skill_id / "SKILL.md"
        skill_source_sha256[skill_id] = sha_bytes(source.read_bytes())
    wrong_ids = full["gates"]["stage_ownership"]["wrong_layer_section_ids"]
    missing_wrong = set(wrong_ids) - set(row_by_id)
    if missing_wrong:
        raise RuntimeError(f"sealed wrong-layer IDs missing: {sorted(missing_wrong)}")

    bindings = {}
    for name in (
        "skill-section-identity-contract-v1.json",
        "selective-skill-section-selector-contract-v1.json",
        "verbatim-section-rendering-policy-v1.json",
        "skill-semantic-stage-ownership-matrix-v1.json",
        "selective-skill-context-budget-policy-v1.json",
        "verbatim-selector-overflow-policy-v1.json",
    ):
        bindings[name] = sha_bytes((DESIGN / name).read_bytes())
    payload = {
        "schema": "SkillSectionIndexV1",
        "version": 1,
        "index_policy": "explicit immutable section IDs with exact file/section assertions",
        "source_root": "vendor/novel-skills/source",
        "short_used_skill_ids": short_ids,
        "skill_source_sha256": skill_source_sha256,
        "known_planning_wrong_layer_section_count": len(wrong_ids),
        "known_planning_wrong_layer_section_ids": wrong_ids,
        "planning_shared_subset_exception_section_ids": [climax_exception_id],
        "design_artifact_sha256": bindings,
        "sections": sections,
    }
    definition = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    payload["index_definition_sha256"] = sha_bytes(definition)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\r\n",
    )
    print(f"INDEX={OUTPUT.relative_to(ROOT).as_posix()}")
    print(f"SHORT_SKILL_COUNT={len(short_ids)}")
    print(f"SECTION_COUNT={len(sections)}")
    print(f"KNOWN_WRONG_LAYER_COUNT={len(wrong_ids)}")
    print(f"INDEX_FILE_SHA256={sha_bytes(OUTPUT.read_bytes())}")


if __name__ == "__main__":
    main()
