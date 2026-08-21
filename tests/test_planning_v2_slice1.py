from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from novel_flywheel.planning_v2_slice1 import (
    EVENT_REALIZATION_ARTIFACT_FIELD_PATHS,
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    Slice1CandidateRejected,
    Slice1FreezeViolationError,
    Slice1NoProgressError,
    Slice1StaleRepairError,
    Slice1RecoveryStateV1,
    Slice1StaleParentError,
    artifact_canonical_bytes,
    artifact_sha256,
    apply_bounded_candidate_patch,
    assemble_shadow_set,
    assert_current_parent,
    build_event_realization_artifact,
    convert_event_realization_candidate,
    compare_shadow_to_v1,
    compute_impact_closure,
    freeze_validated_artifact,
    record_recovery_progress,
    repair_local_metadata,
    regenerate_slice1_set,
    project_ptr3_finding,
    validate_candidate_payload,
    validate_event_realization_artifact,
)


H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64


def _authority(*, dependencies: tuple[str, ...] = ("dep-b", "dep-a")) -> EventRealizationInputAuthorityV1:
    return EventRealizationInputAuthorityV1(
        parent_authority_sha256=H1,
        formal_event_id="EV-00000002",
        formal_event_contract_sha256=H2,
        predecessor_boundary_sha256=H3,
        formal_event_ids=("EV-00000001", "EV-00000002", "EV-00000003"),
        segment_event_ids=(("EV-00000001",), ("EV-00000002", "EV-00000003")),
        dependency_artifact_ids=dependencies,
        context_projection_sha256=H4,
        required_obligation_ids=("motivation", "conflict", "intent", "causal-preparation"),
    )


def _candidate() -> EventRealizationCandidateV1:
    return EventRealizationCandidateV1(
        title="The sealed crossing",
        narrative=(
            "The investigator crosses the sealed bridge, confronts the guard, "
            "and preserves the clue needed for the next event."
        ),
    )


def test_slice1_artifact_has_exact_26_flattened_owned_fields() -> None:
    artifact = build_event_realization_artifact(_authority(), _candidate())

    assert len(EVENT_REALIZATION_ARTIFACT_FIELD_PATHS) == 26
    assert set(EVENT_REALIZATION_ARTIFACT_FIELD_PATHS) == {
        "/schema", "/version", "/artifact_id", "/artifact_revision", "/stage",
        "/scope_id", "/shadow_only", "/parent_authority_sha256",
        "/formal_event_id", "/formal_event_ordinal", "/segment_ordinal",
        "/formal_event_contract_sha256", "/predecessor_boundary_sha256",
        "/dependency_artifact_ids", "/dependency_set_sha256", "/title",
        "/narrative", "/payload_sha256", "/provenance/producer_kind",
        "/provenance/contract_identity", "/provenance/source_candidate_sha256",
        "/validation_status", "/validation_receipt_sha256", "/freeze_state",
        "/commit_performed", "/promotion_eligible",
    }
    dumped = artifact.model_dump(mode="json", by_alias=True)
    assert dumped["schema"] == "EventRealizationArtifactV1"
    assert dumped["version"] == 1
    assert dumped["shadow_only"] is True
    assert dumped["commit_performed"] is False
    assert dumped["promotion_eligible"] is False


def test_identity_and_serialization_are_deterministic() -> None:
    left = build_event_realization_artifact(_authority(), _candidate())
    right = build_event_realization_artifact(
        _authority(dependencies=("dep-a", "dep-b")), _candidate(),
    )

    assert left == right
    assert left.dependency_artifact_ids == ("dep-a", "dep-b")
    assert artifact_canonical_bytes(left) == artifact_canonical_bytes(right)
    assert artifact_sha256(left) == artifact_sha256(right)
    assert json.loads(artifact_canonical_bytes(left))["value"]["title"] == left.title


def test_artifact_binds_exact_parent_and_rejects_stale_parent() -> None:
    artifact = build_event_realization_artifact(_authority(), _candidate())

    assert_current_parent(artifact, H1)
    with pytest.raises(Slice1StaleParentError) as caught:
        assert_current_parent(artifact, "f" * 64)
    assert caught.value.code == "SLICE1_STALE_PARENT"


def test_authority_must_contain_the_event_exactly_once() -> None:
    payload = _authority().model_dump(mode="python")
    payload["formal_event_ids"] = ("EV-00000001", "EV-00000003")

    with pytest.raises(ValidationError):
        EventRealizationInputAuthorityV1.model_validate(payload)


