from __future__ import annotations

import hashlib
import json

import pytest

from novel_flywheel.db import Database
from novel_flywheel.draft_split import DraftTaskContract
from novel_flywheel.execution_manifest import (
    AtomicBeat,
    SegmentBeatContract,
    ShortExecutionManifest,
    StateAssertion,
    execution_manifest_sha256,
)
from novel_flywheel.models import ModelResult
from novel_flywheel.planning_compiler import PlanningSegmentIR
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.prose_quality import (
    AuthorityTermProjectionFieldV1,
    AuthorityTermSourceArtifactV1,
    DraftProseAuthorityContextV1,
    analyze_prose,
    build_authority_approved_latin_term_set,
)
from novel_flywheel.skills import SkillGate, SkillScanner
from novel_flywheel.workflows import WorkflowService


REQUIRED_SKILLS = {
    "story-init", "plot-structure", "character-management", "worldbuilding",
    "chapter-writing", "novel-writing", "dialogue", "revision-continuity",
    "humanizer-zh", "story-maintenance",
}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _make_prompt_skills(root) -> None:
    for name in REQUIRED_SKILLS:
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\n---\n\nDeterministic test skill.",
            encoding="utf-8",
        )


def _semantic_receipt(contract: dict, prose: str) -> dict:
    evidence = prose[:12]
    order_evidence = prose if len(prose) <= 80 else prose[:80]
    return {
        "authority_sha256": contract["authority_sha256"],
        "execution_manifest_sha256": contract["execution_manifest_sha256"],
        "task_id": contract["task_id"],
        "prose_sha256": hashlib.sha256(prose.encode("utf-8")).hexdigest(),
        "beat_receipts": [{
            "beat_id": beat_id,
            "evidence": evidence,
            "actor_action_valid": True,
            "actor_action_evidence": evidence,
            "state_valid": True,
            "state_evidence": evidence,
            "scene_order_valid": True,
            "scene_order_evidence": order_evidence,
        } for beat_id in contract["beat_ids"]],
        "outside_beat_ids": [],
        "future_beat_ids": [],
        "entry": {"satisfied": True, "evidence": evidence},
        "exit": {"satisfied": True, "evidence": prose[-12:]},
        "causal_order_valid": True,
        "causal_order_evidence": order_evidence,
        "viewpoint_valid": True,
        "viewpoint_evidence": evidence,
        "summary": "本段权威、顺序和状态均已核对。",
    }


def _authority_context(
    term: str = "SignalKey",
    *,
    authority_sha256: str = "a" * 64,
) -> DraftProseAuthorityContextV1:
    source_hash = "c" * 64
    binding = "d" * 64
    source = AuthorityTermSourceArtifactV1(
        artifact_kind="planning_segment_ir",
        artifact_sha256=source_hash,
        contract="PlanningSegmentIR",
        version=1,
        authority_status="accepted_current",
    )
    term_set = build_authority_approved_latin_term_set(
        draft_authority_revision=1,
        draft_authority_sha256=authority_sha256,
        segment_binding_sha256=binding,
        source_artifacts=(source,),
        fields=(AuthorityTermProjectionFieldV1(
            source_artifact_sha256=source_hash,
            field_path="segments/1/event_body",
            value=f"当前事件正式要求保留{term}术语",
            segment_binding_sha256=binding,
        ),),
    )
    return DraftProseAuthorityContextV1(
        term_set=term_set,
        current_draft_authority_revision=1,
        current_draft_authority_sha256=authority_sha256,
        current_segment_binding_sha256=binding,
        current_source_artifact_sha256s=(source_hash,),
    )


