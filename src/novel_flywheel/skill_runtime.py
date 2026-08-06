import fnmatch
import hashlib
import json
import re
import uuid
import asyncio
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath
from typing import Callable

from novel_flywheel.db import Database
from novel_flywheel.domain.models import ToolDefinition
from novel_flywheel.projects import Project
from novel_flywheel.storage import ProjectSnapshot, atomic_write
from novel_flywheel.models import ModelGateway
from novel_flywheel.outlines import (
    extract_outline_characters,
    normalize_outline_manifest,
    outline_events,
)
from novel_flywheel.projects import ProjectStore
from novel_flywheel.skills import SkillGate


CONTRACT_PATHS = {
    "story-init": (
        "story.md", "constraints.md", "chapters/_index.md", "characters/_index.md",
        "continuity/promises/_index.md", "continuity/questions/_index.md",
        "glossary/_index.md", "plot/_index.md", "scenes/_index.md",
        "worldbuilding/_index.md", "continuity/state.md", "plot/timeline.md",
    ),
    "character-management": ("characters/*.md",),
    "worldbuilding": ("worldbuilding/*.md", "worldbuilding/**/*.md"),
    "plot-structure": ("plot/*.md", "plot/**/*.md", "continuity/promises/*.md", "continuity/questions/*.md"),
}

CANONICAL_STORY_FILES = (
    "story.md", "chapters/_index.md", "characters/_index.md",
    "continuity/promises/_index.md", "continuity/questions/_index.md",
    "glossary/_index.md", "plot/_index.md", "scenes/_index.md",
    "worldbuilding/_index.md", "continuity/state.md", "plot/timeline.md",
)

ACTIVE_PROPOSAL_STATUSES = {"pending", "retained"}

ENTITY_FOLDERS = {
    "character": "characters",
    "location": "worldbuilding/locations",
    "system": "worldbuilding/systems",
    "arc": "plot/arcs",
    "chapter": "chapters",
    "scene": "scenes",
    "faction": "worldbuilding/factions",
    "artifact": "worldbuilding/artifacts",
}
ENTITY_ALIASES = {**{name: name for name in ENTITY_FOLDERS}, **{
    "characters": "character", "locations": "location", "systems": "system",
    "arcs": "arc", "chapters": "chapter", "scenes": "scene",
    "factions": "faction", "artifacts": "artifact",
}}

RELATIONSHIP_INVERSES = {
    "parent": "child", "child": "parent",
    "grandparent": "grandchild", "grandchild": "grandparent",
    "uncle": "nephew", "aunt": "niece",
    "nephew": "uncle", "niece": "aunt",
    "mentor": "student", "student": "mentor",
    "employer": "subordinate", "subordinate": "employer",
    **{name: name for name in (
        "sibling", "spouse", "partner", "friend", "ally", "rival", "enemy",
        "cousin", "colleague", "foil", "confidant", "love-interest",
    )},
}


@dataclass(frozen=True)
class SkillContract:
    skill_name: str
    writable_patterns: tuple[str, ...]

    @classmethod
    def for_skill(cls, name: str) -> "SkillContract":
        return cls(name, CONTRACT_PATHS.get(name, ()))

    def permits(self, relative_path: str) -> bool:
        return any(fnmatch.fnmatchcase(relative_path, pattern) for pattern in self.writable_patterns)


def expected_initialization_characters(answers: dict) -> list[str]:
    """Return only names the user or confirmed outline identifies explicitly."""
    names = []
    protagonist = str(answers.get("protagonist.name") or "").strip()
    if protagonist:
        names.append(protagonist)
    key_characters = str(answers.get("key_characters") or "")
    for item in re.split(r"[\n；;]+", key_characters):
        candidate = re.split(r"[：:（(，,、-]", item.strip(), maxsplit=1)[0].strip(" -*#")
        if 2 <= len(candidate) <= 20:
            names.append(candidate)

    outline = answers.get("confirmed_outline") or {}
    content = str(outline.get("content") or "") if isinstance(outline, dict) else str(outline)
    names.extend(item["name"] for item in extract_outline_characters(content))
    names.extend(
        str(item.get("name") or "").strip()
        for item in (answers.get("outline_manifest") or {}).get("characters", [])
        if isinstance(item, dict)
    )
    return list(dict.fromkeys(name for name in names if name))


def initialization_answers(project: Project, current_outline: dict) -> dict:
    content = str(current_outline.get("content") or "")
    events = outline_events(content) if content.strip() else current_outline.get("events", [])
    requirements = dict(project.metadata.get("story_requirements", {}))
    characters = extract_outline_characters(content)
    outline_protagonist = next(
        (item["name"] for item in characters if item["role"] == "protagonist"), "",
    )
    if outline_protagonist:
        requirements["protagonist.name"] = outline_protagonist
    answers = {
        **requirements,
        "outline_characters": characters,
        "confirmed_outline": {
            "version": current_outline.get("outline_version", 0),
            "content": content,
            "events": events,
        },
    }
    try:
        cached = json.loads(
            (project.path / "memory" / "outline-manifest.json").read_text(encoding="utf-8")
        )
        if (
            cached.get("outline_hash") == hashlib.sha256(content.encode("utf-8")).hexdigest()
            and isinstance(cached.get("manifest"), dict)
        ):
            answers["outline_manifest"] = normalize_outline_manifest(cached["manifest"])
    except (OSError, json.JSONDecodeError):
        pass
    return answers


