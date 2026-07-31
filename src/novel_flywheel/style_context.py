import re
import json
from pathlib import Path
from typing import Any

from novel_flywheel.storage import atomic_write


DEFAULT_STYLE_RULES = (
    ("句子节奏", "长短交替，避免连续同构短句和整齐排比。"),
    ("描写密度", "只保留能推动动作、关系或判断的细节。"),
    ("情绪表达", "优先动作、选择和对话，不替读者总结感受。"),
    ("结尾方式", "停在人物的具体动作或关系变化，禁止抽象主题盖章。"),
    ("避免使用", "以下是润色版本、这一刻终于明白、不是命运而是选择。"),
)


def default_style_profile(metadata: dict) -> dict:
    return {
        "genre": metadata.get("genre") or "未指定",
        "viewpoint": metadata.get("pov") or metadata.get("perspective") or "跟随当前视角人物",
        "tone": metadata.get("tone") or "具体、克制、以场景推进",
        "rules": [{"label": label, "rule": rule} for label, rule in DEFAULT_STYLE_RULES],
    }


def ensure_style_profile(project: Any) -> str:
    path = Path(project.path) / "style-profile.md"
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        baseline = Path(project.path) / "learning" / "prose_baseline.json"
        try:
            migrated = json.loads(baseline.read_text(encoding="utf-8")).get("data", {}).get("source") == "legacy_style_sample"
        except (OSError, json.JSONDecodeError):
            migrated = False
        if migrated:
            return re.sub(
                r"\n*<!-- STYLE_SAMPLE_START -->.*?<!-- STYLE_SAMPLE_END -->\n*", "\n",
                text, flags=re.S,
            ).rstrip() + "\n"
        return text
    profile_data = default_style_profile(project.metadata)
    profile = (
        "# 作品专属文风档案\n\n"
        f"- 题材：{profile_data['genre']}\n"
        f"- 叙事视角：{profile_data['viewpoint']}\n"
        f"- 基础语调：{profile_data['tone']}\n"
        + "".join(f"- {item['label']}：{item['rule']}\n" for item in profile_data["rules"])
    )
    atomic_write(path, profile)
    return profile


def character_fingerprints(project_path: Path, segment: str, max_chars: int = 2400) -> str:
    folder = Path(project_path) / "characters"
    selected = []
    if not folder.is_dir():
        return ""
    for path in sorted(folder.glob("*.md")):
        if path.name == "_index.md":
            continue
        text = path.read_text(encoding="utf-8")
        heading = re.search(r"(?m)^#\s+(.+)$", text)
        name = heading.group(1).strip() if heading else path.stem
        if name not in segment:
            continue
        useful = [line.strip() for line in text.splitlines() if any(marker in line for marker in (
            "说话", "口头", "称呼", "语气", "句", "情绪", "禁用", "声音",
        ))]
        selected.append(f"## {name}\n" + "\n".join(useful[:8]))
    return "\n\n".join(selected)[:max_chars]