def _manifest() -> tuple[ShortExecutionManifest, PlanningSegmentIR]:
    term = "SignalKey"
    beat_one = AtomicBeat(
        beat_id="EV-00000001/01",
        source_event_id="EV-00000001",
        order=1,
        action=f"主角核对{term}记录",
        preconditions=("记录尚未核对",),
        postconditions=(f"{term}记录完成核对",),
        owner_segment=1,
        source_evidence="Adapter RandomNoise explanatory text",
        actor="主角",
        location="档案室",
        knowledge_delta=(f"主角确认{term}编号",),
        relationship_delta=(),
    )
    beat_two = AtomicBeat(
        beat_id="EV-00000002/01",
        source_event_id="EV-00000002",
        order=2,
        action="另一段处理OtherTerm记录",
        preconditions=(),
        postconditions=(),
        owner_segment=2,
        source_evidence="",
    )
    manifest = ShortExecutionManifest(
        version=3,
        status="ready",
        authority_sha256="1" * 64,
        outline_sha256="2" * 64,
        planning_sha256="3" * 64,
        causal_chain_sha256="4" * 64,
        beats=(beat_one, beat_two),
        segments=(
            SegmentBeatContract(
                segment=1,
                beat_ids=(beat_one.beat_id,),
                entry_state=(StateAssertion("进入档案室"),),
                exit_state=(StateAssertion(f"{term}记录已核对"),),
                previous_exit_sha256="",
            ),
            SegmentBeatContract(
                segment=2,
                beat_ids=(beat_two.beat_id,),
                entry_state=(StateAssertion("承接上一段"),),
                exit_state=(StateAssertion("完成另一段"),),
                previous_exit_sha256="5" * 64,
            ),
        ),
        semantic_receipt={},
    )
    planning = PlanningSegmentIR(
        version=1,
        segment=1,
        heading="第一段",
        event_ids=("EV-00000001",),
        outline="核对记录",
        opening="主角进入档案室",
        event_body=f"主角必须核对{term}记录",
        handoff="记录核对完成",
        source_sha256="6" * 64,
    )
    return manifest, planning


def test_workflow_projection_uses_only_current_structured_segment_fields() -> None:
    manifest, planning = _manifest()
    manifest_hash = execution_manifest_sha256(manifest)
    context = WorkflowService._draft_prose_authority_context(
        planning_segment=planning,
        execution_manifest=manifest,
        execution_manifest_sha256_value=manifest_hash,
        segment_number=1,
        draft_authority_revision=9,
        draft_authority_sha256="a" * 64,
    )

    assert context is not None
    assert {
        item.artifact_kind for item in context.term_set.source_artifacts
    } == {"planning_segment_ir", "short_execution_manifest"}
    assert not [
        item for item in analyze_prose(
            "主角核对SignalKey记录。", authority_context=context,
        )["findings"] if item["blocking"]
    ]
    assert [
        item["code"] for item in analyze_prose(
            "主角核对OtherTerm记录。", authority_context=context,
        )["findings"] if item["blocking"]
    ] == ["mixed_script_corruption"]
    assert [
        item["code"] for item in analyze_prose(
            "主角记录RandomNoise解释。", authority_context=context,
        )["findings"] if item["blocking"]
    ] == ["mixed_script_corruption"]


def test_projection_fails_closed_for_manifest_or_segment_mismatch() -> None:
    manifest, planning = _manifest()

    assert WorkflowService._draft_prose_authority_context(
        planning_segment=planning,
        execution_manifest=manifest,
        execution_manifest_sha256_value="f" * 64,
        segment_number=1,
        draft_authority_revision=9,
        draft_authority_sha256="a" * 64,
    ) is None
    assert WorkflowService._draft_prose_authority_context(
        planning_segment=planning,
        execution_manifest=manifest,
        execution_manifest_sha256_value=execution_manifest_sha256(manifest),
        segment_number=2,
        draft_authority_revision=9,
        draft_authority_sha256="a" * 64,
    ) is None


