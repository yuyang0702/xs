from __future__ import annotations

import hashlib

import pytest

from novel_flywheel.canonical_shadow import story_state_authority_hash
from novel_flywheel.db import Database
from novel_flywheel.short_canonical_promotion import (
    build_short_commit_receipt,
    build_short_hold_decision,
    build_short_writer_plan,
    classify_legacy_disposition,
    evaluate_short_canonical_gate,
    make_maintenance_inventory,
    make_writer_patch,
    proposal_units_from_candidate,
    select_short_mutation_operation,
    short_publication_story_time,
    short_canonical_feature_snapshot,
)


def _profiles(root) -> None:
    characters = root / "characters"
    characters.mkdir(parents=True)
    (characters / "aster.md").write_text(
        "---\nname: Aster\naliases: [A]\n---\n", encoding="utf-8",
    )
    (characters / "rowan.md").write_text(
        "---\nname: Rowan\n---\n", encoding="utf-8",
    )


def _eligible_fixture(
    root, *, legacy_accepted: bool = True, source_mode: str = "normal",
):
    _profiles(root)
    source = (
        "Aster arrived at North Gate. "
        "Aster learned the red seal code. "
        "Aster now trusts Rowan."
    ).encode("utf-8")
    state = {
        "manuscript_revision": 3,
        "confirmed_facts": [],
        "character_states": {
            "Aster": {
                "location": "South Pier",
                "knowledge": {"red-seal": False},
                "relationships": {"Rowan": "distrust"},
            },
            "Rowan": {},
        },
    }
    proposal = {
        "facts": [],
        "state_transitions": [
            {
                "character": "Aster", "field": "location",
                "from": "South Pier", "to": "North Gate",
                "evidence": "arrived at North Gate",
            },
            {
                "character": "Aster", "field": "knowledge.red-seal",
                "from": False, "to": True,
                "evidence": "learned the red seal code",
            },
            {
                "character": "Aster", "field": "relationships.Rowan",
                "from": "distrust", "to": "trust",
                "evidence": "now trusts Rowan",
            },
        ],
    }
    units = proposal_units_from_candidate(
        proposal, source_mode=source_mode, source_locator="fixture",
        source_attempt=1,
    )
    classified = classify_legacy_disposition(
        units, proposal if legacy_accepted else {"facts": []},
    )
    inventory = make_maintenance_inventory(
        source_mode=source_mode,
        source_artifact_hash=hashlib.sha256(source).hexdigest(),
        base_authority_revision=4,
        base_authority_hash=story_state_authority_hash(state),
        units=classified,
    )
    return source, state, inventory


def test_story_time_is_logical_and_narrative_hash_independent() -> None:
    state = {"manuscript_revision": 8}
    first = short_publication_story_time("project-1", state)
    reformatted_narrative_hash = hashlib.sha256(b"different bytes").hexdigest()
    second = short_publication_story_time("project-1", state)
    assert first == second
    assert reformatted_narrative_hash not in first.story_time

    later = short_publication_story_time(
        "project-1", {"manuscript_revision": 9},
    )
    assert later.story_time != first.story_time
    assert select_short_mutation_operation(
        proposed_story_time=first.story_time,
        current_story_time=first.story_time,
        current_exists=True, explicit_transition=False,
    ) == "SUPERSEDE"
    assert select_short_mutation_operation(
        proposed_story_time=later.story_time,
        current_story_time=first.story_time,
        current_exists=True, explicit_transition=True,
    ) == "TRANSITION"


