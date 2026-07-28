from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novel_flywheel.quality_summary import build_quality_summary, effective_han_characters
from novel_flywheel.storage import atomic_write


REQUIRED_FIELDS = {
    "title": "主标题",
    "selling_point": "一句话卖点",
    "introduction": "投稿简介",
    "content_type": "内容类型",
    "audience": "目标读者",
}


def _manuscript(project) -> tuple[Path, str, str]:
    if project.metadata.get("platform_profile_id") != "zhihu-salt-short":
        raise ValueError("请先启用知乎盐选短篇创作配置")
    path = project.path / "manuscript" / "story.md"
    if not path.is_file() or not path.read_text(encoding="utf-8").strip():
        raise ValueError("还没有可投稿的正式稿，请先完成正文和终审")
    text = path.read_text(encoding="utf-8")
    return path, text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _report_for_manuscript(
    project, manuscript_hash: str,
) -> tuple[dict[str, Any] | None, Path | None]:
    paths = sorted(
        (project.path / "runs").glob("*/outputs/quality-report.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not paths:
        return None, None
    latest: tuple[dict[str, Any] | None, Path | None] = (None, paths[0])
    for path in paths:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if latest[0] is None:
            latest = report, path
        if report.get("terminal_reviewed_hash") == manuscript_hash:
            return report, path
    return latest


def formal_publication_authority(project) -> dict[str, Any]:
    _, text, digest = _manuscript(project)
    report, report_path = _report_for_manuscript(project, digest)
    run_id = report_path.parents[1].name if report_path else ""
    summary = build_quality_summary(project, run_id, text, report or {}, None)
    authority = dict(summary["publication_authority"])
    authority["can_generate_package"] = authority["can_set_formal"]
    if report and report.get("status") == "passed" and report.get(
        "terminal_reviewed_hash",
    ) != digest:
        authority["blocking_reasons"] = [
            "最近通过终审的内容不是当前正式稿，请重新终审当前稿件",
            *[
                reason for reason in authority["blocking_reasons"]
                if "内容不一致" not in reason
            ],
        ]
    return {
        **authority,
        "manuscript_hash": digest,
        "review_status": report.get("status") if report else "missing",
        "review_path": str(report_path) if report_path else None,
        "word_count": summary["word_count"],
    }


def preview_zhihu_package(project) -> dict[str, Any]:
    _, text, digest = _manuscript(project)
    authority = formal_publication_authority(project)
    return {
        "ready": authority["can_generate_package"],
        "manuscript_hash": digest,
        "character_count": effective_han_characters(text),
        "review_status": authority["review_status"],
        "publication_authority": authority,
        "message": (
            "正式稿和终审结果已准备好，可以填写投稿信息。"
            if authority["can_generate_package"]
            else authority["blocking_reasons"][0]
        ),
    }


def build_zhihu_package(project, metadata: dict[str, Any]) -> dict[str, Any]:
    _, text, digest = _manuscript(project)
    missing = [label for key, label in REQUIRED_FIELDS.items() if not metadata.get(key)]
    if missing:
        raise ValueError("请先填写：" + "、".join(missing))
    expected = metadata.get("expected_manuscript_hash")
    if expected and expected != digest:
        raise ValueError("预览后正文已经发生变化，请重新确认最新正式稿")
    authority = formal_publication_authority(project)
    if not authority["can_generate_package"]:
        raise ValueError(authority["blocking_reasons"][0])
    report_path = Path(authority["review_path"])
    report = json.loads(report_path.read_text(encoding="utf-8"))

    root = project.path / "publication" / "zhihu"
    existing = [int(item.name[1:]) for item in root.glob("v[0-9][0-9][0-9]") if item.is_dir()]
    version = f"v{max(existing, default=0) + 1:03d}"
    target = root / version
    target.mkdir(parents=True, exist_ok=False)
    exported = {
        **metadata,
        "alternate_titles": list(metadata.get("alternate_titles") or []),
        "character_count": effective_han_characters(text),
        "manuscript_hash": digest,
        "platform_profile_id": "zhihu-salt-short",
        "platform_profile_version": project.metadata.get("platform_profile_version"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    exported.pop("expected_manuscript_hash", None)
    atomic_write(target / "manuscript.md", text)
    atomic_write(target / "metadata.json", json.dumps(exported, ensure_ascii=False, indent=2))
    atomic_write(target / "review-report.json", json.dumps({
        "source": str(report_path.relative_to(project.path)) if report_path else None,
        "status": report.get("status"),
        "review": report.get("review") or report.get("final_review"),
        "final_review_evidence": report.get("final_review_evidence"),
    }, ensure_ascii=False, indent=2))
    return {
        "status": "created", "version": version, "path": str(target),
        "manuscript_hash": digest,
        "message": f"知乎投稿包 {version} 已生成，旧版本仍然保留。",
    }
