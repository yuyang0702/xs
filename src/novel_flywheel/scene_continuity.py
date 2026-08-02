from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata


@dataclass(frozen=True)
class LocationRef:
    name: str
    root: str


_BRIDGE = re.compile(
    r"次日|翌日|第二天|[一二三四五六七八九十\d]+(?:日|天|月|年|时辰|分钟|小时)后|"
    r"与此同时|同一时刻|后来|随后|转眼|天亮|入夜|黄昏|清晨|午后|当晚|"
    r"来到|赶到|抵达|回到|返回|离开|走进|走出|穿过|登上|下了车|从车上下来|乘车|驱车|驶入|"
    r"传送|跃迁|降落|起飞|醒来|梦中|梦里|回忆|记忆|意识|虚拟|幻境|秘境"
)
_FEATURES = re.compile(
    r"(?ms)^##\s+(?:Notable Features|地点特征|重要特征|显著特征)\s*$"
    r"\s*(.*?)(?=^##\s+|\Z)",
)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")).strip())


def _frontmatter(text: str) -> str:
    match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.DOTALL)
    return unicodedata.normalize("NFKC", match.group(1)) if match else ""


def _visible_markdown(text: str) -> str:
    text = re.sub(r"<!--.*?(?:-->|\Z)", "", text, flags=re.DOTALL)
    visible: list[str] = []
    fence_character = ""
    fence_length = 0
    for line in text.splitlines(keepends=True):
        fence = re.match(r"^[ ]{0,3}(?P<mark>`{3,}|~{3,})", line)
        if fence_character:
            if (fence and fence.group("mark")[0] == fence_character
                    and len(fence.group("mark")) >= fence_length):
                fence_character = ""
                fence_length = 0
            continue
        if fence:
            fence_character = fence.group("mark")[0]
            fence_length = len(fence.group("mark"))
            continue
        visible.append(line)
    return "".join(visible)


def _scalar(frontmatter: str, key: str) -> str:
    match = re.search(
        rf"(?m)^{re.escape(key)}\s*:\s*['\"]?([^'\"\r\n]+)['\"]?\s*$",
        frontmatter,
    )
    return _normalize(match.group(1)) if match else ""


def _list(frontmatter: str, key: str) -> list[str]:
    block = re.search(
        rf"(?ms)^{re.escape(key)}\s*:\s*(?:\r?\n)((?:^[ \t]+-.*(?:\r?\n|\Z))*)",
        frontmatter,
    )
    if block:
        return [
            value for value in (
                _normalize(match.group(1).strip(" '\""))
                for match in re.finditer(
                    r"(?m)^[ \t]+-\s*(.+?)\s*$", block.group(1),
                )
            ) if value
        ]
    inline = re.search(
        rf"(?m)^{re.escape(key)}\s*:\s*\[(.*?)\]\s*$", frontmatter,
    )
    if not inline:
        return []
    values: list[str] = []
    current: list[str] = []
    quote = ""
    for character in inline.group(1):
        if quote:
            if character == quote:
                quote = ""
            else:
                current.append(character)
            continue
        if character in {'"', "'"} and not "".join(current).strip():
            quote = character
        elif character in {"[", "]", "{", "}"}:
            return []
        elif character in {",", "，"}:
            values.append("".join(current))
            current = []
        else:
            current.append(character)
    if quote:
        return []
    values.append("".join(current))
    return [
        value for value in (
            _normalize(item.strip(" '\""))
            for item in values
        ) if value
    ]


def _state_locations(value: object, *, key: str = "") -> list[str]:
    if isinstance(value, dict):
        return [
            item
            for child_key, child in value.items()
            for item in _state_locations(child, key=str(child_key))
        ]
    if isinstance(value, list):
        return [item for child in value for item in _state_locations(child, key=key)]
    if isinstance(value, str) and key in {
        "primary_location", "current_location", "location_name",
    }:
        normalized = _normalize(value)
        return [normalized] if 1 < len(normalized) <= 80 else []
    return []


