from __future__ import annotations

import hashlib

from novel_flywheel.generated_artifacts import ReliabilityTraceEnvelopeV1
from novel_flywheel.reliability_trace import (
    assess_authority_evidence_conflict,
    artifact_binding_matrix,
    authority_lineage,
    emit_observation,
    event_type_coverage_matrix,
    projection_provenance_matrix,
    projection_reconciliation,
    recovery_attempt_dag,
    resolve_projection_provenance,
    shadow_slot_identity,
    trace_coverage_matrix,
)
from novel_flywheel.workflows import WorkflowService


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _event(event_type: str, sequence: int, payload: dict, **extra):
    base = {
        "schema": "ReliabilityTraceEnvelopeV1",
        "event_id": f"workflow-event-{sequence:016d}",
        "correlation_id": "workflow-run",
        "sequence": sequence,
        "event_type": event_type,
        "source_component": extra.pop("source_component", "test.workflow"),
        "source_writer": extra.pop("source_writer", "observer"),
        "semantic_domain": extra.pop("semantic_domain", "occurred_current"),
        "observation_status": extra.pop("observation_status", "confirmed"),
        "payload": payload,
        **extra,
    }
    return ReliabilityTraceEnvelopeV1.model_validate(base)


def test_long_authority_divergence_is_characterized_at_legacy_key_boundary() -> None:
    state = {
        "confirmed_facts": [{
            "key": "hero.location", "value": "上海", "source": "story-state",
        }],
        "character_states": {"hero": {"location": "上海"}},
    }
    candidate = {
        "facts": [{"fact_key": "protagonist.location", "value": "北京"}],
        "state": {}, "world_rules": [], "timeline": [],
    }
    canon, confirmed = WorkflowService._merge_short_maintenance_authority(
        state, candidate, run_id="maintenance-run",
    )
    assert {item["value"] for item in confirmed} == {"上海", "北京"}
    assert canon["state"]["hero"]["location"] == "上海"
    chapter_state = {"hero": {"location": "城门"}}
    assert chapter_state["hero"]["location"] not in {item["value"] for item in confirmed}


def test_short_version_lineage_keeps_explicit_object_hashes() -> None:
    events = [
        _event("promotion_write", 1, {"store": "ShortCheckpoint", "writer": "short"},
               object_new_hash="1" * 64),
        _event("promotion_write", 2, {"store": "StoryCandidate", "writer": "polish"},
               object_old_hash="1" * 64, object_new_hash="2" * 64),
        _event("promotion_write", 3, {"store": "StoryState", "writer": "saga"},
               authority_revision=2, object_old_hash="2" * 64,
               object_new_hash="3" * 64),
    ]
    lineage = authority_lineage(events)
    assert [row["object_new_hash"] for row in lineage] == ["1" * 64, "2" * 64, "3" * 64]
    assert lineage[-1]["authority_revision"] == 2


def test_normal_and_window_maintenance_evidence_modes_remain_distinct() -> None:
    normal = _event("authority_read", 1, {
        "authority_type": "maintenance_entry_state", "reader": "normal_maintenance",
        "evidence_mode": "single_response",
    })
    window = _event("authority_read", 2, {
        "authority_type": "maintenance_entry_state", "reader": "capacity_window_maintenance",
        "evidence_mode": "window_reduction",
    })
    assert normal.payload["evidence_mode"] != window.payload["evidence_mode"]


def test_shadow_slot_groups_aliases_but_separates_semantic_dimensions_and_domains() -> None:
    entity = _hash("hero")
    first = shadow_slot_identity(
        entity_hash=entity, predicate="location", semantic_domain="occurred_current",
    )
    alias = shadow_slot_identity(
        entity_hash=entity, predicate="location", semantic_domain="occurred_current",
    )
    knowledge = shadow_slot_identity(
        entity_hash=entity, predicate="knowledge", semantic_domain="occurred_current",
        knowledge_owner_hash=entity,
    )
    future = shadow_slot_identity(
        entity_hash=entity, predicate="location", semantic_domain="future_normative",
    )
    reverse_relation = shadow_slot_identity(
        entity_hash=entity, predicate="relationship", semantic_domain="occurred_current",
        relationship_direction="B->A",
    )
    assert first == alias
    assert len({first, knowledge, future, reverse_relation}) == 4


