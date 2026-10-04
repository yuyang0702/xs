import hashlib
from types import SimpleNamespace

import pytest

from novel_flywheel.draft_split import DraftTaskContract
from novel_flywheel.workflows import DraftReceiptProtocolError, WorkflowService


@pytest.mark.asyncio
@pytest.mark.parametrize("atomic", [False, True])
@pytest.mark.parametrize("item_count", [9, 11, 24, 25, 43])
async def test_receipt_windows_preserve_complete_order_and_original_hash(atomic, item_count):
    prose = "我把账册放在桌上，众人看见印章仍然完整。"
    ids = tuple(f"EV-00000001/{i:02d}" for i in range(1, item_count + 1))
    contract = DraftTaskContract(
        authority_sha256="a" * 64, task_id="segment-05", parent_task_id="",
        depth=0, target_han=100, event_ids=ids if not atomic else ("EV-00000001",),
        beat_ids=ids if atomic else (), scope="完整事件权威",
        entry_state="账册未打开", exit_requirement="印章完整",
    )
    seen = []
    events = []

    async def child(*args, **kwargs):
        child_contract = args[4]
        owned = child_contract.beat_ids or child_contract.event_ids
        seen.extend(owned)
        receipt = {
            "authority_sha256": child_contract.authority_sha256,
            "execution_manifest_sha256": child_contract.execution_manifest_sha256,
            "task_id": child_contract.task_id,
            "prose_sha256": hashlib.sha256(prose.encode()).hexdigest(),
            "entry": {"satisfied": True, "evidence": prose},
            "exit": {"satisfied": True, "evidence": prose},
            "causal_order_valid": True, "causal_order_evidence": prose,
            "summary": "完整核验",
        }
        if atomic:
            receipt.update(beat_receipts=[{
                "beat_id": identity, "evidence": prose,
                "actor_action_valid": True, "actor_action_evidence": prose,
                "state_valid": True, "state_evidence": prose,
                "scene_order_valid": True, "scene_order_evidence": prose,
            } for identity in owned], outside_beat_ids=[], future_beat_ids=[])
        else:
            receipt.update(event_receipts=[{
                "event_id": identity, "evidence": prose,
            } for identity in owned], outside_event_ids=[])
        return receipt

    service = SimpleNamespace(
        _verify_draft_semantic_node=child,
        db=SimpleNamespace(add_run_event=lambda *args, **kwargs: events.append(kwargs)),
    )
    result = await WorkflowService._verify_draft_semantic_node(
        service, "run", None, None, "authority", contract, prose, [], suffix="test",
    )
    assert seen == list(ids)
    field, identity = ("beat_receipts", "beat_id") if atomic else ("event_receipts", "event_id")
    assert [item[identity] for item in result[field]] == list(ids)
    assert result["task_id"] == "segment-05"
    assert result["prose_sha256"] == hashlib.sha256(prose.encode()).hexdigest()
    assert events[0]["metadata"]["window_count"] == (item_count + 7) // 8


@pytest.mark.asyncio
async def test_first_receipt_window_cannot_accept_the_root_segment():
    prose = "我把账册放在桌上，众人看见印章仍然完整。"
    ids = tuple(f"EV-00000001/{i:02d}" for i in range(1, 18))
    contract = DraftTaskContract(
        authority_sha256="a" * 64, task_id="segment-05", parent_task_id="",
        depth=0, target_han=100, event_ids=("EV-00000001",),
        beat_ids=ids, scope="完整事件权威", entry_state="账册未打开",
        exit_requirement="印章完整",
    )
    visited = []
    merged_events = []

    async def child(*args, **kwargs):
        child_contract = args[4]
        visited.append(child_contract.task_id)
        if len(visited) == 2:
            raise DraftReceiptProtocolError(
                child_contract.task_id,
                [{"code": "protocol_route_transport_interrupted"}],
            )
        return {
            "authority_sha256": child_contract.authority_sha256,
            "execution_manifest_sha256": child_contract.execution_manifest_sha256,
            "task_id": child_contract.task_id,
            "prose_sha256": hashlib.sha256(prose.encode()).hexdigest(),
            "beat_receipts": [{
                "beat_id": identity, "evidence": prose,
                "actor_action_valid": True, "actor_action_evidence": prose,
                "state_valid": True, "state_evidence": prose,
                "scene_order_valid": True, "scene_order_evidence": prose,
            } for identity in child_contract.beat_ids],
            "entry": {"satisfied": True, "evidence": prose},
            "exit": {"satisfied": True, "evidence": prose},
            "outside_beat_ids": [], "future_beat_ids": [],
            "viewpoint_valid": True, "viewpoint_evidence": prose,
            "causal_order_valid": True, "causal_order_evidence": prose,
            "summary": "当前窗口核验通过",
        }

    service = SimpleNamespace(
        _verify_draft_semantic_node=child,
        db=SimpleNamespace(
            add_run_event=lambda *args, **kwargs: merged_events.append(kwargs),
        ),
    )
    with pytest.raises(DraftReceiptProtocolError):
        await WorkflowService._verify_draft_semantic_node(
            service, "run", None, None, "authority", contract, prose, [],
            suffix="test",
        )

    assert visited == [
        "segment-05-receipt-window-01",
        "segment-05-receipt-window-02",
    ]
    assert merged_events == []
