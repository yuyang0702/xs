from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from novel_flywheel.db import WIZARD_MUTATION_LOCK
from novel_flywheel.failure_boundary import safe_persistence_error
from novel_flywheel.manuscript_analysis import compact_analysis
from novel_flywheel.project_transactions import (
    ProjectMutationCanonFactV1,
    ProjectMutationChapterIndexV1,
    ProjectMutationChapterStateV1,
    ProjectMutationJournalV1,
    ProjectMutationPostCommitGateV1,
    abort_project_mutation_request,
    canonical_json_sha256,
    commit_project_mutation_authority,
    complete_project_mutation,
    finalize_project_mutation,
    project_mutation_journal_path,
    stage_project_mutation_targets,
    write_project_mutation_journal,
)
from novel_flywheel.storage import ProjectSnapshot, atomic_write


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


async def run_long_setup(
    service: Any, project: Any, run_id: str | None = None,
) -> dict:
    run_id, run_path = service._begin_run(project, "long-setup", run_id)
    outline_path = project.path / "memory" / "book-plan.md"
    canon_path = project.path / "memory" / "canon.json"
    volumes_path = project.path / "memory" / "volumes.json"
    try:
        constraints = service.projects.load_constraints(project.id)
        brief = (
            "Expand the immutable confirmed outline into a complete long-form execution plan with "
            "fixed ending, protagonist arc, act structure, "
            "3-5 volumes, chapter map, hooks, foreshadowing, characters, relationships, world rules, "
            "timeline and knowledge boundaries. Do not replace or contradict the confirmed outline.\n\n" +
            json.dumps(project.metadata, ensure_ascii=False, indent=2)
        )
        outline = await service._stage(run_id, run_path, project, "planning", constraints, brief)
        review = service._review(await service._stage(
            run_id, run_path, project, "review", constraints, outline,
        ))
        if review["score"] < 80 or review["hard_fail"]:
            raise RuntimeError("Book setup review did not pass")
        canon = service._convert_generated_object(
            await service._stage(
                run_id, run_path, project, "maintenance", constraints, outline,
            ),
            run_path, contract_name="long_setup_maintenance",
        )
        if not isinstance(canon.get("facts"), list):
            raise ValueError("Maintenance output must contain a facts array")
        target_text = {
            outline_path: outline,
            canon_path: json.dumps(canon, ensure_ascii=False, indent=2),
        }
        if isinstance(canon.get("volumes"), list):
            target_text[volumes_path] = json.dumps(
                {"volumes": canon["volumes"]},
                ensure_ascii=False, indent=2,
            )
        memory_effects = []
        seen_fact_keys = set()
        for index, fact in enumerate(canon["facts"]):
            if isinstance(fact, dict):
                key = str(fact.get("fact_key") or f"setup.{index}")
                value = str(fact.get("value") or fact.get("fact") or "")
                if key in seen_fact_keys:
                    continue
                seen_fact_keys.add(key)
                memory_effects.append(ProjectMutationCanonFactV1(
                    fact_key=key, value=value, confirmed=True,
                    source="book-setup", preserve_existing=True,
                ))
        with WIZARD_MUTATION_LOCK:
            state = service.story_states.ensure(project.id, project.path)
            managed_paths = list(target_text)
            snapshot_root = (
                project.path / "snapshots" / f"{run_id}-long-setup"
            )
            snapshot = ProjectSnapshot.create(
                project.path, snapshot_root, managed_paths,
            )
            journal_path = project_mutation_journal_path(
                project.path, run_id,
            )
            journal = ProjectMutationJournalV1(
                status="prepared", operation="long-setup",
                run_id=run_id, project_id=project.id,
                snapshot_path=snapshot_root.relative_to(
                    project.path,
                ).as_posix(),
                source_authority_sha256=canonical_json_sha256({
                    "version": 1,
                    "outline_sha256": hashlib.sha256(
                        outline.encode("utf-8")
                    ).hexdigest(),
                    "canon_sha256": canonical_json_sha256(canon),
                    "managed_paths": [
                        path.relative_to(project.path).as_posix()
                        for path in managed_paths
                    ],
                    "base_story_state_revision": state.revision,
                }),
                expected_story_state_revision=state.revision,
                managed_paths=tuple(
                    path.relative_to(project.path).as_posix()
                    for path in managed_paths
                ),
                memory_effects=tuple(memory_effects),
            )
            write_project_mutation_journal(journal_path, journal)
            try:
                for path, content in target_text.items():
                    atomic_write(path, content)
                service._post_write_maintenance(run_id, project)
                artifacts = stage_project_mutation_targets(
                    project.path, snapshot, managed_paths,
                )
                journal = ProjectMutationJournalV1.model_validate(
                    journal.model_copy(update={
                        "status": "artifacts_committed",
                        "artifacts": artifacts,
                    }).model_dump(mode="python"),
                )
                write_project_mutation_journal(journal_path, journal)
                complete_project_mutation(service.projects, run_id)
            except Exception:
                abort_project_mutation_request(
                    service.projects, run_id, snapshot,
                    journal_path, journal,
                    error=(
                        "Long setup authority commit failed and was "
                        "rolled back."
                    ),
                )
                raise
        return service.db.get_run(run_id) or {"id": run_id, "status": "completed"}
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



