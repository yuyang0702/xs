from __future__ import annotations

import pytest

from novel_flywheel.draft_split import DraftTaskContract
from novel_flywheel.generated_root_authority import (
    build_generated_root_authority,
    canonical_sha256,
    normalize_generated_root_task_id,
    reconcile_generated_root_authority,
)
from novel_flywheel.short_receipt_resume import build_pending_recovery_authority


HASH = "a" * 64
RAW_HASH = "b" * 64
INPUT_HASH = "c" * 64
ROUTE_HASH = "d" * 64
REQUEST_HASH = "e" * 64


def _contract(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "authority_sha256": HASH,
        "execution_manifest_sha256": RAW_HASH,
        "event_ids": ["event-1"],
        "beat_ids": ["beat-1"],
    }
    value.update(overrides)
    return value


def _authority(**overrides: object):
    value: dict[str, object] = {
        "run_id": "run-1",
        "project_id": "project-1",
        "task_id": "segment-05/sub-1",
        "candidate_relative_path": "outputs/draft-part-05.md",
        "candidate_prose_sha256": HASH,
        "candidate_raw_sha256": RAW_HASH,
        "contract": _contract(),
        "repair_scope_task_id": "semantic_receipt",
        "checkpoint_input_sha256": INPUT_HASH,
        "route_identity_sha256": ROUTE_HASH,
        "request_condition_sha256": REQUEST_HASH,
        "state": "claimed",
    }
    value.update(overrides)
    return build_generated_root_authority(**value)


def _events() -> list[dict[str, object]]:
    return [
        {
            "id": 10,
            "event_type": "candidate_generated",
            "metadata": {
                "task_id": "segment-05",
                "candidate_relative_path": "outputs/draft-part-05.md",
                "candidate_prose_sha256": HASH,
            },
        },
        {
            "id": 11,
            "event_type": "semantic_receipt_protocol_exhausted",
            "metadata": {
                "task_id": "segment-05-receipt-window-01",
                "prose_sha256": HASH,
            },
        },
    ]


def test_task_id_normalization_accepts_root_child_and_receipt_window() -> None:
    assert normalize_generated_root_task_id("segment-05") == "segment-05"
    assert normalize_generated_root_task_id("segment-05/sub-1") == "segment-05"
    assert normalize_generated_root_task_id("segment-05-receipt-window-01") == "segment-05"
    with pytest.raises(ValueError):
        normalize_generated_root_task_id("segment-00/sub-1")
    with pytest.raises(ValueError):
        normalize_generated_root_task_id("segment-5/sub-1")


def test_authority_hash_is_stable_and_scope_is_bound() -> None:
    first = _authority()
    second = _authority()
    assert first.to_dict() == second.to_dict()
    assert first.scope_sha256 == canonical_sha256({
        "root_task_id": "segment-05",
        "observed_task_id": "segment-05/sub-1",
        "repair_scope_task_id": "semantic_receipt",
        "event_ids": ["event-1"],
        "beat_ids": ["beat-1"],
        "contract_authority_sha256": HASH,
        "execution_manifest_sha256": RAW_HASH,
    })


def test_reconciliation_accepts_matching_event_pair_checkpoint_and_route() -> None:
    result = reconcile_generated_root_authority(
        _authority(),
        filesystem_candidate_prose_sha256=HASH,
        events=_events(),
        checkpoints=[{"output_sha256": HASH, "input_sha256": INPUT_HASH}],
    )
    assert result.ok is True
    assert result.dispatch_ready is True
    assert result.candidate_event_ids == ("10",)
    assert result.exhaustion_event_ids == ("11",)
    assert result.matching_checkpoint_count == 1


def test_reconciliation_fails_closed_for_hash_event_and_duplicate_errors() -> None:
    result = reconcile_generated_root_authority(
        _authority(checkpoint_input_sha256=""),
        filesystem_candidate_prose_sha256=RAW_HASH,
        events=[_events()[0]],
        checkpoints=[{"output_sha256": HASH}, {"output_sha256": HASH}],
    )
    assert result.ok is False
    assert result.dispatch_ready is False
    assert {
        "candidate_filesystem_hash_mismatch",
        "missing_root_exhaustion_event",
        "duplicate_checkpoint_identity",
    }.issubset(result.issues)


def test_reconciliation_requires_dispatch_identity_and_validates_tamper() -> None:
    prepared = _authority(
        route_identity_sha256="", request_condition_sha256="", state="prepared",
    )
    result = reconcile_generated_root_authority(
        prepared,
        filesystem_candidate_prose_sha256=HASH,
        events=_events(),
        checkpoints=[{"output_sha256": HASH, "input_sha256": INPUT_HASH}],
    )
    assert "dispatch_route_or_request_identity_missing" in result.issues

    tampered = prepared.to_dict()
    tampered["candidate_relative_path"] = "outputs/other.md"
    result = reconcile_generated_root_authority(
        tampered,
        filesystem_candidate_prose_sha256=HASH,
        events=_events(),
        checkpoints=[{"output_sha256": HASH, "input_sha256": INPUT_HASH}],
    )
    assert result.ok is False
    assert "authority_sha256 does not match canonical payload" in result.issues

    schema_tampered = prepared.to_dict()
    schema_tampered["schema"] = "OtherSchema"
    result = reconcile_generated_root_authority(
        schema_tampered,
        filesystem_candidate_prose_sha256=HASH,
        events=_events(),
        checkpoints=[{"output_sha256": HASH, "input_sha256": INPUT_HASH}],
    )
    assert result.ok is False
    assert "unsupported generated-root authority schema" in result.issues

    scope_tampered = prepared.to_dict()
    scope_tampered["task_scope_kind"] = "root"
    result = reconcile_generated_root_authority(
        scope_tampered,
        filesystem_candidate_prose_sha256=HASH,
        events=_events(),
        checkpoints=[{"output_sha256": HASH, "input_sha256": INPUT_HASH}],
    )
    assert result.ok is False
    assert "task_scope_kind does not match observed_task_id" in result.issues


def test_pending_receipt_record_persists_authority_binding() -> None:
    contract = DraftTaskContract(
        authority_sha256=HASH,
        task_id="segment-05/sub-1",
        parent_task_id="segment-05",
        depth=1,
        target_han=400,
        event_ids=("event-1",),
        scope="owned child scope",
        entry_state="entry",
        exit_requirement="exit",
        execution_manifest_sha256=RAW_HASH,
        beat_ids=("beat-1",),
    )
    record = {
        "run_id": "run-1",
        "project_id": "project-1",
        "task_id": "segment-05/sub-1",
        "candidate_relative_path": "outputs/draft-part-05.md",
        "candidate_prose_sha256": HASH,
        "candidate_raw_sha256": RAW_HASH,
        "operation_kind": "semantic_receipt",
    }
    binding = build_pending_recovery_authority(record, contract)
    assert binding["schema"] == "GeneratedRootRecoveryAuthorityV1"
    assert binding["root_task_id"] == "segment-05"
    assert binding["task_scope_kind"] == "child"
    assert binding["authority_sha256"]
