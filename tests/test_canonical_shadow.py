from __future__ import annotations

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
    canonical_sha256,
    stable_id,
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
