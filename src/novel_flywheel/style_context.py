import re
from pathlib import Path
from typing import Any

from novel_flywheel.storage import atomic_write


def ensure_style_profile(project: Any) -> str:
    path = Path(project.path) / "style-profile.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    metadata = project.metadata
    profile = (
        "# 作品专属文风档案\n\n"
        f"- 题材：{metadata.get('genre') or '未指定'}\n"
        f"- 叙事视角：{metadata.get('perspective') or '跟随当前视角人物'}\n"
        f"- 基础语调：{metadata.get('tone') or '具体、克制、以场景推进'}\n"
        "- 句子节奏：长短交替，避免连续同构短句和整齐排比。\n"
        "- 描写密度：只保留能推动动作、关系或判断的细节。\n"
        "- 情绪表达：优先动作、选择和对话，不替读者总结感受。\n"
        "- 结尾方式：停在人物的具体动作或关系变化，禁止抽象主题盖章。\n"
        "- 禁止表达：以下是润色版本、这一刻终于明白、不是命运而是选择。\n"
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
