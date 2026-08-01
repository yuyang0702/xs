from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from novel_flywheel.model_output import parse_json_object
from novel_flywheel.storage import atomic_write
from novel_flywheel.style_context import ensure_style_profile


START = "<!-- STYLE_SAMPLE_START -->"
END = "<!-- STYLE_SAMPLE_END -->"
FIELDS = (
    "sentence_rhythm", "dialogue", "narrative_distance",
    "characterization", "diction", "avoid",
)


class StyleSampleService:
    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway

    def status(self, project: Any) -> dict:
        source = Path(project.path) / "style-samples" / "reference.txt"
        profile_file = Path(project.path) / "style-samples" / "profile.json"
        profile = None
        if profile_file.is_file():
            try:
                profile = json.loads(profile_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                profile = None
        return {
            "configured": source.is_file() and profile is not None,
            "source_characters": len(source.read_text(encoding="utf-8")) if source.is_file() else 0,
            "profile": profile,
        }

    async def analyze(self, project: Any, text: str, source_name: str = "reference.txt") -> dict:
        sample = text.strip()
        if len(sample) < 200:
            raise ValueError("范文至少需要 200 个字符")
        if len(sample) > 60_000:
            raise ValueError("范文不能超过 60000 个字符")
        result = await self.gateway.complete(
            "planning",
            "你是小说文体分析编辑。只提炼可迁移的普通写作特征，不复刻原句、专名、情节，"
            "不判断或猜测作者身份。仅返回严格 JSON。",
            "分析下面范文并返回对象，字段必须为 summary 字符串，以及 sentence_rhythm、dialogue、"
            "narrative_distance、characterization、diction、avoid 六个字符串数组。每个数组 1-5 条，"
            "每条必须是可执行的中文写作规则。\n\n范文：\n" + sample,
            max_output_tokens=1200,
        )
        try:
            profile = self._parse_profile(result.text)
        except ValueError:
            repaired = await self.gateway.complete(
                "planning",
                "把给定的文笔分析整理为指定 JSON，不增加新内容，只返回 JSON。",
                json.dumps({
                    "required_fields": ["summary", *FIELDS],
                    "model_response": result.text[:12000],
                }, ensure_ascii=False),
                max_output_tokens=1200,
            )
            profile = self._parse_profile(repaired.text)
        folder = Path(project.path) / "style-samples"
        profile_path = Path(project.path) / "style-profile.md"
        ensure_style_profile(project)
        base = self._without_managed_block(profile_path.read_text(encoding="utf-8"))
        atomic_write(folder / "reference.txt", sample + "\n")
        atomic_write(folder / "profile.json", json.dumps({
            **profile, "source_name": Path(source_name).name[:160],
        }, ensure_ascii=False, indent=2) + "\n")
        atomic_write(profile_path, base.rstrip() + "\n\n" + self._render(profile))
        return self.status(project)

    def delete(self, project: Any) -> dict:
        folder = Path(project.path) / "style-samples"
        if folder.is_dir():
            shutil.rmtree(folder)
        profile = Path(project.path) / "style-profile.md"
        if profile.is_file():
            atomic_write(profile, self._without_managed_block(profile.read_text(encoding="utf-8")).rstrip() + "\n")
        return self.status(project)

    @staticmethod
    def _parse_profile(raw: str) -> dict:
        try:
            value = parse_json_object(raw, label="笔感分析")
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("笔感分析模型没有返回有效 JSON") from exc
        if not isinstance(value, dict) or not isinstance(value.get("summary"), str):
            raise ValueError("笔感分析缺少 summary")
        profile = {"summary": value["summary"].strip()[:300]}
        for field in FIELDS:
            items = value.get(field)
            if not isinstance(items, list) or not items:
                raise ValueError(f"笔感分析缺少 {field}")
            profile[field] = [str(item).strip()[:200] for item in items[:5] if str(item).strip()]
            if not profile[field]:
                raise ValueError(f"笔感分析缺少 {field}")
        return profile

    @staticmethod
    def _without_managed_block(text: str) -> str:
        return re.sub(
            rf"\n*{re.escape(START)}.*?{re.escape(END)}\n*", "\n",
            text, flags=re.S,
        )

    @staticmethod
    def _render(profile: dict) -> str:
        labels = {
            "sentence_rhythm": "句式与节奏", "dialogue": "对白",
            "narrative_distance": "叙事距离", "characterization": "人物描写",
            "diction": "用词", "avoid": "避免",
        }
        lines = [START, "## 范文提炼笔感", "", profile["summary"], ""]
        for field in FIELDS:
            lines.extend([f"### {labels[field]}", *[f"- {item}" for item in profile[field]], ""])
        lines.extend(["仅学习上述一般特征；禁止复刻范文原句、专名、情节和标志性表达。", END, ""])
        return "\n".join(lines)
