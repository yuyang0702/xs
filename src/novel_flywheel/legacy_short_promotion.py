from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_flywheel.projects import Project
from novel_flywheel.storage import ProjectSnapshot, atomic_write


def _file_hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _project_path(project: Project, relative: object) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise RuntimeError("正式稿晋升恢复日志包含无效文件路径")
    project_root = project.path.resolve()
    path = (project_root / relative).resolve()
    if not path.is_relative_to(project_root):
        raise RuntimeError("正式稿晋升恢复日志包含项目外路径")
    return path


def recover_legacy_short_formal_promotions(
    db: Any, story_states: Any, project: Project,
) -> None:
    """Read and close v1 short-promotion journals created before the Saga.

    This module is deliberately read/migrate-only. New promotion writers use
    ``project_transactions``; keeping the old journal state machine outside
    ``WorkflowService`` prevents it from becoming a second live transaction
    protocol while existing interrupted projects remain recoverable.
    """

    for journal_path in sorted(project.path.glob(
        "runs/*/outputs/formal-promotion-journal.json",
    )):
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(journal, dict) or journal.get("version") != 1:
            continue
        if journal.get("status") not in {"prepared", "files_written"}:
            continue
        run_id = str(journal.get("run_id") or journal_path.parents[2].name)
        base_revision = int(journal.get("base_revision") or -1)
        target_revision = int(journal.get("target_revision") or -1)
        files = journal.get("files")
        if (
            base_revision < 0
            or target_revision != base_revision + 1
            or not isinstance(files, list)
            or not files
        ):
            raise RuntimeError("正式稿晋升恢复日志无效，已停止新的写作任务")
        state = story_states.ensure(project.id, project.path)
        resolved_files: list[tuple[Path, dict]] = []
        seen_paths: set[Path] = set()
        for item in files:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("new_sha256"), str)
            ):
                raise RuntimeError("正式稿晋升恢复日志包含无效文件记录")
            path = _project_path(project, item.get("path"))
            if path in seen_paths:
                raise RuntimeError("正式稿晋升恢复日志包含重复文件记录")
            seen_paths.add(path)
            resolved_files.append((path, item))
        required_paths = {
            (project.path / "manuscript" / "story.md").resolve(),
            (project.path / "chapters" / "chapter-01.md").resolve(),
            (project.path / "memory" / "canon.json").resolve(),
        }
        if seen_paths != required_paths:
            raise RuntimeError("正式稿晋升恢复日志的权威文件集合不完整")
        expected_match = all(
            _file_hash(path) == item["new_sha256"]
            for path, item in resolved_files
        )
        snapshot_relative = journal.get("snapshot_path")
        if not isinstance(snapshot_relative, str):
            raise RuntimeError("正式稿晋升恢复日志缺少项目快照位置")
        snapshot_root = (project.path / snapshot_relative).resolve()
        snapshots_root = (project.path / "snapshots").resolve()
        if not snapshot_root.is_relative_to(snapshots_root):
            raise RuntimeError("正式稿晋升恢复快照不在项目快照目录内")
        if state.revision == target_revision and expected_match:
            ProjectSnapshot(project.path, snapshot_root, []).discard()
            journal["status"] = "committed_recovered"
            atomic_write(journal_path, json.dumps(
                journal, ensure_ascii=False, indent=2, sort_keys=True,
            ))
            db.add_run_event(
                run_id, "success", "formal_promotion_recovered",
                "检测到正式稿与故事状态均已提交，已完成中断后的晋升收尾",
                stage="archive",
            )
            continue
        if state.revision == target_revision:
            recovery_contents: list[tuple[Path, str]] = []
            recovery_root = (
                journal_path.parent / "formal-promotion-payload"
            ).resolve()
            try:
                for path, item in resolved_files:
                    recovery_relative = item.get("recovery_path")
                    if not isinstance(recovery_relative, str):
                        raise RuntimeError(
                            "故事状态已提交但正式稿不完整，恢复日志缺少确定性恢复载荷；"
                            "已保留恢复日志并停止新的写作任务"
                        )
                    recovery_path = _project_path(project, recovery_relative)
                    if not recovery_path.is_relative_to(recovery_root):
                        raise RuntimeError(
                            "正式稿晋升恢复载荷不在当前运行的载荷目录内"
                        )
                    content = recovery_path.read_text(encoding="utf-8")
                    if hashlib.sha256(content.encode("utf-8")).hexdigest() != (
                        item["new_sha256"]
                    ):
                        raise RuntimeError("正式稿晋升恢复载荷哈希不匹配")
                    recovery_contents.append((path, content))
            except (OSError, UnicodeError) as exc:
                raise RuntimeError(
                    "故事状态已提交但正式稿不完整，且确定性恢复载荷不可用；"
                    "已保留恢复日志并停止新的写作任务"
                ) from exc
            for path, content in recovery_contents:
                atomic_write(path, content)
            if not all(
                _file_hash(path) == item["new_sha256"]
                for path, item in resolved_files
            ):
                raise RuntimeError(
                    "故事状态已提交但正式稿确定性恢复后仍不一致；"
                    "已保留恢复日志并停止新的写作任务"
                )
            ProjectSnapshot(project.path, snapshot_root, []).discard()
            journal["status"] = "committed_repaired"
            atomic_write(journal_path, json.dumps(
                journal, ensure_ascii=False, indent=2, sort_keys=True,
            ))
            db.add_run_event(
                run_id, "warning", "formal_promotion_repaired",
                "检测到故事状态已提交但正式稿文件不完整，已按哈希绑定载荷恢复",
                stage="archive",
            )
            continue
        if state.revision == base_revision:
            try:
                snapshot = ProjectSnapshot.load(project.path, snapshot_root)
            except ValueError as exc:
                raise RuntimeError(
                    "正式稿晋升中断且原始快照不可用，已停止新的写作任务"
                ) from exc
            snapshot.restore()
            snapshot.discard()
            candidate_id = str(journal.get("candidate_id") or "")
            if candidate_id:
                story_states.reject(
                    candidate_id,
                    "formal promotion recovered after process interruption",
                )
            journal["status"] = "rolled_back_recovered"
            atomic_write(journal_path, json.dumps(
                journal, ensure_ascii=False, indent=2, sort_keys=True,
            ))
            db.add_run_event(
                run_id, "warning", "formal_promotion_rolled_back",
                "检测到正式稿晋升在故事状态提交前中断，已恢复原正式稿",
                stage="archive",
            )
            continue
        if state.revision > target_revision:
            ProjectSnapshot(project.path, snapshot_root, []).discard()
            journal["status"] = "superseded"
            atomic_write(journal_path, json.dumps(
                journal, ensure_ascii=False, indent=2, sort_keys=True,
            ))
            continue
        raise RuntimeError("正式稿晋升恢复状态与 StoryState 版本不一致")