def test_candidate_is_strict_and_owns_only_title_and_narrative() -> None:
    assert tuple(EventRealizationCandidateV1.model_fields) == ("title", "narrative")
    with pytest.raises(ValidationError):
        EventRealizationCandidateV1.model_validate({
            "title": "Owned title",
            "narrative": "A sufficiently meaningful realization remains present.",
            "formal_event_id": "EV-00000002",
        })
    with pytest.raises(ValidationError):
        EventRealizationCandidateV1.model_validate({"title": 7, "narrative": "valid narrative value"})


def test_slice1_module_does_not_import_v1_workflow_or_state_writers() -> None:
    import novel_flywheel.planning_v2_slice1 as module

    source = module.__loader__.get_source(module.__name__)  # type: ignore[union-attr]
    assert "novel_flywheel.workflows" not in source
    assert "novel_flywheel.contract_runtime" not in source
    assert "from novel_flywheel.story_state" not in source
    assert "import novel_flywheel.story_state" not in source
    assert "from novel_flywheel.canon import" not in source
    assert "import novel_flywheel.canon\n" not in source


def test_candidate_ownership_violation_retains_exact_lossless_finding() -> None:
    with pytest.raises(Slice1CandidateRejected) as caught:
        validate_candidate_payload({
            "title": "Candidate title",
            "narrative": "A complete narrative with an actor, action, and result.",
            "formal_event_id": "EV-00000002",
        }, authority=_authority())

    finding = caught.value.findings[0]
    assert finding.rule_code == "SLICE1_FIELD_OWNERSHIP_VIOLATION"
    assert finding.field_path_json_pointer == "/formal_event_id"
    assert finding.invariant_id == "candidate_contains_only_title_narrative"
    assert finding.raw_value_included is False
    assert finding.raw_story_included is False
    projected = project_ptr3_finding(finding)
    assert projected.field_path == "/formal_event_id"
    assert projected.rule_code == finding.rule_code


def test_missing_candidate_field_retains_path_instead_of_generic_failure() -> None:
    with pytest.raises(Slice1CandidateRejected) as caught:
        validate_candidate_payload({"title": "Only a title"}, authority=_authority())
    assert caught.value.findings[0].field_path_json_pointer == "/narrative"
    assert caught.value.findings[0].rule_code == "SLICE1_REQUIRED_FIELD_MISSING"


def test_malformed_conversion_retains_typed_top_level_finding() -> None:
    with pytest.raises(Slice1CandidateRejected) as caught:
        convert_event_realization_candidate(
            '{"title":"broken","narrative":', authority=_authority(),
        )
    finding = caught.value.findings[0]
    assert finding.rule_code == "SLICE1_OUTPUT_TRUNCATED"
    assert finding.field_path_json_pointer == "$"
    assert finding.rule_code != "semantic_validation_failed"


def test_validator_stack_passes_and_defers_global_closure() -> None:
    artifact = build_event_realization_artifact(_authority(), _candidate())
    receipt = validate_event_realization_artifact(artifact, _authority())

    assert receipt.status == "PASS"
    assert receipt.findings == ()
    assert "draft_executability" in receipt.deferred_global_invariant_ids


def test_referential_and_semantic_findings_remain_distinct_and_path_bound() -> None:
    artifact = build_event_realization_artifact(_authority(), _candidate())
    damaged = artifact.model_copy(update={
        "formal_event_ordinal": 99,
        "narrative": "short",
    })
    receipt = validate_event_realization_artifact(damaged, _authority())

    assert receipt.status == "REJECTED"
    findings = {(item.rule_code, item.field_path_json_pointer) for item in receipt.findings}
    assert ("SLICE1_EVENT_ORDINAL_MISMATCH", "/formal_event_ordinal") in findings
    assert ("SLICE1_NARRATIVE_INCOMPLETE", "/narrative") in findings
    assert all(item.rule_code != "semantic_validation_failed" for item in receipt.findings)


def _authority_for(
    event_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    predecessor_sha256: str = H3,
) -> EventRealizationInputAuthorityV1:
    return EventRealizationInputAuthorityV1(
        parent_authority_sha256=H1,
        formal_event_id=event_id,
        formal_event_contract_sha256=(H2 if event_id.endswith("1") else H4),
        predecessor_boundary_sha256=predecessor_sha256,
        formal_event_ids=("EV-00000001", "EV-00000002"),
        segment_event_ids=(("EV-00000001", "EV-00000002"),),
        dependency_artifact_ids=dependencies,
        context_projection_sha256="5" * 64,
        required_obligation_ids=("motivation", "conflict", "intent"),
    )