def test_authority_conflict_requires_slot_time_domain_values_and_sources() -> None:
    left = {
        "shadow_slot": "slot-location", "story_time": "chapter-32",
        "semantic_domain": "occurred_current", "value_sha256": _hash("存活"),
        "source_hash": _hash("final-narrative"),
    }
    right = {**left, "value_sha256": _hash("死亡"), "source_hash": _hash("story-state")}
    conflict = assess_authority_evidence_conflict(left, right)
    assert conflict["conflict"] is True
    assert conflict["payload"]["resolution"] == "unresolved_phase0"
    assert assess_authority_evidence_conflict(
        left, {**right, "story_time": None},
    ) == {"observation_status": "unknown", "conflict": False}


def test_projection_revision_absence_remains_unknown() -> None:
    event = _event("projection_read", 1, {
        "projection": "StoryMemory.context", "requested_revision": None,
        "actual_revision": None, "revision_metadata_present": False,
        "stale": "unknown", "result_sha256": _hash("projection"),
    }, observation_status="unknown")
    view = projection_reconciliation([event])
    assert view[0]["projection"] == "StoryMemory.context"
    assert view[0]["requested_revision"] is None
    assert view[0]["actual_revision"] is None
    assert view[0]["source_authority_hash"] is None
    assert view[0]["revision_metadata_present"] is False
    assert view[0]["stale"] == "unknown"
    assert view[0]["observation_status"] == "unknown"
    assert view[0]["projection_hash"] == _hash("projection")
    assert view[0]["projection_sources"] == []


def test_stale_review_binding_remains_unverifiable_not_rejected() -> None:
    event = _event("resume_binding", 1, {
        "artifact_type": "review.md", "binding_status": "unverifiable_legacy",
        "expected_input_sha256": _hash("draft-v2"), "actual_input_sha256": None,
    }, observation_status="unknown")
    assert event.payload["binding_status"] == "unverifiable_legacy"
    assert event.observation_status == "unknown"
    binding = artifact_binding_matrix([event])[0]
    assert binding["binding_lane"] == "legacy"
    assert binding["binding_status"] == "unverifiable_legacy"
    assert binding["actual_input_object_hash"] is None


def test_recovery_attempt_dag_uses_only_explicit_parent_edges() -> None:
    events = [
        _event("recovery_attempt", 1, {
            "attempt_id": "1", "parent_attempt_id": None, "action": "retry_same_route",
            "outcome": "protocol_failure", "model_call_delta": 1,
        }, semantic_domain="unknown"),
        _event("recovery_attempt", 2, {
            "attempt_id": "3", "parent_attempt_id": "1", "action": "fallback_capable_route",
            "outcome": "valid", "model_call_delta": 1,
        }, semantic_domain="unknown"),
    ]
    dag = recovery_attempt_dag(events)
    assert dag["edges"] == [{"from": "1", "to": "3", "explicit": True}]
    assert sum(node["model_call_delta"] for node in dag["nodes"]) == 2


def test_coverage_matrix_reports_missing_points_without_fabrication() -> None:
    one = _event(
        "authority_read", 1,
        {"authority_type": "StoryState", "reader": "stage:review"},
        source_component="workflows.WorkflowService._stage",
    )
    matrix = trace_coverage_matrix([one])
    assert matrix["covered"] == 1
    assert "projection_read" in matrix["coverage_gaps"]


def test_projection_provenance_resolves_only_trace_backed_writers(tmp_path) -> None:
    project = tmp_path / "projects" / "project"
    project.mkdir(parents=True)
    authority_hash = _hash("story-state-revision-4")
    projection_hash = _hash("canon-fact-effect")
    journal_hash = _hash("journal")
    assert emit_observation(
        project,
        event_type="promotion_write",
        source_component="project_transactions.apply_project_memory_effects",
        source_writer="long-setup",
        observation_status="confirmed",
        payload={
            "store": "ProjectMutationCanonFactV1",
            "writer": "long-setup",
            "projection": "canon_facts",
            "requested_authority_revision": 4,
            "actual_source_revision": 4,
            "source_authority_hash": authority_hash,
            "source_commit_id": "commit-" + "a" * 32,
            "projection_hash": projection_hash,
            "source_artifact": "ProjectMutationJournalV1",
            "source_artifact_hash": journal_hash,
            "provenance_schema": "ProjectionProvenanceV1",
            "provenance_version": 1,
            "freshness": "fresh",
        },
        correlation_id="provenance",
        semantic_domain="occurred_current",
        authority_revision=4,
        authority_hash=authority_hash,
        object_new_hash=projection_hash,
    )

    resolved = resolve_projection_provenance(
        project,
        projections=["canon_facts"],
        requested_authority_revision=4,
        requested_authority_hash=authority_hash,
    )
    assert resolved["revision_metadata_present"] is True
    assert resolved["actual_source_revision"] == 4
    assert resolved["source_authority_hash"] == authority_hash
    assert resolved["projection_sources"][0]["source_commit_id"].startswith("commit-")
    assert resolved["freshness"] == "fresh"
    assert resolved["projection_sources"][0]["source_artifact_hash"] == journal_hash

    legacy = resolve_projection_provenance(
        project,
        projections=["chapter_states"],
        requested_authority_revision=4,
        requested_authority_hash=authority_hash,
    )
    assert legacy["revision_metadata_present"] is False
    assert legacy["actual_source_revision"] is None
    assert legacy["freshness"] == "unknown"