def build_location_catalog(
    project_path: Path, state: dict,
) -> dict[str, LocationRef]:
    documents: list[tuple[str, list[str], list[str]]] = []
    root = project_path / "worldbuilding" / "locations"
    for path in sorted(root.rglob("*.md")) if root.is_dir() else []:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter = _frontmatter(text)
        visible = _visible_markdown(text)
        name = _scalar(frontmatter, "name")
        if not name:
            heading = re.search(r"(?m)^#\s+(.+?)\s*$", visible)
            name = _normalize(heading.group(1)) if heading else ""
        if not name:
            continue
        features_match = _FEATURES.search(visible)
        features = (
            [_normalize(value) for value in re.findall(
                r"(?m)^\s*-\s*\*\*(.+?)\*\*", features_match.group(1),
            )]
            if features_match else []
        )
        documents.append((name, _list(frontmatter, "aliases"), features))

    state_names = _state_locations(state)
    all_names = [name for name, _aliases, _features in documents] + state_names
    roots = {
        name: max(
            (candidate for candidate in all_names if candidate != name and name.startswith(candidate)),
            key=len,
            default=name,
        )
        for name in all_names
    }
    catalog: dict[str, LocationRef] = {}
    ambiguous: set[str] = set()

    def add(alias: str, ref: LocationRef) -> None:
        alias = _normalize(alias)
        if not alias or alias in ambiguous:
            return
        existing = catalog.get(alias)
        if existing is not None and existing != ref:
            catalog.pop(alias, None)
            ambiguous.add(alias)
            return
        catalog[alias] = ref

    for name, aliases, features in documents:
        root_name = roots[name]
        add(name, LocationRef(name, root_name))
        for alias in aliases:
            add(alias, LocationRef(name, root_name))
        for feature in features:
            add(feature, LocationRef(feature, root_name))
    for name in state_names:
        add(name, LocationRef(name, roots[name]))
    return catalog


def _inside_quotes(text: str, position: int) -> bool:
    return text[:position].count("“") > text[:position].count("”")


def _mentions(text: str, catalog: dict[str, LocationRef]) -> list[tuple[int, int, LocationRef]]:
    normalized = _normalize(text)
    mentions = []
    for alias, ref in catalog.items():
        alias = _normalize(alias)
        if not alias:
            continue
        start = 0
        while True:
            position = normalized.find(alias, start)
            if position < 0:
                break
            context = normalized[max(0, position - 8):position]
            if not _inside_quotes(normalized, position) and not re.search(
                r"提到|说起|谈起|想起|听说|梦见$", context,
            ):
                mentions.append((position, len(alias), ref))
            start = position + max(1, len(alias))
    return mentions


def assess_scene_transition(
    previous_text: str, current_text: str, catalog: dict[str, LocationRef],
) -> list[dict]:
    if not previous_text.strip() or not current_text.strip() or not catalog:
        return []
    previous_mentions = _mentions(previous_text[-1200:], catalog)
    opening = next((
        item.strip() for item in re.split(r"\r?\n\s*\r?\n", current_text)
        if item.strip()
    ), "")[:500]
    current_mentions = _mentions(opening, catalog)
    if not previous_mentions or not current_mentions:
        return []
    previous = max(previous_mentions, key=lambda item: (item[0], item[1]))[2]
    current = min(current_mentions, key=lambda item: (item[0], -item[1]))[2]
    if previous.name == current.name:
        return []
    if _BRIDGE.search(opening):
        return []
    metadata = {
        "previous_location": previous.name,
        "current_location": current.name,
    }
    if previous.root == current.root:
        return [{
            "code": "scene_transition_uncertain",
            "message": "场景似乎在同一地点范围内变化，但没有识别到明确移动交代",
            "blocking": False,
            **metadata,
        }]
    return [{
        "code": "scene_transition_missing",
        "message": (
            f"场景从“{previous.name}”切换到“{current.name}”，"
            "但没有识别到时间、移动或场景层级交代"
        ),
        "blocking": True,
        **metadata,
    }]