def test_global_flag_cannot_authorize_project_canary(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.set_feature_flag("short_canonical_v2", True)
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    snapshot = short_canonical_feature_snapshot(db, "project-1")
    assert snapshot.flag_scope_type == "global"
    assert snapshot.environment_enabled is True
    assert snapshot.project_flag_enabled is False
    assert snapshot.enabled is False


def test_gate_uses_exact_story_state_and_final_evidence(tmp_path) -> None:
    source, state, inventory = _eligible_fixture(tmp_path)
    result = evaluate_short_canonical_gate(
        project_root=tmp_path, project_id="project-1",
        inventory=inventory, final_source_bytes=source,
        story_state_revision=4, story_state_data=state,
    )
    assert result.canonical_gate_result == "eligible"
    assert result.operational_readiness == "ready"
    assert len(result.formal_mutations) == 3
    assert {item.operation for item in result.formal_mutations} == {
        "TRANSITION",
    }
    assert all(item.source_artifact_hash == hashlib.sha256(source).hexdigest()
               for item in result.formal_mutations)
    assert result.replay_counts["lost_before_v2"] == 0
    assert result.replay_counts["v2_eligible"] == 3
    assert result.replay_counts["legacy_accept_v2_reject"] == 0


def test_legacy_rejected_unit_remains_independently_v2_eligible(tmp_path) -> None:
    source, state, inventory = _eligible_fixture(
        tmp_path, legacy_accepted=False,
    )
    result = evaluate_short_canonical_gate(
        project_root=tmp_path, project_id="project-1",
        inventory=inventory, final_source_bytes=source,
        story_state_revision=4, story_state_data=state,
    )
    assert result.canonical_gate_result == "eligible"
    assert result.replay_counts["legacy_reject_v2_accept"] == 3


def test_normal_and_window_share_v2_evidence_identity_and_eligibility(
    tmp_path,
) -> None:
    results = []
    for source_mode in ("normal", "window"):
        source, state, inventory = _eligible_fixture(
            tmp_path / source_mode, source_mode=source_mode,
        )
        results.append(evaluate_short_canonical_gate(
            project_root=tmp_path / source_mode, project_id="project-1",
            inventory=inventory, final_source_bytes=source,
            story_state_revision=4, story_state_data=state,
        ))
    normal, window = results
    assert [item.grounding for item in normal.evidence] == [
        item.grounding for item in window.evidence
    ]
    assert [item.evidence_hash for item in normal.evidence] == [
        item.evidence_hash for item in window.evidence
    ]
    assert [item.slot_id for item in normal.phase1a_mutations] == [
        item.slot_id for item in window.phase1a_mutations
    ]
    assert [item.eligibility for item in normal.phase1a_mutations] == [
        item.eligibility for item in window.phase1a_mutations
    ]
    assert [item.operation for item in normal.formal_mutations] == [
        item.operation for item in window.formal_mutations
    ]


def test_stale_base_and_multiple_story_state_values_hold_batch(tmp_path) -> None:
    source, state, inventory = _eligible_fixture(tmp_path / "stale")
    stale = evaluate_short_canonical_gate(
        project_root=tmp_path / "stale", project_id="project-1",
        inventory=inventory, final_source_bytes=source,
        story_state_revision=5, story_state_data=state,
    )
    assert stale.canonical_gate_result == "hold"
    assert "stale_base_revision" in stale.canonical_hold_reasons
    assert not stale.formal_mutations

    source, state, inventory = _eligible_fixture(tmp_path / "multiple")
    state["confirmed_facts"] = [{
        "key": "Aster.location", "value": "West Hall",
    }]
    inventory = make_maintenance_inventory(
        source_mode="normal",
        source_artifact_hash=hashlib.sha256(source).hexdigest(),
        base_authority_revision=4,
        base_authority_hash=story_state_authority_hash(state),
        units=inventory.units,
    )
    multiple = evaluate_short_canonical_gate(
        project_root=tmp_path / "multiple", project_id="project-1",
        inventory=inventory, final_source_bytes=source,
        story_state_revision=4, story_state_data=state,
    )
    assert multiple.canonical_gate_result == "hold"
    assert "story_state_multiple_current_values" in (
        multiple.canonical_hold_reasons
    )
    assert not multiple.formal_mutations


def test_projection_mismatch_holds_operational_readiness_not_canonical_gate(
    tmp_path,
) -> None:
    source, state, inventory = _eligible_fixture(tmp_path)
    result = evaluate_short_canonical_gate(
        project_root=tmp_path, project_id="project-1",
        inventory=inventory, final_source_bytes=source,
        story_state_revision=4, story_state_data=state,
        projection_diagnostics=[{
            "projection": "canon_facts", "freshness": "stale",
            "source_authority_hash": "0" * 64,
        }],
    )
    assert result.canonical_gate_result == "eligible"
    assert result.canonical_hold_reasons == ()
    assert result.operational_readiness == "hold"
    assert result.operational_hold_reasons == (
        "projection_environment_unreconciled",
    )
    assert len(result.formal_mutations) == 3


def test_reserved_shape_or_source_hash_mismatch_holds_batch(tmp_path) -> None:
    _profiles(tmp_path)
    source = b"Aster arrived at North Gate."
    state = {"manuscript_revision": 0, "character_states": {"Aster": {}}}
    proposal = {"facts": [{
        "key": "Aster.location.current", "value": "North Gate",
        "evidence": "arrived at North Gate",
    }]}
    units = proposal_units_from_candidate(
        proposal, source_mode="normal", source_locator="reserved",
        source_attempt=1,
    )
    inventory = make_maintenance_inventory(
        source_mode="normal", source_artifact_hash="0" * 64,
        base_authority_revision=1,
        base_authority_hash=story_state_authority_hash(state), units=units,
    )
    result = evaluate_short_canonical_gate(
        project_root=tmp_path, project_id="project-1",
        inventory=inventory, final_source_bytes=source,
        story_state_revision=1, story_state_data=state,
    )
    assert result.canonical_gate_result == "hold"
    assert set(result.canonical_hold_reasons) == {
        "source_hash_mismatch", "unsupported_reserved_kind",
    }
    assert not result.formal_mutations
    decision = build_short_hold_decision(
        evaluation=result, inventory=inventory,
        candidate_hash=hashlib.sha256(source).hexdigest(),
    )
    assert decision.commit_performed is False
    assert decision.target_revision is None
    assert set(decision.hold_reasons) == {
        "source_hash_mismatch", "unsupported_reserved_kind",
    }


@pytest.mark.parametrize("semantic_domain", [
    "future_normative", "provider-specific-domain",
])
def test_non_current_semantic_domain_holds_entire_batch(
    tmp_path, semantic_domain,
) -> None:
    _profiles(tmp_path)
    source = b"Aster arrived at North Gate."
    state = {
        "manuscript_revision": 0,
        "character_states": {"Aster": {"location": "South Pier"}},
    }
    proposal = {"state_transitions": [{
        "character": "Aster", "field": "location",
        "from": "South Pier", "to": "North Gate",
        "evidence": "arrived at North Gate",
        "semantic_domain": semantic_domain,
    }]}
    units = proposal_units_from_candidate(
        proposal, source_mode="normal", source_locator="semantic-domain",
        source_attempt=1,
    )
    inventory = make_maintenance_inventory(
        source_mode="normal",
        source_artifact_hash=hashlib.sha256(source).hexdigest(),
        base_authority_revision=1,
        base_authority_hash=story_state_authority_hash(state), units=units,
    )
    result = evaluate_short_canonical_gate(
        project_root=tmp_path, project_id="project-1",
        inventory=inventory, final_source_bytes=source,
        story_state_revision=1, story_state_data=state,
    )
    assert result.canonical_gate_result == "hold"
    assert "unauthorized_semantic_domain" in result.canonical_hold_reasons
    assert not result.formal_mutations
    if semantic_domain == "future_normative":
        assert result.claims[0].semantic_domain == "future_normative"
    else:
        assert not result.claims


def test_formal_receipt_separates_story_time_and_source_hash(tmp_path) -> None:
    source, state, inventory = _eligible_fixture(tmp_path)
    result = evaluate_short_canonical_gate(
        project_root=tmp_path, project_id="project-1",
        inventory=inventory, final_source_bytes=source,
        story_state_revision=4, story_state_data=state,
    )
    receipt = build_short_commit_receipt(
        evaluation=result, target_revision=5,
        target_authority_hash="a" * 64,
        candidate_hash=hashlib.sha256(source).hexdigest(),
        writer_plan_hash="b" * 64,
        journal_frozen_input_hash="c" * 64,
        journal_saga_id="run-1",
    )
    assert receipt.story_time == result.story_time.story_time
    assert receipt.source_artifact_hash == hashlib.sha256(source).hexdigest()
    assert receipt.story_time != receipt.source_artifact_hash
    assert receipt.story_state_commit_count == 1
    assert receipt.commit_performed is True
    assert receipt.journal_saga_id == "run-1"
    assert receipt.rejected_mutation_ids == ()
    assert receipt.held_mutation_ids == ()


def test_writer_plan_applies_both_owners_to_base_once() -> None:
    base = {
        "character_states": {"Aster": {
            "location": "South Pier", "inventory": {"coins": 1},
        }},
        "world_rules": [],
    }
    legacy_target = {
        "character_states": {"Aster": {
            "location": "Legacy Wrong", "inventory": {"coins": 2},
        }},
        "world_rules": ["Doors require a seal."],
    }
    v2 = make_writer_patch(
        path="/character_states/Aster/location", operation="set",
        owner="canonical_v2", mutation_id="commit-mutation-0001",
        value="North Gate",
    )
    plan, target = build_short_writer_plan(
        base_state=base, legacy_target=legacy_target, v2_patches=[v2],
    )
    assert target["character_states"]["Aster"] == {
        "location": "North Gate", "inventory": {"coins": 2},
    }
    assert target["world_rules"] == ["Doors require a seal."]
    assert plan.unowned == plan.multi_owned == plan.parent_child_overlaps == 0
    owners = {item.path: item.owner for item in plan.patches}
    assert owners["/character_states/Aster/location"] == "canonical_v2"
    assert owners["/character_states/Aster/inventory/coins"] == "legacy"
    assert set(plan.actual_diff_paths) == set(owners)


@pytest.mark.parametrize("legacy_replacement", [
    {"character_states": {"Aster": "container replacement"}},
    {"character_states": {"Aster": {"location": {
        "nested": "overwrite",
    }}}},
])
def test_writer_plan_rejects_parent_or_nested_container_overwrite(
    legacy_replacement,
) -> None:
    base = {"character_states": {"Aster": {"location": "South Pier"}}}
    v2 = make_writer_patch(
        path="/character_states/Aster/location/value", operation="set",
        owner="canonical_v2", mutation_id="commit-mutation-0001",
        value="North Gate",
    )
    with pytest.raises(ValueError, match="overlapping ownership"):
        build_short_writer_plan(
            base_state=base, legacy_target=legacy_replacement,
            v2_patches=[v2],
        )


def test_writer_plan_rejects_two_v2_mutations_for_one_leaf() -> None:
    base = {"character_states": {"Aster": {"location": "South Pier"}}}
    patches = [
        make_writer_patch(
            path="/character_states/Aster/location", operation="set",
            owner="canonical_v2", mutation_id=f"commit-mutation-{index:04d}",
            value=value,
        )
        for index, value in enumerate(("North Gate", "West Hall"), 1)
    ]
    with pytest.raises(ValueError, match="overlapping ownership"):
        build_short_writer_plan(
            base_state=base, legacy_target=base, v2_patches=patches,
        )