def _frozen(
    authority: EventRealizationInputAuthorityV1,
    *,
    title: str = "Bounded title",
    narrative: str = "The actor makes a choice, meets resistance, and changes the next event.",
):
    artifact = build_event_realization_artifact(
        authority, EventRealizationCandidateV1(title=title, narrative=narrative),
    )
    receipt = validate_event_realization_artifact(artifact, authority)
    return freeze_validated_artifact(artifact, receipt)


def test_validated_artifact_freezes_without_changing_creative_payload() -> None:
    artifact = build_event_realization_artifact(_authority(), _candidate())
    frozen = freeze_validated_artifact(
        artifact, validate_event_realization_artifact(artifact, _authority()),
    )

    assert frozen.freeze_state == "FROZEN"
    assert frozen.validation_status == "PASS"
    assert frozen.title == artifact.title
    assert frozen.narrative == artifact.narrative
    assert frozen.payload_sha256 == artifact.payload_sha256


def test_freeze_rejects_failed_receipt_and_stale_cas_patch() -> None:
    artifact = build_event_realization_artifact(_authority(), _candidate())
    rejected = validate_event_realization_artifact(
        artifact.model_copy(update={"formal_event_ordinal": 99}), _authority(),
    )
    with pytest.raises(Slice1FreezeViolationError):
        freeze_validated_artifact(artifact, rejected)

    frozen = _frozen(_authority())
    finding = validate_candidate_payload  # keep a stable function reference outside state
    del finding
    with pytest.raises(Slice1StaleRepairError):
        apply_bounded_candidate_patch(
            frozen,
            authority=_authority(),
            finding_revision=99,
            field_path="/title",
            replacement="A corrected bounded title",
        )


def test_bounded_patch_changes_only_target_and_preserves_unrelated_frozen_artifact() -> None:
    first_authority = _authority_for("EV-00000001")
    first = _frozen(first_authority, title="First title")
    second_authority = _authority_for(
        "EV-00000002", dependencies=(first.artifact_id,),
        predecessor_sha256=first.payload_sha256,
    )
    second = _frozen(second_authority, title="Second title")
    first_before = artifact_sha256(first)

    patched = apply_bounded_candidate_patch(
        second,
        authority=second_authority,
        finding_revision=second.artifact_revision,
        field_path="/title",
        replacement="Second title corrected",
    )

    assert patched.title == "Second title corrected"
    assert patched.narrative == second.narrative
    assert patched.artifact_revision == second.artifact_revision + 1
    assert patched.freeze_state == "FROZEN"
    assert artifact_sha256(first) == first_before


def test_local_metadata_repair_cannot_rewrite_frozen_content() -> None:
    frozen = _frozen(_authority())
    with pytest.raises(Slice1FreezeViolationError):
        repair_local_metadata(frozen, authority=_authority())


def test_local_metadata_repair_recomputes_only_open_derived_fields() -> None:
    artifact = build_event_realization_artifact(_authority(), _candidate())
    damaged = artifact.model_copy(update={"dependency_set_sha256": "f" * 64})

    repaired = repair_local_metadata(damaged, authority=_authority())

    assert repaired.dependency_set_sha256 == artifact.dependency_set_sha256
    assert repaired.title == artifact.title
    assert repaired.narrative == artifact.narrative


def test_impact_closure_is_bounded_or_escalates_to_slice1_regeneration() -> None:
    first = _frozen(_authority_for("EV-00000001"))
    second_authority = _authority_for(
        "EV-00000002", dependencies=(first.artifact_id,),
        predecessor_sha256=first.payload_sha256,
    )
    second = _frozen(second_authority)

    local = compute_impact_closure(
        field_path="/title", current=second,
    )
    adjacent = compute_impact_closure(
        field_path="/narrative", current=second, predecessor=first,
        dependency_hint_ids=(first.artifact_id,),
    )
    unknown = compute_impact_closure(
        field_path="/narrative", current=second, predecessor=first,
        dependency_hint_ids=("unknown-artifact",),
    )

    assert local.repair_level == 1 and local.closure_size == 1
    assert adjacent.repair_level == 2 and adjacent.closure_size == 2
    assert unknown.repair_level == 3
    assert unknown.requires_slice1_regeneration is True


