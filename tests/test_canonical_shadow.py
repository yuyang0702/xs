from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from novel_flywheel.canonical_shadow import (
    CanonicalMutationV1,
    EvidenceByteSpanV2,
    EvidenceEnvelopeV2,
    ProposedClaimBatchV2,
    ProposedClaimV2,
    ProjectionProvenanceV1,
    ShadowCanonicalCommitReceiptV1,
    build_entity_alias_index,
    build_evidence_envelope,
    build_shadow_mutation,
    build_shadow_receipt,
    canonical_sha256,
    claim_value_hash,
    entity_id,
    make_proposed_claim,
    resolve_shadow_slot,
    resolve_story_state_expected_current,
    stable_id,
    story_state_authority_hash,
)
from novel_flywheel.project_transactions import ProjectMutationJournalV1


H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64


def _claim_payload() -> dict:
    return {
        "schema": "ProposedClaimV2", "version": 2,
        "claim_kind": "character.location", "subject_id": "character:hero",
        "predicate": "location", "object_id": None,
        "knowledge_owner_id": None, "knowledge_topic_hash": None,
        "perspective": "objective_world", "semantic_domain": "occurred_current",
        "story_time": "chapter:32", "value_hash": H1,
        "source_artifact_hash": H2,
    }


def _claim() -> ProposedClaimV2:
    payload = _claim_payload()
    return ProposedClaimV2.model_validate({
        **payload,
        "claim_id": stable_id("claim", "ProposedClaimV2", payload),
    })


def test_canonical_hash_ignores_dict_order_and_volatile_ids() -> None:
    left = {"b": 2, "a": 1, "run_id": "one"}
    right = {"run_id": "two", "a": 1, "b": 2}
    assert canonical_sha256("ExampleV1", left) == canonical_sha256("ExampleV1", right)
    with pytest.raises((TypeError, ValueError)):
        canonical_sha256("ExampleV1", {"bad": object()})


def test_contract_ids_are_content_bound() -> None:
    claim = _claim()
    batch_payload = {
        "schema": "ProposedClaimBatchV2", "version": 2,
        "base_authority_revision": 4, "base_authority_hash": H2,
        "source_artifact_hash": H3, "coverage_mode": "complete_source",
        "claims": (claim.model_dump(mode="json", by_alias=True),),
    }
    batch = ProposedClaimBatchV2.model_validate({
        **batch_payload,
        "batch_id": stable_id("batch", "ProposedClaimBatchV2", batch_payload),
    })
    assert batch.claims == (claim,)
    with pytest.raises(ValidationError, match="claim_id"):
        ProposedClaimV2.model_validate({**_claim_payload(), "claim_id": "claim-stale"})


def test_evidence_contract_requires_one_exact_byte_span() -> None:
    span = EvidenceByteSpanV2(byte_start=3, byte_end=6, byte_sha256=H1)
    payload = {
        "schema": "EvidenceEnvelopeV2", "version": 2,
        "claim_id": _claim().claim_id, "source_artifact_hash": H2,
        "base_authority_revision": 4, "base_authority_hash": H3,
        "extractor_contract_version": "final-bytes-extractor-v1",
        "grounding": "exact", "spans": (span.model_dump(mode="json", by_alias=True),),
        "covered_ranges": ((0, 8),), "gaps": (), "candidate_slot_id": None,
        "ambiguous": False,
    }
    envelope = EvidenceEnvelopeV2.model_validate({
        **payload,
        "evidence_hash": canonical_sha256("EvidenceEnvelopeV2", payload),
    })
    assert envelope.spans[0].byte_start == 3
    with pytest.raises(ValidationError, match="exact grounding"):
        EvidenceEnvelopeV2.model_validate({
            **payload, "spans": (), "evidence_hash": canonical_sha256(
                "EvidenceEnvelopeV2", {**payload, "spans": ()},
            ),
        })


