"""Future Phase 1 authority-cutover acceptance tests.

Every test is strict xfail by design.  Phase 0.5 records the current failure;
it does not change business behavior to make these criteria pass.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from novel_flywheel.context_packet import (
    build_stage_context_packet,
    render_stage_context_packet,
)
from novel_flywheel.generated_artifacts import ReliabilityTraceEnvelopeV1
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.db import Database
from novel_flywheel.memory import StoryMemory
from novel_flywheel.reliability_trace import (
    artifact_binding_matrix,
    resolve_projection_provenance,
)
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.workflows import WorkflowService


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _event(event_type: str, payload: dict, **extra):
    return ReliabilityTraceEnvelopeV1.model_validate({
        "schema": "ReliabilityTraceEnvelopeV1",
        "event_id": "phase1-acceptance-event-0001",
        "correlation_id": "phase1-acceptance",
        "event_type": event_type,
        "source_component": "phase1.acceptance",
        "source_writer": "current_system",
        "semantic_domain": "occurred_current",
        "observation_status": extra.pop("observation_status", "confirmed"),
        "payload": payload,
        **extra,
    })


@pytest.mark.xfail(
    strict=True,
    reason="Phase 1: long current-truth authority has not converged",
)
def test_phase1_acceptance_long_authority_convergence() -> None:
    state = {
        "confirmed_facts": [{
            "key": "hero.location", "value": "上海", "source": "story-state",
        }],
        "character_states": {"hero": {"location": "上海"}},
    }
    maintenance = {
        "facts": [{"fact_key": "protagonist.location", "value": "北京"}],
        "state": {}, "world_rules": [], "timeline": [],
    }
    canon, confirmed = WorkflowService._merge_short_maintenance_authority(
        state, maintenance, run_id="phase1-acceptance",
    )
    chapter_state = {"hero": {"location": "城门"}}
    observed_current_truths = {
        state["character_states"]["hero"]["location"],
        next(item["value"] for item in confirmed if item["key"] == "protagonist.location"),
        chapter_state["hero"]["location"],
        canon["state"]["hero"]["location"],
    }

    assert observed_current_truths == {"上海"}


@pytest.mark.xfail(
    strict=True,
    reason="Phase 1: legacy projections still lack source revision/hash",
)
def test_phase1_acceptance_projection_revision_is_provable(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "projects")
    project = store.create(ProjectCreate(
        title="Legacy projection", mode="long", genre="fantasy",
        premise="A legacy projection has no provenance.", target_words=100_000,
    ))
    state = StoryStateStore(db).ensure(project.id, project.path)
    StoryMemory(db).add_fact(
        project.id, "hero.location", "北京", True, "legacy-import",
    )
    context = StoryMemory(db).context(project.id, "hero")
    assert context["canon"]
    authority_hash = hashlib.sha256(json.dumps(
        state.data, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    provenance = resolve_projection_provenance(
        project.path,
        projections=["canon_facts"],
        requested_authority_revision=state.revision,
        requested_authority_hash=authority_hash,
    )

    assert provenance["revision_metadata_present"] is True
    assert provenance["actual_source_revision"] == state.revision
    assert provenance["source_authority_hash"] == authority_hash
    assert provenance["freshness"] == "fresh"


@pytest.mark.xfail(
    strict=True,
    reason="Phase 1: normal/window Maintenance evidence policies differ",
)
def test_phase1_acceptance_normal_window_maintenance_evidence_parity() -> None:
    normal = _event("authority_read", {
        "authority_type": "maintenance_entry_state",
        "reader": "normal_maintenance",
        "evidence_mode": "single_response",
    })
    window = _event("authority_read", {
        "authority_type": "maintenance_entry_state",
        "reader": "capacity_window_maintenance",
        "evidence_mode": "window_reduction",
    })

    assert normal.payload["evidence_mode"] == window.payload["evidence_mode"]


@pytest.mark.xfail(
    strict=True,
    reason="Phase 1/2: legacy review/resume binding remains unverifiable",
)
def test_phase1_acceptance_stale_review_resume_cannot_appear_fresh() -> None:
    legacy = _event(
        "resume_binding",
        {
            "artifact_type": "review.md",
            "binding_status": "unverifiable_legacy",
            "expected_input_sha256": _hash("draft-v2"),
            "actual_input_sha256": None,
            "reviewed_object_hash": None,
        },
        observation_status="unknown",
    )
    row = artifact_binding_matrix([legacy])[0]

    assert row["binding_status"] == "exact"
    assert row["reviewed_object_hash"] == _hash("draft-v2")


@pytest.mark.xfail(
    strict=True,
    reason="Phase 1: stage context can contain conflicting current truths without a conflict state",
)
def test_phase1_acceptance_canonical_context_uniqueness() -> None:
    relevant = json.dumps({
        "canon": [{"fact_key": "hero.location", "value": "北京"}],
        "recent_state": {"hero": {"location": "城门"}},
    }, ensure_ascii=False)
    skeleton = json.dumps({
        "confirmed_facts": [{"key": "hero.location", "value": "上海"}],
        "character_states": {"hero": {"location": "上海"}},
    }, ensure_ascii=False)
    packet = build_stage_context_packet(
        stage="draft",
        current_contract={"stage": "draft", "user_sha256": _hash(relevant)},
        constraints="Must preserve current character location.",
        skill_prompt="Skill instructions require continuity.",
        explicit_invariants=None,
        relevant_context=relevant,
        global_skeleton=skeleton,
    )
    rendered = render_stage_context_packet(packet)
    truths = {value for value in ("上海", "北京", "城门") if value in rendered}
    explicit_conflict = "authority_evidence_conflict" in rendered

    assert len(truths) == 1 or explicit_conflict

