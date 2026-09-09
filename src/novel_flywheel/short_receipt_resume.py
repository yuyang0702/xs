"""Native receipt-only recovery for an immutable Short Draft candidate."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from novel_flywheel.causal_chain import compact_causal_chain
from novel_flywheel.draft_split import DraftTaskContract
from novel_flywheel.execution_manifest import (
    extend_future_beat_guard,
    execution_manifest_sha256,
    parse_execution_manifest,
)
from novel_flywheel.narrative_contract import (
    ensure_narrative_contract,
    render_narrative_contract,
)
from novel_flywheel.planning_compiler import render_planning_segment_ir
from novel_flywheel.scene_continuity import build_location_catalog
from novel_flywheel.semantic_packets import canonical_sha256
from novel_flywheel.storage import atomic_write


SHA256_RE = re.compile(r"[0-9a-f]{64}")
TASK_RE = re.compile(r"segment-([0-9]{2})/sub-1")


@dataclass(frozen=True)
class PreparedShortReceiptResume:
    record: dict[str, Any]
    contract: DraftTaskContract
    prose: str
    outside_beat_ids: tuple[str, ...]
    run_path: Path
    candidate_path: Path
    state_path: Path
    constraints: str


def _narrative_fields(project: Any) -> dict[str, str]:
    contract = ensure_narrative_contract(project)
    return {
        "viewpoint": render_narrative_contract(contract),
        "narrative_mode": contract.mode,
        "narrator_character_id": contract.narrator_character_id,
        "narrator_name": contract.narrator_name,
        "self_reference": contract.self_reference,
    }


def _exact_candidate_path(run_path: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or relative.suffix.casefold() != ".md":
        raise ValueError("receipt recovery candidate must be a relative Markdown artifact")
    candidate = (run_path / relative).resolve()
    outputs = (run_path / "outputs").resolve()
    try:
        candidate.relative_to(outputs)
    except ValueError as exc:
        raise ValueError("receipt recovery candidate must remain inside run outputs") from exc
    if not candidate.is_file():
        raise ValueError("receipt recovery candidate does not exist")
    return candidate


def _latest_failed_receipt_event(
    service: Any, run_id: str, task_id: str, prose_sha256: str,
) -> dict[str, Any]:
    for event in reversed(service.db.list_run_events(run_id)):
        metadata = event.get("metadata") or {}
        if (
            event.get("event_type") == "semantic_receipt_protocol_exhausted"
            and metadata.get("task_id") == task_id
            and metadata.get("prose_sha256") == prose_sha256
        ):
            return event
    raise ValueError(
        "candidate is not bound to the latest native semantic-receipt boundary"
    )


def prepare_short_receipt_resume(
    service: Any,
    project: Any,
    *,
    run_id: str,
    candidate_relative_path: str,
    candidate_sha256: str,
    task_id: str,
    persist: bool,
) -> PreparedShortReceiptResume:
    """Rebuild the exact pending child contract without generating prose."""

    if SHA256_RE.fullmatch(candidate_sha256) is None:
        raise ValueError("candidate SHA-256 is invalid")
    match = TASK_RE.fullmatch(task_id)
    if match is None:
        raise ValueError("only an exact first-child Draft receipt can be resumed")
    run = service.db.get_run(run_id)
    if (
        run is None
        or run.get("project_id") != project.id
        or run.get("workflow") != "short-story"
        or run.get("status") not in {"failed", "running", "interrupted"}
    ):
        raise ValueError("receipt recovery run identity or state is invalid")

    run_path = project.path / "runs" / run_id
    candidate_path = _exact_candidate_path(run_path, candidate_relative_path)
    raw_bytes = candidate_path.read_bytes()
    prose = candidate_path.read_text(encoding="utf-8")
    prose_sha256 = hashlib.sha256(prose.encode("utf-8")).hexdigest()
    if prose_sha256 != candidate_sha256:
        raise ValueError("candidate content changed after selection")
    source_event = _latest_failed_receipt_event(
        service, run_id, task_id, prose_sha256,
    )

    target_words = int(project.metadata["target_words"])
    segment_count = service._short_segment_count(target_words)
    segment_number = int(match.group(1))
    if not 1 <= segment_number <= segment_count:
        raise ValueError("candidate task is outside the Short segment plan")
    target = math.ceil(target_words / segment_count)
    plan = (run_path / "outputs" / "planning.md").read_text(encoding="utf-8")
    planning_ir = service._require_short_planning_ir(
        run_path, plan, segment_count,
    )
    segment_plans = [
        render_planning_segment_ir(segment) for segment in planning_ir.segments
    ]
    manifest = parse_execution_manifest(json.loads(
        (run_path / "outputs" / "short-execution-index.json").read_text(
            encoding="utf-8"
        )
    ))
    causal_chain = json.loads(
        (run_path / "outputs" / "short-causal-chain.json").read_text(
            encoding="utf-8"
        )
    )
    service._validate_short_authority_graph(planning_ir, causal_chain, manifest)
    manifest_segments = {segment.segment: segment for segment in manifest.segments}
    manifest_segment = manifest_segments.get(segment_number)
    if manifest_segment is None:
        raise ValueError("candidate segment is missing from the execution manifest")
    beat_by_id = {beat.beat_id: beat for beat in manifest.beats}
    parent_beat_ids = list(manifest_segment.beat_ids)
    split_at = max(1, math.ceil(len(parent_beat_ids) / 2))
    first_beat_ids = parent_beat_ids[:split_at]
    second_beat_ids = parent_beat_ids[split_at:]
    if not first_beat_ids or not second_beat_ids:
        raise ValueError("candidate parent is not a valid two-child Draft split")

    state = service.story_states.ensure(project.id, project.path)
    story_state_sha256 = hashlib.sha256(json.dumps(
        state.data, ensure_ascii=False, sort_keys=True, default=str,
    ).encode("utf-8")).hexdigest()
    constraints = service.projects.load_constraints(project.id)
    constraints += (
        "\n\n# Short Story Causal Chain\n\n" + compact_causal_chain(causal_chain)
    )
    style_authority = json.loads(
        (run_path / "outputs" / "style-reference-authority-v1.json").read_text(
            encoding="utf-8"
        )
    )
    manifest_sha256 = execution_manifest_sha256(manifest)
    location_catalog = build_location_catalog(project.path, state.data)
    authority_payload = {
        "planning_ir_sha256": planning_ir.authority_sha256,
        "constraints": constraints,
        "target_words": target_words,
        "segment_count": segment_count,
        "story_state_sha256": story_state_sha256,
        "execution_manifest_sha256": manifest_sha256,
        "style_reference_authority_sha256": str(style_authority["authority_sha256"]),
    }
    authority_sha256 = hashlib.sha256(json.dumps({
        **authority_payload,
        "location_catalog": sorted(
            (alias, ref.name, ref.root) for alias, ref in location_catalog.items()
        ),
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    source_event_ids = tuple(dict.fromkeys(
        beat_by_id[beat_id].source_event_id for beat_id in first_beat_ids
    ))
    expected_entry = "；".join(
        assertion.state for assertion in manifest_segment.entry_state
    )
    previous_plan_tail = (
        service._short_plan_handoff(segment_plans[segment_number - 2])
        if segment_number > 1 else "这是开篇，无上一段交接状态。"
    )
    root_entry = (
        f"执行索引入口状态：\n{expected_entry}\n\n"
        f"上一段计划交接：\n{previous_plan_tail}\n\n"
        "上一段正文结尾：\n这是开篇，无上一段。"
    )
    child_scope_lines = [
        f"{beat_id}：{beat_by_id[beat_id].action}" for beat_id in first_beat_ids
    ]
    child_contract = DraftTaskContract(
        authority_sha256=authority_sha256,
        task_id=task_id,
        parent_task_id=f"segment-{segment_number:02d}",
        depth=1,
        target_han=max(400, target // 2),
        event_ids=source_event_ids,
        scope="内部子任务 1/2：只完成以下节拍\n" + "\n".join(child_scope_lines),
        entry_state=root_entry,
        exit_requirement=(
            "在当前事件范围结束处留下自然交接，不总结且不进入第二子任务事件"
        ),
        execution_manifest_sha256=manifest_sha256,
        beat_ids=tuple(first_beat_ids),
        **_narrative_fields(project),
        future_beat_guard=extend_future_beat_guard(
            manifest_segment.future_beat_guard,
            tuple(beat_by_id[beat_id] for beat_id in second_beat_ids),
        ),
    )
    all_beat_ids = tuple(
        beat_id
        for segment in manifest.segments
        for beat_id in segment.beat_ids
    )
    outside_beat_ids = tuple(
        beat_id for beat_id in all_beat_ids if beat_id not in first_beat_ids
    )
    record: dict[str, Any] = {
        "schema": "ShortDraftPendingSemanticReceiptV1",
        "version": 1,
        "status": "pending_semantic_receipt",
        "project_id": project.id,
        "run_id": run_id,
        "operation_kind": "semantic_receipt",
        "next_model_stage": "review",
        "next_contract_name": "draft_atomic_semantic_receipt",
        "candidate_relative_path": candidate_path.relative_to(run_path).as_posix(),
        "candidate_raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "candidate_prose_sha256": prose_sha256,
        "candidate_bytes": len(raw_bytes),
        "task_id": task_id,
        "draft_request_count": 0,
        "execution_manifest_sha256": manifest_sha256,
        "contract": asdict(child_contract),
        "source_event_id": int(source_event["id"]),
        "source_event_type": source_event["event_type"],
    }
    record["record_sha256"] = canonical_sha256(record)
    state_path = (
        run_path / "outputs" / "draft-pending-candidates"
        / f"{prose_sha256}.json"
    )
    if persist:
        atomic_write(
            state_path, json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2),
        )
    return PreparedShortReceiptResume(
        record=record,
        contract=child_contract,
        prose=prose,
        outside_beat_ids=outside_beat_ids,
        run_path=run_path,
        candidate_path=candidate_path,
        state_path=state_path,
        constraints=constraints,
    )


def persist_validated_receipt(
    prepared: PreparedShortReceiptResume, receipt: dict[str, Any],
) -> dict[str, Any]:
    current_raw_sha256 = hashlib.sha256(prepared.candidate_path.read_bytes()).hexdigest()
    current_prose_sha256 = hashlib.sha256(
        prepared.candidate_path.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()
    if (
        current_raw_sha256 != prepared.record["candidate_raw_sha256"]
        or current_prose_sha256 != prepared.record["candidate_prose_sha256"]
    ):
        raise RuntimeError("candidate changed while semantic receipt was executing")
    record = {
        **prepared.record,
        "status": "semantic_receipt_validated",
        "semantic_receipt": receipt,
        "semantic_receipt_sha256": canonical_sha256(receipt),
    }
    record.pop("record_sha256", None)
    record["record_sha256"] = canonical_sha256(record)
    atomic_write(
        prepared.state_path,
        json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2),
    )
    return record
