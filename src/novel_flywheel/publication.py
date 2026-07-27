from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _latest_report(project) -> tuple[dict[str, Any] | None, Path | None]:
    paths = list((project.path / "runs").glob("*/outputs/quality-report.json"))
    if not paths:
        return None, None
    path = max(paths, key=lambda item: item.stat().st_mtime)
    try:
        return json.loads(path.read_text(encoding="utf-8")), path
    except (OSError, json.JSONDecodeError):
        return None, path


def preview_zhihu_package(project) -> dict[str, Any]:
    _, text, digest = _manuscript(project)
    report, _ = _latest_report(project)
    return {
        "ready": bool(report and report.get("status") == "passed"),
        "manuscript_hash": digest,
        "character_count": len(re.sub(r"\s+", "", text)),
        "review_status": report.get("status") if report else "missing",
        "message": (
            "正式稿和终审结果已准备好，可以填写投稿信息。"
            if report and report.get("status") == "passed"
            else "正式稿已找到，但还缺少通过的终审结果。"
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
    report, report_path = _latest_report(project)
    if not report or report.get("status") != "passed":
        raise ValueError("当前正式稿还没有通过终审，暂时不能生成投稿包")

    root = project.path / "publication" / "zhihu"
    existing = [int(item.name[1:]) for item in root.glob("v[0-9][0-9][0-9]") if item.is_dir()]
    version = f"v{max(existing, default=0) + 1:03d}"
    target = root / version
    target.mkdir(parents=True, exist_ok=False)
    exported = {
        **metadata,
        "alternate_titles": list(metadata.get("alternate_titles") or []),
        "character_count": len(re.sub(r"\s+", "", text)),
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
