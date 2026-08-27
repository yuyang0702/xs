from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence


COMPONENT_ORDER = (
    "ADVISORY_PROJECT_GUIDANCE",
    "ADVISORY_SKILL_GUIDANCE",
    "ADVISORY_STYLE_GUIDANCE",
)
SAMPLE_ORDER = ("A1", "A2", "A3", "B1", "B2", "B3")


class PilotGuidanceBindingError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha_json(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def build_active_reference_provenance(
    contributors: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Validate and bind active model-visible reference-derived contributors.

    Only stable identities, versions, hashes, and counts are returned. Source
    excerpts and model-visible prose are deliberately excluded.
    """

    normalized: list[dict[str, Any]] = []
    for raw in contributors:
        item = dict(raw)
        component_id = str(item.get("component_id") or "")
        if not component_id:
            raise PilotGuidanceBindingError(
                "UNKNOWN_MODEL_VISIBLE_REFERENCE_CONTEXT", "component_id",
            )
        model_visible = bool(item.get("model_visible"))
        required = (
            "source_artifact_id", "source_artifact_version", "source_sha256",
            "activation_identity",
        )
        if model_visible and any(item.get(field) in (None, "") for field in required):
            raise PilotGuidanceBindingError(
                "UNKNOWN_MODEL_VISIBLE_REFERENCE_CONTEXT", component_id,
            )
        if model_visible and not _is_sha256(item.get("source_sha256")):
            raise PilotGuidanceBindingError(
                "UNKNOWN_MODEL_VISIBLE_REFERENCE_CONTEXT", component_id,
            )
        version_ids = tuple(sorted(str(value) for value in item.get(
            "reference_version_ids", [],
        )))
        version_hashes = tuple(sorted(str(value) for value in item.get(
            "reference_version_sha256", [],
        )))
        if len(version_ids) != len(version_hashes) or any(
            not _is_sha256(value) for value in version_hashes
        ):
            raise PilotGuidanceBindingError(
                "STALE_REFERENCE_PROVENANCE_MANIFEST", component_id,
            )
        normalized.append({
            "component_id": component_id,
            "model_visible": model_visible,
            "source_artifact_id": str(item.get("source_artifact_id") or ""),
            "source_artifact_version": int(item.get("source_artifact_version") or 0),
            "source_sha256": str(item.get("source_sha256") or ""),
            "reference_source_ids": sorted(
                str(value) for value in item.get("reference_source_ids", [])
            ),
            "reference_version_ids": list(version_ids),
            "reference_version_sha256": list(version_hashes),
            "learning_node_ids": sorted(
                str(value) for value in item.get("learning_node_ids", [])
            ),
            "learning_node_revision_ids": sorted(
                str(value) for value in item.get("learning_node_revision_ids", [])
            ),
            "project_adoption_ids": sorted(
                str(value) for value in item.get("project_adoption_ids", [])
            ),
            "active_status": "ACTIVE" if model_visible else "INACTIVE",
            "activation_identity": str(item.get("activation_identity") or ""),
        })
    normalized.sort(key=lambda value: value["component_id"])
    definition = {
        "schema": "ActiveReferenceDerivedGuidanceProvenanceV1",
        "contributors": normalized,
        "active_contributor_count": sum(
            1 for item in normalized if item["model_visible"]
        ),
        "raw_reference_text_persisted": False,
        "active_reference_derived_guidance_provenance_complete": True,
    }
    return {**definition, "provenance_manifest_sha256": _sha_json(definition)}


@dataclass(frozen=True)
class PilotAdvisoryPartition:
    rendered_advisory: str
    rendered_advisory_sha256: str
    rendered_advisory_chars: int
    project_guidance_sha256: str
    project_guidance_chars: int
    skill_guidance_sha256: str
    skill_guidance_chars: int
    style_guidance_sha256: str
    style_guidance_chars: int
    style_profile_state: str
    component_order: tuple[str, ...]
    truncation_occurred: bool
    shedding_occurred: bool
    omitted_components: tuple[str, ...]
    omission_reasons: tuple[str, ...]

    def receipt(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("rendered_advisory")
        return {
            "schema": "PilotRenderedAdvisoryPartitionV1",
            **value,
            "raw_advisory_persisted": False,
        }


def render_pilot_advisory_partition(
    *,
    project_guidance: str,
    skill_guidance: str,
    style_guidance: str,
    maximum_chars: int,
) -> PilotAdvisoryPartition:
    """Render an isolated pilot advisory without compaction or shedding."""

    project = str(project_guidance or "")
    skill = str(skill_guidance or "")
    style = str(style_guidance or "")
    if not project.strip():
        raise PilotGuidanceBindingError(
            "UNKNOWN_MODEL_VISIBLE_REFERENCE_CONTEXT", "project guidance absent",
        )
    if not skill.strip():
        raise PilotGuidanceBindingError("UNKNOWN_SKILL_CONTEXT")
    sections = [
        f"{COMPONENT_ORDER[0]}:\n{project}",
        f"{COMPONENT_ORDER[1]}:\n{skill}",
    ]
    if style:
        sections.append(f"{COMPONENT_ORDER[2]}:\n{style}")
    rendered = "\n\n".join(sections)
    if maximum_chars <= 0 or len(rendered) > maximum_chars:
        raise PilotGuidanceBindingError(
            "ADVISORY_OVERFLOW", f"required={len(rendered)} limit={maximum_chars}",
        )
    return PilotAdvisoryPartition(
        rendered_advisory=rendered,
        rendered_advisory_sha256=_sha_text(rendered),
        rendered_advisory_chars=len(rendered),
        project_guidance_sha256=_sha_text(project),
        project_guidance_chars=len(project),
        skill_guidance_sha256=_sha_text(skill),
        skill_guidance_chars=len(skill),
        style_guidance_sha256=_sha_text(style),
        style_guidance_chars=len(style),
        style_profile_state=(
            "MODEL_VISIBLE" if style else "NOT_MODEL_VISIBLE_IN_PLANNING"
        ),
        component_order=COMPONENT_ORDER,
        truncation_occurred=False,
        shedding_occurred=False,
        omitted_components=(),
        omission_reasons=(),
    )


_SNAPSHOT_BINDINGS = (
    "pilot_id", "case_id", "authority_context_sha256", "task_context_sha256",
    "story_slice_sha256", "non_skill_prompt_sha256",
    "project_constraints_source_sha256", "output_schema_sha256",
    "tool_contract_sha256", "ptr9_policy_sha256", "ptr12_policy_sha256",
    "validator_policy_sha256", "route_model_policy_sha256",
)


def build_pilot_non_skill_guidance_snapshot(
    *,
    bindings: Mapping[str, object],
    compacted_project_guidance: str,
    reference_provenance: Mapping[str, object],
    style_profile_state: str,
) -> dict[str, Any]:
    for field in _SNAPSHOT_BINDINGS:
        value = bindings.get(field)
        if not value or field.endswith("sha256") and not _is_sha256(value):
            raise PilotGuidanceBindingError("UNBOUND_NON_SKILL_COMPONENT", field)
    if reference_provenance.get(
        "active_reference_derived_guidance_provenance_complete"
    ) is not True:
        raise PilotGuidanceBindingError("UNKNOWN_MODEL_VISIBLE_REFERENCE_CONTEXT")
    project = str(compacted_project_guidance or "")
    if not project.strip():
        raise PilotGuidanceBindingError("STALE_PROJECT_GUIDANCE_SHA")
    contributors = list(reference_provenance.get("contributors") or [])
    blueprint = next((item for item in contributors if item.get(
        "component_id"
    ) == "ACTIVE_BLUEPRINT_GUIDANCE"), None)
    prose = next((item for item in contributors if item.get(
        "component_id"
    ) == "ACTIVE_PROSE_BASELINE_GUIDANCE"), None)
    snapshot = {
        "schema": "PilotNonSkillGuidanceSnapshotV1",
        **{field: bindings[field] for field in _SNAPSHOT_BINDINGS},
        "compacted_project_guidance_sha256": _sha_text(project),
        "compacted_project_guidance_chars": len(project),
        "blueprint_provenance_manifest_sha256": reference_provenance[
            "provenance_manifest_sha256"
        ],
        "blueprint_sha256": (
            blueprint.get("source_sha256") if blueprint else "ABSENT"
        ),
        "prose_baseline_sha256": (
            prose.get("source_sha256") if prose else "ABSENT"
        ),
        "style_profile_state": style_profile_state,
        "component_order": list(COMPONENT_ORDER),
        "raw_reference_text_present": False,
        "raw_reference_excerpt_present": False,
    }
    definition = dict(snapshot)
    snapshot["snapshot_sha256"] = _sha_json(definition)
    return snapshot


_SNAPSHOT_MISMATCH_CODES = {
    "compacted_project_guidance_sha256": "STALE_PROJECT_GUIDANCE_SHA",
    "blueprint_sha256": "STALE_BLUEPRINT_VERSION",
    "prose_baseline_sha256": "STALE_PROSE_BASELINE_SHA",
    "blueprint_provenance_manifest_sha256": "STALE_REFERENCE_PROVENANCE_MANIFEST",
    "style_profile_state": "UNBOUND_MODEL_VISIBLE_STYLE_CONTEXT",
    "component_order": "WRONG_COMPONENT_ORDER",
}


def validate_pilot_non_skill_guidance_snapshot(
    candidate: Mapping[str, object], expected: Mapping[str, object],
) -> None:
    for field in _SNAPSHOT_BINDINGS:
        if candidate.get(field) != expected.get(field):
            raise PilotGuidanceBindingError("CHANGED_NON_SKILL_BINDING", field)
    for field, code in _SNAPSHOT_MISMATCH_CODES.items():
        if candidate.get(field) != expected.get(field):
            raise PilotGuidanceBindingError(code, field)
    if candidate.get("snapshot_sha256") != expected.get("snapshot_sha256"):
        raise PilotGuidanceBindingError("STALE_PROJECT_GUIDANCE_SHA", "snapshot")


def build_six_sample_component_matrix(
    *, snapshot: Mapping[str, object], arm_skill_contexts: Mapping[str, str],
) -> dict[str, Any]:
    if set(arm_skill_contexts) != {"A", "B"}:
        raise PilotGuidanceBindingError("UNKNOWN_SKILL_CONTEXT")
    arm_hashes = {
        arm: _sha_text(str(value)) for arm, value in arm_skill_contexts.items()
    }
    if arm_hashes["A"] == arm_hashes["B"]:
        raise PilotGuidanceBindingError("SKILL_CONTEXT_NOT_CHANGED")
    rows = []
    for sample_id in SAMPLE_ORDER:
        arm = sample_id[0]
        rows.append({
            "sample_id": sample_id,
            "arm": arm,
            "authority_sha256": snapshot["authority_context_sha256"],
            "task_sha256": snapshot["task_context_sha256"],
            "non_skill_prompt_sha256": snapshot["non_skill_prompt_sha256"],
            "project_guidance_sha256": snapshot[
                "compacted_project_guidance_sha256"
            ],
            "blueprint_provenance_sha256": snapshot[
                "blueprint_provenance_manifest_sha256"
            ],
            "prose_baseline_sha256": snapshot["prose_baseline_sha256"],
            "style_guidance_state": snapshot["style_profile_state"],
            "output_contract_sha256": snapshot["output_schema_sha256"],
            "validator_sha256": snapshot["validator_policy_sha256"],
            "model_route_policy_sha256": snapshot["route_model_policy_sha256"],
            "skill_context_sha256": arm_hashes[arm],
        })
    non_skill_fields = tuple(
        field for field in rows[0] if field not in {"sample_id", "arm", "skill_context_sha256"}
    )
    equal = all(
        len({row[field] for row in rows}) == 1 for field in non_skill_fields
    )
    if not equal:
        raise PilotGuidanceBindingError("DIFFERENT_A_B_PROJECT_GUIDANCE_BYTES")
    return {
        "schema": "SixSampleModelInputComponentMatrixV1",
        "samples": rows,
        "all_non_skill_components_equal_across_6": True,
        "same_non_skill_guidance_snapshot_for_a1_a2_a3_b1_b2_b3": True,
        "primary_changed_variable": "SKILL_CONTEXT",
        "uncontrolled_variable_count": 0,
    }