async def run_chapter(
    service: Any, project: Any, chapter_goal: str,
    run_id: str | None = None,
) -> dict:
    run_id, run_path = service._begin_run(project, "long-chapter", run_id)
    resumed = await service._resume_long_chapter_publication(
        project, run_id, run_path,
    )
    if resumed is not None:
        return resumed
    numbers = [
        int(match.group(1)) for path in project.path.joinpath("chapters").glob("chapter-*.md")
        if (match := re.fullmatch(r"chapter-(\d+)\.md", path.name))
    ]
    chapter_number = max(numbers, default=0) + 1
    chapter_id = f"chapter-{chapter_number:02d}"
    chapter_path = project.path / "chapters" / f"{chapter_id}.md"
    canon_path = project.path / "memory" / "canon.json"
    voice_path = (
        project.path / "memory" / "style-metrics"
        / f"chapter-{chapter_number:02d}.json"
    )
    service._ensure_previous_volume_passed(project, chapter_number)
    snapshot_root = (
        project.path / "snapshots"
        / f"{run_id}-long-chapter-{uuid.uuid4().hex[:8]}"
    )
    snapshot = ProjectSnapshot.create(
        project.path, snapshot_root,
        [chapter_path, canon_path, voice_path],
    )
    committed = False
    journal_path: Path | None = None
    journal: ProjectMutationJournalV1 | None = None
    try:
        constraints = service.projects.load_constraints(project.id)
        context = service.memory.context(project.id, chapter_goal)
        brief = json.dumps({
            "chapter_number": chapter_number,
            "goal": chapter_goal,
            "project": project.metadata,
            "retrieved_memory": context,
        }, ensure_ascii=False, indent=2)
        plan = await service._stage(run_id, run_path, project, "planning", constraints, brief)
        draft = await service._stage(run_id, run_path, project, "draft", constraints, plan)
        draft_analysis = service._analyze_manuscript(draft, run_path, project, "draft")
        review = service._review(await service._stage(
            run_id, run_path, project, "review", constraints,
            f"MEMORY:\n{json.dumps(context, ensure_ascii=False)}\n\nDRAFT:\n{draft}\n\n"
            "LOCAL FULL MANUSCRIPT SUMMARY:\n"
            f"{json.dumps(compact_analysis(draft_analysis), ensure_ascii=False)}",
        ))
        polished, _ = await service._quality_polish(
            run_id, run_path, project, constraints, draft, review,
            chapter_number=chapter_number,
            chapter_goal=chapter_goal,
            volume_end=service._is_volume_end(project, chapter_number),
        )
        canon = service._convert_generated_object(
            await service._stage(
                run_id, run_path, project, "maintenance", constraints, polished,
            ),
            run_path, contract_name="long_chapter_maintenance",
        )
        if not isinstance(canon.get("facts"), list):
            raise ValueError("Maintenance output must contain a facts array")
        chapter_text = service._chapter_file(
            project, polished, chapter_number,
        )
        canon_text = json.dumps(canon, ensure_ascii=False, indent=2)
        memory_effects = [ProjectMutationChapterIndexV1(
            chapter_id=chapter_id,
            chapter_number=chapter_number,
            content=polished,
            content_sha256=hashlib.sha256(
                polished.encode("utf-8")
            ).hexdigest(),
            summary=chapter_goal,
        )]
        if isinstance(canon.get("state"), dict):
            memory_effects.append(ProjectMutationChapterStateV1(
                chapter_id=chapter_id,
                state=canon["state"],
                state_sha256=canonical_json_sha256(canon["state"]),
            ))
        state = service.story_states.ensure(project.id, project.path)
        volume = service._volume_for_chapter(project, chapter_number)
        post_commit_gate = None
        if (
            volume is not None
            and chapter_number == int(volume.get("end_chapter", -1))
        ):
            gate_payload = {
                "chapter_number": chapter_number,
                "volume_number": int(volume["number"]),
            }
            post_commit_gate = ProjectMutationPostCommitGateV1(
                name="volume_audit",
                payload=gate_payload,
                payload_sha256=canonical_json_sha256(gate_payload),
            )
        managed_paths = [chapter_path, canon_path, voice_path]
        journal_path = project_mutation_journal_path(
            project.path, run_id,
        )
        journal = ProjectMutationJournalV1(
            status="prepared", operation="long-chapter",
            run_id=run_id, project_id=project.id,
            snapshot_path=snapshot_root.relative_to(
                project.path,
            ).as_posix(),
            source_authority_sha256=canonical_json_sha256({
                "version": 1,
                "chapter_number": chapter_number,
                "chapter_sha256": hashlib.sha256(
                    chapter_text.encode("utf-8")
                ).hexdigest(),
                "canon_sha256": hashlib.sha256(
                    canon_text.encode("utf-8")
                ).hexdigest(),
                "chapter_memory_sha256": hashlib.sha256(
                    polished.encode("utf-8")
                ).hexdigest(),
                "chapter_goal_sha256": hashlib.sha256(
                    chapter_goal.encode("utf-8")
                ).hexdigest(),
                "base_story_state_revision": state.revision,
                "post_commit_gate": (
                    post_commit_gate.model_dump(mode="json")
                    if post_commit_gate is not None else None
                ),
            }),
            expected_story_state_revision=state.revision,
            managed_paths=tuple(
                path.relative_to(project.path).as_posix()
                for path in managed_paths
            ),
            memory_effects=tuple(memory_effects),
            post_commit_gate=post_commit_gate,
        )
        write_project_mutation_journal(journal_path, journal)
        with WIZARD_MUTATION_LOCK:
            atomic_write(chapter_path, chapter_text)
            service._record_voice_drift(
                run_id, project, chapter_number, polished,
            )
            atomic_write(canon_path, canon_text)
            service._post_write_maintenance(run_id, project)
            artifacts = stage_project_mutation_targets(
                project.path, snapshot, managed_paths,
            )
            journal = ProjectMutationJournalV1.model_validate(
                journal.model_copy(update={
                    "status": "artifacts_committed",
                    "artifacts": artifacts,
                }).model_dump(mode="python"),
            )
            write_project_mutation_journal(journal_path, journal)
            if post_commit_gate is None:
                complete_project_mutation(service.projects, run_id)
            else:
                commit_project_mutation_authority(
                    service.projects, run_id,
                )
        committed = True
        if post_commit_gate is not None:
            try:
                await service._audit_volume_boundary(
                    run_id, run_path, project, chapter_number, constraints,
                )
            except Exception:
                service._bind_long_chapter_volume_gate_receipt(
                    project, run_id, chapter_number,
                )
                raise
            if service._bind_long_chapter_volume_gate_receipt(
                project, run_id, chapter_number,
            ) != "passed":
                raise RuntimeError(
                    "Volume audit receipt did not prove success"
                )
            with WIZARD_MUTATION_LOCK:
                finalize_project_mutation(service.projects, run_id)
        return service.db.get_run(run_id) or {"id": run_id, "status": "completed"}
    except asyncio.CancelledError:
        if not committed:
            if journal_path is None or journal is None:
                snapshot.restore()
                snapshot.discard()
            else:
                abort_project_mutation_request(
                    service.projects, run_id, snapshot, journal_path, journal,
                    error=(
                        "Long-chapter publication was cancelled and "
                        "rolled back."
                    ),
                )
        service.db.update_run(run_id, "cancelled", error="Cancelled by user")
        raise

    except Exception as exc:
        if not committed:
            if journal_path is None or journal is None:
                snapshot.restore()
                snapshot.discard()
                rolled_back = True
            else:
                rolled_back = abort_project_mutation_request(
                    service.projects, run_id, snapshot, journal_path, journal,
                    error=(
                        "Long-chapter publication failed before its durable "
                        "authority commit and was rolled back."
                    ),
                )
            if not rolled_back:
                raise
        service.db.update_run(run_id, "failed", error=_workflow_failure(exc))
        raise
