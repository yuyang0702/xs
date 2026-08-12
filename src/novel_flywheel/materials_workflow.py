from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from novel_flywheel.failure_boundary import safe_persistence_error
from novel_flywheel.material_audit_authority import (
    build_material_audit_packets,
    build_material_reference_authority,
    material_audit_checkpoint_payload,
    merge_material_audit_receipts,
    validate_material_audit_checkpoint,
)
from novel_flywheel.project_transactions import canonical_json_sha256
from novel_flywheel.quality import normalize_review, quality_outcome, review_windows
from novel_flywheel.storage import atomic_write


def _workflow_failure(exc: BaseException) -> str:
    return safe_persistence_error(
        exc,
        boundary="workflow.failed",
        code="workflow.execution_failed",
        family="runtime.workflow_failure",
        message="工作流未完成，已保留可恢复进度。",
        retryable=True,
        recovery_action="resume_from_checkpoint",
    )


async def run_materials_audit(
    service: Any, project: Any, run_id: str | None = None,
) -> dict:
    """Coordinate the material audit without owning its domain validators."""

    run_id, run_path = service._begin_run(project, "materials-audit", run_id)
    try:
        manuscript = service._material_manuscript(project)
        if not manuscript.strip():
            raise RuntimeError("No manuscript is available for conflict checking")
        constraints = service.projects.load_constraints(project.id)
        packet_target = service._material_audit_packet_target()
        reference = build_material_reference_authority(
            project.path, target_characters=packet_target,
        )
        windows = review_windows(
            manuscript,
            target=packet_target,
            overlap=min(400, max(0, packet_target // 8)),
        )
        packets = build_material_audit_packets(reference, manuscript, windows)
        receipts = []
        fallback_circuit_open = any(
            event["event_type"] == "materials_audit_circuit_opened"
            for event in service.db.list_run_events(run_id)
        )
        for packet in packets:
            manuscript_text = manuscript[
                packet.manuscript_start:packet.manuscript_end
            ]
            reference_text = reference.text_for(packet.reference_chunk)
            node_key = f"materials-audit-packet-{packet.sequence:06d}"
            checkpoint = service.db.load_workflow_node_checkpoint(
                run_id=run_id,
                node_key=node_key,
                authority_sha256=packet.reference_authority_sha256,
                input_sha256=packet.packet_id,
                min_validation_stage="local_semantics",
            )
            cached_receipt = validate_material_audit_checkpoint(
                checkpoint.get("payload") if checkpoint else None,
                packet,
                manuscript_text=manuscript_text,
            )
            if cached_receipt is not None:
                receipts.append(cached_receipt)
                service.db.add_run_event(
                    run_id,
                    "success",
                    "materials_audit_checkpoint_reused",
                    "材料审核已从语义检查点恢复一个完整的正文窗口/资料分片。",
                    stage="final_review",
                    metadata={
                        "packet": packet.sequence,
                        "window": packet.manuscript_window_index,
                    },
                )
                continue
            packet_receipt, used_fallback, route_fingerprint = (
                await service._material_audit_packet_receipt(
                    run_id,
                    run_path,
                    project,
                    constraints,
                    packet,
                    manuscript_text=manuscript_text,
                    reference_text=reference_text,
                    fallback_circuit_open=fallback_circuit_open,
                )
            )
            if not fallback_circuit_open and used_fallback:
                fallback_circuit_open = True
                service.db.add_run_event(
                    run_id,
                    "warning",
                    "materials_audit_circuit_opened",
                    "材料审核首选路由已回退成功，后续资料分片直接使用配置备用路由。",
                    stage="final_review",
                    metadata={
                        "packet": packet.sequence,
                        "window": packet.manuscript_window_index,
                    },
                )
            receipts.append(packet_receipt)
            checkpoint_payload = material_audit_checkpoint_payload(
                packet, packet_receipt,
            )
            service.db.save_workflow_node_checkpoint(
                run_id=run_id,
                node_key=node_key,
                authority_sha256=packet.reference_authority_sha256,
                input_sha256=packet.packet_id,
                output_sha256=canonical_json_sha256(packet_receipt),
                status="validated",
                validation_stage="local_semantics",
                route_fingerprint=route_fingerprint,
                payload=checkpoint_payload,
            )
        issues = merge_material_audit_receipts(receipts)
        report = {
            "project_id": project.id,
            "issues": issues,
            "count": len(issues),
        }
        service._commit_material_audit_report(
            project,
            run_id,
            run_path,
            report=report,
            issues=issues,
            source_authority_sha256=canonical_json_sha256({
                "version": 1,
                "manuscript_sha256": hashlib.sha256(
                    manuscript.encode("utf-8")
                ).hexdigest(),
                "reference_authority_sha256": (
                    reference.authority.authority_sha256
                ),
                "packet_ids": [packet.packet_id for packet in packets],
                "report_sha256": canonical_json_sha256(report),
            }),
        )
        return service.db.get_run(run_id) or {
            "id": run_id,
            "status": "completed",
        }
    except asyncio.CancelledError:
        service.db.update_run(run_id, "cancelled", error="Cancelled by user")
        raise
    except Exception as exc:
        recovery_pending = service._project_mutation_recovery_pending(
            project, run_id,
        )
        current_run = service.db.get_run(run_id)
        if (
            not recovery_pending
            and (current_run is None or current_run.get("status") != "failed")
        ):
            service.db.update_run(run_id, "failed", error=_workflow_failure(exc))
        raise


async def run_materials_repair(
    service: Any, project: Any, run_id: str | None = None,
) -> dict:
    """Coordinate material repair through the existing prose and quality gates."""

    run_id, run_path = service._begin_run(project, "materials-repair", run_id)
    try:
        audit = next((
            item
            for item in service.db.list_runs(project.id)
            if item["workflow"] == "materials-audit"
            and item["status"] == "completed"
        ), None)
        if not audit:
            raise RuntimeError("Run a material conflict audit before repair")
        report_path = (
            project.path / "runs" / audit["id"] / "outputs"
            / "conflict-report.json"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        issues = report.get("issues", [])
        if not issues:
            raise RuntimeError("The latest material audit has no conflicts to repair")
        manuscript = service._material_manuscript(project)
        constraints = service.projects.load_constraints(project.id)
        repaired = await service._polish_short_segments(
            run_id,
            run_path,
            project,
            constraints,
            manuscript,
            json.dumps({"material_conflicts": issues}, ensure_ascii=False),
            suffix="-materials",
            structural=True,
        )
        initial = normalize_review({
            "score": 80,
            "dimensions": {"commercial": 80, "story": 80, "prose": 80},
            "hard_fail": False,
            "decision": "revise",
            "issues": issues,
        })
        final, evidence = await service._full_manuscript_review(
            run_id,
            run_path,
            project,
            constraints,
            repaired,
            initial,
            suffix="-materials",
        )
        outcome, reasons = quality_outcome(final)
        atomic_write(run_path / "outputs" / "best-candidate.md", repaired)
        atomic_write(
            run_path / "outputs" / "quality-report.json",
            json.dumps({
                "status": outcome,
                "failure_reasons": reasons,
                "final_review": final,
                "final_review_evidence": evidence,
                "source_audit": audit["id"],
            }, ensure_ascii=False, indent=2),
        )
        if outcome == "failed":
            raise RuntimeError(
                "Material conflict repair did not pass the final quality gate"
            )
        service.db.update_run(run_id, "completed", "archive")
        return service.db.get_run(run_id) or {
            "id": run_id,
            "status": "completed",
        }
    except asyncio.CancelledError:
        service.db.update_run(run_id, "cancelled", error="Cancelled by user")
        raise
    except Exception as exc:
        service.db.update_run(run_id, "failed", error=_workflow_failure(exc))
        raise