class _DraftThenSemanticGateway:
    def __init__(self, prose: str, contract: DraftTaskContract):
        self.prose = prose
        self.contract = contract
        self.draft_calls = 0
        self.review_calls = 0
        self.calls: list[tuple[str, str, str, int | None]] = []

    async def complete_primary(
        self, role, system, user, max_output_tokens=None,
    ):
        self.calls.append((role, system, user, max_output_tokens))
        if role == "draft":
            self.draft_calls += 1
            return ModelResult(
                self.prose,
                {"model_name": "fake-draft", "finish_reason": "stop"},
            )
        if role == "review":
            self.review_calls += 1
            return ModelResult(
                json.dumps(
                    _semantic_receipt(
                        {
                            "authority_sha256": self.contract.authority_sha256,
                            "execution_manifest_sha256": (
                                self.contract.execution_manifest_sha256
                            ),
                            "task_id": self.contract.task_id,
                            "beat_ids": list(self.contract.beat_ids),
                        },
                        self.prose,
                    ),
                    ensure_ascii=False,
                ),
                {"model_name": "fake-review", "finish_reason": "stop"},
            )
        raise AssertionError(f"unexpected fake role: {role}")


def _service(tmp_path, gateway, run_id: str):
    db = Database(tmp_path / "d.db")
    db.migrate()
    store = ProjectStore(db, tmp_path / "w")
    project = store.create(ProjectCreate(
        title="A",
        mode="short",
        genre="suspense",
        premise="A record must be checked.",
        target_words=600,
    ))
    skill_root = tmp_path / "s"
    _make_prompt_skills(skill_root)
    service = WorkflowService(
        db, store, gateway, SkillGate(db, SkillScanner([skill_root])),
    )
    db.create_run(run_id, project.id, "short-story", status="running")
    run_path = project.path / "runs" / run_id
    (run_path / "outputs").mkdir(parents=True)
    (run_path / "outputs" / "conversion-audits").mkdir()
    (run_path / "receipts").mkdir()
    return db, project, service, run_path