def test_shadow_receipt_cannot_claim_or_enter_project_commit() -> None:
    mutation_payload = {
        "schema": "CanonicalMutationV1", "version": 1,
        "operation": "ASSERT", "claim_id": _claim().claim_id,
        "evidence_hash": H1, "slot_id": "slot-" + "a" * 32,
        "competition_key": "compete-" + "b" * 32,
        "base_authority_revision": 4, "base_authority_hash": H2,
        "authority_slice_hash": None, "expected_current_hash": None,
        "proposed_value_hash": H3, "eligibility": "ineligible",
        "failure_codes": ("authority_slice_missing",), "shadow_only": True,
    }
    mutation = CanonicalMutationV1.model_validate({
        **mutation_payload,
        "mutation_id": stable_id("mutation", "CanonicalMutationV1", mutation_payload),
    })
    receipt_payload = {
        "schema": "ShadowCanonicalCommitReceiptV1", "version": 1,
        "mutation_id": mutation.mutation_id, "base_authority_revision": 4,
        "base_authority_hash": H2, "shadow_only": True,
        "commit_performed": False, "outcome": "shadow_not_committed",
        "target_revision": None, "target_authority_hash": None,
        "projection_effects": (), "legacy_comparison": "uncomparable",
    }
    receipt = ShadowCanonicalCommitReceiptV1.model_validate({
        **receipt_payload,
        "receipt_hash": canonical_sha256(
            "ShadowCanonicalCommitReceiptV1", receipt_payload,
        ),
    })
    assert receipt.commit_performed is False
    with pytest.raises(ValidationError):
        ProjectMutationJournalV1.model_validate({
            "version": 1, "status": "prepared", "operation": "test",
            "run_id": "run", "project_id": "project", "snapshot_path": "snapshots/a",
            "source_authority_sha256": H1, "expected_story_state_revision": 1,
            "managed_paths": ["memory/canon.json"],
            "memory_effects": [receipt.model_dump(mode="json", by_alias=True)],
        })


def test_projection_provenance_requires_revision_hash_commit_and_artifact() -> None:
    item = ProjectionProvenanceV1(
        source_authority_revision=3, source_authority_hash=H1,
        source_commit_id="commit-" + "a" * 32, source_artifact_hash=H2,
        projection_hash=H3, writer="long-chapter",
    )
    assert item.version == 1


def test_phase05_baseline_manifests_are_hash_only_and_committed() -> None:
    root = Path(__file__).parent / "fixtures" / "reliability" / "phase05"
    readiness = json.loads((root / "readiness-baseline-v1.json").read_text("utf-8"))
    parity = json.loads((root / "model-parity-baseline-v1.json").read_text("utf-8"))
    assert readiness["strict_xfail_count"] == 5
    assert parity["ordered_model_call_delta"] == 0
    serialized = json.dumps([readiness, parity], ensure_ascii=False).casefold()
    assert '"system":' not in serialized
    assert '"user":' not in serialized
    assert "c:\\" not in serialized


def test_alias_index_uses_explicit_aliases_and_preserves_collisions(tmp_path) -> None:
    characters = tmp_path / "characters"
    characters.mkdir()
    (characters / "hero.md").write_text(
        "---\nname: 柳春杏\naliases:\n  - 花穗\n---\n", encoding="utf-8",
    )
    index = build_entity_alias_index(tmp_path, {"character_states": {}})
    assert index.resolve(" 花穗 ") == (entity_id("柳春杏"), "exact")
    (characters / "other.md").write_text(
        "---\nname: 另一人\naliases: [花穗]\n---\n", encoding="utf-8",
    )
    collision = build_entity_alias_index(tmp_path, {"character_states": {}})
    assert collision.resolve("花穗") == (None, "ambiguous")
    assert collision.resolve("未声明别名") == (None, "unsupported")


def test_slot_identity_ignores_value_but_separates_kind_direction_and_domain() -> None:
    source = H2
    hero = entity_id("主角")
    friend = entity_id("同伴")
    shanghai = make_proposed_claim(
        claim_kind="character.location", subject_id=hero, predicate="location",
        perspective="objective_world", semantic_domain="occurred_current",
        story_time="chapter:32", value="上海", source_artifact_hash=source,
    )
    beijing = make_proposed_claim(
        claim_kind="character.location", subject_id=hero, predicate="location",
        perspective="objective_world", semantic_domain="occurred_current",
        story_time="chapter:32", value="北京", source_artifact_hash=source,
    )
    knowledge = make_proposed_claim(
        claim_kind="character.knowledge", subject_id=hero, predicate="knowledge",
        knowledge_owner_id=hero, knowledge_topic="密信内容",
        perspective="character_belief", semantic_domain="occurred_current",
        story_time="chapter:32", value=True, source_artifact_hash=source,
    )
    forward = make_proposed_claim(
        claim_kind="character.relationship", subject_id=hero, object_id=friend,
        predicate="trust", perspective="character_belief",
        semantic_domain="occurred_current", story_time="chapter:32",
        value="信任", source_artifact_hash=source,
    )
    reverse = make_proposed_claim(
        claim_kind="character.relationship", subject_id=friend, object_id=hero,
        predicate="trust", perspective="character_belief",
        semantic_domain="occurred_current", story_time="chapter:32",
        value="信任", source_artifact_hash=source,
    )
    future = make_proposed_claim(
        claim_kind="character.location", subject_id=hero, predicate="location",
        perspective="objective_world", semantic_domain="future_normative",
        story_time="chapter:32", value="北京", source_artifact_hash=source,
    )
    slots = [resolve_shadow_slot(item) for item in (
        shanghai, beijing, knowledge, forward, reverse, future,
    )]
    assert slots[0].slot_id == slots[1].slot_id
    assert len({item.slot_id for item in slots[1:]}) == 5