def test_same_finding_without_state_change_stops_recovery() -> None:
    artifact = build_event_realization_artifact(_authority(), _candidate())
    finding = _diagnostic_for_test(artifact)
    state = Slice1RecoveryStateV1()

    with pytest.raises(Slice1NoProgressError) as caught:
        record_recovery_progress(
            state,
            level=1,
            before=artifact,
            after=artifact,
            before_findings=(finding,),
            after_findings=(finding,),
            closure_artifact_ids=(artifact.artifact_id,),
        )
    assert caught.value.code == "SLICE1_NO_PROGRESS"


def test_recovery_accepts_strict_issue_progress_once_per_level() -> None:
    clean = build_event_realization_artifact(_authority(), _candidate())
    damaged = clean.model_copy(update={"formal_event_ordinal": 99})
    finding = validate_event_realization_artifact(damaged, _authority()).findings[0]

    state = record_recovery_progress(
        Slice1RecoveryStateV1(),
        level=1,
        before=damaged,
        after=clean,
        before_findings=(finding,),
        after_findings=(),
        closure_artifact_ids=(clean.artifact_id,),
    )
    assert state.attempt_counts == {1: 1}
    with pytest.raises(Slice1NoProgressError):
        record_recovery_progress(
            state,
            level=1,
            before=damaged,
            after=clean,
            before_findings=(finding,),
            after_findings=(),
            closure_artifact_ids=(clean.artifact_id,),
        )


def _diagnostic_for_test(artifact):
    damaged = artifact.model_copy(update={"formal_event_ordinal": 99})
    return validate_event_realization_artifact(damaged, _authority()).findings[0]


def test_deterministic_assembly_enforces_order_coverage_and_predecessor_binding() -> None:
    first = _frozen(_authority_for("EV-00000001"))
    second_authority = _authority_for(
        "EV-00000002", dependencies=(first.artifact_id,),
        predecessor_sha256=first.payload_sha256,
    )
    second = _frozen(second_authority)

    assembled = assemble_shadow_set(
        (second, first),
        parent_authority_sha256=H1,
        expected_event_ids=("EV-00000001", "EV-00000002"),
    )
    assert tuple(item.formal_event_id for item in assembled.ordered_artifacts) == (
        "EV-00000001", "EV-00000002",
    )
    assert assembled.shadow_only is True
    assert assembled.commit_performed is False


def test_slice1_regeneration_is_offline_and_never_regenerates_whole_planning() -> None:
    first_authority = _authority_for("EV-00000001")
    first_seed = _frozen(first_authority)
    second_authority = _authority_for(
        "EV-00000002", dependencies=(first_seed.artifact_id,),
        predecessor_sha256=first_seed.payload_sha256,
    )
    regenerated = regenerate_slice1_set(
        (first_authority, second_authority),
        {
            "EV-00000001": EventRealizationCandidateV1(
                title="First", narrative="The first actor chooses, struggles, and hands off a consequence."
            ),
            "EV-00000002": EventRealizationCandidateV1(
                title="Second", narrative="The second actor receives that consequence, resists, and completes the unit."
            ),
        },
    )
    assert len(regenerated.ordered_artifacts) == 2
    assert regenerated.whole_planning_regeneration_performed is False


def test_shadow_comparison_is_read_only_and_types_cross_version_divergence() -> None:
    first = _frozen(_authority_for("EV-00000001"))
    second_authority = _authority_for(
        "EV-00000002", dependencies=(first.artifact_id,),
        predecessor_sha256=first.payload_sha256,
    )
    second = _frozen(second_authority)
    assembled = assemble_shadow_set(
        (first, second), parent_authority_sha256=H1,
        expected_event_ids=("EV-00000001", "EV-00000002"),
    )
    v1 = {
        "event_ids": ["EV-00000001", "EV-00000002"],
        "narrative_meaningful_counts": {
            "EV-00000001": 5, "EV-00000002": 5,
        },
        "obligation_ids": {
            "EV-00000001": ["motivation"],
            "EV-00000002": ["conflict"],
        },
    }
    before = deepcopy(v1)
    receipt = compare_shadow_to_v1(
        v1,
        assembled,
        shadow_obligation_ids={
            "EV-00000001": ("motivation",),
            "EV-00000002": ("conflict",),
        },
    )

    assert receipt.divergence == "neutral_creative_divergence"
    assert receipt.mutation_performed is False
    assert v1 == before
    unavailable = compare_shadow_to_v1(
        {}, assembled, shadow_obligation_ids={}, historical_evidence_available=False,
    )
    assert unavailable.divergence == "uncomparable_historical_evidence_missing"