def test_projection_and_artifact_binding_matrices_preserve_exact_lineage() -> None:
    authority_hash = _hash("authority")
    projection = _event(
        "promotion_write", 1,
        {
            "store": "ProjectMutationChapterStateV1",
            "writer": "long-chapter",
            "projection": "chapter_states",
            "requested_authority_revision": 7,
            "actual_source_revision": 7,
            "source_authority_hash": authority_hash,
            "source_commit_id": "commit-" + "b" * 32,
            "projection_hash": _hash("projection"),
            "source_artifact": "ProjectMutationJournalV1",
            "source_artifact_hash": _hash("journal"),
            "provenance_schema": "ProjectionProvenanceV1",
            "provenance_version": 1,
            "freshness": "fresh",
        },
        authority_revision=7,
        authority_hash=authority_hash,
        object_new_hash=_hash("projection"),
    )
    binding = _event(
        "resume_binding", 2,
        {
            "artifact_type": "review.md",
            "binding_status": "exact",
            "input_object_hash": _hash("review-input"),
            "output_object_hash": _hash("review-output"),
            "reviewed_object_hash": _hash("draft"),
            "policy": "final_review",
            "policy_version": 3,
            "validator_set": ["contract_adapter", "domain_validator"],
            "parent_artifact": _hash("draft"),
            "superseded_artifact": None,
        },
        authority_revision=7,
        authority_hash=authority_hash,
        object_new_hash=_hash("review-output"),
    )
    repair = _event(
        "repair_diff", 3,
        {
            "allowed_scope_source": "reviewer_minfix",
            "changed_paths": ["$.state.hero.location"],
            "validators_rerun": ["domain_validator"],
            "reviewed_object_hash": _hash("draft"),
            "policy_version": 1,
        },
        object_old_hash=_hash("draft"),
        object_new_hash=_hash("new-draft"),
    )

    provenance = projection_provenance_matrix([projection])
    assert provenance[0]["actual_source_revision"] == 7
    assert provenance[0]["source_artifact_hash"] == _hash("journal")
    assert provenance[0]["source_commit_id"].startswith("commit-")
    bindings = artifact_binding_matrix([binding, repair])
    assert bindings[0]["reviewed_object_hash"] == _hash("draft")
    assert bindings[0]["validator_set"] == [
        "contract_adapter", "domain_validator",
    ]
    assert bindings[0]["binding_lane"] == "exact_v2"
    assert bindings[1]["parent_artifact"] == _hash("draft")
    assert bindings[1]["superseded_artifact"] == _hash("draft")


def test_event_type_coverage_distinguishes_normal_and_synthetic() -> None:
    events = [
        _event(
            "authority_read", 1,
            {"authority_type": "StoryState", "reader": "stage:review"},
        ),
        _event(
            "repair_diff", 2,
            {
                "allowed_scope_source": "controlled_failure_injection",
                "changed_paths": ["$.state"],
                "validators_rerun": ["domain_validator"],
                "synthetic": True,
            },
        ),
    ]
    matrix = event_type_coverage_matrix(events)
    authority = next(
        row for row in matrix["rows"] if row["event_type"] == "authority_read"
    )
    repair = next(
        row for row in matrix["rows"] if row["event_type"] == "repair_diff"
    )
    assert authority["normal_observed"] == 1
    assert authority["synthetic_observed"] == 0
    assert repair["normal_observed"] == 0
    assert repair["synthetic_observed"] == 1
