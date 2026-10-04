from __future__ import annotations

import asyncio
import hashlib

import pytest

from novel_flywheel.db import Database
from novel_flywheel.draft_split import DraftTaskContract
from novel_flywheel.generated_root_authority import build_generated_root_authority
from novel_flywheel.generated_root_recovery import (
    GeneratedRootRecoveryOperation,
    GeneratedRootRecoveryRequest,
    GeneratedRootRecoveryValidationError,
    GeneratedRootSemanticValidation,
)
from novel_flywheel.tasks import RunTaskManager


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _setup(tmp_path, *, task_id: str = "segment-05"):
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("project-1", "Story", "short", tmp_path / "project")
    db.create_run("run-1", "project-1", "short-story", status="failed")
    prose = "�����ĸ�Ϊ�����⡣�������״̬�������������������ϡ�"
    raw = prose.encode("utf-8")
    candidate = tmp_path / "outputs" / "root.md"
    candidate.parent.mkdir()
    candidate.write_bytes(raw)
    prose_hash = _sha(prose)
    raw_hash = hashlib.sha256(raw).hexdigest()
    contract = DraftTaskContract(
        authority_sha256="a" * 64,
        task_id=task_id,
        parent_task_id="",
        depth=0,
        target_han=100,
        event_ids=("event-1",),
        scope="owned root scope",
        entry_state="entry",
        exit_requirement="exit",
        execution_manifest_sha256="b" * 64,
        beat_ids=("beat-1",),
    )
    authority = build_generated_root_authority(
        run_id="run-1", project_id="project-1", task_id=task_id,
        candidate_relative_path="outputs/root.md",
        candidate_prose_sha256=prose_hash,
        candidate_raw_sha256=raw_hash,
        contract={
            "authority_sha256": contract.authority_sha256,
            "execution_manifest_sha256": contract.execution_manifest_sha256,
            "event_ids": contract.event_ids,
            "beat_ids": contract.beat_ids,
        },
        repair_scope_task_id="root_semantic_receipt",
        checkpoint_input_sha256="c" * 64,
        route_identity_sha256="d" * 64,
        request_condition_sha256="e" * 64,
        state="claimed",
    ).to_dict()
    db.add_run_event(
        "run-1", "success", "candidate_generated", "candidate",
        metadata={
            "task_id": task_id,
            "candidate_relative_path": "outputs/root.md",
            "candidate_prose_sha256": prose_hash,
        },
    )
    db.add_run_event(
        "run-1", "error", "semantic_receipt_protocol_exhausted", "exhausted",
        metadata={"task_id": f"{task_id}-receipt-window-01", "prose_sha256": prose_hash},
    )
    request = GeneratedRootRecoveryRequest(
        run_id="run-1", project_id="project-1", task_id=task_id,
        candidate_relative_path="outputs/root.md",
        candidate_prose_sha256=prose_hash, candidate_raw_sha256=raw_hash,
        authority=authority, contract=contract,
        route_identity_sha256="d" * 64, request_condition_sha256="e" * 64,
        node_key="root-node", max_dispatches=2, max_dispatches_per_route=1,
    )

    def loader(_path: str):
        return prose, raw_hash, prose_hash

    return db, request, loader


@pytest.mark.asyncio
async def test_failed_run_reentry_saves_validated_checkpoint_and_releases_local_claim(tmp_path):
    db, request, loader = _setup(tmp_path)

    async def validate(_contract, _prose):
        return GeneratedRootSemanticValidation(
            receipt={"semantic": "validated"}, provider_call_executed=False,
        )

    operation = GeneratedRootRecoveryOperation(
        db, request, candidate_loader=loader, semantic_validator=validate,
    )
    result = await operation.execute("run-1")
    assert result.provider_call_executed is False
    assert result.released_attempts == (1,)
    assert result.checkpoint["status"] == "validated"
    checkpoint = db.load_unambiguous_workflow_node_checkpoint(
        run_id="run-1", node_key="root-node",
        authority_sha256=request.authority["authority_sha256"],
        output_sha256=request.candidate_prose_sha256,
    )
    assert checkpoint is not None
    assert checkpoint["next_node"] == "review"
    assert checkpoint["payload"]["task_id"] == "segment-05"
    assert db.list_workflow_attempts("run-1")[0]["state"] == "local_not_dispatched"


@pytest.mark.asyncio
async def test_hash_mismatch_and_task_scope_mismatch_fail_before_claim(tmp_path):
    db, request, loader = _setup(tmp_path)

    async def validate(_contract, _prose):
        return GeneratedRootSemanticValidation({}, False)

    bad_hash = GeneratedRootRecoveryOperation(
        db,
        GeneratedRootRecoveryRequest(
            **{**request.__dict__, "candidate_prose_sha256": "f" * 64},
        ),
        candidate_loader=loader,
        semantic_validator=validate,
    )
    with pytest.raises(ValueError, match="prose hash mismatch"):
        await bad_hash("run-1")
    assert db.list_workflow_attempts("run-1") == []

    authority = dict(request.authority)
    authority["observed_task_id"] = "segment-06"
    bad_scope = GeneratedRootRecoveryOperation(
        db,
        GeneratedRootRecoveryRequest(**{**request.__dict__, "authority": authority}),
        candidate_loader=loader,
        semantic_validator=validate,
    )
    with pytest.raises(ValueError, match="reconciliation failed"):
        await bad_scope("run-1")
    assert db.list_workflow_attempts("run-1") == []

    mismatch = GeneratedRootRecoveryOperation(
        db,
        GeneratedRootRecoveryRequest(
            **{**request.__dict__, "route_identity_sha256": "f" * 64},
        ),
        candidate_loader=loader,
        semantic_validator=validate,
    )
    with pytest.raises(ValueError, match="dispatch identity mismatch"):
        await mismatch("run-1")
    assert db.list_workflow_attempts("run-1") == []


@pytest.mark.asyncio
async def test_failed_semantic_validation_releases_only_explicit_local_claim(tmp_path):
    db, request, loader = _setup(tmp_path)

    async def validate(_contract, _prose):
        raise GeneratedRootRecoveryValidationError(
            "semantic rejection", provider_call_executed=False,
        )

    operation = GeneratedRootRecoveryOperation(
        db, request, candidate_loader=loader, semantic_validator=validate,
    )
    with pytest.raises(GeneratedRootRecoveryValidationError):
        await operation("run-1")
    attempt = db.list_workflow_attempts("run-1")[0]
    assert attempt["state"] == "local_not_dispatched"
    assert attempt["metadata"]["physical_dispatch_released"] is True


@pytest.mark.asyncio
async def test_operation_is_accepted_by_existing_run_task_resume_api(tmp_path):
    db, request, loader = _setup(tmp_path)

    async def validate(_contract, _prose):
        return GeneratedRootSemanticValidation({"semantic": "validated"}, False)

    operation = GeneratedRootRecoveryOperation(
        db, request, candidate_loader=loader, semantic_validator=validate,
    )
    manager = RunTaskManager(db)
    manager.resume("run-1", operation)
    task = manager.tasks["run-1"]
    await task
    await asyncio.sleep(0)
    assert db.get_run("run-1")["status"] == "completed"
    assert db.load_unambiguous_workflow_node_checkpoint(
        run_id="run-1", node_key="root-node",
        authority_sha256=request.authority["authority_sha256"],
        output_sha256=request.candidate_prose_sha256,
    ) is not None
