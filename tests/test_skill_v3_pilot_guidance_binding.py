from __future__ import annotations

import hashlib

import pytest

from novel_flywheel.pilot_guidance import (
    PilotGuidanceBindingError,
    build_active_reference_provenance,
    build_pilot_non_skill_guidance_snapshot,
    build_six_sample_component_matrix,
    render_pilot_advisory_partition,
    validate_pilot_non_skill_guidance_snapshot,
)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def contributors() -> list[dict[str, object]]:
    return [
        {
            "component_id": "ACTIVE_BLUEPRINT_GUIDANCE",
            "model_visible": True,
            "source_artifact_id": "artifact-blueprint-v3",
            "source_artifact_version": 3,
            "source_sha256": sha("blueprint-v3"),
            "reference_source_ids": ["reference-1"],
            "reference_version_ids": ["reference-1-v2"],
            "reference_version_sha256": [sha("reference-1-v2")],
            "learning_node_ids": ["node-1"],
            "learning_node_revision_ids": ["revision-1"],
            "project_adoption_ids": ["adoption-1"],
            "activation_identity": "active:artifact-blueprint-v3:3",
        },
        {
            "component_id": "ACTIVE_PROSE_BASELINE_GUIDANCE",
            "model_visible": True,
            "source_artifact_id": "artifact-prose-v2",
            "source_artifact_version": 2,
            "source_sha256": sha("prose-v2"),
            "reference_source_ids": [],
            "reference_version_ids": [],
            "reference_version_sha256": [],
            "learning_node_ids": [],
            "learning_node_revision_ids": [],
            "project_adoption_ids": [],
            "activation_identity": "active:artifact-prose-v2:2",
        },
    ]


def bindings() -> dict[str, object]:
    return {
        "pilot_id": "pilot-character-heavy-v1",
        "case_id": "character-heavy",
        "authority_context_sha256": sha("authority"),
        "task_context_sha256": sha("task"),
        "story_slice_sha256": sha("story"),
        "non_skill_prompt_sha256": sha("non-skill"),
        "project_constraints_source_sha256": sha("project-source"),
        "output_schema_sha256": sha("schema"),
        "tool_contract_sha256": sha("tool"),
        "ptr9_policy_sha256": sha("ptr9"),
        "ptr12_policy_sha256": sha("ptr12"),
        "validator_policy_sha256": sha("validator"),
        "route_model_policy_sha256": sha("route-model"),
    }


def test_reference_provenance_is_deterministic_and_rejects_unbound_active_source() -> None:
    first = build_active_reference_provenance(contributors())
    second = build_active_reference_provenance(list(reversed(contributors())))
    assert first == second
    assert first["active_reference_derived_guidance_provenance_complete"] is True
    assert "raw_reference_text" not in first
    assert first["raw_reference_text_persisted"] is False

    broken = contributors()
    broken[0]["source_sha256"] = ""
    with pytest.raises(PilotGuidanceBindingError, match="UNKNOWN_MODEL_VISIBLE_REFERENCE_CONTEXT"):
        build_active_reference_provenance(broken)


def test_pilot_partition_preserves_project_bytes_across_unequal_skill_lengths() -> None:
    project = "project-guidance\n" * 40
    arm_a = "short skill"
    arm_b = "larger skill\n" * 80

    a = render_pilot_advisory_partition(
        project_guidance=project, skill_guidance=arm_a,
        style_guidance="", maximum_chars=8000,
    )
    b = render_pilot_advisory_partition(
        project_guidance=project, skill_guidance=arm_b,
        style_guidance="", maximum_chars=8000,
    )

    assert a.project_guidance_sha256 == b.project_guidance_sha256 == sha(project)
    assert a.project_guidance_chars == b.project_guidance_chars
    assert a.skill_guidance_sha256 != b.skill_guidance_sha256
    assert a.truncation_occurred is b.truncation_occurred is False
    assert a.shedding_occurred is b.shedding_occurred is False


def test_pilot_partition_fails_closed_instead_of_shedding_project_guidance() -> None:
    with pytest.raises(PilotGuidanceBindingError, match="ADVISORY_OVERFLOW"):
        render_pilot_advisory_partition(
            project_guidance="p" * 500,
            skill_guidance="s" * 500,
            style_guidance="",
            maximum_chars=900,
        )


def test_snapshot_and_six_sample_matrix_bind_only_skill_context_difference() -> None:
    provenance = build_active_reference_provenance(contributors())
    snapshot = build_pilot_non_skill_guidance_snapshot(
        bindings=bindings(),
        compacted_project_guidance="frozen project guidance",
        reference_provenance=provenance,
        style_profile_state="NOT_MODEL_VISIBLE_IN_PLANNING",
    )
    matrix = build_six_sample_component_matrix(
        snapshot=snapshot,
        arm_skill_contexts={"A": "skill A", "B": "skill B"},
    )

    assert matrix["all_non_skill_components_equal_across_6"] is True
    assert matrix["primary_changed_variable"] == "SKILL_CONTEXT"
    assert [row["sample_id"] for row in matrix["samples"]] == [
        "A1", "A2", "A3", "B1", "B2", "B3",
    ]
    assert len({row["project_guidance_sha256"] for row in matrix["samples"]}) == 1
    assert len({row["skill_context_sha256"] for row in matrix["samples"]}) == 2


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("compacted_project_guidance_sha256", "STALE_PROJECT_GUIDANCE_SHA"),
        ("blueprint_provenance_manifest_sha256", "STALE_REFERENCE_PROVENANCE_MANIFEST"),
        ("style_profile_state", "UNBOUND_MODEL_VISIBLE_STYLE_CONTEXT"),
        ("component_order", "WRONG_COMPONENT_ORDER"),
    ],
)
def test_snapshot_validation_negative_matrix(field: str, code: str) -> None:
    provenance = build_active_reference_provenance(contributors())
    expected = build_pilot_non_skill_guidance_snapshot(
        bindings=bindings(),
        compacted_project_guidance="frozen project guidance",
        reference_provenance=provenance,
        style_profile_state="NOT_MODEL_VISIBLE_IN_PLANNING",
    )
    candidate = {**expected}
    candidate[field] = "changed"

    with pytest.raises(PilotGuidanceBindingError, match=code):
        validate_pilot_non_skill_guidance_snapshot(candidate, expected)