@pytest.mark.asyncio
async def test_draft_crosses_prose_and_semantic_boundary_without_scope_retry(
    tmp_path,
) -> None:
    prose = (
        "她核对了SignalKey记录，确认编号、时间与签收栏保持一致。"
        "随后她逐项复查封条和登记页，把确认结果写入当日值守记录。"
    ) * 12
    contract = DraftTaskContract(
        authority_sha256="a" * 64,
        task_id="segment-01",
        parent_task_id="",
        depth=0,
        target_han=600,
        event_ids=("EV-00000001",),
        scope="只写核对记录",
        entry_state="记录尚未核对",
        exit_requirement="记录完成核对",
        execution_manifest_sha256="b" * 64,
        beat_ids=("EV-00000001/01",),
        viewpoint="third-limited",
    )
    gateway = _DraftThenSemanticGateway(prose, contract)
    db, project, service, run_path = _service(
        tmp_path, gateway, "d1x",
    )
    receipts: list[tuple[DraftTaskContract, dict]] = []

    result = await service._draft_short_segment_task(
        "d1x",
        run_path,
        project,
        "保持第三人称限知视角。",
        "当前段正式资料。",
        suffix="-part-01",
        target=600,
        previous_parts=[],
        event_ids=["EV-00000001/01"],
        contract=contract,
        semantic_all_event_ids=["EV-00000001/01"],
        semantic_receipt_sink=receipts,
        prose_authority_context=_authority_context(),
    )

    assert str(result) == prose
    assert gateway.draft_calls == 1
    assert gateway.review_calls == 1
    assert len(receipts) == 1
    events = db.list_run_events("d1x")
    assert not [
        event for event in events
        if event["event_type"] == "draft_task_scope_retry"
    ]
    validation = next(
        event for event in events
        if event["event_type"] == "draft_prose_validation_receipt"
    )
    assert validation["metadata"]["decision_counts"] == {
        "exempt_authority_approved_term": 12
    }
    assert "SignalKey" not in json.dumps(
        validation["metadata"], ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_diagnostic_sink_failure_does_not_reopen_retry_or_block_acceptance(
    tmp_path, monkeypatch,
) -> None:
    prose = "她核对了SignalKey记录，确认登记完整。" * 28
    contract = DraftTaskContract(
        authority_sha256="a" * 64,
        task_id="segment-01",
        parent_task_id="",
        depth=0,
        target_han=600,
        event_ids=("EV-00000001",),
        scope="只写核对记录",
        entry_state="记录尚未核对",
        exit_requirement="记录完成核对",
        execution_manifest_sha256="b" * 64,
        beat_ids=("EV-00000001/01",),
        viewpoint="third-limited",
    )
    gateway = _DraftThenSemanticGateway(prose, contract)
    db, project, service, run_path = _service(
        tmp_path, gateway, "d1s",
    )
    original = db.add_run_event

    def failing_receipt(run_id, level, event_type, message, **kwargs):
        if event_type == "draft_prose_validation_receipt":
            raise OSError("synthetic diagnostic sink failure")
        return original(run_id, level, event_type, message, **kwargs)

    monkeypatch.setattr(db, "add_run_event", failing_receipt)

    result = await service._draft_short_segment_task(
        "d1s",
        run_path,
        project,
        "保持第三人称限知视角。",
        "当前段正式资料。",
        suffix="-part-01",
        target=600,
        previous_parts=[],
        event_ids=["EV-00000001/01"],
        contract=contract,
        semantic_all_event_ids=["EV-00000001/01"],
        prose_authority_context=_authority_context(),
    )

    assert str(result) == prose
    assert gateway.draft_calls == gateway.review_calls == 1
    assert not [
        event for event in db.list_run_events("d1s")
        if event["event_type"] == "draft_task_scope_retry"
    ]


@pytest.mark.asyncio
async def test_authority_context_does_not_change_prompt_route_budget_or_call_count(
    tmp_path,
) -> None:
    prose = "她逐项核对登记记录，确认编号、时间与签收栏保持一致。" * 24
    contract = DraftTaskContract(
        authority_sha256="a" * 64,
        task_id="segment-01",
        parent_task_id="",
        depth=0,
        target_han=600,
        event_ids=("EV-00000001",),
        scope="只写核对记录",
        entry_state="记录尚未核对",
        exit_requirement="记录完成核对",
        execution_manifest_sha256="b" * 64,
        beat_ids=("EV-00000001/01",),
        viewpoint="third-limited",
    )
    with_context = _DraftThenSemanticGateway(prose, contract)
    db, project, service, first_path = _service(tmp_path, with_context, "d1p1")
    await service._draft_short_segment_task(
        "d1p1", first_path, project, "保持第三人称限知视角。",
        "当前段正式资料。", suffix="-part-01", target=600,
        previous_parts=[], event_ids=["EV-00000001/01"], contract=contract,
        semantic_all_event_ids=["EV-00000001/01"],
        prose_authority_context=_authority_context(),
    )

    without_context = _DraftThenSemanticGateway(prose, contract)
    service.gateway = without_context
    db.create_run("d1p2", project.id, "short-story", status="running")
    second_path = project.path / "runs" / "d1p2"
    (second_path / "outputs" / "conversion-audits").mkdir(parents=True)
    (second_path / "receipts").mkdir()
    await service._draft_short_segment_task(
        "d1p2", second_path, project, "保持第三人称限知视角。",
        "当前段正式资料。", suffix="-part-01", target=600,
        previous_parts=[], event_ids=["EV-00000001/01"], contract=contract,
        semantic_all_event_ids=["EV-00000001/01"],
        prose_authority_context=None,
    )

    assert with_context.calls == without_context.calls
    assert [item[0] for item in with_context.calls] == ["draft", "review"]
    assert with_context.draft_calls == with_context.review_calls == 1
    assert without_context.draft_calls == without_context.review_calls == 1
