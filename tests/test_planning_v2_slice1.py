from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from novel_flywheel.planning_v2_slice1 import (
    EVENT_REALIZATION_ARTIFACT_FIELD_PATHS,
    EventRealizationCandidateV1,
    EventRealizationInputAuthorityV1,
    Slice1StaleParentError,
    artifact_canonical_bytes,
    artifact_sha256,
    assert_current_parent,
    build_event_realization_artifact,
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