def initialization_context_hash(answers: dict) -> str:
    canon = {
        key: value for key, value in answers.items()
        if key != "confirmed_learning_context"
    }
    encoded = json.dumps(canon, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _frontmatter_relationships(text: str) -> list[tuple[str, str]]:
    _prefix, body, _before_close, _rest = _split_frontmatter(text)
    matches = list(re.finditer(
        r"(?m)^relationships:(?P<value>[^\r\n]*)(?P<eol>\r\n|\n|\Z)",
        body,
    ))
    if len(matches) > 1:
        raise ValueError("Frontmatter field relationships is duplicated")
    if not matches:
        return []
    match = matches[0]
    scalar = match.group("value").strip()
    if scalar:
        if scalar == "[]":
            return []
        raise ValueError("Frontmatter field relationships must use a YAML list")
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in re.finditer(r"[^\r\n]*(?:\r\n|\n|\Z)", body[match.end():]):
        visible = line.group(0).rstrip("\r\n")
        if not visible:
            continue
        if not visible[:1].isspace() and not visible.startswith("-"):
            break
        item_start = re.fullmatch(
            r"\s*-\s*([A-Za-z0-9_-]+):\s*(.+?)\s*", visible,
        )
        continuation = re.fullmatch(
            r"\s+([A-Za-z0-9_-]+):\s*(.+?)\s*", visible,
        )
        if item_start:
            if current is not None:
                entries.append(current)
            current = {}
            key, value = item_start.groups()
        elif continuation and current is not None:
            key, value = continuation.groups()
        else:
            raise ValueError("Frontmatter field relationships contains malformed list content")
        if key in current:
            raise ValueError(f"Relationship field {key} is duplicated")
        current[key] = value.strip().strip("\"'")
    if current is not None:
        entries.append(current)
    relationships = []
    for fields in entries:
        if not fields.get("character") or not fields.get("type"):
            raise ValueError("Each relationship requires character and type")
        relationships.append((fields["character"], fields["type"]))
    return relationships


def _split_frontmatter(text: str) -> tuple[str, str, str, str]:
    match = re.match(
        r"\A(?P<prefix>\ufeff?---(?P<eol>\r\n|\n))"
        r"(?P<body>.*?)(?P<before_close>\r\n|\n)---(?P<rest>(?:\r\n|\n|\Z).*)\Z",
        text, flags=re.DOTALL,
    )
    if not match:
        raise ValueError("Markdown frontmatter is missing or malformed")
    return (
        match.group("prefix"), match.group("body"),
        match.group("before_close"), match.group("rest"),
    )


def _unquote_reference(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    if not value or not re.fullmatch(r"[\w.-]+", value, flags=re.UNICODE):
        raise ValueError(f"Reference ID is malformed: {value!r}")
    return value


def _inline_reference_list(value: str) -> list[str]:
    if not (value.startswith("[") and value.endswith("]")):
        raise ValueError("Reference list must use a YAML list")
    inner = value[1:-1].strip()
    if not inner:
        return []
    items = []
    token = []
    quote: str | None = None
    escaped = False
    for character in inner:
        if escaped:
            token.append(character)
            escaped = False
            continue
        if quote == '"' and character == "\\":
            token.append(character)
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            token.append(character)
            continue
        if character == "," and quote is None:
            items.append(_unquote_reference("".join(token)))
            token = []
            continue
        token.append(character)
    if quote is not None or escaped:
        raise ValueError("Reference list contains an unterminated quoted value")
    items.append(_unquote_reference("".join(token)))
    return items


def _frontmatter_reference_list(text: str, field: str) -> tuple[list[str], bool]:
    _prefix, body, _before_close, _rest = _split_frontmatter(text)
    field_matches = list(re.finditer(
        rf"(?m)^(?P<field>{re.escape(field)}):(?P<value>[^\r\n]*)(?P<eol>\r\n|\n|\Z)",
        body,
    ))
    if len(field_matches) > 1:
        raise ValueError(f"Frontmatter field {field} is duplicated")
    if not field_matches:
        return [], False
    match = field_matches[0]
    scalar = match.group("value").strip()
    if scalar:
        values = _inline_reference_list(scalar)
    else:
        values = []
        for line in re.finditer(r"[^\r\n]*(?:\r\n|\n|\Z)", body[match.end():]):
            raw = line.group(0)
            visible = raw.rstrip("\r\n")
            if not visible:
                continue
            if not visible[:1].isspace() and not visible.startswith("-"):
                break
            item = re.fullmatch(r"\s*-\s*(.+?)\s*", visible)
            if not item:
                raise ValueError(f"Frontmatter field {field} contains malformed list content")
            values.append(_unquote_reference(item.group(1)))
    if len(values) != len(set(values)):
        raise ValueError(f"Frontmatter field {field} contains duplicate references")
    return values, True


def _set_frontmatter_reference_list(text: str, field: str, values: list[str]) -> str:
    prefix, body, before_close, rest = _split_frontmatter(text)
    unique = list(dict.fromkeys(values))
    for value in unique:
        _unquote_reference(value)
    field_matches = list(re.finditer(
        rf"(?m)^(?P<field>{re.escape(field)}):(?P<value>[^\r\n]*)(?P<eol>\r\n|\n|\Z)",
        body,
    ))
    if len(field_matches) > 1:
        raise ValueError(f"Frontmatter field {field} is duplicated")
    eol = "\r\n" if "\r\n" in prefix else "\n"
    rendered = field + ":" + "".join(f"{eol}  - {value}" for value in unique)
    if not field_matches:
        separator = eol if body else ""
        updated_body = body + separator + rendered
        return prefix + updated_body + before_close + "---" + rest
    match = field_matches[0]
    _frontmatter_reference_list(text, field)
    end = match.end()
    if not match.group("value").strip():
        for line in re.finditer(r"[^\r\n]*(?:\r\n|\n|\Z)", body[match.end():]):
            visible = line.group(0).rstrip("\r\n")
            if visible and not visible[:1].isspace() and not visible.startswith("-"):
                break
            end = match.end() + line.end()
    suffix = body[end:]
    if suffix and not suffix.startswith(("\n", "\r\n")):
        rendered += eol
    updated_body = body[:match.start()] + rendered + suffix
    return prefix + updated_body + before_close + "---" + rest


def _location_reference_issues(
    characters: dict[str, str], locations: dict[str, str], *,
    reciprocal_repair_available: bool,
) -> list[str]:
    issues = []
    character_locations: dict[str, list[str]] = {}
    location_characters: dict[str, list[str]] = {}
    for character_id, text in characters.items():
        try:
            character_locations[character_id] = _frontmatter_reference_list(
                text, "locations",
            )[0]
        except ValueError as exc:
            issues.append(f"人物 {character_id} 的 locations 无法安全解析：{exc}")
    for location_id, text in locations.items():
        try:
            location_characters[location_id] = _frontmatter_reference_list(
                text, "notable-characters",
            )[0]
        except ValueError as exc:
            issues.append(f"地点 {location_id} 的 notable-characters 无法安全解析：{exc}")
    for character_id, location_ids in character_locations.items():
        for location_id in location_ids:
            if location_id not in locations:
                issues.append(f"人物 {character_id} 引用了不存在的地点 {location_id}")
            elif (
                not reciprocal_repair_available
                and character_id not in location_characters.get(location_id, [])
            ):
                issues.append(f"地点 {location_id} 缺少人物 {character_id} 的反向链接")
    for location_id, character_ids in location_characters.items():
        for character_id in character_ids:
            if character_id not in characters:
                issues.append(f"地点 {location_id} 引用了不存在的人物 {character_id}")
            elif (
                not reciprocal_repair_available
                and location_id not in character_locations.get(character_id, [])
            ):
                issues.append(f"人物 {character_id} 缺少地点 {location_id} 的反向链接")
    return list(dict.fromkeys(issues))


def _close_location_backlinks(project: Project) -> list[Path]:
    character_paths = {
        path.stem: path for path in sorted((project.path / "characters").glob("*.md"))
        if path.name != "_index.md"
    }
    location_paths = {
        path.stem: path for path in sorted((project.path / "worldbuilding" / "locations").glob("*.md"))
        if path.name != "_index.md"
    }
    character_text = {
        key: path.read_bytes().decode("utf-8") for key, path in character_paths.items()
    }
    location_text = {
        key: path.read_bytes().decode("utf-8") for key, path in location_paths.items()
    }
    issues = _location_reference_issues(
        character_text, location_text, reciprocal_repair_available=True,
    )
    if issues:
        raise ValueError("地点与人物引用无法安全闭合：" + "；".join(issues))
    character_locations = {
        key: _frontmatter_reference_list(text, "locations")[0]
        for key, text in character_text.items()
    }
    location_characters = {
        key: _frontmatter_reference_list(text, "notable-characters")[0]
        for key, text in location_text.items()
    }
    original_character_locations = {
        key: list(values) for key, values in character_locations.items()
    }
    original_location_characters = {
        key: list(values) for key, values in location_characters.items()
    }
    for character_id, location_ids in character_locations.items():
        for location_id in location_ids:
            if character_id not in location_characters[location_id]:
                location_characters[location_id].append(character_id)
    for location_id, character_ids in location_characters.items():
        for character_id in character_ids:
            if location_id not in character_locations[character_id]:
                character_locations[character_id].append(location_id)
    changed = []
    for character_id, values in character_locations.items():
        if values == original_character_locations[character_id]:
            continue
        updated = _set_frontmatter_reference_list(
            character_text[character_id], "locations", values,
        )
        if updated != character_text[character_id]:
            atomic_write(
                character_paths[character_id], updated, preserve_newlines=True,
            )
            changed.append(character_paths[character_id])
    for location_id, values in location_characters.items():
        if values == original_location_characters[location_id]:
            continue
        updated = _set_frontmatter_reference_list(
            location_text[location_id], "notable-characters", values,
        )
        if updated != location_text[location_id]:
            atomic_write(
                location_paths[location_id], updated, preserve_newlines=True,
            )
            changed.append(location_paths[location_id])
    return changed


def initialization_stage_issues(project: Project, skill_name: str, answers: dict,
                                proposals: list[dict] | None = None) -> list[str]:
    """Check bootstrap outcomes against existing files plus pending proposals."""
    local_registry_rebuild_pending = proposals is not None
    proposed = {
        item["relative_path"]: item["content"]
        for item in (proposals or []) if item.get("status") in ACTIVE_PROPOSAL_STATUSES
    }

    def content(relative: str) -> str:
        if relative in proposed:
            return str(proposed[relative])
        path = project.path / relative
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def paths(pattern: str) -> list[str]:
        existing = {
            path.relative_to(project.path).as_posix()
            for path in project.path.glob(pattern) if path.is_file()
        }
        existing.update(relative for relative in proposed if fnmatch.fnmatchcase(relative, pattern))
        return sorted(existing)

    if skill_name == "story-init":
        missing = [relative for relative in CANONICAL_STORY_FILES if not content(relative).strip()]
        issues = [f"缺少项目根目录文件：{', '.join(missing)}"] if missing else []
        story = content("story.md")
        frontmatter = story.split("---", 2)[1] if story.startswith("---") and story.count("---") >= 2 else ""
        fields = {
            key: value.strip().strip("\"'")
            for key, value in re.findall(r"(?m)^([\w-]+):\s*([^\n]+)$", frontmatter)
        }
        unmet = []
        title = str(answers.get("title") or "").strip()
        genre = str(answers.get("genre") or "").strip()
        premise = str(answers.get("premise") or "").strip()
        target_words = str(answers.get("target_words") or "").strip()
        pov = str(answers.get("pov") or "").strip().casefold()
        tone = str(answers.get("tone") or "").strip()
        if title and fields.get("title") != title:
            unmet.append("标题")
        if genre and fields.get("genre") != genre:
            unmet.append("题材")
        if premise:
            normalize = lambda value: re.sub(  # noqa: E731
                r"[^A-Za-z0-9\u3400-\u9fff]+", "", value,
            ).casefold()
            expected_premise = normalize(premise)
            paragraphs = [normalize(item) for item in re.split(r"\n\s*\n", story)]
            premise_similarity = max((
                SequenceMatcher(None, expected_premise, paragraph, autojunk=False).ratio()
                for paragraph in paragraphs if paragraph
            ), default=0.0)
            if premise_similarity < 0.35:
                unmet.append("核心设定")
        if target_words and target_words not in story:
            unmet.append("目标字数")
        actual_pov = fields.get("pov", "").casefold()
        if pov and not (actual_pov == pov or actual_pov.startswith(f"{pov}-")):
            unmet.append("叙事视角")
        if tone and tone not in story:
            unmet.append("文风")
        if unmet:
            issues.append("story.md 还没有正确写入：" + "、".join(unmet))
        constraints = content("constraints.md")
        constraint_issues = []
        for key, label in (("must_include", "必须包含"), ("must_avoid", "必须避免")):
            expected = str(answers.get(key) or "").strip()
            if expected and expected.casefold() != "none" and expected not in constraints:
                constraint_issues.append(label)
        manifest_constraints = (answers.get("outline_manifest") or {}).get("constraints") or []
        missing_manifest_constraints = [
            str(item.get("text") or "").strip() for item in manifest_constraints
            if isinstance(item, dict) and str(item.get("text") or "").strip() not in constraints
        ]
        if constraint_issues:
            issues.append("创作约束还没有正确写入：" + "、".join(constraint_issues))
        if missing_manifest_constraints:
            issues.append(
                f"创作约束还缺少 {len(missing_manifest_constraints)} 条正式大纲要求"
            )
        return issues

    if skill_name == "character-management":
        profiles = [relative for relative in paths("characters/*.md") if not relative.endswith("/_index.md")]
        expected = expected_initialization_characters(answers)
        required_count = max(1, len(expected))
        issues = []
        if len(profiles) < required_count:
            issues.append(f"人物档案只有 {len(profiles)} 份，需要覆盖 {required_count} 位主要人物")
        identities = []
        for relative in profiles:
            text = content(relative)
            name_match = re.search(r'(?m)^name:\s*["\']?([^"\'\r\n]+)', text)
            role_match = re.search(r'(?m)^role:\s*["\']?([^"\'\r\n]+)', text)
            aliases_match = re.search(
                r"(?ms)^aliases:\s*\n(?P<items>(?:\s+-\s+.*\n?)*)", text,
            )
            aliases = re.findall(
                r'(?m)^\s+-\s+["\']?([^"\'\r\n]+)',
                aliases_match.group("items") if aliases_match else "",
            )
            identities.append({
                "path": relative,
                "name": name_match.group(1).strip() if name_match else "",
                "role": role_match.group(1).strip() if role_match else "",
                "aliases": [alias.strip() for alias in aliases],
            })
        used_profiles = set()
        matched = {}
        for expected_name in expected:
            match = next((
                item for item in identities
                if item["path"] not in used_profiles and expected_name == item["name"]
            ), None)
            if match:
                matched[expected_name] = match
                used_profiles.add(match["path"])
        missing_names = [name for name in expected if name not in matched]
        if missing_names:
            issues.append(f"这些主要人物还没有独立档案：{'、'.join(missing_names)}")
        outline_characters = extract_outline_characters(
            str((answers.get("confirmed_outline") or {}).get("content") or "")
        )
        outline_protagonists = {
            item["name"] for item in outline_characters if item["role"] == "protagonist"
        }
        outline_protagonists.update(
            str(item.get("name") or "").strip()
            for item in (answers.get("outline_manifest") or {}).get("characters", [])
            if isinstance(item, dict) and item.get("role") == "protagonist"
        )
        conflicting_protagonists = sorted({
            item["name"] for item in identities
            if item["role"] == "protagonist" and item["name"]
            and outline_protagonists and item["name"] not in outline_protagonists
        })
        if conflicting_protagonists:
            issues.append(
                "主角档案姓名与正式大纲不一致："
                f"档案为{'、'.join(conflicting_protagonists)}，正式大纲为{'、'.join(sorted(outline_protagonists))}"
            )
        duplicate_names = sorted({
            item["name"] for item in identities if item["name"]
            and sum(other["name"] == item["name"] for other in identities) > 1
        })
        if duplicate_names:
            issues.append(f"这些人物存在重复档案：{'、'.join(duplicate_names)}")
        relationships_by_id = {}
        for item in identities:
            character_id = Path(item["path"]).stem
            try:
                relationships_by_id[character_id] = _frontmatter_relationships(
                    content(item["path"]),
                )
            except ValueError as exc:
                relationships_by_id[character_id] = []
                issues.append(f"人物 {character_id} 的 relationships 无法安全解析：{exc}")
        ambiguous_pairs = {
            (source, target)
            for source, relationships in relationships_by_id.items()
            for target, _relationship_type in relationships
            if sum(other_target == target for other_target, _other_type in relationships) > 1
        }
        if ambiguous_pairs:
            labels = [f"{source}→{target}" for source, target in sorted(ambiguous_pairs)]
            issues.append("人物关系中同一对象只能登记一种关系：" + "、".join(labels))
        relationship_link_issues = []
        for source, relationships in relationships_by_id.items():
            for target, relationship_type in relationships:
                if (source, target) in ambiguous_pairs or (target, source) in ambiguous_pairs:
                    continue
                backlinks = [
                    backlink_type for backlink_target, backlink_type
                    in relationships_by_id.get(target, []) if backlink_target == source
                ]
                expected_type = RELATIONSHIP_INVERSES.get(relationship_type)
                if not backlinks:
                    relationship_link_issues.append(f"{source}→{target} 缺少反向关系")
                elif expected_type and expected_type not in backlinks:
                    relationship_link_issues.append(
                        f"{source}→{target} 的反向关系类型不一致，需要 {expected_type}"
                    )
        if relationship_link_issues:
            issues.append("；".join(dict.fromkeys(relationship_link_issues)))
        registry = content("characters/_index.md")
        unregistered_profiles = [
            relative for relative in profiles
            if Path(relative).name not in registry and Path(relative).stem not in registry
        ]
        if (not registry.strip() or unregistered_profiles) and not local_registry_rebuild_pending:
            suffix = f"：{', '.join(unregistered_profiles)}" if unregistered_profiles else ""
            issues.append(f"人物列表还没有登记完整{suffix}")
        if required_count > 1:
            relationship = re.search(
                r"(?ms)^## Relationship Map\s*(.*?)(?=^## |\Z)", registry,
            )
            body = relationship.group(1).strip() if relationship else ""
            if not body or "No relationships" in body:
                issues.append("人物关系图还是空的")
        return issues

    if skill_name == "worldbuilding":
        details = [
            relative for relative in paths("worldbuilding/**/*.md")
            if not relative.endswith("/_index.md")
        ]
        registry = content("worldbuilding/_index.md")
        issues = []
        if not details:
            issues.append("至少还需要一份与剧情直接相关的地点、规则、势力或关键物件资料")
        unregistered = [relative for relative in details if Path(relative).stem not in registry]
        if (not registry.strip() or unregistered) and not local_registry_rebuild_pending:
            suffix = f"：{', '.join(unregistered)}" if unregistered else ""
            issues.append(f"世界设定列表还没有登记完整{suffix}")
        named_details = []
        for relative in details:
            match = re.search(r'(?m)^name:\s*["\']?([^"\'\r\n]+)', content(relative))
            if match:
                named_details.append((relative, match.group(1).strip()))
        duplicate_names = sorted({
            name for _relative, name in named_details
            if sum(other_name == name for _other, other_name in named_details) > 1
        })
        if duplicate_names:
            issues.append(f"这些地点或设定存在重复档案：{'、'.join(duplicate_names)}")
        locations = [relative for relative in details if relative.startswith("worldbuilding/locations/")]
        if not locations:
            issues.append("还没有建立故事发生地点的资料")
        manifest = answers.get("outline_manifest") or {}
        all_world_text = "\n".join(content(relative) for relative in details)
        location_text = "\n".join(content(relative) for relative in locations)
        missing_world = [
            str(item.get("name") or "").strip()
            for item in manifest.get("world", []) if isinstance(item, dict)
            and str(item.get("name") or "").strip() not in all_world_text
        ]
        missing_locations = [
            str(item.get("name") or "").strip()
            for item in manifest.get("locations", []) if isinstance(item, dict)
            and str(item.get("name") or "").strip() not in location_text
        ]
        if missing_world:
            issues.append(f"这些世界设定还没有资料：{'、'.join(missing_world)}")
        if missing_locations:
            issues.append(f"这些故事地点还没有资料：{'、'.join(missing_locations)}")
        character_profiles = {
            path.stem: path.read_text(encoding="utf-8")
            for path in sorted((project.path / "characters").glob("*.md"))
            if path.name != "_index.md"
        }
        location_profiles = {
            Path(relative).stem: content(relative) for relative in locations
        }
        issues.extend(_location_reference_issues(
            character_profiles,
            location_profiles,
            reciprocal_repair_available=proposals is not None,
        ))
        return issues

    if skill_name == "plot-structure":
        arcs = paths("plot/arcs/*.md")
        issues = []
        if not content("plot/outline.md").strip():
            issues.append("正式大纲不存在")
        if not arcs:
            issues.append("还没有根据正式大纲建立主剧情线")
        registry = content("plot/_index.md")
        unregistered_arcs = [relative for relative in arcs if Path(relative).stem not in registry]
        if (not registry.strip() or unregistered_arcs) and not local_registry_rebuild_pending:
            issues.append("剧情结构列表还没有登记完整")
        timeline = content("plot/timeline.md")
        if len([line for line in timeline.splitlines() if "|" in line]) <= 2:
            issues.append("剧情时间线还是空的")
        questions = [
            relative for relative in paths("continuity/questions/*.md")
            if not relative.endswith("/_index.md")
        ]
        promises = [
            relative for relative in paths("continuity/promises/*.md")
            if not relative.endswith("/_index.md")
        ]
        manifest = answers.get("outline_manifest") or {}
        arc_text = "\n".join(content(relative) for relative in arcs)
        question_text = "\n".join(content(relative) for relative in questions)
        promise_text = "\n".join(content(relative) for relative in promises)

        def missing_items(key: str, haystack: str) -> list[str]:
            result = []
            for item in manifest.get(key, []):
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                evidence = str(item.get("evidence") or "").strip()
                if name and name not in haystack and evidence not in haystack:
                    result.append(name)
            return result

        missing_arcs = missing_items("plot_arcs", arc_text)
        missing_timeline = missing_items("timeline", timeline)
        missing_promises = missing_items("promises", promise_text)
        missing_questions = missing_items("questions", question_text)
        if missing_arcs:
            issues.append(f"这些剧情阶段还没有进入剧情结构：{'、'.join(missing_arcs)}")
        if missing_timeline:
            issues.append(f"时间线还缺少 {len(missing_timeline)} 个正式大纲事件")
        if missing_promises:
            issues.append(f"这些伏笔还没有登记：{'、'.join(missing_promises)}")
        if missing_questions:
            issues.append(f"这些未解问题还没有登记：{'、'.join(missing_questions)}")
        for relatives, index_path, label in (
            (questions, "continuity/questions/_index.md", "问题列表"),
            (promises, "continuity/promises/_index.md", "伏笔列表"),
        ):
            index = content(index_path)
            missing = [relative for relative in relatives if Path(relative).stem not in index]
            if missing and not local_registry_rebuild_pending:
                issues.append(f"{label}还没有登记完整：{', '.join(missing)}")
        return issues
    return []


class StoryCli:
    ALLOWED = ("reindex", "links", "validate", "wordcount")

    def __init__(self, project: Project, runner: Callable[[list[str]], str]) -> None:
        self.project = project
        self.runner = runner

    def run(self, command: str, arguments: list[str] | None = None) -> str:
        if command not in self.ALLOWED:
            raise ValueError(f"Story command not allowed: {command}")
        arguments = arguments or []
        if any(item.startswith(("/", "\\")) or ".." in PurePosixPath(item).parts for item in arguments):
            raise ValueError("Story command arguments must stay inside the project")
        return self.runner([command, ".", *arguments])


class SkillRuntimeToolbox:
    def __init__(self, db: Database, project: Project, execution_id: str,
                 contract: SkillContract, story_cli: StoryCli, bootstrap: bool = False,
                 answers: dict | None = None) -> None:
        self.db = db
        self.project = project
        self.execution_id = execution_id
        self.contract = contract
        self.story_cli = story_cli
        self.bootstrap = bootstrap
        self.answers = answers or {}
        self.awaiting_question: str | None = None

    def definitions(self) -> list[ToolDefinition]:
        object_schema = {"type": "object", "additionalProperties": False}
        tools = [
            ToolDefinition(name="read_story_file", description="Read one project story file", input_schema={**object_schema, "properties": {"relative_path": {"type": "string"}}, "required": ["relative_path"]}),
            ToolDefinition(name="list_story_entities", description="List story entities", input_schema={**object_schema, "properties": {"entity_type": {"type": "string", "enum": list(ENTITY_FOLDERS)}}, "required": ["entity_type"]}),
            ToolDefinition(name="request_user_input", description="Request missing structured input", input_schema={"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}),
            ToolDefinition(name="create_file_proposal", description="Propose a complete story file", input_schema={"type": "object", "properties": {"relative_path": {"type": "string"}, "content": {"type": "string"}, "facts": {"type": "object"}}, "required": ["relative_path", "content"]}),
            ToolDefinition(name="update_file_proposal", description="Propose replacement content for a story file", input_schema={"type": "object", "properties": {"relative_path": {"type": "string"}, "content": {"type": "string"}, "facts": {"type": "object"}}, "required": ["relative_path", "content"]}),
            ToolDefinition(name="update_registry_proposal", description="Propose complete registry content", input_schema={"type": "object", "properties": {"relative_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["relative_path", "content"]}),
            ToolDefinition(name="check_story_links", description="Run deterministic link checks", input_schema=object_schema),
            ToolDefinition(name="run_story_command", description="Run a maintenance subcommand in the existing project. Pass only the subcommand, never the 'story' executable name and never 'init'.", input_schema={"type": "object", "properties": {"command": {"type": "string", "enum": list(StoryCli.ALLOWED)}, "arguments": {"type": "array", "items": {"type": "string"}}}, "required": ["command"]}),
            ToolDefinition(name="complete_skill", description="Mark the Skill execution complete", input_schema={"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}),
        ]
        return [tool for tool in tools if not (self.bootstrap and tool.name == "request_user_input")]

    def execute(self, name: str, arguments: dict) -> dict:
        if name == "read_story_file":
            relative = self._normalize(str(arguments.get("relative_path", "")))
            retained = next((
                item for item in reversed(self.active_proposals())
                if item["relative_path"] == relative
            ), None)
            if retained:
                return {"relative_path": relative, "content": retained["content"][:20000],
                        "source": "retained_candidate"}
            path = self._safe_read_path(relative)
            return {"relative_path": path.relative_to(self.project.path).as_posix(),
                    "content": path.read_text(encoding="utf-8")[:20000],
                    "source": "project_file"}
        if name == "list_story_entities":
            entity = ENTITY_ALIASES.get(str(arguments.get("entity_type", "")).lower())
            folder = ENTITY_FOLDERS.get(entity or "")
            if not folder:
                raise ValueError(f"Unknown entity type; use one of: {', '.join(ENTITY_FOLDERS)}")
            return {"items": [path.stem for path in sorted((self.project.path / folder).glob("*.md")) if path.name != "_index.md"]}
        if name in {"create_file_proposal", "update_file_proposal", "update_registry_proposal"}:
            return self._propose(arguments)
        if name == "request_user_input":
            question = str(arguments.get("question", "")).strip()
            if not question:
                raise ValueError("Question is required")
            self.db.update_skill_execution(self.execution_id, "awaiting_user")
            self.awaiting_question = question
            return {"status": "awaiting_user", "question": question}
        if name == "check_story_links":
            return {"output": self.story_cli.run("links")}
        if name == "run_story_command":
            return {"output": self.story_cli.run(str(arguments.get("command", "")), arguments.get("arguments") or [])}
        if name == "complete_skill":
            proposals = self.active_proposals()
            if not proposals:
                raise ValueError("At least one file proposal is required before completion")
            if self.bootstrap:
                issues = initialization_stage_issues(
                    self.project, self.contract.skill_name, self.answers,
                    proposals,
                )
                if issues:
                    raise ValueError("初始化资料还没补齐：" + "；".join(issues))
            self.db.update_skill_execution(self.execution_id, "validating")
            return {"status": "validating", "summary": str(arguments.get("summary", ""))}
        raise ValueError(f"Unknown runtime tool: {name}")

    def _propose(self, arguments: dict) -> dict:
        relative = self._normalize(str(arguments.get("relative_path", "")))
        if not self.contract.permits(relative):
            raise ValueError(f"Path not allowed for {self.contract.skill_name}: {relative}")
        if self.bootstrap and relative == "plot/outline.md":
            raise ValueError("初始化不能改写已经确认的正式大纲")
        content = arguments.get("content")
        if not isinstance(content, str) or not content or len(content) > 200000:
            raise ValueError("Proposal content is required and must be bounded")
        if relative.endswith(".md") and not content.startswith("---\n"):
            raise ValueError("Story markdown proposals require YAML frontmatter")
        if relative.endswith(".md"):
            self._validate_frontmatter_syntax(content)
        if relative.startswith("characters/"):
            content = self._normalize_character_metadata(relative, content)
        if self.bootstrap:
            content = self._remove_bootstrap_references(relative, content)
        if relative.endswith("/_index.md") or relative in {"plot/timeline.md", "continuity/state.md"}:
            content = self._set_frontmatter_scalar(content, "story", self.project.id)
        canonical_types = {
            "chapters/_index.md": "chapter-registry",
            "characters/_index.md": "character-registry",
            "continuity/promises/_index.md": "promise-registry",
            "continuity/questions/_index.md": "question-registry",
            "glossary/_index.md": "glossary-registry",
            "plot/_index.md": "plot-registry",
            "scenes/_index.md": "scene-registry",
            "worldbuilding/_index.md": "world-registry",
            "plot/timeline.md": "timeline",
            "continuity/state.md": "continuity-state",
        }
        if relative in canonical_types:
            content = self._set_frontmatter_scalar(content, "type", canonical_types[relative])
        if relative == "plot/_index.md":
            content = self._set_frontmatter_scalar(content, "structure", "three-act")
        locks = {item["key"]: item["value"] for item in self.db.list_locks(self.project.id)}
        for key, proposed in (arguments.get("facts") or {}).items():
            if key in locks and locks[key] != proposed:
                self.db.save_change_request(uuid.uuid4().hex, self.project.id, key, locks[key], proposed,
                                            f"Proposed by {self.contract.skill_name}")
                raise PermissionError(f"Proposed fact conflicts with locked value: {key}")
        relative = self._canonical_entity_path(relative, content)
        proposal_id = uuid.uuid4().hex
        self.db.save_file_proposal(proposal_id, self.execution_id, relative, content, "pending")
        return {"proposal_id": proposal_id, "relative_path": relative, "status": "pending"}

    def apply(self) -> None:
        candidates = self.active_proposals()
        if not candidates:
            self.db.update_skill_execution(self.execution_id, "completed")
            return
        latest_by_path = {item["relative_path"]: item for item in candidates}
        proposals = list(latest_by_path.values())
        superseded = [
            item for item in candidates
            if item["id"] not in {proposal["id"] for proposal in proposals}
        ]
        files = list(dict.fromkeys([
            *(self.project.path / item["relative_path"] for item in proposals),
            *(path for path in self.project.path.rglob("_index.md")
              if path.relative_to(self.project.path).parts[0] != "snapshots"),
        ]))
        if self.bootstrap and self.contract.skill_name == "worldbuilding":
            files = list(dict.fromkeys([
                *files,
                *(self.project.path / "characters").glob("*.md"),
                *(self.project.path / "worldbuilding" / "locations").glob("*.md"),
            ]))
        snapshot = ProjectSnapshot.create(
            self.project.path, self.project.path / "snapshots" / f"skill-{self.execution_id}", files,
        )
        try:
            for proposal in proposals:
                atomic_write(self.project.path / proposal["relative_path"], proposal["content"])
            if self.bootstrap and self.contract.skill_name == "worldbuilding":
                _close_location_backlinks(self.project)
            commands = (
                ("reindex", "validate")
                if self.bootstrap and self.contract.skill_name == "character-management"
                else ("reindex", "links", "validate")
            )
            for command in commands:
                self.story_cli.run(command)
            if self.bootstrap:
                issues = initialization_stage_issues(
                    self.project, self.contract.skill_name, self.answers,
                )
                if issues:
                    raise RuntimeError("本地整理索引后资料仍不完整：" + "；".join(issues))
            for proposal in superseded:
                self.db.update_file_proposal(proposal["id"], "superseded")
            for proposal in proposals:
                self.db.update_file_proposal(proposal["id"], "applied")
            self.db.update_skill_execution(self.execution_id, "completed")
        except Exception as exc:
            snapshot.restore()
            for proposal in candidates:
                if proposal["status"] == "pending":
                    self.db.update_file_proposal(proposal["id"], "failed", str(exc))
            self.db.update_skill_execution(self.execution_id, "recoverable", str(exc))
            raise

    def finalize_on_tool_limit(self) -> str | None:
        proposals = self.active_proposals()
        if not proposals:
            return None
        if self.bootstrap and initialization_stage_issues(
                self.project, self.contract.skill_name, self.answers,
                proposals):
            return None
        self.db.update_skill_execution(self.execution_id, "validating")
        return "Generated proposals are ready for local validation"

    def finalize_after_route_error(self) -> str | None:
        return self.finalize_on_tool_limit()

    def active_proposals(self) -> list[dict]:
        return [
            item for item in self.db.list_file_proposals(self.execution_id)
            if item["status"] in ACTIVE_PROPOSAL_STATUSES
        ]

    def prepare_fallback(self, error: Exception) -> str:
        message = str(error)[:500]
        self.db.update_file_proposals_status(
            self.execution_id, "pending", "retained", message,
        )
        proposals = self.active_proposals()
        issues = initialization_stage_issues(
            self.project, self.contract.skill_name, self.answers, proposals,
        ) if self.bootstrap else []
        paths = [item["relative_path"] for item in proposals]
        return (
            "主模型已经生成的候选已保留，不能另建同一实体或重写无关文件。"
            f"已保留路径：{json.dumps(paths, ensure_ascii=False)}。"
            "只补齐或修复以下问题："
            + ("；".join(issues) if issues else "完成并核对现有候选")
        )

    def preserve_failure(self, error: Exception) -> dict:
        execution = self.db.get_skill_execution(self.execution_id)
        if not execution or execution["status"] != "completed":
            self.db.update_file_proposals_status(
                self.execution_id, "pending", "failed", str(error)[:1000],
            )
        recoverable = [
            item for item in self.db.list_file_proposals(self.execution_id)
            if item["status"] in {"pending", "retained", "failed"}
        ]
        paths_by_status = {
            status: {
                item["relative_path"] for item in recoverable if item["status"] == status
            }
            for status in ("pending", "retained", "failed")
        }
        candidate_copies = [{**item, "status": "pending"} for item in recoverable]
        missing_items = initialization_stage_issues(
            self.project, self.contract.skill_name, self.answers, candidate_copies,
        ) if self.bootstrap else []
        summary = self.db.file_proposal_summary(self.execution_id)
        summary.update({
            "retainable_count": len(paths_by_status["pending"] | paths_by_status["retained"]),
            "repair_count": len(paths_by_status["failed"]),
            "duplicate_count": len(recoverable) - len({
                item["relative_path"] for item in recoverable
            }),
            "missing_count": len(missing_items),
            "missing_items": missing_items,
            "formal_unchanged": True,
        })
        if not execution or execution["status"] != "completed":
            self.db.update_skill_execution(
                self.execution_id,
                "recoverable" if summary["recoverable_count"] else "failed",
                str(error),
            )
        return summary

    def _canonical_entity_path(self, relative: str, content: str) -> str:
        identity = self._entity_identity(relative, content)
        if identity is None:
            return relative
        for path in sorted(self.project.path.rglob("*.md")):
            candidate = path.relative_to(self.project.path).as_posix()
            if candidate.endswith("/_index.md") or not self.contract.permits(candidate):
                continue
            try:
                existing = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if self._entity_identity(candidate, existing) == identity:
                return candidate
        for proposal in self.active_proposals():
            if self._entity_identity(
                    proposal["relative_path"], proposal["content"]) == identity:
                return proposal["relative_path"]
        return relative

    @classmethod
    def _entity_identity(cls, relative: str, content: str) -> tuple[str, str] | None:
        path = PurePosixPath(relative)
        if path.name == "_index.md" or path.suffix != ".md":
            return None
        parts = path.parts
        if parts[:1] == ("characters",) and len(parts) == 2:
            kind = "character"
        elif parts[:2] == ("worldbuilding", "locations"):
            kind = "location"
        elif parts[:2] == ("worldbuilding", "factions"):
            kind = "faction"
        elif parts[:2] == ("worldbuilding", "systems"):
            kind = "system"
        elif parts[:2] == ("worldbuilding", "artifacts"):
            kind = "artifact"
        elif parts[:1] == ("worldbuilding",):
            kind = "worldbuilding"
        elif parts[:2] == ("plot", "arcs"):
            kind = "plot-arc"
        elif parts[:2] == ("continuity", "promises"):
            kind = "promise"
        elif parts[:2] == ("continuity", "questions"):
            kind = "question"
        else:
            return None
        match = re.match(r"^---\n([\s\S]*?)\n---", content)
        if not match:
            return None
        fields = {
            key: value.strip().strip("\"'")
            for key, value in re.findall(
                r"(?m)^(name|title):\s*([^\r\n]+)$", match.group(1),
            )
        }
        name = fields.get("name") or fields.get("title") or ""
        normalized = re.sub(r"[\W_]+", "", name, flags=re.UNICODE).casefold()
        return (kind, normalized) if normalized else None

    def _safe_read_path(self, relative_path: str) -> Path:
        relative = self._normalize(relative_path)
        path = (self.project.path / relative).resolve()
        if not path.is_relative_to(self.project.path.resolve()) or not path.is_file():
            raise ValueError("Story file not found or outside project")
        if path.suffix not in {".md", ".json"}:
            raise ValueError("Story file type is not readable")
        return path

    @staticmethod
    def _normalize(value: str) -> str:
        if not value or "\\" in value:
            raise ValueError("Path not allowed")
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("Path not allowed")
        return pure.as_posix()

    @staticmethod
    def _set_frontmatter_scalar(content: str, key: str, value: str) -> str:
        match = re.match(r"^---\n([\s\S]*?)\n---", content)
        if not match:
            raise ValueError("Story markdown proposals require YAML frontmatter")
        lines = match.group(1).splitlines()
        replacement = f"{key}: {value}"
        for index, line in enumerate(lines):
            if line.startswith(f"{key}:"):
                lines[index] = replacement
                break
        else:
            lines.append(replacement)
        return f"---\n{'\n'.join(lines)}\n---{content[match.end():]}"

    @staticmethod
    def _validate_frontmatter_syntax(content: str) -> None:
        match = re.match(r"^---\n([\s\S]*?)\n---", content)
        if not match:
            raise ValueError("Story markdown proposals require YAML frontmatter")
        allowed = (
            re.compile(r"^[A-Za-z0-9_-]+:(?:\s*.*)?$"),
            re.compile(r"^  -(?:\s+.*)?$"),
            re.compile(r"^    [A-Za-z0-9_-]+:\s*.*$"),
        )
        for line in match.group(1).splitlines():
            if line.strip() and not line.lstrip().startswith("#") and not any(pattern.match(line) for pattern in allowed):
                raise ValueError(f"Unsupported frontmatter line: {line}")

    @staticmethod
    def _normalize_character_metadata(relative: str, content: str) -> str:
        if relative.endswith("/_index.md"):
            return re.sub(
                r"(?m)^(\|\s*[^|\r\n]+\|\s*)counterpart(\s*\|)",
                r"\1deuteragonist\2", content,
            )
        match = re.match(r"^---\n([\s\S]*?)\n---", content)
        if not match:
            return content
        frontmatter = re.sub(
            r"(?m)^role:\s*[\"']?counterpart[\"']?\s*$",
            "role: deuteragonist", match.group(1),
        )

        def clean_aliases(block: re.Match) -> str:
            values = []
            for raw in re.findall(r"(?m)^[ \t]+-[ \t]*(.*)$", block.group("items")):
                value = raw.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1].strip()
                if value and value.casefold() not in {"null", "~"} and value not in values:
                    values.append(value)
            if not values:
                return ""
            return "aliases:\n" + "".join(
                f"  - {json.dumps(value, ensure_ascii=False)}\n" for value in values
            )

        frontmatter = re.sub(
            r"(?ms)^aliases:[ \t]*\n(?P<items>(?:[ \t]+-[^\r\n]*(?:\r?\n|$))*)",
            clean_aliases, frontmatter,
        )
        return f"---\n{frontmatter}\n---{content[match.end():]}"

    def _remove_bootstrap_references(self, relative: str, content: str) -> str:
        fields: set[str] = set()
        if relative.startswith("characters/") and not relative.endswith("/_index.md"):
            fields = {"died-in"}
        elif relative.startswith("continuity/promises/"):
            fields = {"planted", "payoff"}
        elif relative.startswith("continuity/questions/"):
            fields = {"introduced", "resolved"}
        cleaned = self._remove_frontmatter_fields(content, fields) if fields else content

        def keep_existing_chapter(match: re.Match) -> str:
            target = match.group("target").split("#", 1)[0]
            source_folder = (self.project.path / relative).parent
            resolved = (source_folder / Path(target)).resolve()
            if resolved.is_relative_to(self.project.path.resolve()) and resolved.is_file():
                return match.group(0)
            return match.group("label")

        return re.sub(
            r"\[(?P<label>[^]]+)]\((?P<target>(?:\.\.?/)*chapters/[^)#]+\.md(?:#[^)]*)?)\)",
            keep_existing_chapter,
            cleaned,
        )

    @staticmethod
    def _remove_frontmatter_fields(content: str, fields: set[str]) -> str:
        match = re.match(r"^---\n([\s\S]*?)\n---", content)
        if not match:
            return content
        lines = match.group(1).splitlines()
        kept = []
        skipping = False
        for line in lines:
            top_level = re.match(r"^([A-Za-z0-9_-]+):", line)
            if top_level:
                skipping = top_level.group(1) in fields
            if not skipping:
                kept.append(line)
        return f"---\n{'\n'.join(kept)}\n---{content[match.end():]}"


class SkillRuntimeService:
    def __init__(self, db: Database, projects: ProjectStore, gateway: ModelGateway,
                 skills: SkillGate) -> None:
        self.db = db
        self.projects = projects
        self.gateway = gateway
        self.skills = skills

    async def run(self, project_id: str, skill_name: str, answers: dict,
                  bootstrap: bool = False) -> dict:
        project = self.projects.get(project_id)
        skill = self.skills.skills(project.path).get(skill_name)
        if skill is None:
            raise LookupError(f"Skill not found: {skill_name}")
        contract = SkillContract.for_skill(skill_name)
        if not contract.writable_patterns:
            raise PermissionError(f"Skill contract is not approved for file operations: {skill_name}")
        execution_id = uuid.uuid4().hex
        context_hash = initialization_context_hash(answers) if bootstrap else None
        recoverable = self.db.list_recoverable_skill_executions(
            project.id, skill.name, skill.content_hash, context_hash,
        ) if bootstrap else []
        self.db.create_skill_execution(
            execution_id, project.id, skill.name, skill.content_hash, "running",
            context_hash=context_hash,
        )
        resumed_from, resumed_paths = self._resume_proposals(
            execution_id, recoverable[0]["id"] if recoverable else None,
        )
        toolbox = SkillRuntimeToolbox(
            self.db, project, execution_id, contract,
            StoryCli(project, lambda command: self._run_story_cli(project, command)),
            bootstrap=bootstrap, answers=answers,
        )
        writable_paths = ", ".join(contract.writable_patterns)
        system = (
            "Execute the Skill using only the supplied runtime tools. Read existing story files, "
            "request input when essential, propose complete validated files, update registries, and "
            "call complete_skill. Never invent tool results or paths. The project structure already exists; "
            "do not initialize a new project. For run_story_command, pass only an allowed maintenance "
            "subcommand, never the 'story' executable name. If a tool returns an error, correct the call "
            "or use file proposals instead. Prefer supplied answers and existing indexes over exhaustive "
            "reads. Follow the supplied Skill references exactly; do not invent nested frontmatter fields. "
            "Confirmed learning context is optional guidance. It must never override the confirmed outline, "
            "locked requirements, confirmed facts, point of view, character identities, or existing canon. "
            "The supplied outline_manifest is a required checklist derived from exact outline evidence. "
            "Cover every listed item in the files owned by this Skill. Never attach one item's evidence or "
            "facts to a different person, place, arc, promise, or question. "
            "During initialization, never create or update plot/outline.md. "
            f"A completed run must create or update at least one project-root-relative file matching: "
            f"{writable_paths}. Never prefix a path with the project title, slug, or another folder. "
            + ("This is initial bootstrap: preserve supported relationships between proposed entities. "
               "Omit only chapter fields and links when those chapter files do not exist yet. " if bootstrap else "")
            + (("A previous attempt left recoverable candidate files. Read them before replacing them, "
                "keep all supported details, and only repair or complete what is missing. Retained paths: "
                + json.dumps(resumed_paths, ensure_ascii=False) + ". ") if resumed_paths else "")
            + (self._initialization_instruction(skill_name, answers) if bootstrap else "")
            + "Once the proposals are sufficient, call complete_skill immediately.\n\nSKILL:\n"
            + skill.instructions + self._reference_context(skill)
        )
        try:
            result = await self.gateway.complete_with_tools(
                "planning", system, json.dumps(answers, ensure_ascii=False), toolbox,
                fallback_context=lambda: json.dumps(answers, ensure_ascii=False), run_id=execution_id,
            )
            if result.receipt.get("execution_mode") != "native_tools":
                raise RuntimeError("Skill Runtime requires native Tool Calling; prompt fallback cannot write files")
            if toolbox.awaiting_question and not self.db.list_file_proposals(execution_id):
                return {"id": execution_id, "status": "awaiting_user",
                        "question": toolbox.awaiting_question, "summary": result.text, "proposals": []}
            if not self.db.list_file_proposals(execution_id):
                raise RuntimeError("Skill completed without file proposals")
            if bootstrap:
                issues = initialization_stage_issues(
                    project, skill_name, answers, toolbox.active_proposals(),
                )
                if issues:
                    raise RuntimeError("初始化资料还没补齐：" + "；".join(issues))
            toolbox.apply()
            if resumed_from:
                self.db.update_skill_execution(
                    resumed_from, "resumed", f"continued by {execution_id}",
                )
            return {"id": execution_id, "status": "completed", "summary": result.text,
                    "proposals": self.db.list_file_proposals(execution_id)}
        except asyncio.CancelledError as exc:
            toolbox.preserve_failure(exc)
            raise
        except Exception as exc:
            summary = toolbox.preserve_failure(exc)
            setattr(exc, "execution_id", execution_id)
            setattr(exc, "proposal_summary", summary)
            raise

    def _resume_proposals(
        self, execution_id: str, source_execution_id: str | None,
    ) -> tuple[str | None, list[str]]:
        if not source_execution_id:
            return None, []
        latest = {}
        for item in self.db.list_file_proposals(source_execution_id):
            if item["status"] in {"pending", "retained", "failed"}:
                latest[item["relative_path"]] = item
        for item in latest.values():
            status = "pending" if item["status"] == "failed" else "retained"
            self.db.save_file_proposal(
                uuid.uuid4().hex, execution_id, item["relative_path"], item["content"],
                status, item.get("error"),
            )
        paths = sorted(latest)
        return (source_execution_id, paths) if paths else (None, [])

    @staticmethod
    def _initialization_instruction(skill_name: str, answers: dict) -> str:
        expected = expected_initialization_characters(answers)
        instructions = {
            "story-init": (
                "Update root story.md and constraints.md from the supplied confirmed requirements. The project folders "
                "already exist; do not create a title-named wrapper directory. Include the confirmed title, "
                "genre, premise, target word count, point of view, and tone. Natural Chinese section headings "
                "are allowed; no fixed English heading is required. Copy every outline_manifest constraint "
                "into constraints.md without changing its meaning. "
            ),
            "character-management": (
                "Read the supplied confirmed outline. Create a complete profile for every main or key "
                "character, then update characters/_index.md and its Relationship Map. Do not stop after "
                "creating only the protagonist. Review existing profiles and correct facts that conflict "
                "with or are not supported by the confirmed outline. Character file roles must be one of "
                "protagonist, antagonist, supporting, minor, narrator, or deuteragonist; use deuteragonist "
                "for an outline counterpart. Omit aliases when the character has no non-empty alias. "
                "Use at most one relationship entry per target character and give the other profile the exact "
                "inverse type; describe any additional relationship dynamic in body text. Preserve supported "
                "future location references even when worldbuilding has not created those files yet. "
            ),
            "worldbuilding": (
                "Read the supplied confirmed outline. Create every location, rule, faction, system, and "
                "important object that later writing needs, then update worldbuilding/_index.md. Preserve "
                "confirmed names and facts, but freely add supporting places, people, and concrete details "
                "when they enrich the story without contradicting the confirmed outline. Never create two "
                "files for the same named place or entity; update and reuse an existing file instead. Read "
                "existing character location references as a required checklist: create each referenced "
                "location id and include the matching character ids in notable-characters backlinks. "
            ),
            "plot-structure": (
                "Treat plot/outline.md as immutable authority. Build supporting arcs, the plot registry, "
                "timeline, promises, and open questions from it without replacing the confirmed outline. "
                "Chapter files do not exist during initialization. Keep introduced, resolved, planted, "
                "payoff, and died-in chapter fields empty; describe planned chapter positions only in body text. "
            ),
        }
        detail = instructions.get(skill_name, "")
        if skill_name == "character-management" and expected:
            detail += "The confirmed main-character list is: " + ", ".join(expected) + ". "
        return detail

    def _run_story_cli(self, project: Project, command: list[str]) -> str:
        skill = self.skills.skills(project.path).get("story-maintenance")
        if not skill or not skill.executable:
            raise RuntimeError("Executable story-maintenance Skill is required")
        argv = ["scripts/story.js", *command]
        story_path = project.path / "story.md"
        original_story = story_path.read_text(encoding="utf-8")
        compatible_story = SkillRuntimeToolbox._set_frontmatter_scalar(
            original_story, "title", project.id,
        )
        atomic_write(story_path, compatible_story)
        try:
            result = self.skills.run_required(
                "skill-runtime", ["story-maintenance"], {"story-maintenance": argv},
                project.path, project.path,
            )
        finally:
            atomic_write(story_path, original_story)
        return result.receipts[0].output

    @staticmethod
    def _reference_context(skill, limit: int = 20000) -> str:
        reference_root = skill.path / "references"
        if not reference_root.is_dir():
            return ""
        parts = []
        used = 0
        for path in sorted(reference_root.rglob("*.md")):
            content = path.read_text(encoding="utf-8")
            block = f"\n\nREFERENCE: {path.relative_to(skill.path).as_posix()}\n{content}"
            if used + len(block) > limit:
                break
            parts.append(block)
            used += len(block)
        return "".join(parts)