def test_evidence_uses_utf8_bytes_and_never_selects_first_duplicate() -> None:
    claim = make_proposed_claim(
        claim_kind="character.location", subject_id=entity_id("主角"),
        predicate="location", perspective="objective_world",
        semantic_domain="occurred_current", story_time="chapter:2", value="北京",
        source_artifact_hash=hashlib.sha256("甲到北京。".encode()).hexdigest(),
    )
    final = "甲到北京。".encode("utf-8")
    exact = build_evidence_envelope(
        claim, final_source_bytes=final,
        declared_source_artifact_hash=hashlib.sha256(final).hexdigest(),
        evidence_text="北京", base_authority_revision=3,
        base_authority_hash=H1, covered_ranges=((0, len(final)),),
    )
    assert exact.grounding == "exact"
    assert exact.spans[0].byte_start == len("甲到".encode("utf-8"))
    duplicate_bytes = "北京后又回北京".encode("utf-8")
    duplicate_claim = make_proposed_claim(
        claim_kind="character.location", subject_id=entity_id("主角"),
        predicate="location", perspective="objective_world",
        semantic_domain="occurred_current", story_time="chapter:3", value="北京",
        source_artifact_hash=hashlib.sha256(duplicate_bytes).hexdigest(),
    )
    ambiguous = build_evidence_envelope(
        duplicate_claim, final_source_bytes=duplicate_bytes,
        declared_source_artifact_hash=hashlib.sha256(duplicate_bytes).hexdigest(),
        evidence_text="北京", base_authority_revision=3,
        base_authority_hash=H1, covered_ranges=((0, len(duplicate_bytes)),),
    )
    assert ambiguous.grounding == "ambiguous"
    assert ambiguous.spans == ()


def test_expected_current_reads_only_exact_story_state_authority(tmp_path) -> None:
    state = {"character_states": {"主角": {"location": "上海"}}, "confirmed_facts": []}
    authority_hash = story_state_authority_hash(state)
    aliases = build_entity_alias_index(tmp_path, state)
    claim = make_proposed_claim(
        claim_kind="character.location", subject_id=entity_id("主角"),
        predicate="location", perspective="objective_world",
        semantic_domain="occurred_current", story_time="chapter:32", value="北京",
        source_artifact_hash=H2,
    )
    current = resolve_story_state_expected_current(
        state_data=state, actual_revision=7, actual_authority_hash=authority_hash,
        requested_revision=7, requested_authority_hash=authority_hash,
        claim=claim, aliases=aliases,
    )
    assert current["status"] == "exact"
    assert current["current_hash"] == claim_value_hash("上海")
    stale = resolve_story_state_expected_current(
        state_data=state, actual_revision=7, actual_authority_hash=authority_hash,
        requested_revision=7, requested_authority_hash=H3,
        claim=claim, aliases=aliases,
    )
    assert stale["status"] == "unavailable"
    assert "projection" not in resolve_story_state_expected_current.__annotations__


