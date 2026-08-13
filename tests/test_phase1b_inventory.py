from __future__ import annotations

import hashlib
import json
from pathlib import Path

from novel_flywheel.canonical_shadow import story_state_authority_hash
from novel_flywheel.short_canonical_promotion import (
    classify_legacy_disposition,
    inventory_as_shadow_candidate,
    make_maintenance_inventory,
    predecision_replay_counts,
    proposal_units_from_candidate,
)


CORPUS = (
    Path(__file__).parent / "fixtures" / "canonical"
    / "phase1b-replay-corpus-v1.json"
)


def _samples() -> list[dict]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))["samples"]


def test_predecision_inventory_covers_every_structurally_valid_corpus_unit() -> None:
    for sample in _samples():
        source_hash = hashlib.sha256(sample["source"].encode("utf-8")).hexdigest()
        units = proposal_units_from_candidate(
            sample["proposal"], source_mode=sample["mode"],
            source_locator=sample["id"], source_attempt=1,
        )
        classified = classify_legacy_disposition(
            units, sample["proposal"] if sample["legacy"] == "accepted" else {
                "facts": [], "state": {}, "state_transitions": [],
                "world_rules": [], "timeline": [],
            },
        )
        inventory = make_maintenance_inventory(
            source_mode=sample["mode"], source_artifact_hash=source_hash,
            base_authority_revision=4,
            base_authority_hash=story_state_authority_hash(sample["state"]),
            units=classified,
        )
        counts = predecision_replay_counts(inventory)
        assert counts["proposal_total"] == len(units)
        assert counts["lost_before_v2"] == 0
        assert counts[
            "legacy_accepted" if sample["legacy"] == "accepted"
            else "legacy_rejected"
        ] == len(units)
        assert len(inventory_as_shadow_candidate(inventory)["facts"]) + len(
            inventory_as_shadow_candidate(inventory)["state_transitions"]
        ) == sum(
            item.category != "legacy_only" for item in inventory.units
        )


def test_normal_and_window_inventory_have_same_semantic_units() -> None:
    by_id = {sample["id"]: sample for sample in _samples()}
    for normal_id, normal in by_id.items():
        if not normal_id.startswith("normal-"):
            continue
        window = by_id[normal_id.replace("normal-", "window-", 1)]
        normal_units = proposal_units_from_candidate(
            normal["proposal"], source_mode="normal",
            source_locator="normal", source_attempt=1,
        )
        window_units = proposal_units_from_candidate(
            window["proposal"], source_mode="window",
            source_locator="window", source_attempt=1,
        )
        normal_semantics = {
            (item.shape, item.category, item.raw_key, item.payload_hash)
            for item in normal_units
        }
        window_semantics = {
            (item.shape, item.category, item.raw_key, item.payload_hash)
            for item in window_units
        }
        assert normal_semantics == window_semantics


def test_legacy_rejection_is_annotation_not_v2_filter() -> None:
    sample = next(
        item for item in _samples() if item["id"] == "normal-evidence-missing"
    )
    units = proposal_units_from_candidate(
        sample["proposal"], source_mode="normal",
        source_locator="raw-before-legacy", source_attempt=1,
    )
    classified = classify_legacy_disposition(units, {"facts": []})
    assert len(classified) == len(units) == 1
    assert classified[0].legacy_disposition == "legacy_rejected"
    inventory = make_maintenance_inventory(
        source_mode="normal",
        source_artifact_hash=hashlib.sha256(
            sample["source"].encode("utf-8")
        ).hexdigest(),
        base_authority_revision=1,
        base_authority_hash=story_state_authority_hash(sample["state"]),
        units=classified,
    )
    assert inventory_as_shadow_candidate(inventory)["facts"]
    assert inventory.lost_before_v2 == 0


def test_legacy_text_facts_are_counted_before_v2_without_becoming_reserved() -> None:
    proposal = {"facts": ["  first durable fact  ", "second durable fact"]}
    units = proposal_units_from_candidate(
        proposal, source_mode="normal", source_locator="legacy-text",
        source_attempt=1,
    )
    assert len(units) == 2
    assert {item.category for item in units} == {"legacy_only"}
    assert {item.value for item in units} == {
        "first durable fact", "second durable fact",
    }
    assert all(item.raw_key.startswith("maintenance.") for item in units)
    classified = classify_legacy_disposition(units, proposal)
    assert all(
        item.legacy_disposition == "legacy_accepted" for item in classified
    )
    inventory = make_maintenance_inventory(
        source_mode="normal", source_artifact_hash="a" * 64,
        base_authority_revision=1, base_authority_hash="b" * 64,
        units=classified,
    )
    assert predecision_replay_counts(inventory) == {
        "proposal_total": 2, "legacy_accepted": 2,
        "legacy_rejected": 0, "lost_before_v2": 0,
    }


def test_private_snapshot_isomorphic_legacy_normal_topology_is_lossless() -> None:
    fixture = json.loads((
        Path(__file__).parent / "fixtures" / "canonical"
        / "phase1b-legacy-normal-isomorphic-v1.json"
    ).read_text(encoding="utf-8"))
    units = proposal_units_from_candidate(
        {"facts": fixture["facts"]}, source_mode="normal",
        source_locator="sanitized-private-isomorph", source_attempt=1,
    )
    inventory = make_maintenance_inventory(
        source_mode="normal", source_artifact_hash="a" * 64,
        base_authority_revision=2, base_authority_hash="b" * 64,
        units=classify_legacy_disposition(
            units, {"facts": fixture["facts"]},
        ),
    )
    assert len(units) == fixture["expected"]["proposal_total"]
    assert sum(item.category == "legacy_only" for item in units) == (
        fixture["expected"]["legacy_only"]
    )
    assert inventory.lost_before_v2 == fixture["expected"][
        "lost_before_v2"
    ]
