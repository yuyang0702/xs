from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from novel_flywheel.contract_runtime import execute_contract_runtime
from novel_flywheel.db import WIZARD_MUTATION_LOCK
from novel_flywheel.storage import atomic_write, project_snapshot_transaction
from novel_flywheel.style_context import ensure_style_profile
from novel_flywheel.structured_artifacts import StructuredArtifactContract


START = "<!-- STYLE_SAMPLE_START -->"
END = "<!-- STYLE_SAMPLE_END -->"
FIELDS = (
    "sentence_rhythm", "dialogue", "narrative_distance",
    "characterization", "diction", "avoid",
)


STYLE_ANALYSIS_STRUCTURED_CONTRACT = StructuredArtifactContract(
    name="style_analysis_output",
    version=1,
    schema={
        "type": "object",
        "properties": {
            "summary": {"type": "string", "minLength": 1},
            **{
                field: {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 5,
                    "items": {"type": "string", "minLength": 1},
                }
                for field in FIELDS
            },
        },
        "required": ["summary", *FIELDS],
        "additionalProperties": False,
    },
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

    @staticmethod
    def _normalize_profile_payload(value: object) -> dict | None:
        if not isinstance(value, dict) or not isinstance(value.get("summary"), str):
            return None
        profile = {"summary": value["summary"].strip()[:300]}
        if not profile["summary"]:
            return None
        for field in FIELDS:
            items = value.get(field)
            if not isinstance(items, list) or not items:
                return None
            normalized = [
                str(item).strip()[:200] for item in items[:5]
                if str(item).strip()
            ]
            if not normalized:
                return None
            profile[field] = normalized
        return profile

    async def analyze(self, project: Any, text: str, source_name: str = "reference.txt") -> dict:
        sample = text.strip()
        if len(sample) < 200:
            raise ValueError("范文至少需要 200 个字符")
        if len(sample) > 60_000:
            raise ValueError("范文不能超过 60000 个字符")
        runtime_system = (
            "You are a fiction-style analyst. Extract only transferable, ordinary "
            "writing techniques. Never copy source sentences, names, settings, or plot, "
            "and never infer the author's identity. Return only the contracted JSON."
        )
        runtime_user = (
            "Analyze the sample below. Return a Chinese summary plus 1-5 actionable "
            "Chinese rules for every required style field.\n\nSAMPLE:\n" + sample
        )
        runtime = await execute_contract_runtime(
            self.gateway,
            role="planning",
            system=runtime_system,
            user=runtime_user,
            contract_name="style_analysis",
            structured_contract=STYLE_ANALYSIS_STRUCTURED_CONTRACT,
            semantic_normalizer=self._normalize_profile_payload,
            max_output_tokens=1200,
        )
        profile = dict(runtime.domain_value)
        folder = Path(project.path) / "style-samples"
        profile_path = Path(project.path) / "style-profile.md"
        managed_paths = [
            folder / "reference.txt", folder / "profile.json", profile_path,
        ]
        with WIZARD_MUTATION_LOCK:
            with project_snapshot_transaction(
                Path(project.path),
                Path(project.path) / "snapshots" / f"style-sample-{uuid.uuid4().hex}",
                managed_paths,
            ):
                ensure_style_profile(project)
                base = self._without_managed_block(
                    profile_path.read_text(encoding="utf-8")
                )
                atomic_write(folder / "reference.txt", sample + "\n")
                atomic_write(folder / "profile.json", json.dumps({
                    **profile, "source_name": Path(source_name).name[:160],
                }, ensure_ascii=False, indent=2) + "\n")
                atomic_write(
                    profile_path,
                    base.rstrip() + "\n\n" + self._render(profile),
                )
        return self.status(project)

    def delete(self, project: Any) -> dict:
        folder = Path(project.path) / "style-samples"
        profile = Path(project.path) / "style-profile.md"
        managed_paths = [
            path for path in sorted(folder.rglob("*")) if path.is_file()
        ] if folder.is_dir() else []
        managed_paths.append(profile)
        with WIZARD_MUTATION_LOCK:
            with project_snapshot_transaction(
                Path(project.path),
                Path(project.path) / "snapshots" / f"style-sample-delete-{uuid.uuid4().hex}",
                managed_paths,
            ):
                if folder.is_dir():
                    shutil.rmtree(folder)
                if profile.is_file():
                    atomic_write(
                        profile,
                        self._without_managed_block(
                            profile.read_text(encoding="utf-8")
                        ).rstrip() + "\n",
                    )
        return self.status(project)

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