def test_mutation_eligibility_requires_story_state_current_and_exact_evidence(tmp_path) -> None:
    final = "主角从上海抵达北京。".encode("utf-8")
    state = {"character_states": {"主角": {"location": "上海"}}, "confirmed_facts": []}
    authority_hash = story_state_authority_hash(state)
    aliases = build_entity_alias_index(tmp_path, state)
    claim = make_proposed_claim(
        claim_kind="character.location", subject_id=entity_id("主角"),
        predicate="location", perspective="objective_world",
        semantic_domain="occurred_current", story_time="chapter:33", value="北京",
        source_artifact_hash=hashlib.sha256(final).hexdigest(),
    )
    evidence = build_evidence_envelope(
        claim, final_source_bytes=final,
        declared_source_artifact_hash=hashlib.sha256(final).hexdigest(),
        evidence_text="抵达北京", base_authority_revision=7,
        base_authority_hash=authority_hash, covered_ranges=((0, len(final)),),
    )
    mutation = build_shadow_mutation(
        operation="TRANSITION", claim=claim, evidence=evidence,
        slot=resolve_shadow_slot(claim), state_data=state, actual_revision=7,
        actual_authority_hash=authority_hash, aliases=aliases,
        requested_expected_current_hash=claim_value_hash("上海"),
    )
    assert mutation.eligibility == "eligible"
    assert mutation.expected_current_hash == claim_value_hash("上海")
    stale = build_shadow_mutation(
        operation="TRANSITION", claim=claim,
        evidence=evidence.model_copy(update={"base_authority_hash": H3}),
        slot=resolve_shadow_slot(claim), state_data=state, actual_revision=7,
        actual_authority_hash=authority_hash, aliases=aliases,
        requested_expected_current_hash=claim_value_hash("上海"),
    )
    assert stale.eligibility == "ineligible"
    assert "story_state_base_mismatch" in stale.failure_codes
    receipt = build_shadow_receipt(mutation, legacy_comparison="equivalent")
    assert receipt.outcome == "shadow_not_committed"


@pytest.mark.parametrize("operation", ["SUPERSEDE", "RETRACT"])
def test_explicit_current_operations_require_matching_story_state(
    tmp_path, operation,
) -> None:
    final = "主角公开离开上海。".encode("utf-8")
    state = {"character_states": {"主角": {"location": "上海"}}}
    authority_hash = story_state_authority_hash(state)
    aliases = build_entity_alias_index(tmp_path, state)
    claim = make_proposed_claim(
        claim_kind="character.location", subject_id=entity_id("主角"),
        predicate="location", perspective="objective_world",
        semantic_domain="occurred_current", story_time="chapter:34", value="离开",
        source_artifact_hash=hashlib.sha256(final).hexdigest(),
    )
    evidence = build_evidence_envelope(
        claim, final_source_bytes=final,
        declared_source_artifact_hash=hashlib.sha256(final).hexdigest(),
        evidence_text="离开上海", base_authority_revision=2,
        base_authority_hash=authority_hash, covered_ranges=((0, len(final)),),
    )
    mutation = build_shadow_mutation(
        operation=operation, claim=claim, evidence=evidence,
        slot=resolve_shadow_slot(claim), state_data=state, actual_revision=2,
        actual_authority_hash=authority_hash, aliases=aliases,
        requested_expected_current_hash=claim_value_hash("上海"),
    )
    assert mutation.eligibility == "eligible"


def test_assert_requires_known_absence_not_unknown_subject(tmp_path) -> None:
    final = "主角抵达上海。".encode("utf-8")
    state = {"character_states": {"主角": {"status": "active"}}}
    authority_hash = story_state_authority_hash(state)
    aliases = build_entity_alias_index(tmp_path, state)
    claim = make_proposed_claim(
        claim_kind="character.location", subject_id=entity_id("主角"),
        predicate="location", perspective="objective_world",
        semantic_domain="occurred_current", story_time="chapter:1", value="上海",
        source_artifact_hash=hashlib.sha256(final).hexdigest(),
    )
    evidence = build_evidence_envelope(
        claim, final_source_bytes=final,
        declared_source_artifact_hash=hashlib.sha256(final).hexdigest(),
        evidence_text="抵达上海", base_authority_revision=1,
        base_authority_hash=authority_hash, covered_ranges=((0, len(final)),),
    )
    eligible = build_shadow_mutation(
        operation="ASSERT", claim=claim, evidence=evidence,
        slot=resolve_shadow_slot(claim), state_data=state, actual_revision=1,
        actual_authority_hash=authority_hash, aliases=aliases,
    )
    assert eligible.eligibility == "eligible"
    unknown = {"character_states": {"另一人": {"location": "北京"}}}
    unknown_hash = story_state_authority_hash(unknown)
    unknown_aliases = build_entity_alias_index(tmp_path, unknown)
    blocked = build_shadow_mutation(
        operation="ASSERT", claim=claim,
        evidence=evidence.model_copy(update={"base_authority_hash": unknown_hash}),
        slot=resolve_shadow_slot(claim), state_data=unknown, actual_revision=1,
        actual_authority_hash=unknown_hash, aliases=unknown_aliases,
    )
    assert blocked.eligibility == "ineligible"
    assert "story_state_subject_unknown" in blocked.failure_codes
